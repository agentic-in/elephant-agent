"""Shared projection helper utilities and public helper functions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import hashlib
import re

from packages.contracts.runtime import PromptMessage
from packages.embeddings import EmbeddingPreloadEntry

from .projection_types import ContextProjectionCompactionResult

_REFERENCE_ONLY_HEADER = (
    "[CONTEXT COMPACTION - REFERENCE ONLY] Reference summary of earlier completed turns. "
    "Latest live messages and the protected recent tail are authoritative."
)
_BANNED_SUMMARY_PHRASES = (
    "must",
    "should",
    "no tool actions",
    "current priority",
    "active state focus",
    "open / current focus",
    "open/current focus",
)
_PROJECTION_EMBEDDING_TEXT_LIMIT = 1200


def projection_result_with_estimated_tokens(
    result: ContextProjectionCompactionResult,
    *,
    before_tokens: int,
    after_tokens: int,
) -> ContextProjectionCompactionResult:
    return replace(result, before_tokens=max(0, before_tokens), after_tokens=max(0, after_tokens))


def latest_user_line(lines: tuple[str, ...]) -> str:
    for line in reversed(lines):
        if line.lower().startswith("user:"):
            return compact_text(re.sub(r"^user:\s*", "", line, flags=re.IGNORECASE), limit=220)
    return ""


def normalize_prompt_message(message: PromptMessage) -> PromptMessage | None:
    role = str(message.role or "").strip().lower()
    if role not in {"user", "assistant", "tool", "system"}:
        return None
    content = str(message.content or "")
    tool_calls = tuple(dict(call) for call in message.tool_calls if isinstance(call, Mapping))
    if not content.strip() and not tool_calls:
        return None
    return PromptMessage(
        role=role,
        content=content,
        name=str(message.name or "").strip(),
        tool_call_id=str(message.tool_call_id or "").strip(),
        tool_name=str(message.tool_name or "").strip(),
        tool_calls=tool_calls,
        metadata={str(key): str(value) for key, value in message.metadata.items()},
    )


def prompt_message_projection_line(message: PromptMessage) -> str:
    role = str(message.role or "message").strip().lower()
    if role == "tool":
        name = message.tool_name.strip() or "unknown"
        return f"tool: {name} tool_call_id={message.tool_call_id or '<none>'} summary: {message.content}"
    if role == "assistant" and message.tool_calls:
        call_names = ", ".join(
            tool_call_name(call)
            for call in message.tool_calls
            if isinstance(call, Mapping)
        )
        text = message.content.strip()
        suffix = f" tool_calls: {call_names}" if call_names else ""
        return f"assistant: {text}{suffix}".strip()
    return f"{role}: {message.content}"


def build_projection_query(*, thread_focus: str, latest_user_query: str = "") -> str:
    parts: list[str] = []
    normalized_user = compact_text(str(latest_user_query or "").strip(), limit=220)
    if normalized_user:
        parts.append(f"latest user query: {normalized_user}")

    focus_segments: list[str] = []
    for segment in re.split(r"(?:\s*;\s*|\n+)", str(thread_focus or "").strip()):
        cleaned = segment.strip()
        if cleaned:
            focus_segments.append(cleaned)

    if focus_segments:
        parts.append(f"state focus: {'; '.join(focus_segments)}")
    return projection_embedding_text("\n".join(parts))


def projection_query_text(*, thread_focus: str, messages: tuple[PromptMessage, ...]) -> str:
    lines = tuple(prompt_message_projection_line(message) for message in messages)
    return build_projection_query(
        thread_focus=thread_focus,
        latest_user_query=latest_user_line(lines),
    )


def normalize_projection_query_text(query: str) -> str:
    normalized_lines = tuple(line.strip() for line in str(query or "").splitlines() if line.strip())
    if not normalized_lines:
        return ""
    labeled_prefixes = ("latest user query:", "state focus:")
    if any(line.casefold().startswith(labeled_prefixes) for line in normalized_lines):
        return projection_embedding_text("\n".join(normalized_lines))
    if len(normalized_lines) >= 2:
        return build_projection_query(
            thread_focus="\n".join(normalized_lines[:-1]),
            latest_user_query=normalized_lines[-1],
        )
    return projection_embedding_text(normalized_lines[0])


def projection_group_preload_entries(
    messages: tuple[PromptMessage, ...],
    *,
    recent_first: bool = False,
) -> tuple[EmbeddingPreloadEntry, ...]:
    normalized = tuple(
        message
        for message in (normalize_prompt_message(message) for message in messages)
        if message is not None
    )
    entries: list[EmbeddingPreloadEntry] = []
    groups = tuple(enumerate(message_groups(normalized)))
    ordered_groups = tuple(reversed(groups)) if recent_first else groups
    for group_index, (start, end) in ordered_groups:
        text = projection_embedding_text(
            "\n".join(prompt_message_projection_line(message) for message in normalized[start:end])
        )
        if not text:
            continue
        key = projection_embedding_cache_key("group", text)
        entries.append(
            EmbeddingPreloadEntry(
                cache_key=key,
                text=text,
                metadata={
                    "surface": "context-projection",
                    "kind": "group",
                    "group_index": str(group_index),
                    "message_count": str(max(0, end - start)),
                    "priority": "recent" if recent_first else "normal",
                },
            )
        )
    return tuple(entries)


def projection_embedding_text(value: str) -> str:
    return compact_text(value, limit=_PROJECTION_EMBEDDING_TEXT_LIMIT)


def projection_embedding_cache_key(kind: str, text: str) -> str:
    normalized_kind = re.sub(r"[^a-z0-9_.-]+", "-", str(kind or "entry").strip().lower()).strip("-")
    normalized_text = projection_embedding_text(text)
    digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:24]
    return f"{normalized_kind or 'entry'}:{digest}"


def tool_call_name(call: Mapping[str, object]) -> str:
    function = call.get("function")
    if isinstance(function, Mapping):
        name = str(function.get("name") or "").strip()
        if name:
            return name
    return str(call.get("name") or call.get("tool_name") or "unknown").strip() or "unknown"


def tool_call_id(call: Mapping[str, object]) -> str:
    return str(call.get("id") or call.get("call_id") or call.get("tool_call_id") or "").strip()


def message_groups(messages: tuple[PromptMessage, ...]) -> tuple[tuple[int, int], ...]:
    groups: list[tuple[int, int]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        end = index + 1
        if message.role == "assistant" and message.tool_calls:
            call_ids = {
                call_id
                for call in message.tool_calls
                if isinstance(call, Mapping) and (call_id := tool_call_id(call))
            }
            while end < len(messages) and messages[end].role == "tool":
                if call_ids and messages[end].tool_call_id and messages[end].tool_call_id not in call_ids:
                    break
                end += 1
        elif message.role == "tool":
            while end < len(messages) and messages[end].role == "tool":
                end += 1
        groups.append((index, end))
        index = end
    return tuple(groups)


def group_end_at_or_after(groups: tuple[tuple[int, int], ...], target_count: int) -> int:
    if target_count <= 0:
        return 0
    for _start, end in groups:
        if end >= target_count:
            return end
    return groups[-1][1] if groups else 0


def latest_user_group(
    groups: tuple[tuple[int, int], ...],
    messages: tuple[PromptMessage, ...],
) -> tuple[int, int] | None:
    for start, end in reversed(groups):
        if any(message.role == "user" for message in messages[start:end]):
            return start, end
    return None


def compact_text(value: str, *, limit: int) -> str:
    compact = " ".join(str(value or "").split()).strip()
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."


def ensure_reference_only_summary(summary: str) -> str:
    normalized = _sanitize_reference_summary(str(summary or "").strip())
    if not normalized:
        return _REFERENCE_ONLY_HEADER
    if normalized.startswith("[CONTEXT COMPACTION - REFERENCE ONLY]"):
        return normalized
    return f"{_REFERENCE_ONLY_HEADER}\n\n{normalized}"


def _sanitize_reference_summary(summary: str) -> str:
    lines = []
    for line in str(summary or "").splitlines():
        if any(phrase in line.casefold() for phrase in _BANNED_SUMMARY_PHRASES):
            continue
        lines.append(line)
    return "\n".join(lines).strip()
