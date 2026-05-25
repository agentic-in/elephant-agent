"""Projection compaction for prompt-only session history views."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime
import hashlib
import logging
import re
import time
from typing import Any

from packages.contracts.layers import Episode
from packages.contracts.runtime import ContextBundle, ExecutionResult, PersonalModelRuntimeState, PromptEnvelope, PromptMessage
from packages.embeddings import EmbeddingPreloadEntry, cosine_similarity, embedding_runtime_is_loaded
from packages.context.projection_types import (
    ContextProjectionCompactionResult,
    ProjectionCompactionPolicy,
    ProjectionSemanticAnchorStats,
    SessionMessageProjection,
)
from packages.context.projection_support import (
    build_projection_query as _build_projection_query,
    compact_text as _compact_text,
    ensure_reference_only_summary as _ensure_reference_only_summary,
    group_end_at_or_after as _group_end_at_or_after,
    latest_user_group as _latest_user_group,
    latest_user_line as _latest_user_line,
    message_groups as _message_groups,
    normalize_prompt_message as _normalize_prompt_message,
    projection_embedding_cache_key as _projection_embedding_cache_key,
    projection_embedding_text as _projection_embedding_text,
    projection_group_preload_entries as _projection_group_preload_entries,
    projection_query_text as _projection_query_text,
    normalize_projection_query_text as _normalize_projection_query_text,
    projection_result_with_estimated_tokens,
    prompt_message_projection_line as _prompt_message_projection_line,
    tool_call_id as _tool_call_id,
    tool_call_name as _tool_call_name,
)

_REFERENCE_ONLY_HEADER = (
    "[CONTEXT COMPACTION - REFERENCE ONLY] Reference summary of earlier completed turns. "
    "Latest live messages and the protected recent tail are authoritative."
)
_CHARS_PER_TOKEN = 4
PROJECTION_EMBEDDING_TARGET = "projection-history"
_PROJECTION_EMBEDDING_TEXT_LIMIT = 1200
_PROJECTION_EMBEDDING_MAX_BACKFILL_ENTRIES = 32
LOGGER = logging.getLogger(__name__)

# Tiktoken encoding for more accurate token estimation (lazy-loaded)
_TIKTOKEN_ENCODING = None
_USE_TIKTOKEN = False


def _get_tiktoken_encoding():
    """Lazily load tiktoken encoding to avoid import-time network access."""
    global _TIKTOKEN_ENCODING, _USE_TIKTOKEN
    if _TIKTOKEN_ENCODING is not None:
        return _TIKTOKEN_ENCODING
    try:
        import tiktoken
        _TIKTOKEN_ENCODING = tiktoken.get_encoding("cl100k_base")
        _USE_TIKTOKEN = True
        return _TIKTOKEN_ENCODING
    except (ImportError, Exception):
        LOGGER.debug("Tiktoken encoding unavailable; using projection token fallback.", exc_info=True)
        _USE_TIKTOKEN = False
        return None


def estimate_projection_tokens(text: str) -> int:
    """Return a rough, deterministic token estimate for projection text."""
    normalized = str(text or "")
    if not normalized:
        return 0
    
    # Use tiktoken for more accurate estimation if available
    encoding = _get_tiktoken_encoding()
    if encoding is not None:
        try:
            return len(encoding.encode(normalized))
        except Exception:
            LOGGER.debug("Tiktoken encode failed; using projection token fallback.", exc_info=True)
    
    # Fallback to character-based estimation
    return max(1, len(normalized) // _CHARS_PER_TOKEN)


def estimate_projection_lines_tokens(lines: tuple[str, ...]) -> int:
    return estimate_projection_tokens("\n".join(lines))


def _protected_ranges(*, message_count: int, head_count: int, tail_count: int) -> tuple[str, ...]:
    total = max(0, int(message_count))
    if total <= 0:
        return ()
    normalized_head = max(0, min(int(head_count), total))
    normalized_tail = max(0, min(int(tail_count), max(0, total - normalized_head)))
    ranges: list[str] = []
    if normalized_head > 0:
        ranges.append(f"head:0-{normalized_head - 1}")
    if normalized_tail > 0:
        ranges.append(f"tail:{total - normalized_tail}-{total - 1}")
    return tuple(ranges)


def _projection_summary_hash(summary: str) -> str:
    normalized = str(summary or "").strip()
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


class CheapToolResultPruner:
    """Cheaply shrink old tool-result text before summary generation."""

    tool_markers: tuple[str, ...] = (
        "tool:",
        "tool result",
        "tool-result",
        "runtime tool results",
        "arguments:",
        "outcome:",
        "summary:",
    )

    def prune_line(self, line: str, *, max_chars: int = 280) -> str:
        normalized = " ".join(str(line or "").split()).strip()
        if not normalized:
            return ""
        if not self._looks_like_tool_result(normalized):
            return _compact_text(normalized, limit=max_chars)
        tool_name = self._tool_name(normalized)
        return f"tool-result-pruned: {tool_name} | {_compact_text(normalized, limit=max(80, max_chars // 2))}"

    def prune_lines(self, lines: Sequence[str], *, max_chars: int = 280) -> tuple[str, ...]:
        return tuple(pruned for line in lines if (pruned := self.prune_line(line, max_chars=max_chars)))

    def prune_messages(self, messages: Sequence[PromptMessage], *, max_chars: int = 280) -> tuple[str, ...]:
        pruned: list[str] = []
        for message in messages:
            line = _prompt_message_projection_line(message)
            if message.role == "tool":
                tool_name = message.tool_name.strip() or self._tool_name(line)
                content = _compact_text(message.content, limit=max(80, max_chars // 2))
                pruned.append(
                    f"tool-result-pruned: {tool_name} "
                    f"tool_call_id={message.tool_call_id or '<none>'} | {content}"
                )
                continue
            if message.role == "assistant" and message.tool_calls:
                call_names = ", ".join(_tool_call_name(call) for call in message.tool_calls)
                content = _compact_text(message.content, limit=max(80, max_chars // 2))
                pruned.append(f"assistant-tool-call: {content} tool_calls={call_names}".strip())
                continue
            if compacted := self.prune_line(line, max_chars=max_chars):
                pruned.append(compacted)
        return tuple(pruned)

    def _looks_like_tool_result(self, line: str) -> bool:
        lower = line.casefold()
        return any(marker in lower for marker in self.tool_markers) or len(line) > 900

    def _tool_name(self, line: str) -> str:
        match = re.search(r"(?:tool|tool-result)[\s:_-]+([A-Za-z0-9_.-]+)", line, flags=re.IGNORECASE)
        return match.group(1) if match is not None else "unknown"


class EmbeddingProjectionRelevanceScorer:
    """Rank compacted middle messages using only cached projection embeddings.

    Cache-first by design: the scorer never synchronously embeds on the hot
    path. A miss on either the query vector or a candidate group vector
    enqueues a best-effort background backfill and the scorer returns no
    ranking for this call. The projection compactor treats an empty ranking
    as "no semantic anchor" and falls back to its deterministic protected
    head/tail policy.
    """

    def __init__(
        self,
        embedding_service: Any,
        *,
        latency_mode: str = "fast",
        dimensions: int = 64,
        min_score: float = 0.18,
    ) -> None:
        self.embedding_service = embedding_service
        self.latency_mode = latency_mode
        self.dimensions = dimensions
        self.min_score = min_score
        self.last_stats = ProjectionSemanticAnchorStats()

    def rank(self, *, query: str, candidates: tuple[str, ...], limit: int) -> tuple[int, ...]:
        normalized_query = _normalize_projection_query_text(query)
        if not normalized_query or not candidates or limit <= 0:
            self.last_stats = ProjectionSemanticAnchorStats(candidate_count=len(candidates))
            return ()
        cached_vector = getattr(self.embedding_service, "cached_vector", None)
        if not callable(cached_vector):
            self.last_stats = ProjectionSemanticAnchorStats(
                candidate_count=len(candidates),
                vector_cache_status="unavailable",
            )
            return ()

        started_at = time.monotonic()
        query_vector, candidate_vectors, stats = self._snapshot_cached_vectors(
            query=normalized_query,
            candidates=candidates,
        )
        wait_ms = int(round((time.monotonic() - started_at) * 1000))
        self._queue_missing_backfill(query=normalized_query, candidates=candidates, stats=stats)
        if query_vector is None:
            cache_status = "pending" if stats.query_pending else "miss-backfilled"
            self.last_stats = replace(stats, wait_ms=wait_ms, vector_cache_status=cache_status)
            return ()
        query_values = tuple(getattr(query_vector, "values", ()) or ())
        if not query_values:
            self.last_stats = replace(stats, wait_ms=wait_ms, vector_cache_status="miss-backfilled")
            return ()

        scored: list[tuple[float, int]] = []
        for index, candidate_vector in candidate_vectors.items():
            score = cosine_similarity(query_values, tuple(getattr(candidate_vector, "values", ()) or ()))
            if score >= self.min_score:
                scored.append((score, index))
        ranked = sorted(scored, key=lambda item: (-item[0], -item[1]))[:limit]
        indexes = tuple(sorted(index for _score, index in ranked))
        self.last_stats = replace(
            stats,
            selected_group_count=len(indexes),
            wait_ms=wait_ms,
            vector_cache_status="hit",
        )
        return indexes

    def _snapshot_cached_vectors(
        self,
        *,
        query: str,
        candidates: tuple[str, ...],
    ) -> tuple[Any | None, dict[int, Any], ProjectionSemanticAnchorStats]:
        cached_vector = getattr(self.embedding_service, "cached_vector", None)
        pending_vector = getattr(self.embedding_service, "pending_vector", None)
        if not callable(cached_vector):
            return None, {}, ProjectionSemanticAnchorStats(candidate_count=len(candidates))

        query_key = _projection_embedding_cache_key("query", query)
        query_vector = None
        query_cached = False
        query_pending = False
        try:
            query_vector = cached_vector(
                target=PROJECTION_EMBEDDING_TARGET,
                cache_key=query_key,
                dimensions=self.dimensions,
            )
            query_cached = query_vector is not None
        except Exception:
            LOGGER.debug("Projection query cached-vector lookup failed.", exc_info=True)
            query_vector = None
        if query_vector is None and callable(pending_vector):
            try:
                query_pending = bool(
                    pending_vector(
                        target=PROJECTION_EMBEDDING_TARGET,
                        cache_key=query_key,
                        dimensions=self.dimensions,
                    )
                )
            except Exception:
                LOGGER.debug("Projection query pending-vector lookup failed.", exc_info=True)
                query_pending = False

        candidate_vectors: dict[int, Any] = {}
        pending_count = 0
        missed_count = 0
        for index, candidate in enumerate(candidates):
            normalized_candidate = _projection_embedding_text(candidate)
            if not normalized_candidate:
                missed_count += 1
                continue
            key = _projection_embedding_cache_key("group", normalized_candidate)
            vector = None
            try:
                vector = cached_vector(
                    target=PROJECTION_EMBEDDING_TARGET,
                    cache_key=key,
                    dimensions=self.dimensions,
                )
            except Exception:
                LOGGER.debug("Projection candidate cached-vector lookup failed.", exc_info=True)
                vector = None
            if vector is not None:
                candidate_vectors[index] = vector
                continue
            is_pending = False
            if callable(pending_vector):
                try:
                    is_pending = bool(
                        pending_vector(
                            target=PROJECTION_EMBEDDING_TARGET,
                            cache_key=key,
                            dimensions=self.dimensions,
                        )
                    )
                except Exception:
                    LOGGER.debug("Projection candidate pending-vector lookup failed.", exc_info=True)
                    is_pending = False
            if is_pending:
                pending_count += 1
            else:
                missed_count += 1
        stats = ProjectionSemanticAnchorStats(
            candidate_count=len(candidates),
            cached_group_count=len(candidate_vectors),
            pending_group_count=pending_count,
            missed_group_count=missed_count,
            query_cached=query_cached,
            query_pending=query_pending,
        )
        return query_vector, candidate_vectors, stats

    def _queue_missing_backfill(
        self,
        *,
        query: str,
        candidates: tuple[str, ...],
        stats: ProjectionSemanticAnchorStats,
    ) -> None:
        if stats.missed_group_count <= 0 and (stats.query_cached or stats.query_pending):
            return
        queue_backfill = getattr(self.embedding_service, "queue_backfill", None)
        if not callable(queue_backfill):
            return
        entries: dict[str, EmbeddingPreloadEntry] = {}
        if query and not stats.query_cached and not stats.query_pending:
            query_key = _projection_embedding_cache_key("query", query)
            entries[query_key] = EmbeddingPreloadEntry(
                cache_key=query_key,
                text=query,
                metadata={"surface": "context-projection", "kind": "query", "priority": "recent"},
            )
        for index, candidate in reversed(tuple(enumerate(candidates))):
            normalized_candidate = _projection_embedding_text(candidate)
            if not normalized_candidate:
                continue
            key = _projection_embedding_cache_key("group", normalized_candidate)
            try:
                if self.embedding_service.cached_vector(
                    target=PROJECTION_EMBEDDING_TARGET,
                    cache_key=key,
                    dimensions=self.dimensions,
                ) is not None:
                    continue
            except Exception:
                LOGGER.debug("Projection backfill cached-vector lookup failed.", exc_info=True)
                continue
            pending_vector = getattr(self.embedding_service, "pending_vector", None)
            if callable(pending_vector):
                try:
                    if pending_vector(
                        target=PROJECTION_EMBEDDING_TARGET,
                        cache_key=key,
                        dimensions=self.dimensions,
                        ):
                            continue
                except Exception:
                    LOGGER.debug("Projection backfill pending-vector lookup failed.", exc_info=True)
                    continue
            entries[key] = EmbeddingPreloadEntry(
                cache_key=key,
                text=normalized_candidate,
                metadata={
                    "surface": "context-projection",
                    "kind": "group",
                    "priority": "recent-middle",
                    "candidate_index": str(index),
                },
            )
            if len(entries) >= _PROJECTION_EMBEDDING_MAX_BACKFILL_ENTRIES:
                break
        if not entries:
            return
        try:
            queue_backfill(
                target=PROJECTION_EMBEDDING_TARGET,
                entries=tuple(entries.values()),
                latency_mode=self.latency_mode,
            )
        except Exception:
            LOGGER.debug("Projection missing-vector backfill queue failed.", exc_info=True)
            return


def queue_projection_history_embedding_backfill(
    embedding_service: Any,
    *,
    messages: tuple[PromptMessage, ...],
    thread_focus: str = "",
    latency_mode: str = "fast",
    max_entries: int = _PROJECTION_EMBEDDING_MAX_BACKFILL_ENTRIES,
    include_query: bool = True,
) -> Any | None:
    """Queue projection embedding precompute after a turn, without cold-starting embeddings."""

    if embedding_service is None or not messages or max_entries <= 0:
        return None
    health = getattr(embedding_service, "health", None)
    if callable(health):
        try:
            if not embedding_runtime_is_loaded(health()):
                return None
        except Exception:
            LOGGER.debug("Projection embedding health check failed; skipping backfill.", exc_info=True)
            return None
    queue_backfill = getattr(embedding_service, "queue_backfill", None)
    if not callable(queue_backfill):
        return None

    entries: dict[str, EmbeddingPreloadEntry] = {}
    query_text = _projection_query_text(thread_focus=thread_focus, messages=messages) if include_query else ""
    if include_query and query_text:
        query_key = _projection_embedding_cache_key("query", query_text)
        entries[query_key] = EmbeddingPreloadEntry(
            cache_key=query_key,
            text=query_text,
            metadata={"surface": "context-projection", "kind": "query", "priority": "recent"},
        )
    for entry in _projection_group_preload_entries(messages, recent_first=True):
        entries.setdefault(entry.cache_key, entry)
        if len(entries) >= max_entries:
            break
    if not entries:
        return None
    try:
        return queue_backfill(
            target=PROJECTION_EMBEDDING_TARGET,
            entries=tuple(entries.values())[:max_entries],
            latency_mode=latency_mode,
        )
    except Exception:
        LOGGER.debug("Projection history embedding backfill queue failed.", exc_info=True)
        return None


class DeterministicProjectionSummaryHook:
    """Build an inspectable handoff summary without making a provider call."""

    def summarize(
        self,
        *,
        thread_focus: str,
        previous_summary: str,
        compacted_lines: tuple[str, ...],
        protected_tail: tuple[str, ...],
        token_budget: int,
    ) -> str:
        parts: list[str] = [
            _REFERENCE_ONLY_HEADER,
            "## Completed background",
            f"- covered entries: {len(compacted_lines)}",
        ]
        for line in compacted_lines[: max(0, min(len(compacted_lines), token_budget // 32))]:
            parts.append(f"- {_compact_text(line, limit=180)}")
            if estimate_projection_tokens("\n".join(parts)) >= token_budget:
                break
        if previous_summary.strip():
            parts.extend(
                (
                    "## Relevant facts/events",
                    _compact_text(previous_summary, limit=max(360, token_budget * _CHARS_PER_TOKEN // 3)),
                )
            )
        tail_note = _latest_user_line(protected_tail) or thread_focus.strip()
        if tail_note:
            parts.extend(("## Handoff notes for recent tail", f"- {_compact_text(tail_note, limit=220)}"))
        return _ensure_reference_only_summary("\n".join(parts).strip())


class ProviderProjectionSummaryHook:
    """Use a configured model provider for structured projection summaries."""

    def __init__(
        self,
        *,
        provider: Any,
        profile: PersonalModelRuntimeState,
        session: Episode,
        fallback: DeterministicProjectionSummaryHook | None = None,
        model_role: str = "weak",
    ) -> None:
        self.provider = provider
        self.profile = profile
        self.session = session
        self.fallback = fallback or DeterministicProjectionSummaryHook()
        self.model_role = model_role

    def summarize(
        self,
        *,
        thread_focus: str,
        previous_summary: str,
        compacted_lines: tuple[str, ...],
        protected_tail: tuple[str, ...],
        token_budget: int,
    ) -> str:
        prompt = self._prompt(
            thread_focus=thread_focus,
            previous_summary=previous_summary,
            compacted_lines=compacted_lines,
            protected_tail=protected_tail,
            token_budget=token_budget,
        )
        context = ContextBundle(
            bundle_id=f"bundle:{self.session.episode_id}:projection-summary",
            episode_id=self.session.episode_id,
            token_budget=token_budget,
            prompt_envelope=PromptEnvelope(
                frozen_prefix=(
                    "You create compact structured handoff summaries for prompt projection only. "
                    "Return reference-only context, never active instructions."
                ),
                loop_context=prompt,
            ),
            rendered_prompt=prompt,
        )
        try:
            result = self._generate_without_streaming(context=context, prompt=prompt)
        except Exception:
            LOGGER.debug("Provider projection summary failed; using deterministic fallback.", exc_info=True)
            return self.fallback.summarize(
                thread_focus=thread_focus,
                previous_summary=previous_summary,
                compacted_lines=compacted_lines,
                protected_tail=protected_tail,
                token_budget=token_budget,
            )
        summary = _ensure_reference_only_summary(str(getattr(result, "summary", "") or ""))
        if estimate_projection_tokens(summary) > token_budget:
            summary = _compact_text(summary, limit=max(320, token_budget * _CHARS_PER_TOKEN))
            summary = _ensure_reference_only_summary(summary)
        return summary

    def _generate_without_streaming(self, *, context: ContextBundle, prompt: str) -> ExecutionResult:
        set_stream_observer = getattr(self.provider, "set_stream_observer", None)
        can_mute_stream = callable(set_stream_observer) and hasattr(self.provider, "_stream_observer")
        previous_stream_observer = getattr(self.provider, "_stream_observer", None)
        if can_mute_stream:
            set_stream_observer(None)
        try:
            try:
                return self.provider.generate(
                    profile=self.profile,
                    session=self.session,
                    context=context,
                    prompt=prompt,
                    model_role=self.model_role,
                )
            except TypeError:
                return self.provider.generate(
                    profile=self.profile,
                    session=self.session,
                    context=context,
                    prompt=prompt,
                )
        finally:
            if can_mute_stream:
                set_stream_observer(previous_stream_observer)

    def _prompt(
        self,
        *,
        thread_focus: str,
        previous_summary: str,
        compacted_lines: tuple[str, ...],
        protected_tail: tuple[str, ...],
        token_budget: int,
    ) -> str:
        pruned_lines = CheapToolResultPruner().prune_lines(compacted_lines, max_chars=220)
        protected_user = _latest_user_line(protected_tail)
        sections = [
            "Create a compact reference summary for Elephant Agent context projection.",
            "Output exactly these section headings when content exists: Completed background, Relevant facts/events, Handoff notes for recent tail.",
            "Summarize completed older turns as background only; avoid action directives and modal verbs.",
            f"Stay under roughly {token_budget} tokens.",
        ]
        if previous_summary.strip():
            sections.append(f"Prior reference summary:\n{_compact_text(previous_summary, limit=900)}")
        sections.append("Completed older turns:\n" + "\n".join(f"- {line}" for line in pruned_lines))
        tail_parts = tuple(part for part in (protected_user, thread_focus.strip()) if part)
        if tail_parts:
            sections.append("Recent tail hints:\n" + "\n".join(f"- {part}" for part in tail_parts))
        return "\n\n".join(sections)


def _message_projection_surface(message: PromptMessage) -> str:
    metadata = dict(message.metadata or {})
    return str(metadata.get("projection_surface") or metadata.get("surface") or metadata.get("source") or "").strip().lower()


def _history_is_im(messages: tuple[PromptMessage, ...]) -> bool:
    for message in messages:
        surface = _message_projection_surface(message)
        if surface == "im" or surface.startswith("gateway:") or surface.startswith("feishu") or surface.startswith("wecom") or surface.startswith("weixin") or surface.startswith("dingding") or surface.startswith("discord"):
            return True
    return False


def _message_created_at(message: PromptMessage) -> datetime | None:
    value = str((message.metadata or {}).get("created_at") or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _im_burst_tail_start(
    groups: tuple[tuple[int, int], ...],
    messages: tuple[PromptMessage, ...],
    *,
    head_end: int,
    window_seconds: int,
    idle_gap_seconds: int,
) -> int | None:
    if not groups:
        return None
    latest = next((_message_created_at(message) for message in reversed(messages) if _message_created_at(message) is not None), None)
    if latest is None:
        return None
    tail_start = len(messages)
    previous_group_time: datetime | None = None
    for start, end in reversed(groups):
        if end <= head_end:
            break
        group_times = tuple(
            timestamp
            for message in messages[start:end]
            if (timestamp := _message_created_at(message)) is not None
        )
        group_time = max(group_times) if group_times else previous_group_time
        if group_time is None:
            break
        if max(0.0, (latest - group_time).total_seconds()) > max(1, window_seconds):
            break
        if previous_group_time is not None and max(0.0, (previous_group_time - group_time).total_seconds()) > max(1, idle_gap_seconds):
            break
        tail_start = start
        previous_group_time = group_time
    return tail_start if tail_start < len(messages) else None


class SessionProjectionCompactor:
    """Compact prompt projection history while leaving durable records intact."""

    def __init__(
        self,
        *,
        policy: ProjectionCompactionPolicy | None = None,
        summary_hook: Any | None = None,
        tool_result_pruner: CheapToolResultPruner | None = None,
        relevance_scorer: Any | None = None,
    ) -> None:
        self.policy = policy or ProjectionCompactionPolicy()
        self.summary_hook = summary_hook or DeterministicProjectionSummaryHook()
        self.tool_result_pruner = tool_result_pruner or CheapToolResultPruner()
        self.relevance_scorer = relevance_scorer

    def compact_messages(
        self,
        *,
        messages: tuple[PromptMessage, ...],
        thread_focus: str = "",
        previous_summary: str = "",
        total_tokens: int,
        reason: str = "manual",
        force: bool = False,
    ) -> SessionMessageProjection:
        normalized = tuple(message for message in (_normalize_prompt_message(message) for message in messages) if message is not None)
        rendered = tuple(_prompt_message_projection_line(message) for message in normalized)
        before_tokens = estimate_projection_lines_tokens(rendered)
        before_count = len(normalized)
        trigger_tokens = self.policy.trigger_tokens(total_tokens)
        if not force and before_tokens <= trigger_tokens:
            return SessionMessageProjection(
                summary=previous_summary,
                messages=normalized,
                result=ContextProjectionCompactionResult(
                    compacted=False,
                    reason=reason,
                    before_tokens=before_tokens,
                    after_tokens=before_tokens + estimate_projection_tokens(previous_summary),
                    before_line_count=before_count,
                    after_line_count=before_count,
                    summary=previous_summary,
                    protected_ranges=_protected_ranges(
                        message_count=before_count,
                        head_count=min(self.policy.protected_head_lines, before_count),
                        tail_count=min(
                            self.policy.protected_tail_lines,
                            max(0, before_count - min(self.policy.protected_head_lines, before_count)),
                        ),
                    ),
                    summary_hash=_projection_summary_hash(previous_summary),
                ),
            )

        reason_key = str(reason or "").strip().lower()
        usage_after_turn_force = force and reason_key == "usage"
        im_history = _history_is_im(normalized)
        protected_head_lines = self.policy.im_protected_head_lines if im_history else self.policy.protected_head_lines
        if usage_after_turn_force and before_count <= self.policy.protected_head_lines + 2:
            protected_head_lines = 0
        protected_tail_lines = 1 if usage_after_turn_force and not im_history else self.policy.protected_tail_lines
        head, middle, tail = self._split_messages(
            normalized,
            total_tokens=total_tokens,
            force=force,
            protected_head_lines=protected_head_lines,
            protected_tail_lines=protected_tail_lines,
            protect_latest_user=not usage_after_turn_force,
        )
        if not middle:
            return SessionMessageProjection(
                summary=previous_summary,
                messages=normalized,
                result=ContextProjectionCompactionResult(
                    compacted=False,
                    reason=reason,
                    before_tokens=before_tokens,
                    after_tokens=before_tokens + estimate_projection_tokens(previous_summary),
                    before_line_count=before_count,
                    after_line_count=before_count,
                    summary=previous_summary,
                    protected_head_count=len(head),
                    protected_tail_count=len(tail),
                    protected_ranges=_protected_ranges(
                        message_count=len(normalized),
                        head_count=len(head),
                        tail_count=len(tail),
                    ),
                    summary_hash=_projection_summary_hash(previous_summary),
                ),
            )

        tail_lines = tuple(_prompt_message_projection_line(message) for message in tail)
        protected_ranges = _protected_ranges(
            message_count=len(normalized),
            head_count=len(head),
            tail_count=len(tail),
        )
        anchor_messages, compacted_middle, anchor_stats, selected_raw_ids, compaction_query = self._semantic_anchor_messages(
            middle,
            thread_focus=thread_focus,
            protected_tail=tail,
            force=force,
        )
        pruned_middle = self.tool_result_pruner.prune_messages(compacted_middle, max_chars=280)
        summary = self.summary_hook.summarize(
            thread_focus=thread_focus,
            previous_summary=previous_summary,
            compacted_lines=pruned_middle,
            protected_tail=tail_lines,
            token_budget=self.policy.target_tokens(total_tokens),
        )
        updated_messages = head + anchor_messages + tail
        after_tokens = estimate_projection_tokens(summary) + estimate_projection_lines_tokens(
            tuple(_prompt_message_projection_line(message) for message in updated_messages)
        )
        if not force and after_tokens >= max(1, int(before_tokens * 0.90)):
            return SessionMessageProjection(
                summary=previous_summary,
                messages=normalized,
                result=ContextProjectionCompactionResult(
                    compacted=False,
                    reason=reason,
                    before_tokens=before_tokens,
                    after_tokens=before_tokens + estimate_projection_tokens(previous_summary),
                    before_line_count=before_count,
                    after_line_count=before_count,
                    summary=previous_summary,
                    protected_head_count=len(head),
                    protected_tail_count=len(tail),
                    protected_ranges=protected_ranges,
                    selected_raw_ids=selected_raw_ids,
                    compaction_query=compaction_query,
                    summary_hash=_projection_summary_hash(previous_summary),
                    semantic_anchor_selected_count=anchor_stats.selected_group_count,
                    semantic_anchor_cached_count=anchor_stats.cached_group_count,
                    semantic_anchor_pending_count=anchor_stats.pending_group_count,
                    missed_projection_embedding_count=anchor_stats.missed_group_count,
                    semantic_anchor_wait_ms=anchor_stats.wait_ms,
                ),
            )
        return SessionMessageProjection(
            summary=summary,
            messages=updated_messages,
            result=ContextProjectionCompactionResult(
                compacted=True,
                reason=reason,
                before_tokens=before_tokens,
                after_tokens=after_tokens,
                before_line_count=before_count,
                after_line_count=len(updated_messages),
                summary=summary,
                protected_head_count=len(head),
                protected_tail_count=len(tail),
                protected_ranges=protected_ranges,
                compacted_line_count=len(compacted_middle),
                selected_raw_ids=selected_raw_ids,
                compaction_query=compaction_query,
                summary_hash=_projection_summary_hash(summary),
                semantic_anchor_selected_count=anchor_stats.selected_group_count,
                semantic_anchor_cached_count=anchor_stats.cached_group_count,
                semantic_anchor_pending_count=anchor_stats.pending_group_count,
                missed_projection_embedding_count=anchor_stats.missed_group_count,
                semantic_anchor_wait_ms=anchor_stats.wait_ms,
            ),
        )

    def _split_messages(
        self,
        messages: tuple[PromptMessage, ...],
        *,
        total_tokens: int,
        force: bool,
        protected_head_lines: int | None = None,
        protected_tail_lines: int | None = None,
        protect_latest_user: bool = True,
    ) -> tuple[tuple[PromptMessage, ...], tuple[PromptMessage, ...], tuple[PromptMessage, ...]]:
        if not messages:
            return (), (), ()
        groups = _message_groups(messages)
        resolved_head_lines = (
            self.policy.protected_head_lines
            if protected_head_lines is None
            else max(0, protected_head_lines)
        )
        head_target = min(resolved_head_lines, len(messages))
        head_end = _group_end_at_or_after(groups, head_target)
        head_end = min(head_end, len(messages))
        tail_start = self._tail_start(
            groups,
            messages,
            head_end=head_end,
            total_tokens=total_tokens,
            force=force,
            protected_tail_lines=protected_tail_lines,
            protect_latest_user=protect_latest_user,
        )
        tail_start = max(head_end, tail_start)
        head = messages[:head_end]
        tail = messages[tail_start:] if tail_start < len(messages) else ()
        middle = messages[head_end:tail_start]
        return head, middle, tail

    def _tail_start(
        self,
        groups: tuple[tuple[int, int], ...],
        messages: tuple[PromptMessage, ...],
        *,
        head_end: int,
        total_tokens: int,
        force: bool,
        protected_tail_lines: int | None = None,
        protect_latest_user: bool = True,
    ) -> int:
        remaining_groups = tuple(group for group in groups if group[1] > head_end)
        if not remaining_groups:
            return len(messages)
        min_tail_messages = (
            self.policy.protected_tail_lines
            if protected_tail_lines is None
            else max(0, protected_tail_lines)
        )
        if force and len(messages) > head_end + 3:
            min_tail_messages = max(3, self.policy.protected_tail_lines // 2)
        if protected_tail_lines is not None:
            min_tail_messages = max(0, protected_tail_lines)
        min_tail_messages = min(min_tail_messages, max(0, len(messages) - head_end))
        if _history_is_im(messages):
            burst_start = _im_burst_tail_start(
                remaining_groups,
                messages,
                head_end=head_end,
                window_seconds=self.policy.im_tail_window_seconds,
                idle_gap_seconds=self.policy.im_idle_gap_seconds,
            )
            if burst_start is not None:
                return burst_start
        token_budget = self.policy.tail_tokens(total_tokens, force=force)
        token_count = 0
        message_count = 0
        tail_start = len(messages)
        for start, end in reversed(remaining_groups):
            group = messages[start:end]
            token_count += estimate_projection_lines_tokens(tuple(_prompt_message_projection_line(message) for message in group))
            message_count += len(group)
            tail_start = start
            if protected_tail_lines is not None and message_count >= min_tail_messages:
                break
            if message_count >= min_tail_messages and token_count >= token_budget:
                break
        if protect_latest_user:
            latest_user_group = _latest_user_group(groups, messages)
            if latest_user_group is not None and latest_user_group[0] >= head_end:
                tail_start = min(tail_start, latest_user_group[0])
        return tail_start

    def _semantic_anchor_messages(
        self,
        middle: tuple[PromptMessage, ...],
        *,
        thread_focus: str,
        protected_tail: tuple[PromptMessage, ...],
        force: bool,
    ) -> tuple[
        tuple[PromptMessage, ...],
        tuple[PromptMessage, ...],
        ProjectionSemanticAnchorStats,
        tuple[str, ...],
        str,
    ]:
        max_anchors = max(0, self.policy.semantic_anchor_max_messages)
        if force:
            max_anchors = min(max_anchors, 1)
        query = _build_projection_query(
            thread_focus=thread_focus,
            latest_user_query=_latest_user_line(
                tuple(_prompt_message_projection_line(message) for message in protected_tail)
            ),
        )
        if self.relevance_scorer is None or max_anchors <= 0 or not middle:
            return (), middle, ProjectionSemanticAnchorStats(), (), query
        groups = _message_groups(middle)
        candidates = tuple(
            "\n".join(_prompt_message_projection_line(message) for message in middle[start:end])
            for start, end in groups
        )
        candidate_ids = tuple(_projection_embedding_cache_key("group", candidate) for candidate in candidates)
        if not query:
            return (), middle, ProjectionSemanticAnchorStats(candidate_count=len(candidates)), (), query
        try:
            ranked_groups = tuple(self.relevance_scorer.rank(query=query, candidates=candidates, limit=max_anchors))
            stats = getattr(self.relevance_scorer, "last_stats", None)
            if not isinstance(stats, ProjectionSemanticAnchorStats):
                stats = ProjectionSemanticAnchorStats(
                    candidate_count=len(candidates),
                    selected_group_count=len(ranked_groups),
                )
        except Exception:
            LOGGER.debug("Projection semantic anchor ranking failed.", exc_info=True)
            return (), middle, ProjectionSemanticAnchorStats(candidate_count=len(candidates)), (), query
        if not ranked_groups:
            return (), middle, stats, (), query
        anchor_indexes: set[int] = set()
        anchor_messages: list[PromptMessage] = []
        selected_raw_ids: list[str] = []
        selected_groups = 0
        for group_index in sorted(set(ranked_groups)):
            if group_index < 0 or group_index >= len(groups):
                continue
            start, end = groups[group_index]
            if len(anchor_messages) + (end - start) > max_anchors:
                continue
            selected_groups += 1
            selected_raw_ids.append(candidate_ids[group_index])
            for index in range(start, end):
                anchor_indexes.add(index)
                anchor_messages.append(middle[index])
        compacted = tuple(message for index, message in enumerate(middle) if index not in anchor_indexes)
        return (
            tuple(anchor_messages),
            compacted,
            replace(stats, selected_group_count=selected_groups),
            tuple(selected_raw_ids),
            query,
        )
