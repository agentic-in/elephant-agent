"""Unified context compression pipeline for CLI and Gateway.

Single entry point for both systems:
- LLM-based compress via reflect agent (high quality, requires sub-agent capability)
- Deterministic fallback (truncate + template summary, for hot-path overflow retries)

Split logic protects the most recent tail while compressing older or oversized
completed context into a reference summary.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from packages.contracts.runtime import PromptMessage

from .projection_support import message_groups, tool_call_id
from .session_projection import (
    SessionContextEpoch,
    compact_session_context_epoch,
    estimate_epoch_prompt_tokens,
)


@dataclass(frozen=True, slots=True)
class CompressResult:
    """Outcome of a compress operation."""

    compressed: bool
    summary: str
    before_messages: int
    after_messages: int
    before_tokens: int
    after_tokens: int
    method: str  # "reflect", "deterministic", "skipped"


class ReflectCompressor(Protocol):
    """Protocol for LLM-based compression via reflect agent."""

    def __call__(
        self,
        to_summarize: tuple[PromptMessage, ...],
        tail: tuple[PromptMessage, ...],
        *,
        session_id: str,
        context_limit: int,
    ) -> str:
        """Run reflect compress agent, return summary text."""
        ...


def compress_epoch(
    epoch: SessionContextEpoch,
    *,
    context_limit: int,
    usage_tokens: int,
    trigger_ratio: float = 0.85,
    reflect_compressor: ReflectCompressor | None = None,
    session_id: str = "",
) -> tuple[SessionContextEpoch, CompressResult] | None:
    """Unified compress entry point for both CLI and Gateway.

    Returns None if compression is not needed or not possible.
    Returns (updated_epoch, result) on successful compression.

    - reflect_compressor: LLM-based compress (pass None for hot-path deterministic fallback)
    - trigger_ratio: fraction of context_limit that triggers compression
    """
    if usage_tokens <= 0 or context_limit <= 0:
        return None
    trigger_tokens = max(1, int(context_limit * trigger_ratio))
    if usage_tokens < trigger_tokens:
        return None
    if not epoch.frozen or not epoch.history_messages:
        return None

    history = epoch.history_messages
    to_summarize, tail = split_for_compress(history)
    if not to_summarize:
        return None

    resolved_session_id = session_id or epoch.session_id

    # Try LLM-based compress first
    summary = ""
    method = "deterministic"
    if reflect_compressor is not None:
        try:
            summary = reflect_compressor(
                to_summarize, tail,
                session_id=resolved_session_id,
                context_limit=context_limit,
            )
            if summary.strip():
                method = "reflect"
        except Exception:
            summary = ""

    # Deterministic fallback
    if not summary.strip():
        summary = _deterministic_summary(to_summarize, history_count=len(history))
        method = "deterministic"

    # Apply compression: replace history with tail, set summary
    before_tokens = estimate_epoch_prompt_tokens(
        epoch, history_messages=history, compacted_summary=epoch.compacted_history_summary,
    )
    updated, _result = compact_session_context_epoch(
        epoch,
        total_tokens=context_limit,
        reason="usage",
        force=True,
        summary_text=summary,
        tail_messages=tail,
    )

    # Update Episode resume in frozen_prefix
    from packages.kernel.generation_context import (
        _strip_prompt_sections,
        _append_prompt_section,
    )
    updated_prefix = _strip_prompt_sections(updated.frozen_prefix, "Episode resume")
    updated_prefix = _append_prompt_section(
        updated_prefix,
        "Episode resume",
        (f"Reference summary: {summary}",),
    )
    updated = replace(updated, frozen_prefix=updated_prefix)

    after_tokens = estimate_epoch_prompt_tokens(
        updated, history_messages=tail, compacted_summary=summary,
    )

    result = CompressResult(
        compressed=True,
        summary=summary,
        before_messages=len(history),
        after_messages=len(tail),
        before_tokens=before_tokens,
        after_tokens=after_tokens,
        method=method,
    )
    return updated, result


def split_for_compress(
    messages: tuple[PromptMessage, ...],
    *,
    protected_tail_turns: int = 2,
) -> tuple[tuple[PromptMessage, ...], tuple[PromptMessage, ...]]:
    """Split messages into (to_summarize, protected_tail).

    For multi-turn conversations: keeps last N user turns intact.
    For single long turns (1 user + many tools): keeps the first user query plus
    the last ~25% of messages (final assistant response + recent tool context).
    For very short high-usage histories (for example one huge user request plus
    one assistant reply), keeps only the latest completed tail message and
    summarizes the earlier oversized context. Callers only invoke this splitter
    after a high-usage threshold, so this branch does not affect ordinary short
    conversations.
    """
    total = len(messages)
    if total < 2:
        return (), messages
    groups = message_groups(messages)

    # Find user-message boundaries
    user_starts: list[int] = []
    for i, msg in enumerate(messages):
        if msg.role == "user" and msg.content.strip():
            user_starts.append(i)

    # Normal multi-turn case: 3+ user turns -> keep last 2 intact
    if len(user_starts) > protected_tail_turns:
        tail_start = user_starts[-protected_tail_turns]
        # Ensure we're actually compressing a meaningful amount (>30%)
        if tail_start > total * 0.3:
            selected_groups = {
                group_index
                for group_index, (start, _end) in enumerate(groups)
                if start >= tail_start
            }
            to_summarize, tail = _split_by_tail_groups(messages, groups, selected_groups)
            if to_summarize:
                return to_summarize, tail

    # Few turns OR the normal split didn't compress enough:
    # Use aggressive compression: keep first user + last N messages.
    # This handles "1 user query → 100 tool calls → assistant response"
    keep_tail_count = max(6, min(total // 3, 20))  # Keep 1/3 but max 20 messages
    tail_start_idx = max(1, total - keep_tail_count)

    tail_groups: set[int] = set()
    _add_group_containing_index(groups, tail_groups, 0)
    for group_index, (_start, end) in enumerate(groups):
        if end > tail_start_idx:
            tail_groups.add(group_index)
    # Also keep any user/assistant content messages (they're rare and valuable).
    for group_index, (start, end) in enumerate(groups):
        if start >= tail_start_idx:
            continue
        group_messages = messages[start:end]
        if any(msg.role == "user" and msg.content.strip() for msg in group_messages):
            tail_groups.add(group_index)
        elif any(
            msg.role == "assistant" and msg.content.strip() and not msg.tool_calls
            for msg in group_messages
        ):
            tail_groups.add(group_index)

    to_summarize, tail = _split_by_tail_groups(messages, groups, tail_groups)
    if to_summarize:
        return to_summarize, tail

    # Group-boundary fallback: compress the first 60% without splitting a
    # provider-visible tool call/result group.
    cut = max(1, int(total * 0.6))
    tail_start = _group_boundary_after_index(groups, cut)
    tail_groups = {
        group_index
        for group_index, (start, _end) in enumerate(groups)
        if start >= tail_start
    }
    return _split_by_tail_groups(messages, groups, tail_groups)


def _split_by_tail_groups(
    messages: tuple[PromptMessage, ...],
    groups: tuple[tuple[int, int], ...],
    selected_groups: set[int],
) -> tuple[tuple[PromptMessage, ...], tuple[PromptMessage, ...]]:
    tail_indices: set[int] = set()
    for group_index in sorted(selected_groups):
        if group_index < 0 or group_index >= len(groups):
            continue
        start, end = groups[group_index]
        if not _preservable_live_group(messages[start:end]):
            continue
        tail_indices.update(range(start, end))
    tail = tuple(message for index, message in enumerate(messages) if index in tail_indices)
    to_summarize = tuple(message for index, message in enumerate(messages) if index not in tail_indices)
    return to_summarize, tail


def _preservable_live_group(group: tuple[PromptMessage, ...]) -> bool:
    if not group:
        return False
    first = group[0]
    if first.role == "tool":
        return False
    if first.role != "assistant" or not first.tool_calls:
        return True

    tool_messages = tuple(message for message in group[1:] if message.role == "tool")
    if not tool_messages:
        return False
    call_ids = {
        call_id
        for call in first.tool_calls
        if (call_id := tool_call_id(call))
    }
    if not call_ids:
        return True
    result_ids = {message.tool_call_id for message in tool_messages if message.tool_call_id}
    return call_ids.issubset(result_ids)


def _add_group_containing_index(
    groups: tuple[tuple[int, int], ...],
    selected_groups: set[int],
    index: int,
) -> None:
    for group_index, (start, end) in enumerate(groups):
        if start <= index < end:
            selected_groups.add(group_index)
            return


def _group_boundary_after_index(groups: tuple[tuple[int, int], ...], index: int) -> int:
    for start, end in groups:
        if start >= index:
            return start
        if start < index < end:
            return end
    return groups[-1][1] if groups else index


def _deterministic_summary(
    to_summarize: tuple[PromptMessage, ...],
    *,
    history_count: int,
) -> str:
    """Generate a simple heuristic summary when LLM compress is unavailable."""
    user_messages = [msg for msg in to_summarize if msg.role == "user" and msg.content.strip()]
    tool_count = sum(1 for msg in to_summarize if msg.role == "tool")

    parts: list[str] = []
    parts.append(f"[Context compressed] {len(to_summarize)} of {history_count} messages summarized.")

    if user_messages:
        # Include abbreviated user queries for continuity
        for msg in user_messages[:3]:
            text = msg.content.strip()[:120]
            parts.append(f"User asked: {text}")

    if tool_count > 0:
        parts.append(f"({tool_count} tool interactions were executed.)")

    return " ".join(parts)
