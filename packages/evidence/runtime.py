"""Explainable evidence retrieval and wake-recovery helpers."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Mapping

from packages.contracts.runtime import (
    EmbeddingIndexInvalidation,
    EmbeddingIndexPolicy,
    EmbeddingIndexRebuildPlan,
    EvidenceCandidate,
    EvidenceRetrievalRequest,
    EvidenceRetrievalResult,
    RecallEvidence,
    RecallReason,
    RecallReasons,
    StepReplayRecord,
    StructuredTurnSlot,
)
from packages.embeddings import (
    ELEPHANT_EMBED_MODEL_ID,
    ELEPHANT_EMBED_ONLINE_DIMENSIONS,
    EmbeddingPreloadEntry,
    EmbeddingService,
    build_default_embedding_service,
    cosine_similarity,
    embedding_runtime_is_loaded,
    embedding_mode_for_latency,
    resolve_embedding_dimensions,
)
from packages.semantic_index import HybridSemanticSearcher, SemanticSearchQuery
from packages.storage import RuntimeStorageRepository
from .state_focus_support import (
    focus_work_item_ids,
    state_focus_scope_hints,
    state_focus_score_adjustments,
)

if TYPE_CHECKING:
    from .recall_runtime import StepEvidenceStore
    from .semantic_index_factory import SemanticIndexBundle


_LEXICAL_INDEX_VERSION = "fts5-evidence-v1"
_EMBEDDING_INDEX_VERSION = f"{ELEPHANT_EMBED_MODEL_ID}@2026-04"
_EVIDENCE_EMBED_TEXT_LIMIT = 8_192
_EVIDENCE_BACKFILL_TOP_K = 8
EVIDENCE_QUERY_TARGET = "evidence-query"
EVIDENCE_CORPUS_TARGET = "evidence"
_CONTINUITY_QUERY_TOKENS = frozenset(
    {
        "continue",
        "continuity",
        "handoff",
        "left",
        "next",
        "pick",
        "recover",
        "recovery",
        "resume",
        "resumed",
        "step",
        "where",
    }
)


def evidence_query_cache_key(query: str, *, latency_mode: str = "fast") -> str:
    """Stable query-vector cache key for normal retrieval."""

    normalized = " ".join(str(query or "").split()).strip().lower()
    if not normalized:
        return ""
    dims = resolve_embedding_dimensions(latency_mode)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"evidence-query:{dims}d:{digest}"


_SEMANTIC_RECALL_SCORE_SCALE = 100.0
_SEMANTIC_MEMORY_ENTRY_INACTIVE_STATES = frozenset(
    {"deleted", "superseded", "retired", "inactive", "archived", "rejected"}
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _tokenize(text: str) -> set[str]:
    return {token for token in re.findall(r"[A-Za-z0-9_]+", text.lower()) if token}


def _query_episode_ids(
    repository: RuntimeStorageRepository,
    *,
    personal_model_id: str | None = None,
    elephant_id: str | None = None,
) -> tuple[str, ...]:
    if not personal_model_id and not elephant_id:
        return ()
    episodes = repository.list_episodes()
    episode_ids: list[str] = []
    for episode in sorted(
        episodes,
        key=lambda item: (
            item.metadata.get("updated_at", ""),
            (item.ended_at or item.started_at).isoformat(),
            item.episode_id,
        ),
        reverse=True,
    ):
        if personal_model_id and episode.personal_model_id != personal_model_id:
            continue
        if elephant_id:
            state = repository.load_state(episode.state_id)
            if state is None or state.elephant_id != elephant_id:
                continue
        episode_ids.append(episode.episode_id)
    return tuple(dict.fromkeys(episode_ids))


@dataclass(frozen=True, slots=True)
class _ResolvedScope:
    episode_ids: tuple[str, ...]
    opened_scopes: tuple[str, ...]
    scope_reason: str
    lineage_episode_ids: tuple[str, ...]
    elephant_episode_ids: tuple[str, ...]
    personal_model_episode_ids: tuple[str, ...]


_REPLAY_SLOT_NAMES = ("observation", "reasoning", "action", "outcome")
_REPLAY_SLOT_LABELS = {
    "observation": "observation",
    "reasoning": "reasoning",
    "action": "action",
    "outcome": "outcome",
}
_REPLAY_DETAIL_RANK = {
    "summary_only": 0,
    "episode_summary": 1,
    "structured_summary": 2,
    "structured": 3,
    "raw_turn": 4,
    "raw_trace": 5,
}


def _tuple_from_metadata(value: object) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if str(item))
    if value is None:
        return ()
    cleaned = str(value).strip()
    return (cleaned,) if cleaned else ()


def _record_search_text(record: RecallEvidence, *, structured_text: str = "") -> str:
    return "\n".join(part for part in (record.content, structured_text) if part)


def _embedding_text(value: str, *, max_chars: int = _EVIDENCE_EMBED_TEXT_LIMIT) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip()


def _record_embedding_text(record: RecallEvidence, *, structured_text: str | None = None) -> str:
    if structured_text is None:
        structured_turn = _structured_turn_from_record(record)
        structured_text = (
            _replay_text(structured_turn, selected_slots=_REPLAY_SLOT_NAMES) if structured_turn is not None else ""
        )
    search_text = _record_search_text(record, structured_text=structured_text) or record.content
    return _embedding_text(search_text)


def _evidence_cache_key(record: RecallEvidence, *, search_text: str) -> str:
    created_at = record.created_at.isoformat() if record.created_at is not None else ""
    digest = hashlib.sha256(search_text.encode("utf-8")).hexdigest()[:16]
    return f"{record.evidence_id}:{created_at}:{digest}"


def _evidence_preload_entry(record: RecallEvidence, *, structured_text: str = "") -> EmbeddingPreloadEntry:
    search_text = _record_embedding_text(record, structured_text=structured_text or None)
    return EmbeddingPreloadEntry(
        cache_key=_evidence_cache_key(record, search_text=search_text),
        text=search_text or record.content,
        metadata={
            "evidence_id": record.evidence_id,
            "evidence_kind": record.kind,
            "episode_id": record.episode_id,
        },
    )


def _structured_slot_from_metadata(value: object) -> StructuredTurnSlot:
    if not isinstance(value, dict):
        return StructuredTurnSlot()
    return StructuredTurnSlot(
        summary=str(value.get("summary", "")),
        detail=_tuple_from_metadata(value.get("detail")),
        compression=str(value.get("compression", "structured")),
        provenance=str(value.get("provenance", "")),
        source_refs=_tuple_from_metadata(value.get("source_refs")),
        linkage_refs=_tuple_from_metadata(value.get("linkage_refs")),
    )


def _structured_turn_from_record(record: RecallEvidence) -> StepReplayRecord | None:
    if record.kind != "structured_turn":
        return None
    payload = record.metadata.get("structured_turn")
    if not isinstance(payload, dict):
        return None
    return StepReplayRecord(
        turn_id=str(payload.get("turn_id", record.evidence_id)),
        episode_id=str(payload.get("episode_id", record.episode_id)),
        source=str(payload.get("source", "runtime")),
        observation=_structured_slot_from_metadata(payload.get("observation")),
        reasoning=_structured_slot_from_metadata(payload.get("reasoning")),
        action=_structured_slot_from_metadata(payload.get("action")),
        outcome=_structured_slot_from_metadata(payload.get("outcome")),
        personal_model_id=(
            str(payload.get("personal_model_id")) if payload.get("personal_model_id") is not None else None
        ),
        elephant_id=str(payload.get("elephant_id")) if payload.get("elephant_id") is not None else None,
        source_event_id=str(payload.get("source_event_id"))
        if payload.get("source_event_id") is not None
        else record.source_id,
        reasoning_availability=str(payload.get("reasoning_availability", "summary_only")),
        reasoning_provenance=str(payload.get("reasoning_provenance", "runtime.decision_summary")),
        compression_tier=str(payload.get("compression_tier", "raw_turn")),
        work_item_ids=_tuple_from_metadata(payload.get("work_item_ids") or record.work_item_ids),
        source_turn_ids=_tuple_from_metadata(payload.get("source_turn_ids")),
        correction_evidence_ids=_tuple_from_metadata(payload.get("correction_evidence_ids")),
        artifact_ids=_tuple_from_metadata(payload.get("artifact_ids")),
        created_at=record.created_at,
    )


def parse_step_replay_record(record: RecallEvidence) -> StepReplayRecord | None:
    """Parse Step replay metadata from a recall evidence record."""

    return _structured_turn_from_record(record)


def _normalize_target_slots(target_slots: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(slot.strip().lower() for slot in target_slots if slot.strip().lower() in _REPLAY_SLOT_NAMES)
    )


def _detail_rank(compression: str) -> int:
    return _REPLAY_DETAIL_RANK.get(compression.strip().lower(), _REPLAY_DETAIL_RANK["structured_summary"])


def _project_slot(
    slot: StructuredTurnSlot,
    *,
    max_compression: str,
) -> tuple[StructuredTurnSlot, bool]:
    allowed_rank = _detail_rank(max_compression)
    slot_rank = _detail_rank(slot.compression)
    if slot_rank <= allowed_rank:
        return slot, False
    return (
        StructuredTurnSlot(
            summary=slot.summary,
            detail=(),
            compression=max_compression,
            provenance=slot.provenance,
            source_refs=slot.source_refs,
            linkage_refs=slot.linkage_refs,
        ),
        True,
    )


def _selected_replay_slots(
    request: EvidenceRetrievalRequest,
    turn: StepReplayRecord | None,
) -> tuple[str, ...]:
    explicit = _normalize_target_slots(request.target_slots)
    if explicit:
        return explicit
    if turn is None or request.replay_mode == "off":
        return ()
    return tuple(
        slot_name
        for slot_name in _REPLAY_SLOT_NAMES
        if getattr(turn, slot_name).summary or getattr(turn, slot_name).detail
    )


def _project_replay_record(
    turn: StepReplayRecord,
    *,
    selected_slots: tuple[str, ...],
    max_compression: str,
) -> tuple[StepReplayRecord, tuple[str, ...]]:
    slots = set(selected_slots)
    degraded_slots: list[str] = []

    def project(slot_name: str) -> StructuredTurnSlot:
        slot = getattr(turn, slot_name)
        if slot_name not in slots:
            return StructuredTurnSlot()
        projected, degraded = _project_slot(slot, max_compression=max_compression)
        if degraded:
            degraded_slots.append(slot_name)
        return projected

    return (
        StepReplayRecord(
            turn_id=turn.turn_id,
            episode_id=turn.episode_id,
            source=turn.source,
            observation=project("observation"),
            reasoning=project("reasoning"),
            action=project("action"),
            outcome=project("outcome"),
            personal_model_id=turn.personal_model_id,
            elephant_id=turn.elephant_id,
            source_event_id=turn.source_event_id,
            reasoning_availability=turn.reasoning_availability,
            reasoning_provenance=turn.reasoning_provenance,
            compression_tier=turn.compression_tier,
            work_item_ids=turn.work_item_ids,
            source_turn_ids=turn.source_turn_ids,
            correction_evidence_ids=turn.correction_evidence_ids,
            artifact_ids=turn.artifact_ids,
            created_at=turn.created_at,
        ),
        tuple(dict.fromkeys(degraded_slots)),
    )


def _slot_text(slot_name: str, slot: StructuredTurnSlot) -> tuple[str, ...]:
    label = _REPLAY_SLOT_LABELS.get(slot_name, slot_name)
    lines: list[str] = []
    if slot.summary:
        lines.append(f"{label}: {slot.summary}")
    lines.extend(slot.detail)
    return tuple(lines)


def _replay_text(turn: StepReplayRecord, *, selected_slots: tuple[str, ...]) -> str:
    lines: list[str] = []
    for slot_name in selected_slots:
        lines.extend(_slot_text(slot_name, getattr(turn, slot_name)))
    return "\n".join(line for line in lines if line)


def _replay_summary(turn: StepReplayRecord, *, selected_slots: tuple[str, ...]) -> str:
    slot_summary = ", ".join(selected_slots) or "structured evidence"
    work_summary = ", ".join(turn.work_item_ids[:2]) or "the active thread"
    if turn.compression_tier == "episode_summary" or len(turn.source_turn_ids) > 1:
        boundary = f"episode replay across {len(turn.source_turn_ids) or 1} turn(s)"
    else:
        boundary = "turn replay"
    selected_compressions = tuple(
        dict.fromkeys(
            getattr(turn, slot_name).compression
            for slot_name in selected_slots
            if getattr(turn, slot_name).summary or getattr(turn, slot_name).detail
        )
    )
    compression = ",".join(selected_compressions) if selected_compressions else turn.compression_tier
    return (
        f"{boundary} for {work_summary}; slots={slot_summary}; "
        f"compression={compression}; reasoning={turn.reasoning_availability}"
    )


class DefaultEvidenceRetriever:
    """Cache-first evidence retriever.

    Semantic recall is served by the durable `SemanticIndexBundle` built once
    at runtime-create time. Producer-side writers (episode-exit indexer,
    personal-model record indexer, skill indexer) already populate that
    bundle's `semantic_index_entries` — so we query the persistent backing
    store directly instead of rebuilding an ephemeral sqlite-vec database
    for every single `retrieve()` call.

    When no bundle is wired (tests, minimal embedders), semantic recall is
    disabled and retrieval degrades to the deterministic lexical + graph +
    continuity scoring already implemented in `_candidate_for_record`. No
    tempdir sqlite, no per-turn reindex, no hidden O(N) work.
    """

    def __init__(
        self,
        store: "StepEvidenceStore",
        repository: RuntimeStorageRepository | None = None,
        *,
        embedding_service: EmbeddingService | None = None,
        semantic_bundle: "SemanticIndexBundle | None" = None,
    ) -> None:
        self.store = store
        self.repository = repository
        self.embedding_service = embedding_service or build_default_embedding_service()
        self.semantic_bundle = semantic_bundle

    def retrieve(self, request: EvidenceRetrievalRequest) -> EvidenceRetrievalResult:
        resolved_scope = self._resolve_scope(request)
        scope_set = set(resolved_scope.episode_ids)
        query_tokens = _tokenize(request.query)
        dims = resolve_embedding_dimensions(request.latency_mode)
        episode_scope_records = tuple(
            record
            for record in self.store.list(include_inactive=request.include_inactive)
            if record.episode_id in scope_set
        )
        scope_records = tuple({record.evidence_id: record for record in episode_scope_records}.values())
        query_vector: tuple[float, ...] = ()
        embeddings_allowed = bool(request.allow_embeddings)
        if not embeddings_allowed:
            vector_cache_status = "disabled"
        else:
            health = getattr(self.embedding_service, "health", None)
            if callable(health):
                try:
                    embeddings_allowed = embedding_runtime_is_loaded(health())
                except Exception:
                    embeddings_allowed = False
            else:
                # No health surface means we cannot confirm the runtime is
                # loaded — treat as unavailable rather than eagerly enqueuing
                # backfill against an embedding service we cannot probe.
                embeddings_allowed = False
            vector_cache_status = "unavailable" if not embeddings_allowed else ""
        if embeddings_allowed:
            # Cache-first: never synchronously invoke a local embedding model on
            # the hot path. Read the shared matryoshka cache; when absent, queue
            # a best-effort backfill so the next turn is steady and fall through
            # to the deterministic lexical + graph + continuity scoring already
            # implemented in `_candidate_for_record`.
            query_vector, vector_cache_status = self._resolve_query_vector(
                request,
                dims=dims,
            )
        lexical_candidates: list[EvidenceCandidate] = []
        for record in scope_records:
            candidate = self._candidate_for_record(
                request,
                record,
                resolved_scope=resolved_scope,
                query_tokens=query_tokens,
                query_vector=query_vector,
                dims=dims,
            )
            if candidate is not None:
                lexical_candidates.append(candidate)
        semantic_candidates = self._semantic_candidates(
            request,
            scope_records=episode_scope_records,
            dims=dims,
            query_vector=query_vector,
            embeddings_allowed=embeddings_allowed,
        )
        candidates = self._merge_candidate_sets(
            semantic_candidates=semantic_candidates,
            lexical_candidates=tuple(lexical_candidates),
        )
        selected = tuple(candidates[: request.limit])
        self._queue_candidate_backfill(
            request=request,
            candidates=tuple(candidates[: max(_EVIDENCE_BACKFILL_TOP_K, request.limit * 2)]),
            query_vector=query_vector,
            embeddings_allowed=embeddings_allowed,
        )
        recall_reasons = RecallReasons(
            opened_scopes=resolved_scope.opened_scopes,
            evidence_ids=tuple(candidate.evidence_id for candidate in selected),
            scope_reason=resolved_scope.scope_reason,
            rerank_summary=self._rerank_summary(selected),
            reasons=tuple(reason for candidate in selected for reason in candidate.reasons[:3]),
            vector_cache_status=vector_cache_status,
        )
        return EvidenceRetrievalResult(
            request=request,
            scope_episode_ids=resolved_scope.episode_ids,
            scope_reason=resolved_scope.scope_reason,
            candidates=selected,
            recall_reasons=recall_reasons,
            index_policy=build_embedding_index_policy(self.store),
        )

    def _resolve_scope(self, request: EvidenceRetrievalRequest) -> _ResolvedScope:
        requested_scopes = tuple(
            dict.fromkeys(
                (
                    *(scope for scope in request.scopes if scope),
                    *state_focus_scope_hints(request),
                )
            )
        ) or ("episode",)
        episode_ids: list[str] = [request.episode_id]
        opened_scopes: list[str] = []

        lineage_episode_ids = tuple(
            dict.fromkeys(request.lineage_episode_ids or self._lineage_episode_ids(request.episode_id))
        )
        elephant_episode_ids = (
            _query_episode_ids(self.repository, elephant_id=request.elephant_id)
            if self.repository is not None and request.elephant_id is not None and "elephant" in requested_scopes
            else ()
        )
        personal_model_episode_ids = (
            _query_episode_ids(self.repository, personal_model_id=request.personal_model_id)
            if self.repository is not None and request.personal_model_id and "personal_model" in requested_scopes
            else ()
        )

        for scope in requested_scopes:
            if scope == "turn":
                opened_scopes.append("turn")
            elif scope == "episode":
                opened_scopes.append("episode")
            elif scope == "lineage":
                opened_scopes.append("lineage")
                episode_ids.extend(lineage_episode_ids)
            elif scope == "elephant" and elephant_episode_ids:
                opened_scopes.append("elephant")
                episode_ids.extend(elephant_episode_ids)
            elif scope == "personal_model" and personal_model_episode_ids:
                opened_scopes.append("personal_model")
                episode_ids.extend(personal_model_episode_ids)

        resolved_episode_ids = tuple(dict.fromkeys(episode_ids))
        explicit_reason = request.scope_reason.strip()
        if explicit_reason:
            scope_reason = explicit_reason
        else:
            scope_reason = self._default_scope_reason(
                request,
                opened_scopes=tuple(opened_scopes),
                resolved_episode_ids=resolved_episode_ids,
            )
        return _ResolvedScope(
            episode_ids=resolved_episode_ids,
            opened_scopes=tuple(opened_scopes) or ("episode",),
            scope_reason=scope_reason,
            lineage_episode_ids=lineage_episode_ids,
            elephant_episode_ids=elephant_episode_ids,
            personal_model_episode_ids=personal_model_episode_ids,
        )

    def _resolve_query_vector(
        self,
        request: EvidenceRetrievalRequest,
        *,
        dims: int,
    ) -> tuple[tuple[float, ...], str]:
        """Cache-first lookup for the query vector.

        Returns `(values, status)`. Never synchronously embeds on the hot path.
        On a miss we enqueue the query for background backfill so the next
        retrieval finds it steady, and degrade to lexical + graph + continuity
        scoring for this call.
        """

        query = request.query
        normalized = " ".join(str(query or "").split()).strip()
        if not normalized:
            return (), ""
        cached_vector = getattr(self.embedding_service, "cached_vector", None)
        if not callable(cached_vector):
            return (), "unavailable"
        cache_key = evidence_query_cache_key(normalized, latency_mode=request.latency_mode)
        if not cache_key:
            return (), ""
        try:
            cached = cached_vector(
                target=EVIDENCE_QUERY_TARGET,
                cache_key=cache_key,
                dimensions=dims,
            )
        except Exception:
            cached = None
        if cached is not None:
            values = tuple(getattr(cached, "values", ()) or ())
            if values:
                return values, "hit"
        # Cache miss: enqueue a best-effort backfill for the next turn.
        queue_status = "miss-backfilled"
        pending_vector = getattr(self.embedding_service, "pending_vector", None)
        if callable(pending_vector):
            try:
                if pending_vector(
                    target=EVIDENCE_QUERY_TARGET,
                    cache_key=cache_key,
                    dimensions=dims,
                ):
                    queue_status = "pending"
            except Exception:
                pass
        queue_backfill = getattr(self.embedding_service, "queue_backfill", None)
        if callable(queue_backfill):
            try:
                queue_backfill(
                    target=EVIDENCE_QUERY_TARGET,
                    entries=(
                        EmbeddingPreloadEntry(
                            cache_key=cache_key,
                            text=normalized,
                            metadata={
                                "surface": "evidence.retrieve",
                                "kind": "query",
                                "latency_mode": request.latency_mode,
                            },
                        ),
                    ),
                    latency_mode=request.latency_mode,
                )
            except Exception:
                pass
        return (), queue_status

    def _queue_candidate_backfill(
        self,
        *,
        request: EvidenceRetrievalRequest,
        candidates: tuple[EvidenceCandidate, ...],
        query_vector: tuple[float, ...],
        embeddings_allowed: bool = True,
    ) -> None:
        if not candidates or not embeddings_allowed:
            return
        # Always steady the corpus vectors, even on a cold-query miss — the next
        # turn's cached_vector() lookup benefits and the per-turn work is
        # bounded by `_EVIDENCE_BACKFILL_TOP_K`.
        queue_backfill = getattr(self.embedding_service, "queue_backfill", None)
        if not callable(queue_backfill):
            return
        try:
            queue_backfill(
                target=EVIDENCE_CORPUS_TARGET,
                entries=tuple(_evidence_preload_entry(candidate.evidence) for candidate in candidates),
                latency_mode=request.latency_mode,
            )
        except Exception:
            return

    def _semantic_candidates(
        self,
        request: EvidenceRetrievalRequest,
        *,
        scope_records: tuple[RecallEvidence, ...],
        dims: int,
        query_vector: tuple[float, ...],
        embeddings_allowed: bool,
    ) -> tuple[EvidenceCandidate, ...]:
        """Hybrid semantic + lexical recall against the durable bundle.

        When the runtime wired a `SemanticIndexBundle` we issue a single
        `HybridSemanticSearcher.search` call per owner scope against the
        persistent sqlite-vec backing store. Producer-side writers already
        populated those scopes (episode-exit indexer, personal-model record
        indexer, skill indexer), so recall sees exactly the rows the system
        committed — no tempdir rebuild, no O(N) per-turn reindex.

        When no bundle is wired, semantic recall is disabled and the caller
        degrades to lexical + graph + continuity scoring already implemented
        in `_candidate_for_record`. That is the same graceful path query-time
        skill re-rank uses when the cache is cold.
        """

        if self.semantic_bundle is None:
            return ()
        if self.repository is None or not request.query.strip():
            return ()

        state_scope_id = self._semantic_state_scope_id(request)
        state_records: dict[str, RecallEvidence] = {}
        personal_model_records: dict[str, RecallEvidence] = {}
        for evidence in scope_records:
            state_records[evidence.evidence_id] = evidence

        searcher = self.semantic_bundle.searcher
        candidates: list[EvidenceCandidate] = []
        if state_records:
            candidates.extend(
                self._semantic_scope_candidates(
                    request,
                    owner_scope="state",
                    state_scope_id=state_scope_id,
                    personal_model_id=request.personal_model_id,
                    recall_evidence_by_source_id=state_records,
                    dims=dims,
                    query_vector=query_vector,
                    searcher=searcher,
                )
            )
        candidates.extend(
            self._semantic_scope_candidates(
                request,
                owner_scope="personal_model",
                state_scope_id=state_scope_id,
                personal_model_id=request.personal_model_id,
                recall_evidence_by_source_id=personal_model_records,
                dims=dims,
                query_vector=query_vector,
                searcher=searcher,
            )
        )
        return self._merge_candidate_sets(
            semantic_candidates=tuple(candidates),
            lexical_candidates=(),
        )

    def _semantic_scope_candidates(
        self,
        request: EvidenceRetrievalRequest,
        *,
        owner_scope: str,
        state_scope_id: str,
        personal_model_id: str,
        recall_evidence_by_source_id: Mapping[str, RecallEvidence],
        dims: int,
        query_vector: tuple[float, ...],
        searcher: HybridSemanticSearcher,
    ) -> tuple[EvidenceCandidate, ...]:
        query_kwargs: dict[str, object] = {
            "text": request.query,
            "owner_scope": owner_scope,
            "limit": max(request.limit * 3, len(recall_evidence_by_source_id), 1),
        }
        if query_vector:
            query_kwargs["vector"] = query_vector
            query_kwargs["dimensions"] = dims
        if owner_scope == "state":
            query_kwargs["state_id"] = state_scope_id
        else:
            query_kwargs["personal_model_id"] = personal_model_id
        try:
            matches = searcher.search(SemanticSearchQuery(**query_kwargs))
        except Exception:
            return ()
        return tuple(
            self._semantic_candidate_from_match(
                evidence=recall_evidence_by_source_id.get(match.document.source_id)
                or self._recall_evidence_from_semantic_match(request, match),
                match=match,
                owner_scope=owner_scope,
            )
            for match in matches
        )

    def _recall_evidence_from_semantic_match(self, request: EvidenceRetrievalRequest, match) -> RecallEvidence:
        document = match.document
        metadata = {str(key): str(value) for key, value in dict(getattr(document, "metadata", {}) or {}).items()}
        source_id = str(getattr(document, "source_id", "") or match.semantic_index_entry.source_id)
        content = str(getattr(document, "payload", {}).get("text") or "").strip()
        if not content:
            content = str(metadata.get("indexed_text") or metadata.get("text") or source_id)
        layer_type = str(
            getattr(document, "layer_type", "") or metadata.get("kind") or getattr(document, "kind", "") or "semantic"
        )
        episode_id = str(metadata.get("episode_id") or request.episode_id)
        step_id = metadata.get("step_id") if source_id.startswith("step:") or metadata.get("step_id") else None
        loop_id = metadata.get("loop_id") or None
        return RecallEvidence(
            evidence_id=f"semantic:{match.semantic_index_entry.semantic_index_entry_id}",
            episode_id=episode_id,
            kind=layer_type,
            content=content,
            source_id=source_id,
            source_kind="semantic_index",
            semantic_index_entry_id=match.semantic_index_entry.semantic_index_entry_id,
            step_id=step_id,
            loop_id=loop_id,
            created_at=getattr(document, "created_at", None) or match.semantic_index_entry.created_at,
            metadata=metadata,
        )

    def _semantic_state_scope_id(self, request: EvidenceRetrievalRequest) -> str:
        if self.repository is None:
            return f"episode-scope:{request.episode_id}"
        if request.elephant_id:
            for state in self.repository.list_states():
                if state.elephant_id == request.elephant_id:
                    return state.state_id
        current_state = self.repository.current_state()
        if current_state is not None and current_state.personal_model_id == request.personal_model_id:
            return current_state.state_id
        return f"episode-scope:{request.episode_id}"

    def _semantic_candidate_from_match(
        self,
        *,
        evidence: RecallEvidence,
        match,
        owner_scope: str,
    ) -> EvidenceCandidate:
        scaled_signal_scores = {
            signal: value * _SEMANTIC_RECALL_SCORE_SCALE for signal, value in match.signal_scores.items()
        }
        lexical_score = sum(score for signal, score in scaled_signal_scores.items() if signal != "vector")
        vector_score = scaled_signal_scores.get("vector", 0.0)
        reasons = [
            RecallReason(
                f"semantic.{signal}",
                f"hybrid semantic {signal} signal via weighted RRF",
                score,
            )
            for signal, score in scaled_signal_scores.items()
            if score > 0.0
        ]
        reasons.insert(
            0,
            RecallReason(
                f"semantic.scope.{owner_scope}",
                f"{owner_scope.replace('_', ' ')} semantic evidence scope",
                0.0,
            ),
        )
        return EvidenceCandidate(
            evidence_id=evidence.evidence_id,
            evidence=evidence,
            score=sum(scaled_signal_scores.values()),
            lexical_score=lexical_score,
            vector_score=vector_score,
            matched_scopes=(owner_scope,),
            reasons=tuple(reasons),
        )

    def _merge_candidate_sets(
        self,
        *,
        semantic_candidates: tuple[EvidenceCandidate, ...],
        lexical_candidates: tuple[EvidenceCandidate, ...],
    ) -> tuple[EvidenceCandidate, ...]:
        merged: dict[str, EvidenceCandidate] = {}
        for candidate in (*semantic_candidates, *lexical_candidates):
            existing = merged.get(candidate.evidence_id)
            if existing is None:
                merged[candidate.evidence_id] = candidate
                continue
            reason_index: dict[tuple[str, str], RecallReason] = {
                (reason.code, reason.detail): reason for reason in (*existing.reasons, *candidate.reasons)
            }
            merged[candidate.evidence_id] = EvidenceCandidate(
                evidence_id=existing.evidence_id,
                evidence=existing.evidence if existing.score >= candidate.score else candidate.evidence,
                score=existing.score + candidate.score,
                lexical_score=existing.lexical_score + candidate.lexical_score,
                vector_score=existing.vector_score + candidate.vector_score,
                graph_score=existing.graph_score + candidate.graph_score,
                matched_scopes=tuple(dict.fromkeys((*existing.matched_scopes, *candidate.matched_scopes))),
                reasons=tuple(reason_index.values()),
                embedding_mode=existing.embedding_mode or candidate.embedding_mode,
                replay_record=existing.replay_record or candidate.replay_record,
                replay_slots=existing.replay_slots or candidate.replay_slots,
                replay_summary=existing.replay_summary or candidate.replay_summary,
            )
        return tuple(
            sorted(
                merged.values(),
                key=lambda item: (
                    -item.score,
                    -(item.evidence.created_at.timestamp() if item.evidence.created_at is not None else 0.0),
                    item.evidence_id,
                ),
            )
        )

    def _lineage_episode_ids(self, episode_id: str) -> tuple[str, ...]:
        if self.repository is None:
            return (episode_id,)
        # `RuntimeStorageRepository.lineage` does not exist on the trunk
        # repository surface — it's provided by bespoke wrappers in the CLI
        # retrieval helpers. Probe with getattr so this method degrades
        # gracefully when the repository surface lacks the extension.
        lineage_fn = getattr(self.repository, "lineage", None)
        if not callable(lineage_fn):
            return (episode_id,)
        try:
            lineage = lineage_fn(episode_id)
        except Exception:
            return (episode_id,)
        if not lineage:
            return (episode_id,)
        return tuple(dict.fromkeys(state.episode_id for state in lineage))

    def _default_scope_reason(
        self,
        request: EvidenceRetrievalRequest,
        *,
        opened_scopes: tuple[str, ...],
        resolved_episode_ids: tuple[str, ...],
    ) -> str:
        focus = request.state_focus
        focus_ids = focus_work_item_ids(request)
        reasons: list[str] = []
        if "lineage" in opened_scopes and len(resolved_episode_ids) > 1:
            reasons.append("resume recovery expands recall across the durable episode lineage")
        else:
            reasons.append("recovery stays inside the active episode scope")
        if focus_ids:
            reasons.append(f"elephant focus {', '.join(focus_ids[:2])} outranks generic recall")
        elif request.work_item_ids:
            reasons.append(f"active work {', '.join(request.work_item_ids[:2])} outranks generic recall")
        if focus is not None and focus.continuity_signal != "none":
            reasons.append(f"elephant focus signaled {focus.continuity_signal} recovery handling")
        if request.relationship_hints:
            reasons.append("relationship continuity stays explicit during rerank")
        if "elephant" in opened_scopes:
            reasons.append("elephant scope opened because the active elephant spans multiple episodes")
        if "personal_model" in opened_scopes:
            reasons.append("personal model scope opened to preserve long-horizon continuity beyond one elephant")
        return "; ".join(reasons)

    def _candidate_for_record(
        self,
        request: EvidenceRetrievalRequest,
        record: RecallEvidence,
        *,
        resolved_scope: _ResolvedScope,
        query_tokens: set[str],
        query_vector: tuple[float, ...],
        dims: int,
    ) -> EvidenceCandidate | None:
        focus_ids = focus_work_item_ids(request)
        reasons: list[RecallReason] = []
        matched_scopes = self._matched_scopes(record, resolved_scope=resolved_scope)
        scope_score = 0.0
        if record.episode_id == request.episode_id:
            scope_score += 2.5
            reasons.append(RecallReason("scope.episode", "current-episode scope", 2.5))
        elif record.episode_id in set(resolved_scope.lineage_episode_ids):
            scope_score += 1.5
            reasons.append(RecallReason("scope.lineage", "recovery-scope episode", 1.5))
        elif record.episode_id in set(resolved_scope.elephant_episode_ids):
            scope_score += 1.0
            reasons.append(RecallReason("scope.elephant", "elephant continuity scope", 1.0))
        elif record.episode_id in set(resolved_scope.personal_model_episode_ids):
            scope_score += 0.75
            reasons.append(RecallReason("scope.personal_model", "personal-model continuity scope", 0.75))

        structured_turn = _structured_turn_from_record(record)
        selected_slots = _selected_replay_slots(request, structured_turn)
        replay_record: StepReplayRecord | None = None
        replay_summary = ""
        degraded_slots: tuple[str, ...] = ()
        replay_text = ""
        structured_text = ""
        if structured_turn is not None:
            structured_text = _replay_text(structured_turn, selected_slots=_REPLAY_SLOT_NAMES)
            if selected_slots:
                replay_record, degraded_slots = _project_replay_record(
                    structured_turn,
                    selected_slots=selected_slots,
                    max_compression=request.max_compression,
                )
                replay_text = _replay_text(replay_record, selected_slots=selected_slots)
                replay_summary = _replay_summary(replay_record, selected_slots=selected_slots)

        search_text = "\n".join(part for part in (record.content, structured_text) if part)
        content_tokens = _tokenize(search_text)
        overlap = sorted(query_tokens & content_tokens)
        lexical_score = float(len(overlap)) * 2.0
        if overlap:
            reasons.append(
                RecallReason(
                    "lexical.query",
                    f"query overlap: {','.join(overlap)}",
                    lexical_score,
                )
            )
        tag_tokens = _tokenize(" ".join(record.tags))
        tag_overlap = sorted(query_tokens & tag_tokens)
        if tag_overlap:
            tag_score = float(len(tag_overlap)) * 1.25
            lexical_score += tag_score
            reasons.append(RecallReason("lexical.tags", f"tag overlap: {','.join(tag_overlap)}", tag_score))
            novel_tag_overlap = tuple(token for token in tag_overlap if token not in overlap)
            if novel_tag_overlap:
                novel_tag_score = float(len(novel_tag_overlap)) * 0.75
                lexical_score += novel_tag_score
                reasons.append(
                    RecallReason(
                        "lexical.tags.novel",
                        f"novel tag overlap: {','.join(novel_tag_overlap)}",
                        novel_tag_score,
                    )
                )

        vector_input = _record_embedding_text(record, structured_text=structured_text)
        vector_score = 0.0
        if query_vector:
            candidate_embedding = self.embedding_service.cached_vector(
                target="evidence",
                cache_key=_evidence_cache_key(record, search_text=vector_input),
                dimensions=dims,
            )
            if candidate_embedding is not None:
                vector_score = max(0.0, cosine_similarity(query_vector, candidate_embedding.values)) * 3.0
                if vector_score > 0.0:
                    reasons.append(
                        RecallReason(
                            "vector.elephant-embed",
                            f"matryoshka vector similarity via {embedding_mode_for_latency(request.latency_mode)}",
                            vector_score,
                        )
                    )

        graph_score = 0.0
        work_item_overlap = tuple(work_item_id for work_item_id in focus_ids if work_item_id in record.work_item_ids)
        if work_item_overlap:
            graph_score += float(len(work_item_overlap)) * 3.5
            reasons.append(
                RecallReason(
                    "work.item-overlap",
                    f"work item overlap: {','.join(work_item_overlap)}",
                    graph_score,
                )
            )
        elif focus_ids and not record.work_item_ids:
            graph_score -= 0.5
            reasons.append(
                RecallReason(
                    "work.generic-penalty",
                    "generic recall deprioritized behind active work",
                    -0.5,
                )
            )
        graph_delta, continuity_delta, state_focus_reasons = state_focus_score_adjustments(
            request,
            record=record,
            work_item_overlap=work_item_overlap,
        )
        graph_score += graph_delta
        reasons.extend(state_focus_reasons)

        relationship_score = 0.0
        relationship_tokens = _tokenize(" ".join(request.relationship_hints))
        relationship_overlap = sorted(relationship_tokens & (content_tokens | tag_tokens))
        if relationship_overlap:
            relationship_score += float(len(relationship_overlap)) * 0.8
            reasons.append(
                RecallReason(
                    "relationship.continuity",
                    f"relationship continuity overlap: {','.join(relationship_overlap)}",
                    relationship_score,
                )
            )

        continuity_score = 0.0
        if query_tokens & _CONTINUITY_QUERY_TOKENS:
            if record.kind in {
                "procedural",
                "semantic",
                "summary",
                "decision",
                "structured_turn",
            }:
                continuity_score += 1.75
                reasons.append(
                    RecallReason(
                        "continuity.focus_family",
                        f"continuity elephant focus prefers durable kind {record.kind}",
                        continuity_score,
                    )
                )
            if record.work_item_ids:
                continuity_score += 0.4
                reasons.append(
                    RecallReason(
                        "continuity.current-work-link",
                        "active elephant work-linked continuity",
                        0.4,
                    )
                )
            continuity_tags = {
                "continuity",
                "handoff",
                "recovery",
                "resume",
                "scope-aware",
            }
            if continuity_tags & set(record.tags):
                continuity_score += 0.4
                reasons.append(
                    RecallReason(
                        "continuity.tags",
                        "continuity-tag boost",
                        0.4,
                    )
                )

        continuity_score += continuity_delta

        replay_score = 0.0
        if structured_turn is not None:
            replay_score += 0.75
            reasons.append(
                RecallReason(
                    "replay.structured-turn",
                    "structured turn evidence is replayable",
                    0.75,
                )
            )
            if request.replay_mode != "off":
                replay_score += 0.8
                reasons.append(
                    RecallReason(
                        "replay.mode",
                        f"explicit {request.replay_mode} replay requested",
                        0.8,
                    )
                )
                if selected_slots:
                    slot_score = float(len(selected_slots)) * 0.35
                    replay_score += slot_score
                    reasons.append(
                        RecallReason(
                            "replay.slots",
                            f"replay targets slots: {','.join(selected_slots)}",
                            slot_score,
                        )
                    )
                replay_overlap = sorted(query_tokens & _tokenize(replay_text))
                if replay_overlap:
                    overlap_score = float(len(replay_overlap)) * 2.25
                    replay_score += overlap_score
                    reasons.append(
                        RecallReason(
                            "replay.slot-overlap",
                            f"replay overlap: {','.join(replay_overlap)}",
                            overlap_score,
                        )
                    )
                if request.replay_mode == "turn":
                    if structured_turn.compression_tier == "raw_turn":
                        replay_score += 1.25
                        reasons.append(
                            RecallReason(
                                "replay.turn-boundary",
                                "turn replay prefers raw turn evidence",
                                1.25,
                            )
                        )
                elif request.replay_mode == "episode":
                    if (
                        structured_turn.compression_tier == "episode_summary"
                        or len(structured_turn.source_turn_ids) > 1
                    ):
                        replay_score += 1.5
                        reasons.append(
                            RecallReason(
                                "replay.episode-boundary",
                                "episode replay prefers multi-turn summaries",
                                1.5,
                            )
                        )
                    else:
                        replay_score += 0.5
                        reasons.append(
                            RecallReason(
                                "replay.episode-rebuild",
                                "raw turns remain eligible when an episode summary is unavailable",
                                0.5,
                            )
                        )
                if degraded_slots:
                    replay_score += 0.35
                    reasons.append(
                        RecallReason(
                            "replay.compression-fallback",
                            f"replay fell back to {request.max_compression} for {','.join(degraded_slots)}",
                            0.35,
                        )
                    )
                elif selected_slots:
                    reasons.append(
                        RecallReason(
                            "replay.compression",
                            f"replay stayed within {request.max_compression}",
                            0.2,
                        )
                    )
            elif selected_slots:
                replay_score += 0.3
                reasons.append(
                    RecallReason(
                        "replay.slot-focus",
                        f"slot-aware retrieval focused on {','.join(selected_slots)}",
                        0.3,
                    )
                )
        elif request.replay_mode != "off":
            replay_score -= 0.5
            reasons.append(
                RecallReason(
                    "replay.generic-fallback",
                    "generic evidence stayed eligible because no step replay record was available",
                    -0.5,
                )
            )

        lifecycle_score = 0.0
        if "corrected" in record.tags:
            lifecycle_score += 1.4
            reasons.append(RecallReason("lifecycle.corrected", "corrected evidence", 1.4))

        recency_score = 0.0
        if record.created_at is not None:
            age_seconds = max(0.0, (_now() - record.created_at).total_seconds())
            recency_score = max(0.0, 2.0 - (age_seconds / 86400.0))
            reasons.append(RecallReason("time.recency", "recency boost", recency_score))

        total_score = (
            scope_score
            + lexical_score
            + vector_score
            + graph_score
            + relationship_score
            + continuity_score
            + replay_score
            + lifecycle_score
            + recency_score
        )
        if total_score <= 0.0 and not matched_scopes:
            return None
        return EvidenceCandidate(
            evidence_id=record.evidence_id,
            evidence=record,
            score=total_score,
            lexical_score=lexical_score,
            vector_score=vector_score,
            graph_score=graph_score + relationship_score + continuity_score,
            matched_scopes=matched_scopes,
            reasons=tuple(reasons),
            embedding_mode=embedding_mode_for_latency(request.latency_mode),
            replay_record=replay_record,
            replay_slots=selected_slots,
            replay_summary=replay_summary,
        )

    def _matched_scopes(self, record: RecallEvidence, *, resolved_scope: _ResolvedScope) -> tuple[str, ...]:
        scopes: list[str] = []
        if record.episode_id in resolved_scope.episode_ids:
            scopes.append("episode")
        if record.episode_id in resolved_scope.lineage_episode_ids:
            scopes.append("lineage")
        if record.episode_id in resolved_scope.elephant_episode_ids:
            scopes.append("elephant")
        if record.episode_id in resolved_scope.personal_model_episode_ids:
            scopes.append("personal_model")
        return tuple(dict.fromkeys(scopes))

    def _rerank_summary(self, candidates: tuple[EvidenceCandidate, ...]) -> str:
        if not candidates:
            return "no evidence survived rerank"
        top = candidates[0]
        reasons = ", ".join(reason.code for reason in top.reasons[:4]) or "no explicit reasons"
        replay = f"; replay={top.replay_summary}" if top.replay_summary else ""
        return f"top evidence {top.evidence_id} survived rerank via {reasons}{replay}"


def _evidence_sort_key(record: RecallEvidence) -> tuple[datetime, str]:
    return (
        record.created_at or datetime.min.replace(tzinfo=timezone.utc),
        record.evidence_id,
    )


def _index_refresh_action(*, lifecycle_state: str, replacement_evidence_id: str | None) -> str:
    if lifecycle_state in {"superseded", "consolidated"} and replacement_evidence_id:
        return "replace"
    if lifecycle_state == "deleted":
        return "drop"
    return "refresh"


def _index_invalidation_reason(*, lifecycle_state: str, replacement_evidence_id: str | None) -> str:
    if lifecycle_state == "superseded" and replacement_evidence_id:
        return f"superseded evidence must be replaced by {replacement_evidence_id} before lexical and vector views are trusted"
    if lifecycle_state == "consolidated" and replacement_evidence_id:
        return f"consolidated evidence must be replaced by summary {replacement_evidence_id} before lexical and vector views are trusted"
    if lifecycle_state == "deleted":
        return "deleted evidence must be removed from lexical and vector views"
    return f"{lifecycle_state} evidence must refresh derived lexical and vector views from canonical rows"


def _embedding_index_invalidations(
    store: "StepEvidenceStore",
) -> tuple[EmbeddingIndexInvalidation, ...]:
    invalidations: list[EmbeddingIndexInvalidation] = []
    ordered_records = tuple(sorted(store.list(include_inactive=True), key=_evidence_sort_key))
    for record in ordered_records:
        state_payload = store.state(record.evidence_id)
        lifecycle_state = str(state_payload.get("status") or "active")
        if lifecycle_state in {None, "active"}:
            continue
        replacement_evidence_id = None
        preload_entry = _evidence_preload_entry(record)
        invalidations.append(
            EmbeddingIndexInvalidation(
                evidence_id=record.evidence_id,
                lifecycle_state=lifecycle_state,
                stale_cache_key=preload_entry.cache_key,
                replacement_evidence_id=replacement_evidence_id,
                refresh_action=_index_refresh_action(
                    lifecycle_state=lifecycle_state,
                    replacement_evidence_id=replacement_evidence_id,
                ),
                reason=_index_invalidation_reason(
                    lifecycle_state=lifecycle_state,
                    replacement_evidence_id=replacement_evidence_id,
                ),
            )
        )
    return tuple(invalidations)


def build_embedding_index_rebuild_plan(
    store: "StepEvidenceStore",
) -> EmbeddingIndexRebuildPlan:
    ordered_records = tuple(sorted(store.list(include_inactive=True), key=_evidence_sort_key))
    active_records = tuple(
        record
        for record in ordered_records
        if str(store.state(record.evidence_id).get("status") or "active") == "active"
    )
    invalidations = _embedding_index_invalidations(store)
    active_entries = tuple(_evidence_preload_entry(record) for record in active_records)
    replacement_evidence_ids = tuple(
        dict.fromkeys(
            invalidation.replacement_evidence_id
            for invalidation in invalidations
            if invalidation.replacement_evidence_id is not None
        )
    )
    if not invalidations:
        return EmbeddingIndexRebuildPlan(
            target="evidence",
            refresh_scope="noop",
            active_evidence_ids=tuple(record.evidence_id for record in active_records),
            active_cache_keys=tuple(entry.cache_key for entry in active_entries),
            stale_cache_keys=(),
            replacement_evidence_ids=(),
            dimensions=ELEPHANT_EMBED_ONLINE_DIMENSIONS,
            steps=(
                "no rebuild is required while canonical evidence rows, lexical views, and shared vector projections stay aligned",
            ),
            summary="derived lexical and vector views already match the active canonical evidence rows",
        )
    stale_cache_keys = tuple(invalidation.stale_cache_key for invalidation in invalidations)
    steps = [
        f"drop {len(stale_cache_keys)} stale vector cache entr{'y' if len(stale_cache_keys) == 1 else 'ies'} for inactive evidence rows",
        f"rebuild lexical evidence views from {len(active_records)} active canonical row(s)",
        (
            f"reseed shared {ELEPHANT_EMBED_MODEL_ID} candidate vectors for {len(active_entries)} active evidence row(s) "
            f"at dimensions {', '.join(str(value) for value in ELEPHANT_EMBED_ONLINE_DIMENSIONS)}"
        ),
    ]
    if replacement_evidence_ids:
        steps.insert(
            1,
            f"promote lineage replacements before rebuild: {', '.join(replacement_evidence_ids)}",
        )
    return EmbeddingIndexRebuildPlan(
        target="evidence",
        refresh_scope="full",
        active_evidence_ids=tuple(record.evidence_id for record in active_records),
        active_cache_keys=tuple(entry.cache_key for entry in active_entries),
        stale_cache_keys=stale_cache_keys,
        replacement_evidence_ids=replacement_evidence_ids,
        dimensions=ELEPHANT_EMBED_ONLINE_DIMENSIONS,
        steps=tuple(steps),
        summary=(
            f"refresh the evidence index from {len(active_records)} active canonical row(s) after "
            f"invalidating {len(invalidations)} stale derived entr{'y' if len(invalidations) == 1 else 'ies'}"
        ),
    )


def build_embedding_index_policy(store: "StepEvidenceStore") -> EmbeddingIndexPolicy:
    invalidations = _embedding_index_invalidations(store)
    rebuild_plan = build_embedding_index_rebuild_plan(store)
    invalidation_reason = (
        "superseded, consolidated, and deleted evidence must invalidate derived lexical and vector views"
        if invalidations
        else "derived lexical and vector views are aligned with the active canonical evidence rows"
    )
    return EmbeddingIndexPolicy(
        model_id=ELEPHANT_EMBED_MODEL_ID,
        lexical_index_version=_LEXICAL_INDEX_VERSION,
        embedding_index_version=_EMBEDDING_INDEX_VERSION,
        active_dimensions=ELEPHANT_EMBED_ONLINE_DIMENSIONS,
        tracked_evidence_count=len(rebuild_plan.active_evidence_ids),
        rebuild_required=bool(invalidations),
        invalidated_evidence_ids=tuple(invalidation.evidence_id for invalidation in invalidations),
        invalidation_reason=invalidation_reason,
        invalidations=invalidations,
        rebuild_plan=rebuild_plan,
    )
