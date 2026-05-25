"""Scoped hybrid semantic search over indexed Step, Episode, and Fact text."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import math
import unicodedata
from typing import Mapping, Protocol

from packages.contracts import SemanticIndexEntry

from .backend import SemanticIndexBackend, SemanticIndexVectorQuery

RRF_K = 60.0
FUSION_WEIGHTS = {
    "token_coverage": 2.0,
    "keyword_exact": 1.5,
    "bm25": 1.2,
    "vector": 1.0,
    "ngram": 0.9,
}
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SemanticSourceDocument:
    source_id: str
    kind: str
    schema_version: str
    payload: Mapping[str, object] = field(default_factory=dict)
    owner_scope: str | None = None
    personal_model_id: str | None = None
    state_id: str | None = None
    layer_type: str | None = None
    artifact_uri: str | None = None
    created_at: datetime | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SemanticSearchQuery:
    text: str
    vector: tuple[float, ...] = ()
    dimensions: int | None = None
    owner_scope: str | None = None
    personal_model_id: str | None = None
    state_id: str | None = None
    provider_id: str | None = None
    model_id: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    limit: int = 10

    def __post_init__(self) -> None:
        if not self.text.strip() and not self.vector:
            raise ValueError("semantic search requires text, vector, or both")
        if self.vector and (self.dimensions is None or self.dimensions <= 0):
            raise ValueError("semantic search vector queries require dimensions")
        if self.dimensions is not None and self.vector and len(self.vector) != self.dimensions:
            raise ValueError("semantic search vector length must match dimensions")
        if self.limit <= 0:
            raise ValueError("semantic search limit must be positive")


@dataclass(frozen=True, slots=True)
class SemanticSearchMatch:
    semantic_index_entry: SemanticIndexEntry
    document: SemanticSourceDocument
    score: float
    signal_scores: Mapping[str, float] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()


class SemanticSearchRepository(Protocol):
    def list_semantic_index_entries(
        self,
        *,
        owner_scope: str | None = None,
        state_id: str | None = None,
        personal_model_id: str | None = None,
        provider_id: str | None = None,
        model_id: str | None = None,
    ) -> tuple[SemanticIndexEntry, ...]:
        """Return semantic-index metadata rows under hard owner/provider gates."""


class HybridSemanticSearcher:
    def __init__(self, *, repository: SemanticSearchRepository, backend: SemanticIndexBackend) -> None:
        self.repository = repository
        self.backend = backend

    def search(self, query: SemanticSearchQuery) -> tuple[SemanticSearchMatch, ...]:
        owner_scope = "state" if query.owner_scope == "episode" else query.owner_scope
        entries = tuple(
            entry
            for entry in self.repository.list_semantic_index_entries(
                owner_scope=owner_scope,
                state_id=query.state_id,
                personal_model_id=query.personal_model_id,
                provider_id=query.provider_id,
                model_id=query.model_id,
            )
            if entry.status != "deleted"
        )
        entries_by_id = {entry.semantic_index_entry_id: entry for entry in entries}
        documents_by_entry_id = _documents_by_entry_id(self.repository, entries, query)
        contributions: dict[str, dict[str, float]] = {
            entry_id: {} for entry_id in documents_by_entry_id
        }
        vector_ranked_ids = self._vector_ranking(query, documents_by_entry_id, entries_by_id)
        _add_ranked_signal(
            contributions,
            signal="vector",
            ranked_ids=vector_ranked_ids,
            weight=FUSION_WEIGHTS["vector"],
        )
        coverage_ranked_ids = _token_coverage_ranking(query.text, documents_by_entry_id)
        _add_ranked_signal(
            contributions,
            signal="token_coverage",
            ranked_ids=coverage_ranked_ids,
            weight=FUSION_WEIGHTS["token_coverage"],
        )
        keyword_ranked_ids = _keyword_exact_ranking(query.text, documents_by_entry_id)
        _add_ranked_signal(
            contributions,
            signal="keyword_exact",
            ranked_ids=keyword_ranked_ids,
            weight=FUSION_WEIGHTS["keyword_exact"],
        )
        bm25_ranked_ids = _bm25_ranking(query.text, documents_by_entry_id)
        _add_ranked_signal(
            contributions,
            signal="bm25",
            ranked_ids=bm25_ranked_ids,
            weight=FUSION_WEIGHTS["bm25"],
        )
        ngram_ranked_ids = _ngram_ranking(query.text, documents_by_entry_id)
        _add_ranked_signal(
            contributions,
            signal="ngram",
            ranked_ids=ngram_ranked_ids,
            weight=FUSION_WEIGHTS["ngram"],
        )
        ranked = sorted(
            (
                (entry_id, sum(signal_scores.values()), signal_scores)
                for entry_id, signal_scores in contributions.items()
                if signal_scores
            ),
            key=lambda item: (-item[1], item[0]),
        )
        return tuple(
            SemanticSearchMatch(
                semantic_index_entry=entries_by_id[entry_id],
                document=documents_by_entry_id[entry_id],
                score=score,
                signal_scores=dict(signal_scores),
                reasons=tuple(sorted(signal_scores)),
            )
            for entry_id, score, signal_scores in ranked[: query.limit]
        )

    def _vector_ranking(
        self,
        query: SemanticSearchQuery,
        documents_by_entry_id: Mapping[str, SemanticSourceDocument],
        entries_by_id: Mapping[str, SemanticIndexEntry],
    ) -> tuple[str, ...]:
        if not query.vector or query.dimensions is None:
            return ()
        try:
            health = self.backend.health()
            if not health.vector_available:
                return ()
            vector_matches = tuple(
                match
                for match in self.backend.search(
                    SemanticIndexVectorQuery(
                        dimensions=query.dimensions,
                        values=query.vector,
                        limit=max(query.limit, len(entries_by_id) or query.limit),
                    )
                )
                if match.semantic_index_entry_id in documents_by_entry_id
            )
        except Exception:
            LOGGER.debug("Semantic vector backend search failed; using lexical semantic signals only.", exc_info=True)
            return ()
        return tuple(match.semantic_index_entry_id for match in vector_matches)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _documents_by_entry_id(
    repository: SemanticSearchRepository,
    entries: tuple[SemanticIndexEntry, ...],
    query: SemanticSearchQuery,
) -> dict[str, SemanticSourceDocument]:
    documents: dict[str, SemanticSourceDocument] = {}
    for entry in entries:
        document = _source_document_for_entry(repository, entry)
        if document is None:
            continue
        if not _document_matches_query_scope(document, entry, query):
            continue
        if not _document_in_time_range(document, entry, query):
            continue
        documents[entry.semantic_index_entry_id] = document
    return documents


def _source_document_for_entry(
    repository: SemanticSearchRepository,
    entry: SemanticIndexEntry,
) -> SemanticSourceDocument | None:
    metadata = _entry_metadata(entry)
    source_id = str(entry.source_id or "").strip()
    if source_id.startswith("episode:"):
        return _episode_record(repository, entry, metadata, source_id.removeprefix("episode:"))
    if source_id.startswith("step:"):
        return _step_record(repository, entry, metadata, source_id.removeprefix("step:"))
    if entry.owner_scope == "personal_model":
        return _fact_record(repository, entry, metadata, source_id)
    return _metadata_record(entry, metadata)


def _entry_metadata(entry: SemanticIndexEntry) -> dict[str, str]:
    return {str(key): str(value) for key, value in dict(getattr(entry, "metadata", {}) or {}).items()}


def _indexed_text(metadata: Mapping[str, str]) -> str:
    return str(metadata.get("indexed_text") or metadata.get("text") or "").strip()


def _episode_record(
    repository: SemanticSearchRepository,
    entry: SemanticIndexEntry,
    metadata: Mapping[str, str],
    episode_id: str,
) -> SemanticSourceDocument | None:
    load_episode = getattr(repository, "load_episode", None)
    episode = None
    if callable(load_episode):
        try:
            episode = load_episode(episode_id)
        except Exception:
            LOGGER.debug("Failed to load episode source document for semantic search; using metadata fallback.", exc_info=True)
            episode = None
    if episode is None:
        return _metadata_record(entry, metadata, schema_version="episode_summary/v1", layer_type="episode_summary")
    episode_metadata = {str(key): str(value) for key, value in dict(getattr(episode, "metadata", {}) or {}).items()}
    text = _indexed_text(metadata)
    if not text:
        parts = (
            str(getattr(episode, "exit_summary", "") or "").strip(),
            str(getattr(episode, "entry_surface", "") or "").strip(),
            str(episode_metadata.get("topic") or "").strip(),
            str(episode_metadata.get("focus") or "").strip(),
            str(episode_metadata.get("note") or "").strip(),
        )
        text = " | ".join(dict.fromkeys(part for part in parts if part))
    return SemanticSourceDocument(
        source_id=entry.source_id,
        kind="derived",
        schema_version="episode_summary/v1",
        payload={"text": text},
        owner_scope="state",
        personal_model_id=getattr(episode, "personal_model_id", None) or entry.personal_model_id,
        state_id=getattr(episode, "state_id", None) or entry.state_id,
        layer_type="episode_summary",
        created_at=getattr(episode, "ended_at", None) or getattr(episode, "started_at", None) or entry.created_at,
        metadata={**episode_metadata, **dict(metadata), "kind": "episode_summary", "episode_id": episode_id},
    )


def _step_record(
    repository: SemanticSearchRepository,
    entry: SemanticIndexEntry,
    metadata: Mapping[str, str],
    step_id: str,
) -> SemanticSourceDocument | None:
    load_step = getattr(repository, "load_step", None)
    step = None
    if callable(load_step):
        try:
            step = load_step(step_id)
        except Exception:
            LOGGER.debug("Failed to load step source document for semantic search; using metadata fallback.", exc_info=True)
            step = None
    if step is None:
        return _metadata_record(entry, metadata, schema_version="step/v1", layer_type="step")
    step_metadata = {str(key): str(value) for key, value in dict(getattr(step, "metadata", {}) or {}).items()}
    merged_metadata = {**step_metadata, **dict(metadata)}
    text = _indexed_text(metadata) or _step_text(step, merged_metadata)
    return SemanticSourceDocument(
        source_id=entry.source_id,
        kind="derived",
        schema_version="step/v1",
        payload={"text": text},
        owner_scope="state",
        personal_model_id=getattr(step, "personal_model_id", None) or entry.personal_model_id,
        state_id=getattr(step, "state_id", None) or entry.state_id,
        layer_type="step",
        created_at=getattr(step, "created_at", None) or entry.created_at,
        metadata={
            **merged_metadata,
            "kind": "step",
            "step_id": step_id,
            "loop_id": str(getattr(step, "loop_id", "") or merged_metadata.get("loop_id", "")),
            "episode_id": str(getattr(step, "episode_id", "") or merged_metadata.get("episode_id", "")),
            "action": str(getattr(step, "action", "") or merged_metadata.get("action", "")),
        },
    )


def _step_text(step: object, metadata: Mapping[str, str]) -> str:
    action = str(getattr(step, "action", "") or "").strip().lower()
    summary = str(getattr(step, "summary", "") or "").strip()
    if action == "record_input":
        parts = (str(metadata.get("user_query") or metadata.get("raw_user_query") or "").strip(),)
    elif action == "emit_response":
        parts = (str(metadata.get("final_response") or metadata.get("assistant_response") or summary).strip(),)
    elif action == "reply":
        parts = (summary, str(metadata.get("final_response") or metadata.get("assistant_response") or "").strip())
    else:
        parts = (
            summary,
            str(metadata.get("user_query") or metadata.get("raw_user_query") or "").strip(),
            str(metadata.get("final_response") or metadata.get("assistant_response") or "").strip(),
        )
    return " | ".join(dict.fromkeys(part for part in parts if part))


def _fact_record(
    repository: SemanticSearchRepository,
    entry: SemanticIndexEntry,
    metadata: Mapping[str, str],
    fact_id: str,
) -> SemanticSourceDocument | None:
    fact = _load_fact(repository, entry, fact_id)
    if fact is None:
        return _metadata_record(entry, metadata, schema_version="personal_model_claim/v1", layer_type="personal_model_claim")
    fact_metadata = {str(key): str(value) for key, value in dict(getattr(fact, "metadata", {}) or {}).items()}
    text = _indexed_text(metadata) or str(getattr(fact, "text", "") or "").strip()
    return SemanticSourceDocument(
        source_id=fact_id,
        kind="derived",
        schema_version="personal_model_claim/v1",
        payload={"text": text},
        owner_scope="personal_model",
        personal_model_id=getattr(fact, "personal_model_id", None) or entry.personal_model_id,
        state_id=entry.state_id,
        layer_type="personal_model_claim",
        created_at=getattr(fact, "committed_at", None) or entry.created_at,
        metadata={
            **fact_metadata,
            **dict(metadata),
            "kind": "personal_model_claim",
            "claim_ref": fact_id,
            "lens": str(getattr(fact, "lens", "") or metadata.get("lens", "")),
            "topic": str(fact_metadata.get("topic") or metadata.get("topic", "")),
            "text": str(getattr(fact, "text", "") or metadata.get("text", "")),
        },
    )


def _load_fact(repository: SemanticSearchRepository, entry: SemanticIndexEntry, fact_id: str) -> object | None:
    list_facts = getattr(repository, "list_personal_model_facts", None)
    if not callable(list_facts) or not fact_id:
        return None
    try:
        facts = list_facts(
            personal_model_id=entry.personal_model_id or "",
            status=("active", "retired", "disputed"),
        )
    except Exception:
        LOGGER.debug("Failed to load Personal Model fact source document for semantic search.", exc_info=True)
        return None
    return next((fact for fact in facts if str(getattr(fact, "fact_id", "") or "") == fact_id), None)


def _metadata_record(
    entry: SemanticIndexEntry,
    metadata: Mapping[str, str],
    *,
    schema_version: str | None = None,
    layer_type: str | None = None,
) -> SemanticSourceDocument | None:
    text = _indexed_text(metadata)
    if not text:
        return None
    resolved_layer = layer_type or str(metadata.get("layer_type") or metadata.get("kind") or entry.owner_scope or "semantic_index")
    return SemanticSourceDocument(
        source_id=entry.source_id,
        kind="derived",
        schema_version=schema_version or f"{resolved_layer}/v1",
        payload={"text": text},
        owner_scope=entry.owner_scope,
        personal_model_id=entry.personal_model_id,
        state_id=entry.state_id,
        layer_type=resolved_layer,
        created_at=entry.created_at,
        metadata=dict(metadata),
    )


def _document_matches_query_scope(
    document: SemanticSourceDocument,
    entry: SemanticIndexEntry,
    query: SemanticSearchQuery,
) -> bool:
    if query.owner_scope != "episode":
        return True
    return (
        str(getattr(document, "schema_version", "") or "") == "episode_summary/v1"
        or str(getattr(document, "layer_type", "") or "") == "episode_summary"
        or str(getattr(entry, "metadata", {}).get("kind") or "") == "episode_summary"
    )


def _document_in_time_range(
    document: SemanticSourceDocument,
    entry: SemanticIndexEntry,
    query: SemanticSearchQuery,
) -> bool:
    if query.start_at is None and query.end_at is None:
        return True
    when = getattr(document, "created_at", None) or getattr(entry, "created_at", None)
    if when is None:
        return False
    resolved = _aware(when)
    if query.start_at is not None and resolved < _aware(query.start_at):
        return False
    if query.end_at is not None and resolved > _aware(query.end_at):
        return False
    return True


def _add_ranked_signal(
    contributions: dict[str, dict[str, float]],
    *,
    signal: str,
    ranked_ids: tuple[str, ...],
    weight: float,
) -> None:
    for rank, entry_id in enumerate(ranked_ids, start=1):
        if entry_id not in contributions:
            continue
        contributions[entry_id][signal] = weight / (RRF_K + rank)


def _token_coverage_ranking(
    text: str,
    documents_by_entry_id: Mapping[str, SemanticSourceDocument],
) -> tuple[str, ...]:
    tokens = tuple(dict.fromkeys(_tokens(text)))
    if not tokens:
        return ()
    scored: list[tuple[str, float]] = []
    for entry_id, document in documents_by_entry_id.items():
        document_text = _normalized_text(_document_text(document))
        hits = sum(1 for token in tokens if token in document_text)
        if hits:
            coverage = hits / float(len(tokens))
            scored.append((entry_id, coverage + (0.05 * hits)))
    return tuple(entry_id for entry_id, _score in sorted(scored, key=lambda item: (-item[1], item[0])))


def _keyword_exact_ranking(
    text: str,
    documents_by_entry_id: Mapping[str, SemanticSourceDocument],
) -> tuple[str, ...]:
    tokens = _tokens(text)
    if not tokens:
        return ()
    scored: list[tuple[str, int]] = []
    for entry_id, document in documents_by_entry_id.items():
        document_text = _normalized_text(_document_text(document))
        exact_hits = sum(1 for token in tokens if token in document_text)
        if exact_hits:
            scored.append((entry_id, exact_hits))
    return tuple(entry_id for entry_id, _score in sorted(scored, key=lambda item: (-item[1], item[0])))


def _bm25_ranking(
    text: str,
    documents_by_entry_id: Mapping[str, SemanticSourceDocument],
) -> tuple[str, ...]:
    query_tokens = _tokens(text)
    if not query_tokens or not documents_by_entry_id:
        return ()
    documents = {
        entry_id: _tokens(_document_text(document))
        for entry_id, document in documents_by_entry_id.items()
    }
    document_count = float(len(documents))
    average_length = sum(len(tokens) for tokens in documents.values()) / max(document_count, 1.0)
    document_frequency = {
        token: sum(1 for tokens in documents.values() if token in tokens)
        for token in set(query_tokens)
    }
    scored: list[tuple[str, float]] = []
    for entry_id, tokens in documents.items():
        if not tokens:
            continue
        token_counts = Counter(tokens)
        score = 0.0
        for token in query_tokens:
            frequency = token_counts.get(token, 0)
            if frequency <= 0:
                continue
            idf = math.log(1.0 + ((document_count - document_frequency[token] + 0.5) / (document_frequency[token] + 0.5)))
            denominator = frequency + 1.5 * (1.0 - 0.75 + 0.75 * (len(tokens) / max(average_length, 1.0)))
            score += idf * ((frequency * 2.5) / denominator)
        if score > 0.0:
            scored.append((entry_id, score))
    return tuple(entry_id for entry_id, _score in sorted(scored, key=lambda item: (-item[1], item[0])))


def _ngram_ranking(
    text: str,
    documents_by_entry_id: Mapping[str, SemanticSourceDocument],
) -> tuple[str, ...]:
    query_ngrams = _char_ngrams(_compact_lexical_text(text))
    if not query_ngrams:
        return ()
    scored: list[tuple[str, float]] = []
    for entry_id, document in documents_by_entry_id.items():
        document_ngrams = _char_ngrams(_compact_lexical_text(_document_text(document)))
        if not document_ngrams:
            continue
        score = len(query_ngrams & document_ngrams) / float(len(query_ngrams))
        if score > 0.0:
            scored.append((entry_id, score))
    return tuple(entry_id for entry_id, _score in sorted(scored, key=lambda item: (-item[1], item[0])))


def _normalized_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or "")).casefold()
    decomposed = unicodedata.normalize("NFKD", normalized)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _tokens(text: str) -> tuple[str, ...]:
    normalized = _normalized_text(text)
    tokens: list[str] = []
    current: list[str] = []
    for ch in normalized:
        category = unicodedata.category(ch)
        if category[0] in {"L", "N"} or ch in "_./:-":
            current.append(ch)
            continue
        if current:
            tokens.extend(_token_variants("".join(current)))
            current = []
    if current:
        tokens.extend(_token_variants("".join(current)))
    return tuple(token for token in dict.fromkeys(tokens) if token)


def _token_variants(token: str) -> tuple[str, ...]:
    if not token:
        return ()
    variants: list[str] = [token]
    if _has_cjk(token):
        variants.extend(_char_ngrams(token, widths=(1, 2)))
    return tuple(variants)


def _has_cjk(text: str) -> bool:
    return any(
        "CJK" in unicodedata.name(ch, "")
        or "HIRAGANA" in unicodedata.name(ch, "")
        or "KATAKANA" in unicodedata.name(ch, "")
        for ch in text
    )


def _compact_lexical_text(text: str) -> str:
    normalized = _normalized_text(text)
    return "".join(ch for ch in normalized if unicodedata.category(ch)[0] in {"L", "N"})


def _char_ngrams(text: str, *, widths: tuple[int, ...] = (2, 3)) -> set[str]:
    if not text:
        return set()
    grams: set[str] = set()
    for width in widths:
        if len(text) <= width:
            grams.add(text)
        else:
            grams.update(text[index : index + width] for index in range(0, len(text) - width + 1))
    return grams


def _document_text(document: SemanticSourceDocument) -> str:
    fragments: list[str] = [document.source_id, document.kind, document.schema_version]
    if document.layer_type:
        fragments.append(document.layer_type)
    if document.artifact_uri:
        fragments.append(document.artifact_uri)
    fragments.extend(str(value) for value in document.payload.values())
    fragments.extend(str(value) for value in document.metadata.values())
    return " ".join(fragment for fragment in fragments if fragment)
