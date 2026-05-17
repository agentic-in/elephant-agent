"""Bound methods extracted from apps/cli/shell.py."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from difflib import unified_diff
import os
from pathlib import Path
import re
import shlex
import threading
import time

from packages.contracts import ExperienceRecord
from packages.kernel.runtime import KernelOutcome
from packages.operator.runtime import (
    RecallEvidenceOperatorDetail,
    RecallEvidenceSearchHit,
    build_recall_evidence_operator_surface,
    build_profile_operator_surface,
    render_recall_evidence_lines,
    render_profile_lines,
)
from packages.tools.handler_support import resolve_allowed_path
from .provider_flow import provider_setup_defaults, run_provider_selection_wizard
from .runtime import CliRuntime
from .wizard import WIZARD_BACK
from .shell_composer import (
    build_command_palette as _build_shell_command_palette,
    build_composer_body as _build_shell_composer_body,
    build_divider_window as _build_shell_divider_window,
    build_input_window as _build_shell_input_window,
    build_key_bindings as _build_shell_key_bindings,
    build_prompt_buffer as _build_shell_prompt_buffer,
    build_queue_preview_window as _build_shell_queue_preview_window,
    prompt_continuation as _shell_prompt_continuation,
    prompt_label as _shell_prompt_label,
    prompt_style as _shell_prompt_style,
    prompt_style_map as _shell_prompt_style_map,
    prompt_toolkit_composer_available as _shell_prompt_toolkit_composer_available,
    read_command as _read_shell_command,
    shell_history as _shell_history,
)
from .shell_boot import WAKE_DISPLAY_SECONDS, BootFrameContext, render_boot_frame
from .shell_opening import (
    ShellOpeningContext,
    compose_shell_opening_instruction,
    compose_shell_opener,
)
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
    render_brand_column as _render_shell_brand_column,
    render_chat_entry as _render_shell_chat_entry,
    render_entry as _render_shell_entry,
    render_elephant_brand_mark as _render_shell_elephant_mark,
    render_growth_mark_for_stage as _render_shell_growth_mark,
    render_pending_entries as _render_shell_pending_entries,
    render_shell_frame as _render_shell_frame_view,
    render_status_column as _render_shell_status_column,
    should_display_experience as _should_display_shell_experience,
    styled_growth_progress_bar as _styled_shell_growth_progress_bar,
)
from .shell_stack import (
    Align,
    Completion,
    Completer,
    Console,
    Document,
    FormattedText,
    Group,
    Live,
    PROMPT_TOOLKIT_AVAILABLE,
    Panel,
    RICH_AVAILABLE,
    Table,
    Text,
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
    HATCHLING_STAGE_ROWS,
    QUEUE_PREVIEW_INSET,
    SCOUT_STAGE_ROWS,
    SEED_STAGE_ROWS,
    SHELL_WELCOME_HEADLINE,
    USER_HISTORY_BG,
    USER_HISTORY_FG,
    WEB_URL_PATTERN,
    compact_line as _compact_line,
    centered_elephant_rows as _centered_elephant_rows,
    display_path as _display_path,
    display_width as _display_width,
    render_elephant_mark,
    resolve_elephant_version as _resolve_elephant_version,
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

def _safe_usage_token_count(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0

def _execution_prompt_usage_tokens(execution: object) -> int:
    prompt_tokens = _safe_usage_token_count(getattr(execution, "prompt_tokens", 0))
    total_tokens = _safe_usage_token_count(getattr(execution, "total_tokens", 0))
    return prompt_tokens or total_tokens

def _outcome_has_context_compaction(outcome: KernelOutcome) -> bool:
    stages = getattr(outcome, "stages", ())
    if not isinstance(stages, tuple | list):
        return False
    return any(
        str(getattr(stage, "stage", "") or "") == "context-compact"
        for stage in stages
    )

def _outcome_context_compaction_after_tokens(outcome: KernelOutcome) -> int | None:
    stages = getattr(outcome, "stages", ())
    if not isinstance(stages, tuple | list):
        return None
    for stage in reversed(stages):
        if str(getattr(stage, "stage", "") or "") != "context-compact":
            continue
        detail = str(getattr(stage, "detail", "") or "")
        match = re.search(r"(?:^|\s)tokens=\d+->(\d+)(?:\s|$)", detail)
        if match is not None:
            return int(match.group(1))
    return None

def _dispatch(self, raw_command: str | PendingShellCommand) -> bool:
    pending = coerce_pending_shell_command(raw_command)
    command = pending.command.strip()
    if not command:
        return False
    display_command = pending.display_command.strip() or command
    if self._pending_context_compaction_frame is not None:
        self._pending_context_compaction_frame = None
        self._pending_context_compaction_frame_rendered = False
    if command.startswith("/"):
        self._clear_composer(command)
        self._composer_paste_items.clear()
        return self._handle_slash_command(command)
    self._clear_composer(display_command)
    self._append_entry("user", "You", display_command)
    self._render_pending_entries()
    if self._handle_conversational_surface_request(command):
        self._refresh_shell_frame_if_needed()
        return False
    try:
        if self.debug:
            debug_session = self.runtime.inspect_session(self.session_id)
            debug_provider = dict(self.runtime.provider_summary())
            self._append_entry(
                "status",
                "Runtime",
                "\n".join(
                    [
                        f"session_id: {self.session_id}",
                        f"elephant · {self.runtime.elephant_id_for_session(debug_session)}",
                        f"model {debug_provider.get('model_id') or debug_provider.get('default_model') or '<unset>'}",
                        "mode: shared-runtime",
                        "trace: debug diagnostics enabled",
                    ]
                ),
            )
            self._render_pending_entries()
        event_payload = dict(pending.event_payload)
        skill_route = self._resolved_skill_route(command)
        if skill_route is not None:
            spec, route_mode = skill_route
            event_payload.update(
                {
                    "skill_route": spec.skill_id,
                    "skill_route_mode": route_mode,
                }
            )
        outcome = self._run_turn_with_progress(command, event_payload=event_payload or None)
    except Exception as error:  # pragma: no cover - defensive shell surface
        self._append_entry(
            "recovery",
            "Turn failed",
            f"{error}\nstatus: /status",
        )
        return False
    context_prompt_tokens = self._last_prompt_tokens
    self._append_outcome(outcome)
    # Render the assistant response immediately so it appears in scrollback
    # without a visible gap after the turn Application's erase_when_done fires.
    self._render_pending_entries()
    prompt_usage_tokens = _execution_prompt_usage_tokens(outcome.execution)
    if _outcome_has_context_compaction(outcome):
        self._last_provider_prompt_tokens = 0
        self._last_prompt_tokens = _outcome_context_compaction_after_tokens(outcome) or context_prompt_tokens
    else:
        self._last_provider_prompt_tokens = prompt_usage_tokens
        self._last_prompt_tokens = context_prompt_tokens
    # Growth celebration and learning result checks involve DB I/O.
    # Schedule them to run in a background thread so the composer input
    # box reappears immediately — the results are appended to the
    # transcript and rendered on the next loop iteration.
    self._schedule_post_turn_background()
    return False

def _schedule_post_turn_background(self) -> None:
    """Run growth celebration and learning-result checks off the main thread.

    These involve DB lookups that can block 100-500 ms. Running them in a
    background thread lets the composer start immediately so the user sees
    the input box without delay. The prompt_toolkit composer's refresh_interval
    (0.33 s) will pick up any new transcript entries on its next tick.
    """

    def _post_turn_work() -> None:
        try:
            growth_update = self._show_growth_celebration_if_needed()
            self._append_growth_update_message(growth_update)
        except Exception:
            pass
        try:
            self._append_latest_learning_result()
        except Exception:
            pass

    threading.Thread(
        target=_post_turn_work,
        name="elephant-post-turn",
        daemon=True,
    ).start()

def _handle_conversational_surface_request(self, message: str) -> bool:
    normalized = message.strip().lower().rstrip("?.!")
    if normalized in {
        "what tools do you have",
        "which tools do you have",
        "show tools",
        "list tools",
    }:
        tools = tuple(
            tool
            for tool in self.runtime.tool_catalog(session_id=self.session_id, audience="model")
            if tool.enabled and tool.available
        )
        lines = [
            "I can use these tools right now:",
            *[
                f"- {tool.display_name} ({tool.tool_id}): {tool.description}"
                for tool in tools
            ],
            "",
            "Ask me naturally if you want one used, or give me a manifest path if you want me to install an external tool.",
        ]
        self._append_assistant_surface_reply("\n".join(lines))
        return True
    if normalized in {
        "what cron jobs do you have",
        "which cron jobs do you have",
        "show cron jobs",
        "list cron jobs",
        "show schedules",
        "list schedules",
    }:
        jobs = self.runtime.cron_jobs(session_id=self.session_id)
        if jobs:
            body = "\n".join(
                [
                    "These scheduled jobs are active for this elephant:",
                    *[
                        f"- {job.name} ({job.job_id}) · {job.status} · {job.schedule_text} · {job.action_kind}"
                        for job in jobs
                    ],
                ]
            )
        else:
            body = "I don't have any scheduled jobs running for this elephant yet."
        self._append_assistant_surface_reply(body)
        return True
    tool_match = re.match(r"(?i)^(install|add|load)\s+tools?\s+(.+)$", message.strip())
    if tool_match is not None:
        reference = self._strip_wrapping_quotes(tool_match.group(2).strip())
        try:
            record = self.runtime.install_tool_manifest(reference, session_id=self.session_id)
        except Exception as error:
            self._append_assistant_surface_reply(
                "I couldn't install that tool manifest yet.\n"
                f"reason: {error}\n"
                "Right now external tools install from a local manifest path.",
            )
            return True
        self._append_assistant_surface_reply(
            "\n".join(
                [
                    "I installed that tool manifest for this elephant.",
                    f"- source: {record.source_path}",
                    f"- tools: {', '.join(record.tool_ids) or '<empty>'}",
                    f"- executable: {', '.join(record.executable_tool_ids) or '<empty>'}",
                ]
            )
        )
        return True
    cron_prompt = re.match(
        r"(?is)^(?:schedule|create|set up)\s+(?:a\s+)?(?:prompt|task|cron(?:\s+job)?)(?:\s+(?:to|for))?\s+(.+?)\s+(every .+|daily at .+|\d+[mhd])$",
        message.strip(),
    )
    if cron_prompt is not None:
        prompt = self._strip_wrapping_quotes(cron_prompt.group(1).strip())
        schedule = cron_prompt.group(2).strip()
        try:
            job = self.runtime.create_cron_job(
                session_id=self.session_id,
                name=f"Prompt · {prompt[:32]}",
                schedule=schedule,
                payload={"prompt": prompt},
            )
        except Exception as error:
            self._append_assistant_surface_reply(f"I couldn't create that scheduled prompt task yet.\nreason: {error}")
            return True
        self._append_assistant_surface_reply(
            f"I scheduled that prompt task for this elephant.\n- {job.name} · {job.schedule_text} · {job.action_kind}"
        )
        return True
    webpage_url = self._requested_webpage_url(message)
    if webpage_url is not None:
        try:
            result = self._run_tool_with_progress("tool.web.read", {"url": webpage_url})
        except Exception as error:
            self._append_assistant_surface_reply(
                f"I couldn't fetch that web page yet.\nreason: {error}",
                meta=webpage_url,
            )
            return True
        self._append_assistant_surface_reply(
            f"I opened that page and pulled the readable content:\n{result.summary}",
            meta=webpage_url,
        )
        return True
    return False

def _handle_slash_command(self, raw_command: str) -> bool:
    try:
        parts = self._parse_slash_command(raw_command)
    except ValueError as error:
        self._append_entry("recovery", "Command parse error", str(error))
        return False
    command = parts[0]
    args = parts[1:]

    if command == "/exit":
        elephant_id = self.runtime.elephant_id_for_session(self.runtime.inspect_session(self.session_id))
        learning_detail = "background learning queued"
        try:
            from packages.kernel.episode_state_machine import close_episode

            close_episode(
                self.runtime.repository,
                self.session_id,
                reason="shell_exit",
                summary="wake surface exited by user",
                semantic_summary_indexer=getattr(self.runtime, "_semantic_summary_indexer", None),
            )
            self.runtime._ensure_learning_worker_if_needed()
            learning_detail = "episode closed · learning queued"
        except Exception:
            pass
        self._append_entry(
            "notice",
            "Wake surface",
            f"🐾 Elephant Agent is closing elephant {elephant_id} for now.\n🌱 {learning_detail}.",
        )
        return True
    if command == "/help":
        self._append_help()
        return False
    if command == "/status":
        self._append_status()
        return False
    if command == "/recall":
        self._append_recall(args)
        return False
    if command == "/tools":
        self._append_tools(args)
        return False
    if command == "/skills":
        self._append_skills(args)
        return False
    if command == "/learn":
        self._append_learn(args)
        return False
    if command == "/gateway":
        self._append_gateway(args)
        return False
    if command == "/cron":
        self._append_cron(args)
        return False
    if command == "/providers":
        self._append_providers(args)
        return False
    if command == "/models":
        self._append_models(args)
        return False
    if command == "/expand":
        self._append_expand(args)
        return False
    if command == "/clear":
        previous_session_id = self.session_id
        learning_detail = "episode closed · learning queued"
        # Close the previous episode explicitly so the dashboard / history
        # shows a clean break, then start a fresh Episode on the same elephant.
        previous_episode = self.runtime.inspect_session(previous_session_id)
        fresh_session = self.runtime.open_next_episode(
            previous_session_id,
            reason="shell_clear",
            summary=(previous_episode.exit_summary or "").strip() or "/clear requested a fresh Episode",
        ).episode
        self.session_id = fresh_session.episode_id
        self.opened = f"Reopened elephant {self.runtime.elephant_id_for_session(fresh_session)}"
        self.transcript.clear()
        self._pending_commands.clear()
        self._composer_paste_items.clear()
        self._last_learning_notice_id = None
        self._startup_transcript_primed = False
        if hasattr(self, "_first_real_turn_committed"):
            self._first_real_turn_committed.clear()
        self._prime_transcript(use_proactive_opening=True)
        del previous_episode  # referenced for clarity; learning uses the id above
        self._append_entry(
            "notice",
            "Wake surface",
            f"🐾 Elephant Agent reopened this elephant on a fresh Episode.\n🌱 {learning_detail}.",
        )
        self._refresh_shell_frame()
        return False

    if self._dispatch_skill_slash_command(raw_command, command, args):
        return False

    self._append_entry("command", "Unknown command", f"{command}\nhelp: /help")
    return False

def _parse_slash_command(self, raw_command: str) -> list[str]:
    try:
        return shlex.split(raw_command)
    except ValueError:
        fallback = self._text_surface_fallback_parts(raw_command)
        if fallback is not None:
            return fallback
        raise

def _text_surface_fallback_parts(self, raw_command: str) -> list[str] | None:
    return None
