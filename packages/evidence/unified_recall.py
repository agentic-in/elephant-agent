"""Unified recall entry point shared by CLI / API / Gateway / prefetch.

Before: call sites duplicated the "load sources → wrap as RecallCandidate
→ rank_recall_candidates()" pattern with slightly different filters. The
hybrid semantic index was implemented but not consistently consulted.

Now: every surface calls `unified_recall(...)` which:

  1. Tries the shared `HybridSemanticSearcher` (vector + BM25 + exact +
     ngram RRF fusion) against the SAME durable SQLite-vec index the
     producer side (episode close hook, personal-model indexer) writes to.
  2. Falls back to `rank_recall_candidates` (token-overlap + CJK
     n-grams) when the embedding runtime is cold, the query is empty, or
     no hybrid hit comes back — so recall still returns something sane
     during index steadyup.

Output: a homogeneous `tuple[RecallHit, ...]` — no record ids leak to
the caller.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import re
from typing import Any, Mapping, Protocol

from packages.contracts import SemanticIndexEntry
from packages.semantic_index import (
    HybridSemanticSearcher,
    SemanticSearchQuery,
)

from .recall_support import (
    RecallCandidate,
    RecallHit,
    rank_recall_candidates,
)
from .recall_time_range import RecallTimeRange, recall_time_range_from_payload
from .recall_planning import plan_recall_query
from .recall_rerank import rerank_recall_hits


__all__ = [
    "RecallDocument",
    "RecallTimeRange",
    "CONVERSATION_RECALL_SCOPES",
    "CONVERSATION_SEARCH_SCOPES",
    "UnifiedRecallRepository",
    "UnifiedRecallRequest",
    "conversation_scopes_for_view",
    "recall_timeline",
    "unified_recall",
    "recall_time_range_from_payload",
    "candidates_from_episodes",
    "candidates_from_steps",
    "summarize_recall_hits",
]


# Debug/raw recall may inspect all historical material. The public conversation
# search tool defaults to `CONVERSATION_SEARCH_SCOPES` so internal source/tool
# material does not compete with user-visible turns and episode summaries.
CONVERSATION_RECALL_SCOPES = ("steps", "episodes")
CONVERSATION_SEARCH_SCOPES = ("steps", "episodes")
_SCOPE_TO_OWNER_SCOPE: Mapping[str, str] = {
    "personal_model": "personal_model",
    "state": "state",
    "steps": "state",
    "episodes": "state",
    "episode": "state",
}
_TEXT_ANCHOR_SIGNALS = frozenset({"token_coverage", "keyword_exact", "bm25", "ngram"})
_QUERY_TOKEN_RE = re.compile(r"[A-Za-z0-9_./:-]+")
_QUERY_CJK_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")
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
_USER_TURN_ACTIONS = frozenset({"record_input"})
_ASSISTANT_TURN_ACTIONS = frozenset({"emit_response", "reply"})


def conversation_scopes_for_view(view: object) -> tuple[str, ...]:
    resolved = str(view or "conversation").strip().lower()
    if resolved == "debug":
        return CONVERSATION_RECALL_SCOPES
    return CONVERSATION_SEARCH_SCOPES


@dataclass(frozen=True, slots=True)
class RecallDocument:
    document_id: str
    kind: str
    text: str
    scope: str
    when: datetime | None = None
    personal_model_id: str | None = None
    state_id: str | None = None
    episode_id: str | None = None
    loop_id: str | None = None
    step_id: str | None = None
    source_id: str | None = None
    metadata: Mapping[str, str] | None = None
    importance: float = 0.5

    def candidate(self) -> RecallCandidate:
        metadata = {
            **dict(self.metadata or {}),
            "document_id": self.document_id,
            "scope": self.scope,
            "episode_id": self.episode_id or "",
            "loop_id": self.loop_id or "",
            "step_id": self.step_id or "",
            "source_id": self.source_id or "",
        }
        return RecallCandidate(
            title=self.text[:72].strip() or self.kind,
            body=self.text,
            kind=self.kind,
            when=self.when,
            extra_metadata=metadata,
            importance=max(0.0, min(1.0, self.importance)),
        )


@dataclass(frozen=True, slots=True)
class UnifiedRecallRequest:
    query: str
    scopes: tuple[str, ...]
    personal_model_id: str
    state_id: str | None
    limit: int
    time_range: RecallTimeRange | None = None
    now: datetime | None = None
    view: str = "raw"
    exclude_episode_ids: tuple[str, ...] = ()


class UnifiedRecallRepository(Protocol):
    """Subset of ``RuntimeStorageRepository`` that unified_recall needs.

    CLI/API/Gateway all pass their runtime repository; it satisfies this
    protocol already via the storage package.
    """

    def list_episodes(
        self,
        *,
        state_id: str | None = None,
        limit: int | None = None,
    ) -> tuple[Any, ...]:
        ...

    def list_steps(self, *, loop_id: str | None = None) -> tuple[Any, ...]:
        ...

    def list_semantic_index_entries(
        self,
        *,
        owner_scope: str | None = None,
        state_id: str | None = None,
        personal_model_id: str | None = None,
        provider_id: str | None = None,
        model_id: str | None = None,
    ) -> tuple[SemanticIndexEntry, ...]:
        ...


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _in_time_range(when: datetime | None, time_range: RecallTimeRange | None) -> bool:
    return True if time_range is None else time_range.contains(when)


def _excluded_episode_ids(values: Iterable[str]) -> frozenset[str]:
    return frozenset(str(value or "").strip() for value in values if str(value or "").strip())


def _is_excluded_episode(episode_id: object, excluded_episode_ids: frozenset[str]) -> bool:
    return bool(str(episode_id or "").strip() in excluded_episode_ids)


def _is_startup_surface(value: object) -> bool:
    surface = str(value or "").strip().lower()
    return surface.startswith("cli.startup") or surface.endswith(".startup")


def _metadata_tool_name(metadata: Mapping[str, str]) -> str:
    return str(metadata.get("tool_name") or "").strip()


def _is_filtered_step(action: str, metadata: Mapping[str, str], *, text: str = "") -> bool:
    normalized_action = action.strip().lower()
    if normalized_action in _NOISY_STEP_ACTIONS:
        return True
    if _metadata_tool_name(metadata):
        return True
    if str(metadata.get("event_type") or "").strip().lower() == "turn.internal":
        return True
    if _is_startup_surface(metadata.get("source")):
        return True
    return False


def _step_display_kind(action: str) -> str:
    normalized = action.strip().lower()
    if normalized in _USER_TURN_ACTIONS:
        return "turn:user"
    if normalized in _ASSISTANT_TURN_ACTIONS:
        return "turn:assistant"
    return f"step:{action or 'event'}"


def _step_importance(action: str) -> float:
    normalized = action.strip().lower()
    if normalized in _USER_TURN_ACTIONS | _ASSISTANT_TURN_ACTIONS:
        return 0.75
    return 0.45


def _is_step_document(document: Any | None) -> bool:
    if document is None:
        return False
    metadata = dict(getattr(document, "metadata", {}) or {})
    source_id = str(getattr(document, "source_id", "") or getattr(document, "document_id", "") or "")
    return (
        str(getattr(document, "schema_version", "") or "") == "step/v1"
        or str(getattr(document, "layer_type", "") or "") == "step"
        or str(metadata.get("kind") or "") == "step"
        or source_id.startswith("step:")
    )


def _is_episode_document(document: Any | None) -> bool:
    if document is None:
        return False
    source_id = str(getattr(document, "source_id", "") or getattr(document, "document_id", "") or "")
    return (
        str(getattr(document, "schema_version", "") or "") == "episode_summary/v1"
        or str(getattr(document, "layer_type", "") or "") == "episode_summary"
        or source_id.startswith("episode:")
    )


def documents_from_episodes(episodes: Iterable[Any]) -> list[RecallDocument]:
    out: list[RecallDocument] = []
    for episode in episodes:
        summary = str(getattr(episode, "exit_summary", "") or "").strip()
        entry_surface = str(getattr(episode, "entry_surface", "") or "").strip()
        metadata = dict(getattr(episode, "metadata", {}) or {})
        body = " | ".join(part for part in (summary, entry_surface, metadata.get("topic", ""), metadata.get("focus", ""), metadata.get("note", "")) if str(part or "").strip())
        if not body:
            continue
        out.append(
            RecallDocument(
                document_id=str(getattr(episode, "episode_id", "") or body[:32]),
                kind="episode_summary",
                text=body,
                scope="episodes",
                when=getattr(episode, "ended_at", None) or getattr(episode, "started_at", None),
                personal_model_id=getattr(episode, "personal_model_id", None),
                state_id=getattr(episode, "state_id", None),
                episode_id=getattr(episode, "episode_id", None),
                metadata={**{str(k): str(v) for k, v in metadata.items()}, "recall_source": "episode"},
            )
        )
    return out


def candidates_from_episodes(episodes: Iterable[Any]) -> list[RecallCandidate]:
    return [document.candidate() for document in documents_from_episodes(episodes)]


def documents_from_steps(steps: Iterable[Any]) -> list[RecallDocument]:
    out: list[RecallDocument] = []
    for step in steps:
        metadata = {str(k): str(v) for k, v in dict(getattr(step, "metadata", {}) or {}).items()}
        text = _step_text(step, metadata)
        if not text:
            continue
        payload_refs = tuple(getattr(step, "payload_refs", ()) or ())
        out.append(
            RecallDocument(
                document_id=str(getattr(step, "step_id", "") or text[:32]),
                kind=_step_display_kind(str(getattr(step, "action", "") or getattr(step, "phase", "") or "event")),
                text=text,
                scope="steps",
                when=getattr(step, "created_at", None),
                personal_model_id=getattr(step, "personal_model_id", None),
                state_id=getattr(step, "state_id", None),
                episode_id=getattr(step, "episode_id", None),
                loop_id=getattr(step, "loop_id", None),
                step_id=getattr(step, "step_id", None),
                source_id=str(payload_refs[0]) if payload_refs else None,
                metadata={**metadata, "recall_source": "step", "owner_scope": "state"},
                importance=_step_importance(str(getattr(step, "action", "") or "")),
            )
        )
    return out


def candidates_from_steps(steps: Iterable[Any]) -> list[RecallCandidate]:
    return [document.candidate() for document in documents_from_steps(steps)]


def _step_text(step: Any, metadata: Mapping[str, str]) -> str:
    action = str(getattr(step, "action", "") or "").strip()
    normalized_action = action.lower()
    summary = str(getattr(step, "summary", "") or "").strip()
    if normalized_action == "record_input":
        parts = [str(metadata.get("user_query") or metadata.get("raw_user_query") or "").strip()]
    elif normalized_action == "emit_response":
        parts = [str(metadata.get("final_response") or metadata.get("assistant_response") or summary).strip()]
    elif normalized_action == "reply":
        parts = [summary, str(metadata.get("final_response") or metadata.get("assistant_response") or "").strip()]
    else:
        parts = [
            summary,
            str(metadata.get("user_query") or metadata.get("raw_user_query") or "").strip(),
            str(metadata.get("final_response") or metadata.get("assistant_response") or "").strip(),
        ]
    text = " | ".join(dict.fromkeys(part for part in parts if part))
    if _is_filtered_step(action, metadata, text=text):
        return ""
    return text


def _collect_recall_documents(
    *,
    repository: UnifiedRecallRepository,
    scopes: tuple[str, ...],
    personal_model_id: str,
    state_id: str | None,
    episodes_cap: int,
    time_range: RecallTimeRange | None,
    exclude_episode_ids: tuple[str, ...] = (),
) -> list[RecallDocument]:
    documents: list[RecallDocument] = []
    excluded = _excluded_episode_ids(exclude_episode_ids)
    for scope in scopes:
        if scope in {"episodes", "episode"}:
            try:
                episodes = repository.list_episodes(state_id=state_id, limit=episodes_cap)
            except TypeError:
                try:
                    episodes = repository.list_episodes(state_id=state_id)
                except Exception:
                    episodes = ()
            except Exception:
                episodes = ()
            documents.extend(
                document for document in documents_from_episodes(episodes or ())
                if not _is_excluded_episode(document.episode_id, excluded)
            )
        elif scope == "steps":
            try:
                steps = repository.list_steps()
            except Exception:
                steps = ()
            documents.extend(
                document for document in documents_from_steps(steps or ())
                if (not state_id or document.state_id in {None, "", state_id})
                and not _is_excluded_episode(document.episode_id, excluded)
            )
        # Legacy scopes (personal_model, state, sources) are no longer supported.
        # Steps + episodes + semantic index are the canonical search path.
    return [
        document for document in documents
        if _in_time_range(document.when, time_range)
        and not _is_excluded_episode(document.episode_id, excluded)
    ]


def _collect_fallback_candidates(
    *,
    repository: UnifiedRecallRepository,
    scopes: tuple[str, ...],
    personal_model_id: str,
    state_id: str | None,
    episodes_cap: int,
    time_range: RecallTimeRange | None,
    exclude_episode_ids: tuple[str, ...] = (),
) -> list[RecallCandidate]:
    return [
        document.candidate()
        for document in _collect_recall_documents(
            repository=repository,
            scopes=scopes,
            personal_model_id=personal_model_id,
            state_id=state_id,
            episodes_cap=episodes_cap,
            time_range=time_range,
            exclude_episode_ids=exclude_episode_ids,
        )
    ]


def _query_needs_text_anchor(query: str) -> bool:
    text = str(query or "").strip()
    if not text:
        return False
    tokens = _QUERY_TOKEN_RE.findall(text)
    cjk = _QUERY_CJK_RE.findall(text)
    return len(tokens) <= 2 and len(cjk) <= 8


def _match_has_text_anchor(match: Any) -> bool:
    reasons = set(str(reason) for reason in tuple(getattr(match, "reasons", ()) or ()))
    signal_scores = set(str(key) for key in dict(getattr(match, "signal_scores", {}) or {}).keys())
    return bool(_TEXT_ANCHOR_SIGNALS.intersection(reasons | signal_scores))


def _semantic_step_is_noise(document: Any | None, hit: RecallHit | None = None) -> bool:
    if document is None:
        return True
    metadata = {str(k): str(v) for k, v in dict(getattr(document, "metadata", {}) or {}).items()}
    action = str(metadata.get("action") or "").strip()
    text = str(getattr(hit, "content", "") if hit is not None else "")
    if not text:
        payload = dict(getattr(document, "payload", {}) or {})
        text = str(payload.get("text") or payload.get("content") or payload.get("summary") or "")
    return _is_filtered_step(action, metadata, text=text)


def _hit_from_match(match: Any, document: Any | None) -> RecallHit | None:
    """Build a human-readable hit from a HybridSemanticSearcher match."""
    entry = getattr(match, "semantic_index_entry", None)
    owner_scope = str(getattr(entry, "owner_scope", "") or "")
    metadata: Mapping[str, str] = getattr(entry, "metadata", {}) or {}
    when_value: datetime | None = getattr(entry, "created_at", None)
    if document is not None:
        when_value = getattr(document, "created_at", when_value) or when_value

    text = ""
    if document is not None:
        payload = document.payload or {}
        if isinstance(payload, Mapping):
            for key in ("content", "text", "summary", "title"):
                candidate = str(payload.get(key) or "").strip()
                if candidate:
                    text = candidate
                    break
    if not text:
        text = str(metadata.get("text") or "").strip()
    if not text:
        return None

    kind_label = str(metadata.get("kind") or "").strip() or owner_scope or "note"
    if kind_label == "step":
        kind_label = _step_display_kind(str(metadata.get("action") or ""))
    display_when = ""
    if when_value is not None:
        display_when = when_value.strftime("%Y-%m-%d")

    hit_metadata = {
        **dict(metadata),
        "owner_scope": owner_scope,
        "schema_version": str(getattr(document, "schema_version", "") or "") if document is not None else "",
        "layer_type": str(getattr(document, "layer_type", "") or "") if document is not None else "",
        "semantic_reasons": ",".join(str(reason) for reason in tuple(getattr(match, "reasons", ()) or ())),
    }
    return RecallHit(
        title=text[:72].strip() or kind_label,
        content=text,
        kind=kind_label,
        when=display_when,
        score=float(getattr(match, "score", 0.0) or 0.0),
        when_datetime=when_value,
        extra_metadata=hit_metadata,
    )


def summarize_recall_hits(
    hits: "tuple[RecallHit, ...]",
    *,
    max_lines: int = 5,
    char_budget: int = 400,
) -> str:
    """Render multiple hits as a compact time-anchored narrative.

    Why this exists: the raw RecallHit stream is good for machine ranking
    but not for LLM consumption. Hermes-agent's `session_search` returns
    narrative lines like "4月15日和 Alice 聊过 AA 项目：结论是X" because
    that's both (a) shorter than raw hits, (b) easier for the model
    to assimilate into its next reply. Mem0 (2025) and Letta also funnel
    recall output through a compact narrative layer before prompt
    injection.

    Strategy (deterministic, no LLM): group hits by `kind`, prefix the
    line with the day (`when`) when present, truncate each hit to a
    fair share of the char budget. Preserves the existing "no ids
    leak" contract. Returns "" for empty input so callers can drop
    it into an f-string unconditionally.

    Call this from Personal Model search surfaces or current-turn prompt
    prefetch before joining hits into a multi-line human display. The default `unified_recall` path
    returns hits unsummarised so programmatic callers keep structured
    data.
    """
    if not hits:
        return ""
    lines: list[str] = []
    total = 0
    per_hit_budget = max(1, char_budget // max(min(len(hits), max_lines), 1))
    for hit in hits[:max_lines]:
        prefix = f"[{hit.when}] " if hit.when else ""
        kind = hit.kind or "note"
        body = hit.content.strip()
        if len(body) > per_hit_budget:
            body = body[: per_hit_budget - 1].rstrip(" ,;|.") + "…"
        line = f"{prefix}({kind}) {body}"
        if total + len(line) > char_budget and lines:
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)


def _bucket_start(value: datetime, *, bucket: str, tz: timezone | ZoneInfo | None = None) -> datetime:
    when = _aware(value).astimezone(tz) if tz is not None else _aware(value)
    if bucket == "day":
        return when.replace(hour=0, minute=0, second=0, microsecond=0)
    return when.replace(minute=0, second=0, microsecond=0)


def _bucket_end(start: datetime, *, bucket: str) -> datetime:
    return start + (timedelta(days=1) if bucket == "day" else timedelta(hours=1))


def _query_terms(query: str) -> set[str]:
    text = str(query or "").strip().lower()
    terms = {token for token in _QUERY_TOKEN_RE.findall(text) if token}
    terms.update(_QUERY_CJK_RE.findall(text))
    return terms


def _text_relevance_score(query: str, text: str) -> float:
    terms = _query_terms(query)
    if not terms:
        return 0.0
    normalized = str(text or "").lower()
    hits = sum(1 for term in terms if term and term in normalized)
    return hits / max(len(terms), 1)


def _anchor_text(text: str, *, limit: int = 96) -> str:
    compacted = " ".join(str(text or "").split()).strip()
    if len(compacted) <= limit:
        return compacted
    return compacted[: max(1, limit - 1)].rstrip(" ,;|.") + "…"


def _anchor_priority(document: RecallDocument, query: str) -> tuple[int, float, float]:
    kind_priority = {"turn:user": 0, "episode_summary": 1, "turn:assistant": 2}.get(document.kind, 3)
    when_ts = _aware(document.when).timestamp() if document.when is not None else 0.0
    return (kind_priority, -_text_relevance_score(query, document.text), when_ts)


def _range_time_range_payload(start: datetime, end: datetime, *, timezone_name: str = "") -> dict[str, str]:
    out = {
        "start_at": start.isoformat(timespec="minutes"),
        "end_at": end.isoformat(timespec="minutes"),
    }
    if timezone_name:
        out["timezone"] = timezone_name
    return out


def recall_timeline(
    request: UnifiedRecallRequest,
    *,
    repository: UnifiedRecallRepository,
    bucket: str = "hour",
    preview: str = "anchors",
    limit: int = 24,
) -> Mapping[str, object]:
    bucket_value = str(bucket or "auto").strip().lower()
    if bucket_value == "auto":
        time_range = request.time_range
        if time_range is not None and time_range.start_at is not None and time_range.end_at is not None:
            span = _aware(time_range.end_at) - _aware(time_range.start_at)
            resolved_bucket = "day" if span > timedelta(days=3) else "hour"
        else:
            resolved_bucket = "day"
    else:
        resolved_bucket = "day" if bucket_value == "day" else "hour"
    capped = max(1, min(int(limit or 24), 168))
    if request.time_range is None:
        return {
            "total": 0,
            "bucket": resolved_bucket,
            "query": str(request.query or "").strip(),
            "view": request.view,
            "resolved_time_range": {},
            "ranges": (),
            "requires_time_range": True,
            "guidance": "mode=discover requires top-level expr or explicit start_at/end_at; use expr like last_night, yesterday, last:3d, or pass an explicit ISO interval.",
        }
    documents = _collect_recall_documents(
        repository=repository,
        scopes=tuple(request.scopes) or conversation_scopes_for_view(request.view),
        personal_model_id=request.personal_model_id,
        state_id=request.state_id,
        episodes_cap=max(50, capped * 4),
        time_range=request.time_range,
        exclude_episode_ids=request.exclude_episode_ids,
    )
    timeline_tz = request.time_range.start_at.tzinfo if request.time_range.start_at is not None else None
    timezone_name = request.time_range.timezone
    grouped: dict[datetime, list[RecallDocument]] = {}
    for document in documents:
        if document.when is None:
            continue
        grouped.setdefault(_bucket_start(document.when, bucket=resolved_bucket, tz=timeline_tz), []).append(document)
    query = str(request.query or "").strip()
    ranges = []
    for start, grouped_items in grouped.items():
        items = sorted(grouped_items, key=lambda item: _aware(item.when or start))
        by_kind: dict[str, int] = {}
        item_scores = []
        for item in items:
            key = item.kind
            by_kind[key] = by_kind.get(key, 0) + 1
            item_scores.append(_text_relevance_score(query, item.text))
        score = max(item_scores) if item_scores else 0.0
        if query and score <= 0.0:
            continue
        anchor_items = [
            item for item in items
            if item.text.strip() and (not query or _text_relevance_score(query, item.text) > 0.0)
        ]
        anchors = tuple(
            {"kind": item.kind, "text": _anchor_text(item.text)}
            for item in sorted(anchor_items, key=lambda candidate: _anchor_priority(candidate, query))[:3]
        )
        end = _bucket_end(start, bucket=resolved_bucket)
        payload: dict[str, object] = {
            "range_id": f"{resolved_bucket}:{start.isoformat(timespec='minutes')}",
            "start_at": start.isoformat(timespec="minutes"),
            "end_at": end.isoformat(timespec="minutes"),
            "time_range": _range_time_range_payload(start, end, timezone_name=timezone_name),
            "score": round(score, 4),
            "count": len(items),
            "by_kind": by_kind,
        }
        if str(preview or "anchors").strip().lower() == "anchors" and anchors:
            payload["anchors"] = anchors
        ranges.append(payload)
    if query:
        ranges.sort(key=lambda item: (-float(item.get("score", 0.0)), str(item.get("start_at", ""))))
    else:
        ranges.sort(key=lambda item: str(item.get("start_at", "")))
    selected = tuple(ranges[:capped])
    return {
        "total": len(documents),
        "bucket": resolved_bucket,
        "query": query,
        "view": request.view,
        "resolved_time_range": request.time_range.payload() if request.time_range is not None else {},
        "ranges": selected,
    }


def unified_recall(
    request: UnifiedRecallRequest,
    *,
    repository: UnifiedRecallRepository,
    searcher: HybridSemanticSearcher | None = None,
    embedding_service: Any = None,
    embedding_health_callable: Any = None,
) -> tuple[RecallHit, ...]:
    """Run hybrid semantic recall with graceful fallback.

    Args:
        request: query + scopes + personal_model/state scoping + limit.
        repository: durable runtime storage (implements the protocol).
        searcher: optional HybridSemanticSearcher; when None, always fall
            back to rank_recall_candidates.
        embedding_service: optional; when provided together with
            `embedding_health_callable`, is used to compute the query
            vector for better vector signal. Not required for BM25/exact.
        embedding_health_callable: optional no-arg callable returning
            `EmbeddingHealth`; used to skip embedding if the runtime is
            cold.

    Returns:
        tuple of RecallHit ordered best-to-worst.
    """
    capped = max(1, min(int(request.limit or 5), 20))
    now_ts = (request.now or datetime.now(timezone.utc))
    query_plan = plan_recall_query(request.query)
    query = query_plan.search_query.strip()
    scopes = tuple(request.scopes) or CONVERSATION_SEARCH_SCOPES

    time_range = request.time_range
    # Fallback path (cold index / no searcher / empty query).
    use_hybrid = bool(searcher is not None and query)
    if not use_hybrid:
        candidates = _collect_fallback_candidates(
            repository=repository,
            scopes=scopes,
            personal_model_id=request.personal_model_id,
            state_id=request.state_id,
            episodes_cap=max(20, capped * 4),
            time_range=time_range,
            exclude_episode_ids=request.exclude_episode_ids,
        )
        return rank_recall_candidates(request.query, candidates, limit=capped, now=now_ts)

    query_vector: tuple[float, ...] = ()
    query_dimensions: int | None = None
    if embedding_service is not None:
        try:
            if embedding_health_callable is not None:
                health = embedding_health_callable()
                status = str(getattr(health, "status", "") or "").lower()
                if status in {"failed", "unavailable", "disabled"}:
                    raise RuntimeError(status)
            vector = embedding_service.embed_text(
                query,
                request_id="unified-recall-query",
                task="query",
                latency_mode="balanced",
            )
            query_vector = tuple(getattr(vector, "values", ()) or ())
            query_dimensions = int(getattr(vector, "dimensions", 0) or 0) or None
        except Exception:
            query_vector = ()
            query_dimensions = None

    # Attempt hybrid per-scope; collect matches into one ranked list.
    hits: list[RecallHit] = []
    per_scope_limit = max(capped, capped * (8 if time_range is not None else 2), 50 if time_range is not None else capped)
    require_text_anchor = _query_needs_text_anchor(query)
    excluded = _excluded_episode_ids(request.exclude_episode_ids)
    for scope in scopes:
        owner_scope = _SCOPE_TO_OWNER_SCOPE.get(scope)
        if owner_scope is None:
            continue
        try:
            search_query = SemanticSearchQuery(
                text=query,
                vector=query_vector,
                dimensions=query_dimensions,
                owner_scope=owner_scope,
                personal_model_id=(
                    request.personal_model_id if owner_scope == "personal_model" else None
                ),
                state_id=request.state_id if owner_scope == "state" else None,
                start_at=time_range.start_at if time_range is not None else None,
                end_at=time_range.end_at if time_range is not None else None,
                limit=per_scope_limit,
            )
        except ValueError:
            continue
        try:
            matches = searcher.search(search_query)
        except Exception:
            matches = ()
        for match in matches:
            if require_text_anchor and not _match_has_text_anchor(match):
                continue
            document = getattr(match, "document", None)
            if scope == "steps" and not _is_step_document(document):
                continue
            if scope in {"episodes", "episode"} and not _is_episode_document(document):
                continue
            hit = _hit_from_match(match, document)
            if scope == "steps" and _semantic_step_is_noise(document, hit):
                continue
            hit_episode_id = dict(getattr(hit, "extra_metadata", {}) or {}).get("episode_id") if hit is not None else ""
            if hit is not None and not _is_excluded_episode(hit_episode_id, excluded) and _in_time_range(hit.when_datetime, time_range):
                hits.append(hit)

    step_candidates = _collect_fallback_candidates(
        repository=repository,
        scopes=tuple(scope for scope in scopes if scope == "steps"),
        personal_model_id=request.personal_model_id,
        state_id=request.state_id,
        episodes_cap=max(20, capped * 4),
        time_range=time_range,
        exclude_episode_ids=request.exclude_episode_ids,
    )
    hits.extend(rank_recall_candidates(request.query, step_candidates, limit=max(capped, len(step_candidates)), now=now_ts))

    # Merge: sort by relevance plus intent-aware freshness, then de-duplicate by provenance first.
    ranked_hits = rerank_recall_hits(tuple(hits), plan=query_plan, now=now_ts)
    deduped: list[RecallHit] = []
    seen_keys: set[str] = set()
    for ranked_hit in ranked_hits:
        hit = ranked_hit.hit
        metadata = dict(hit.extra_metadata or {})
        provenance = "|".join(
            str(metadata.get(key) or "").strip()
            for key in ("episode_id", "loop_id", "step_id", "source_id")
        ).strip("|")
        key = provenance or hit.content.casefold()
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(hit)
        if len(deduped) >= capped:
            break

    if deduped:
        return tuple(deduped)

    # Hybrid returned 0 — fall back to lexical so the user still sees something
    # meaningful during index steady-up.
    candidates = _collect_fallback_candidates(
        repository=repository,
        scopes=scopes,
        personal_model_id=request.personal_model_id,
        state_id=request.state_id,
        episodes_cap=max(20, capped * 4),
        time_range=time_range,
        exclude_episode_ids=request.exclude_episode_ids,
    )
    return rank_recall_candidates(request.query, candidates, limit=capped, now=now_ts)
