"""Turn-scoped recall helper utilities for model runtime injection."""

from __future__ import annotations

import re

from packages.contracts.runtime import PromptMessage

from .ephemeral_injection import recall_block_contents


_RECALL_CONTEXT_MARKER = "Current-turn recall support:"
_MAX_SESSION_RECALL_BYTES = 60 * 1024
_MIN_RECALL_QUERY_CHARS = 4
_MIN_RECALL_QUERY_WORDS = 2
_RECALL_WORD_RE = re.compile(r"[A-Za-z0-9_./:-]+")
_RECALL_CJK_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")


def _hot_recall_query_allowed(query: str) -> bool:
    normalized = " ".join(str(query or "").split()).strip()
    if len(normalized) < _MIN_RECALL_QUERY_CHARS:
        return False
    words = _RECALL_WORD_RE.findall(normalized)
    cjk_chars = _RECALL_CJK_RE.findall(normalized)
    if len(words) < _MIN_RECALL_QUERY_WORDS and len(cjk_chars) < _MIN_RECALL_QUERY_CHARS:
        return False
    return True


def _recall_message_contents(message: PromptMessage) -> tuple[str, ...]:
    content = str(message.content or "").strip()
    if not content:
        return ()
    if str(message.metadata.get("elephant_context") or "").strip() == "recall":
        return (content,)
    if content.startswith(_RECALL_CONTEXT_MARKER):
        return (content,)
    return recall_block_contents(content)


def _surfaced_recall_stats(messages: tuple[PromptMessage, ...]) -> tuple[int, frozenset[str]]:
    contents = tuple(content for message in messages for content in _recall_message_contents(message))
    return sum(len(content.encode("utf-8")) for content in contents), frozenset(contents)
