"""Tool trace and frame rendering helpers for shell progress."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import re
import threading
from typing import TYPE_CHECKING

from packages.kernel.runtime import KernelOutcome
from packages.models.reasoning_parser import split_reasoning_and_content
from packages.tools import ToolLifecycleEvent

from .shell_stack import (
    Application,
    Condition,
    ConditionalContainer,
    FormattedText,
    FormattedTextControl,
    Group,
    Layout,
    Live,
    Panel,
    RICH_AVAILABLE,
    Text,
    Window,
)
from .shell_ui import (
    BRAND_ACCENT,
    BRAND_ACCENT_STRONG,
    BRAND_DARK,
    BRAND_LIGHT,
    BRAND_MUTED,
    LIVE_DIFF_ADD_FG,
    LIVE_DIFF_CONTEXT_FG,
    LIVE_DIFF_FILE_FG,
    LIVE_DIFF_HUNK_FG,
    LIVE_DIFF_REMOVE_FG,
    QUEUE_PREVIEW_INSET,
    compact_line,
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

from .shell_progress_support import (
    _ToolTraceDisplayParts,
    _VisibleToolEvent,
    live_tool_feed_lines,
    pending_tool_display_lines,
    summarize_progress_prompt,
    recall_progress_line,
    loop_context_progress_line,
    turn_state_focus_progress_line,
    turn_marker,
    turn_phase,
    turn_title,
    turn_tool_progress_lines,
)

LOGGER = logging.getLogger(__name__)


def render_turn_frame(
    shell: ProductizedShell,
    *,
    prompt: str,
    tick: int,
    tool_event: ToolLifecycleEvent | None = None,
    tool_events: tuple[ToolLifecycleEvent, ...] = (),
    kernel_stage_events: tuple[dict[str, object], ...] = (),
    stream_text: str = "",
    tool_event_holder=None,
    tool_event_lock=None,
):
    from .shell_progress_runtime import render_live_tool_line_text

    marker, _phase_label, phase_detail = turn_phase(tick)
    title_glyph, title_copy = turn_title(tick)
    live_lines = live_tool_feed_lines(shell, tool_event=tool_event, tool_events=tool_events)
    if not RICH_AVAILABLE:
        stream_preview = _stream_response_text(stream_text, limit=280)
        progress_lines = [
            f"{marker} {phase_detail}",
            turn_state_focus_progress_line(kernel_stage_events=kernel_stage_events),
        ]
        context_line = loop_context_progress_line(kernel_stage_events=kernel_stage_events)
        if _is_compaction_context_line(context_line):
            progress_lines.append(context_line)
        recall_line = recall_progress_line(kernel_stage_events=kernel_stage_events)
        if recall_line:
            progress_lines.append(recall_line)
        body = "\n".join(progress_lines)
        if live_lines:
            body = f"{body}\n" + "\n".join(live_lines)
        if stream_preview:
            body = f"{body}\n\n{stream_preview}"
        return body
    progress_body = Text()
    progress_body.append(marker, style=BRAND_MUTED)
    progress_body.append(f" {phase_detail}", style=BRAND_LIGHT)
    progress_body.append("\n")
    progress_body.append_text(render_live_tool_line_text(turn_state_focus_progress_line(kernel_stage_events=kernel_stage_events)))
    context_line = loop_context_progress_line(kernel_stage_events=kernel_stage_events)
    if _is_compaction_context_line(context_line):
        progress_body.append("\n")
        progress_body.append_text(render_live_tool_line_text(context_line))
    recall_line = recall_progress_line(kernel_stage_events=kernel_stage_events)
    if recall_line:
        progress_body.append("\n")
        progress_body.append_text(render_live_tool_line_text(recall_line))
    
    # Render tool lines with stream text anchored to the matching tool event when
    # possible, while preserving the full merged tool rail from transcript + live events.
    if tool_event_holder is not None and tool_event_lock is not None:
        from .shell_progress_runtime import stream_anchor_events, visible_tool_events
        visible_events = visible_tool_events(tool_event_holder, tool_event_lock)
        stable_stream_anchors = stream_anchor_events(tool_event_holder, tool_event_lock)
        previous_stream_was_reasoning_only = False
        for item_kind, item_text in anchored_tool_progress_items(
            shell,
            visible_events=visible_events,
            stream_text=stream_text,
            stream_anchor_events=stable_stream_anchors,
        ):
            progress_body.append("\n\n" if item_kind == "line" and previous_stream_was_reasoning_only else "\n")
            if item_kind == "stream":
                progress_body.append_text(_stream_response_rich_text(item_text))
                previous_stream_was_reasoning_only = _stream_has_reasoning_only(item_text)
            else:
                progress_body.append_text(render_live_tool_line_text(item_text))
                previous_stream_was_reasoning_only = False
    else:
        stream_response = _stream_response_rich_text(stream_text)
        stream_has_reasoning_only = _stream_has_reasoning_only(stream_text)
        if stream_response.plain:
            progress_body.append("\n")
            progress_body.append_text(stream_response)
        for live_index, live_line in enumerate(live_lines):
            progress_body.append("\n\n" if live_index == 0 and stream_has_reasoning_only else "\n")
            progress_body.append_text(render_live_tool_line_text(live_line))
    
    progress_panel = Panel(
        progress_body,
        title=f"[bold {BRAND_ACCENT}]{title_glyph} {title_copy}[/bold {BRAND_ACCENT}]",
        border_style=BRAND_DARK,
        padding=(0, 1),
    )
    return progress_panel

def render_tool_frame(
    shell: ProductizedShell,
    *,
    tool_id: str,
    tick: int,
    tool_event: ToolLifecycleEvent | None = None,
    tool_events: tuple[ToolLifecycleEvent, ...] = (),
):
    from .shell_progress_runtime import render_live_tool_line_text

    phases = tool_frame_phases(shell, tool_id, tool_event=tool_event)
    phase_label, phase_detail = phases[(tick // 3) % len(phases)]
    marker = turn_marker(tick)
    live_lines = live_tool_feed_lines(shell, tool_event=tool_event, tool_events=tool_events)
    if not RICH_AVAILABLE:
        body = f"{marker} {phase_detail}"
        if live_lines:
            body = f"{body}\n" + "\n".join(live_lines)
        return body
    body = Text()
    body.append(marker, style=BRAND_MUTED)
    body.append(f" {phase_detail}\n", style=BRAND_LIGHT)
    body.append(f"{phase_label} · {tool_id}", style=BRAND_MUTED)
    for live_line in live_lines:
        body.append("\n")
        body.append_text(render_live_tool_line_text(live_line))
    return Panel(
        body,
        title=f"[bold {BRAND_ACCENT}]🛠️ Elephant Agent is using a tool[/bold {BRAND_ACCENT}]",
        border_style=BRAND_DARK,
        padding=(0, 1),
    )

def tool_frame_phases(
    shell: ProductizedShell,
    tool_id: str,
    *,
    tool_event: ToolLifecycleEvent | None = None,
) -> tuple[tuple[str, str], ...]:
    return (
        ("tool.prepare", "Preparing the tool call"),
        ("tool.execute", "Working inside this Episode"),
        ("tool.report", "Adding the result to the Step trail"),
    )

def tool_trace_line(
    shell: ProductizedShell,
    tool_event: ToolLifecycleEvent | None,
) -> str | None:
    if tool_event is None:
        return None
    tool_id = tool_event.invocation.tool_id
    emoji = _tool_trace_emoji(tool_id)
    marker = _tool_trace_emoji_marker(emoji)
    label = _tool_trace_label(tool_event)
    if tool_event.phase == "requested":
        prepare_label = _tool_trace_prepare_label(tool_event)
        preview = _tool_trace_preview(tool_event.invocation.arguments, tool_id=tool_id)
        if preview and preview != prepare_label:
            return f"┊ {marker}Calling {prepare_label} · {preview}…"
        return f"┊ {marker}Calling {prepare_label}…"
    if tool_event.phase == "approval.denied":
        return f"┊ {marker}{label:<12} blocked"
    if tool_event.phase == "approval.deferred":
        return f"┊ {marker}{label:<12} awaiting approval"
    if tool_event.phase not in {"execution.completed", "execution.failed"}:
        return None
    preview = _tool_trace_preview(tool_event.invocation.arguments, tool_id=tool_id)
    duration = _tool_trace_duration(tool_event)
    duration_part = f"  {duration}" if duration else ""
    if tool_event.phase == "execution.failed":
        if preview and tool_id in {"tool.terminal.exec", "tool.process.manage"}:
            return f"┊ {marker}{label:<12} {preview} [error]{duration_part}"
        failure_label = compact_line(tool_event.detail or "failed", limit=28)
        return f"┊ {marker}{label:<12} {failure_label}{duration_part}"
    if preview:
        return f"┊ {marker}{label:<12} {preview}{duration_part}"
    return f"┊ {marker}{label}{duration_part}"

def tool_event_progress_line(
    shell: ProductizedShell,
    tool_event: ToolLifecycleEvent | None,
) -> str | None:
    if tool_event is None:
        return None
    if tool_event.phase == "execution.started":
        emoji = _tool_trace_emoji(tool_event.invocation.tool_id, tool_event.invocation.arguments)
        marker = _tool_trace_emoji_marker(emoji)
        label = _tool_trace_started_label(tool_event)
        preview = _tool_trace_preview(tool_event.invocation.arguments, tool_id=tool_event.invocation.tool_id)
        if preview:
            return f"┊ {marker}{label:<12} {preview}"
        return f"┊ {marker}{label}"
    return tool_trace_line(shell, tool_event)

def tool_event_progress_lines(
    shell: ProductizedShell,
    *,
    tool_event: ToolLifecycleEvent | None = None,
    tool_events: tuple[ToolLifecycleEvent, ...] = (),
) -> tuple[str, ...]:
    lines: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    events = tool_events or ((tool_event,) if tool_event is not None else ())
    for event in events[-3:]:
        event_lines = _tool_event_progress_lines_for_event(shell, event)
        for line in event_lines:
            key = (event.invocation.invocation_id, event.phase, line)
            if key in seen:
                continue
            seen.add(key)
            lines.append(line)
    return tuple(lines)

def anchored_tool_progress_items(
    shell: ProductizedShell,
    *,
    visible_events: tuple[_VisibleToolEvent, ...],
    stream_text: str,
    stream_anchor_events: tuple[_VisibleToolEvent, ...] = (),
) -> tuple[tuple[str, str], ...]:
    tool_lines = list(
        live_tool_feed_lines(
            shell,
            tool_events=tuple(visible_event.event for visible_event in visible_events),
        )
    )
    insertions: dict[int, list[str]] = {}
    rendered_stream_text = ""
    search_start = 0
    anchor_events = stream_anchor_events or tuple(
        visible_event for visible_event in visible_events if visible_event.stream_text
    )

    for anchor_event in anchor_events:
        candidate_line_groups: list[tuple[str, ...]] = []
        event_lines = tool_event_progress_lines(shell, tool_event=anchor_event.event)
        if event_lines:
            candidate_line_groups.append(event_lines)
        invocation_id = anchor_event.event.invocation.invocation_id
        for visible_event in visible_events:
            if visible_event.event.invocation.invocation_id != invocation_id:
                continue
            visible_lines = tool_event_progress_lines(shell, tool_event=visible_event.event)
            if visible_lines:
                candidate_line_groups.append(visible_lines)
        anchor_index: int | None = None
        for candidate_lines in candidate_line_groups:
            for index in range(search_start, len(tool_lines)):
                if tool_lines[index] in candidate_lines:
                    anchor_index = index
                    search_start = index + 1
                    break
            if anchor_index is not None:
                break
        response_text = stream_response_delta(anchor_event.stream_text, previous_stream_text=rendered_stream_text)
        if response_text:
            insertions.setdefault(len(tool_lines) if anchor_index is None else anchor_index, []).append(response_text)
        snapshot_text = _stream_response_text(anchor_event.stream_text)
        if snapshot_text and len(snapshot_text) >= len(rendered_stream_text):
            rendered_stream_text = snapshot_text

    response_tail = stream_response_delta(stream_text, previous_stream_text=rendered_stream_text)
    if response_tail:
        insertions.setdefault(len(tool_lines), []).append(response_tail)

    items: list[tuple[str, str]] = []
    for index, line in enumerate(tool_lines):
        for response_text in insertions.get(index, ()): 
            items.append(("stream", response_text))
        items.append(("line", line))
    for response_text in insertions.get(len(tool_lines), ()): 
        items.append(("stream", response_text))
    return tuple(items)

def _tool_event_progress_lines_for_event(
    shell: ProductizedShell,
    event: ToolLifecycleEvent,
) -> tuple[str, ...]:
    if event.phase == "execution.started" and event.invocation.tool_id == "tool.sub_agents":
        expanded = _sub_agents_trace_progress_lines(event.invocation.arguments)
        if expanded:
            return expanded
    line = tool_event_progress_line(shell, event)
    return () if line is None else (line,)

def tool_event_lines(
    shell: ProductizedShell,
    tool_event: ToolLifecycleEvent | None,
) -> tuple[str | None, str | None]:
    if tool_event is None:
        return (None, None)
    phase_labels = {
        "requested": "Tool requested",
        "classified": "Tool classified",
        "approval.granted": "Approval granted",
        "approval.denied": "Approval denied",
        "approval.deferred": "Approval deferred",
        "execution.started": "Tool executing",
        "execution.completed": "Tool completed",
        "execution.failed": "Tool failed",
    }
    title = f"{phase_labels.get(tool_event.phase, tool_event.phase)} · {tool_event.invocation.tool_id}"
    detail = compact_line(" ".join((tool_event.detail or "").split()), limit=112) if tool_event.detail else ""
    details = [detail] if detail else []
    if tool_event.approval is not None and tool_event.approval.required_controls:
        details.append(f"controls: {', '.join(tool_event.approval.required_controls)}")
    if tool_event.execution is not None:
        details.append(f"outcome: {tool_event.execution.outcome}")
    return (title, " · ".join(part for part in details if part))

def tool_event_summary(shell: ProductizedShell, tool_event: ToolLifecycleEvent | None) -> str | None:
    if tool_event is None:
        return None
    line = tool_event_progress_line(shell, tool_event)
    if line:
        return compact_line(strip_markdown_bold(line.replace("┊ ", "")), limit=112)
    title, _ = tool_event_lines(shell, tool_event)
    return title

def render_tool_trace_fragments(line: str, *, leading_newline: bool = False) -> list[tuple[str, str]]:
    parts = _tool_trace_display_parts(line)
    if _is_state_focus_trace_line(line):
        fragments: list[tuple[str, str]] = []
        if leading_newline:
            fragments.append(("", "\n"))
        for text in (parts.rail, f"{parts.emoji} " if parts.emoji else "", parts.prefix, parts.label):
            if text:
                fragments.append(("class:progress-state-focus", text))
        if parts.body:
            fragments.append(("class:progress-state-focus", parts.gap or " "))
            fragments.append(("class:progress-state-focus", parts.body))
        if parts.duration:
            fragments.append(("class:progress-state-focus", parts.duration_gap or "  "))
            fragments.append(("class:progress-state-focus", parts.duration))
        return fragments
    state = _tool_trace_state(line)
    emoji_style = "class:progress-tool-emoji" if state == "done" else "class:progress-tool-verb"
    label_style = "class:progress-tool-label" if state in {"done", "error"} else "class:progress-tool-verb"
    body_style = "class:progress-tool-body" if state in {"done", "error"} else "class:progress-tool-verb"
    fragments: list[tuple[str, str]] = []
    if leading_newline:
        fragments.append(("", "\n"))
    if parts.rail:
        fragments.append(("class:progress-tool-rail", parts.rail))
    if parts.emoji:
        fragments.append((emoji_style, _tool_trace_emoji_marker(parts.emoji)))
    if parts.prefix:
        fragments.append(("class:progress-tool-verb", parts.prefix))
    fragments.append((label_style, parts.label))
    if parts.body:
        fragments.append(("class:progress-tool-gap", parts.gap or " "))
        fragments.append((body_style, parts.body))
    if parts.duration:
        fragments.append(("class:progress-tool-gap", parts.duration_gap or "  "))
        fragments.append(("class:progress-tool-duration", parts.duration))
    return fragments

def render_tool_trace_text(line: str) -> Text:
    parts = _tool_trace_display_parts(line)
    if _is_state_focus_trace_line(line):
        block = Text()
        for text in (parts.rail, f"{parts.emoji} " if parts.emoji else "", parts.prefix, parts.label):
            if text:
                block.append(text, style=BRAND_ACCENT_STRONG)
        if parts.body:
            block.append(parts.gap or " ", style=BRAND_ACCENT_STRONG)
            block.append(parts.body, style=BRAND_ACCENT_STRONG)
        if parts.duration:
            block.append(parts.duration_gap or "  ", style=BRAND_ACCENT_STRONG)
            block.append(parts.duration, style=BRAND_ACCENT_STRONG)
        return block
    state = _tool_trace_state(line)
    emoji_style = BRAND_ACCENT if state == "done" else BRAND_MUTED
    label_style = f"bold {BRAND_ACCENT_STRONG}" if state in {"done", "error"} else BRAND_MUTED
    body_style = BRAND_LIGHT if state in {"done", "error"} else BRAND_MUTED
    block = Text()
    if parts.rail:
        block.append(parts.rail, style=BRAND_DARK)
    if parts.emoji:
        block.append(_tool_trace_emoji_marker(parts.emoji), style=emoji_style)
    if parts.prefix:
        block.append(parts.prefix, style=BRAND_MUTED)
    block.append(parts.label, style=label_style)
    if parts.body:
        block.append(parts.gap or " ")
        block.append(parts.body, style=body_style)
    if parts.duration:
        block.append(parts.duration_gap or "  ")
        block.append(parts.duration, style=BRAND_MUTED)
    return block

def _is_state_focus_trace_line(line: str) -> bool:
    normalized = strip_markdown_bold(line)
    return (
        normalized.startswith("┊ 🧭 focus")
        or normalized.startswith("┊ 🐘 model")
        or normalized.startswith("┊ 🧭 routing")
    )

def _is_compaction_context_line(line: str) -> bool:
    return line.startswith("┊ 🧩 context") and (
        "projection" in line or "compressing" in line
    )

def _tool_trace_display_parts(line: str) -> _ToolTraceDisplayParts:
    body = strip_markdown_bold(line).rstrip("\n")
    rail = ""
    if body.startswith("┊ "):
        rail = "┊ "
        body = body[2:]
    emoji_match = re.match(r"(?P<emoji>\S+)(?P<separator>\s+)(?P<remainder>.*)$", body)
    if emoji_match is None:
        return _ToolTraceDisplayParts(rail="", emoji="", prefix="", label=body, gap="", body="", duration_gap="", duration="")
    emoji = emoji_match.group("emoji")
    remainder = emoji_match.group("remainder").lstrip()

    duration_gap = ""
    duration = ""
    duration_match = re.search(r"(?P<spacing>\s{2,})(?P<duration>\d+(?:\.\d)?s)$", remainder)
    if duration_match is not None:
        duration_gap = duration_match.group("spacing")
        duration = duration_match.group("duration")
        remainder = remainder[: duration_match.start()].rstrip()

    prefix = ""
    label = remainder
    gap = ""
    tail = ""
    if remainder.startswith("Calling "):
        prefix = "Calling "
        label = remainder.removeprefix("Calling ")
    else:
        detail_match = re.match(r"(?P<label>.+?)(?P<gap>\s{2,})(?P<body>.+)$", remainder)
        if detail_match is not None:
            label = detail_match.group("label")
            gap = detail_match.group("gap")
            tail = detail_match.group("body")

    return _ToolTraceDisplayParts(
        rail=rail,
        emoji=emoji,
        prefix=prefix,
        label=label,
        gap=gap,
        body=tail,
        duration_gap=duration_gap,
        duration=duration,
    )

def _tool_trace_state(line: str) -> str:
    normalized = strip_markdown_bold(line).rstrip("\n")
    parts = _tool_trace_display_parts(normalized)
    if "[error]" in normalized:
        return "error"
    if parts.prefix == "Calling ":
        return "active"
    if "awaiting approval" in normalized or normalized.endswith(" blocked"):
        return "active"
    if parts.body and not parts.duration:
        return "active"
    return "done"

def _tool_trace_emoji(tool_id: str, arguments=None) -> str:
    if tool_id.startswith("mcp."):
        return "🧩"
    emoji_by_tool = {
        "tool.web.search": "🌐",
        "tool.web.read": "🌐",
        "tool.web.extract": "🌐",
        "tool.file.search": "🔎",
        "tool.file.read": "📖",
        "tool.file.write": "✍️",
        "tool.file.patch": "🩹",
        "tool.code.execute": "🛠️",
        "tool.terminal.exec": "💻",
        "tool.process.manage": "🖥️",
        "tool.clarify": "❓",
        "tool.cron.manage": "⏰",
        "tool.personal_model.search": "🐘",
        "tool.conversation.search": "🐾",
        "tool.personal_model.update": "🌱",
        "tool.personal_model.questions": "👂",
        "tool.diary.list": "🌾",
        "tool.diary.write": "🌾",
        "tool.sub_agents": "🐘",
        "tool.skill.list": "🧩",
        "tool.skill.view": "🧩",
        "tool.skill.manage": "🧩",
        "tool.message.send": "📨",
        "tool.todo.manage": "📋",
    }
    if tool_id in emoji_by_tool:
        return emoji_by_tool[tool_id]
    if tool_id.startswith("tool.browser."):
        return "🌐"
    return "🧩"

def _tool_trace_emoji_marker(emoji: str) -> str:
    if emoji in {"✍️", "🖥️", "🛠️"}:
        return f"{emoji}  "
    return f"{emoji} "

def _tool_trace_label(tool_event: ToolLifecycleEvent) -> str:
    tool_id = tool_event.invocation.tool_id
    aliases = {
        "tool.file.search": "grep",
        "tool.file.read": "read",
        "tool.file.write": "write",
        "tool.file.patch": "patch",
        "tool.web.search": "search",
        "tool.web.read": "fetch",
        "tool.terminal.exec": "computer",
        "tool.process.manage": "proc",
        "tool.cron.manage": "cron",
        "tool.personal_model.search": "model",
        "tool.conversation.search": "trail",
        "tool.personal_model.update": "learn",
        "tool.personal_model.questions": "ask",
        "tool.diary.list": "rhythm",
        "tool.diary.write": "rhythm",
        "tool.sub_agents": "herd",
        "tool.skill.list": "skills",
        "tool.skill.view": "skill",
        "tool.skill.manage": "skill",
        "tool.todo.manage": "todo",
        "tool.message.send": "message",
        "tool.code.execute": "code",
    }
    if tool_id.startswith("tool.browser."):
        return tool_id.removeprefix("tool.browser.")
    return aliases.get(tool_id, tool_id.removeprefix("tool."))

def _personal_model_trace_preview(arguments, *, tool_id: str | None = None) -> str:
    action = str(arguments.get("action") or "").strip().lower()
    topic = str(arguments.get("topic") or "").strip()
    lens = str(arguments.get("lens") or "").strip()
    query = str(arguments.get("query") or "").strip()
    claim = str(arguments.get("claim") or "").strip()
    time_range = arguments.get("time_range") if isinstance(arguments.get("time_range"), dict) else {}
    expr = str(time_range.get("expr") or arguments.get("expr") or "").strip()
    start_at = str(time_range.get("start_at") or arguments.get("start_at") or "").strip()
    target = topic or lens or query or claim or expr or start_at
    fallback_by_tool = {
        "tool.personal_model.search": "model",
        "tool.conversation.search": "trail",
        "tool.personal_model.update": "learn",
        "tool.personal_model.questions": "ask",
    }
    fallback = fallback_by_tool.get(tool_id, "model")
    return compact_line(" ".join(item for item in (action, target) if item).strip() or fallback, limit=64)

def _tool_trace_preview(arguments, *, tool_id: str | None = None) -> str:
    if tool_id == "tool.sub_agents":
        preview = _sub_agents_trace_preview(arguments)
        if preview:
            return preview
    if tool_id in {"tool.personal_model.search", "tool.conversation.search", "tool.personal_model.update", "tool.personal_model.questions"}:
        preview = _personal_model_trace_preview(arguments, tool_id=tool_id)
        if preview:
            return preview
    if tool_id == "tool.process.manage":
        action = str(arguments.get("action") or "").strip().lower()
        process_id = str(arguments.get("process_id") or "").strip()
        if action and process_id:
            return compact_line(f"{action} {process_id}", limit=56)
        if action:
            return compact_line(action, limit=36)
    if tool_id == "tool.terminal.exec":
        command = str(arguments.get("command") or "").strip()
        if command:
            return compact_line(command, limit=96)
    preview_keys = (
        "query",
        "pattern",
        "url",
        "path",
        "file_path",
        "filePath",
        "command",
        "title",
        "prompt",
        "name",
        "message",
        "text",
        "content",
        "elephant_identity_text",
        "user_text",
        "user_content",
        "relationship_text",
        "relationship_content",
        "reference",
        "evidence_ref",
        "skill_id",
        "server_id",
    )
    for key in preview_keys:
        value = arguments.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            if key in {"path", "file_path", "filePath"} and isinstance(tool_id, str) and tool_id.startswith("tool.file."):
                import os as _os

                try:
                    absolute = text if _os.path.isabs(text) else _os.path.abspath(text)
                    relative = _os.path.relpath(absolute, _os.getcwd())
                    display_path = relative if not relative.startswith(f"..{_os.sep}") and relative != ".." else text
                except Exception:
                    LOGGER.warning("failed to render compact path for shell progress trace", exc_info=True)
                    display_path = text
                return compact_line(display_path, limit=56)
            return compact_line(text, limit=36)
    action = str(arguments.get("action") or "").strip().lower()
    if action in {"list", "ls"}:
        return "all"
    return ""

def _sub_agents_trace_preview(arguments) -> str:
    action = _sub_agents_action_label(arguments)
    tasks = arguments.get("tasks")
    if isinstance(tasks, list) and tasks:
        previews = list(_sub_agent_task_previews(tasks, limit=3))
        if previews:
            suffix = f" +{len(tasks) - len(previews)}" if len(tasks) > len(previews) else ""
            return compact_line(f"{action} · " + "; ".join(previews) + suffix, limit=112)
    run_id = str(arguments.get("run_id") or arguments.get("sub_agent_run_id") or "").strip()
    if run_id:
        return compact_line(f"{action} · {run_id}", limit=112)
    name = str(arguments.get("name") or "").strip()
    task = str(arguments.get("task") or arguments.get("prompt") or "").strip()
    if name and task:
        return compact_line(f"{action} · {name}: {task}", limit=112)
    if task:
        return compact_line(f"{action} · {task}", limit=112)
    if name:
        return compact_line(f"{action} · {name}", limit=56)
    return action

def _sub_agents_trace_progress_lines(arguments) -> tuple[str, ...]:
    tasks = arguments.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        return ()
    previews = tuple(_sub_agent_task_previews(tasks, limit=6))
    if not previews:
        return ()
    lines = [f"┊ 🐘 herd         {_sub_agents_action_label(arguments)} · {len(tasks)} agents"]
    lines.extend(f"┊   {index}. {compact_line(preview, limit=104)}" for index, preview in enumerate(previews, start=1))
    if len(tasks) > len(previews):
        lines.append(f"┊   … {len(tasks) - len(previews)} more")
    return tuple(lines)

def _sub_agents_action_label(arguments) -> str:
    action = str(arguments.get("action") or "run").strip().lower()
    aliases = {
        "check": "status",
        "wait": "join",
    }
    return aliases.get(action, action or "run")

def _sub_agent_task_previews(tasks: list, *, limit: int) -> tuple[str, ...]:
    previews: list[str] = []
    for item in tasks[:limit]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        task = str(item.get("task") or item.get("prompt") or "").strip()
        if name and task:
            previews.append(f"{name}: {task}")
        elif task:
            previews.append(task)
        elif name:
            previews.append(name)
    return tuple(previews)

def _tool_trace_prepare_label(tool_event: ToolLifecycleEvent) -> str:
    return _tool_trace_label(tool_event)

def _tool_trace_started_label(tool_event: ToolLifecycleEvent) -> str:
    return _tool_trace_label(tool_event)

def _tool_trace_duration(tool_event: ToolLifecycleEvent) -> str:
    requested_at = tool_event.invocation.requested_at
    if requested_at is None:
        return ""
    delta = max(0.0, (tool_event.occurred_at - requested_at).total_seconds())
    return f"{delta:.1f}s"

def _stream_preview(stream_text: str, *, limit: int = 220) -> str:
    normalized = " ".join(_stream_response_text(stream_text).split())
    if not normalized:
        return ""
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3]}..."

STREAM_REASONING_HEADING = "🐾 Elephant Agent's Trail:"

def _stream_display_parts(stream_text: str, *, streaming: bool = True) -> tuple[str, str]:
    sanitized = _sanitize_stream_tool_markup(stream_text)
    parsed = split_reasoning_and_content(sanitized, streaming=streaming)
    reasoning = strip_markdown_bold(parsed.reasoning.replace("\r\n", "\n").replace("\r", "\n")).lstrip("\n")
    response = strip_markdown_bold(parsed.content.replace("\r\n", "\n").replace("\r", "\n")).lstrip("\n")
    return reasoning, response

def format_reasoning_display_text(reasoning: str, response: str = "") -> str:
    normalized_reasoning = str(reasoning or "").strip()
    normalized_response = str(response or "").strip()
    if normalized_reasoning and normalized_response:
        return f"{STREAM_REASONING_HEADING}\n{normalized_reasoning}\n\n{normalized_response}"
    if normalized_reasoning:
        return f"{STREAM_REASONING_HEADING}\n{normalized_reasoning}"
    return normalized_response

def _compose_stream_markup(reasoning: str, response: str) -> str:
    normalized_reasoning = str(reasoning or "")
    normalized_response = str(response or "")
    if normalized_reasoning and normalized_response:
        return f"<think>{normalized_reasoning}</think>\n{normalized_response}"
    if normalized_reasoning:
        return f"<think>{normalized_reasoning}</think>"
    return normalized_response

def _stream_response_fragments(stream_text: str) -> list[tuple[str, str]]:
    reasoning, response = _stream_display_parts(stream_text, streaming=True)
    fragments: list[tuple[str, str]] = []
    if reasoning:
        fragments.append(("class:stream-reasoning-label", STREAM_REASONING_HEADING))
        fragments.append(("", "\n"))
        fragments.append(("class:stream-reasoning-body", reasoning))
    if response:
        if reasoning:
            fragments.append(("", "\n\n"))
        fragments.extend(_format_stream_response_markdown(response))
    return fragments

def _format_stream_response_markdown(response: str) -> list[tuple[str, str]]:
    fragments: list[tuple[str, str]] = []
    lines = response.split("\n")
    in_code_block = False

    _bold_italic_pat = re.compile(r"\*\*\*(.+?)\*\*\*")
    _bold_pat = re.compile(r"\*\*(.+?)\*\*")
    _italic_pat = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
    _code_pat = re.compile(r"`([^`]+)`")
    _heading_pat = re.compile(r"^(#{1,6})\s+(.+)$")
    _list_pat = re.compile(r"^(\s*)([-*+]|\d+\.)\s+(.*)$")

    for line_index, line in enumerate(lines):
        if line_index > 0:
            fragments.append(("", "\n"))
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            fragments.append(("class:stream-response-code", line))
            continue
        if in_code_block:
            fragments.append(("class:stream-response-code", line))
            continue
        heading_match = _heading_pat.match(line)
        if heading_match:
            level = len(heading_match.group(1))
            style = "class:stream-response-heading" if level <= 2 else "class:stream-response-heading-minor"
            fragments.append((style, heading_match.group(2)))
            continue
        if re.match(r"^[-*_]{3,}\s*$", line):
            fragments.append(("class:stream-response-muted", "─" * 40))
            continue
        list_match = _list_pat.match(line)
        if list_match:
            fragments.append(("class:stream-response-accent", f"{list_match.group(1)}{list_match.group(2)} "))
            _append_inline_stream_fragments(fragments, list_match.group(3), _bold_italic_pat, _bold_pat, _italic_pat, _code_pat)
            continue
        if line.startswith(">"):
            fragments.append(("class:stream-response-muted", "│ "))
            _append_inline_stream_fragments(fragments, line.lstrip("> "), _bold_italic_pat, _bold_pat, _italic_pat, _code_pat)
            continue
        _append_inline_stream_fragments(fragments, line, _bold_italic_pat, _bold_pat, _italic_pat, _code_pat)

    return fragments

def _append_inline_stream_fragments(
    fragments: list[tuple[str, str]],
    text: str,
    bold_italic_pat: re.Pattern[str],
    bold_pat: re.Pattern[str],
    italic_pat: re.Pattern[str],
    code_pat: re.Pattern[str],
) -> None:
    combined = re.compile(
        r"\*\*\*(?P<bi_inner>.+?)\*\*\*"
        r"|\*\*(?P<b_inner>.+?)\*\*"
        r"|(?<!\*)\*(?!\*)(?P<i_inner>.+?)(?<!\*)\*(?!\*)"
        r"|`(?P<c_inner>[^`]+)`"
    )
    pos = 0
    for match in combined.finditer(text):
        start = match.start()
        if start > pos:
            fragments.append(("class:stream-response-body", text[pos:start]))
        if match.group("bi_inner") is not None:
            fragments.append(("class:stream-response-bold-italic", match.group("bi_inner")))
        elif match.group("b_inner") is not None:
            fragments.append(("class:stream-response-bold", match.group("b_inner")))
        elif match.group("i_inner") is not None:
            fragments.append(("class:stream-response-italic", match.group("i_inner")))
        elif match.group("c_inner") is not None:
            fragments.append(("class:stream-response-code", match.group("c_inner")))
        pos = match.end()
    if pos < len(text):
        fragments.append(("class:stream-response-body", text[pos:]))

def _stream_has_reasoning_only(stream_text: str) -> bool:
    reasoning, response = _stream_display_parts(stream_text, streaming=True)
    return bool(reasoning and not response)

def _stream_response_rich_text(stream_text: str) -> Text:
    text = Text()
    style_map = {
        "class:stream-reasoning-label": f"bold {BRAND_ACCENT_STRONG}",
        "class:stream-reasoning-body": BRAND_MUTED,
        "class:stream-response-body": BRAND_LIGHT,
        "class:stream-response-bold": f"bold {BRAND_LIGHT}",
        "class:stream-response-italic": f"italic {BRAND_LIGHT}",
        "class:stream-response-bold-italic": f"bold italic {BRAND_LIGHT}",
        "class:stream-response-code": BRAND_MUTED,
        "class:stream-response-heading": f"bold {BRAND_ACCENT_STRONG}",
        "class:stream-response-heading-minor": f"bold {BRAND_LIGHT}",
        "class:stream-response-accent": BRAND_ACCENT,
        "class:stream-response-muted": BRAND_MUTED,
        "": "",
    }
    for style, fragment in _stream_response_fragments(stream_text):
        text.append(fragment, style=style_map.get(style, BRAND_LIGHT))
    return text

def _stream_response_text(stream_text: str, *, limit: int = 3200) -> str:
    reasoning, response = _stream_display_parts(stream_text, streaming=True)
    normalized = format_reasoning_display_text(reasoning, response)
    if not normalized.strip():
        return ""
    if len(normalized) <= limit:
        return normalized
    tail = normalized[-limit:]
    newline = tail.find("\n")
    if newline >= 0:
        trimmed = tail[newline + 1 :].lstrip("\n")
        if trimmed:
            return f"...\n{trimmed}"
    return f"... {tail.lstrip()}"

def select_stream_response_text(
    stream_text: str,
    *,
    visible_events: tuple[_VisibleToolEvent, ...] = (),
) -> str:
    selected = ""
    for visible_event in visible_events:
        candidate = _stream_response_text(visible_event.stream_text)
        if candidate and len(candidate) > len(selected):
            selected = candidate
    current = _stream_response_text(stream_text)
    if current and len(current) >= len(selected):
        return current
    return selected

def stream_response_delta(stream_text: str, *, previous_stream_text: str = "") -> str:
    current_reasoning, current_response = _stream_display_parts(stream_text, streaming=True)
    if not current_reasoning and not current_response:
        return ""
    previous_reasoning, previous_response = _stream_display_parts(previous_stream_text, streaming=True)
    if current_reasoning == previous_reasoning and current_response == previous_response:
        return ""
    if current_reasoning.startswith(previous_reasoning):
        delta_reasoning = current_reasoning[len(previous_reasoning) :]
    else:
        delta_reasoning = current_reasoning
    if current_response.startswith(previous_response):
        delta_response = current_response[len(previous_response) :]
    else:
        delta_response = current_response
    return _compose_stream_markup(delta_reasoning.lstrip("\n"), delta_response.lstrip("\n"))

def _sanitize_stream_tool_markup(raw: str) -> str:
    cleaned = raw
    for pattern in _STREAM_TOOL_BLOCK_PATTERNS:
        previous = None
        while previous != cleaned:
            previous = cleaned
            cleaned = pattern.sub("", cleaned)
    open_match = _STREAM_OPEN_TOOL_TAG_PATTERN.search(cleaned)
    if open_match is not None:
        cleaned = cleaned[: open_match.start()]
    cleaned = _STREAM_TOOL_TAG_PATTERN.sub("", cleaned)
    partial_start = _partial_tool_tag_start(cleaned)
    if partial_start is not None:
        cleaned = cleaned[:partial_start]
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned

def _partial_tool_tag_start(text: str) -> int | None:
    marker = text.rfind("<")
    if marker < 0:
        return None
    fragment = text[marker + 1 :].strip().lower()
    if ">" in fragment or not fragment:
        return marker if fragment == "" else None
    closing = fragment.startswith("/")
    if closing:
        fragment = fragment[1:]
    if ":" in fragment:
        fragment = fragment.split(":", 1)[1]
    fragment = fragment.strip()
    tool_tags = ("tool_call", "invoke", "parameter")
    if not fragment:
        return marker
    if any(name.startswith(fragment) for name in tool_tags):
        return marker
    return None
