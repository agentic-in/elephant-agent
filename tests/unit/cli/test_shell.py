from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from queue import Queue
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from apps.cli.runtime import CliRuntime
from apps.cli.shell_composer import (
    _state_focus_notice_fragments,
    _startup_transition_result,
    build_composer_body,
    prompt_style_map,
)
from apps.cli.shell_progress import _VisibleToolEvent, latest_stream_text, reset_stream_text, stream_text_tracker, turn_tool_progress_lines
import apps.cli.shell_progress_runtime as shell_progress_runtime
from apps.cli.shell_render import _render_tooltrace_body_line
import apps.cli.shell_render as shell_render
from apps.cli.shell_banner import _learning_job_execution_summary, _skill_affinity_summary
import apps.cli.shell_progress_trace as shell_progress_trace
from apps.cli.shell_clarify import ShellClarifyState, render_clarify_fragments, route_clarify_answer
from apps.cli.shell_stack import FormattedTextControl as StackFormattedTextControl, ScrollablePane, Window as StackWindow
from apps.cli.shell import (
    BRAND_ACCENT,
    BRAND_DARK,
    BRAND_LIGHT,
    BRAND_MUTED,
    BRAND_ACCENT_STRONG,
    COMMAND_PALETTE_VISIBLE_ROWS,
    Console,
    Document,
    ELEPHANT_STAGE_ROWS,
    ELEPHANT_STAGE_ROWS,
    GROWTH_PROGRESS_EMPTY,
    GROWTH_PROGRESS_FILLED,
    GROWTH_PROGRESS_WIDTH,
    GROWTH_HIGHLIGHT_FG,
    HATCHLING_STAGE_ROWS,
    HATCHLING_HEAD_ROWS,
    PendingShellCommand,
    QUEUE_PREVIEW_INSET,
    SCOUT_STAGE_ROWS,
    SEED_STAGE_ROWS,
    SHELL_WELCOME_HEADLINE,
    STARTUP_SEQUENCE_FINAL_DELAY,
    STARTUP_SEQUENCE_STEP_DELAY,
    USER_HISTORY_BG,
    USER_HISTORY_FG,
    _centered_elephant_rows,
    ProductizedShell,
    RICH_AVAILABLE,
    ShellCompleter,
    TranscriptEntry,
    _display_width,
)
from apps.cli.wizard import WIZARD_BACK
from apps.cli.shell_ui import (
    GROWTH_MARK_CANVAS_WIDTH,
    LIVE_DIFF_ADD_FG,
    LIVE_DIFF_FILE_FG,
    LIVE_DIFF_HUNK_FG,
    LIVE_DIFF_REMOVE_FG,
    SETTLED_DIFF_ADD_FG,
    SETTLED_DIFF_FILE_FG,
    SETTLED_DIFF_HUNK_FG,
    SETTLED_DIFF_REMOVE_FG,
    visual_centered_rows,
)
from packages.contracts import (
    ContextBundle,
    EventEnvelope,
    ExecutionResult,
    Fact,
    OpenQuestion,
    StateFocusReason,
    PromptEnvelope,
    Record,
)
from packages.contracts.runtime import StateFocusDecision
from packages.growth import GrowthTurnSignals, apply_turn_growth, default_growth_state
from packages.state import render_user_profile_text
from packages.skills import SkillSearchEntry
from packages.tools import ToolApprovalResult, ToolLifecycleEvent, ToolInvocation


class _StubConsole:
    def __init__(self, width: int) -> None:
        self.width = width
        self.size = type("Size", (), {"width": width})()


class _CaptureConsole(_StubConsole):
    def __init__(self, width: int) -> None:
        super().__init__(width)
        self.printed: list[str] = []
        self.clear_calls: list[bool] = []

    def clear(self, home: bool = False) -> None:
        self.clear_calls.append(home)

    def print(self, renderable="") -> None:
        if hasattr(renderable, "plain"):
            self.printed.append(renderable.plain)
        else:
            self.printed.append(str(renderable))


class _WebPageStubServer:
    def __init__(self) -> None:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/"

    def start(self) -> "_WebPageStubServer":
        self._thread.start()
        return self

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                body = (
                    "<html><head><title>Atlas Journal</title></head>"
                    "<body><main><h1>Atlas Journal</h1>"
                    "<p>This page explains the durable elephant continuity loop.</p>"
                    "</main></body></html>"
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                return

        return Handler


class ShellPaletteTest(unittest.TestCase):
    def _make_shell(
        self,
        *,
        opened: str = "Shaped new",
        user_profile_text: str | None = None,
        prime_transcript: bool = False,
    ) -> ProductizedShell:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        root = Path(tmpdir.name)
        state_dir = root / "state"
        profile_dir = root / "profile"
        profile_dir.mkdir()
        (root / "profile.json").write_text(
            json.dumps(
                {
                    "profile_id": "profile-companion",
                    "display_name": "Elephant Agent",
                    "mode": "companion",
                }
            ),
            encoding="utf-8",
        )
        runtime = CliRuntime.create(state_dir=state_dir)
        runtime.update_identity_state(
            profile_id="profile-companion",
            elephant_identity_text="Stay durable.",
        )
        session = runtime.create_elephant(elephant_id="atlas")
        if user_profile_text is not None:
            runtime.update_user_state(profile_id=session.personal_model_id, text=user_profile_text)
        shell = ProductizedShell(runtime, session_id=session.session_id, opened=opened)
        if prime_transcript:
            shell._prime_transcript()
        return shell

    def _make_shell_without_identity_update(self) -> ProductizedShell:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        root = Path(tmpdir.name)
        profile_dir = root / "profile"
        profile_dir.mkdir()
        (root / "profile.json").write_text(
            json.dumps(
                {
                    "profile_id": "profile-companion",
                    "display_name": "Elephant Agent",
                    "mode": "companion",
                }
            ),
            encoding="utf-8",
        )
        runtime = CliRuntime.create(state_dir=root / "state")
        session = runtime.create_elephant(elephant_id="atlas")
        return ProductizedShell(runtime, session_id=session.episode_id, opened="Shaped new")

    def test_shell_uses_normal_terminal_scrollback_by_default(self) -> None:
        shell = self._make_shell_without_identity_update()

        self.assertFalse(shell._use_alternate_screen)

    def test_shell_allows_opt_in_alternate_screen(self) -> None:
        with mock.patch.dict(os.environ, {"ELEPHANT_ALT_SCREEN": "1"}):
            shell = self._make_shell_without_identity_update()

        self.assertTrue(shell._use_alternate_screen)

    def test_refresh_shell_frame_does_not_clear_or_replay_same_frame_in_scrollback_mode(self) -> None:
        shell = self._make_shell_without_identity_update()
        shell.console = _CaptureConsole(100)
        shell._last_shell_frame_token = shell._current_shell_frame_token()
        shell._rendered_entries = 2

        shell._refresh_shell_frame()

        self.assertEqual(shell.console.clear_calls, [])
        self.assertEqual(shell.console.printed, [])
        self.assertEqual(shell._rendered_entries, 2)

    def test_refresh_shell_frame_clears_and_replays_in_alternate_screen_mode(self) -> None:
        shell = self._make_shell_without_identity_update()
        shell.console = _CaptureConsole(100)
        shell._use_alternate_screen = True
        shell._last_shell_frame_token = shell._current_shell_frame_token()
        shell._rendered_entries = 2

        shell._refresh_shell_frame()

        self.assertEqual(shell.console.clear_calls, [True])
        self.assertGreaterEqual(len(shell.console.printed), 1)
        self.assertEqual(shell._rendered_entries, 0)

    def test_prime_transcript_uses_elephant_state_name_for_assistant_title(self) -> None:
        shell = self._make_shell(opened="Opened elephant atlas")
        shell.runtime.update_identity_state(
            session_id=shell.session_id,
            display_name="Leah",
            elephant_identity_text=(
                "# Elephant Identity: Leah\n"
                "Display name: Leah\n\n"
                "You are Leah, a steady companion on one continuous line with this person."
            ),
        )

        shell.transcript.clear()
        shell._startup_transcript_primed = False
        shell._prime_transcript(use_proactive_opening=False)

        self.assertEqual(shell.transcript[-1].title, "Leah")
        self.assertNotEqual(shell.transcript[-1].title, "Elephant Agent")

    def test_command_palette_stays_minimal_and_identity_focused(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_dir = root / "state"
            profile_dir = root / "profile"
            profile_dir.mkdir()
            (root / "profile.json").write_text(
                json.dumps(
                    {
                        "profile_id": "profile-companion",
                        "display_name": "Elephant Agent",
                        "mode": "companion",
                    }
                ),
                encoding="utf-8",
            )

            runtime = CliRuntime.create(state_dir=state_dir)
            runtime.update_identity_state(
                profile_id="profile-companion",
                elephant_identity_text="Stay durable.",
            )
            session = runtime.create_elephant(elephant_id="atlas")
            shell = ProductizedShell(runtime, session_id=session.session_id, opened="Shaped new")
            completer = ShellCompleter(shell)

            root_commands = {item.text for item in completer.get_completions(Document("/"), None)}
            self.assertIn("/help", root_commands)
            self.assertNotIn("/procedure", root_commands)
            self.assertIn("/tools", root_commands)
            self.assertIn("/skills", root_commands)
            self.assertIn("/learn", root_commands)
            self.assertIn("/cron", root_commands)
            self.assertIn("/providers", root_commands)
            self.assertIn("/models", root_commands)
            self.assertNotIn("/whoami", root_commands)
            self.assertNotIn("/personal-model", root_commands)
            self.assertIn("/gateway", root_commands)
            self.assertNotIn("/profile", root_commands)
            self.assertNotIn("/activity", root_commands)
            self.assertNotIn("/resume", root_commands)
            self.assertNotIn("/audit", root_commands)
            self.assertNotIn("/frozen", root_commands)
            self.assertNotIn("/elephant", root_commands)
            self.assertNotIn("/herd", root_commands)
            self.assertNotIn("/wake", root_commands)
            self.assertNotIn("/doctor", root_commands)
            self.assertNotIn("/new", root_commands)

            filtered_skill_commands = {item.text for item in completer.get_completions(Document("/apple"), None)}
            self.assertNotIn("/apple-notes", filtered_skill_commands)

            learn_commands = {item.text for item in completer.get_completions(Document("/learn "), None)}
            self.assertIn("queue", learn_commands)
            self.assertIn("run", learn_commands)
            self.assertIn("start", learn_commands)
            self.assertIn("status", learn_commands)
            self.assertIn("history", learn_commands)

            tool_commands = {item.text for item in completer.get_completions(Document("/tools "), None)}
            self.assertIn("inspect", tool_commands)
            self.assertIn("enable", tool_commands)
            self.assertIn("disable", tool_commands)
            self.assertIn("install", tool_commands)
            self.assertIn("run", tool_commands)

            skill_commands = {item.text for item in completer.get_completions(Document("/skills "), None)}
            self.assertIn("inspect", skill_commands)
            self.assertIn("enable", skill_commands)
            self.assertIn("disable", skill_commands)
            self.assertIn("install", skill_commands)
            self.assertIn("search", skill_commands)

            cron_commands = {item.text for item in completer.get_completions(Document("/cron "), None)}
            self.assertIn("create", cron_commands)
            self.assertIn("inspect", cron_commands)
            self.assertIn("pause", cron_commands)
            self.assertIn("resume", cron_commands)
            self.assertIn("remove", cron_commands)

            removed_whoami_commands = {
                item.text for item in completer.get_completions(Document("/whoami "), None)
            }
            self.assertEqual(set(), removed_whoami_commands)

            gateway_commands = {item.text for item in completer.get_completions(Document("/gateway "), None)}
            self.assertIn("status", gateway_commands)
            self.assertIn("setup", gateway_commands)
            self.assertIn("doctor", gateway_commands)

    def test_learn_slash_status_is_bound(self) -> None:
        shell = self._make_shell()

        handled = shell._handle_slash_command("/learn status")

        self.assertFalse(handled)
        self.assertTrue(any(entry.title == "Learning" for entry in shell.transcript))

    def test_latest_learning_notice_ignores_regular_turn_experience(self) -> None:
        shell = self._make_shell()
        shell.runtime._append_outcome_experience(
            SimpleNamespace(
                route_session_id=shell.session_id,
                state=SimpleNamespace(summary="ordinary turn summary"),
                execution=SimpleNamespace(
                    execution_id="execution-1",
                    outcome="ok",
                    summary="ordinary turn summary",
                    produced_artifact_ids=(),
                ),
                event=SimpleNamespace(event_id="event-1"),
                tool_call_count=0,
                model_turn_count=1,
            )
        )

        shell._append_latest_learning_result()

        self.assertFalse(any(entry.title == "Learning" for entry in shell.transcript))

    def test_latest_learning_notice_surfaces_completed_learning_result_once(self) -> None:
        shell = self._make_shell()
        job = shell.runtime.schedule_learning_for_session(
            session_id=shell.session_id,
            trigger="manual",
            summary="manual learning requested",
            start_worker=False,
        )
        shell.runtime.write_learning_result(
            session_id=shell.session_id,
            job_id=job.job_id,
            status="updated",
            summary="remembered the direct review preference",
        )
        shell.runtime.repository.complete_learning_job(
            job.job_id,
            worker_id="test",
        )

        shell._append_latest_learning_result()
        shell._append_latest_learning_result()

        learning_entries = tuple(entry for entry in shell.transcript if entry.title == "Learning")
        self.assertEqual(len(learning_entries), 1)
        self.assertIn("remembered the direct review preference", learning_entries[0].body)

    def test_existing_learning_result_is_not_replayed_when_shell_opens(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        runtime = CliRuntime.create(state_dir=Path(tmpdir.name) / "state")
        session = runtime.create_elephant(elephant_id="atlas")
        job = runtime.schedule_learning_for_session(
            session_id=session.episode_id,
            trigger="manual",
            summary="manual learning requested",
            start_worker=False,
        )
        runtime.write_learning_result(
            session_id=session.episode_id,
            job_id=job.job_id,
            status="completed",
            summary="old learning result",
        )
        runtime.repository.complete_learning_job(job.job_id, worker_id="test")

        shell = ProductizedShell(runtime, session_id=session.episode_id, opened="Opened elephant atlas")
        shell._append_latest_learning_result()

        self.assertFalse(any(entry.title == "Learning" for entry in shell.transcript))

    def test_conversational_surface_requests_list_tools_on_explicit_show_list_verbs(self) -> None:
        shell = self._make_shell()

        handled_tools = shell._handle_conversational_surface_request("show tools")

        self.assertTrue(handled_tools)
        self.assertEqual(shell.transcript[-1].kind, "assistant")
        self.assertIn("I can use these tools right now", shell.transcript[-1].body)
        self.assertIn("tool.terminal.exec", shell.transcript[-1].body)
        self.assertIn("tool.file.search", shell.transcript[-1].body)
        self.assertIn("tool.web.search", shell.transcript[-1].body)
        self.assertIn("tool.web.read", shell.transcript[-1].body)
        self.assertIn("tool.personal_model.search", shell.transcript[-1].body)
        self.assertIn("tool.personal_model.update", shell.transcript[-1].body)
        self.assertIn("tool.personal_model.questions", shell.transcript[-1].body)
        self.assertNotIn("tool.memory.recall", shell.transcript[-1].body)
        self.assertNotIn("tool.memory.note", shell.transcript[-1].body)
        self.assertIn("tool.skill.list", shell.transcript[-1].body)
        self.assertIn("tool.skill.view", shell.transcript[-1].body)
        self.assertNotIn("tool.profile.manage", shell.transcript[-1].body)
        self.assertNotIn("tool.memory.upload", shell.transcript[-1].body)
        self.assertNotIn("tool.procedure.inspect", shell.transcript[-1].body)
        self.assertNotIn("tool.procedure.manage", shell.transcript[-1].body)
        self.assertNotIn("tool.skill.manage", shell.transcript[-1].body)
        self.assertIn("tool.cron.manage", shell.transcript[-1].body)

    def test_conversational_questions_about_skills_no_longer_bypass_shell(self) -> None:
        shell = self._make_shell()
        original_len = len(shell.transcript)

        handled_skills = shell._handle_conversational_surface_request("what skills do you have?")

        self.assertFalse(handled_skills)
        self.assertEqual(len(shell.transcript), original_len)

    def test_skills_search_routes_through_skill_search_tool_and_records_tooltrace(self) -> None:
        shell = self._make_shell()
        with mock.patch.object(
            shell.runtime.skill_search_hub,
            "search",
            return_value=(
                SkillSearchEntry(
                    skill_id="apple-notes-remote",
                    display_name="Apple Notes Remote",
                    summary="Remote Apple Notes workflow from GitHub.",
                    source_id="github",
                    source_label="GitHub",
                    reference="github:openai/skills/apple-notes",
                    install_reference="github:openai/skills/apple-notes",
                    trust_level="trusted",
                ),
            ),
        ):
            shell._append_skills(["search", "notes"])

        tool_entries = [entry for entry in shell.transcript if entry.kind == "tooltrace"]
        if tool_entries:
            self.assertIn("Calling skills", tool_entries[-1].body)
            self.assertIn("┊ 📚 skills", tool_entries[-1].body)
        self.assertEqual(shell.transcript[-1].title, "Skill search")
        self.assertIn("github:openai/skills/apple-notes", shell.transcript[-1].body)

    def test_plain_turn_with_explicit_skill_name_no_longer_routes_skill_body(self) -> None:
        shell = self._make_shell()
        outcome = mock.Mock()
        with (
            mock.patch.object(shell, "_run_turn_with_progress", return_value=outcome) as run_turn,
            mock.patch.object(shell, "_append_outcome") as append_outcome,
            mock.patch.object(shell, "_show_growth_celebration_if_needed", return_value=None),
            mock.patch.object(shell, "_append_growth_update_message"),
            mock.patch.object(shell, "_refresh_shell_frame"),
            mock.patch.object(type(shell.runtime), "inspect_skill") as inspect_skill,
        ):
            handled = shell._dispatch("use gif-search to find a cat reaction gif")

        self.assertFalse(handled)
        inspect_skill.assert_not_called()
        self.assertEqual(run_turn.call_args.args[0], "use gif-search to find a cat reaction gif")
        self.assertIsNone(run_turn.call_args.kwargs["event_payload"])
        append_outcome.assert_called_once_with(outcome)

    def test_dispatch_clears_pending_context_compaction_frame_before_next_turn(self) -> None:
        shell = self._make_shell()
        shell._pending_context_compaction_frame = {"prompt": "previous", "tick": 0, "kernel_stage_events": ()}
        shell._pending_context_compaction_frame_rendered = True
        with (
            mock.patch.object(shell, "_handle_slash_command", return_value=False),
            mock.patch.object(shell, "_refresh_shell_frame") as refresh,
        ):
            handled = shell._dispatch("/status")

        self.assertFalse(handled)
        self.assertIsNone(shell._pending_context_compaction_frame)
        self.assertFalse(shell._pending_context_compaction_frame_rendered)
        refresh.assert_not_called()

    def test_personal_model_surface_uses_user_name_not_elephant_name(self) -> None:
        shell = self._make_shell(
            user_profile_text=render_user_profile_text(
                preferred_name="Bit",
                current_work="Building durable agent systems.",
            )
        )
        shell.runtime.update_identity_state(
            session_id=shell.session_id,
            display_name="Leah",
            elephant_identity_text=(
                "# Elephant Identity: Leah\n"
                "Display name: Leah\n\n"
                "You are Leah, a steady companion on one continuous line with this person."
            ),
        )

        shell._append_personal_model([])
        self.assertEqual(shell.transcript[-1].title, "About you")
        self.assertIn("who_i_am: Bit", shell.transcript[-1].body)
        self.assertNotIn("who_i_am: Leah", shell.transcript[-1].body)

    def test_whoami_slash_command_is_removed(self) -> None:
        shell = self._make_shell()

        self.assertFalse(shell._handle_slash_command("/whoami"))
        self.assertEqual(shell.transcript[-1].title, "Unknown command")
        self.assertIn("/whoami", shell.transcript[-1].body)

    def test_personal_model_slash_command_is_removed(self) -> None:
        shell = self._make_shell()

        self.assertFalse(shell._handle_slash_command("/personal-model"))
        self.assertEqual(shell.transcript[-1].title, "Unknown command")
        self.assertIn("/personal-model", shell.transcript[-1].body)

    def test_dispatch_persists_response_prompt_usage_after_turn(self) -> None:
        shell = self._make_shell()
        shell._last_prompt_tokens = 12_800
        outcome = SimpleNamespace(
            execution=SimpleNamespace(prompt_tokens=14_000, total_tokens=18_400),
            stages=(),
        )

        with (
            mock.patch.object(shell, "_handle_conversational_surface_request", return_value=False),
            mock.patch.object(shell, "_run_turn_with_progress", return_value=outcome),
            mock.patch.object(shell, "_append_outcome"),
            mock.patch.object(shell, "_show_growth_celebration_if_needed", return_value=None),
            mock.patch.object(shell, "_append_growth_update_message"),
            mock.patch.object(shell, "_refresh_shell_frame_if_needed"),
        ):
            handled = shell._dispatch("continue the thread")

        self.assertFalse(handled)
        self.assertEqual(shell._last_provider_prompt_tokens, 14_000)
        self.assertEqual(shell._last_prompt_tokens, 12_800)

    def test_dispatch_keeps_compacted_context_usage_after_turn(self) -> None:
        shell = self._make_shell()
        shell._last_prompt_tokens = 32_000
        outcome = SimpleNamespace(
            execution=SimpleNamespace(prompt_tokens=32_000, total_tokens=36_400),
            stages=(SimpleNamespace(stage="context-compact"),),
        )

        def run_turn(*_args, **_kwargs):
            shell._last_prompt_tokens = 6_200
            return outcome

        with (
            mock.patch.object(shell, "_handle_conversational_surface_request", return_value=False),
            mock.patch.object(shell, "_run_turn_with_progress", side_effect=run_turn),
            mock.patch.object(shell, "_append_outcome"),
            mock.patch.object(shell, "_show_growth_celebration_if_needed", return_value=None),
            mock.patch.object(shell, "_append_growth_update_message"),
            mock.patch.object(shell, "_refresh_shell_frame_if_needed"),
        ):
            handled = shell._dispatch("continue the thread")

        self.assertFalse(handled)
        self.assertEqual(shell._last_provider_prompt_tokens, 0)
        self.assertEqual(shell._last_prompt_tokens, 6_200)

    def test_dispatch_reads_compacted_context_usage_from_outcome_stage(self) -> None:
        shell = self._make_shell()
        shell._last_prompt_tokens = 32_000
        outcome = SimpleNamespace(
            execution=SimpleNamespace(prompt_tokens=108_000, total_tokens=110_000),
            stages=(
                SimpleNamespace(
                    stage="context-compact",
                    detail="reason=usage tokens=108000->6200 messages=20->3 compacted_messages=17",
                ),
            ),
        )

        with (
            mock.patch.object(shell, "_handle_conversational_surface_request", return_value=False),
            mock.patch.object(shell, "_run_turn_with_progress", return_value=outcome),
            mock.patch.object(shell, "_append_outcome"),
            mock.patch.object(shell, "_show_growth_celebration_if_needed", return_value=None),
            mock.patch.object(shell, "_append_growth_update_message"),
            mock.patch.object(shell, "_refresh_shell_frame_if_needed"),
        ):
            handled = shell._dispatch("continue the thread")

        self.assertFalse(handled)
        self.assertEqual(shell._last_provider_prompt_tokens, 0)
        self.assertEqual(shell._last_prompt_tokens, 6_200)

    def test_plain_turn_with_contextual_skill_phrase_no_longer_routes_skill_body(self) -> None:
        shell = self._make_shell()
        outcome = mock.Mock()
        with (
            mock.patch.object(shell, "_run_turn_with_progress", return_value=outcome) as run_turn,
            mock.patch.object(shell, "_append_outcome") as append_outcome,
            mock.patch.object(shell, "_show_growth_celebration_if_needed", return_value=None),
            mock.patch.object(shell, "_append_growth_update_message"),
            mock.patch.object(shell, "_refresh_shell_frame"),
            mock.patch.object(type(shell.runtime), "inspect_skill") as inspect_skill,
        ):
            handled = shell._dispatch("打开我的苹果备忘录 写一个 elephant 的介绍方案")

        self.assertFalse(handled)
        inspect_skill.assert_not_called()
        self.assertEqual(run_turn.call_args.args[0], "打开我的苹果备忘录 写一个 elephant 的介绍方案")
        self.assertIsNone(run_turn.call_args.kwargs["event_payload"])
        append_outcome.assert_called_once_with(outcome)

    def test_skill_slash_specs_include_full_local_skill_hub_not_first_page_only(self) -> None:
        shell = self._make_shell()

        spec_ids = {spec.skill_id for spec in shell.skill_slash_specs()}

        self.assertGreater(len(spec_ids), 96)
        self.assertIn("gif-search", spec_ids)

    def test_skills_enable_routes_through_runtime_skill_catalog(self) -> None:
        shell = self._make_shell()
        with mock.patch.object(type(shell.runtime), "set_skill_enabled") as set_skill_enabled:
            set_skill_enabled.return_value = SimpleNamespace(skill_id="shell-execution", enabled=True)
            shell._append_skills(["enable", "shell-execution"])

        set_skill_enabled.assert_called_once_with(
            "shell-execution",
            True,
            session_id=shell.session_id,
        )
        self.assertEqual(shell.transcript[-1].title, "Skill updated")

    def test_skills_install_routes_through_runtime_skill_catalog(self) -> None:
        shell = self._make_shell()
        with (
            mock.patch.object(
                type(shell.runtime),
                "install_skill_source",
                return_value=SimpleNamespace(
                    source_path="/tmp/skills.json",
                    skill_ids=("apple-notes",),
                    status="loaded",
                    detail="installed via GitHub (trusted)",
                    metadata={
                        "source_id": "github",
                        "source_label": "GitHub",
                        "source_reference": "github:openai/skills/apple-notes",
                        "install_reference": "github:openai/skills/apple-notes",
                        "trust_level": "trusted",
                        "install_action": "install",
                        "install_requester": "operator",
                    },
                ),
            ) as install_skill_source,
            mock.patch.object(shell, "_refresh_skill_slash_specs") as refresh_specs,
        ):
            shell._append_skills(["install", "apple-notes"])

        install_skill_source.assert_called_once_with(
            "apple-notes",
            session_id=shell.session_id,
        )
        refresh_specs.assert_called_once_with()
        self.assertEqual(shell.transcript[-1].title, "Skill installed")
        self.assertIn("detail: installed via GitHub (trusted)", shell.transcript[-1].body)
        self.assertIn("source_reference: github:openai/skills/apple-notes", shell.transcript[-1].body)
        self.assertIn("install_action: install", shell.transcript[-1].body)
        self.assertIn("install_requester: operator", shell.transcript[-1].body)

    def test_growth_panel_keeps_removed_procedural_memory_out_of_learning_overview(self) -> None:
        shell = self._make_shell()
        now = datetime.now(timezone.utc)
        session = shell.runtime.inspect_session(shell.session_id)
        state = shell.runtime.ensure_elephant_state(session)
        shell.runtime.repository.upsert_record(
            Record(
                record_id="procedure:release-state-recovery",
                kind="derived",
                schema_version="personal_model.procedural_memory/v1",
                owner_scope="personal_model",
                personal_model_id=state.personal_model_id,
                state_id=state.state_id,
                layer_type="procedural_memory",
                created_at=now,
                payload={
                    "title": "Release State Recovery",
                    "summary": "Recovered the active release State and clarified the next governed step.",
                    "status": "active",
                    "maturity_state": "committed",
                    "approval_state": "approved",
                    "behavioral_state": "active",
                    "trigger_conditions": ("release recovery",),
                    "steps": ("Keep release recovery work grounded in current State evidence.",),
                },
            )
        )

        continuity = shell.runtime.inspect_continuity(session_id=shell.session_id)
        provider = dict(shell.runtime.provider_summary())
        lines = shell._recent_activity_lines(session, continuity, provider)

        self.assertFalse(any("Release State Recovery" in line for line in lines))
        self.assertIn("latest · no captured grounded experience yet", lines)

    def test_growth_panel_filters_noisy_failure_experiences_from_learning_overview(self) -> None:
        shell = self._make_shell()
        now = datetime.now(timezone.utc)
        session = shell.runtime.inspect_session(shell.session_id)
        state = shell.runtime.ensure_elephant_state(session)
        shell.runtime.repository.upsert_record(
            Record(
                record_id="procedure:skill-manager-trouble",
                kind="derived",
                schema_version="personal_model.procedural_memory/v1",
                owner_scope="personal_model",
                personal_model_id=state.personal_model_id,
                state_id=state.state_id,
                layer_type="procedural_memory",
                created_at=now,
                payload={
                    "title": "It looks like the skill manager is having some trouble",
                    "summary": "It looks like the skill catalog is having some trouble. unknown skill source.",
                    "status": "active",
                    "maturity_state": "committed",
                    "approval_state": "approved",
                    "behavioral_state": "active",
                    "trigger_conditions": ("skill failure",),
                    "steps": ("Do not promote noisy failure text as useful operator guidance.",),
                },
            )
        )

        continuity = shell.runtime.inspect_continuity(session_id=shell.session_id)
        provider = dict(shell.runtime.provider_summary())
        lines = shell._recent_activity_lines(session, continuity, provider)

        self.assertFalse(any("skill manager is having some trouble" in line for line in lines))
        self.assertIn("latest · no captured grounded experience yet", lines)

    def test_conversational_surface_request_reads_specific_web_page_without_hitting_model(self) -> None:
        shell = self._make_shell()
        server = _WebPageStubServer().start()
        self.addCleanup(server.close)

        with mock.patch("apps.cli.shell_progress_runtime.animations_enabled", return_value=False):
            handled = shell._handle_conversational_surface_request(f"can you read {server.url}?")

        self.assertTrue(handled)
        self.assertEqual(shell.transcript[-1].kind, "assistant")
        self.assertIn("I opened that page", shell.transcript[-1].body)
        self.assertIn("Atlas Journal", shell.transcript[-1].body)
        self.assertIn("durable elephant continuity loop", shell.transcript[-1].body)
        self.assertIn(server.url.rstrip("/"), shell.transcript[-1].meta)

    def test_provider_configure_cancels_when_wizard_is_escaped(self) -> None:
        shell = self._make_shell()

        with mock.patch("apps.cli.shell.run_provider_selection_wizard", return_value=WIZARD_BACK), mock.patch.object(
            CliRuntime,
            "set_default_provider",
            autospec=True,
        ) as set_default_provider:
            shell._append_providers([])

        set_default_provider.assert_not_called()
        self.assertEqual(shell.transcript[-1].body, "Provider setup cancelled.")

    def test_models_configure_cancels_when_wizard_is_escaped(self) -> None:
        shell = self._make_shell()
        session = shell.runtime.inspect_session(shell.session_id)
        profile = shell.runtime.inspect_profile(session.personal_model_id)
        shell.runtime.set_default_provider(
            provider_id="openai-compatible",
            profile_id=profile.state.profile_id,
            display_name=profile.state.display_name,
            mode=profile.state.mode,
            base_url="https://api.example.test/v1",
            model_id="gpt-4o-mini",
            api_key="sk-test",
        )

        with mock.patch("apps.cli.shell.run_provider_selection_wizard", return_value=WIZARD_BACK), mock.patch.object(
            CliRuntime,
            "set_default_provider",
            autospec=True,
        ) as set_default_provider:
            shell._append_models([])

        set_default_provider.assert_not_called()
        self.assertEqual(shell.transcript[-1].body, "Model setup cancelled.")

    def test_work_surface_discloses_resolved_state_focus_scope_and_fallback(self) -> None:
        shell = self._make_shell()
        session = shell.runtime.inspect_session(shell.session_id)
        profile = shell.runtime.inspect_profile(session.personal_model_id)

        shell.runtime._write_snapshot(
            profile=profile.state,
            session=session,
            work_items=(),
            memories=shell.runtime.inspect_memories(shell.session_id),
            plan=None,
            execution=None,
            delivery=None,
            stages=(),
            event=None,
            elephant_identity_text=profile.elephant_identity_text,
            state_focus=StateFocusDecision(
                focus_family="resume",
                confidence=0.92,
                focus_work_item_ids=("state-focus:operator-rollout",),
                continuity_signal="continue",
                focus_scope="lineage",
                context_budget="narrow",
                embedding_available=False,
                degradation_mode="embedding-unavailable",
                needs_focus_model_assist=True,
                focus_assist_outcome="suggested",
                selection_path="embedding-unavailable.weak-assist.suggested.narrow",
                reasons=(
                    StateFocusReason("continuation", "The prompt continues the active rollout thread.", 0.9),
                    StateFocusReason("focus", "The active work stays ahead of generic recall.", 0.8),
                ),
                audit_trace=("stage3: fallback path -> embedding-unavailable.weak-assist.suggested.narrow",),
            ),
        )

        self.assertFalse(hasattr(shell, "_append_work"))
        self.assertFalse(shell._handle_slash_command("/work"))
        self.assertEqual(shell.transcript[-1].title, "Unknown command")

    def test_conversational_surface_requests_can_schedule_prompt_cron_and_list_jobs(self) -> None:
        shell = self._make_shell()

        created = shell._handle_conversational_surface_request("schedule a prompt to tell me a joke every morning")
        listed = shell._handle_conversational_surface_request("what cron jobs do you have?")

        self.assertTrue(created)
        self.assertTrue(listed)
        self.assertEqual(shell.transcript[-2].kind, "assistant")
        self.assertIn("I scheduled that prompt task", shell.transcript[-2].body)
        self.assertEqual(shell.transcript[-1].kind, "assistant")
        self.assertIn("scheduled jobs", shell.transcript[-1].body)
        self.assertIn("Prompt · tell me a joke", shell.transcript[-1].body)

    def test_due_cron_tick_appends_prompt_result_to_open_shell(self) -> None:
        shell = self._make_shell()
        shell.runtime.create_cron_job(
            session_id=shell.session_id,
            name="Timed hello",
            schedule="2000-01-01T00:00:00+00:00",
            payload={"prompt": "say hello from cron"},
        )

        self.assertTrue(shell.runtime.has_due_cron_jobs(session_id=shell.session_id))

        with mock.patch.object(
            type(shell.runtime),
            "explain_next_step",
            return_value=SimpleNamespace(execution=SimpleNamespace(summary="hello from cron")),
        ):
            shell._append_due_cron_jobs()

        self.assertEqual(shell.transcript[-1].kind, "assistant")
        self.assertEqual(shell.transcript[-1].body, "hello from cron")
        self.assertIn("cron", shell.transcript[-1].meta)
        self.assertFalse(shell.runtime.has_due_cron_jobs(session_id=shell.session_id))

    def test_prompt_cron_job_references_requested_skill_without_body_injection(self) -> None:
        shell = self._make_shell()
        skill = shell.runtime.inspect_skill("arxiv", session_id=shell.session_id)
        shell.runtime.create_cron_job(
            session_id=shell.session_id,
            name="Paper scan",
            schedule="2000-01-01T00:00:00+00:00",
            payload={"prompt": "find papers and write a markdown note", "skills": ["arxiv"]},
        )
        outcome = SimpleNamespace(execution=SimpleNamespace(summary="wrote paper note"))

        with mock.patch.object(type(shell.runtime), "inspect_skill", return_value=skill) as inspect_skill, mock.patch.object(
            type(shell.runtime),
            "explain_next_step",
            return_value=outcome,
        ) as explain:
            executions = shell.runtime.run_due_cron_jobs(session_id=shell.session_id)

        self.assertEqual(executions[0].summary, "wrote paper note")
        inspect_skill.assert_called_with("arxiv", session_id=shell.session_id)
        prompt = explain.call_args.kwargs["prompt"]
        self.assertIn("This turn is running as a scheduled Elephant Agent cron job", prompt)
        self.assertIn("do not call tool.message.send", prompt)
        self.assertIn("Skill: ", prompt)
        self.assertIn("Full skill body: not injected automatically.", prompt)
        self.assertNotIn(skill.instruction_text.strip().splitlines()[0], prompt)

    def test_sub_agents_tool_runs_bounded_runtime_task(self) -> None:
        shell = self._make_shell()
        captured: dict[str, str] = {}
        child_tool_runtime = SimpleNamespace(subscribe=mock.Mock(return_value=mock.Mock()))
        child_runtime = SimpleNamespace(
            tool_runtime=child_tool_runtime,
            prepare_session_surface=mock.Mock(),
            explain_next_step=mock.Mock(),
        )

        def explain_next_step(*, session_id: str, prompt: str):
            captured["session_id"] = session_id
            captured["prompt"] = prompt
            return SimpleNamespace(
                execution=ExecutionResult(
                    execution_id="exec:child",
                    episode_id=session_id,
                    outcome="success",
                    summary="sub-agent result",
                )
            )

        child_runtime.explain_next_step.side_effect = explain_next_step

        with mock.patch(
            "apps.cli.runtime_cron_sub_agents._create_child_runtime",
            return_value=child_runtime,
        ) as create_child_runtime:
            result = shell.runtime.tool_runtime.invoke(
                "tool.sub_agents",
                {"task": "inspect the cron implementation", "name": "reviewer", "skills": ["subagent-driven-development"]},
                session_id=shell.session_id,
                requester="model",
            )

        self.assertEqual(result.summary, "sub-agent result")
        create_child_runtime.assert_called_once_with(shell.runtime)
        child_session_id = captured["session_id"]
        self.assertNotEqual(child_session_id, shell.session_id)
        self.assertTrue(child_runtime.sub_agent_active)
        child_runtime.prepare_session_surface.assert_called_once_with(child_session_id)
        child_runtime.explain_next_step.assert_called_once()
        prompt = captured["prompt"]
        self.assertIn("bounded Elephant Agent sub-agent", prompt)
        self.assertIn("Do not call tool.sub_agents", prompt)
        self.assertIn("Sub-agent name: reviewer", prompt)

    def test_learning_sub_agent_uses_dedicated_system_prompt_without_generic_wrapper(self) -> None:
        shell = self._make_shell()
        captured: dict[str, object] = {}
        child_tool_runtime = SimpleNamespace(subscribe=mock.Mock(return_value=mock.Mock()), descriptor=SimpleNamespace())
        child_runtime = SimpleNamespace(
            tool_runtime=child_tool_runtime,
            model_provider=SimpleNamespace(tool_runtime=child_tool_runtime),
            prepare_session_surface=mock.Mock(),
            close=mock.Mock(),
        )

        def run_turn(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                execution=ExecutionResult(
                    execution_id="exec:learning-child",
                    episode_id=str(kwargs["session_id"]),
                    outcome="success",
                    summary="learning result written",
                )
            )

        child_runtime._run_turn = mock.Mock(side_effect=run_turn)
        with mock.patch("apps.cli.runtime_cron_sub_agents._create_child_runtime", return_value=child_runtime):
            result = shell.runtime.run_sub_agent(
                session_id=shell.session_id,
                task="Mode: manual\nLearning context packet: compact facts",
                name="Manual learning",
                allowed_tools=("tool.personal_model.search", "tool.personal_model.update"),
                system_prompt="[SYSTEM: Background Learning Agent]",
                learning_agent=True,
            )

        self.assertEqual(result["summary"], "learning result written")
        self.assertEqual(captured["prompt"], "Mode: manual\nLearning context packet: compact facts")
        event_payload = captured["event_payload"]
        self.assertIsInstance(event_payload, dict)
        self.assertEqual(event_payload["system_prompt"], "[SYSTEM: Background Learning Agent]")
        self.assertEqual(event_payload["context_mode"], "learning_agent")
        self.assertNotIn("bounded Elephant Agent sub-agent", str(captured["prompt"]))

    def test_sub_agents_start_returns_handle_and_emits_child_lifecycle_events(self) -> None:
        shell = self._make_shell()
        child_started = threading.Event()
        release_child = threading.Event()
        captured_events: list[ToolLifecycleEvent] = []

        def make_child_runtime(_runtime):
            child_tool_runtime = SimpleNamespace(subscribe=mock.Mock(return_value=mock.Mock()))
            child_runtime = SimpleNamespace(
                tool_runtime=child_tool_runtime,
                prepare_session_surface=mock.Mock(),
                close=mock.Mock(),
            )

            def explain_next_step(*, session_id: str, prompt: str):
                child_started.set()
                release_child.wait(timeout=5)
                return SimpleNamespace(
                    execution=ExecutionResult(
                        execution_id="exec:child-async",
                        episode_id=session_id,
                        outcome="success",
                        summary="async child result",
                    )
                )

            child_runtime.explain_next_step = mock.Mock(side_effect=explain_next_step)
            return child_runtime

        unsubscribe = shell.runtime.tool_runtime.subscribe(captured_events.append)
        try:
            with mock.patch(
                "apps.cli.runtime_cron_sub_agents._create_child_runtime",
                side_effect=make_child_runtime,
            ):
                started = shell.runtime.start_sub_agents(
                    session_id=shell.session_id,
                    tasks=(
                        {
                            "task": "inspect the async sub-agent implementation",
                            "name": "async-reviewer",
                            "skills": (),
                        },
                    ),
                    max_concurrency=1,
                )
                run_id = str(started["run_id"])

                self.assertEqual(started["status"], "running")
                self.assertTrue(child_started.wait(timeout=1))
                running = shell.runtime.inspect_sub_agent_run(session_id=shell.session_id, run_id=run_id)
                self.assertEqual(running["status"], "running")

                release_child.set()
                joined = shell.runtime.inspect_sub_agent_run(
                    session_id=shell.session_id,
                    run_id=run_id,
                    wait_timeout_seconds=5,
                )
        finally:
            unsubscribe()

        self.assertEqual(joined["status"], "completed")
        self.assertIn("async child result", joined["summary"])
        child_events = [
            event
            for event in captured_events
            if event.invocation.tool_id == "tool.sub_agents"
            and event.invocation.arguments.get("sub_agent_child")
        ]
        self.assertTrue(any(event.phase == "execution.started" for event in child_events))
        self.assertTrue(any(event.phase == "execution.completed" for event in child_events))

    def test_sub_agent_child_writes_single_structured_result(self) -> None:
        from apps.cli import sub_agent_child

        previous_sub_agent_flag = os.environ.get("ELEPHANT_SUB_AGENT_CHILD")
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / "prompt.txt"
            result_path = Path(tmpdir) / "result.json"
            prompt_path.write_text("delegated task", encoding="utf-8")
            execution = ExecutionResult(
                execution_id="exec:child",
                episode_id="session:child",
                outcome="completed",
                summary="child summary",
            )
            runtime = SimpleNamespace(
                prepare_session_surface=mock.Mock(),
                explain_next_step=mock.Mock(return_value=SimpleNamespace(execution=execution)),
            )

            with mock.patch("apps.cli.sub_agent_child.CliRuntime.create", return_value=runtime) as create:
                exit_code = sub_agent_child.main(
                    [
                        "--state-dir",
                        str(Path(tmpdir) / "state"),
                        "--profile-dir",
                        str(Path(tmpdir) / "profile"),
                        "--session-id",
                        "session:child",
                        "--prompt-file",
                        str(prompt_path),
                        "--result-file",
                        str(result_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            create.assert_called_once()
            runtime.prepare_session_surface.assert_called_once_with("session:child")
            runtime.explain_next_step.assert_called_once_with(session_id="session:child", prompt="delegated task")
            self.assertEqual(
                json.loads(result_path.read_text(encoding="utf-8")),
                {
                    "status": "completed",
                    "summary": "child summary",
                    "execution_id": "exec:child",
                    "session_id": "session:child",
                    "outcome": "completed",
                },
            )
            self.assertEqual(os.environ.get("ELEPHANT_SUB_AGENT_CHILD"), previous_sub_agent_flag)

    def test_tool_trace_emoji_covers_builtin_chat_tools(self) -> None:
        expected = {
            "tool.terminal.exec": "💻",
            "tool.process.manage": "🖥️",
            "tool.file.read": "📖",
            "tool.file.write": "✍️",
            "tool.file.patch": "🩹",
            "tool.file.search": "🔎",
            "tool.web.search": "🌐",
            "tool.web.read": "🌐",
            "tool.web.extract": "🌐",
            "tool.clarify": "❓",
            "tool.cron.manage": "⏰",
            "tool.personal_model.search": "🐘",
            "tool.personal_model.update": "🌱",
            "tool.personal_model.questions": "👂",
            "tool.code.execute": "🛠️",
            "tool.sub_agents": "🐘",
            "tool.skill.list": "🧩",
            "tool.skill.view": "🧩",
            "tool.skill.manage": "🧩",
            "tool.message.send": "📨",
            "tool.todo.manage": "📋",
        }
        for tool_id, emoji in expected.items():
            self.assertEqual(shell_progress_trace._tool_trace_emoji(tool_id), emoji)
        self.assertEqual(shell_progress_trace._tool_trace_emoji("mcp.km.hot-articles"), "🧩")

    def test_clarify_blocks_for_shell_input_and_returns_answer_as_tool_result(self) -> None:
        shell = self._make_shell()
        shell.runtime.set_clarify_surface(shell._interactive_clarify_surface())
        holder: dict[str, ExecutionResult] = {}

        def invoke_clarify() -> None:
            holder["result"] = shell.runtime.tool_runtime.invoke(
                "tool.clarify",
                {"question": "Which target?", "choices": ["alpha", "beta"]},
                session_id=shell.session_id,
            )

        thread = threading.Thread(target=invoke_clarify)
        thread.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if shell._clarify_state is not None:
                break
            time.sleep(0.01)
        self.assertIsNotNone(shell._clarify_state)

        self.assertTrue(route_clarify_answer(shell, "2"))
        thread.join(timeout=5)

        self.assertFalse(thread.is_alive())
        result = holder["result"]
        self.assertEqual(result.outcome, "success")
        self.assertIn("question: Which target?", result.summary)
        self.assertIn("user_response: beta", result.summary)
        self.assertIsNone(shell._clarify_state)

    def test_clarify_render_adds_title_emoji_and_hint_spacing(self) -> None:
        shell = self._make_shell()

        with shell._clarify_lock:
            shell._clarify_state = ShellClarifyState(
                question="Which target?",
                mode="choice",
                choices=("alpha", "beta"),
                response_queue=Queue(maxsize=1),
            )
        choice_plain = "".join(text for _style, text in render_clarify_fragments(shell))

        self.assertIn("Clarification needed 🤔", choice_plain)
        self.assertIn("Type a number or a custom answer, then press Enter.\n", choice_plain)
        self.assertTrue(choice_plain.endswith("Enter.\n"))

        with shell._clarify_lock:
            shell._clarify_state = ShellClarifyState(
                question="What should I do?",
                mode="open",
                choices=(),
                response_queue=Queue(maxsize=1),
            )
        open_plain = "".join(text for _style, text in render_clarify_fragments(shell))

        self.assertIn("Type your answer, then press Enter.\n", open_plain)
        self.assertTrue(open_plain.endswith("Enter.\n"))

    def test_assistant_render_strips_markdown_markers_from_plain_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_dir = root / "state"
            profile_dir = root / "profile"
            profile_dir.mkdir()
            (root / "profile.json").write_text(
                json.dumps(
                    {
                        "profile_id": "profile-companion",
                        "display_name": "Elephant Agent",
                        "mode": "companion",
                    }
                ),
                encoding="utf-8",
            )

            runtime = CliRuntime.create(state_dir=state_dir)
            runtime.update_identity_state(
                profile_id="profile-companion",
                elephant_identity_text="Stay durable.",
            )
            session = runtime.create_elephant(elephant_id="atlas")
            shell = ProductizedShell(runtime, session_id=session.session_id, opened="Shaped new")
            rendered = shell._render_entry(
                TranscriptEntry(
                    kind="assistant",
                    title="Elephant Agent",
                    body="You're the **Local Operator** in this session.",
                )
            )
            plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)
            self.assertIn("Local Operator", plain)
            self.assertNotIn("**", plain)

    def test_assistant_reasoning_heading_renders_without_leading_bullet(self) -> None:
        shell = self._make_shell()
        rendered = shell._render_entry(
            TranscriptEntry(
                kind="assistant",
                title="Elephant Agent",
                body="<think>Inspect memory state first.</think>The memory summary is ready.",
            )
        )

        plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)
        first_line = next((line for line in plain.splitlines() if line.strip()), "")

        self.assertEqual(first_line.strip(), "🐾 Elephant Agent's Trail:")
        self.assertNotIn("● 🐾 Elephant Agent's Trail:", plain)

    def test_prompt_style_keeps_live_composer_unboxed(self) -> None:
        shell = self._make_shell()
        style_map = shell._prompt_style_map()
        self.assertEqual(style_map[""], f"fg:{BRAND_LIGHT}")
        self.assertEqual(style_map["composer-divider"], f"fg:{BRAND_ACCENT}")
        self.assertEqual(style_map["composer-prefix"], f"fg:{BRAND_ACCENT_STRONG} bold")
        self.assertEqual(style_map["progress-meta"], f"fg:{BRAND_LIGHT}")
        self.assertEqual(style_map["progress-hint"], f"fg:{BRAND_LIGHT}")
        self.assertEqual(style_map["progress-active-marker"], f"fg:{BRAND_MUTED} bold")
        self.assertEqual(style_map["progress-active-detail"], f"fg:{BRAND_LIGHT}")
        self.assertEqual(style_map["progress-tool-rail"], f"fg:{BRAND_DARK}")
        self.assertEqual(style_map["progress-tool-label"], f"fg:{BRAND_ACCENT_STRONG} bold")
        self.assertEqual(style_map["stream-response-body"], f"fg:{BRAND_LIGHT}")
        self.assertEqual(style_map["status-bar-growth-empty"], f"bg:#1b2029 fg:{BRAND_ACCENT}")
        self.assertEqual(style_map["completion-menu.completion.current"], f"bg:#2a3343 fg:{BRAND_ACCENT_STRONG} bold")
        self.assertEqual(style_map["scrollbar.button"], f"bg:{BRAND_ACCENT}")
        self.assertNotIn("bg:", style_map[""])
        self.assertNotIn("bg:", style_map["composer-prefix"])
        self.assertNotIn("bottom-toolbar", style_map)

    def test_live_composer_body_wraps_running_surface_in_scrollable_pane(self) -> None:
        if ScrollablePane is None or StackWindow is None or StackFormattedTextControl is None:
            self.skipTest("prompt_toolkit scrollable pane is unavailable")
        shell = self._make_shell()
        input_window = StackWindow(StackFormattedTextControl("input"), height=1, dont_extend_height=True)
        command_palette = StackWindow(StackFormattedTextControl("palette"), height=1, dont_extend_height=True)
        progress_window = StackWindow(StackFormattedTextControl("trace"), dont_extend_height=True)

        body = build_composer_body(
            shell,
            input_window=input_window,
            command_palette=command_palette,
            top_windows=(progress_window,),
        )

        self.assertIsInstance(body, ScrollablePane)

    def test_command_palette_reserves_at_least_six_visible_rows(self) -> None:
        self.assertGreaterEqual(COMMAND_PALETTE_VISIBLE_ROWS, 6)

    def test_next_command_prefers_queued_followup_before_prompting(self) -> None:
        shell = self._make_shell()
        shell._pending_commands.append(PendingShellCommand(command="queued followup"))

        with mock.patch.object(shell, "_read_command", side_effect=AssertionError("should not prompt")):
            queued = shell._next_command()

        self.assertEqual(queued, PendingShellCommand(command="queued followup"))

    def test_enqueue_followup_command_does_not_preappend_transcript_entry(self) -> None:
        shell = self._make_shell()
        original_len = len(shell.transcript)

        shell._enqueue_followup_command("queued followup")

        self.assertEqual(len(shell.transcript), original_len)
        queued = shell._next_command()
        self.assertEqual(queued, PendingShellCommand(command="queued followup"))

    def test_queued_followup_enters_transcript_only_when_dispatched(self) -> None:
        shell = self._make_shell()
        shell._enqueue_followup_command("queued followup")

        with mock.patch.object(shell, "_handle_conversational_surface_request", return_value=True):
            shell._dispatch(shell._next_command().command)

        queued_entries = [
            entry
            for entry in shell.transcript
            if entry.kind == "user" and entry.body == "queued followup"
        ]
        self.assertEqual(len(queued_entries), 1)

    def test_queued_followup_fragments_stack_without_blank_lines(self) -> None:
        shell = self._make_shell()
        shell.console = _StubConsole(48)
        shell._enqueue_followup_command("who are you")
        shell._enqueue_followup_command("how are you")
        shell._enqueue_followup_command("hi")

        fragments = shell._render_queued_followup_fragments()
        lines = "".join(text for _style, text in fragments).splitlines()

        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0].strip(), "› who are you")
        self.assertEqual(lines[1].strip(), "› how are you")
        self.assertEqual(lines[2].strip(), "› hi")

    def test_queue_preview_rows_are_narrower_than_sent_user_rows(self) -> None:
        shell = self._make_shell()
        shell.console = _StubConsole(48)
        shell._enqueue_followup_command("queued followup")

        preview_lines = "".join(
            text for _style, text in shell._render_queued_followup_fragments()
        ).splitlines()
        sent = shell._render_entry(
            TranscriptEntry(
                kind="user",
                title="You",
                body="queued followup",
            )
        )
        sent_lines = (sent.plain if hasattr(sent, "plain") else str(sent)).splitlines()

        self.assertEqual(
            _display_width(preview_lines[0]),
            shell._history_row_width() - QUEUE_PREVIEW_INSET,
        )
        self.assertEqual(_display_width(sent_lines[0]), shell._history_row_width())

    def test_turn_progress_fragments_show_queued_followup_count(self) -> None:
        shell = self._make_shell()

        fragments = shell._render_turn_progress_fragments(
            prompt="draft the next release note",
            tick=0,
            queued_count=2,
        )

        rendered = "".join(text for _style, text in fragments)
        self.assertIn("Working", rendered)
        self.assertIn("queued scrolls · 2 messages", rendered)

    def test_turn_progress_fragments_drop_queue_scroll_hint_but_keep_spacing(self) -> None:
        shell = self._make_shell()

        fragments = shell._render_turn_progress_fragments(
            prompt="draft the next release note",
            tick=0,
        )

        rendered = "".join(text for _style, text in fragments)
        self.assertNotIn("Press Enter to queue another scroll.", rendered)
        self.assertTrue(rendered.endswith("\n"))

    def test_turn_progress_fragments_keep_live_tool_lines_on_separate_rows(self) -> None:
        shell = self._make_shell()
        shell._rendered_entries = len(shell.transcript)
        shell._append_tooltrace_line("┊ 📚 Calling skill…")
        shell._append_tooltrace_line("┊ 📚 skill        apple-notes  0.3s")

        fragments = shell._render_turn_progress_fragments(
            prompt="open notes",
            tick=0,
        )

        rendered = "".join(text for _style, text in fragments)
        self.assertIn("\n┊ 📚 Calling skill…", rendered)
        self.assertIn("\n┊ 📚 skill        apple-notes  0.3s", rendered)
        self.assertNotIn("skill…┊ 📚 skill", rendered)

    def test_turn_progress_fragments_surface_state_focus_resolution_summary(self) -> None:
        shell = self._make_shell()

        fragments = shell._render_turn_progress_fragments(
            prompt="draft the next release note",
            tick=0,
            kernel_stage_events=(
                {
                    "payload": {
                        "stage": "relationship",
                        "detail": "continuity_notes=1",
                        "recorded_at": "2026-04-17T08:00:00+00:00",
                    }
                },
                {
                    "payload": {
                        "stage": "state_focus",
                        "detail": (
                            "state_focus=exploration confidence=0.82 focus=work-release "
                            "scope=elephant degradation=none weak_assist=false "
                            "weak_outcome=not-requested fallback=none candidates=3"
                        ),
                        "recorded_at": "2026-04-17T08:00:00.035000+00:00",
                    }
                },
            ),
        )

        rendered = "".join(text for _style, text in fragments)
        self.assertIn("┊ 🧭 focus        exploration · 35ms · elephant · conf 0.82", rendered)

    def test_turn_progress_fragments_omit_context_and_request_progress_rows(self) -> None:
        shell = self._make_shell()

        fragments = shell._render_turn_progress_fragments(
            prompt="draft the next release note",
            tick=0,
            kernel_stage_events=(
                {
                    "payload": {
                        "stage": "context-projection",
                        "detail": "prompt_tokens=1800 token_budget=4096 source=generation",
                    }
                },
                {
                    "payload": {
                        "stage": "context-usage",
                        "detail": "prompt_tokens=720 completion_tokens=40 total_tokens=760",
                    }
                },
            ),
        )

        rendered = "".join(text for _style, text in fragments)

        self.assertNotIn("┊ 🧩 context", rendered)
        self.assertNotIn("┊ 📈 request", rendered)
        self.assertNotIn("provider running", rendered)

    def test_record_kernel_event_trace_appends_skill_disclosure_line(self) -> None:
        shell = self._make_shell()

        shell._record_kernel_event_trace(
            {
                "event_type": "skill.disclosed",
                "payload": {
                    "skill_id": "skill.research.web",
                    "display_name": "Web research skill",
                    "disclosure_kind": "state-focus.overlay",
                },
            }
        )

        tool_entries = [entry for entry in shell.transcript if entry.kind == "tooltrace"]
        self.assertEqual(len(tool_entries), 1)
        self.assertIn(
            "┊ 📚 disclosed    Web research skill (skill.research.web) · state-focus.overlay",
            tool_entries[0].body,
        )

    def test_record_kernel_event_trace_omits_recall_tooltrace_rows(self) -> None:
        shell = self._make_shell()

        shell._record_kernel_event_trace(
            {
                "event_type": "kernel.stage",
                "payload": {
                    "stage": "recall",
                    "detail": "status=miss count=0 bytes=0",
                    "recorded_at": "2026-04-17T08:00:00+00:00",
                },
            }
        )

        self.assertFalse([entry for entry in shell.transcript if entry.kind == "tooltrace"])

    def test_record_kernel_event_trace_updates_context_projection_after_compaction(self) -> None:
        shell = self._make_shell()
        shell._last_prompt_tokens = 1800

        shell._record_kernel_event_trace(
            {
                "event_type": "kernel.stage",
                "payload": {
                    "stage": "context-compact",
                    "detail": (
                        "reason=preflight tokens=1800->620 messages=80->12 "
                        "compacted_messages=68 tail=10 semantic_cached=2 semantic_pending=5 semantic_missed=1"
                    ),
                    "recorded_at": "2026-04-17T08:00:00+00:00",
                },
            }
        )

        self.assertEqual(shell._last_prompt_tokens, 620)
        tool_entries = [entry for entry in shell.transcript if entry.kind == "tooltrace"]
        self.assertEqual(len(tool_entries), 1)
        self.assertIn("┊ 🧩 context      projection compact · est 1800->620 tokens · preflight", tool_entries[0].body)
        self.assertIn("scanner: 2 cached / 5 pending / 1 missed", tool_entries[0].body)

    def test_record_kernel_event_trace_uses_provider_prompt_usage_for_status_bar(self) -> None:
        shell = self._make_shell()
        shell._last_prompt_tokens = 1800

        shell._record_kernel_event_trace(
            {
                "event_type": "kernel.stage",
                "payload": {
                    "stage": "context-usage",
                    "detail": "prompt_tokens=720 completion_tokens=40 total_tokens=760",
                    "recorded_at": "2026-04-17T08:00:00+00:00",
                },
            }
        )

        self.assertEqual(shell._last_prompt_tokens, 1800)
        self.assertEqual(shell._last_provider_prompt_tokens, 720)
        self.assertFalse([entry for entry in shell.transcript if entry.kind == "tooltrace"])

    def test_record_kernel_event_trace_tracks_latest_context_projection_status(self) -> None:
        shell = self._make_shell()
        shell._last_prompt_tokens = 1800

        for prompt_tokens in (2400, 720):
            shell._record_kernel_event_trace(
                {
                    "event_type": "kernel.stage",
                    "payload": {
                        "stage": "context-projection",
                        "detail": f"prompt_tokens={prompt_tokens} token_budget=4096 source=generation",
                        "recorded_at": "2026-04-17T08:00:00+00:00",
                    },
                }
            )

        self.assertEqual(shell._last_prompt_tokens, 720)
        self.assertEqual(shell._last_provider_prompt_tokens, 0)
        self.assertFalse([entry for entry in shell.transcript if entry.kind == "tooltrace"])

    def test_user_history_rows_expand_to_console_width(self) -> None:
        shell = self._make_shell()
        shell.console = _StubConsole(48)
        padded_prompt = shell._pad_history_line("› hello from wake shell")
        padded_meta = shell._pad_history_line("  sent just now")
        self.assertEqual(_display_width(padded_prompt), shell._history_row_width())
        self.assertEqual(_display_width(padded_meta), shell._history_row_width())
        rendered = shell._render_entry(
            TranscriptEntry(
                kind="user",
                title="You",
                body="hello from wake shell",
                meta="sent just now",
            )
        )
        plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)
        lines = plain.splitlines()
        self.assertEqual(len(lines), 2)
        if RICH_AVAILABLE:
            self.assertEqual(lines[0], padded_prompt)
            self.assertEqual(lines[1], padded_meta)
        else:
            self.assertEqual(lines[0], "hello from wake shell")
            self.assertEqual(lines[1], "sent just now")

    def test_growth_rows_use_gray_history_background_with_selective_yellow_text(self) -> None:
        shell = self._make_shell()
        shell.console = _StubConsole(48)
        rendered = shell._render_entry(
            TranscriptEntry(
                kind="growth",
                title="Elephant Agent",
                body="Something settled into memory — checkpoint 1 in Memory I. I'll carry it forward.",
                meta="memory · checkpoint",
            )
        )
        plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)
        lines = plain.splitlines()
        self.assertEqual(len(lines), 2)
        if RICH_AVAILABLE:
            self.assertEqual(
                lines[0],
                shell._pad_history_line(
                    "› Something settled into memory — checkpoint 1 in Memory I. I'll carry it forward."
                ),
            )
            self.assertEqual(lines[1], shell._pad_history_line("  memory · checkpoint"))
            styles = {str(span.style) for span in rendered.spans}
            self.assertIn(f"{USER_HISTORY_FG} on {USER_HISTORY_BG}", styles)
            self.assertIn(f"{BRAND_MUTED} on {USER_HISTORY_BG}", styles)
            self.assertIn(f"{GROWTH_HIGHLIGHT_FG} on {USER_HISTORY_BG}", styles)
        else:
            self.assertEqual(lines[0], "Something settled into memory — checkpoint 1 in Memory I. I'll carry it forward.")
            self.assertEqual(lines[1], "memory · checkpoint")

    def test_composer_divider_tracks_console_width_without_old_cap(self) -> None:
        shell = self._make_shell()
        shell.console = _StubConsole(140)
        divider = shell._composer_divider()
        self.assertEqual(len(divider), 139)
        self.assertGreater(len(divider), 116)

    def test_growth_stage_rows_use_one_current_elephant_logo(self) -> None:
        self.assertIs(SEED_STAGE_ROWS, ELEPHANT_STAGE_ROWS)
        self.assertIs(HATCHLING_STAGE_ROWS, ELEPHANT_STAGE_ROWS)
        self.assertIs(SCOUT_STAGE_ROWS, ELEPHANT_STAGE_ROWS)
        self.assertEqual(HATCHLING_HEAD_ROWS, ELEPHANT_STAGE_ROWS[: len(HATCHLING_HEAD_ROWS)])

    def test_growth_stage_rows_fit_canonical_canvas(self) -> None:
        stage_rows = (
            ELEPHANT_STAGE_ROWS,
            SEED_STAGE_ROWS,
            HATCHLING_STAGE_ROWS,
            SCOUT_STAGE_ROWS,
            ELEPHANT_STAGE_ROWS,
        )
        for rows in stage_rows:
            self.assertLessEqual(max(len(row) for row in rows), GROWTH_MARK_CANVAS_WIDTH)
            self.assertTrue(all(row.strip() for row in rows))

    def test_elephant_stage_rows_keep_ascii_side_profile_readable(self) -> None:
        self.assertEqual(
            ELEPHANT_STAGE_ROWS,
            (
                "        /  \\~~~/  \\",
                "      (     ..    )---.",
                "       \\__     __/    \\",
                "        )|  /)         |",
                "       / | / /~~~\\    /",
                "      '-'-'     `---'",
            ),
        )

    def test_elephant_rows_match_current_ascii_logo(self) -> None:
        joined = "\n".join(ELEPHANT_STAGE_ROWS)
        self.assertIn("/  \\~~~/  \\", joined, msg="ear and head line should survive terminal rendering")
        self.assertIn("..", joined, msg="eye dots should survive terminal rendering")
        self.assertIn("`---'", joined, msg="body tail line should survive terminal rendering")
        centered_rows = _centered_elephant_rows()
        self.assertEqual(centered_rows, ELEPHANT_STAGE_ROWS)
        self.assertTrue(centered_rows[0].strip())
        self.assertTrue(centered_rows[1].strip())
        self.assertEqual(centered_rows[-1].strip(), ELEPHANT_STAGE_ROWS[-1].strip())

    def test_elephant_mark_renders_full_centered_stage(self) -> None:
        shell = self._make_shell()
        rendered = shell._render_elephant_mark()
        if not RICH_AVAILABLE:
            plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)
            self.assertEqual(plain, "[Elephant Agent elephant]")
            return
        plain_lines = rendered.plain.splitlines()
        self.assertEqual(len(plain_lines), len(ELEPHANT_STAGE_ROWS))
        self.assertEqual(tuple(plain_lines), ELEPHANT_STAGE_ROWS)
        self.assertTrue(rendered.plain.strip())
        self.assertIn("/  \\~~~/  \\", rendered.plain)
        styles = {str(span.style) for span in rendered.spans}
        self.assertEqual(str(rendered.style), BRAND_LIGHT)
        self.assertFalse(styles)

    def test_elephant_rows_keep_sticker_optically_centered(self) -> None:
        centered = _centered_elephant_rows()
        self.assertEqual(centered, ELEPHANT_STAGE_ROWS)
        visible = [
            index
            for row in centered
            for index, cell in enumerate(row)
            if cell != " "
        ]
        self.assertTrue(visible)

    def test_growth_levels_reuse_unified_elephant_mark(self) -> None:
        shell = self._make_shell()
        elephant = shell._render_growth_mark("seed", level=0)
        seed = shell._render_growth_mark("seed", level=1)
        if not RICH_AVAILABLE:
            self.assertEqual(elephant.plain if hasattr(elephant, "plain") else str(elephant), "[Elephant Agent elephant]")
            self.assertEqual(seed.plain if hasattr(seed, "plain") else str(seed), "[Elephant Agent seed]")
            return
        elephant_lines = elephant.plain.splitlines()
        seed_lines = seed.plain.splitlines()
        self.assertEqual(elephant.plain, seed.plain)
        self.assertEqual(tuple(elephant_lines), ELEPHANT_STAGE_ROWS)
        self.assertEqual(tuple(seed_lines), ELEPHANT_STAGE_ROWS)

    def test_shell_frame_centers_elephant_mark_without_brand_column_drift(self) -> None:
        if not RICH_AVAILABLE:
            self.skipTest("rich is required for shell frame rendering")
        shell = self._make_shell()
        console = Console(width=120, record=True, force_terminal=True)
        console.print(shell._render_shell_frame())
        exported_lines = console.export_text(styles=False).splitlines()
        for row in ELEPHANT_STAGE_ROWS:
            self.assertTrue(any(row.strip() in line for line in exported_lines), msg=row)

    def test_growth_stage_rows_center_visible_pixels(self) -> None:
        for label, rows in (
            ("elephant", ELEPHANT_STAGE_ROWS),
            ("seed", SEED_STAGE_ROWS),
            ("elephant", HATCHLING_STAGE_ROWS),
            ("scout", SCOUT_STAGE_ROWS),
            ("elephant", HATCHLING_STAGE_ROWS),
        ):
            centered = visual_centered_rows(rows, width=GROWTH_MARK_CANVAS_WIDTH)
            self.assertEqual({len(row) for row in centered}, {GROWTH_MARK_CANVAS_WIDTH})
            visible = [
                index
                for row in centered
                for index, cell in enumerate(row)
                if cell != " "
            ]
            self.assertTrue(visible, msg=label)
            visible_center = (min(visible) + max(visible)) / 2
            canvas_center = (GROWTH_MARK_CANVAS_WIDTH - 1) / 2
            self.assertLessEqual(abs(visible_center - canvas_center), 0.5, msg=label)

    def test_shell_frame_uses_your_own_elephant_branding(self) -> None:
        shell = self._make_shell()
        frame = shell._render_shell_frame()
        self.assertIn("Elephant Agent", str(getattr(frame, "title", "")))
        self.assertIn(
            "Personal Model first · curious at your pace",
            str(getattr(frame, "subtitle", "")),
        )

    def test_shell_frame_banner_uses_personal_model_readiness_sections(self) -> None:
        shell = self._make_shell()
        frame = shell._render_shell_frame()
        if RICH_AVAILABLE:
            console = Console(width=120, record=True, force_terminal=True)
            console.print(frame)
            rendered = console.export_text(styles=False)
        else:
            rendered = str(getattr(frame, "renderable", ""))
        self.assertIn("Ready for this chat", rendered)
        self.assertIn("What I know", rendered)
        self.assertIn("Skills for you", rendered)
        self.assertNotIn("What matters now", rendered)
        self.assertNotIn("This Episode", rendered)
        self.assertNotIn("Start with the person", rendered)
        self.assertNotIn("What Elephant Agent is carrying forward", rendered)
        self.assertNotIn("Recent activity", rendered)
        self.assertNotIn("Support style", rendered)
        self.assertNotIn("Next best context", rendered)
        self.assertNotIn("grounding ·", rendered)

    def test_shell_frame_banner_summarizes_pm_lenses_and_curiosity(self) -> None:
        shell = self._make_shell()
        session = shell.runtime.inspect_session(shell.session_id)
        now = datetime.now(timezone.utc)
        shell.runtime.repository.upsert_personal_model_fact(
            Fact(
                fact_id="fact:identity:style",
                personal_model_id=session.personal_model_id,
                lens="identity",
                text="Prefers direct technical review.",
                confidence=0.9,
                committed_at=now,
                source="user_explicit",
                metadata={"topic": "identity.style.review"},
            )
        )
        shell.runtime.repository.upsert_personal_model_fact(
            Fact(
                fact_id="fact:world:project",
                personal_model_id=session.personal_model_id,
                lens="world",
                text="Currently building durable agent systems.",
                confidence=0.9,
                committed_at=now,
                source="user_explicit",
                metadata={"topic": "world.projects.aegis"},
            )
        )
        shell.runtime.repository.upsert_personal_model_fact(
            Fact(
                fact_id="fact:world:skill:diagram",
                personal_model_id=session.personal_model_id,
                lens="world",
                text="Architecture diagrams are useful for this user.",
                confidence=0.9,
                committed_at=now,
                source="user_explicit",
                metadata={
                    "topic": "world.skills.affinity.architecture_diagram",
                    "skill_id": "architecture-diagram",
                    "projection_policy": "skill_shelf_candidate",
                },
            )
        )
        shell.runtime.repository.upsert_open_question(
            OpenQuestion(
                question_id="question:pulse:focus",
                personal_model_id=session.personal_model_id,
                lens="pulse",
                sub_lens="current_focus",
                text="What should I treat as the current highest-priority thread?",
                rationale="Current focus would improve future help.",
                priority=0.8,
                sensitivity="low",
                source="contextual",
                created_at=now,
            )
        )
        continuity = shell.runtime.inspect_continuity(session_id=shell.session_id)
        context_frame = shell.runtime.inspect_context_frame(session.episode_id)
        provider = dict(shell.runtime.provider_summary())
        growth = shell.runtime.inspect_growth(session_id=shell.session_id)

        rendered = shell._render_status_column(session, continuity, context_frame, provider, growth)
        plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)

        self.assertIn("🐘 What I know", plain)
        self.assertIn("saved · identity 1 · world 2 · 2 lens empty", plain)
        self.assertIn("question (pulse · current_focus) · What should I treat as the current highest-priority thread?", plain)
        self.assertIn("🧩 Skills for you", plain)
        self.assertIn("affinities · 1 learned · 1 active", plain)
        self.assertNotIn("affinities · Architecture Diagram", plain)
        self.assertIn("active ·", plain)
        self.assertIn("built-in", plain)
        self.assertIn("discover ·", plain)
        self.assertNotIn("Building durable agent systems.", plain)
        self.assertNotIn("proof-backed", plain)

    def test_skill_affinities_report_metrics_without_skill_names(self) -> None:
        now = datetime.now(timezone.utc)
        summary = _skill_affinity_summary(
            facts=(
                Fact(
                    fact_id="fact:world:skill:workflow",
                    personal_model_id="you",
                    lens="world",
                    text="Workflow automation fits the user's repeated work.",
                    confidence=0.83,
                    committed_at=now,
                    source="user_explicit",
                    metadata={
                        "topic": "world.skills.affinity.workflow_automation",
                        "skill_id": "workflow-automation",
                        "projection_policy": "skill_shelf_candidate",
                    },
                ),
            ),
        )

        self.assertEqual(summary, "1 learned · 1 active")

    def test_skill_affinities_follow_dashboard_topic_detection_without_projection_filter(self) -> None:
        now = datetime.now(timezone.utc)
        summary = _skill_affinity_summary(
            facts=(
                Fact(
                    fact_id="fact:world:skill:paper",
                    personal_model_id="you",
                    lens="world",
                    text="Paper workflow skills match the user's research process.",
                    confidence=0.8,
                    committed_at=now,
                    source="user_explicit",
                    metadata={
                        "topic": "world.skills.affinity.paper_workflow",
                        "skill_id": "paper-workflow",
                        "projection_policy": "dashboard-only",
                    },
                ),
            ),
        )

        self.assertEqual(summary, "1 learned · 1 active")

    def test_learning_job_execution_summary_counts_executed_jobs(self) -> None:
        runtime = SimpleNamespace(
            repository=SimpleNamespace(
                list_learning_jobs=lambda personal_model_id: (
                    SimpleNamespace(status="queued", started_at=None, finished_at=None),
                    SimpleNamespace(status="completed", started_at=object(), finished_at=object()),
                    SimpleNamespace(status="failed", started_at=object(), finished_at=object()),
                )
            )
        )

        self.assertEqual(_learning_job_execution_summary(runtime, "you"), "2 run(s) · 1 completed · 1 failed")

    def test_shell_frame_surfaces_user_facing_context_summary(self) -> None:
        shell = self._make_shell()
        frame = shell._render_shell_frame()
        if RICH_AVAILABLE:
            console = Console(width=120, record=True, force_terminal=True)
            console.print(frame)
            rendered = console.export_text(styles=False)
        else:
            rendered = str(getattr(frame, "renderable", ""))

        self.assertIn("Ready for this chat", rendered)
        self.assertIn("What I know", rendered)
        self.assertIn("Skills for you", rendered)
        self.assertIn("saved · No saved user notes yet.", rendered)
        self.assertNotIn("grounding ·", rendered)
        self.assertNotIn("proof-backed", rendered)
        self.assertNotIn("This Episode", rendered)
        self.assertNotIn("focus right now ·", rendered)
        self.assertNotIn("why this context ·", rendered)
        self.assertNotIn("What this wake will carry in", rendered)
        self.assertNotIn("SessionFrame", rendered)
        self.assertNotIn("assistant_display_name:", rendered)
        self.assertNotIn("opening_profile_gap:", rendered)
        self.assertNotIn("current_work_summary:", rendered)

    def test_shell_frame_filters_opening_prompt_like_state_text(self) -> None:
        shell = self._make_shell()
        session = shell.runtime.inspect_session(shell.session_id)
        state = shell.runtime.ensure_elephant_state(session)
        shell.runtime.repository.upsert_state(
            replace(
                state,
                summary="Open the wake surface proactively before the user sends a new message. assistant_display_name: Miles current_work_summary: Ship the release.",
                active_task="",
                next_step="",
            )
        )

        frame = shell._render_shell_frame()
        if RICH_AVAILABLE:
            console = Console(width=120, record=True, force_terminal=True)
            console.print(frame)
            rendered = console.export_text(styles=False)
        else:
            rendered = str(getattr(frame, "renderable", ""))

        self.assertIn("now · Ready to pick the thread back up when you are.", rendered)
        self.assertNotIn("assistant_display_name:", rendered)
        self.assertNotIn("Open the wake surface proactively before the user sends a new message.", rendered)

    def test_status_column_renders_carrying_forward_with_bold_label_and_markdown_value(self) -> None:
        shell = self._make_shell()
        session = shell.runtime.inspect_session(shell.session_id)
        continuity = shell.runtime.inspect_continuity(session_id=shell.session_id)
        context_frame = shell.runtime.inspect_context_frame(session.episode_id)
        provider = dict(shell.runtime.provider_summary())
        growth = shell.runtime.inspect_growth(session_id=shell.session_id)
        state = shell.runtime.ensure_elephant_state(session)
        shell.runtime.repository.upsert_state(
            replace(
                state,
                current_context_note="**Ship the release**",
                summary="",
            )
        )

        rendered = shell._render_status_column(session, continuity, context_frame, provider, growth)
        plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)

        self.assertIn("✨ Ready for this chat", plain)
        self.assertIn("now · Ship the release", plain)
        self.assertNotIn("next step ·", plain)
        self.assertNotIn("**", plain)
        if RICH_AVAILABLE:
            styles = {str(span.style) for span in rendered.spans}
            self.assertIn(f"bold {shell_render.BRAND_ACCENT}", styles)
            self.assertIn(f"bold {shell_render.BRAND_LIGHT}", styles)

    def test_status_column_compacts_long_markdown_state_into_summary(self) -> None:
        shell = self._make_shell()
        session = shell.runtime.inspect_session(shell.session_id)
        continuity = shell.runtime.inspect_continuity(session_id=shell.session_id)
        context_frame = shell.runtime.inspect_context_frame(session.episode_id)
        provider = dict(shell.runtime.provider_summary())
        growth = shell.runtime.inspect_growth(session_id=shell.session_id)
        state = shell.runtime.ensure_elephant_state(session)
        shell.runtime.repository.upsert_state(
            replace(
                state,
                active_task="",
                summary=(
                    "当然可以。下面是我目前对你的了解。\n\n"
                    "# 已知信息\n"
                    "| 字段 | 内容 |\n"
                    "| --- | --- |\n"
                    "| name | Xunzhuo |\n"
                    "| city | Chengdu |\n"
                    "后面这整段历史内容不应该原样出现在 banner 里。"
                ),
                next_step="整理成更短的摘要\n并保留必要信息",
            )
        )

        rendered = shell._render_status_column(session, continuity, context_frame, provider, growth)
        plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)

        self.assertIn("now · 当然可以。下面是我目前对你的了解。", plain)
        self.assertNotIn("next step ·", plain)
        self.assertNotIn("# 已知信息", plain)
        self.assertNotIn("| 字段 | 内容 |", plain)
        self.assertNotIn("后面这整段历史内容不应该原样出现在 banner 里。", plain)

    def test_shell_frame_surfaces_frozen_session_focus_and_counts(self) -> None:
        shell = self._make_shell()
        session = shell.runtime.inspect_session(shell.session_id)
        profile = shell.runtime._load_profile(session.personal_model_id)
        shell.runtime._write_snapshot(
            profile=profile.state,
            session=session,
            work_items=(),
            memories=(),
            plan=None,
            execution=ExecutionResult(
                execution_id="exec:first",
                episode_id=session.session_id,
                outcome="ok",
                summary="first reply",
            ),
            delivery=None,
            stages=(),
            event=EventEnvelope(
                event_id="event:first",
                event_type="turn.received",
                episode_id=session.session_id,
                source="cli",
                payload={"message": "first ask"},
            ),
            elephant_identity_text=profile.elephant_identity_text,
            state_focus=None,
            context=ContextBundle(
                bundle_id="bundle:first",
                episode_id=session.session_id,
                prompt_envelope=PromptEnvelope(
                    frozen_prefix="FIRST PREFIX",
                    session_snapshot="FIRST SNAPSHOT",
                    loop_context="FIRST INJECTIONS",
                ),
            ),
        )

        frame = shell._render_shell_frame()
        if RICH_AVAILABLE:
            console = Console(width=120, record=True, force_terminal=True)
            console.print(frame)
            rendered = console.export_text(styles=False)
        else:
            rendered = str(getattr(frame, "renderable", ""))

        self.assertIn("saved · No saved user notes yet.", rendered)
        self.assertNotIn("No durable elephant focus is available yet.", rendered)
        self.assertNotIn("grounding ·", rendered)
        self.assertNotIn("proof-backed", rendered)
        self.assertNotIn("focus right now ·", rendered)
        self.assertNotIn("why this context ·", rendered)

    def test_frozen_slash_command_surfaces_only_initial_frozen_sections(self) -> None:
        shell = self._make_shell()
        session = shell.runtime.inspect_session(shell.session_id)
        profile = shell.runtime._load_profile(session.personal_model_id)
        shell.runtime._write_snapshot(
            profile=profile.state,
            session=session,
            work_items=(),
            memories=(),
            plan=None,
            execution=ExecutionResult(
                execution_id="exec:first",
                episode_id=session.session_id,
                outcome="ok",
                summary="first reply",
            ),
            delivery=None,
            stages=(),
            event=EventEnvelope(
                event_id="event:first",
                event_type="turn.received",
                episode_id=session.session_id,
                source="cli",
                payload={"message": "first ask"},
            ),
            elephant_identity_text=profile.elephant_identity_text,
            state_focus=None,
            context=ContextBundle(
                bundle_id="bundle:first",
                episode_id=session.session_id,
                prompt_envelope=PromptEnvelope(
                    frozen_prefix="FIRST PREFIX",
                    session_snapshot="FIRST SNAPSHOT",
                    loop_context="FIRST INJECTIONS",
                ),
            ),
        )
        shell.runtime._write_snapshot(
            profile=profile.state,
            session=session,
            work_items=(),
            memories=(),
            plan=None,
            execution=ExecutionResult(
                execution_id="exec:second",
                episode_id=session.session_id,
                outcome="ok",
                summary="second reply",
            ),
            delivery=None,
            stages=(),
            event=EventEnvelope(
                event_id="event:second",
                event_type="turn.received",
                episode_id=session.session_id,
                source="cli",
                payload={"message": "second ask"},
            ),
            elephant_identity_text=profile.elephant_identity_text,
            state_focus=None,
            context=ContextBundle(
                bundle_id="bundle:second",
                episode_id=session.session_id,
                prompt_envelope=PromptEnvelope(
                    frozen_prefix="SECOND PREFIX",
                    session_snapshot="SECOND SNAPSHOT",
                    loop_context="SECOND INJECTIONS",
                ),
            ),
        )

        handled = shell._handle_slash_command("/frozen")

        self.assertFalse(handled)
        self.assertEqual(shell.transcript[-1].title, "Unknown command")
        self.assertIn("/frozen", shell.transcript[-1].body)
        self.assertNotIn("system prompt (tool fallback) :: tool_schema", shell.transcript[-1].body)
        self.assertNotIn("FIRST TOOLS", shell.transcript[-1].body)
        self.assertIn("help: /help", shell.transcript[-1].body)
        self.assertNotIn("frozen_skill_index:", shell.transcript[-1].body)
        self.assertNotIn("SECOND PREFIX", shell.transcript[-1].body)
        self.assertNotIn("user: first ask", shell.transcript[-1].body)

    def test_settled_state_focus_meta_stays_muted_in_transcript(self) -> None:
        shell = self._make_shell()
        rendered = shell._render_entry(
            TranscriptEntry(
                kind="assistant",
                title="Elephant Agent",
                body="reply",
                meta="routing · resume · 56ms · lineage · 0.94",
            )
        )

        self.assertIn("routing · resume · 56ms · lineage · 0.94", rendered.plain if hasattr(rendered, "plain") else str(rendered))

    def test_live_state_focus_progress_uses_steady_orange_trace_style(self) -> None:
        text = shell_progress_trace.render_tool_trace_text("┊ 🧭 routing      resume · 56ms · lineage · 0.94")

        self.assertEqual(text.spans[0].style, shell_render.BRAND_ACCENT_STRONG)

    def test_growth_panel_reports_enabled_and_self_learned_skill_counts_without_internal_next_move(self) -> None:
        shell = self._make_shell()
        shell.runtime.create_experience_skill(
            skill_id="self-learned-shell-fix",
            display_name="Self Learned Shell Fix",
            summary="Recover shell work after a failed command.",
            instruction_text="Inspect stderr, retry carefully, and summarize the durable fix.",
            session_id=shell.session_id,
        )

        session = shell.runtime.inspect_session(shell.session_id)
        continuity = shell.runtime.inspect_continuity(session_id=shell.session_id)
        provider = dict(shell.runtime.provider_summary())
        lines = shell._recent_activity_lines(session, continuity, provider)
        enabled_skills = tuple(skill for skill in shell.runtime.skill_catalog(session_id=shell.session_id) if skill.enabled)

        self.assertIn(f"skills · {len(enabled_skills)} enabled · 1 self-learned", lines)
        self.assertFalse(any(line.startswith("next move ·") for line in lines))
        self.assertFalse(any(line.startswith("focus ·") for line in lines))
        self.assertFalse(any(line.startswith("grounding ·") for line in lines))

    def test_growth_progress_bar_uses_glyph_bar_and_orange_fill(self) -> None:
        shell = self._make_shell()
        growth = type("GrowthProbe", (), {"progress_ratio": 0.40, "progress_percent": 40})()

        bar = shell._growth_progress_bar(growth)
        self.assertEqual(
            bar,
            (GROWTH_PROGRESS_FILLED * 6) + (GROWTH_PROGRESS_EMPTY * (GROWTH_PROGRESS_WIDTH - 6)),
        )

        styled = shell._styled_growth_progress_bar(growth)
        self.assertEqual(styled.plain, bar)
        if RICH_AVAILABLE:
            styles = [span.style for span in styled.spans]
            self.assertIn(BRAND_ACCENT_STRONG, styles)
            self.assertIn(BRAND_MUTED, styles)

    def test_diff_styles_use_brighter_live_palette_and_dimmer_settled_palette(self) -> None:
        style_map = prompt_style_map()

        self.assertEqual(style_map["progress-output-file"], f"fg:{LIVE_DIFF_FILE_FG} bold")
        self.assertEqual(style_map["progress-output-hunk"], f"fg:{LIVE_DIFF_HUNK_FG} bold")
        self.assertEqual(style_map["progress-output-add"], f"fg:{LIVE_DIFF_ADD_FG} bold")
        self.assertEqual(style_map["progress-output-remove"], f"fg:{LIVE_DIFF_REMOVE_FG} bold")
        self.assertEqual(_render_tooltrace_body_line("a/notes.md → b/notes.md").style, SETTLED_DIFF_FILE_FG)
        self.assertEqual(_render_tooltrace_body_line("@@ -1 +1 @@").style, SETTLED_DIFF_HUNK_FG)
        self.assertEqual(_render_tooltrace_body_line("+added").style, SETTLED_DIFF_ADD_FG)
        self.assertEqual(_render_tooltrace_body_line("-removed").style, SETTLED_DIFF_REMOVE_FG)

    def test_status_bar_fragments_include_checkpoint_and_growth_progress(self) -> None:
        shell = self._make_shell()
        session = shell.runtime.inspect_session(shell.session_id)
        update = apply_turn_growth(
            default_growth_state(session.personal_model_id),
            GrowthTurnSignals(
                session_id=shell.session_id,
                profile_id=session.personal_model_id,
                total_tokens=320,
            ),
        )
        shell.runtime.repository.upsert_personal_model_growth(update.after.state)
        shell._last_prompt_tokens = 12_800
        shell._last_turn_elapsed_seconds = 12

        fragments = shell._status_bar_fragments()
        rendered = "".join(text for _style, text in fragments)

        self.assertIn("12s", rendered)
        self.assertIn("Memory I", rendered)
        self.assertIn(shell._build_context_bar(update.after.progress_percent), rendered)
        self.assertIn(f"checkpoint {update.after.level} · {update.after.progress_percent}%", rendered)

        styles = {style for style, _text in fragments if style}
        self.assertIn("class:status-bar-level", styles)
        self.assertIn("class:status-bar-growth-bracket", styles)
        self.assertIn("class:status-bar-growth-fill", styles)
        self.assertIn("class:status-bar-growth-empty", styles)

    def test_status_bar_stream_phase_reads_as_following_with_path_dots(self) -> None:
        shell = self._make_shell()
        shell._streaming_response_active = True

        fragments = shell._status_bar_fragments()
        rendered = "".join(text for _style, text in fragments)

        self.assertIn("following", rendered)
        self.assertNotIn("replying", rendered)
        self.assertTrue(any(frame in rendered for frame in ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")))
        self.assertFalse(any(frame in rendered for frame in ("▁", "▃", "▅", "▇")))

    def test_status_bar_think_phase_reads_as_orienting_with_reply_pulse(self) -> None:
        shell = self._make_shell()
        shell._turn_started_at = time.monotonic()

        fragments = shell._status_bar_fragments()
        rendered = "".join(text for _style, text in fragments)

        self.assertIn("orienting", rendered)
        self.assertNotIn("thinking", rendered)
        self.assertTrue(any(frame in rendered for frame in ("▁", "▃", "▅", "▇")))

    def test_status_bar_fragments_keep_previous_usage_during_live_turn(self) -> None:
        shell = self._make_shell()
        shell._last_prompt_tokens = 12_800
        shell._last_provider_prompt_tokens = 6_400
        shell._turn_started_at = time.monotonic()

        with mock.patch.object(
            type(shell.runtime),
            "provider_summary",
            return_value={"model_id": "gpt-5.4", "context_window_tokens": 128_000},
        ):
            fragments = shell._status_bar_fragments()
        rendered = "".join(text for _style, text in fragments)

        self.assertIn("6K/128K", rendered)
        self.assertIn("5%", rendered)
        self.assertNotIn("--/128K", rendered)
        self.assertNotIn("10%", rendered)

    def test_status_bar_fragments_show_committed_provider_usage_after_turn(self) -> None:
        shell = self._make_shell()
        shell._last_prompt_tokens = 14_000
        shell._last_provider_prompt_tokens = 43_500

        with mock.patch.object(
            type(shell.runtime),
            "provider_summary",
            return_value={"model_id": "glm5", "context_window_tokens": 128_000},
        ):
            fragments = shell._status_bar_fragments()
        rendered = "".join(text for _style, text in fragments)

        self.assertIn("44K/128K", rendered)
        self.assertIn("34%", rendered)
        self.assertIn("◔", rendered)
        self.assertNotIn("req ", rendered)

    def test_status_bar_fragments_use_lightweight_growth_projection(self) -> None:
        shell = self._make_shell()

        with mock.patch.object(
            type(shell.runtime),
            "inspect_growth",
            side_effect=AssertionError("status bar should avoid heavy inspect_growth"),
        ):
            fragments = shell._status_bar_fragments()
        rendered = "".join(text for _style, text in fragments)

        self.assertIn("Memory I", rendered)
        self.assertIn("checkpoint", rendered)

    def test_turn_progress_frame_uses_growing_copy(self) -> None:
        shell = self._make_shell()
        frame = shell._render_turn_frame(prompt="hello", tick=0)
        if RICH_AVAILABLE:
            self.assertIn("Working", str(getattr(frame, "title", "")))
        else:
            self.assertIn("Checking conversation context", str(frame))

    def test_turn_progress_title_rotates_with_tick(self) -> None:
        shell = self._make_shell()

        first = shell._render_turn_frame(prompt="hello", tick=0)
        # Title rotates once every 32 render ticks (~2.5s at 12.5 Hz).
        # Jump well past that boundary to see the second stage.
        later = shell._render_turn_frame(prompt="hello", tick=64)

        if RICH_AVAILABLE:
            self.assertIn("Working", str(getattr(first, "title", "")))
            self.assertIn("Composing reply", str(getattr(later, "title", "")))
        else:
            self.assertIn("Checking conversation context", str(first))
            self.assertIn("Composing the reply", str(later))

    def test_turn_progress_frame_surfaces_live_tool_activity(self) -> None:
        shell = self._make_shell()
        event = ToolLifecycleEvent(
            event_id="tool-event-1",
            invocation=ToolInvocation(
                invocation_id="session-1:tool.web.read",
                tool_id="tool.web.read",
                session_id="session-1",
                arguments={"url": "https://example.com"},
            ),
            phase="execution.started",
            detail="executing tool.web.read",
            approval=ToolApprovalResult(
                decision="approved",
                risk_class="high",
                required_controls=("outbound-policy",),
                reason="auto-approved locally",
            ),
        )
        frame = shell._render_turn_frame(prompt="hello", tick=0, tool_event=event)
        renderable = getattr(frame, "renderable", frame)
        rendered = renderable.plain if hasattr(renderable, "plain") else str(renderable)
        self.assertIn("┊ 🌐 fetch", rendered)
        self.assertIn("https://example.com", rendered)

    def test_turn_progress_frame_keeps_cumulative_tool_rail_visible(self) -> None:
        shell = self._make_shell()
        shell._rendered_entries = len(shell.transcript)
        shell._append_tooltrace_line("┊ 📚 Calling skill…")
        shell._append_tooltrace_line("┊ 📚 skill        apple-notes  0.3s")
        event = ToolLifecycleEvent(
            event_id="tool-event-2",
            invocation=ToolInvocation(
                invocation_id="session-1:tool.terminal.exec",
                tool_id="tool.terminal.exec",
                session_id="session-1",
                arguments={"command": "memo notes --help"},
            ),
            phase="execution.started",
            detail="executing tool.terminal.exec",
        )

        frame = shell._render_turn_frame(prompt="hello", tick=0, tool_event=event)
        renderable = getattr(frame, "renderable", frame)
        rendered = renderable.plain if hasattr(renderable, "plain") else str(renderable)

        self.assertIn("Calling skill", rendered)
        self.assertIn("apple-notes", rendered)
        self.assertIn("memo notes --help", rendered)

    def test_turn_progress_frame_renders_streaming_response_in_dedicated_surface(self) -> None:
        shell = self._make_shell()
        frame = shell._render_turn_frame(
            prompt="hello",
            tick=0,
            stream_text="First line of the reply.\nSecond line arrives next.",
        )

        if RICH_AVAILABLE:
            console = Console(width=100, record=True, force_terminal=True)
            console.print(frame)
            rendered = console.export_text(styles=False)
        else:
            rendered = str(frame)

        self.assertNotIn("Elephant Agent response", rendered)
        self.assertIn("First line of the reply.", rendered)
        self.assertIn("Second line arrives next.", rendered)

    def test_turn_progress_frame_formats_reasoning_with_elephant_mind_heading(self) -> None:
        shell = self._make_shell()
        frame = shell._render_turn_frame(
            prompt="hello",
            tick=0,
            stream_text="<think>Inspect the tool results first.</think>The release note draft is ready.",
        )

        if RICH_AVAILABLE:
            console = Console(width=100, record=True, force_terminal=True)
            console.print(frame)
            rendered = console.export_text(styles=False)
        else:
            rendered = str(frame)

        normalized_lines = [line.strip("│ ").rstrip() for line in rendered.splitlines()]
        mind_index = normalized_lines.index("🐾 Elephant Agent's Trail:")

        self.assertEqual(normalized_lines[mind_index + 1], "Inspect the tool results first.")
        self.assertEqual(normalized_lines[mind_index + 2], "")
        # Streaming frames decorate the tail with a pulsing cursor glyph
        # (▌▍▎▏). Be robust to that decoration — the response prefix should
        # still match exactly.
        self.assertTrue(
            normalized_lines[mind_index + 3].startswith("The release note draft is ready."),
            normalized_lines[mind_index + 3],
        )

    def test_turn_progress_frame_surfaces_context_compaction(self) -> None:
        shell = self._make_shell()
        frame = shell._render_turn_frame(
            prompt="hello",
            tick=0,
            kernel_stage_events=(
                {
                    "payload": {
                        "stage": "context-compact",
                        "detail": "reason=usage tokens=1800->620 messages=80->12 compacted_messages=68 tail=10",
                        "recorded_at": "2026-04-17T08:00:00+00:00",
                    }
                },
            ),
        )

        if RICH_AVAILABLE:
            console = Console(width=100, record=True, force_terminal=True)
            console.print(frame)
            rendered = console.export_text(styles=False)
        else:
            rendered = str(frame)

        self.assertIn("🧩 context", rendered)
        self.assertIn("projection compact", rendered)
        self.assertIn("est 1800->620 tokens", rendered)

    def test_turn_progress_frame_surfaces_recall_without_context_ready_or_request_rows(self) -> None:
        shell = self._make_shell()
        frame = shell._render_turn_frame(
            prompt="hello",
            tick=0,
            kernel_stage_events=(
                {
                    "payload": {
                        "stage": "context",
                        "detail": "bundle=bundle:session budget=204800",
                    }
                },
                {
                    "payload": {
                        "stage": "context-projection",
                        "detail": "prompt_tokens=2534 token_budget=204800 source=generation",
                    }
                },
                {
                    "payload": {
                        "stage": "recall",
                        "detail": "status=hit count=2 bytes=128",
                    }
                },
            ),
        )

        if RICH_AVAILABLE:
            console = Console(width=100, record=True, force_terminal=True)
            console.print(frame)
            rendered = console.export_text(styles=False)
        else:
            rendered = str(frame)

        self.assertIn("🗺️ recall", rendered)
        self.assertIn("linked 2 signals", rendered)
        self.assertNotIn("🧩 context", rendered)
        self.assertNotIn("📈 request", rendered)
        self.assertNotIn("provider running", rendered)

    def test_turn_progress_frame_hides_raw_tool_call_markup_from_stream_response(self) -> None:
        shell = self._make_shell()
        frame = shell._render_turn_frame(
            prompt="hello",
            tick=0,
            stream_text=(
                "I'll search for information on Xunzhuo Liu.\n"
                "<tool_call><invoke name=\"tool.web.search\"><parameter name=\"query\">"
                "xunzhuo liu researcher academic</parameter></invoke></tool_call>"
            ),
        )

        if RICH_AVAILABLE:
            console = Console(width=100, record=True, force_terminal=True)
            console.print(frame)
            rendered = console.export_text(styles=False)
        else:
            rendered = str(frame)

        self.assertIn("I'll search for information on Xunzhuo Liu.", rendered)
        self.assertNotIn("<tool_call>", rendered)
        self.assertNotIn("<invoke name=", rendered)
        self.assertNotIn("<parameter name=", rendered)

    def test_append_outcome_surfaces_state_focus_meta_in_transcript(self) -> None:
        shell = self._make_shell()
        outcome = SimpleNamespace(
            execution=SimpleNamespace(
                summary="The release note draft is ready.",
                prompt_tokens=128,
                completion_tokens=32,
                total_tokens=160,
                cached_prompt_tokens=64,
                cache_creation_prompt_tokens=8,
                cache_usage_reported=True,
                outcome="success",
            ),
            stages=(
                SimpleNamespace(
                    stage="relationship",
                    detail="continuity_notes=1",
                    recorded_at=datetime(2026, 4, 17, 8, 0, 0, tzinfo=timezone.utc),
                ),
                SimpleNamespace(
                    stage="state_focus",
                    detail=(
                        "state_focus=execution confidence=0.74 focus=work-release "
                        "scope=session degradation=none weak_assist=false "
                        "weak_outcome=not-requested fallback=none candidates=2"
                    ),
                    recorded_at=datetime(2026, 4, 17, 8, 0, 0, 12000, tzinfo=timezone.utc),
                ),
            ),
            plan=None,
            work_items=(),
            memories=(),
        )

        shell._append_outcome(outcome)

        self.assertEqual(shell.transcript[-1].kind, "assistant")
        self.assertEqual(shell.transcript[-1].body, "The release note draft is ready.")
        self.assertEqual(shell.transcript[-1].meta, "routing · execution · 12ms · loop · 0.74 · cache hit · 50.0%")

    def test_state_focus_notice_fragments_show_almost_there_while_transcript_prime_pending(self) -> None:
        shell = self._make_shell()

        with mock.patch.object(
            type(shell.runtime),
            "state_focus_runtime_status",
            return_value={
                "health_status": "ready",
                "runtime_state": "loaded",
                "embedding_ready": True,
                "summary": "steady",
            },
        ):
            fragments = _state_focus_notice_fragments(shell)

        rendered = "".join(text for _style, text in fragments)
        # Truthful state: embedding is loaded but transcript has not been
        # primed yet. Show a "finishing setup" banner — not "ready" — because
        # any message the user sends is still queued until the opening reply
        # completes. The old banner lied.
        self.assertIn("path nearly ready", rendered)
        self.assertNotIn("🐾 ready", rendered)
        self.assertNotIn("I'm with you", rendered)
        self.assertTrue(shell._state_focus_runtime_ready_seen)

    def test_state_focus_notice_fragments_hide_after_first_user_turn_is_submitted(self) -> None:
        shell = self._make_shell()
        shell._startup_user_turn_submitted = True

        with mock.patch.object(
            type(shell.runtime),
            "state_focus_runtime_status",
            return_value={
                "health_status": "ready",
                "runtime_state": "steadying",
                "embedding_ready": True,
                "summary": "steadying",
            },
        ):
            fragments = _state_focus_notice_fragments(shell)

        rendered = "".join(text for _style, text in fragments)
        # Single live slot — steadying state shows the orienting notice, not init.
        self.assertIn("🐘 orienting", rendered)
        self.assertNotIn("opening", rendered)
        self.assertNotIn("ready", rendered)

    def test_state_focus_notice_fragments_hide_after_ready_once_first_user_turn_is_submitted(self) -> None:
        shell = self._make_shell()
        shell._startup_surface_prepared = True
        shell._startup_user_turn_submitted = True
        shell._startup_transcript_primed = True  # opener already completed
        shell._state_focus_runtime_ready_seen = True

        with mock.patch.object(
            type(shell.runtime),
            "state_focus_runtime_status",
            return_value={
                "health_status": "ready",
                "runtime_state": "loaded",
                "embedding_ready": True,
                "summary": "steady",
            },
        ):
            fragments = _state_focus_notice_fragments(shell)

        rendered = "".join(text for _style, text in fragments)
        # Once embedding is loaded AND transcript primed, no notice — the
        # phase pip in the status bar carries signal from here on.
        self.assertNotIn("ready", rendered)
        self.assertNotIn("orienting", rendered)
        self.assertNotIn("opening", rendered)
        self.assertNotIn("path nearly ready", rendered)

    def test_state_focus_notice_fragments_surface_state_focus_queue_after_ready_when_first_turn_is_waiting(self) -> None:
        shell = self._make_shell()
        shell._startup_surface_prepared = True
        shell._startup_user_turn_submitted = True
        shell._pending_commands.append(PendingShellCommand(command="帮我看下这个"))

        with mock.patch.object(
            type(shell.runtime),
            "state_focus_runtime_status",
            return_value={
                "health_status": "ready",
                "runtime_state": "loaded",
                "embedding_ready": True,
                "summary": "steady",
            },
        ):
            fragments = _state_focus_notice_fragments(shell)

        rendered = "".join(text for _style, text in fragments)
        # A queued first turn surfaces the truthful pre-prime notice; the
        # queue itself surfaces via the pending-commands preview panel.
        self.assertIn("path nearly ready", rendered)
        self.assertNotIn("🐾 ready", rendered)

    def test_startup_transition_result_primes_opening_after_ready_idle_threshold(self) -> None:
        shell = self._make_shell()
        shell._state_focus_runtime_ready_seen_at = time.monotonic() - 10

        with mock.patch.object(type(shell), "_startup_state_focus_dispatch_ready", return_value=True):
            immediate = _startup_transition_result(shell, buffer_text="", idle_seconds=0.2)
            result = _startup_transition_result(shell, buffer_text="", idle_seconds=1.6)

        self.assertIsNone(immediate)
        self.assertEqual(result, "__elephant.startup.prime__")

    def test_startup_transition_result_primes_before_dispatching_queued_first_turn(self) -> None:
        shell = self._make_shell()
        shell._startup_user_turn_submitted = True
        shell._pending_commands.append(PendingShellCommand(command="帮我看下这个"))
        shell._state_focus_runtime_ready_seen_at = time.monotonic() - 10

        with mock.patch.object(type(shell), "_startup_state_focus_dispatch_ready", return_value=True):
            result = _startup_transition_result(shell, buffer_text="", idle_seconds=0.0)

        self.assertEqual(result, "__elephant.startup.prime__")

    def test_startup_transition_result_waits_briefly_after_ready_notice(self) -> None:
        shell = self._make_shell()
        shell._state_focus_runtime_ready_seen_at = time.monotonic()

        with mock.patch.object(type(shell), "_startup_state_focus_dispatch_ready", return_value=True):
            result = _startup_transition_result(shell, buffer_text="", idle_seconds=2.0)

        self.assertIsNone(result)

    def test_startup_transition_result_does_not_restart_prime_while_background_prime_runs(self) -> None:
        shell = self._make_shell()
        shell._startup_prime_started = True
        shell._state_focus_runtime_ready_seen_at = time.monotonic() - 10

        with mock.patch.object(type(shell), "_startup_state_focus_dispatch_ready", return_value=True):
            result = _startup_transition_result(shell, buffer_text="", idle_seconds=2.0)

        self.assertIsNone(result)

    def test_startup_transition_result_dispatches_pending_after_proactive_prime(self) -> None:
        shell = self._make_shell()
        shell._startup_user_turn_submitted = True
        shell._startup_transcript_primed = True
        shell._pending_commands.append(PendingShellCommand(command="帮我看下这个"))

        with mock.patch.object(type(shell), "_startup_state_focus_dispatch_ready", return_value=True):
            result = _startup_transition_result(shell, buffer_text="", idle_seconds=0.0)

        self.assertEqual(result, "__elephant.startup.dispatch-pending__")

    def test_startup_turn_is_queued_until_state_focus_runtime_is_ready(self) -> None:
        shell = self._make_shell()

        with mock.patch.object(type(shell), "_startup_state_focus_dispatch_ready", return_value=False):
            self.assertTrue(shell._startup_should_hold_user_command("帮我看下这个"))
            self.assertFalse(shell._startup_should_hold_user_command("/help"))
            shell._mark_startup_user_turn_submitted("帮我看下这个")
            shell._enqueue_followup_command("帮我看下这个")
            self.assertTrue(shell._startup_should_hold_user_command("再补一句"))

        self.assertTrue(shell._startup_user_turn_submitted)

    def test_startup_turn_still_queues_until_proactive_opening_is_primed(self) -> None:
        shell = self._make_shell()

        with mock.patch.object(type(shell), "_startup_state_focus_dispatch_ready", return_value=True):
            self.assertTrue(shell._startup_should_hold_user_command("帮我看下这个"))
        shell._startup_transcript_primed = True
        with mock.patch.object(type(shell), "_startup_state_focus_dispatch_ready", return_value=True):
            self.assertFalse(shell._startup_should_hold_user_command("帮我看下这个"))

    def test_shell_constructor_defers_startup_opening_until_explicit_prime(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        root = Path(tmpdir.name)
        state_dir = root / "state"
        profile_dir = root / "profile"
        profile_dir.mkdir()
        (root / "profile.json").write_text(
            json.dumps(
                {
                    "profile_id": "profile-companion",
                    "display_name": "Elephant Agent",
                    "mode": "companion",
                }
            ),
            encoding="utf-8",
        )
        runtime = CliRuntime.create(state_dir=state_dir)
        runtime.update_identity_state(
            profile_id="profile-companion",
            elephant_identity_text="Stay durable.",
        )
        session = runtime.create_elephant(elephant_id="atlas")

        with mock.patch.object(CliRuntime, "generate_opening_reply") as generate_opening_reply:
            shell = ProductizedShell(runtime, session_id=session.session_id, opened="Shaped new")

        generate_opening_reply.assert_not_called()
        self.assertEqual(shell.transcript, [])

    def test_run_prepares_surface_after_shell_frame_is_rendered(self) -> None:
        shell = self._make_shell()
        events: list[str] = []

        def record(name: str):
            def _inner(*args, **kwargs):
                events.append(name)
                return None

            return _inner

        with (
            mock.patch.object(shell, "_render_startup_sequence", side_effect=record("startup-sequence")),
            mock.patch.object(shell, "_refresh_shell_frame", side_effect=record("refresh-frame")),
            mock.patch.object(shell, "_prepare_startup_surface", side_effect=record("prepare-surface")),
            mock.patch.object(shell, "_next_command", side_effect=EOFError),
            mock.patch.object(shell.console, "print"),
        ):
            shell.run()

        self.assertLess(events.index("refresh-frame"), events.index("prepare-surface"))

    def test_run_handles_startup_prime_sentinel_before_next_turn(self) -> None:
        shell = self._make_shell()
        commands = iter(
            (
                PendingShellCommand(command="__elephant.startup.prime__"),
                EOFError(),
            )
        )

        def next_command():
            value = next(commands)
            if isinstance(value, BaseException):
                raise value
            return value

        with (
            mock.patch.object(shell, "_render_startup_sequence"),
            mock.patch.object(shell, "_refresh_shell_frame"),
            mock.patch.object(shell, "_prepare_startup_surface"),
            mock.patch.object(shell, "_prime_startup_transcript_if_needed") as prime,
            mock.patch.object(shell, "_render_pending_entries"),
            mock.patch.object(shell, "_next_command", side_effect=next_command),
            mock.patch.object(shell.console, "print"),
        ):
            shell.run()

        prime.assert_called_once_with()

    def test_run_dispatches_queued_startup_turn_immediately_after_prime(self) -> None:
        shell = self._make_shell()
        shell._pending_commands.append(PendingShellCommand(command="帮我看下这个"))
        commands = iter(
            (
                PendingShellCommand(command="__elephant.startup.prime__"),
            )
        )

        def next_command():
            value = next(commands)
            if isinstance(value, BaseException):
                raise value
            return value

        with (
            mock.patch.object(shell, "_render_startup_sequence"),
            mock.patch.object(shell, "_refresh_shell_frame"),
            mock.patch.object(shell, "_prepare_startup_surface"),
            mock.patch.object(shell, "_prime_startup_transcript_if_needed") as prime,
            mock.patch.object(shell, "_startup_state_focus_dispatch_ready", return_value=True),
            mock.patch.object(shell, "_dispatch", return_value=True) as dispatch,
            mock.patch.object(shell, "_render_pending_entries"),
            mock.patch.object(shell, "_next_command", side_effect=next_command),
            mock.patch.object(shell.console, "print"),
        ):
            shell.run()

        prime.assert_called_once_with()
        dispatch.assert_called_once_with(PendingShellCommand(command="帮我看下这个"))

    def test_prepare_startup_surface_runs_in_background_and_refreshes_skills(self) -> None:
        shell = self._make_shell()

        class _ImmediateThread:
            def __init__(self, *, target, name=None, daemon=None):
                self._target = target

            def start(self) -> None:
                self._target()

        with (
            mock.patch("apps.cli.shell_methods_ui.threading.Thread", side_effect=_ImmediateThread),
            mock.patch.object(type(shell.runtime), "prepare_session_surface") as prepare_surface,
            mock.patch.object(shell, "_refresh_skill_slash_specs") as refresh_skills,
        ):
            shell._prepare_startup_surface()

        prepare_surface.assert_called_once_with(shell.session_id)
        refresh_skills.assert_called_once_with()
        self.assertTrue(shell._startup_surface_prepared)

    def test_turn_progress_fragments_keep_stream_text_out_of_progress_header(self) -> None:
        shell = self._make_shell()

        fragments = shell._render_turn_progress_fragments(
            prompt="draft the next release note",
            tick=0,
            stream_text="streaming chunk",
        )

        rendered = "".join(text for _style, text in fragments)
        self.assertIn("Working", rendered)
        self.assertIn("streaming chunk", rendered)
        self.assertNotIn("active request:", rendered)

    def test_stream_text_tracker_strips_tool_markup_and_resets_between_tool_rounds(self) -> None:
        holder, lock, observer = stream_text_tracker()

        observer("I'll search for information on Xunzhuo Liu.\n")
        observer("<tool_call><invoke name=\"tool.web.search\"><parameter name=\"query\">xunzhuo")
        self.assertEqual(
            latest_stream_text(holder, lock).strip(),
            "I'll search for information on Xunzhuo Liu.",
        )

        observer(" liu researcher academic</parameter></invoke></tool_call>")
        self.assertEqual(
            latest_stream_text(holder, lock).strip(),
            "I'll search for information on Xunzhuo Liu.",
        )

        reset_stream_text(holder, lock)
        observer("I found several relevant researcher profiles.")
        self.assertEqual(
            latest_stream_text(holder, lock),
            "I found several relevant researcher profiles.",
        )

    def test_retain_stream_response_only_drops_old_thinking_but_keeps_response(self) -> None:
        holder, lock, observer = stream_text_tracker()

        observer("<think>Inspect the first result carefully.</think>I'll open the strongest profile next.")

        preserved = shell_progress_runtime.retain_stream_response_only(holder, lock)

        self.assertEqual(preserved, "I'll open the strongest profile next.")
        self.assertEqual(latest_stream_text(holder, lock), "I'll open the strongest profile next.")

    def test_tool_event_tracker_stream_anchors_exclude_historical_thinking(self) -> None:
        holder, lock, observer = stream_text_tracker()
        tool_event_holder, tool_event_lock, tool_observer = shell_progress_runtime.tool_event_tracker(
            stream_holder=holder,
            stream_lock=lock,
        )
        invocation = ToolInvocation(
            invocation_id="session-1:tool.web.search",
            tool_id="tool.web.search",
            session_id="session-1",
            arguments={"query": "release note"},
            requested_at=datetime(2026, 4, 13, 8, 0, 0, tzinfo=timezone.utc),
        )

        observer("<think>Inspect the strongest result first.</think>I'll open the release dashboard.")
        tool_observer(
            ToolLifecycleEvent(
                event_id="tool-event-requested-thinking-trim",
                invocation=invocation,
                phase="requested",
                detail="requested tool.web.search",
                occurred_at=invocation.requested_at,
            )
        )

        anchors = shell_progress_runtime.stream_anchor_events(tool_event_holder, tool_event_lock)

        self.assertEqual(len(anchors), 1)
        self.assertEqual(anchors[0].stream_text, "I'll open the release dashboard.")

    def test_boot_frame_uses_centered_full_screen_brand_layout(self) -> None:
        shell = self._make_shell()
        shell.console = _StubConsole(120)
        shell.console.size = type("Size", (), {"width": 120, "height": 34})()
        frame = shell._render_boot_frame()

        if not RICH_AVAILABLE:
            self.assertIn("Elephant Agent", str(frame))
            self.assertNotIn("waking", str(frame).lower())
            return

        panel = getattr(frame, "renderable", frame)
        self.assertIn("Elephant Agent", str(getattr(panel, "title", "")))
        self.assertNotIn("waking", str(getattr(panel, "title", "")).lower())
        self.assertEqual(str(getattr(panel, "border_style", "")), BRAND_DARK)
        self.assertEqual(getattr(panel, "width", None), 72)
        console = Console(width=120, record=True, force_terminal=True)
        console.print(frame)
        rendered = console.export_text(styles=False)
        self.assertNotIn("ELEPHANT // wake", rendered)
        self.assertNotIn("waking", rendered.lower())
        self.assertIn("Picking up your thread", rendered)
        self.assertIn("Memory I", rendered)

    def test_startup_sequence_does_not_render_boot_animation(self) -> None:
        shell = self._make_shell()
        with mock.patch.object(shell, "_render_boot_frame") as render_boot:
            shell._render_startup_sequence()
        render_boot.assert_not_called()

    def test_unknown_command_uses_brand_accent_panel(self) -> None:
        shell = self._make_shell()
        panel = shell._render_entry(TranscriptEntry(kind="command", title="Unknown command", body="/wat\nhelp: /help"))
        self.assertEqual(getattr(panel, "title", ""), "Unknown command")
        border_style = getattr(panel, "border_style", None)
        if border_style is not None:
            self.assertEqual(str(border_style), BRAND_ACCENT)

    def test_personal_model_update_progress_copy_mentions_understanding_surface(self) -> None:
        shell = self._make_shell()
        event = ToolLifecycleEvent(
            event_id="tool-event-2",
            invocation=ToolInvocation(
                invocation_id="session-1:tool.personal_model.update",
                tool_id="tool.personal_model.update",
                session_id="session-1",
                arguments={"action": "remember", "lens": "trait", "topic": "identity.name.preferred", "text": "The user's preferred name is Bit."},
            ),
            phase="execution.started",
            detail="executing tool.personal_model.update",
            approval=ToolApprovalResult(
                decision="approved",
                risk_class="medium",
                reason="auto-approved locally",
            ),
        )

        title, detail = shell._tool_event_lines(event)
        self.assertEqual(title, "Tool executing · tool.personal_model.update")
        self.assertIn("executing tool.personal_model.update", detail or "")

        frame = shell._render_tool_frame(tool_id="tool.personal_model.update", tick=3, tool_event=event)
        renderable = getattr(frame, "renderable", frame)
        rendered = renderable.plain if hasattr(renderable, "plain") else str(renderable)
        self.assertIn("┊ 🌱 learn", rendered)
        self.assertIn("remember identity.name.preferred", rendered)

    def test_personal_model_search_progress_uses_generic_lookup_copy(self) -> None:
        shell = self._make_shell()
        event = ToolLifecycleEvent(
            event_id="tool-event-2c",
            invocation=ToolInvocation(
                invocation_id="session-1:tool.personal_model.search",
                tool_id="tool.personal_model.search",
                session_id="session-1",
                arguments={"query": "notes"},
            ),
            phase="execution.started",
            detail="executing tool.personal_model.search",
        )

        title, detail = shell._tool_event_lines(event)
        self.assertEqual(title, "Tool executing · tool.personal_model.search")
        self.assertIn("executing tool.personal_model.search", detail or "")

        frame = shell._render_tool_frame(tool_id="tool.personal_model.search", tick=2, tool_event=event)
        renderable = getattr(frame, "renderable", frame)
        rendered = renderable.plain if hasattr(renderable, "plain") else str(renderable)
        self.assertIn("┊ 🐘 model", rendered)

    def test_tool_trace_lines_persist_start_and_completion_events(self) -> None:
        shell = self._make_shell()
        started_at = datetime(2026, 4, 13, 8, 0, 0, tzinfo=timezone.utc)
        requested = ToolLifecycleEvent(
            event_id="tool-event-requested",
            invocation=ToolInvocation(
                invocation_id="session-1:tool.file.search",
                tool_id="tool.file.search",
                session_id="session-1",
                arguments={"query": "xunzhuo liu"},
                requested_at=started_at,
            ),
            phase="requested",
            detail="requested tool.file.search",
            occurred_at=started_at,
        )
        completed = ToolLifecycleEvent(
            event_id="tool-event-completed",
            invocation=requested.invocation,
            phase="execution.completed",
            detail="completed tool.file.search",
            occurred_at=started_at.replace(second=3, microsecond=200000),
        )

        shell._record_tool_event_trace(requested)
        shell._record_tool_event_trace(completed)

        tool_entries = [entry for entry in shell.transcript if entry.kind == "tooltrace"]
        self.assertEqual(len(tool_entries), 1)
        self.assertIn("┊ 🔎 Calling grep · xunzhuo liu…", tool_entries[0].body)
        self.assertIn("┊ 🔎 grep", tool_entries[0].body)
        self.assertIn("xunzhuo liu", tool_entries[0].body)
        self.assertIn("3.2s", tool_entries[0].body)

    def test_todo_completed_event_appends_current_items_to_tooltrace(self) -> None:
        shell = self._make_shell()
        shell.runtime.todo_store.upsert_item(
            shell.session_id,
            title="梳理 UI 工具链路",
            status="in_progress",
            notes="",
        )
        shell.runtime.todo_store.upsert_item(
            shell.session_id,
            title="补齐 write file diff 预览",
            status="open",
            notes="",
        )
        event = ToolLifecycleEvent(
            event_id="tool-event-todo-completed",
            invocation=ToolInvocation(
                invocation_id="session-1:tool.todo.manage",
                tool_id="tool.todo.manage",
                session_id=shell.session_id,
                arguments={"action": "list"},
                requested_at=datetime(2026, 4, 13, 8, 0, 0, tzinfo=timezone.utc),
            ),
            phase="execution.completed",
            detail="listed todos",
            execution=SimpleNamespace(outcome="success"),
        )

        shell._record_tool_event_trace(event)

        tool_entries = [entry for entry in shell.transcript if entry.kind == "tooltrace"]
        self.assertEqual(len(tool_entries), 1)
        self.assertIn("┊ 📋 todo", tool_entries[0].body)
        self.assertIn("┊ 📋 todo items   2 item(s)", tool_entries[0].body)
        self.assertIn("in_progress | 梳理 UI 工具链路", tool_entries[0].body)
        self.assertIn("open | 补齐 write file diff 预览", tool_entries[0].body)

    def test_file_write_completed_event_appends_review_diff_to_tooltrace(self) -> None:
        shell = self._make_shell()
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            file_path = Path(tmpdir) / "tool-review-diff.md"
            file_path.write_text("hello\n", encoding="utf-8")
            relative_path = str(file_path.relative_to(Path.cwd()))
            requested_at = datetime(2026, 4, 13, 8, 0, 0, tzinfo=timezone.utc)
            invocation = ToolInvocation(
                invocation_id="session-1:tool.file.write",
                tool_id="tool.file.write",
                session_id=shell.session_id,
                arguments={"path": relative_path, "content": "hello\nworld\n"},
                requested_at=requested_at,
            )
            requested = ToolLifecycleEvent(
                event_id="tool-event-write-requested",
                invocation=invocation,
                phase="requested",
                detail="requested tool.file.write",
                occurred_at=requested_at,
            )
            completed = ToolLifecycleEvent(
                event_id="tool-event-write-completed",
                invocation=invocation,
                phase="execution.completed",
                detail=f"path: {relative_path}",
                execution=SimpleNamespace(outcome="success"),
                occurred_at=requested_at.replace(second=1),
            )

            shell._record_tool_event_trace(requested)
            file_path.write_text("hello\nworld\n", encoding="utf-8")
            shell._record_tool_event_trace(completed)

        tool_entries = [entry for entry in shell.transcript if entry.kind == "tooltrace"]
        self.assertEqual(len(tool_entries), 1)
        self.assertIn("┊ 🛠 write", tool_entries[0].body)
        self.assertIn("┊ 🛠 diff", tool_entries[0].body)
        self.assertIn(f"a/{relative_path} → b/{relative_path}", tool_entries[0].body)
        self.assertIn("@@ -1 +1,2 @@", tool_entries[0].body)
        self.assertIn("+world", tool_entries[0].body)

    def test_turn_tool_progress_lines_keep_write_visible_when_diff_is_pending(self) -> None:
        shell = self._make_shell()
        shell.transcript = [
            TranscriptEntry(
                kind="tooltrace",
                title="Tool trace",
                body=(
                    "┊ 🛠 Calling write…\n"
                    "┊ 🛠 write        notes.md  0.2s\n"
                    "┊ 🛠 diff\n"
                    "a/notes.md → b/notes.md\n"
                    "@@ -1 +1,2 @@\n"
                    " hello\n"
                    "+world"
                ),
            )
        ]
        shell._rendered_entries = 0

        lines = turn_tool_progress_lines(shell)

        self.assertIn("┊ 🛠 Calling write…", lines)
        self.assertIn("┊ 🛠 write        notes.md  0.2s", lines)
        self.assertIn("┊ 🛠 diff", lines)
        self.assertFalse(any(line.startswith("a/") for line in lines))
        self.assertFalse(any(line.startswith("@@") for line in lines))
        self.assertFalse(any(line.startswith("+") for line in lines))

    def test_render_pending_entries_keeps_context_compaction_frame_until_next_turn(self) -> None:
        shell = self._make_shell()
        shell._pending_context_compaction_frame = {
            "prompt": "hello",
            "tick": 0,
            "kernel_stage_events": (
                {
                    "payload": {
                        "stage": "context-compact",
                        "detail": "reason=usage tokens=1800->620 messages=80->12 compacted_messages=68 tail=10",
                        "recorded_at": "2026-04-17T08:00:00+00:00",
                    }
                },
            ),
        }
        if RICH_AVAILABLE:
            shell.console = Console(width=100, record=True, force_terminal=True)
            shell._render_pending_entries()
            rendered = shell.console.export_text(styles=False)
        else:
            capture = _CaptureConsole(100)
            shell.console = capture
            shell._render_pending_entries()
            rendered = "\n".join(capture.printed)

        self.assertTrue(shell._pending_context_compaction_frame_rendered)
        self.assertIn("🧩 context", rendered)
        self.assertIn("projection compact", rendered)
        self.assertIn("est 1800->620 tokens", rendered)

    def test_turn_progress_frame_keeps_later_tool_events_visible_after_diff_body(self) -> None:
        shell = self._make_shell()
        shell.transcript = [
            TranscriptEntry(
                kind="tooltrace",
                title="Tool trace",
                body=(
                    "┊ 🛠 write        notes.md  0.2s\n"
                    "┊ 🛠 diff\n"
                    "a/notes.md → b/notes.md\n"
                    "@@ -1 +1,2 @@\n"
                    " hello\n"
                    "+world\n"
                    "┊ 💻 computer     osascript -e 'tell app \"Notes\" to activate'  0.3s"
                ),
            )
        ]
        shell._rendered_entries = 0

        frame = shell._render_turn_frame(prompt="hello", tick=0)
        renderable = getattr(frame, "renderable", frame)
        rendered = renderable.plain if hasattr(renderable, "plain") else str(renderable)

        self.assertIn("┊ 🛠 diff", rendered)
        self.assertIn("a/notes.md → b/notes.md", rendered)
        self.assertIn("┊ 💻 computer", rendered)
        self.assertIn("osascript", rendered)

    def test_personal_model_update_completed_event_keeps_generic_tooltrace(self) -> None:
        shell = self._make_shell()
        event = ToolLifecycleEvent(
            event_id="tool-event-state-completed",
            invocation=ToolInvocation(
                invocation_id="session-1:tool.personal_model.update",
                tool_id="tool.personal_model.update",
                session_id=shell.session_id,
                arguments={"action": "remember", "lens": "trait", "topic": "identity.name.preferred", "text": "The user's preferred name is Bit."},
                requested_at=datetime(2026, 4, 13, 8, 0, 0, tzinfo=timezone.utc),
            ),
            phase="execution.completed",
            detail="understanding updated",
            execution=SimpleNamespace(outcome="success"),
        )

        shell._record_tool_event_trace(event)

        tool_entries = [entry for entry in shell.transcript if entry.kind == "tooltrace"]
        self.assertEqual(len(tool_entries), 1)
        self.assertIn("┊ 🌱 learn", tool_entries[0].body)
        self.assertIn("remember identity.name.preferred", tool_entries[0].body)
        self.assertNotIn("legacy file", tool_entries[0].body.lower())

    def test_tool_trace_entries_render_with_layered_styles(self) -> None:
        shell = self._make_shell()
        rendered = shell._render_entry(
            TranscriptEntry(
                kind="tooltrace",
                title="Tool trace",
                body="┊ 🌐 search       xunzhuo liu  3.2s",
            )
        )

        plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)
        self.assertIn("┊ 🌐 search", plain)
        self.assertIn("xunzhuo liu", plain)
        self.assertIn("3.2s", plain)
        if RICH_AVAILABLE:
            styles = {str(span.style) for span in rendered.spans}
            self.assertIn(BRAND_DARK, styles)
            self.assertIn(BRAND_ACCENT, styles)
            self.assertIn(BRAND_MUTED, styles)
            self.assertIn(f"bold {BRAND_ACCENT_STRONG}", styles)

    def test_turn_progress_fragments_reuse_tool_trace_copy_for_live_events(self) -> None:
        shell = self._make_shell()
        invocation = ToolInvocation(
            invocation_id="session-1:tool.web.search",
            tool_id="tool.web.search",
            session_id="session-1",
            arguments={"query": "xunzhuo liu"},
            requested_at=datetime(2026, 4, 13, 8, 0, 0, tzinfo=timezone.utc),
        )
        requested = ToolLifecycleEvent(
            event_id="tool-event-requested",
            invocation=invocation,
            phase="requested",
            detail="requested tool.web.search",
            occurred_at=invocation.requested_at,
        )
        started = ToolLifecycleEvent(
            event_id="tool-event-started",
            invocation=invocation,
            phase="execution.started",
            detail="executing tool.web.search",
            occurred_at=invocation.requested_at,
        )

        requested_fragments = shell._render_turn_progress_fragments(prompt="search xunzhuo liu", tick=0, tool_event=requested)
        started_fragments = shell._render_turn_progress_fragments(prompt="search xunzhuo liu", tick=0, tool_event=started)

        requested_text = "".join(fragment[1] for fragment in requested_fragments)
        started_text = "".join(fragment[1] for fragment in started_fragments)
        self.assertIn("┊ 🌐 Calling search…", requested_text)
        self.assertIn("┊ 🌐 search", started_text)
        self.assertIn("xunzhuo liu", started_text)

    def test_turn_progress_fragments_anchor_stream_text_to_matching_tool_event(self) -> None:
        shell = self._make_shell()
        stream_holder, stream_lock, stream_observer = stream_text_tracker()
        tool_event_holder, tool_event_lock, tool_observer = shell_progress_runtime.tool_event_tracker(
            stream_holder=stream_holder,
            stream_lock=stream_lock,
        )
        search_invocation = ToolInvocation(
            invocation_id="session-1:tool.web.search",
            tool_id="tool.web.search",
            session_id="session-1",
            arguments={"query": "xunzhuo liu"},
            requested_at=datetime(2026, 4, 13, 8, 0, 0, tzinfo=timezone.utc),
        )
        search_requested = ToolLifecycleEvent(
            event_id="tool-event-search-requested",
            invocation=search_invocation,
            phase="requested",
            detail="requested tool.web.search",
            occurred_at=search_invocation.requested_at,
        )
        search_started = ToolLifecycleEvent(
            event_id="tool-event-search-started",
            invocation=search_invocation,
            phase="execution.started",
            detail="executing tool.web.search",
            occurred_at=search_invocation.requested_at,
        )
        read_invocation = ToolInvocation(
            invocation_id="session-1:tool.web.read",
            tool_id="tool.web.read",
            session_id="session-1",
            arguments={"url": "https://example.com/profile"},
            requested_at=datetime(2026, 4, 13, 8, 0, 1, tzinfo=timezone.utc),
        )
        read_requested = ToolLifecycleEvent(
            event_id="tool-event-read-requested",
            invocation=read_invocation,
            phase="requested",
            detail="requested tool.web.read",
            occurred_at=read_invocation.requested_at,
        )
        read_started = ToolLifecycleEvent(
            event_id="tool-event-read-started",
            invocation=read_invocation,
            phase="execution.started",
            detail="executing tool.web.read",
            occurred_at=read_invocation.requested_at,
        )

        stream_observer("I'll search for the profile first.")
        tool_observer(search_requested)
        tool_observer(search_started)
        stream_observer("\nThen I'll open the best result.")
        tool_observer(read_requested)
        tool_observer(read_started)

        fragments = shell_progress_runtime.render_turn_progress_fragments(
            shell,
            prompt="inspect the profile",
            tick=0,
            stream_text=latest_stream_text(stream_holder, stream_lock),
            tool_event_holder=tool_event_holder,
            tool_event_lock=tool_event_lock,
        )

        rendered = "".join(fragment[1] for fragment in fragments)
        self.assertLess(rendered.index("I'll search for the profile first."), rendered.index("┊ 🌐 search"))
        self.assertGreater(rendered.index("Then I'll open the best result."), rendered.index("┊ 🌐 search"))
        self.assertLess(rendered.index("Then I'll open the best result."), rendered.rindex("┊ 🌐 Calling fetch…"))

    def test_turn_progress_fragments_keep_stream_text_with_started_event_after_requested_event_expires(self) -> None:
        shell = self._make_shell()
        stream_holder, stream_lock, stream_observer = stream_text_tracker()
        tool_event_holder, tool_event_lock, tool_observer = shell_progress_runtime.tool_event_tracker(
            stream_holder=stream_holder,
            stream_lock=stream_lock,
        )
        invocation = ToolInvocation(
            invocation_id="session-1:tool.web.search",
            tool_id="tool.web.search",
            session_id="session-1",
            arguments={"query": "elephant status"},
            requested_at=datetime(2026, 4, 13, 8, 0, 0, tzinfo=timezone.utc),
        )
        requested = ToolLifecycleEvent(
            event_id="tool-event-requested",
            invocation=invocation,
            phase="requested",
            detail="requested tool.web.search",
            occurred_at=invocation.requested_at,
        )
        started = ToolLifecycleEvent(
            event_id="tool-event-started",
            invocation=invocation,
            phase="execution.started",
            detail="executing tool.web.search",
            occurred_at=invocation.requested_at,
        )

        stream_observer("I'll inspect local files first.")
        tool_observer(requested)
        tool_observer(started)

        now = time.monotonic()
        with tool_event_lock:
            tool_event_holder["feed"] = [
                _VisibleToolEvent(
                    event=item.event,
                    expires_at=(now - 1.0) if item.event.phase == "requested" else (now + 10.0),
                    stream_text=item.stream_text,
                )
                for item in tool_event_holder.get("feed", ())
                if isinstance(item, _VisibleToolEvent)
            ]

        fragments = shell_progress_runtime.render_turn_progress_fragments(
            shell,
            prompt="inspect local files",
            tick=0,
            stream_text=latest_stream_text(stream_holder, stream_lock),
            tool_event_holder=tool_event_holder,
            tool_event_lock=tool_event_lock,
        )

        rendered = "".join(fragment[1] for fragment in fragments)
        self.assertIn("I'll inspect local files first.", rendered)
        self.assertEqual(rendered.count("I'll inspect local files first."), 1)
        self.assertLess(rendered.index("I'll inspect local files first."), rendered.index("┊ 🌐 search"))

    def test_turn_progress_fragments_preserve_repeated_tool_rail_with_late_stream_anchor(self) -> None:
        shell = self._make_shell()
        shell._rendered_entries = len(shell.transcript)
        stream_holder, stream_lock, stream_observer = stream_text_tracker()
        tool_event_holder, tool_event_lock, tool_observer = shell_progress_runtime.tool_event_tracker(
            shell._record_tool_event_trace,
            stream_holder=stream_holder,
            stream_lock=stream_lock,
        )
        first_invocation = ToolInvocation(
            invocation_id="session-1:tool.file.read:1",
            tool_id="tool.file.read",
            session_id="session-1",
            arguments={"file_path": "/tmp/alpha.txt"},
            requested_at=datetime(2026, 4, 13, 8, 0, 0, tzinfo=timezone.utc),
        )
        first_requested = ToolLifecycleEvent(
            event_id="tool-event-read-requested-1",
            invocation=first_invocation,
            phase="requested",
            detail="requested tool.file.read",
            occurred_at=first_invocation.requested_at,
        )
        first_completed = ToolLifecycleEvent(
            event_id="tool-event-read-completed-1",
            invocation=first_invocation,
            phase="execution.completed",
            detail="read /tmp/alpha.txt",
            occurred_at=datetime(2026, 4, 13, 8, 0, 0, 700000, tzinfo=timezone.utc),
            execution=SimpleNamespace(outcome="success"),
        )
        second_invocation = ToolInvocation(
            invocation_id="session-1:tool.file.read:2",
            tool_id="tool.file.read",
            session_id="session-1",
            arguments={"file_path": "/tmp/beta.txt"},
            requested_at=datetime(2026, 4, 13, 8, 0, 1, tzinfo=timezone.utc),
        )
        second_requested = ToolLifecycleEvent(
            event_id="tool-event-read-requested-2",
            invocation=second_invocation,
            phase="requested",
            detail="requested tool.file.read",
            occurred_at=second_invocation.requested_at,
        )

        stream_observer("I'll inspect the first file.")
        tool_observer(first_requested)
        tool_observer(first_completed)
        stream_observer("\nThen I'll inspect the second file.")
        tool_observer(second_requested)

        fragments = shell_progress_runtime.render_turn_progress_fragments(
            shell,
            prompt="inspect files",
            tick=0,
            stream_text=latest_stream_text(stream_holder, stream_lock),
            tool_event_holder=tool_event_holder,
            tool_event_lock=tool_event_lock,
        )

        rendered = "".join(fragment[1] for fragment in fragments)
        self.assertGreaterEqual(rendered.count("┊ 📖 Calling read…"), 2)
        self.assertIn("┊ 📖 read         /tmp/alpha.txt  0.7s", rendered)
        self.assertLess(rendered.index("┊ 📖 read         /tmp/alpha.txt  0.7s"), rendered.index("Then I'll inspect the second file."))
        self.assertLess(rendered.index("Then I'll inspect the second file."), rendered.rindex("┊ 📖 Calling read…"))

    def test_turn_progress_fragments_keep_middle_stream_text_after_live_events_expire(self) -> None:
        shell = self._make_shell()
        shell._rendered_entries = len(shell.transcript)
        stream_holder, stream_lock, stream_observer = stream_text_tracker()
        tool_event_holder, tool_event_lock, tool_observer = shell_progress_runtime.tool_event_tracker(
            shell._record_tool_event_trace,
            stream_holder=stream_holder,
            stream_lock=stream_lock,
        )
        search_invocation = ToolInvocation(
            invocation_id="session-1:tool.web.search",
            tool_id="tool.web.search",
            session_id="session-1",
            arguments={"query": "xunzhuo liu"},
            requested_at=datetime(2026, 4, 13, 8, 0, 0, tzinfo=timezone.utc),
        )
        search_requested = ToolLifecycleEvent(
            event_id="tool-event-search-requested-expiring",
            invocation=search_invocation,
            phase="requested",
            detail="requested tool.web.search",
            occurred_at=search_invocation.requested_at,
        )
        search_completed = ToolLifecycleEvent(
            event_id="tool-event-search-completed-expiring",
            invocation=search_invocation,
            phase="execution.completed",
            detail="completed tool.web.search",
            occurred_at=datetime(2026, 4, 13, 8, 0, 0, 900000, tzinfo=timezone.utc),
            execution=SimpleNamespace(outcome="success"),
        )
        read_invocation = ToolInvocation(
            invocation_id="session-1:tool.web.read",
            tool_id="tool.web.read",
            session_id="session-1",
            arguments={"url": "https://example.com/profile"},
            requested_at=datetime(2026, 4, 13, 8, 0, 1, tzinfo=timezone.utc),
        )
        read_requested = ToolLifecycleEvent(
            event_id="tool-event-read-requested-expiring",
            invocation=read_invocation,
            phase="requested",
            detail="requested tool.web.read",
            occurred_at=read_invocation.requested_at,
        )

        stream_observer("I'll search for the profile first.")
        tool_observer(search_requested)
        tool_observer(search_completed)
        stream_observer("\nThen I'll open the best result.")
        tool_observer(read_requested)

        now = time.monotonic()
        with tool_event_lock:
            tool_event_holder["feed"] = [
                _VisibleToolEvent(event=item.event, expires_at=now - 1.0, stream_text=item.stream_text)
                for item in tool_event_holder.get("feed", ())
                if isinstance(item, _VisibleToolEvent)
            ]

        fragments = shell_progress_runtime.render_turn_progress_fragments(
            shell,
            prompt="inspect the profile",
            tick=0,
            stream_text=latest_stream_text(stream_holder, stream_lock),
            tool_event_holder=tool_event_holder,
            tool_event_lock=tool_event_lock,
        )

        rendered = "".join(fragment[1] for fragment in fragments)
        self.assertLess(rendered.index("I'll search for the profile first."), rendered.index("┊ 🌐 Calling search…"))
        self.assertGreater(rendered.index("Then I'll open the best result."), rendered.index("┊ 🌐 search"))
        self.assertLess(rendered.index("Then I'll open the best result."), rendered.rindex("┊ 🌐 Calling fetch…"))

    def test_turn_progress_fragments_keep_earliest_stream_anchor_after_live_feed_truncates(self) -> None:
        shell = self._make_shell()
        shell._rendered_entries = len(shell.transcript)
        stream_holder, stream_lock, stream_observer = stream_text_tracker()
        tool_event_holder, tool_event_lock, tool_observer = shell_progress_runtime.tool_event_tracker(
            shell._record_tool_event_trace,
            stream_holder=stream_holder,
            stream_lock=stream_lock,
        )
        invocations_and_events = (
            (
                "I'll search first.",
                ToolInvocation(
                    invocation_id="session-1:tool.web.search",
                    tool_id="tool.web.search",
                    session_id="session-1",
                    arguments={"query": "alpha"},
                    requested_at=datetime(2026, 4, 13, 8, 0, 0, tzinfo=timezone.utc),
                ),
                "requested tool.web.search",
                "completed tool.web.search",
                datetime(2026, 4, 13, 8, 0, 0, 500000, tzinfo=timezone.utc),
            ),
            (
                "\nThen I'll fetch.",
                ToolInvocation(
                    invocation_id="session-1:tool.web.read",
                    tool_id="tool.web.read",
                    session_id="session-1",
                    arguments={"url": "https://example.com/alpha"},
                    requested_at=datetime(2026, 4, 13, 8, 0, 1, tzinfo=timezone.utc),
                ),
                "requested tool.web.read",
                "completed tool.web.read",
                datetime(2026, 4, 13, 8, 0, 1, 500000, tzinfo=timezone.utc),
            ),
            (
                "\nNext I'll read a file.",
                ToolInvocation(
                    invocation_id="session-1:tool.file.read",
                    tool_id="tool.file.read",
                    session_id="session-1",
                    arguments={"file_path": "/tmp/alpha.txt"},
                    requested_at=datetime(2026, 4, 13, 8, 0, 2, tzinfo=timezone.utc),
                ),
                "requested tool.file.read",
                "read /tmp/alpha.txt",
                datetime(2026, 4, 13, 8, 0, 2, 500000, tzinfo=timezone.utc),
            ),
            (
                "\nFinally I'll grep.",
                ToolInvocation(
                    invocation_id="session-1:tool.file.search",
                    tool_id="tool.file.search",
                    session_id="session-1",
                    arguments={"query": "needle"},
                    requested_at=datetime(2026, 4, 13, 8, 0, 3, tzinfo=timezone.utc),
                ),
                "requested tool.file.search",
                "completed tool.file.search",
                datetime(2026, 4, 13, 8, 0, 3, 500000, tzinfo=timezone.utc),
            ),
        )

        for message, invocation, requested_detail, completed_detail, completed_at in invocations_and_events:
            stream_observer(message)
            tool_observer(
                ToolLifecycleEvent(
                    event_id=f"{invocation.invocation_id}:requested",
                    invocation=invocation,
                    phase="requested",
                    detail=requested_detail,
                    occurred_at=invocation.requested_at,
                )
            )
            tool_observer(
                ToolLifecycleEvent(
                    event_id=f"{invocation.invocation_id}:completed",
                    invocation=invocation,
                    phase="execution.completed",
                    detail=completed_detail,
                    occurred_at=completed_at,
                    execution=SimpleNamespace(outcome="success"),
                )
            )

        with tool_event_lock:
            feed = [item for item in tool_event_holder.get("feed", ()) if isinstance(item, _VisibleToolEvent)]
            self.assertEqual(len(feed), 6)
            self.assertNotIn("session-1:tool.web.search", {item.event.invocation.invocation_id for item in feed})

        fragments = shell_progress_runtime.render_turn_progress_fragments(
            shell,
            prompt="inspect the profile",
            tick=0,
            stream_text=latest_stream_text(stream_holder, stream_lock),
            tool_event_holder=tool_event_holder,
            tool_event_lock=tool_event_lock,
        )

        rendered = "".join(fragment[1] for fragment in fragments)
        self.assertLess(rendered.index("I'll search first."), rendered.index("┊ 🌐 Calling search…"))
        self.assertLess(rendered.index("Then I'll fetch."), rendered.index("┊ 🌐 Calling fetch…"))
        self.assertLess(rendered.index("Next I'll read a file."), rendered.index("┊ 📖 Calling read…"))
        self.assertLess(rendered.index("Finally I'll grep."), rendered.index("┊ 🔎 Calling grep…"))

    def test_tool_event_lines_compact_completed_tool_result_details(self) -> None:
        shell = self._make_shell()
        event = ToolLifecycleEvent(
            event_id="tool-event-search-complete",
            invocation=ToolInvocation(
                invocation_id="session-1:tool.web.search",
                tool_id="tool.web.search",
                session_id="session-1",
                arguments={"query": "xunzhuo liu researcher academic"},
            ),
            phase="execution.completed",
            detail=(
                "search: xunzhuo liu researcher academic\n"
                "1. result one\nhttps://example.com/1\nsummary line one\n"
                "2. result two\nhttps://example.com/2\nsummary line two"
            ),
            execution=SimpleNamespace(outcome="success"),
        )

        title, detail = shell._tool_event_lines(event)

        self.assertEqual(title, "Tool completed · tool.web.search")
        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertNotIn("\n", detail)
        self.assertIn("outcome: success", detail)
        self.assertIn("...", detail)

    def test_append_user_routes_writes_through_state_surface(self) -> None:
        shell = self._make_shell()
        self.assertFalse(hasattr(shell, "_append_user"))
        self.assertFalse(shell._handle_slash_command("/user set Call me Bit."))
        self.assertEqual(shell.transcript[-1].title, "Unknown command")

    def test_append_relationship_routes_clear_through_state_surface(self) -> None:
        shell = self._make_shell()
        self.assertFalse(hasattr(shell, "_append_relationship"))
        self.assertFalse(shell._handle_slash_command("/relationship clear"))
        self.assertEqual(shell.transcript[-1].title, "Unknown command")

    def test_render_pending_entries_inserts_blank_line_between_user_and_assistant(self) -> None:
        shell = self._make_shell()
        shell.console = _CaptureConsole(80)
        shell.transcript = [
            TranscriptEntry(kind="user", title="You", body="where did we leave off?"),
            TranscriptEntry(kind="assistant", title="Elephant Agent", body="We were refining the wake shell."),
        ]
        shell._rendered_entries = 0

        shell._render_pending_entries()

        self.assertEqual(len(shell.console.printed), 3)
        self.assertIn("where did we leave off?", shell.console.printed[0])
        self.assertEqual(shell.console.printed[1], "")
        self.assertIn("We were refining the wake shell.", shell.console.printed[2])

    def test_render_pending_entries_keeps_tooltrace_rows_tight(self) -> None:
        shell = self._make_shell()
        shell.console = _CaptureConsole(80)
        shell.transcript = [
            TranscriptEntry(kind="tooltrace", title="Tool trace", body="┊ 🌐 Calling search…"),
            TranscriptEntry(kind="tooltrace", title="Tool trace", body="┊ 🌐 search       xunzhuo liu  3.2s"),
        ]
        shell._rendered_entries = 0

        shell._render_pending_entries()

        self.assertEqual(len(shell.console.printed), 1)
        self.assertIn("Calling search", shell.console.printed[0])
        self.assertIn("xunzhuo liu", shell.console.printed[0])

    def test_render_pending_entries_keeps_inline_review_diff_in_same_tooltrace_block(self) -> None:
        shell = self._make_shell()
        shell.console = _CaptureConsole(120)
        shell.transcript = [
            TranscriptEntry(
                kind="tooltrace",
                title="Tool trace",
                body=(
                    "┊ 🛠 write        notes.md  0.2s\n"
                    "┊ 🛠 diff\n"
                    "a/notes.md → b/notes.md\n"
                    "@@ -1 +1,2 @@\n"
                    " hello\n"
                    "+world"
                ),
            )
        ]
        shell._rendered_entries = 0

        shell._render_pending_entries()

        self.assertEqual(len(shell.console.printed), 1)
        self.assertIn("diff", shell.console.printed[0])
        self.assertIn("a/notes.md → b/notes.md", shell.console.printed[0])
        self.assertIn("+world", shell.console.printed[0])

    def test_render_pending_entries_inserts_blank_line_between_tooltrace_and_assistant(self) -> None:
        shell = self._make_shell()
        shell.console = _CaptureConsole(80)
        shell.transcript = [
            TranscriptEntry(kind="tooltrace", title="Tool trace", body="┊ 📚 skill        apple-notes  0.3s"),
            TranscriptEntry(kind="assistant", title="Elephant Agent", body="I created the note in Apple Notes."),
        ]
        shell._rendered_entries = 0

        shell._render_pending_entries()

        self.assertEqual(len(shell.console.printed), 3)
        self.assertIn("apple-notes", shell.console.printed[0])
        self.assertEqual(shell.console.printed[1], "")
        self.assertIn("I created the note in Apple Notes.", shell.console.printed[2])

    def test_render_pending_entries_inserts_blank_line_between_reasoning_and_tooltrace(self) -> None:
        shell = self._make_shell()
        shell.console = _CaptureConsole(100)
        shell.transcript = [
            TranscriptEntry(
                kind="assistant",
                title="Elephant Agent",
                body="<think>Inspect the tool results first.</think>",
            ),
            TranscriptEntry(kind="tooltrace", title="Tool trace", body="┊ 🌐 fetch        https://example.com"),
        ]
        shell._rendered_entries = 0

        shell._render_pending_entries()

        self.assertEqual(len(shell.console.printed), 3)
        self.assertIn("🐾 Elephant Agent's Trail:", shell.console.printed[0])
        self.assertEqual(shell.console.printed[1], "")
        self.assertIn("https://example.com", shell.console.printed[2])

    def test_elephant_commands_redirect_to_cli_from_grow(self) -> None:
        shell = self._make_shell()

        handled = shell._handle_slash_command("/elephant nova")

        self.assertFalse(handled)
        self.assertEqual(shell.transcript[-1].title, "Unknown command")
        self.assertIn("/elephant", shell.transcript[-1].body)

    def test_providers_embeddings_status_surfaces_active_selection(self) -> None:
        shell = self._make_shell()

        with mock.patch.object(
            type(shell.runtime),
            "embedding_provider_summary",
            return_value={
                "source": "configured",
                "provider_id": "openai-compatible-embed",
                "provider_kind": "openai-compatible",
                "model_id": "text-embedding-3-large",
                "dimensions": 1536,
                "base_url": "https://api.example.test/v1",
                "secret_status": "stored",
                "embedding_bootstrap_status": "external",
            },
        ):
            handled = shell._handle_slash_command("/providers embeddings status")

        self.assertFalse(handled)
        self.assertEqual(shell.transcript[-1].title, "Embedding provider")
        self.assertIn("provider_id: openai-compatible-embed", shell.transcript[-1].body)
        self.assertIn("dimensions: 1536", shell.transcript[-1].body)

    def test_providers_embeddings_local_switches_back_to_default(self) -> None:
        shell = self._make_shell()

        with mock.patch.object(
            type(shell.runtime),
            "set_local_embedding_provider",
            return_value={
                "source": "local-default",
                "provider_id": "local-elephant",
                "model_id": "elephant-embed",
                "dimensions": 256,
                "embedding_bootstrap_status": "ready",
            },
        ) as set_local:
            handled = shell._handle_slash_command("/providers embeddings local")

        self.assertFalse(handled)
        set_local.assert_called_once_with()
        self.assertEqual(shell.transcript[-1].title, "Embedding provider updated")
        self.assertIn("selection: local-default", shell.transcript[-1].body)

    def test_refresh_shell_frame_resets_render_cursor_and_clears_console_in_alternate_screen(self) -> None:
        shell = self._make_shell_without_identity_update()
        shell.console = _CaptureConsole(120)
        shell._use_alternate_screen = True
        shell._rendered_entries = len(shell.transcript)

        shell._refresh_shell_frame()

        self.assertEqual(shell._rendered_entries, 0)
        self.assertEqual(shell.console.clear_calls, [True])
        self.assertEqual(len(shell.console.printed), 1)

    def test_conversational_dispatch_skips_shell_frame_refresh_when_frame_state_is_unchanged(self) -> None:
        shell = self._make_shell()

        with mock.patch.object(shell, "_refresh_shell_frame_if_needed") as refresh:
            handled = shell._dispatch("what tools do you have?")

        self.assertFalse(handled)
        refresh.assert_called_once_with()

    def test_clear_resets_transcript_and_replays_model_generated_opening(self) -> None:
        shell = self._make_shell(prime_transcript=True)
        shell._append_entry("user", "You", "stale message")
        self.assertGreater(len(shell.transcript), 1)
        original_session_id = shell.session_id

        with mock.patch.object(
            CliRuntime,
            "generate_opening_reply",
            return_value=SimpleNamespace(execution=SimpleNamespace(summary="startup-reply:I'm back in the thread.")),
        ) as generate_opening_reply:
            with mock.patch.object(shell, "_refresh_shell_frame") as refresh:
                handled = shell._handle_slash_command("/clear")

        self.assertFalse(handled)
        generate_opening_reply.assert_called_once()
        refresh.assert_called_once_with()
        self.assertNotEqual(shell.session_id, original_session_id)
        self.assertEqual(shell.runtime.inspect_session(shell.session_id).parent_episode_id, original_session_id)
        self.assertEqual(len(shell.transcript), 2)
        self.assertEqual(shell.transcript[0].kind, "assistant")
        self.assertEqual(shell.transcript[0].body, "startup-reply:I'm back in the thread.")
        self.assertEqual(shell.transcript[1].kind, "notice")
        self.assertIn("fresh Loop", shell.transcript[1].body)

    def test_append_growth_update_message_surfaces_visible_memory_checkpoint_reply(self) -> None:
        shell = self._make_shell()
        now = datetime.now(timezone.utc)
        initial = default_growth_state(shell.runtime.current_profile().state.profile_id, now=now)
        first = apply_turn_growth(
            initial,
            GrowthTurnSignals(
                session_id=shell.session_id,
                profile_id=initial.profile_id,
                total_tokens=64,
                captured_experiences=1,
                occurred_at=now,
            ),
        )
        update = apply_turn_growth(
            first.after.state,
            GrowthTurnSignals(
                session_id=shell.session_id,
                profile_id=initial.profile_id,
                total_tokens=64,
                captured_experiences=1,
                occurred_at=now,
            ),
        )

        shell._append_growth_update_message(update)

        self.assertEqual(shell.transcript[-1].kind, "growth")
        self.assertIn("checkpoint 1 in Memory I", shell.transcript[-1].body)
        self.assertEqual(shell.transcript[-1].meta, "memory · checkpoint")

    def test_dispatch_schedules_memory_followup_after_turn(self) -> None:
        shell = self._make_shell()
        shell.console = _CaptureConsole(120)
        outcome = SimpleNamespace(execution=SimpleNamespace(prompt_tokens=0))

        with mock.patch.object(shell, "_handle_conversational_surface_request", return_value=False):
            with mock.patch.object(shell, "_run_turn_with_progress", return_value=outcome):
                with mock.patch.object(shell, "_append_outcome"):
                    with mock.patch.object(shell, "_schedule_post_turn_background") as schedule:
                        with mock.patch.object(shell, "_refresh_shell_frame_if_needed") as refresh:
                            handled = shell._dispatch("hello there")

        self.assertFalse(handled)
        schedule.assert_called_once_with()
        refresh.assert_not_called()

    def test_refresh_shell_frame_if_needed_skips_when_frame_token_is_unchanged(self) -> None:
        shell = self._make_shell()
        shell._last_shell_frame_token = shell._current_shell_frame_token()

        with mock.patch.object(shell, "_refresh_shell_frame") as refresh:
            changed = shell._refresh_shell_frame_if_needed()

        self.assertFalse(changed)
        refresh.assert_not_called()

    def test_refresh_shell_frame_if_needed_skips_for_pending_context_compaction_frame(self) -> None:
        shell = self._make_shell()
        shell._last_shell_frame_token = shell._current_shell_frame_token()
        shell._pending_context_compaction_frame = {
            "prompt": "compact now",
            "tick": 4,
            "kernel_stage_events": (
                {
                    "payload": {
                        "stage": "context-compact",
                        "detail": "reason=usage tokens=1800->620 messages=80->12",
                        "recorded_at": "2026-04-17T08:00:00+00:00",
                    }
                },
            ),
        }

        with mock.patch.object(shell, "_refresh_shell_frame") as refresh:
            changed = shell._refresh_shell_frame_if_needed()

        self.assertFalse(changed)
        refresh.assert_not_called()

    def test_refresh_shell_frame_if_needed_skips_when_session_context_freezes(self) -> None:
        shell = self._make_shell()
        shell._last_shell_frame_token = shell._current_shell_frame_token()
        session = shell.runtime.inspect_session(shell.session_id)
        profile = shell.runtime._load_profile(session.personal_model_id)
        shell.runtime._write_snapshot(
            profile=profile.state,
            session=session,
            work_items=(),
            memories=(),
            plan=None,
            execution=ExecutionResult(
                execution_id="exec:first",
                episode_id=session.session_id,
                outcome="ok",
                summary="first reply",
            ),
            delivery=None,
            stages=(),
            event=EventEnvelope(
                event_id="event:first",
                event_type="turn.received",
                episode_id=session.session_id,
                source="cli",
                payload={"message": "first ask"},
            ),
            elephant_identity_text=profile.elephant_identity_text,
            state_focus=None,
            context=ContextBundle(
                bundle_id="bundle:first",
                episode_id=session.session_id,
                prompt_envelope=PromptEnvelope(
                    frozen_prefix="FIRST PREFIX",
                    session_snapshot="FIRST SNAPSHOT",
                    loop_context="FIRST INJECTIONS",
                ),
            ),
        )

        with mock.patch.object(shell, "_refresh_shell_frame") as refresh:
            changed = shell._refresh_shell_frame_if_needed()

        self.assertFalse(changed)
        refresh.assert_not_called()

    def test_opener_uses_continuity_driven_wake_summary(self) -> None:
        shell = self._make_shell()
        shell.runtime.update_user_state(
            profile_id=shell.runtime.inspect_session(shell.session_id).profile_id,
            text="User works on release operations and likes concise updates.",
        )
        state = shell.runtime.current_elephant_state()
        assert state is not None
        shell.runtime.repository.upsert_state(replace(state, active_task="Ship the release"))
        shell.transcript = []
        shell._rendered_entries = 0
        continuity = shell.runtime.inspect_continuity(session_id=shell.session_id)

        shell._prime_transcript()

        self.assertEqual(shell.transcript[0].kind, "assistant")
        self.assertNotIn("I am Atlas.", shell.transcript[0].body)
        self.assertIn("I'm here", shell.transcript[0].body)
        self.assertIn("I still have Ship the release", shell.transcript[0].body)
        self.assertIn("Ship the release", shell.transcript[0].body)
        self.assertNotIn("Resume active", shell.transcript[0].body)
        self.assertNotIn("internal projection", shell.transcript[0].body)

    def test_opener_hides_internal_defer_summary_when_no_actionable_current_work_exists(self) -> None:
        shell = self._make_shell()
        shell.runtime.update_user_state(
            profile_id=shell.runtime.inspect_session(shell.session_id).profile_id,
            text="User works on durable agent systems.",
        )
        shell.transcript = []
        shell._rendered_entries = 0

        shell._prime_transcript()

        self.assertNotIn("I am Atlas.", shell.transcript[0].body)
        self.assertIn("If something matters right now, name it", shell.transcript[0].body)
        self.assertNotIn("No actionable current work was available", shell.transcript[0].body)

    def test_opener_keeps_blank_user_profile_flow_light(self) -> None:
        shell = self._make_shell(prime_transcript=True)

        self.assertEqual(len(shell.transcript), 1)
        self.assertNotIn("I am Atlas.", shell.transcript[0].body)
        self.assertIn("I'm here", shell.transcript[0].body)
        self.assertIn("I'll start holding this new elephant with you.", shell.transcript[0].body)
        self.assertNotIn("Welcome back", shell.transcript[0].body)
        self.assertIn("What should I call you", shell.transcript[0].body)
        self.assertNotIn("one durable thing I should keep in mind from the start", shell.transcript[0].body)

    def test_prime_transcript_prefers_model_generated_opening_reply(self) -> None:
        shell = self._make_shell()
        shell.transcript = []
        shell._rendered_entries = 0

        with mock.patch.object(
            CliRuntime,
            "generate_opening_reply",
            return_value=SimpleNamespace(execution=SimpleNamespace(summary="startup-reply:I'm already here.")),
        ):
            shell._prime_transcript()

        self.assertEqual(len(shell.transcript), 1)
        self.assertEqual(shell.transcript[0].body, "startup-reply:I'm already here.")

    def test_prime_transcript_renders_new_elephant_opening_without_runtime_label(self) -> None:
        shell = self._make_shell(opened="Shaped new")
        shell.transcript = []
        shell._rendered_entries = 0

        with mock.patch.object(
            CliRuntime,
            "generate_opening_reply",
            return_value=SimpleNamespace(execution=SimpleNamespace(summary="startup-reply:I'm here. What should I call you?")),
        ) as generate_opening_reply:
            shell._prime_transcript()

        _, kwargs = generate_opening_reply.call_args
        prompt = kwargs["prompt"]
        self.assertIn("first message", prompt)
        self.assertNotIn("newly created companion", prompt)
        self.assertNotIn("Shaped new", prompt)
        self.assertNotIn("welcome back", shell.transcript[0].body.lower())

    def test_prime_transcript_passes_known_name_and_active_state_into_startup_prompt(self) -> None:
        shell = self._make_shell(
            opened="Opened elephant atlas",
            user_profile_text=render_user_profile_text(
                preferred_name="Bit",
                current_work="Building durable agent systems.",
            ),
        )
        state = shell.runtime.current_elephant_state()
        assert state is not None
        shell.runtime.repository.upsert_state(replace(state, active_task="Ship the release"))
        shell.transcript = []
        shell._rendered_entries = 0

        with mock.patch.object(
            CliRuntime,
            "generate_opening_reply",
            return_value=SimpleNamespace(execution=SimpleNamespace(summary="startup-reply:Bit, I still have the release State in view.")),
        ) as generate_opening_reply:
            shell._prime_transcript()

        _, kwargs = generate_opening_reply.call_args
        prompt = kwargs["prompt"]
        self.assertNotIn("Known name:", prompt)
        self.assertNotIn("their current context is Building durable agent systems.", prompt)
        self.assertNotIn("returning to an ongoing relationship", prompt)
        self.assertNotIn("Opened elephant atlas", prompt)
        self.assertNotIn('Live thread', prompt)
        self.assertNotIn("private posture signals only", prompt)
        self.assertIn("one natural message", prompt)
        self.assertEqual(shell.transcript[0].body, "startup-reply:Bit, I still have the release State in view.")

    def test_existing_elephant_open_does_not_render_user_questionnaire(self) -> None:
        shell = self._make_shell(
            opened="Opened elephant atlas",
            user_profile_text=render_user_profile_text(
                preferred_name="Bit",
                current_work="Building durable agent systems.",
            ),
            prime_transcript=True,
        )

        self.assertEqual(len(shell.transcript), 1)
        self.assertNotIn("I am Atlas.", shell.transcript[0].body)
        self.assertIn("I'm here, Bit.", shell.transcript[0].body)
        self.assertNotIn("What Should I Call You?", shell.transcript[0].body)
        self.assertNotIn("Where Did You Go To School?", shell.transcript[0].body)

    def test_opener_mentions_durable_thread_when_state_focus_is_missing(self) -> None:
        shell = self._make_shell(
            opened="Opened elephant atlas",
            user_profile_text=render_user_profile_text(
                preferred_name="Bit",
                current_work="Building durable agent systems.",
            ),
            prime_transcript=True,
        )

        self.assertEqual(len(shell.transcript), 1)
        self.assertIn("If something matters right now", shell.transcript[0].body)

    def test_existing_elephant_open_skips_user_onboarding_when_profile_fields_are_complete(self) -> None:
        shell = self._make_shell(
            opened="Opened elephant atlas",
            user_profile_text=render_user_profile_text(
                preferred_name="Bit",
                current_work="Building durable agent systems.",
                school="SJTU",
                current_city="Shanghai",
                mbti="INTJ",
                dream="Build a durable AI companion.",
                creative_hobby="Sketching interfaces.",
                media_hobby="Science fiction novels.",
                movement_hobby="Hiking.",
                boundaries="Do not be pushy with scheduling.",
            ),
            prime_transcript=True,
        )

        self.assertEqual(len(shell.transcript), 1)
        self.assertNotIn("I am Atlas.", shell.transcript[0].body)
        self.assertIn("I'm here, Bit.", shell.transcript[0].body)
        self.assertNotIn("stable profile", shell.transcript[0].body)
        self.assertIn("If something matters right now", shell.transcript[0].body)

    def test_state_focus_onboarding_skips_when_durable_state_focus_exists(self) -> None:
        shell = self._make_shell(
            opened="Opened elephant atlas",
            user_profile_text=render_user_profile_text(
                preferred_name="Bit",
                current_work="Building durable agent systems.",
            ),
        )
        state = shell.runtime.current_elephant_state()
        assert state is not None
        shell.runtime.repository.upsert_state(replace(state, active_task="Ship the durable companion shell"))
        shell.transcript = []
        shell._rendered_entries = 0

        shell._prime_transcript()

        self.assertEqual(len(shell.transcript), 1)
        self.assertNotIn("If there's something you want me to keep carrying", shell.transcript[-1].body)

    def test_shell_welcome_copy_and_boot_delays_support_a_visible_entry(self) -> None:
        self.assertEqual(SHELL_WELCOME_HEADLINE, "Your elephant still knows the path.")
        self.assertAlmostEqual((STARTUP_SEQUENCE_STEP_DELAY * 4) + STARTUP_SEQUENCE_FINAL_DELAY, 3.0, delta=0.12)
        self.assertGreaterEqual(STARTUP_SEQUENCE_STEP_DELAY, 0.50)
        self.assertGreaterEqual(STARTUP_SEQUENCE_FINAL_DELAY, 0.50)


if __name__ == "__main__":
    unittest.main()
