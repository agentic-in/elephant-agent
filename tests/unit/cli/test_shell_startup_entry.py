from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from apps.cli.runtime import CliRuntime
from apps.cli.shell import (
    PendingShellCommand,
    ProductizedShell,
    SHELL_WELCOME_HEADLINE,
    STARTUP_SEQUENCE_FINAL_DELAY,
    STARTUP_SEQUENCE_STEP_DELAY,
    TranscriptEntry,
)
from apps.cli.shell_composer import (
    _state_focus_notice_fragments,
    _startup_transition_result,
)
from packages.contracts import (
    ContextBundle,
    EventEnvelope,
    ExecutionResult,
    PromptEnvelope,
)
from packages.growth import GrowthTurnSignals, apply_turn_growth, default_growth_state
from packages.state import render_user_profile_text
from packages.tools import ToolInvocation, ToolLifecycleEvent
from tests.unit.cli.shell_test_support import (
    CaptureConsole as _CaptureConsole,
    ShellTestBase,
)


class ShellStartupEntryTest(ShellTestBase):
    def test_run_dispatches_queued_startup_turn_immediately_after_prime(self) -> None:
        shell = self._make_shell()
        shell._pending_commands.append(PendingShellCommand(command="帮我看下这个"))
        commands = iter((PendingShellCommand(command="__elephant.startup.prime__"),))

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
            mock.patch.object(
                shell, "_startup_state_focus_dispatch_ready", return_value=True
            ),
            mock.patch.object(shell, "_dispatch", return_value=True) as dispatch,
            mock.patch.object(shell, "_render_pending_entries"),
            mock.patch.object(shell, "_next_command", side_effect=next_command),
            mock.patch.object(shell.console, "print"),
        ):
            shell.run()

        prime.assert_called_once_with()
        dispatch.assert_called_once_with(PendingShellCommand(command="帮我看下这个"))

    def test_prepare_startup_surface_runs_in_background_and_refreshes_skills(
        self,
    ) -> None:
        shell = self._make_shell()

        class _ImmediateThread:
            def __init__(self, *, target, name=None, daemon=None):
                self._target = target

            def start(self) -> None:
                self._target()

        with (
            mock.patch(
                "apps.cli.shell_methods_ui.threading.Thread",
                side_effect=_ImmediateThread,
            ),
            mock.patch.object(
                type(shell.runtime), "prepare_session_surface"
            ) as prepare_surface,
            mock.patch.object(shell, "_refresh_skill_slash_specs") as refresh_skills,
        ):
            shell._prepare_startup_surface()

        prepare_surface.assert_called_once_with(shell.session_id)
        refresh_skills.assert_called_once_with()
        self.assertTrue(shell._startup_surface_prepared)

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

    def test_render_pending_entries_inserts_blank_line_between_user_and_assistant(
        self,
    ) -> None:
        shell = self._make_shell()
        shell.console = _CaptureConsole(80)
        shell.transcript = [
            TranscriptEntry(kind="user", title="You", body="where did we leave off?"),
            TranscriptEntry(
                kind="assistant",
                title="Elephant Agent",
                body="We were refining the wake shell.",
            ),
        ]
        shell._rendered_entries = 0

        shell._render_pending_entries()

        rendered = "\n".join(shell.console.printed)
        self.assertIn("where did we leave off?", rendered)
        self.assertIn("We were refining the wake shell.", rendered)

    def test_render_pending_entries_keeps_tooltrace_rows_tight(self) -> None:
        shell = self._make_shell()
        shell.console = _CaptureConsole(80)
        shell.transcript = [
            TranscriptEntry(
                kind="tooltrace", title="Tool trace", body="┊ 🌐 Calling search…"
            ),
            TranscriptEntry(
                kind="tooltrace",
                title="Tool trace",
                body="┊ 🌐 search       xunzhuo liu  3.2s",
            ),
        ]
        shell._rendered_entries = 0

        shell._render_pending_entries()

        self.assertEqual(len(shell.console.printed), 1)
        self.assertIn("Calling search", shell.console.printed[0])
        self.assertIn("xunzhuo liu", shell.console.printed[0])

    def test_render_pending_entries_keeps_inline_review_diff_in_same_tooltrace_block(
        self,
    ) -> None:
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

    def test_render_pending_entries_inserts_blank_line_between_tooltrace_and_assistant(
        self,
    ) -> None:
        shell = self._make_shell()
        shell.console = _CaptureConsole(80)
        shell.transcript = [
            TranscriptEntry(
                kind="tooltrace",
                title="Tool trace",
                body="┊ 📚 skill        apple-notes  0.3s",
            ),
            TranscriptEntry(
                kind="assistant",
                title="Elephant Agent",
                body="I created the note in Apple Notes.",
            ),
        ]
        shell._rendered_entries = 0

        shell._render_pending_entries()

        rendered = "\n".join(shell.console.printed)
        self.assertIn("apple-notes", rendered)
        self.assertIn("I created the note in Apple Notes.", rendered)

    def test_render_pending_entries_inserts_blank_line_between_reasoning_and_tooltrace(
        self,
    ) -> None:
        shell = self._make_shell()
        shell.console = _CaptureConsole(100)
        shell.transcript = [
            TranscriptEntry(
                kind="assistant",
                title="Elephant Agent",
                body="<think>Inspect the tool results first.</think>",
            ),
            TranscriptEntry(
                kind="tooltrace",
                title="Tool trace",
                body="┊ 🌐 fetch        https://example.com",
            ),
        ]
        shell._rendered_entries = 0

        shell._render_pending_entries()

        rendered = "\n".join(shell.console.printed)
        self.assertIn("🐾 Elephant Agent's Trail:", rendered)
        self.assertIn("https://example.com", rendered)

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

    def test_refresh_shell_frame_resets_render_cursor_and_clears_console_in_alternate_screen(
        self,
    ) -> None:
        shell = self._make_shell_without_identity_update()
        shell.console = _CaptureConsole(120)
        shell._use_alternate_screen = True
        shell._rendered_entries = len(shell.transcript)

        shell._refresh_shell_frame()

        self.assertEqual(shell._rendered_entries, 0)
        self.assertEqual(shell.console.clear_calls, [True])
        self.assertEqual(len(shell.console.printed), 1)

    def test_conversational_dispatch_skips_shell_frame_refresh_when_frame_state_is_unchanged(
        self,
    ) -> None:
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

        with (
            mock.patch.object(
                CliRuntime,
                "generate_opening_reply",
                return_value=SimpleNamespace(
                    execution=SimpleNamespace(
                        summary="startup-reply:I'm back in the thread."
                    )
                ),
            ) as generate_opening_reply,
            mock.patch(
                "apps.learning_worker_runtime.ensure_learning_worker_running",
                return_value=True,
            ),
            mock.patch.object(shell, "_refresh_shell_frame") as refresh,
        ):
            handled = shell._handle_slash_command("/clear")

        self.assertFalse(handled)
        generate_opening_reply.assert_called_once()
        refresh.assert_called_once_with()
        self.assertNotEqual(shell.session_id, original_session_id)
        self.assertEqual(
            shell.runtime.inspect_session(shell.session_id).parent_episode_id,
            original_session_id,
        )
        self.assertEqual(len(shell.transcript), 2)
        self.assertEqual(shell.transcript[0].kind, "assistant")
        self.assertEqual(
            shell.transcript[0].body, "startup-reply:I'm back in the thread."
        )
        self.assertEqual(shell.transcript[1].kind, "notice")
        self.assertIn("fresh Episode", shell.transcript[1].body)
        jobs = shell.runtime.repository.list_learning_jobs(
            episode_id=original_session_id
        )
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].trigger, "episode_close")

    def test_exit_closes_episode_and_queues_episode_close_learning(self) -> None:
        shell = self._make_shell(prime_transcript=True)
        original_session_id = shell.session_id

        with mock.patch(
            "apps.learning_worker_runtime.ensure_learning_worker_running",
            return_value=True,
        ):
            handled = shell._handle_slash_command("/exit")

        self.assertTrue(handled)
        closed = shell.runtime.repository.load_episode(original_session_id)
        self.assertIsNotNone(closed)
        assert closed is not None
        self.assertEqual(closed.status, "closed")
        jobs = shell.runtime.repository.list_learning_jobs(
            episode_id=original_session_id
        )
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].trigger, "episode_close")

    def test_append_growth_update_message_surfaces_visible_understanding_checkpoint_reply(
        self,
    ) -> None:
        shell = self._make_shell()
        now = datetime.now(timezone.utc)
        initial = default_growth_state(
            shell.runtime.current_profile().state.profile_id, now=now
        )
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
        self.assertIn("checkpoint 1 in Evidence I", shell.transcript[-1].body)
        self.assertEqual(shell.transcript[-1].meta, "understanding · checkpoint")

    def test_dispatch_schedules_growth_followup_after_turn(self) -> None:
        shell = self._make_shell()
        shell.console = _CaptureConsole(120)
        outcome = SimpleNamespace(execution=SimpleNamespace(prompt_tokens=0))

        with mock.patch.object(
            shell, "_handle_conversational_surface_request", return_value=False
        ):
            with mock.patch.object(
                shell, "_run_turn_with_progress", return_value=outcome
            ):
                with mock.patch.object(shell, "_append_outcome"):
                    with mock.patch.object(
                        shell, "_schedule_post_turn_background"
                    ) as schedule:
                        with mock.patch.object(
                            shell, "_refresh_shell_frame_if_needed"
                        ) as refresh:
                            handled = shell._dispatch("hello there")

        self.assertFalse(handled)
        schedule.assert_called_once_with()
        refresh.assert_not_called()

    def test_refresh_shell_frame_if_needed_skips_when_frame_token_is_unchanged(
        self,
    ) -> None:
        shell = self._make_shell()
        shell._last_shell_frame_token = shell._current_shell_frame_token()

        with mock.patch.object(shell, "_refresh_shell_frame") as refresh:
            changed = shell._refresh_shell_frame_if_needed()

        self.assertFalse(changed)
        refresh.assert_not_called()

    def test_refresh_shell_frame_if_needed_skips_for_pending_context_compaction_frame(
        self,
    ) -> None:
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

    def test_refresh_shell_frame_if_needed_skips_when_session_context_freezes(
        self,
    ) -> None:
        shell = self._make_shell()
        shell._last_shell_frame_token = shell._current_shell_frame_token()
        session = shell.runtime.inspect_session(shell.session_id)
        profile = shell.runtime._load_profile(session.personal_model_id)
        shell.runtime._write_snapshot(
            profile=profile.state,
            session=session,
            work_items=(),
            recall_items=(),
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


if __name__ == "__main__":
    unittest.main()
