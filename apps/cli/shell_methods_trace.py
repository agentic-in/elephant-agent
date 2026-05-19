"""Bound methods extracted from apps/cli/shell.py."""

from __future__ import annotations

from difflib import unified_diff
from pathlib import Path
import re
import time

from packages.contracts import ExperienceRecord
from packages.kernel.runtime import KernelOutcome
from packages.tools.handler_support import resolve_allowed_path
from .shell_progress import (
    animations_enabled as _shell_animations_enabled,
    render_queued_followup_fragments as _render_shell_queued_followup_fragments,
    render_tool_frame as _render_shell_tool_frame,
    tool_trace_line as _shell_tool_trace_line,
    render_turn_frame as _render_shell_turn_frame,
    render_turn_progress_fragments as _render_shell_turn_progress_fragments,
    run_tool_with_progress as _run_shell_tool_with_progress,
    run_turn_with_progress as _run_shell_turn_with_progress,
    run_turn_with_queued_input as _run_shell_turn_with_queued_input,
    summarize_progress_prompt as _summarize_shell_progress_prompt,
    tool_event_lines as _shell_tool_event_lines,
    tool_event_summary as _shell_tool_event_summary,
    tool_event_tracker as _shell_tool_event_tracker,
    tool_frame_phases as _shell_tool_frame_phases,
    turn_phase as _shell_turn_phase,
    _tool_trace_emoji as _shell_tool_trace_emoji,
)
from .shell_render import (
    center_brand_block as _center_shell_brand_block,
    displayable_experiences as _displayable_shell_experiences,
    format_experience_status as _format_shell_experience_status,
    growth_panel_lines as _shell_growth_panel_lines,
    growth_progress_bar as _shell_growth_progress_bar,
    growth_progress_counts as _shell_growth_progress_counts,
    recent_activity_lines as _shell_recent_activity_lines,
    recent_experience_lines as _shell_recent_experience_lines,
    render_chat_entry as _render_shell_chat_entry,
    render_entry as _render_shell_entry,
    render_elephant_brand_mark as _render_shell_elephant_mark,
    render_growth_mark_for_stage as _render_shell_growth_mark,
    render_pending_entries as _render_shell_pending_entries,
    should_display_experience as _should_display_shell_experience,
    styled_growth_progress_bar as _styled_shell_growth_progress_bar,
)
from .shell_stack import (
    Console,
    Document,
    FormattedText,
    RICH_AVAILABLE,
)
from .shell_ui import (
    BRAND_ACCENT,
    BRAND_ACCENT_STRONG,
    BRAND_DARK,
    BRAND_LIGHT,
    BRAND_MUTED,
    COMMAND_PALETTE_VISIBLE_ROWS,
    ELEPHANT_STAGE_ROWS,
    GROWTH_HIGHLIGHT_FG,
    GROWTH_PROGRESS_EMPTY,
    GROWTH_PROGRESS_FILLED,
    GROWTH_PROGRESS_WIDTH,
    HATCHLING_HEAD_ROWS,
    HATCHLING_STAGE_ROWS,
    QUEUE_PREVIEW_INSET,
    SCOUT_STAGE_ROWS,
    SEED_STAGE_ROWS,
    SHELL_WELCOME_HEADLINE,
    USER_HISTORY_BG,
    USER_HISTORY_FG,
    compact_line as _compact_line,
    centered_elephant_rows as _centered_elephant_rows,
    display_width as _display_width,
    render_elephant_mark,
)

__all__ = [
    "BRAND_ACCENT",
    "BRAND_ACCENT_STRONG",
    "BRAND_DARK",
    "BRAND_LIGHT",
    "BRAND_MUTED",
    "COMMAND_PALETTE_VISIBLE_ROWS",
    "Console",
    "Document",
    "ELEPHANT_STAGE_ROWS",
    "GROWTH_HIGHLIGHT_FG",
    "GROWTH_PROGRESS_EMPTY",
    "GROWTH_PROGRESS_FILLED",
    "GROWTH_PROGRESS_WIDTH",
    "HATCHLING_HEAD_ROWS",
    "HATCHLING_STAGE_ROWS",
    "HATCHLING_STAGE_ROWS",
    "PendingShellCommand",
    "ProductizedShell",
    "QUEUE_PREVIEW_INSET",
    "RICH_AVAILABLE",
    "SCOUT_STAGE_ROWS",
    "SEED_STAGE_ROWS",
    "SHELL_WELCOME_HEADLINE",
    "ShellCompleter",
    "TranscriptEntry",
    "USER_HISTORY_BG",
    "USER_HISTORY_FG",
    "_centered_elephant_rows",
    "_display_width",
    "render_elephant_mark",
]


from .shell_support_runtime import *  # noqa: F401,F403


def _identity_lines(self, profile_id: str) -> list[str]:
    profile = self.runtime.inspect_profile(profile_id)
    identity = self.runtime.inspect_identity(profile_id=profile_id)
    user = self.runtime.inspect_user(profile_id=profile_id)
    relationship = self.runtime.inspect_relationship(profile_id=profile_id)
    lines = [
        f"profile_id: {profile.state.profile_id}",
        f"display_name: {identity.display_name}",
        f"mode: {profile.state.mode}",
        f"elephant_id: {identity.elephant_id}",
        f"identity_mode: {identity.identity_mode}",
        f"personality_preset: {identity.personality_preset}",
        f"initiative: {identity.initiative}",
        f"relational_stance: {identity.relational_stance}",
        f"elephant_identity_text: {identity.elephant_identity_text or '<empty>'}",
        f"user_preferred_name: {user.preferred_name or '<empty>'}",
        f"relationship_notes: {', '.join(relationship.continuity_notes) or '<empty>'}",
    ]
    full_contract = self.runtime.prompt_contract(profile_id=profile_id, prompt_mode="full")
    minimal_contract = self.runtime.prompt_contract(profile_id=profile_id, prompt_mode="minimal")
    lines.extend(
        [
            f"prompt_contract_full: {', '.join(full_contract.section_names)}",
            f"prompt_contract_minimal: {', '.join(minimal_contract.section_names)}",
        ]
    )
    return lines


def _user_lines(self, profile_id: str) -> list[str]:
    user = self.runtime.inspect_user(profile_id=profile_id)
    return [
        f"profile_id: {user.profile_id}",
        f"user_profile_id: {user.user_profile_id}",
        f"preferred_name: {user.preferred_name or '<empty>'}",
        f"locale: {user.locale or '<empty>'}",
        f"timezone: {user.timezone or '<empty>'}",
        f"communication_preferences: {', '.join(user.communication_preferences) or '<empty>'}",
        f"boundaries: {', '.join(user.boundaries) or '<empty>'}",
        f"biography_fragments: {', '.join(user.biography_fragments) or '<empty>'}",
        f"shared_preferences: {', '.join(user.shared_preferences) or '<empty>'}",
    ]


def _relationship_lines(self, profile_id: str) -> list[str]:
    relationship = self.runtime.inspect_relationship(profile_id=profile_id)
    return [
        f"profile_id: {relationship.profile_id}",
        f"relationship_id: {relationship.relationship_id}",
        f"elephant_id: {relationship.elephant_id}",
        f"user_profile_id: {relationship.user_profile_id or '<empty>'}",
        f"interaction_preferences: {', '.join(relationship.interaction_preferences) or '<empty>'}",
        f"expectations: {', '.join(relationship.expectations) or '<empty>'}",
        f"continuity_notes: {', '.join(relationship.continuity_notes) or '<empty>'}",
    ]


def _append_entry(self, kind: str, title: str, body: str, *, meta: str = "") -> None:
    self.transcript.append(TranscriptEntry(kind=kind, title=title, body=body, meta=meta))
    if len(self.transcript) > 80:
        overflow = len(self.transcript) - 80
        self.transcript = self.transcript[overflow:]
        self._rendered_entries = max(0, self._rendered_entries - overflow)


def _append_tooltrace_line(self, line: str) -> None:
    if self.transcript and self.transcript[-1].kind == "tooltrace":
        previous = self.transcript[-1]
        combined = previous.body.rstrip("\n")
        combined = f"{combined}\n{line}" if combined else line
        self.transcript[-1] = TranscriptEntry(
            kind=previous.kind,
            title=previous.title,
            body=combined,
            meta=previous.meta,
        )
        return
    self._append_entry("tooltrace", "Tool trace", line)


def _capture_pending_file_review(self, tool_event: ToolLifecycleEvent) -> None:
    if tool_event.phase != "requested":
        return
    if tool_event.invocation.tool_id not in {"tool.file.write", "tool.file.patch"}:
        return
    raw_path = str(tool_event.invocation.arguments.get("path") or "").strip()
    if not raw_path:
        return
    try:
        path = resolve_allowed_path(Path.cwd(), raw_path, must_exist=False)
    except Exception:
        return
    before_text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else None
    self._pending_file_reviews[tool_event.invocation.invocation_id] = _PendingFileReview(
        path=path,
        before_text=before_text,
    )


def _todo_trace_lines(self) -> tuple[str, ...]:
    todo_glyph = _shell_tool_trace_emoji("tool.todo.manage")
    items = self.runtime.todo_store.list_items(self.session_id)
    if not items:
        return (f"┊ {todo_glyph} todo items   <empty>",)
    lines = [f"┊ {todo_glyph} todo items   {len(items)} item(s)"]
    visible_items = items[:6]
    for index, item in enumerate(visible_items, start=1):
        work_item_part = f" | work_item={item.work_item_id}" if item.work_item_id else ""
        detail = _compact_line(f"{item.status} | {item.title}{work_item_part}", limit=108)
        lines.append(f"┊ {todo_glyph} {f'item {index}':<12} {detail}")
    if len(items) > len(visible_items):
        remaining = len(items) - len(visible_items)
        lines.append(f"┊ {todo_glyph} more        {remaining} additional item(s)")
    return tuple(lines)


def _display_tool_diff_path(self, path: Path) -> str:
    resolved = path.expanduser().resolve()
    try:
        return str(resolved.relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(resolved)


def _file_review_trace_lines(self, tool_event: ToolLifecycleEvent) -> tuple[str, ...]:
    snapshot = self._pending_file_reviews.pop(tool_event.invocation.invocation_id, None)
    if snapshot is None:
        return ()
    after_text = snapshot.path.read_text(encoding="utf-8", errors="replace") if snapshot.path.exists() else None
    if snapshot.before_text == after_text:
        return ()
    display_path = self._display_tool_diff_path(snapshot.path)
    diff_lines = list(
        unified_diff(
            [] if snapshot.before_text is None else snapshot.before_text.splitlines(),
            [] if after_text is None else after_text.splitlines(),
            fromfile=f"a/{display_path}",
            tofile=f"b/{display_path}",
            lineterm="",
        )
    )
    if not diff_lines:
        return ()
    review_glyph = _shell_tool_trace_emoji(tool_event.invocation.tool_id)
    rendered: list[str] = [f"┊ {review_glyph} diff"]
    from_file: str | None = None
    for raw_line in diff_lines:
        if raw_line.startswith("--- "):
            from_file = raw_line[4:].strip()
            continue
        if raw_line.startswith("+++ "):
            to_file = raw_line[4:].strip()
            rendered.append(f"{from_file or 'a/?'} → {to_file or 'b/?'}")
            continue
        rendered.append(raw_line)
    max_lines = 80
    overflow = len(rendered) - max_lines
    if overflow > 0:
        rendered = rendered[:max_lines]
        rendered.append(f"… omitted {overflow} diff line(s)")
    return tuple(rendered)


def _tool_result_trace_lines(self, tool_event: ToolLifecycleEvent) -> tuple[str, ...]:
    if tool_event.phase == "execution.failed":
        self._pending_file_reviews.pop(tool_event.invocation.invocation_id, None)
        return ()
    if tool_event.phase != "execution.completed":
        return ()
    if tool_event.invocation.tool_id == "tool.todo.manage":
        return self._todo_trace_lines()
    if tool_event.invocation.tool_id in {"tool.file.write", "tool.file.patch"}:
        return self._file_review_trace_lines(tool_event)
    return ()


def _boot_growth_stage(self, active: int) -> tuple[str, int]:
    if active < 0:
        return ("seed", 0)
    stages = (
        ("seed", 1),
        ("elephant", 2),
        ("scout", 3),
        ("elephant", 4),
    )
    return stages[min(active, len(stages) - 1)]


def _record_tool_event_trace(self, tool_event: ToolLifecycleEvent) -> None:
    self._capture_pending_file_review(tool_event)
    # Per-turn tally for the end-of-turn condense line. Only final phases
    # count toward the summary (requests/starts are noise here).
    if tool_event.phase in {"execution.completed", "execution.failed"}:
        events = getattr(self, "_turn_tool_events", None)
        if events is not None:
            tool_id = str(tool_event.invocation.tool_id or "").strip()
            succeeded = tool_event.phase == "execution.completed"
            events.append((tool_id, succeeded, int(time.time_ns())))
    line = self._tool_trace_line(tool_event)
    if line is not None:
        self._append_tooltrace_line(line)
    for extra_line in self._tool_result_trace_lines(tool_event):
        self._append_tooltrace_line(extra_line)


def _kernel_stage_payload(event: dict[str, object]) -> dict[str, object] | None:
    event_type = str(event.get("event_type") or "").strip().lower()
    if event_type != "kernel.stage":
        return None
    payload = event.get("payload")
    return payload if isinstance(payload, dict) else None


def _parse_context_compaction_tokens(detail: str) -> tuple[int, int] | None:
    match = re.search(r"(?:^|\s)tokens=(\d+)->(\d+)(?:\s|$)", str(detail or ""))
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def _parse_kernel_stage_int(detail: str, key: str) -> int | None:
    match = re.search(rf"(?:^|\s){re.escape(key)}=(\d+)(?:\s|$)", str(detail or ""))
    return int(match.group(1)) if match is not None else None


def _kernel_trace_line(self, event: dict[str, object]) -> str | None:
    event_type = str(event.get("event_type") or "").strip().lower()
    stage_payload = _kernel_stage_payload(event)
    if stage_payload is not None:
        stage_name = str(stage_payload.get("stage") or "").strip()
        if stage_name == "context-compact":
            detail = str(stage_payload.get("detail") or "").strip()
            token_pair = _parse_context_compaction_tokens(detail)
            reason_match = re.search(r"(?:^|\s)reason=([^\s]+)", detail)
            reason = reason_match.group(1) if reason_match is not None else "preflight"
            status_match = re.search(r"(?:^|\s)status=([^\s]+)", detail)
            status = status_match.group(1) if status_match is not None else None
            if status == "compressing":
                messages_match = re.search(r"(?:^|\s)messages=(\d+)", detail)
                tail_match = re.search(r"(?:^|\s)tail=(\d+)", detail)
                msg_count = messages_match.group(1) if messages_match else "?"
                tail_count = tail_match.group(1) if tail_match else "?"
                body = f"compressing · {msg_count} messages → {tail_count} tail"
                return f"┊ 🧩 context      {_compact_line(body, limit=140)}"
            body = reason
            if token_pair is not None:
                before_tokens, after_tokens = token_pair
                action = "projection rewrite" if after_tokens >= before_tokens else "projection compact"
                body = f"{action} · est {before_tokens}->{after_tokens} tokens · {reason}"
            return f"┊ 🧩 context      {_compact_line(body, limit=140)}"
        if stage_name == "recall":
            return None
    if event_type != "skill.disclosed":
        return None
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return None
    skill_id = str(payload.get("skill_id") or "").strip()
    display_name = str(payload.get("display_name") or "").strip()
    disclosure_kind = str(payload.get("disclosure_kind") or "").strip()
    skill_label = display_name or skill_id or "skill"
    if skill_id and skill_id != skill_label:
        skill_label = f"{skill_label} ({skill_id})"
    body_parts = [skill_label]
    if disclosure_kind:
        body_parts.append(disclosure_kind)
    body = _compact_line(" · ".join(part for part in body_parts if part), limit=96)
    return f"┊ 📚 disclosed    {body}"


def _record_kernel_event_trace(self, event: dict[str, object]) -> None:
    stage_payload = _kernel_stage_payload(event)
    if stage_payload is not None:
        stage = str(stage_payload.get("stage") or "").strip()
        detail = str(stage_payload.get("detail") or "")
        if stage == "context-compact":
            token_pair = _parse_context_compaction_tokens(detail)
            if token_pair is not None:
                object.__setattr__(self, "_last_prompt_tokens", token_pair[1])
                object.__setattr__(self, "_last_provider_prompt_tokens", 0)
        elif stage == "context-projection":
            prompt_tokens = _parse_kernel_stage_int(detail, "prompt_tokens")
            if prompt_tokens is not None:
                object.__setattr__(self, "_last_prompt_tokens", prompt_tokens)
                object.__setattr__(self, "_last_provider_prompt_tokens", 0)
        elif stage == "context-usage":
            prompt_tokens = _parse_kernel_stage_int(detail, "prompt_tokens")
            total_tokens = _parse_kernel_stage_int(detail, "total_tokens")
            usage_tokens = prompt_tokens if prompt_tokens is not None else total_tokens
            if usage_tokens is not None:
                object.__setattr__(self, "_last_provider_prompt_tokens", usage_tokens)
    line = self._kernel_trace_line(event)
    if line is not None:
        self._append_tooltrace_line(line)


def _animations_enabled(self) -> bool:
    return _shell_animations_enabled()


def _turn_phase(self, tick: int) -> tuple[str, str, str]:
    return _shell_turn_phase(tick)


def _summarize_progress_prompt(self, prompt: str) -> str:
    return _summarize_shell_progress_prompt(prompt)


def _render_turn_progress_fragments(
    self,
    *,
    prompt: str,
    tick: int,
    tool_event: ToolLifecycleEvent | None = None,
    tool_events: tuple[ToolLifecycleEvent, ...] = (),
    kernel_stage_events: tuple[dict[str, object], ...] = (),
    queued_count: int = 0,
    stream_text: str = "",
) -> FormattedText:
    return _render_shell_turn_progress_fragments(
        self,
        prompt=prompt,
        tick=tick,
        tool_event=tool_event,
        tool_events=tool_events,
        kernel_stage_events=kernel_stage_events,
        queued_count=queued_count,
        stream_text=stream_text,
    )


def _render_queued_followup_fragments(self) -> FormattedText:
    return _render_shell_queued_followup_fragments(self)


def _run_turn_with_queued_input(self, prompt: str) -> KernelOutcome:
    return _run_shell_turn_with_queued_input(self, prompt)


def _run_turn_with_progress(
    self,
    prompt: str,
    *,
    event_payload: dict[str, str] | None = None,
) -> KernelOutcome:
    return _run_shell_turn_with_progress(self, prompt, event_payload=event_payload)


def _run_tool_with_progress(self, tool_id: str, arguments: dict[str, str]):
    return _run_shell_tool_with_progress(self, tool_id, arguments)


def _tool_event_tracker(self):
    return _shell_tool_event_tracker()


def _render_turn_frame(
    self,
    *,
    prompt: str,
    tick: int,
    tool_event: ToolLifecycleEvent | None = None,
    tool_events: tuple[ToolLifecycleEvent, ...] = (),
    kernel_stage_events: tuple[dict[str, object], ...] = (),
    stream_text: str = "",
):
    return _render_shell_turn_frame(
        self,
        prompt=prompt,
        tick=tick,
        tool_event=tool_event,
        tool_events=tool_events,
        kernel_stage_events=kernel_stage_events,
        stream_text=stream_text,
    )


def _render_tool_frame(self, *, tool_id: str, tick: int, tool_event: ToolLifecycleEvent | None = None):
    return _render_shell_tool_frame(self, tool_id=tool_id, tick=tick, tool_event=tool_event)


def _tool_frame_phases(
    self, tool_id: str, *, tool_event: ToolLifecycleEvent | None = None
) -> tuple[tuple[str, str], ...]:
    return _shell_tool_frame_phases(self, tool_id, tool_event=tool_event)


def _tool_event_lines(self, tool_event: ToolLifecycleEvent | None) -> tuple[str | None, str | None]:
    return _shell_tool_event_lines(self, tool_event)


def _tool_event_summary(self, tool_event: ToolLifecycleEvent | None) -> str | None:
    return _shell_tool_event_summary(self, tool_event)


def _tool_trace_line(self, tool_event: ToolLifecycleEvent | None) -> str | None:
    return _shell_tool_trace_line(self, tool_event)


def _render_pending_entries(self) -> None:
    _render_shell_pending_entries(self)


def _render_entry(self, entry: TranscriptEntry):
    return _render_shell_entry(self, entry)


def _growth_panel_lines(self, session, continuity, provider, growth) -> tuple[str, ...]:
    return _shell_growth_panel_lines(self, session, continuity, provider, growth)


def _recent_activity_lines(self, session, continuity, provider) -> tuple[str, ...]:
    return _shell_recent_activity_lines(self, session, continuity, provider)


def _recent_experience_lines(self, experiences: tuple[ExperienceRecord, ...]) -> tuple[str, ...]:
    return _shell_recent_experience_lines(experiences)


def _displayable_experiences(self, experiences: tuple[ExperienceRecord, ...]) -> tuple[ExperienceRecord, ...]:
    return _displayable_shell_experiences(experiences)


def _should_display_experience(self, experience: ExperienceRecord) -> bool:
    return _should_display_shell_experience(experience)


def _format_experience_status(self, experience: ExperienceRecord) -> str:
    return _format_shell_experience_status(experience)


def _growth_progress_counts(self, growth, *, width: int = GROWTH_PROGRESS_WIDTH) -> tuple[int, int]:
    return _shell_growth_progress_counts(growth, width=width)


def _growth_progress_bar(self, growth, *, width: int = GROWTH_PROGRESS_WIDTH) -> str:
    return _shell_growth_progress_bar(growth, width=width)


def _styled_growth_progress_bar(self, growth, *, width: int = GROWTH_PROGRESS_WIDTH):
    return _styled_shell_growth_progress_bar(growth, width=width)


def _render_chat_entry(self, entry: TranscriptEntry, *, accent: str):
    return _render_shell_chat_entry(self, entry, accent=accent)


def _history_row_width(self) -> int:
    return max(24, len(self._composer_divider()))


def _queue_preview_row_width(self) -> int:
    return max(16, self._history_row_width() - (QUEUE_PREVIEW_INSET * 2))


def _pad_history_line(self, content: str) -> str:
    display_width = _display_width(content)
    width = self._history_row_width()
    if display_width >= width:
        return content
    return content + (" " * (width - display_width))


def _pad_queue_preview_line(self, content: str) -> str:
    display_width = _display_width(content)
    width = self._queue_preview_row_width()
    if display_width >= width:
        return content
    return content + (" " * (width - display_width))


def _center_brand_block(self, renderable):
    return _center_shell_brand_block(renderable)


def _render_growth_mark(self, stage_id: str, *, level: int | None = None):
    return _render_shell_growth_mark(stage_id, level=level)


def _render_elephant_mark(self):
    return _render_shell_elephant_mark()
