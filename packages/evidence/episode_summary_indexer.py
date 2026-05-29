"""Auto-index committed content into the semantic index for recall.

## The gap this closes

Without a producer hook, the `semantic_index` package is inert — nothing
ever calls `index_document()`, so recall can only fall back to
substring scans. We fix that by writing committed content (personal-model
records, episode exit summaries, state insights) into the index right after
they are persisted, so the *next* turn's recall has a populated search
surface.

## Usage

    indexer = SemanticSummaryIndexer(
        semantic_index=SemanticIndexService(...),
        embedding_service=DefaultEmbeddingService(...),
    )
    indexer.index_episode_exit(episode)
    indexer.index_personal_model_claim(fact)

Every call is best-effort: a missing service, an embedding failure, or a
backend outage returns ``None`` without raising. The producer path must
never block a governance write because indexing had a bad day.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import logging
from typing import Any
from uuid import uuid4

from packages.contracts import DiaryEntry, Episode, Fact, Step
from packages.contracts.paths import LearningSummaryRecord

LOGGER = logging.getLogger(__name__)


__all__ = [
    "SemanticSummaryIndexer",
    "SemanticSummaryBackfillResult",
    "backfill_existing_semantic_summaries",
    "build_diary_entry_recall_text",
    "build_episode_summary_text",
    "build_learning_summary_recall_text",
    "build_personal_model_claim_text",
    "build_step_recall_text",
]


_MAX_TEXT_CHARS = 4_000
_NOISY_STEP_ACTIONS = frozenset(
    {
        "assemble_context",
        "call_model",
        "call_tool",
        "compact_context",
        "context_prompt",
        "effective_user_query",
        "model",
        "reflect",
        "write_state",
    }
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _truncate(text: str, limit: int = _MAX_TEXT_CHARS) -> str:
    collapsed = " ".join(str(text or "").split()).strip()
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: max(0, limit - 3)].rstrip(" ,;|") + "..."


def _is_startup_surface(value: object) -> bool:
    surface = str(value or "").strip().lower()
    return surface.startswith("cli.startup") or surface.endswith(".startup")


def _is_filtered_step(action: str, metadata: Mapping[str, object], *, text: str) -> bool:
    normalized_action = action.strip().lower()
    if normalized_action in _NOISY_STEP_ACTIONS:
        return True
    if str(metadata.get("tool_name") or "").strip():
        return True
    del text
    if str(metadata.get("event_type") or "").strip().lower() == "turn.internal":
        return True
    if _is_startup_surface(metadata.get("source")):
        return True
    return False


def build_episode_summary_text(episode: Episode) -> str:
    """Flatten an `Episode` into an indexable snippet for `semantic_index`.

    Combines exit_summary + entry_surface + metadata notes so a later recall
    query can match on any of them. No record ids in the indexed text — we
    want the semantic index to return content, not ids.
    """
    parts: list[str] = []
    exit_summary = str(getattr(episode, "exit_summary", "") or "").strip()
    entry_surface = str(getattr(episode, "entry_surface", "") or "").strip()
    if exit_summary:
        parts.append(f"exit: {exit_summary}")
    if entry_surface:
        parts.append(f"entry: {entry_surface}")
    metadata = dict(getattr(episode, "metadata", {}) or {})
    for key in ("topic", "focus", "note"):
        value = str(metadata.get(key) or "").strip()
        if value:
            parts.append(f"{key}: {value}")
    return _truncate(" | ".join(parts))


def build_personal_model_claim_text(fact: Fact) -> str:
    """Flatten one active Personal Model claim for semantic recall."""
    metadata = dict(fact.metadata or {})
    pieces = [
        f"lens: {fact.lens}",
        f"topic: {metadata.get('topic', '')}",
        f"claim: {fact.text}",
    ]
    return _truncate(" | ".join(piece for piece in pieces if piece.strip()))


def build_step_recall_text(step: Step) -> str:
    """Flatten a kernel Step into an indexable historical recall document."""
    metadata = dict(step.metadata or {})
    action = str(step.action or "").strip()
    normalized_action = action.lower()
    if normalized_action == "record_input":
        parts = [str(metadata.get("user_query") or metadata.get("raw_user_query") or "").strip()]
    elif normalized_action == "emit_response":
        parts = [str(metadata.get("final_response") or metadata.get("assistant_response") or step.summary).strip()]
    elif normalized_action == "reply":
        parts = [str(step.summary or "").strip(), str(metadata.get("final_response") or metadata.get("assistant_response") or "").strip()]
    else:
        parts = [
            str(step.summary or "").strip(),
            str(metadata.get("user_query") or metadata.get("raw_user_query") or "").strip(),
            str(metadata.get("final_response") or metadata.get("assistant_response") or "").strip(),
        ]
    text = _truncate(" | ".join(dict.fromkeys(part for part in parts if part)))
    if _is_filtered_step(action, metadata, text=text):
        return ""
    return text


def build_learning_summary_recall_text(
    summary: LearningSummaryRecord,
    *,
    path_step: Any | None = None,
    path: Any | None = None,
) -> str:
    """Flatten a Path learning summary into a compact recall document.

    Learning summaries are the durable human-learning artifact for a Path
    step. Raw run rows are operational, so the indexed text deliberately
    favors the human takeaway and knowledge to absorb.
    """
    path_title = str(getattr(path, "title", "") or "").strip()
    step_title = str(getattr(path_step, "title", "") or "").strip()
    step_description = str(getattr(path_step, "description", "") or "").strip()
    pieces = [
        f"path: {path_title}" if path_title else "",
        f"step: {step_title}" if step_title else "",
        step_description,
        f"takeaway: {summary.human_takeaway}" if summary.human_takeaway else "",
        f"knowledge: {summary.knowledge}" if summary.knowledge else "",
        f"what changed: {summary.what_done}" if summary.what_done else "",
        f"why it matters: {summary.why_it_matters}" if summary.why_it_matters else "",
        f"how it was done: {summary.how_it_was_done}" if summary.how_it_was_done else "",
    ]
    return _truncate(" | ".join(part for part in pieces if part.strip()))


def build_diary_entry_recall_text(entry: DiaryEntry) -> str:
    """Flatten a Diary entry into source-backed Personal Model recall text."""
    metadata = dict(entry.metadata or {})
    pieces = [
        f"diary date: {entry.entry_date}",
        f"kind: {metadata.get('kind', '')}",
        f"source: {metadata.get('source', '')}",
        f"sources: {', '.join(entry.source_episode_ids)}" if entry.source_episode_ids else "",
        entry.content,
    ]
    return _truncate(" | ".join(part for part in pieces if part.strip()))


@dataclass(frozen=True, slots=True)
class SemanticSummaryBackfillResult:
    facts_indexed: int = 0
    episodes_indexed: int = 0
    steps_indexed: int = 0
    learning_summaries_indexed: int = 0
    diary_entries_indexed: int = 0

    @property
    def total_indexed(self) -> int:
        return (
            self.facts_indexed
            + self.episodes_indexed
            + self.steps_indexed
            + self.learning_summaries_indexed
            + self.diary_entries_indexed
        )


@dataclass(frozen=True, slots=True)
class SemanticSummaryIndexer:
    """Best-effort bridge from committed content → semantic_index.

    `semantic_index`: SemanticIndexService | None — when None, all methods no-op.
    `embedding_service`: an object exposing `embed_text(text, *, request_id, ...)
                        -> EmbeddingVector` (matches `DefaultEmbeddingService`).
    `repository`: optional RuntimeStorageRepository. When provided and the
                  Step, Episode, and Fact sources are reconstructed from their
                  canonical tables plus semantic index metadata.
    """

    semantic_index: Any = None
    embedding_service: Any = None
    repository: Any = None
    provider_id: str = ""
    model_id: str = ""

    def _embed(self, text: str) -> tuple[Any | None, int]:
        service = self.embedding_service
        if service is None or not text.strip():
            return None, 0
        try:
            vec = service.embed_text(
                text,
                request_id=f"summary-index-{uuid4().hex}",
                task="index",
                latency_mode="balanced",
            )
        except Exception:
            LOGGER.debug("Semantic summary embedding failed.", exc_info=True)
            return None, 0
        try:
            return vec.values, int(vec.dimensions)
        except AttributeError:
            LOGGER.debug("Semantic summary embedding returned an invalid vector.", exc_info=True)
            return None, 0

    def _index(
        self,
        *,
        text: str,
        source_id: str,
        owner_scope: str,
        personal_model_id: str | None,
        state_id: str | None,
        metadata: Mapping[str, str] | None = None,
    ) -> object | None:
        service = self.semantic_index
        if service is None:
            return None
        if not source_id.strip() or not text.strip():
            return None
        vec_values, dimensions = self._embed(text)
        if vec_values is None or dimensions <= 0:
            return None
        try:
            from packages.semantic_index import SemanticIndexDocument
        except Exception:
            LOGGER.debug("Semantic index document contract is unavailable.", exc_info=True)
            return None
        provider_id = self.provider_id or (
            getattr(self.embedding_service, "registry", None)
            and getattr(self.embedding_service.registry.default(), "provider_id", "")
            or ""
        )
        model_id = self.model_id or (
            getattr(self.embedding_service, "registry", None)
            and getattr(self.embedding_service.registry.default(), "model_id", "")
            or ""
        )
        if not provider_id or not model_id:
            return None
        try:
            document = SemanticIndexDocument(
                source_id=source_id,
                owner_scope=owner_scope,
                text=text,
                vector=tuple(vec_values),
                provider_id=provider_id,
                model_id=model_id,
                dimensions=dimensions,
                personal_model_id=personal_model_id,
                state_id=state_id,
                metadata={k: str(v) for k, v in dict(metadata or {}).items()},
            )
        except Exception:
            LOGGER.debug("Failed to build semantic summary index document for %s.", source_id, exc_info=True)
            return None
        try:
            return service.index_document(document)
        except Exception:
            LOGGER.debug("Semantic summary indexing failed for %s.", source_id, exc_info=True)
            return None

    def index_episode_exit(self, episode: Episode) -> object | None:
        """Index an Episode's exit_summary for cross-episode recall."""
        if episode is None:
            return None
        text = build_episode_summary_text(episode)
        if not text:
            return None
        personal_model_id = str(getattr(episode, "personal_model_id", "") or "").strip() or None
        state_id = str(getattr(episode, "state_id", "") or "").strip() or None
        return self._index(
            text=text,
            source_id=f"episode:{episode.episode_id}",
            owner_scope="state",
            personal_model_id=personal_model_id,
            state_id=state_id,
            metadata={
                "kind": "episode_summary",
                "episode_id": episode.episode_id,
                "status": str(getattr(episode, "status", "") or ""),
                "retention_lifecycle": "episode",
            },
        )

    def index_step(self, step: Step) -> object | None:
        """Index one kernel Step as historical recall material."""
        if step is None:
            return None
        text = build_step_recall_text(step)
        if not text:
            return None
        metadata = dict(step.metadata or {})
        return self._index(
            text=text,
            source_id=f"step:{step.step_id}",
            owner_scope="state",
            personal_model_id=step.personal_model_id,
            state_id=step.state_id,
            metadata={
                "kind": "step",
                "step_id": step.step_id,
                "loop_id": step.loop_id,
                "episode_id": step.episode_id,
                "action": step.action,
                "phase": step.phase,
                "status": step.status,
                "retention_lifecycle": "episode",
            },
        )

    def index_personal_model_claim(self, fact: Fact) -> object | None:
        """Index one active Personal Model claim for future recall."""
        if fact is None or fact.status != "active":
            return None
        text = build_personal_model_claim_text(fact)
        if not text:
            return None
        metadata = dict(fact.metadata or {})
        return self._index(
            text=text,
            source_id=fact.fact_id,
            owner_scope="personal_model",
            personal_model_id=fact.personal_model_id,
            state_id=None,
            metadata={
                "kind": "personal_model_claim",
                "claim_ref": fact.fact_id,
                "lens": fact.lens,
                "topic": str(metadata.get("topic") or ""),
                "text": fact.text,
                "reason": str(metadata.get("reason") or ""),
                "confidence": str(fact.confidence),
                "retention_lifecycle": "preference",
            },
        )

    def index_learning_summary(
        self,
        summary: LearningSummaryRecord,
        *,
        path_step: Any | None = None,
        path: Any | None = None,
    ) -> object | None:
        """Index one Path learning summary as user-visible recall material."""
        if summary is None:
            return None
        resolved_step = path_step or self._load_path_step(summary.path_step_id)
        resolved_path = path or self._load_path(summary.path_id)
        text = build_learning_summary_recall_text(
            summary,
            path_step=resolved_step,
            path=resolved_path,
        )
        if not text:
            return None
        personal_model_id = (
            str(getattr(resolved_step, "personal_model_id", "") or "").strip()
            or str(getattr(resolved_path, "personal_model_id", "") or "").strip()
            or None
        )
        return self._index(
            text=text,
            source_id=f"path:learning_summary:{summary.summary_id}",
            owner_scope="personal_model",
            personal_model_id=personal_model_id,
            state_id=None,
            metadata={
                "kind": "path_learning_summary",
                "layer_type": "path_learning_summary",
                "path_id": summary.path_id,
                "path_step_id": summary.path_step_id,
                "summary_id": summary.summary_id,
                "run_id": summary.run_id,
                "summary_type": summary.summary_type,
                "retention_lifecycle": "path",
            },
        )

    def index_diary_entry(self, entry: DiaryEntry) -> object | None:
        """Index one Diary entry as durable source-backed Personal Model recall."""
        if entry is None:
            return None
        text = build_diary_entry_recall_text(entry)
        if not text:
            return None
        personal_model_id = str(entry.personal_model_id or "").strip() or None
        source_id = _diary_entry_source_id(
            personal_model_id=personal_model_id,
            entry_date=entry.entry_date,
        )
        self._mark_previous_source_entries_deleted(
            source_id=source_id,
            personal_model_id=personal_model_id,
            deleted_by="diary_reindex",
        )
        return self._index(
            text=text,
            source_id=source_id,
            owner_scope="personal_model",
            personal_model_id=personal_model_id,
            state_id=None,
            metadata={
                "kind": "diary_entry",
                "layer_type": "diary_entry",
                "entry_id": entry.entry_id,
                "entry_date": entry.entry_date,
                "source_episode_ids": ",".join(entry.source_episode_ids),
                "retention_lifecycle": "diary",
            },
        )

    def _mark_previous_source_entries_deleted(
        self,
        *,
        source_id: str,
        personal_model_id: str | None,
        deleted_by: str,
    ) -> int:
        list_entries = getattr(self.repository, "list_semantic_index_entries", None)
        upsert_entry = getattr(self.repository, "upsert_semantic_index_entry", None)
        if not callable(list_entries) or not callable(upsert_entry):
            return 0
        try:
            entries = list_entries(
                owner_scope="personal_model",
                personal_model_id=personal_model_id,
            )
        except Exception:
            LOGGER.debug("Failed to list previous semantic source entries for reindex.", exc_info=True)
            return 0
        now = _utc_now()
        updated = 0
        for entry in entries:
            if str(getattr(entry, "source_id", "") or "") != source_id:
                continue
            if str(getattr(entry, "status", "") or "").strip().lower() == "deleted":
                continue
            try:
                upsert_entry(
                    replace(
                        entry,
                        status="deleted",
                        updated_at=now,
                        metadata={
                            **dict(getattr(entry, "metadata", {}) or {}),
                            "retention_lifecycle_status": "deleted",
                            "deleted_by": deleted_by,
                        },
                    )
                )
                updated += 1
            except Exception:
                LOGGER.debug("Failed to mark previous semantic source entry deleted.", exc_info=True)
        return updated

    def _load_path_step(self, path_step_id: str) -> Any | None:
        load_path_step = getattr(self.repository, "load_path_step", None)
        if not callable(load_path_step) or not path_step_id:
            return None
        try:
            return load_path_step(path_step_id)
        except Exception:
            LOGGER.debug("Failed to load Path step for semantic summary indexing.", exc_info=True)
            return None

    def _load_path(self, path_id: str) -> Any | None:
        load_path = getattr(self.repository, "load_path", None)
        if not callable(load_path) or not path_id:
            return None
        try:
            return load_path(path_id)
        except Exception:
            LOGGER.debug("Failed to load Path for semantic summary indexing.", exc_info=True)
            return None


def _existing_semantic_source_ids(repository: Any) -> set[str]:
    list_entries = getattr(repository, "list_semantic_index_entries", None)
    if not callable(list_entries):
        return set()
    try:
        entries = list_entries()
    except Exception:
        LOGGER.debug("Failed to list semantic index entries before backfill.", exc_info=True)
        return set()
    return {
        str(getattr(entry, "source_id", "") or "").strip()
        for entry in entries
        if str(getattr(entry, "status", "") or "").strip().lower() != "deleted"
    }


def _personal_model_ids(repository: Any) -> tuple[str, ...]:
    ids: list[str] = []
    list_models = getattr(repository, "list_personal_models", None)
    if callable(list_models):
        try:
            ids.extend(
                str(getattr(model, "personal_model_id", "") or "").strip()
                for model in list_models()
            )
        except Exception:
            LOGGER.debug("Failed to list Personal Models for semantic backfill.", exc_info=True)
    current_state = getattr(repository, "current_state", None)
    if callable(current_state):
        try:
            state = current_state()
            ids.append(str(getattr(state, "personal_model_id", "") or "").strip())
        except Exception:
            LOGGER.debug("Failed to inspect current state for semantic backfill.", exc_info=True)
    return tuple(dict.fromkeys(item for item in ids if item))


def _diary_entry_source_id(*, personal_model_id: str | None, entry_date: str) -> str:
    pm_id = str(personal_model_id or "").strip() or "you"
    return f"diary:{pm_id}:{str(entry_date or '').strip()}"


def backfill_existing_semantic_summaries(
    *,
    repository: Any,
    indexer: SemanticSummaryIndexer | None,
    personal_model_limit: int = 128,
    episode_limit: int = 80,
    step_limit: int = 160,
    learning_summary_limit: int = 160,
    diary_entry_limit: int = 160,
) -> SemanticSummaryBackfillResult:
    """Index existing committed records so upgraded runtimes do not start with empty recall."""

    if repository is None or indexer is None:
        return SemanticSummaryBackfillResult()
    source_ids = _existing_semantic_source_ids(repository)
    facts_indexed = 0
    episodes_indexed = 0
    steps_indexed = 0
    learning_summaries_indexed = 0
    diary_entries_indexed = 0

    list_facts = getattr(repository, "list_personal_model_facts", None)
    if callable(list_facts):
        for personal_model_id in _personal_model_ids(repository):
            if facts_indexed >= personal_model_limit:
                break
            try:
                facts = list_facts(personal_model_id=personal_model_id, status="active")
            except Exception:
                LOGGER.debug("Failed to list Personal Model facts for semantic backfill.", exc_info=True)
                continue
            for fact in facts:
                if facts_indexed >= personal_model_limit:
                    break
                source_id = str(getattr(fact, "fact_id", "") or "").strip()
                if not source_id or source_id in source_ids:
                    continue
                if indexer.index_personal_model_claim(fact) is not None:
                    facts_indexed += 1
                    source_ids.add(source_id)

    list_episodes = getattr(repository, "list_episodes", None)
    if callable(list_episodes):
        try:
            episodes = list_episodes(status="closed", newest_first=True, limit=episode_limit)
        except Exception:
            LOGGER.debug("Failed to list Episodes for semantic backfill.", exc_info=True)
            episodes = ()
        for episode in episodes:
            source_id = f"episode:{getattr(episode, 'episode_id', '')}"
            if source_id in source_ids:
                continue
            if not str(getattr(episode, "exit_summary", "") or "").strip():
                continue
            if indexer.index_episode_exit(episode) is not None:
                episodes_indexed += 1
                source_ids.add(source_id)

    list_steps = getattr(repository, "list_steps", None)
    if callable(list_steps):
        try:
            steps = list_steps(newest_first=True, limit=step_limit)
        except Exception:
            LOGGER.debug("Failed to list Steps for semantic backfill.", exc_info=True)
            steps = ()
        for step in steps:
            source_id = f"step:{getattr(step, 'step_id', '')}"
            if source_id in source_ids:
                continue
            if indexer.index_step(step) is not None:
                steps_indexed += 1
                source_ids.add(source_id)

    list_learning_summaries = getattr(repository, "list_learning_summaries", None)
    if callable(list_learning_summaries):
        try:
            summaries = list_learning_summaries(limit=learning_summary_limit)
        except Exception:
            LOGGER.debug("Failed to list Path learning summaries for semantic backfill.", exc_info=True)
            summaries = ()
        for summary in summaries:
            source_id = f"path:learning_summary:{getattr(summary, 'summary_id', '')}"
            if source_id in source_ids:
                continue
            if indexer.index_learning_summary(summary) is not None:
                learning_summaries_indexed += 1
                source_ids.add(source_id)

    list_diary_entries = getattr(repository, "list_diary_entries", None)
    if callable(list_diary_entries):
        for personal_model_id in _personal_model_ids(repository):
            if diary_entries_indexed >= diary_entry_limit:
                break
            try:
                entries = list_diary_entries(
                    personal_model_id=personal_model_id,
                    limit=diary_entry_limit,
                )
            except Exception:
                LOGGER.debug("Failed to list Diary entries for semantic backfill.", exc_info=True)
                continue
            for entry in entries:
                if diary_entries_indexed >= diary_entry_limit:
                    break
                source_id = _diary_entry_source_id(
                    personal_model_id=getattr(entry, "personal_model_id", personal_model_id),
                    entry_date=getattr(entry, "entry_date", ""),
                )
                if source_id in source_ids:
                    continue
                if indexer.index_diary_entry(entry) is not None:
                    diary_entries_indexed += 1
                    source_ids.add(source_id)

    return SemanticSummaryBackfillResult(
        facts_indexed=facts_indexed,
        episodes_indexed=episodes_indexed,
        steps_indexed=steps_indexed,
        learning_summaries_indexed=learning_summaries_indexed,
        diary_entries_indexed=diary_entries_indexed,
    )
