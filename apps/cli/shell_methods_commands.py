"""Bound methods extracted from apps/cli/shell.py."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import unified_diff
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
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
from packages.state import parse_user_profile_text
from packages.tools.handler_support import resolve_allowed_path
from .provider_flow import provider_setup_defaults, run_provider_selection_wizard
from .runtime import CliRuntime
from .shell_progress_support import outcome_state_focus_meta
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

def _append_help(self) -> None:
    lines = [
        "Stay in the conversation. Slash commands exist only for orientation and control.",
        "",
        "/status - refresh elephant, provider, and Personal Model posture",
        "/recall [list|inspect|search|lineage] - inspect Step/Episode recall evidence",
        "/tools [inspect|enable|disable|install|run] - govern built-ins and manifest-backed tools",
        "/skills [list|active|search|view|enable|disable|install] - discover, inspect, and govern skill packages",
        "/learn [queue|run|start|status|history] - manually trigger or inspect background learning",
        "/gateway [status|setup|doctor] - inspect gateway posture and setup commands",
        "/cron [create|inspect|pause|resume|remove] - govern built-in scheduled jobs",
        "/providers [configure|status|list] - switch provider, endpoint, key, and embedding path",
        "/models [configure|status|list] - switch the active dialogue model and context window",
        "/clear - reset the transcript and replay the opening reply",
        "/exit - leave the wake surface",
        "",
        "Use /skills to inspect installed skills, search shelves, or view one skill package before invoking it.",
        "Examples: /skills active · /skills search notes · /skills view apple-notes",
        "",
        "Elephant management stays in the CLI: elephant herd new <name>",
        "Elephant inventory and retirement stay in the CLI: elephant herd / elephant herd delete <name>",
        "",
        "Tip: type / and keep typing to open the command palette.",
    ]
    self._append_entry("notice", "Command palette", "\n".join(lines))


def _append_personal_model(self, args: list[str]) -> None:
    action = (args[0] if args else "summary").strip().lower()
    session = self.runtime.inspect_session(self.session_id)
    state = self.runtime.state_for_elephant(self.runtime.elephant_id_for_session(session)) or self.runtime.current_elephant_state()
    if state is None:
        self._append_entry("recovery", "About you", "No active elephant is available yet.")
        return
    continuity = self.runtime.inspect_continuity(session_id=self.session_id)
    known_user_fields = parse_user_profile_text((continuity.profile.user_profile_text or "").strip())
    who_i_am = str(known_user_fields.get("preferred_name") or "").strip() or "<not learned yet>"
    list_facts = getattr(self.runtime.repository, "list_personal_model_facts", None)
    if callable(list_facts):
        try:
            facts = tuple(list_facts(personal_model_id=state.personal_model_id, status="active"))
        except Exception:
            facts = ()
    else:
        facts = ()
    list_questions = getattr(self.runtime.repository, "list_open_questions", None)
    if callable(list_questions):
        try:
            open_questions = tuple(list_questions(personal_model_id=state.personal_model_id, status="open"))
        except Exception:
            open_questions = ()
    else:
        open_questions = ()
    if action in {"summary", "show", "who"}:
        lines = [
            f"personal_model_id: {state.personal_model_id}",
            f"state_id: {state.state_id}",
            f"who_i_am: {who_i_am}",
            f"how_elephant_understands_me: {len(facts)} durable fact(s)",
            f"what_is_grounded: {sum(1 for fact in facts if getattr(fact, 'status', '') == 'active')} active fact(s)",
            f"what_needs_correction: {len(open_questions)} open question(s)",
            "procedure_rows: procedures are tracked in procedure library state, not Personal Model support rows",
        ]
        self._append_entry("notice", "About you", "\n".join(lines))
        return
    if action == "evidence":
        rows = [
            f"{getattr(fact, 'fact_id', '<fact>')} | {getattr(fact, 'lens', '')}.{getattr(fact, 'facet', '')} | {getattr(fact, 'committed_at', None).isoformat() if getattr(fact, 'committed_at', None) else '<time?>'}"
            for fact in facts[:20]
        ] or ["<no personal model facts>"]
        self._append_entry("notice", "About you facts", "\n".join(rows))
        return
    if action in {"uncertain", "proposals", "confirm"}:
        rows = [
            f"{getattr(question, 'question_id', '<question>')} | {getattr(question, 'lens', '')}.{getattr(question, 'sub_lens', '')} | {getattr(question, 'status', '')} | {getattr(question, 'text', '')}"
            for question in open_questions[:20]
        ] or ["<no pending understanding updates>"]
        self._append_entry("notice", "About you to confirm", "\n".join(rows))
        return
    if action in {"procedural", "skills"}:
        self._append_entry("notice", "How I help", "Procedural patterns are tracked outside Personal Model support rows.")
        return
    if action in {"learned", "diff", "recent"}:
        self._append_entry("notice", "What I learned recently", "Use Personal Model facts and History for recent learning provenance.")
        return
    self._append_entry("recovery", "About you", "Usage: [summary|evidence|uncertain|procedural|learned]")


def _append_gateway(self, args: list[str]) -> None:
    action = (args[0] if args else "status").strip().lower()
    commands = {
        "status": "elephant gateway doctor",
        "setup": "elephant gateway setup",
        "doctor": "elephant gateway doctor",
    }
    command = commands.get(action)
    if command is None:
        self._append_entry("recovery", "Gateway", "Usage: /gateway [status|setup|doctor]")
        return
    self._append_entry(
        "notice",
        "Gateway",
        "\n".join(
            [
                "Gateway setup stays in the CLI so IM credentials and elephant runtime files remain governed.",
                f"next_command: {command}",
                f"runtime_dir: {self.runtime.paths.state_dir}",
            ]
        ),
    )


def _append_tools(self, args: list[str]) -> None:
    command = args[0] if args else "list"
    if command in {"list", "ls"}:
        tools = self.runtime.tool_catalog(session_id=self.session_id)
        lines = [
            (
                f"{tool.tool_id} | enabled={tool.enabled} | available={tool.available} | "
                f"family={tool.family} | audience={tool.audience} | {tool.display_name} | {tool.description}"
            )
            for tool in tools
        ] or ["<empty>"]
        lines.extend(
            [
                "",
                "inspect: /tools inspect <tool-id>",
                "enable: /tools enable <tool-id>",
                "disable: /tools disable <tool-id>",
                "install: /tools install </path/to/tools.json>",
                'run terminal: /tools run tool.terminal.exec command="pwd"',
                'run search: /tools run tool.file.search query="elephant"',
                'run web: /tools run tool.web.search query="agentic intelligence"',
                'read page: /tools run tool.web.read url="https://example.com"',
                'run todos: /tools run tool.todo.manage action=list',
                'search understanding: /tools run tool.personal_model.search query="review style"',
                'update understanding: /tools run tool.personal_model.update action=remember lens=identity topic=identity.style.review.feedback text="prefers direct review" reason="user said this preference"',
                'manage cron: /tools run tool.cron.manage action=list',
            ]
        )
        self._append_entry("notice", "Tools", "\n".join(lines))
        return
    if command == "inspect":
        if len(args) < 2:
            self._append_entry("recovery", "Tools", "Usage: /tools inspect <tool-id>")
            return
        tool = self.runtime.inspect_tool(args[1], session_id=self.session_id)
        self._append_entry(
            "status",
            "Tool",
            "\n".join(
                [
                    f"tool_id: {tool.tool_id}",
                    f"display_name: {tool.display_name}",
                    f"enabled: {tool.enabled}",
                    f"available: {tool.available}",
                    f"availability_reason: {tool.availability.reason or '<none>'}",
                    f"version: {tool.version}",
                    f"family: {tool.family}",
                    f"audience: {tool.audience}",
                    f"backend: {tool.backend or '<none>'}",
                    f"description: {tool.description}",
                    f"categories: {', '.join(tool.side_effects.categories) or '<none>'}",
                    f"approval_class: {tool.side_effects.approval_class}",
                    f"risk_class: {tool.side_effects.risk_class}",
                    f"provenance: {tool.provenance or 'built-in'}",
                ]
            ),
        )
        return
    if command in {"enable", "disable"}:
        if len(args) < 2:
            self._append_entry("recovery", "Tools", f"Usage: /tools {command} <tool-id>")
            return
        updated = self.runtime.set_tool_enabled(
            args[1],
            command == "enable",
            session_id=self.session_id,
        )
        self._append_entry("status", "Tool updated", f"{updated.tool_id}\nenabled: {updated.enabled}")
        return
    if command == "install":
        if len(args) < 2:
            self._append_entry("recovery", "Tools", "Usage: /tools install </path/to/tools.json>")
            return
        try:
            record = self.runtime.install_tool_manifest(args[1], session_id=self.session_id)
        except Exception as error:
            self._append_entry("recovery", "Tools", str(error))
            return
        self._append_entry(
            "status",
            "Tool manifest installed",
            "\n".join(
                [
                    f"source_path: {record.source_path}",
                    f"tool_ids: {', '.join(record.tool_ids) or '<empty>'}",
                    f"executable_tool_ids: {', '.join(record.executable_tool_ids) or '<empty>'}",
                ]
            ),
        )
        return
    if command == "run":
        if len(args) < 2:
            self._append_entry("recovery", "Tools", "Usage: /tools run <tool-id> key=value ...")
            return
        try:
            arguments = self._parse_named_arguments(args[2:])
        except ValueError as error:
            self._append_entry("recovery", "Tools", str(error))
            return
        try:
            result = self._run_tool_with_progress(args[1], arguments)
        except Exception as error:
            self._append_entry("recovery", "Tool result", str(error), meta=args[1])
            return
        self._append_entry(
            "assistant" if result.outcome == "success" else "recovery",
            "Tool result",
            result.summary,
            meta=f"{args[1]} · outcome={result.outcome}",
        )
        return
    self._append_entry("recovery", "Tools", "Usage: /tools [inspect|enable|disable|install|run]")

def _append_learn(self, args: list[str]) -> None:
    wait_for_worker = "--wait" in args
    filtered_args = [item for item in args if item != "--wait"]
    command = filtered_args[0] if filtered_args else "list"
    if command in {"status", "ls", "list", "history"}:
        status = self.runtime.learning_runtime_status(session_id=self.session_id, limit=8)
        jobs = tuple(status.get("jobs") or ()) if isinstance(status, dict) else ()
        lines = [
            f"worker: {status.get('worker_status', '<unknown>') if isinstance(status, dict) else '<unknown>'}",
            f"jobs: running={status.get('running_count', 0) if isinstance(status, dict) else 0} queued={status.get('queued_count', 0) if isinstance(status, dict) else 0} failed={status.get('failed_count', 0) if isinstance(status, dict) else 0} completed={status.get('completed_count', 0) if isinstance(status, dict) else 0}",
        ]
        for job in jobs:
            if isinstance(job, dict):
                lines.append(f"- {job.get('status', '')} {job.get('job_type', '')} {job.get('trigger', '')} {job.get('job_id', '')}")
        if len(lines) == 2:
            lines.append("<no learning jobs>")
        self._append_entry("notice", "Learning", "\n".join(lines))
        return
    if command == "kill":
        try:
            from apps.learning_worker_runtime import stop_learning_worker

            result = stop_learning_worker(state_dir=self.runtime.paths.state_dir, reason="operator requested /learn kill")
        except Exception as error:
            self._append_entry("recovery", "Learning", str(error))
            return
        self._append_entry("notice", "Learning", f"worker stopped · pid={result.get('stopped_pid') or '<none>'}")
        return
    if command not in {"queue", "run", "start"}:
        self._append_entry("recovery", "Learning", "Usage: /learn [list|run [--wait]|kill]")
        return
    try:
        job = self.runtime.schedule_learning_for_session(
            session_id=self.session_id,
            trigger="manual",
            summary="manual background learning requested from wake shell",
            metadata={"source": "shell.learn", "command": command},
            start_worker=not wait_for_worker,
        )
    except Exception as error:
        self._append_entry("recovery", "Learning", str(error))
        return
    detail = f"queued · {job.job_id} · background worker requested"
    if wait_for_worker:
        completed = subprocess.run(
            (sys.executable, "-m", "apps.learning_worker_command", "--state-dir", str(self.runtime.paths.state_dir), "--once"),
            check=False,
        )
        exit_code = int(completed.returncode or 0)
        if exit_code:
            from apps.learning_worker_runtime import mark_learning_job_terminal_failure

            mark_learning_job_terminal_failure(
                self.runtime,
                job_id=job.job_id,
                worker_id="shell.learn.run",
                error=f"learning worker subprocess exited with code {exit_code}",
            )
        detail = f"ran worker once · exit={exit_code} · {job.job_id}"
    self._append_entry("notice", "Learning", detail)


def _append_skills(self, args: list[str]) -> None:
    command = args[0] if args else "list"
    if command in {"list", "ls"}:
        entries = self.runtime.list_skill_hub(limit=24)
        lines = [
            f"{_display_skill_reference(entry)} | {entry.display_name} | source={entry.source_id} | {entry.summary}"
            for entry in entries
        ] or ["<empty>"]
        lines.extend(
            [
                "",
                "active installed skills: /skills active",
                "search external sources: /skills search <query>",
                "view local or remote: /skills view <skill-id|reference>",
                "enable: /skills enable <skill-id>",
                "disable: /skills disable <skill-id>",
                "install from source: /skills install <skill-id|reference>",
                "install from path: /skills install </path/to/skill-or-skills.json>",
            ]
        )
        self._append_entry("notice", "Skills", "\n".join(lines))
        return
    if command == "active":
        skills = self.runtime.skill_catalog(session_id=self.session_id)
        lines = [
            f"{skill.skill_id} | enabled={skill.enabled} | {skill.display_name} | {skill.summary}"
            for skill in skills
            if skill.enabled
        ] or ["<empty>"]
        self._append_entry("notice", "Active skills", "\n".join(lines))
        return
    if command == "search":
        if len(args) < 2:
            self._append_entry("recovery", "Skills", "Usage: /skills search <query>")
            return
        query = " ".join(args[1:]).strip()
        local_entries = self.runtime.search_skill_hub(query, limit=12)
        external_entries = self.runtime.search_skill_sources(query, limit=12)
        lines: list[str] = []
        if local_entries:
            lines.append("local shelves:")
            lines.extend(
                f"- {_display_skill_reference(entry)} | {entry.display_name} | source={entry.source_id} | {entry.summary}"
                for entry in local_entries
            )
        if external_entries:
            if lines:
                lines.append("")
            lines.append("external sources:")
            lines.extend(
                f"- {entry.reference} | {entry.display_name} | source={entry.source_id} | trust={entry.trust_level or '<unknown>'} | {entry.summary}"
                for entry in external_entries
            )
        if not lines:
            lines.append("<empty>")
        lines.extend(
            [
                "",
                "install one: /skills install <skill-id|reference>",
                "view one: /skills view <skill-id|reference>",
            ]
        )
        self._append_entry("notice", "Skill search", "\n".join(lines))
        return
    if command in {"inspect", "view"}:
        if len(args) < 2:
            self._append_entry("recovery", "Skills", "Usage: /skills view <skill-id|reference>")
            return
        try:
            skill = self.runtime.inspect_skill(args[1], session_id=self.session_id)
        except Exception as error:
            self._append_entry("recovery", "Skills", str(error))
            return
        lines = [
            f"skill_id: {skill.skill_id}",
            f"display_name: {skill.display_name}",
            f"enabled: {skill.enabled}",
            f"version: {skill.version}",
            f"summary: {skill.summary}",
            f"provenance: {skill.provenance or 'built-in'}",
        ]
        installed = skill.metadata.get("installed")
        if isinstance(installed, bool):
            lines.append(f"installed: {installed}")
        slash_command = str(skill.metadata.get("slash_command") or "").strip()
        if slash_command:
            lines.append(f"slash_command: /{slash_command}")
        if skill.instruction_text.strip():
            lines.extend(["", skill.instruction_text.strip()])
        self._append_entry(
            "status",
            "Skill",
            "\n".join(lines),
        )
        return
    if command in {"enable", "disable"}:
        if len(args) < 2:
            self._append_entry("recovery", "Skills", f"Usage: /skills {command} <skill-id>")
            return
        try:
            updated = self.runtime.set_skill_enabled(
                args[1],
                command == "enable",
                session_id=self.session_id,
            )
        except Exception as error:
            self._append_entry("recovery", "Skills", str(error))
            return
        self._append_entry("status", "Skill updated", f"{updated.skill_id}\nenabled: {updated.enabled}")
        return
    if command == "install":
        if len(args) < 2:
            self._append_entry("recovery", "Skills", "Usage: /skills install <skill-id|/path/to/skill|/path/to/skills.json>")
            return
        try:
            result = self.runtime.install_skill_source(args[1], session_id=self.session_id)
        except Exception as error:
            self._append_entry("recovery", "Skills", str(error))
            return
        self._append_entry(
            "status",
            "Skill installed",
            "\n".join(
                [
                    f"source_path: {result.source_path}",
                    f"skill_ids: {', '.join(result.skill_ids) or '<empty>'}",
                    f"status: {result.status}",
                ]
            ),
        )
        self._refresh_skill_slash_specs()
        return
    self._append_entry("recovery", "Skills", "Usage: /skills [list|active|search|view|enable|disable|install]")


def _display_skill_reference(entry) -> str:
    if getattr(entry, "source_id", "") == "builtin":
        return str(getattr(entry, "skill_id", "")).strip() or str(getattr(entry, "reference", ""))
    return str(getattr(entry, "reference", "")).strip()

def _append_cron(self, args: list[str]) -> None:
    command = args[0] if args else "list"
    if command in {"list", "ls"}:
        jobs = self.runtime.cron_jobs(session_id=self.session_id)
        lines = [
            f"{job.job_id} | {job.status} | {job.name} | {job.schedule_text} | {job.action_kind}"
            for job in jobs
        ] or ["<empty>"]
        lines.extend(
            [
                "",
                'create prompt task: /cron create name="Joke loop" schedule="every 1m" prompt="讲一个中文笑话"',
                "inspect: /cron inspect <job-id>",
                "pause: /cron pause <job-id>",
                "resume: /cron resume <job-id>",
                "remove: /cron remove <job-id>",
            ]
        )
        self._append_entry("notice", "Cron jobs", "\n".join(lines))
        return
    if command == "create":
        try:
            arguments = self._parse_named_arguments(args[1:])
        except ValueError as error:
            self._append_entry("recovery", "Cron jobs", str(error))
            return
        schedule = arguments.get("schedule", "").strip()
        prompt = arguments.get("prompt", "").strip()
        if not schedule or not prompt:
            self._append_entry(
                "recovery",
                "Cron jobs",
                "Usage: /cron create name=<name> schedule=<schedule> prompt=<task>",
            )
            return
        payload = {"prompt": prompt}
        name = arguments.get("name", "").strip() or "Cron · prompt"
        try:
            job = self.runtime.create_cron_job(
                session_id=self.session_id,
                name=name,
                schedule=schedule,
                payload=payload,
            )
        except Exception as error:
            self._append_entry("recovery", "Cron jobs", str(error))
            return
        self._append_entry(
            "status",
            "Cron job created",
            "\n".join(
                [
                    f"job_id: {job.job_id}",
                    f"name: {job.name}",
                    f"schedule: {job.schedule_text}",
                    f"action_kind: {job.action_kind}",
                    f"next_run_at: {job.next_run_at.isoformat() if job.next_run_at is not None else '<none>'}",
                ]
            ),
        )
        return
    if command == "inspect":
        if len(args) < 2:
            self._append_entry("recovery", "Cron jobs", "Usage: /cron inspect <job-id>")
            return
        try:
            job = self.runtime.inspect_cron_job(args[1])
        except Exception as error:
            self._append_entry("recovery", "Cron jobs", str(error))
            return
        self._append_entry(
            "status",
            "Cron job",
            "\n".join(
                [
                    f"job_id: {job.job_id}",
                    f"name: {job.name}",
                    f"status: {job.status}",
                    f"schedule: {job.schedule_text}",
                    f"action_kind: {job.action_kind}",
                    f"last_summary: {job.last_summary or '<none>'}",
                ]
            ),
        )
        return
    if command in {"pause", "resume", "remove"}:
        if len(args) < 2:
            self._append_entry("recovery", "Cron jobs", f"Usage: /cron {command} <job-id>")
            return
        try:
            if command == "pause":
                job = self.runtime.pause_cron_job(args[1])
            elif command == "resume":
                job = self.runtime.resume_cron_job(args[1])
            else:
                job = self.runtime.remove_cron_job(args[1])
        except Exception as error:
            self._append_entry("recovery", "Cron jobs", str(error))
            return
        self._append_entry(
            "status",
            "Cron job updated",
            "\n".join(
                [
                    f"job_id: {job.job_id}",
                    f"name: {job.name}",
                    f"status: {'removed' if command == 'remove' else job.status}",
                ]
            ),
        )
        return
    self._append_entry("recovery", "Cron jobs", "Usage: /cron [create|inspect|pause|resume|remove]")

def _parse_named_arguments(self, args: list[str]) -> dict[str, str]:
    payload: dict[str, str] = {}
    for item in args:
        if "=" not in item:
            raise ValueError("tool arguments must be key=value pairs")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError("tool argument keys must not be empty")
        payload[key] = self._strip_wrapping_quotes(value.strip())
    return payload

def _requested_webpage_url(self, message: str) -> str | None:
    lowered = message.strip().lower()
    match = WEB_URL_PATTERN.search(message)
    if match is None:
        return None
    if not any(
        phrase in lowered
        for phrase in (
            "read ",
            "open ",
            "fetch ",
            "visit ",
            "browse ",
            "look at ",
            "check ",
            "web page",
            "website",
            " url",
        )
    ):
        return None
    return match.group(1).rstrip(").,!?\"'")

def _strip_wrapping_quotes(self, value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1].strip()
    return value

def _append_status(self) -> None:
    session = self.runtime.inspect_session(self.session_id)
    provider = dict(self.runtime.provider_summary())
    continuity = self.runtime.inspect_continuity(session_id=self.session_id)
    growth = self.runtime.inspect_growth(session_id=self.session_id)
    provider_doctor = self.runtime.provider_doctor()
    security_doctor = self.runtime.security_doctor()
    try:
        wake_outcome = self.runtime.inspect_wake_continuity(self.session_id)
    except Exception:
        wake_lines = [
            "loop_mode: foreground",
            f"loop_selection: {continuity.wake_action}",
            "selected_current_work: <none>",
            f"loop_rationale: {continuity.wake_summary}",
            "planned_current_work: <none>",
        ]
    else:
        planned_current_work = wake_outcome.state_focus.strip() or "<none>"
        wake_lines = [
            "loop_mode: foreground",
            f"loop_selection: {wake_outcome.wake_action}",
            f"selected_current_work: {planned_current_work}",
            f"loop_rationale: {wake_outcome.wake_summary}",
            f"planned_current_work: {planned_current_work}",
            f"state_reconciliation: {wake_outcome.reconciliation.summary}",
        ]
    lines = [
        f"elephant_id: {self.runtime.elephant_id_for_session(session)}",
        f"status: {session.status}",
        f"provider_id: {provider.get('provider_id', '<unset>')}",
        f"provider_source: {provider.get('source', '<unknown>')}",
        f"provider_model: {provider.get('model_id') or provider.get('default_model') or '<unset>'}",
        f"provider_context_window: {provider.get('context_window_tokens') or '<unset>'}",
        f"provider_secret_status: {provider.get('secret_status', '<unknown>')}",
        f"provider_status: {provider_doctor['status']}",
        f"security_status: {security_doctor['status']}",
        *wake_lines,
        f"state_action: {continuity.wake_action}",
        f"state_summary: {continuity.wake_summary}",
        f"personal_model_understanding: {growth.stage_title}",
        f"personal_model_growth: {growth.cycle_label}",
        f"personal_model_checkpoint: {growth.level}",
        f"personal_model_signal: {growth.power_score}",
        f"personal_model_progress: {growth.progress_percent}%",
        f"personal_model_next: {growth.next_milestone}",
        f"personal_model_momentum: {growth.momentum_state}",
        (
            "personal_model_support: "
            f"dialogues={growth.canonical_dialogues} "
            f"tokens={growth.state.total_tokens} "
            f"experiences={growth.canonical_experiences} "
            f"promoted={growth.canonical_promoted_procedures} "
            f"active_days={growth.canonical_active_days}"
        ),
    ]
    if growth.active_challenge_tracks:
        lines.append(f"personal_model_focus: {growth.active_challenge_tracks[0].summary}")
    for check in provider_doctor["checks"]:
        summary = f" | {check['summary']}" if check.get("summary") else ""
        lines.append(f"provider/{check['check']}: {check['status']}{summary}")
    for check in security_doctor["checks"]:
        summary = f" | {check['summary']}" if check.get("summary") else ""
        lines.append(f"security/{check['check']}: {check['status']}{summary}")
    experiences = self.runtime.inspect_experiences(session_id=self.session_id, limit=2)
    displayable = self._displayable_experiences(experiences)
    try:
        learning_status = self.runtime.learning_runtime_status(session_id=self.session_id)
    except Exception:
        learning_status = None
    jobs = tuple((learning_status or {}).get("jobs") or ())
    if jobs:
        latest_job = jobs[0]
        lines.append(
            "learning_active_job: "
            f"{latest_job.get('status', '<unknown>')} · "
            f"{latest_job.get('trigger', '<unknown>')} · "
            f"{latest_job.get('progress_stage', '<none>')}"
        )
    if displayable:
        lines.append(f"latest_learning: {self._format_experience_status(displayable[0])}")
    else:
        lines.append("latest_learning: no captured experience yet")
    if provider_doctor["status"] != "ready":
        lines.append("next: exit and run elephant init")
    else:
        lines.append("next: keep talking")
    self._append_entry("status", "Elephant status", "\n".join(lines))

def _append_recall(self, args: list[str]) -> None:
    action = args[0] if args else "inspect"
    if action in {"inspect", "show", "list", "ls"} and len(args) <= 1:
        surface = self.runtime.inspect_recall_evidence_surface(self.session_id)
        lines = list(render_recall_evidence_lines(surface))
        lines.extend(
            [
                "",
                "inspect: /recall inspect <evidence-ref>",
                "search: /recall search <query>",
                "lineage: /recall lineage <evidence-ref>",
            ]
        )
        self._append_entry("notice", "Understanding", "\n".join(lines))
        return
    if action == "inspect":
        if len(args) < 2:
            self._append_entry("recovery", "Understanding", "Usage: /recall inspect <evidence-ref>")
            return
        evidence = self.runtime.inspect_recall_evidence_item(self.session_id, args[1])
        detail = RecallEvidenceOperatorDetail(
            evidence=evidence,
            state=self.runtime.recall_evidence_state(evidence.evidence_id),
            lineage=self.runtime.recall_evidence_lineage(evidence.evidence_id),
        )
        surface = build_recall_evidence_operator_surface(
            session_id=self.session_id,
            evidence_items=(detail,),
            index_policy=self.runtime.recall_runtime.index_policy(),
        )
        self._append_entry("notice", "Understanding detail", "\n".join(render_recall_evidence_lines(surface)))
        return
    if action == "search":
        query = " ".join(args[1:]).strip()
        if not query:
            self._append_entry("recovery", "Understanding", "Usage: /recall search <query>")
            return
        surface = self.runtime.search_recall_evidence_surface(self.session_id, query=query)
        self._append_entry("notice", "Understanding search", "\n".join(render_recall_evidence_lines(surface)))
        return
    if action == "lineage":
        if len(args) < 2:
            self._append_entry("recovery", "Understanding", "Usage: /recall lineage <evidence-ref>")
            return
        evidence_ref = args[1]
        self._append_entry(
            "notice",
            "Understanding lineage",
            "\n".join(
                [
                    f"evidence_ref: {evidence_ref}",
                    f"state: {self.runtime.recall_evidence_state(evidence_ref) or 'unknown'}",
                    f"lineage: {self.runtime.recall_evidence_lineage(evidence_ref) or '<none>'}",
                ]
            ),
        )
        return
    self._append_entry("recovery", "Understanding", "Usage: /recall [list|inspect|search|lineage]")

def _append_outcome(self, outcome: KernelOutcome) -> None:
    self._last_prompt_tokens = outcome.execution.prompt_tokens
    self._last_completion_tokens = outcome.execution.completion_tokens
    self._last_total_tokens = outcome.execution.total_tokens
    if self.debug and outcome.stages:
        stage_lines = [
            f"{stage.stage} | {stage.detail} | {stage.recorded_at.isoformat(timespec='seconds')}"
            for stage in outcome.stages
        ]
        self._append_entry("status", "Runtime stages", "\n".join(stage_lines))
    assistant_name = self.runtime.inspect_profile(self.runtime.inspect_session(self.session_id).personal_model_id).state.display_name
    assistant_lines = [outcome.execution.summary]
    if self.debug and outcome.plan is not None:
        assistant_lines.append(f"plan: {outcome.plan.rationale}")
    if self.debug:
        assistant_lines.extend(
            [
                f"execution: {outcome.execution.outcome}",
                f"current_context: {outcome.state.summary or '<none>'}",
                f"recall_hits: {len(outcome.recall_items)}",
            ]
        )
    self._append_entry("assistant", assistant_name, "\n".join(assistant_lines), meta=outcome_state_focus_meta(outcome))

def _append_growth_update_message(self, update) -> None:
    if update is None:
        return
    continuity = self.runtime.inspect_continuity(session_id=self.session_id)
    assistant_name = continuity.profile.state.display_name or "Elephant Agent"
    after = update.after
    after_checkpoint = getattr(after, "level", 0)
    after_growth = getattr(after, "cycle_label", "Evidence I")
    after_identity = getattr(after, "identity_line", getattr(getattr(after, "stage", None), "title", "Elephant Agent"))
    if update.stage_changed:
        body = (
            f"The path is clearer now: {after_identity}. "
            "I'll carry this understanding forward."
        )
        meta = "understanding · clearer path"
    else:
        body = (
            f"Something settled into the Personal Model — checkpoint {after_checkpoint} in {after_growth}. "
            "I'll carry it forward."
        )
        meta = "understanding · checkpoint"
    self._append_entry("growth", assistant_name, body, meta=meta)
    # Force the status bar to pick up the new growth checkpoint on the next render tick,
    # rather than waiting on the 1.5s growth-cache TTL.
    self._status_bar_growth_cache = None
    # Poke the background refresher to re-prime the growth snapshot now,
    # so the status bar reflects the new checkpoint immediately.
    try:
        self._wake_status_refresher()
    except Exception:
        pass


def _append_latest_learning_result(self) -> None:
    try:
        status = self.runtime.learning_runtime_status(session_id=self.session_id, limit=8)
    except Exception:
        return
    jobs = tuple(status.get("jobs") or ()) if isinstance(status, dict) else ()
    latest_result = next(
        (
            job
            for job in jobs
            if isinstance(job, dict)
            and str(job.get("status") or "") == "completed"
            and (str(job.get("result_status") or "").strip() or str(job.get("result_summary") or "").strip())
        ),
        None,
    )
    if latest_result is None:
        return
    result_id = str(latest_result.get("result_job_id") or latest_result.get("job_id") or "").strip()
    if result_id and getattr(self, "_last_learning_notice_id", None) == result_id:
        return
    result_summary = str(latest_result.get("result_summary") or "").strip()
    summary = result_summary or str(latest_result.get("summary") or "").strip() or "completed"
    self._append_entry(
        "notice",
        "Learning",
        f"Latest grounded learning: {summary}",
        meta=f"learning · {result_id or latest_result.get('job_id') or 'latest'}",
    )
    self._last_learning_notice_id = result_id or getattr(self, "_last_learning_notice_id", None)


def _append_expand(self, args: list[str]) -> None:
    """Re-print the most recent folded notice in full.

    Long dumps get trimmed when rendered to the transcript so the
    screen stays readable; this command surfaces the original body
    on demand. Usage: `/expand last` or just `/expand`.
    """
    target = (args[0] if args else "last").strip().lower() or "last"
    bodies = getattr(self, "_folded_entry_bodies", None) or {}
    if target not in {"last"}:
        self._append_entry(
            "recovery",
            "Expand",
            "Only `/expand last` is supported right now — it reprints the most recent folded entry.",
        )
        return
    body = bodies.get("__last__")
    if not body:
        self._append_entry(
            "notice",
            "Expand",
            "Nothing to expand — the transcript has no folded entries.",
        )
        return
    self._append_entry("notice", "📖 Expanded", body)
