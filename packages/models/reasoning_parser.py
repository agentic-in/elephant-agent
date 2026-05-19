"""Shared helpers for extracting visible reasoning from model output.

The parser handles the common reasoning-tag conventions used by
instruction-tuned and reasoning models:
- reasoning may arrive inside ``<think>``, ``<thinking>``, or ``<reasoning>`` tags
- code fences and inline code are protected so literal tags stay literal
- streaming mode keeps a trailing unclosed reasoning tag as pending reasoning
"""

from __future__ import annotations

from dataclasses import dataclass
import re


_TAG_RE = re.compile(r"<(think|thinking|reasoning)>([\s\S]*?)</\1>", re.IGNORECASE)
_OPEN_RE = re.compile(r"<(think|thinking|reasoning)>([\s\S]*)$", re.IGNORECASE)
_PLACEHOLDER_PREFIX = "\u0000ELEPHANTREASON"
_PLACEHOLDER_SUFFIX = "\u0000"
_FENCED_RE = re.compile(r"(^|\n)( {0,3})(`{3,}|~{3,})[^\n]*\n[\s\S]*?\n\2\3[ \t]*(?=\n|$)")
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
_CLOSING_PUNCTUATION = ",.!?;:)]}%>”’、，。！？；："
_OPENING_PUNCTUATION = "([{%<$#@/“‘"
_SENTENCE_PUNCTUATION = ",.!?;:。！？；："
_OPENING_QUOTES = '"“‘'


def _is_cjk(char: str) -> bool:
    if not char:
        return False
    code = ord(char)
    return 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF or 0x3040 <= code <= 0x30FF or 0xAC00 <= code <= 0xD7AF


def _needs_collapsed_whitespace_spacing(previous: str, current: str) -> bool:
    left = previous[-1:] if previous else ""
    right = current[:1] if current else ""
    if not left or not right:
        return False
    if left.isspace() or right.isspace():
        return False
    if right in _CLOSING_PUNCTUATION:
        return False
    if left in _OPENING_PUNCTUATION:
        return False
    if left in _SENTENCE_PUNCTUATION and right.isalnum():
        return True
    if _is_cjk(left) or _is_cjk(right):
        return False
    return left.isalnum() and right.isalnum()


def _needs_direct_token_spacing(previous: str, current: str) -> bool:
    left = previous[-1:] if previous else ""
    right = current[:1] if current else ""
    if not left or not right:
        return False
    if left.isspace() or right.isspace():
        return False
    if right in _CLOSING_PUNCTUATION:
        return False
    if left in _OPENING_PUNCTUATION:
        return False
    if left.isalnum() and right in _OPENING_QUOTES:
        return True
    if _is_cjk(left) or _is_cjk(right):
        return False
    if left in _SENTENCE_PUNCTUATION and right.isalnum():
        return True
    if left.isalnum() and right.isalnum():
        return True
    return False


def stitch_text_fragments(*parts: str | None) -> str:
    stitched: list[str] = []
    pending_whitespace = False
    for part in parts:
        text = str(part or "")
        if not text:
            continue
        if text.isspace():
            pending_whitespace = True
            continue
        if not stitched:
            stitched.append(text)
            pending_whitespace = False
            continue
        previous = stitched[-1]
        if pending_whitespace:
            if not text[:1].isspace() and _needs_collapsed_whitespace_spacing(previous, text):
                stitched.append(" ")
            pending_whitespace = False
        elif _needs_direct_token_spacing(previous, text):
            stitched.append(" ")
        stitched.append(text)
    return "".join(stitched)


def normalize_reasoning_text(text: str | None) -> str:
    return stitch_text_fragments(*re.split(r"(\s+)", str(text or ""))).strip()


@dataclass(frozen=True, slots=True)
class ParsedReasoningContent:
    segments: tuple[str, ...] = ()
    pending: str | None = None
    body: str = ""
    has_reasoning: bool = False

    @property
    def reasoning_text(self) -> str:
        return stitch_text_fragments(*self.segments, self.pending or "")


@dataclass(frozen=True, slots=True)
class _ProtectedCode:
    masked: str
    blocks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CombinedReasoning:
    content: str
    reasoning: str


def _protect_code_blocks(text: str) -> _ProtectedCode:
    blocks: list[str] = []

    def replace_block(match: re.Match[str]) -> str:
        blocks.append(match.group(0))
        return f"{_PLACEHOLDER_PREFIX}{len(blocks) - 1}{_PLACEHOLDER_SUFFIX}"

    masked = _FENCED_RE.sub(replace_block, text)
    masked = _INLINE_CODE_RE.sub(replace_block, masked)
    return _ProtectedCode(masked=masked, blocks=tuple(blocks))


def _restore_code_blocks(text: str, blocks: tuple[str, ...]) -> str:
    if not blocks:
        return text
    placeholder_re = re.compile(re.escape(_PLACEHOLDER_PREFIX) + r"(\d+)" + re.escape(_PLACEHOLDER_SUFFIX))
    restored = text
    while True:
        changed = False

        def replace_placeholder(match: re.Match[str]) -> str:
            nonlocal changed
            changed = True
            index = int(match.group(1))
            return blocks[index] if 0 <= index < len(blocks) else ""

        next_text = placeholder_re.sub(replace_placeholder, restored)
        restored = next_text
        if not changed:
            return restored


def parse_reasoning_content(content: str, *, streaming: bool) -> ParsedReasoningContent:
    protected = _protect_code_blocks(content)
    masked = protected.masked
    segments: list[str] = []
    body_parts: list[str] = []
    last_index = 0

    for match in _TAG_RE.finditer(masked):
        body_parts.append(masked[last_index : match.start()])
        segments.append(match.group(2))
        last_index = match.end()

    rest = masked[last_index:]
    pending: str | None = None
    open_match = _OPEN_RE.search(rest)
    if open_match is not None:
        boundary = open_match.start()
        body_parts.append(rest[:boundary])
        if streaming:
            pending = open_match.group(2)
        else:
            body_parts.append(rest[boundary:])
    else:
        body_parts.append(rest)

    restored_segments = tuple(_restore_code_blocks(segment, protected.blocks) for segment in segments)
    restored_pending = _restore_code_blocks(pending, protected.blocks) if pending is not None else None
    restored_body = _restore_code_blocks("".join(body_parts), protected.blocks)
    return ParsedReasoningContent(
        segments=restored_segments,
        pending=restored_pending,
        body=restored_body,
        has_reasoning=bool(restored_segments or restored_pending is not None),
    )


def _reasoning_dedupe_key(text: str) -> str:
    return stitch_text_fragments(*re.split(r"(\s+)", text))


def combine_reasoning_text(*parts: str | None) -> str:
    ordered: list[str] = []
    seen: set[str] = set()
    for part in parts:
        normalized = str(part or "").strip()
        if not normalized:
            continue
        dedupe_key = _reasoning_dedupe_key(normalized)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        ordered.append(normalized)
    return "\n\n".join(ordered)


def split_reasoning_and_content(
    content: str,
    *,
    streaming: bool,
    reasoning: str | None = None,
) -> CombinedReasoning:
    parsed = parse_reasoning_content(content, streaming=streaming)
    return CombinedReasoning(
        content=parsed.body,
        reasoning=combine_reasoning_text(reasoning, parsed.reasoning_text),
    )


__all__ = [
    "CombinedReasoning",
    "ParsedReasoningContent",
    "combine_reasoning_text",
    "normalize_reasoning_text",
    "parse_reasoning_content",
    "split_reasoning_and_content",
    "stitch_text_fragments",
]
