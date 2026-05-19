"""Support types and small helpers for shell progress rendering."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import os
import re
from typing import TYPE_CHECKING

from packages.kernel.runtime import KernelOutcome
from packages.tools import ToolLifecycleEvent

from .shell_stack import (
    Live,
    RICH_AVAILABLE,
)
from .shell_ui import (
    strip_markdown_bold,
)

if TYPE_CHECKING:
    from .shell import ProductizedShell


_STREAM_TOOL_BLOCK_PATTERNS = (
    re.compile(
        r"<(?:[\w.-]+:)?tool_call\b[^>]*>.*?</(?:[\w.-]+:)?tool_call\s*>",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"<(?:[\w.-]+:)?invoke\b[^>]*>.*?</(?:[\w.-]+:)?invoke\s*>",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"<(?:[\w.-]+:)?parameter\b[^>]*>.*?</(?:[\w.-]+:)?parameter\s*>",
        re.IGNORECASE | re.DOTALL,
    ),
)
_STREAM_TOOL_TAG_PATTERN = re.compile(
    r"</?(?:[\w.-]+:)?(?:tool_call|invoke|parameter)\b[^>]*>",
    re.IGNORECASE,
)
_STREAM_OPEN_TOOL_TAG_PATTERN = re.compile(
    r"<(?:[\w.-]+:)?(?:tool_call|invoke|parameter)\b[^>]*>",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class _ToolTraceDisplayParts:
    rail: str
    emoji: str
    prefix: str
    label: str
    gap: str
    body: str
    duration_gap: str
    duration: str


@dataclass(frozen=True, slots=True)
class _VisibleToolEvent:
    event: ToolLifecycleEvent
    expires_at: float
    stream_text: str = ""


@dataclass(frozen=True, slots=True)
class _KernelStageView:
    stage: str
    detail: str
    recorded_at: datetime | None


_TURN_TITLE_FRAMES: tuple[tuple[str, str], ...] = (
    ("🐘", "Elephant Agent is orienting"),
    ("🐾", "Elephant Agent is following the path"),
    ("👂", "Elephant Agent is listening"),
)

# Quiet marker palette — gentle dot fade, not twinkling sparkles. The
# whole row uses the same glyph set as the status-bar dot-pulse so the
# turn frame and status bar read as one coherent animation, not two
# competing ones.
_TURN_MARKER_FRAMES: tuple[str, ...] = ("✧", "✦", "✧", "·")
_CONTEXT_COMPACTION_MIN_VISIBLE_SECONDS = 1.5


def animations_enabled() -> bool:
    return RICH_AVAILABLE and Live is not None and os.environ.get("ELEPHANT_NO_ANIMATION") != "1"


def turn_title(tick: int) -> tuple[str, str]:
    # Slower title rotation — one frame every ~2.5s at 12.5 Hz caller.
    # Rapid title changes read as twitchy; a slow drift reads as calm
    # progress.
    return _TURN_TITLE_FRAMES[(tick // 32) % len(_TURN_TITLE_FRAMES)]


def turn_marker(tick: int) -> str:
    # Marker ticks at ~2 Hz (every 6th caller frame at 12.5 Hz) — fast
    # enough to feel alive, slow enough not to distract.
    return _TURN_MARKER_FRAMES[(tick // 6) % len(_TURN_MARKER_FRAMES)]


def turn_phase(tick: int) -> tuple[str, str, str]:
    phases = (
        ("Opening", "Opening your thread and current path"),
        ("Listening", "Staying close to who you are"),
        ("Composing", "Shaping the reply from the current path"),
    )
    # Phase copy rotates about every 1.5s at 12.5 Hz — one beat of
    # natural reading cadence.
    phase_label, phase_detail = phases[(tick // 20) % len(phases)]
    marker = turn_marker(tick)
    return marker, phase_label, phase_detail


def _parse_kernel_stage_detail(detail: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for token in str(detail).split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        normalized_key = key.strip().lower()
        if normalized_key:
            parsed[normalized_key] = value.strip()
    return parsed


def _kernel_stage_views(
    kernel_stage_events: tuple[Mapping[str, object], ...],
) -> tuple[_KernelStageView, ...]:
    views: list[_KernelStageView] = []
    for event in kernel_stage_events:
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        stage = str(payload.get("stage") or "").strip()
        if not stage:
            continue
        recorded_at_value = str(payload.get("recorded_at") or "").strip()
        recorded_at = None
        if recorded_at_value:
            try:
                recorded_at = datetime.fromisoformat(recorded_at_value)
            except ValueError:
                recorded_at = None
        views.append(
            _KernelStageView(
                stage=stage,
                detail=str(payload.get("detail") or "").strip(),
                recorded_at=recorded_at,
            )
        )
    return tuple(views)


def _format_state_focus_scope(scope: str, *, compact: bool) -> str:
    normalized = str(scope or "").strip().lower()
    if not compact:
        return normalized
    return {
        "session": "loop",
        "elephant": "state",
        "profile": "personal",
        "lineage": "lineage",
    }.get(normalized, normalized)


def _state_focus_stage_summary_parts(
    kernel_stage_events: tuple[Mapping[str, object], ...],
    *,
    compact: bool = False,
) -> tuple[str, ...]:
    views = _kernel_stage_views(kernel_stage_events)
    target_index = next(
        (index for index in range(len(views) - 1, -1, -1) if views[index].stage == "state_focus"),
        None,
    )
    if target_index is None:
        return ()
    target = views[target_index]
    detail = _parse_kernel_stage_detail(target.detail)
    parts = [detail.get("state_focus") or "unknown"]
    previous = views[target_index - 1] if target_index > 0 else None
    if previous is not None and previous.recorded_at is not None and target.recorded_at is not None:
        duration_ms = max(0, round((target.recorded_at - previous.recorded_at).total_seconds() * 1000))
        parts.append(f"{duration_ms}ms")
    scope = detail.get("scope")
    if scope and scope != "<none>":
        parts.append(_format_state_focus_scope(scope, compact=compact))
    confidence = detail.get("confidence")
    if confidence:
        parts.append(str(confidence) if compact else f"conf {confidence}")
    degradation = detail.get("degradation")
    if degradation and degradation not in {"none", "<none>"}:
        parts.append(degradation)
    return tuple(parts)


def turn_state_focus_progress_line(
    *,
    kernel_stage_events: tuple[Mapping[str, object], ...] = (),
) -> str:
    parts = _state_focus_stage_summary_parts(kernel_stage_events)
    body = "orienting..." if not parts else " · ".join(parts)
    return f"┊ 🐘 model           {body}"


def recall_progress_line(
    *,
    kernel_stage_events: tuple[Mapping[str, object], ...] = (),
) -> str | None:
    views = _kernel_stage_views(kernel_stage_events)
    recall_views = tuple(view for view in views if view.stage == "recall")
    if not recall_views:
        return None
    detail = _parse_kernel_stage_detail(recall_views[-1].detail)
    status = detail.get("status")
    if not status:
        return None
    if status in {"hit", "miss", "failed"} and len(recall_views) > 1:
        return None
    count = detail.get("count") or "0"
    if status == "searching":
        return "┊ 🗺️ recall       scanning map"
    if status == "hit":
        suffix = "signal" if count == "1" else "signals"
        return f"┊ 🗺️ recall       linked {count} {suffix}"
    if status == "miss":
        return "┊ 🗺️ recall       no signal"
    if status == "failed":
        return "┊ 🗺️ recall       signal lost"
    return f"┊ 🗺️ recall       {status}"


def loop_context_progress_line(
    *,
    kernel_stage_events: tuple[Mapping[str, object], ...] = (),
    now: datetime | None = None,
) -> str:
    views = _kernel_stage_views(kernel_stage_events)
    if not views:
        return "┊ 🧩 context      assembling"
    latest_context_view = next(
        (view for view in reversed(views) if view.stage in {"context-compact", "context"}),
        None,
    )
    if latest_context_view is None:
        return "┊ 🧩 context      assembling"
    compact_view = next((view for view in reversed(views) if view.stage == "context-compact"), None)
    if compact_view is not None and latest_context_view.stage == "context":
        if compact_view.recorded_at is not None and latest_context_view.recorded_at is not None:
            current = now or datetime.now(tz=compact_view.recorded_at.tzinfo)
            elapsed = (current - compact_view.recorded_at).total_seconds()
            if 0 <= elapsed <= _CONTEXT_COMPACTION_MIN_VISIBLE_SECONDS:
                latest_context_view = compact_view
        elif tuple(view.stage for view in views[-3:]).count("context-compact"):
            latest_context_view = compact_view
    detail = _parse_kernel_stage_detail(latest_context_view.detail)
    if latest_context_view.stage == "context-compact":
        tokens = detail.get("tokens")
        messages = detail.get("messages") or detail.get("lines")
        reason = detail.get("reason")
        parts = [_projection_compaction_label(tokens)]
        if tokens:
            parts.append(f"est {tokens} tokens")
        if messages:
            parts.append(f"{messages} messages")
        semantic_cached = detail.get("semantic_cached")
        semantic_pending = detail.get("semantic_pending")
        semantic_missed = detail.get("semantic_missed")
        if semantic_cached is not None or semantic_pending is not None or semantic_missed is not None:
            parts.append(
                "scanner: "
                f"{semantic_cached or '0'} cached / {semantic_pending or '0'} pending / {semantic_missed or '0'} missed"
            )
        if reason:
            parts.append(reason)
        return f"┊ 🧩 context      {' · '.join(parts)}"
    budget = detail.get("budget")
    body = f"ready · budget {budget}" if budget else "ready"
    return f"┊ 🧩 context      {body}"


def _projection_compaction_label(tokens: str | None) -> str:
    if not tokens:
        return "projection compact"
    match = re.fullmatch(r"(\d+)->(\d+)", tokens.strip())
    if match is None:
        return "projection compact"
    before_tokens = int(match.group(1))
    after_tokens = int(match.group(2))
    if after_tokens >= before_tokens:
        return "projection rewrite"
    return "projection compact"


def _latest_stage_detail(views: tuple[_KernelStageView, ...], stage: str) -> dict[str, str]:
    view = next((item for item in reversed(views) if item.stage == stage), None)
    return _parse_kernel_stage_detail(view.detail) if view is not None else {}


def turn_usage_progress_line(
    *,
    kernel_stage_events: tuple[Mapping[str, object], ...] = (),
) -> str:
    views = _kernel_stage_views(kernel_stage_events)
    usage = _latest_stage_detail(views, "context-usage")
    usage_tokens = usage.get("total_tokens") or usage.get("prompt_tokens")
    projection = _latest_stage_detail(views, "context-projection")
    context = _latest_stage_detail(views, "context")
    limit = projection.get("token_budget") or context.get("budget")
    if not usage_tokens:
        projection_tokens = projection.get("prompt_tokens")
        if projection_tokens and limit:
            try:
                percent = max(0, min(100, round((int(projection_tokens) / int(limit)) * 100)))
            except ValueError:
                percent = None
            if percent is not None:
                return f"┊ 📈 request      provider running · sent est {projection_tokens}/{limit} · {percent}% · usage pending"
        if projection_tokens:
            return f"┊ 📈 request      provider running · sent est {projection_tokens} tokens · usage pending"
        return "┊ 📈 request      provider running · usage pending"
    if limit:
        try:
            percent = max(0, min(100, round((int(usage_tokens) / int(limit)) * 100)))
        except ValueError:
            percent = None
        if percent is not None:
            return f"┊ 📈 request      {usage_tokens}/{limit} · {percent}%"
    return f"┊ 📈 request      {usage_tokens} total tokens"


def outcome_state_focus_meta(outcome: KernelOutcome) -> str:
    stage_events = tuple(
        {
            "payload": {
                "stage": stage.stage,
                "detail": stage.detail,
                "recorded_at": stage.recorded_at.isoformat(),
            }
        }
        for stage in outcome.stages
    )
    parts = _state_focus_stage_summary_parts(stage_events, compact=True)
    if not parts:
        return ""
    return f"routing · {' · '.join(parts)}"


def summarize_progress_prompt(prompt: str) -> str:
    normalized = " ".join(prompt.split())
    if len(normalized) <= 72:
        return normalized
    return f"{normalized[:69]}..."


def pending_tooltrace_lines(shell: ProductizedShell) -> tuple[str, ...]:
    pending = shell.transcript[shell._rendered_entries :]
    lines: list[str] = []
    for entry in pending:
        if entry.kind != "tooltrace":
            continue
        body_lines = entry.body.splitlines() or [entry.body]
        for body_line in body_lines:
            normalized = strip_markdown_bold(body_line).rstrip("\n")
            if not normalized or not normalized.startswith("┊ "):
                continue
            if lines and lines[-1] == normalized:
                continue
            lines.append(normalized)
    return tuple(lines)


def pending_tool_output_lines(shell: ProductizedShell) -> tuple[str, ...]:
    pending = shell.transcript[shell._rendered_entries :]
    lines: list[str] = []
    for entry in pending:
        if entry.kind != "tooltrace":
            continue
        body_lines = entry.body.splitlines() or [entry.body]
        for body_line in body_lines:
            normalized = strip_markdown_bold(body_line).rstrip("\n")
            if not normalized or normalized.startswith("┊ "):
                continue
            lines.append(normalized)
    return tuple(lines[-80:])


def pending_tool_display_lines(shell: ProductizedShell, *, limit: int | None = None) -> tuple[str, ...]:
    pending = shell.transcript[shell._rendered_entries :]
    lines: list[str] = []
    for entry in pending:
        if entry.kind != "tooltrace":
            continue
        body_lines = entry.body.splitlines() or [entry.body]
        for body_line in body_lines:
            normalized = strip_markdown_bold(body_line).rstrip("\n")
            if not normalized:
                continue
            if lines and lines[-1] == normalized:
                continue
            lines.append(normalized)
    if limit is None or len(lines) <= limit:
        return tuple(lines)
    hidden = len(lines) - (limit - 1)
    return (f"… {hidden} earlier tool line(s) hidden", *lines[-(limit - 1) :])


def live_tool_feed_lines(
    shell: ProductizedShell,
    *,
    tool_event: ToolLifecycleEvent | None = None,
    tool_events: tuple[ToolLifecycleEvent, ...] = (),
    limit: int | None = None,
) -> tuple[str, ...]:
    from .shell_progress_trace import tool_event_progress_lines

    pending_limit = None if limit is None else max(limit, 8)
    lines = list(pending_tool_display_lines(shell, limit=pending_limit))
    seen = set(lines)
    for line in tool_event_progress_lines(shell, tool_event=tool_event, tool_events=tool_events):
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)
    if limit is None or len(lines) <= limit:
        return tuple(lines)
    hidden = len(lines) - (limit - 1)
    return (f"… {hidden} earlier tool line(s) hidden", *lines[-(limit - 1) :])


def turn_tool_progress_lines(
    shell: ProductizedShell,
    *,
    tool_event: ToolLifecycleEvent | None = None,
    tool_events: tuple[ToolLifecycleEvent, ...] = (),
) -> tuple[str, ...]:
    from .shell_progress_trace import tool_event_progress_lines

    lines: list[str] = []
    seen: set[str] = set()
    for line in pending_tooltrace_lines(shell):
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)
    for line in tool_event_progress_lines(shell, tool_event=tool_event, tool_events=tool_events):
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return tuple(lines[-12:])
