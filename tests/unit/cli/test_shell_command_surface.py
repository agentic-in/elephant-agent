from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
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
from apps.cli.shell_progress import (
    _VisibleToolEvent,
    latest_stream_text,
    reset_stream_text,
    stream_text_tracker,
    turn_tool_progress_lines,
)
import apps.cli.shell_progress_runtime as shell_progress_runtime
from apps.cli.shell_render import _render_tooltrace_body_line
import apps.cli.shell_render as shell_render
from apps.cli.shell_banner import (
    _learning_job_execution_summary,
    _skill_affinity_summary,
)
import apps.cli.shell_progress_trace as shell_progress_trace
from apps.cli.shell_clarify import (
    ShellClarifyState,
    render_clarify_fragments,
    route_clarify_answer,
)
from apps.cli.shell_stack import (
    FormattedTextControl as StackFormattedTextControl,
    ScrollablePane,
    Window as StackWindow,
)
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
)
from packages.contracts.runtime import StateFocusDecision
from packages.growth import GrowthTurnSignals, apply_turn_growth, default_growth_state
from packages.state import render_user_profile_text
from packages.skills import SkillSearchEntry
from packages.tools import ToolApprovalResult, ToolLifecycleEvent, ToolInvocation
from tests.unit.cli.shell_test_support import (
    CaptureConsole as _CaptureConsole,
    ShellTestBase,
    StubConsole as _StubConsole,
    WebPageStubServer as _WebPageStubServer,
)


class ShellCommandSurfaceTest(ShellTestBase):
    def test_shell_uses_normal_terminal_scrollback_by_default(self) -> None:
        shell = self._make_shell_without_identity_update()

        self.assertFalse(shell._use_alternate_screen)

    def test_shell_allows_opt_in_alternate_screen(self) -> None:
        with mock.patch.dict(os.environ, {"ELEPHANT_ALT_SCREEN": "1"}):
            shell = self._make_shell_without_identity_update()

        self.assertTrue(shell._use_alternate_screen)

    def test_refresh_shell_frame_does_not_clear_or_replay_same_frame_in_scrollback_mode(
        self,
    ) -> None:
        shell = self._make_shell_without_identity_update()
        shell.console = _CaptureConsole(100)
        shell._last_shell_frame_token = shell._current_shell_frame_token()
        shell._rendered_entries = 2

        shell._refresh_shell_frame()

        self.assertEqual(shell.console.clear_calls, [])
        self.assertEqual(shell.console.printed, [])
        self.assertEqual(shell._rendered_entries, 2)

    def test_refresh_shell_frame_clears_and_replays_in_alternate_screen_mode(
        self,
    ) -> None:
        shell = self._make_shell_without_identity_update()
        shell.console = _CaptureConsole(100)
        shell._use_alternate_screen = True
        shell._last_shell_frame_token = shell._current_shell_frame_token()
        shell._rendered_entries = 2

        shell._refresh_shell_frame()

        self.assertEqual(shell.console.clear_calls, [True])
        self.assertGreaterEqual(len(shell.console.printed), 1)
        self.assertEqual(shell._rendered_entries, 0)

    def test_prime_transcript_uses_elephant_state_name_for_assistant_title(
        self,
    ) -> None:
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
            shell = ProductizedShell(
                runtime, session_id=session.session_id, opened="Shaped new"
            )
            completer = ShellCompleter(shell)

            root_commands = {
                item.text for item in completer.get_completions(Document("/"), None)
            }
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

            filtered_skill_commands = {
                item.text
                for item in completer.get_completions(Document("/apple"), None)
            }
            self.assertNotIn("/apple-notes", filtered_skill_commands)

            learn_commands = {
                item.text
                for item in completer.get_completions(Document("/learn "), None)
            }
            self.assertIn("queue", learn_commands)
            self.assertIn("run", learn_commands)
            self.assertIn("start", learn_commands)
            self.assertIn("status", learn_commands)
            self.assertIn("history", learn_commands)

            tool_commands = {
                item.text
                for item in completer.get_completions(Document("/tools "), None)
            }
            self.assertIn("inspect", tool_commands)
            self.assertIn("enable", tool_commands)
            self.assertIn("disable", tool_commands)
            self.assertIn("install", tool_commands)
            self.assertIn("run", tool_commands)

            skill_commands = {
                item.text
                for item in completer.get_completions(Document("/skills "), None)
            }
            self.assertIn("inspect", skill_commands)
            self.assertIn("enable", skill_commands)
            self.assertIn("disable", skill_commands)
            self.assertIn("install", skill_commands)
            self.assertIn("search", skill_commands)

            cron_commands = {
                item.text
                for item in completer.get_completions(Document("/cron "), None)
            }
            self.assertIn("create", cron_commands)
            self.assertIn("inspect", cron_commands)
            self.assertIn("pause", cron_commands)
            self.assertIn("resume", cron_commands)
            self.assertIn("remove", cron_commands)

            removed_whoami_commands = {
                item.text
                for item in completer.get_completions(Document("/whoami "), None)
            }
            self.assertEqual(set(), removed_whoami_commands)

            gateway_commands = {
                item.text
                for item in completer.get_completions(Document("/gateway "), None)
            }
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

    def test_latest_learning_notice_surfaces_completed_learning_result_once(
        self,
    ) -> None:
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

        learning_entries = tuple(
            entry for entry in shell.transcript if entry.title == "Learning"
        )
        self.assertEqual(len(learning_entries), 1)
        self.assertIn(
            "remembered the direct review preference", learning_entries[0].body
        )

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

        shell = ProductizedShell(
            runtime, session_id=session.episode_id, opened="Opened elephant atlas"
        )
        shell._append_latest_learning_result()

        self.assertFalse(any(entry.title == "Learning" for entry in shell.transcript))

    def test_conversational_surface_requests_list_tools_on_explicit_show_list_verbs(
        self,
    ) -> None:
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

        handled_skills = shell._handle_conversational_surface_request(
            "what skills do you have?"
        )

        self.assertFalse(handled_skills)
        self.assertEqual(len(shell.transcript), original_len)

    def test_skills_search_routes_through_skill_search_tool_and_records_tooltrace(
        self,
    ) -> None:
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

        tool_entries = [
            entry for entry in shell.transcript if entry.kind == "tooltrace"
        ]
        if tool_entries:
            self.assertIn("Calling skills", tool_entries[-1].body)
            self.assertIn("┊ 📚 skills", tool_entries[-1].body)
        self.assertEqual(shell.transcript[-1].title, "Skill search")
        self.assertIn("github:openai/skills/apple-notes", shell.transcript[-1].body)

    def test_plain_turn_with_explicit_skill_name_no_longer_routes_skill_body(
        self,
    ) -> None:
        shell = self._make_shell()
        outcome = mock.Mock()
        with (
            mock.patch.object(
                shell, "_run_turn_with_progress", return_value=outcome
            ) as run_turn,
            mock.patch.object(shell, "_append_outcome") as append_outcome,
            mock.patch.object(
                shell, "_show_growth_celebration_if_needed", return_value=None
            ),
            mock.patch.object(shell, "_append_growth_update_message"),
            mock.patch.object(shell, "_refresh_shell_frame"),
            mock.patch.object(type(shell.runtime), "inspect_skill") as inspect_skill,
        ):
            handled = shell._dispatch("use gif-search to find a cat reaction gif")

        self.assertFalse(handled)
        inspect_skill.assert_not_called()
        self.assertEqual(
            run_turn.call_args.args[0], "use gif-search to find a cat reaction gif"
        )
        self.assertIsNone(run_turn.call_args.kwargs["event_payload"])
        append_outcome.assert_called_once_with(outcome)

    def test_dispatch_clears_pending_context_compaction_frame_before_next_turn(
        self,
    ) -> None:
        shell = self._make_shell()
        shell._pending_context_compaction_frame = {
            "prompt": "previous",
            "tick": 0,
            "kernel_stage_events": (),
        }
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
            mock.patch.object(
                shell, "_handle_conversational_surface_request", return_value=False
            ),
            mock.patch.object(shell, "_run_turn_with_progress", return_value=outcome),
            mock.patch.object(shell, "_append_outcome"),
            mock.patch.object(
                shell, "_show_growth_celebration_if_needed", return_value=None
            ),
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
            mock.patch.object(
                shell, "_handle_conversational_surface_request", return_value=False
            ),
            mock.patch.object(shell, "_run_turn_with_progress", side_effect=run_turn),
            mock.patch.object(shell, "_append_outcome"),
            mock.patch.object(
                shell, "_show_growth_celebration_if_needed", return_value=None
            ),
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
            mock.patch.object(
                shell, "_handle_conversational_surface_request", return_value=False
            ),
            mock.patch.object(shell, "_run_turn_with_progress", return_value=outcome),
            mock.patch.object(shell, "_append_outcome"),
            mock.patch.object(
                shell, "_show_growth_celebration_if_needed", return_value=None
            ),
            mock.patch.object(shell, "_append_growth_update_message"),
            mock.patch.object(shell, "_refresh_shell_frame_if_needed"),
        ):
            handled = shell._dispatch("continue the thread")

        self.assertFalse(handled)
        self.assertEqual(shell._last_provider_prompt_tokens, 0)
        self.assertEqual(shell._last_prompt_tokens, 6_200)

    def test_plain_turn_with_contextual_skill_phrase_no_longer_routes_skill_body(
        self,
    ) -> None:
        shell = self._make_shell()
        outcome = mock.Mock()
        with (
            mock.patch.object(
                shell, "_run_turn_with_progress", return_value=outcome
            ) as run_turn,
            mock.patch.object(shell, "_append_outcome") as append_outcome,
            mock.patch.object(
                shell, "_show_growth_celebration_if_needed", return_value=None
            ),
            mock.patch.object(shell, "_append_growth_update_message"),
            mock.patch.object(shell, "_refresh_shell_frame"),
            mock.patch.object(type(shell.runtime), "inspect_skill") as inspect_skill,
        ):
            handled = shell._dispatch("打开我的苹果备忘录 写一个 elephant 的介绍方案")

        self.assertFalse(handled)
        inspect_skill.assert_not_called()
        self.assertEqual(
            run_turn.call_args.args[0], "打开我的苹果备忘录 写一个 elephant 的介绍方案"
        )
        self.assertIsNone(run_turn.call_args.kwargs["event_payload"])
        append_outcome.assert_called_once_with(outcome)

    def test_skill_slash_specs_include_full_local_skill_hub_not_first_page_only(
        self,
    ) -> None:
        shell = self._make_shell()

        spec_ids = {spec.skill_id for spec in shell.skill_slash_specs()}

        self.assertGreater(len(spec_ids), 96)
        self.assertIn("gif-search", spec_ids)

    def test_skills_enable_routes_through_runtime_skill_catalog(self) -> None:
        shell = self._make_shell()
        with mock.patch.object(
            type(shell.runtime), "set_skill_enabled"
        ) as set_skill_enabled:
            set_skill_enabled.return_value = SimpleNamespace(
                skill_id="shell-execution", enabled=True
            )
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
        self.assertIn(
            "detail: installed via GitHub (trusted)", shell.transcript[-1].body
        )
        self.assertIn(
            "source_reference: github:openai/skills/apple-notes",
            shell.transcript[-1].body,
        )
        self.assertIn("install_action: install", shell.transcript[-1].body)
        self.assertIn("install_requester: operator", shell.transcript[-1].body)

    def test_growth_panel_keeps_removed_procedural_memory_out_of_learning_overview(
        self,
    ) -> None:
        shell = self._make_shell()
        session = shell.runtime.inspect_session(shell.session_id)

        continuity = shell.runtime.inspect_continuity(session_id=shell.session_id)
        provider = dict(shell.runtime.provider_summary())
        lines = shell._recent_activity_lines(session, continuity, provider)

        self.assertFalse(any("Release State Recovery" in line for line in lines))
        self.assertIn("latest · no captured grounded experience yet", lines)

    def test_growth_panel_filters_noisy_failure_experiences_from_learning_overview(
        self,
    ) -> None:
        shell = self._make_shell()
        session = shell.runtime.inspect_session(shell.session_id)

        continuity = shell.runtime.inspect_continuity(session_id=shell.session_id)
        provider = dict(shell.runtime.provider_summary())
        lines = shell._recent_activity_lines(session, continuity, provider)

        self.assertFalse(
            any("skill manager is having some trouble" in line for line in lines)
        )
        self.assertIn("latest · no captured grounded experience yet", lines)

    def test_conversational_surface_request_reads_specific_web_page_without_hitting_model(
        self,
    ) -> None:
        shell = self._make_shell()
        server = _WebPageStubServer().start()
        self.addCleanup(server.close)

        with mock.patch(
            "apps.cli.shell_progress_runtime.animations_enabled", return_value=False
        ):
            handled = shell._handle_conversational_surface_request(
                f"can you read {server.url}?"
            )

        self.assertTrue(handled)
        self.assertEqual(shell.transcript[-1].kind, "assistant")
        self.assertIn("I opened that page", shell.transcript[-1].body)
        self.assertIn("Atlas Journal", shell.transcript[-1].body)
        self.assertIn("durable elephant continuity loop", shell.transcript[-1].body)
        self.assertIn(server.url.rstrip("/"), shell.transcript[-1].meta)

    def test_provider_configure_cancels_when_wizard_is_escaped(self) -> None:
        shell = self._make_shell()

        with (
            mock.patch(
                "apps.cli.shell_impl.run_provider_selection_wizard",
                return_value=WIZARD_BACK,
            ),
            mock.patch.object(
                CliRuntime,
                "set_default_provider",
                autospec=True,
            ) as set_default_provider,
        ):
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

        with (
            mock.patch(
                "apps.cli.shell_impl.run_provider_selection_wizard",
                return_value=WIZARD_BACK,
            ),
            mock.patch.object(
                CliRuntime,
                "set_default_provider",
                autospec=True,
            ) as set_default_provider,
        ):
            shell._append_models([])

        set_default_provider.assert_not_called()
        self.assertEqual(shell.transcript[-1].body, "Model setup cancelled.")

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
        self.assertEqual(
            style_map["progress-tool-label"], f"fg:{BRAND_ACCENT_STRONG} bold"
        )
        self.assertEqual(style_map["stream-response-body"], f"fg:{BRAND_LIGHT}")
        self.assertEqual(
            style_map["status-bar-growth-empty"], f"bg:#173141 fg:{BRAND_ACCENT}"
        )
        self.assertEqual(
            style_map["completion-menu.completion.current"],
            f"bg:#21475c fg:{BRAND_ACCENT_STRONG} bold",
        )
        self.assertEqual(style_map["scrollbar.button"], f"bg:{BRAND_ACCENT}")
        self.assertNotIn("bg:", style_map[""])
        self.assertNotIn("bg:", style_map["composer-prefix"])
        self.assertNotIn("bottom-toolbar", style_map)

    def test_live_composer_body_wraps_running_surface_in_scrollable_pane(self) -> None:
        if (
            ScrollablePane is None
            or StackWindow is None
            or StackFormattedTextControl is None
        ):
            self.skipTest("prompt_toolkit scrollable pane is unavailable")
        shell = self._make_shell()
        input_window = StackWindow(
            StackFormattedTextControl("input"), height=1, dont_extend_height=True
        )
        command_palette = StackWindow(
            StackFormattedTextControl("palette"), height=1, dont_extend_height=True
        )
        progress_window = StackWindow(
            StackFormattedTextControl("trace"), dont_extend_height=True
        )

        body = build_composer_body(
            shell,
            input_window=input_window,
            command_palette=command_palette,
            top_windows=(progress_window,),
        )

        self.assertIsInstance(body, ScrollablePane)

    def test_command_palette_reserves_at_least_six_visible_rows(self) -> None:
        self.assertGreaterEqual(COMMAND_PALETTE_VISIBLE_ROWS, 6)


if __name__ == "__main__":
    unittest.main()
