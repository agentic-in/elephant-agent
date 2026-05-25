"""Per-turn ephemeral context injection for outbound user turns.

## Why this module exists

Elephant Agent has two context-delivery layers to the model:

1. **Stable prefix** — system prompt + earlier role-preserved history. This
   stays byte-identical across turns so the provider's prefix cache keeps
   hitting. The kernel persists it as `ContextBundle.prompt_envelope.messages`
   and it is the single source of truth for session history.

2. **Turn recall suffix** — a short support section
   produced once from the current user's query. It is appended to the current
   user message after the user's text, then persisted as part of that same
   user turn. When the turn becomes history, the provider prefix remains
   append-only and cacheable.

## The rule

Live runtime recall must not create a second synthetic user turn. Recall is
runtime-added context inside the same user-role message as the user's request,
placed after the request so the authored text remains the lead signal.

## Turn-scoped caching

The kernel may call `model_provider.generate()` multiple times for a single
user turn:

- a **tool loop** fires one initial call plus one follow-up per tool
  observation round, all sharing the same inbound user message;
- a **provider-overflow retry** compacts the context and re-runs the turn.

Re-running affinity/focus builders on each of those calls would (a)
waste latency and cost, (b) feed the follow-up calls a `prompt` argument
that is no longer the user's original query (it becomes "Continue the same
turn…"), which would corrupt the current-turn signal. We solve both problems with
`TurnScopedPrefixCache`: the composer keys ephemeral blocks on
``(episode_id, last_user_message_content)``. A new user turn always changes
the key (because the new turn's last user message is different), so the
cache evicts itself naturally — no TTL, no explicit invalidation.

## The shape

- `ephemeral_blocks_as_user_suffix(blocks=...)` returns the concatenated
  recall/focus blocks without manufacturing a message.
- `append_ephemeral_suffix_to_last_user(messages, blocks=...)` rewrites only
  the last user message into `user text\n\nCurrent-turn recall support:\n- ...`.
- `TurnScopedPrefixCache.resolve(...)` drives builders once per turn and
  returns the same block tuple on subsequent calls inside the same turn.
- `safe_call_block_builder(builder, *args, **kwargs)` centralises the
  try/except pattern every builder needs: a degraded memory/skill subsystem
  must never block the actual model request.
## Where this module MUST NOT reach

- No kernel imports — we want this to be pure.
- No storage writes — everything here is in-memory, request-scoped.
- No logging of block content — blocks can contain sensitive recalled
  memory and are strictly short-lived to the active request.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import replace
import logging
import re
from typing import Any

from packages.contracts import Episode
from packages.contracts.runtime import (
    ContextBundle,
    PersonalModelRuntimeState,
    PromptMessage,
)

LOGGER = logging.getLogger(__name__)


__all__ = [
    "TurnScopedPrefixCache",
    "append_ephemeral_suffix_to_last_user",
    "ephemeral_blocks_as_user_suffix",
    "last_user_message_content",
    "recall_block_contents",
    "safe_call_block_builder",
    "strip_recall_blocks",
]

_RECALL_HEADER = "Current-turn recall support:"


def _recall_block_span(text: str) -> tuple[int, int] | None:
    start = text.find(_RECALL_HEADER)
    if start < 0:
        return None
    cursor = start + len(_RECALL_HEADER)
    if cursor < len(text) and text[cursor] == "\r":
        cursor += 1
    if cursor < len(text) and text[cursor] == "\n":
        cursor += 1
    line_start = cursor
    while line_start < len(text):
        line_end = text.find("\n", line_start)
        if line_end < 0:
            line_end = len(text)
        line = text[line_start:line_end].strip()
        if line and not line.startswith("-"):
            break
        line_start = line_end + 1 if line_end < len(text) else line_end
    return start, line_start


def _compose_blocks(blocks: Iterable[str]) -> str:
    """Join non-empty blocks with a blank line and no outer padding."""

    normalized = tuple(block for block in (str(b or "").strip() for b in blocks) if block)
    if not normalized:
        return ""
    return "\n\n".join(normalized)


def ephemeral_blocks_as_user_suffix(*, blocks: Iterable[str]) -> str:
    """Return recall blocks as the suffix for the current user message."""

    return _compose_blocks(blocks)


def append_ephemeral_suffix_to_last_user(
    messages: tuple[PromptMessage, ...],
    *,
    blocks: Iterable[str],
) -> tuple[PromptMessage, ...]:
    """Return a tuple whose last user turn carries the recall suffix."""

    suffix = ephemeral_blocks_as_user_suffix(blocks=blocks)
    if not suffix:
        return messages
    last_user_idx: int | None = None
    for idx in range(len(messages) - 1, -1, -1):
        if messages[idx].role == "user":
            last_user_idx = idx
            break
    if last_user_idx is None:
        return messages
    target = messages[last_user_idx]
    current = str(target.content or "").rstrip()
    new_content = f"{current}\n\n{suffix}" if current else suffix
    replaced = replace(target, content=new_content)
    out = list(messages)
    out[last_user_idx] = replaced
    return tuple(out)


def recall_block_contents(content: str) -> tuple[str, ...]:
    """Extract current-turn recall support blocks from a user message body."""

    text = str(content or "")
    span = _recall_block_span(text)
    if span is None:
        return ()
    start, end = span
    block = text[start:end].strip()
    return (block,) if block else ()


def strip_recall_blocks(content: str) -> str:
    """Return user text with any embedded current-turn recall support removed."""

    text = str(content or "")
    span = _recall_block_span(text)
    if span is not None:
        start, end = span
        text = text[:start] + text[end:]
    cleaned = "\n".join(line.rstrip() for line in text.splitlines()).strip()
    return re.sub(r"\n{3,}", "\n\n", cleaned)


def last_user_message_content(messages: Sequence[PromptMessage]) -> str:
    """Return the `.content` of the last `role=="user"` message, or ``""``.

    Used as the stable query key for turn-scoped suffix builders: within a single
    kernel turn (including tool-loop follow-ups and overflow retries) this
    value is invariant, because the kernel only ever appends assistant /
    tool messages to the collected turn messages — it never swaps the
    original user turn.
    """
    for idx in range(len(messages) - 1, -1, -1):
        if messages[idx].role == "user":
            return messages[idx].content
    return ""


def safe_call_block_builder(builder: Any, /, *args: Any, **kwargs: Any) -> str:
    """Invoke a block builder and swallow any exception.

    Block builders (skill/affinity injectors, focus hints, etc.)
    are defence-in-depth. A bug in a builder must degrade to "no block" —
    it must never break the model request. Returning an empty string here
    lets the composer treat the builder as a no-op.
    """
    if builder is None:
        return ""
    try:
        value = builder(*args, **kwargs)
    except Exception:
        LOGGER.warning("failed to build ephemeral injection section", exc_info=True)
        return ""
    return str(value or "")


class TurnScopedPrefixCache:
    """Cache the rendered ephemeral blocks for the duration of a single turn.

    Keyed on ``(episode_id, last_user_message_content)``. Holds a single
    entry per episode — a new user turn evicts the previous one automatically
    because the last user message content changes. Concurrent access across
    episodes is fine (disjoint keys); concurrent access inside one episode
    would race, which matches the existing `generate()` contract of
    single-threaded per-session execution.
    """

    __slots__ = ("_entries",)

    def __init__(self) -> None:
        # episode_id -> (user_content_key, rendered_blocks)
        self._entries: dict[str, tuple[str, tuple[str, ...]]] = {}

    def resolve(
        self,
        *,
        builders: Sequence[Any],
        profile: PersonalModelRuntimeState,
        session: Episode,
        context: ContextBundle,
        prompt: str,
        query: str,
    ) -> tuple[str, ...]:
        """Return the rendered blocks for this turn, computing on cache miss.

        ``query`` is the stable per-turn key (typically the last user message
        content); ``prompt`` is forwarded to builders as the active model
        input, which may differ from ``query`` on tool-loop follow-ups.
        """
        episode_id = str(getattr(session, "episode_id", "") or "")
        cache_key = query
        if episode_id:
            cached = self._entries.get(episode_id)
            if cached is not None and cached[0] == cache_key:
                return cached[1]
        blocks = tuple(
            safe_call_block_builder(builder, profile, session, context, prompt, query)
            for builder in builders
        )
        if episode_id:
            self._entries[episode_id] = (cache_key, blocks)
        return blocks

    def invalidate(self, episode_id: str | None = None) -> None:
        """Drop the cache for one episode (or everything, if id is None).

        The natural eviction — "last user message changes, key no longer
        matches" — covers the common case. This method is here for explicit
        resets during tests and for surfaces that want to force a rebuild
        on a new session boundary.
        """
        if episode_id is None:
            self._entries.clear()
            return
        self._entries.pop(str(episode_id), None)
