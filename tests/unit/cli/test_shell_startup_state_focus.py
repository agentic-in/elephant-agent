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


class ShellStartupStateFocusTest(ShellTestBase):
    def test_opener_uses_continuity_driven_wake_summary(self) -> None:
        shell = self._make_shell()
        shell.runtime.update_user_state(
            profile_id=shell.runtime.inspect_session(
                shell.session_id
            ).personal_model_id,
            text="User works on release operations and likes concise updates.",
        )
        state = shell.runtime.current_elephant_state()
        assert state is not None
        shell.runtime.repository.upsert_state(
            replace(state, current_context_note="Ship the release")
        )
        shell.transcript = []
        shell._rendered_entries = 0
        continuity = shell.runtime.inspect_continuity(session_id=shell.session_id)

        shell._prime_transcript()

        self.assertEqual(shell.transcript[0].kind, "assistant")
        self.assertNotIn("I am Atlas.", shell.transcript[0].body)
        self.assertIn("I'm here", shell.transcript[0].body)
        self.assertIn(
            "If something matters right now, name it", shell.transcript[0].body
        )
        self.assertNotIn("Resume active", shell.transcript[0].body)
        self.assertNotIn("internal projection", shell.transcript[0].body)

    def test_opener_hides_internal_defer_summary_when_no_actionable_current_work_exists(
        self,
    ) -> None:
        shell = self._make_shell()
        shell.runtime.update_user_state(
            profile_id=shell.runtime.inspect_session(
                shell.session_id
            ).personal_model_id,
            text="User works on durable agent systems.",
        )
        shell.transcript = []
        shell._rendered_entries = 0

        shell._prime_transcript()

        self.assertNotIn("I am Atlas.", shell.transcript[0].body)
        self.assertIn(
            "If something matters right now, name it", shell.transcript[0].body
        )
        self.assertNotIn(
            "No actionable current work was available", shell.transcript[0].body
        )

    def test_opener_keeps_blank_user_profile_flow_light(self) -> None:
        shell = self._make_shell(prime_transcript=True)

        self.assertEqual(len(shell.transcript), 1)
        self.assertNotIn("I am Atlas.", shell.transcript[0].body)
        self.assertIn("I'm here", shell.transcript[0].body)
        self.assertIn(
            "I'll start holding this new elephant with you.", shell.transcript[0].body
        )
        self.assertNotIn("Welcome back", shell.transcript[0].body)
        self.assertIn("What should I call you", shell.transcript[0].body)
        self.assertNotIn(
            "one durable thing I should keep in mind from the start",
            shell.transcript[0].body,
        )

    def test_prime_transcript_prefers_model_generated_opening_reply(self) -> None:
        shell = self._make_shell()
        shell.transcript = []
        shell._rendered_entries = 0

        with mock.patch.object(
            CliRuntime,
            "generate_opening_reply",
            return_value=SimpleNamespace(
                execution=SimpleNamespace(summary="startup-reply:I'm already here.")
            ),
        ):
            shell._prime_transcript()

        self.assertEqual(len(shell.transcript), 1)
        self.assertEqual(shell.transcript[0].body, "startup-reply:I'm already here.")

    def test_prime_transcript_renders_new_elephant_opening_without_runtime_label(
        self,
    ) -> None:
        shell = self._make_shell(opened="Shaped new")
        shell.transcript = []
        shell._rendered_entries = 0

        with mock.patch.object(
            CliRuntime,
            "generate_opening_reply",
            return_value=SimpleNamespace(
                execution=SimpleNamespace(
                    summary="startup-reply:I'm here. What should I call you?"
                )
            ),
        ) as generate_opening_reply:
            shell._prime_transcript()

        _, kwargs = generate_opening_reply.call_args
        prompt = kwargs["prompt"]
        self.assertIn("first message", prompt)
        self.assertNotIn("newly created companion", prompt)
        self.assertNotIn("Shaped new", prompt)
        self.assertNotIn("welcome back", shell.transcript[0].body.lower())

    def test_prime_transcript_passes_known_name_and_active_state_into_startup_prompt(
        self,
    ) -> None:
        shell = self._make_shell(
            opened="Opened elephant atlas",
            user_profile_text=render_user_profile_text(
                preferred_name="Bit",
                current_work="Building durable agent systems.",
            ),
        )
        state = shell.runtime.current_elephant_state()
        assert state is not None
        shell.runtime.repository.upsert_state(
            replace(state, current_context_note="Ship the release")
        )
        shell.transcript = []
        shell._rendered_entries = 0

        with mock.patch.object(
            CliRuntime,
            "generate_opening_reply",
            return_value=SimpleNamespace(
                execution=SimpleNamespace(
                    summary="startup-reply:Bit, I still have the release State in view."
                )
            ),
        ) as generate_opening_reply:
            shell._prime_transcript()

        _, kwargs = generate_opening_reply.call_args
        prompt = kwargs["prompt"]
        self.assertNotIn("Known name:", prompt)
        self.assertNotIn(
            "their current context is Building durable agent systems.", prompt
        )
        self.assertNotIn("returning to an ongoing relationship", prompt)
        self.assertNotIn("Opened elephant atlas", prompt)
        self.assertNotIn("Live thread", prompt)
        self.assertNotIn("private posture signals only", prompt)
        self.assertIn("one natural next question", prompt)
        self.assertEqual(
            shell.transcript[0].body,
            "startup-reply:Bit, I still have the release State in view.",
        )

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

    def test_existing_elephant_open_skips_user_onboarding_when_profile_fields_are_complete(
        self,
    ) -> None:
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
        shell.runtime.repository.upsert_state(
            replace(state, current_context_note="Ship the durable companion shell")
        )
        shell.transcript = []
        shell._rendered_entries = 0

        shell._prime_transcript()

        self.assertEqual(len(shell.transcript), 1)
        self.assertNotIn(
            "If there's something you want me to keep carrying",
            shell.transcript[-1].body,
        )

    def test_shell_welcome_copy_and_boot_delays_support_a_visible_entry(self) -> None:
        self.assertEqual(SHELL_WELCOME_HEADLINE, "Your elephant still knows the path.")
        self.assertAlmostEqual(
            (STARTUP_SEQUENCE_STEP_DELAY * 4) + STARTUP_SEQUENCE_FINAL_DELAY,
            3.0,
            delta=0.12,
        )
        self.assertGreaterEqual(STARTUP_SEQUENCE_STEP_DELAY, 0.50)
        self.assertGreaterEqual(STARTUP_SEQUENCE_FINAL_DELAY, 0.50)

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
                    recorded_at=datetime(
                        2026, 4, 17, 8, 0, 0, 12000, tzinfo=timezone.utc
                    ),
                ),
            ),
            plan=None,
            work_items=(),
            recall_items=(),
        )

        shell._append_outcome(outcome)

        self.assertEqual(shell.transcript[-1].kind, "assistant")
        self.assertEqual(shell.transcript[-1].body, "The release note draft is ready.")
        self.assertEqual(
            shell.transcript[-1].meta,
            "routing · execution · 12ms · loop · 0.74 · cache hit · 50.0%",
        )

    def test_state_focus_notice_fragments_show_almost_there_while_transcript_prime_pending(
        self,
    ) -> None:
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

    def test_state_focus_notice_fragments_hide_after_first_user_turn_is_submitted(
        self,
    ) -> None:
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

    def test_state_focus_notice_fragments_hide_after_ready_once_first_user_turn_is_submitted(
        self,
    ) -> None:
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

    def test_state_focus_notice_fragments_surface_state_focus_queue_after_ready_when_first_turn_is_waiting(
        self,
    ) -> None:
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

    def test_startup_transition_result_primes_opening_after_ready_idle_threshold(
        self,
    ) -> None:
        shell = self._make_shell()
        shell._state_focus_runtime_ready_seen_at = time.monotonic() - 10

        with mock.patch.object(
            type(shell), "_startup_state_focus_dispatch_ready", return_value=True
        ):
            immediate = _startup_transition_result(
                shell, buffer_text="", idle_seconds=0.2
            )
            result = _startup_transition_result(shell, buffer_text="", idle_seconds=1.6)

        self.assertIsNone(immediate)
        self.assertEqual(result, "__elephant.startup.prime__")

    def test_startup_transition_result_primes_before_dispatching_queued_first_turn(
        self,
    ) -> None:
        shell = self._make_shell()
        shell._startup_user_turn_submitted = True
        shell._pending_commands.append(PendingShellCommand(command="帮我看下这个"))
        shell._state_focus_runtime_ready_seen_at = time.monotonic() - 10

        with mock.patch.object(
            type(shell), "_startup_state_focus_dispatch_ready", return_value=True
        ):
            result = _startup_transition_result(shell, buffer_text="", idle_seconds=0.0)

        self.assertEqual(result, "__elephant.startup.prime__")

    def test_startup_transition_result_waits_briefly_after_ready_notice(self) -> None:
        shell = self._make_shell()
        shell._state_focus_runtime_ready_seen_at = time.monotonic()

        with mock.patch.object(
            type(shell), "_startup_state_focus_dispatch_ready", return_value=True
        ):
            result = _startup_transition_result(shell, buffer_text="", idle_seconds=2.0)

        self.assertIsNone(result)

    def test_startup_transition_result_does_not_restart_prime_while_background_prime_runs(
        self,
    ) -> None:
        shell = self._make_shell()
        shell._startup_prime_started = True
        shell._state_focus_runtime_ready_seen_at = time.monotonic() - 10

        with mock.patch.object(
            type(shell), "_startup_state_focus_dispatch_ready", return_value=True
        ):
            result = _startup_transition_result(shell, buffer_text="", idle_seconds=2.0)

        self.assertIsNone(result)

    def test_startup_transition_result_dispatches_pending_after_proactive_prime(
        self,
    ) -> None:
        shell = self._make_shell()
        shell._startup_user_turn_submitted = True
        shell._startup_transcript_primed = True
        shell._pending_commands.append(PendingShellCommand(command="帮我看下这个"))

        with mock.patch.object(
            type(shell), "_startup_state_focus_dispatch_ready", return_value=True
        ):
            result = _startup_transition_result(shell, buffer_text="", idle_seconds=0.0)

        self.assertEqual(result, "__elephant.startup.dispatch-pending__")

    def test_startup_turn_is_queued_until_state_focus_runtime_is_ready(self) -> None:
        shell = self._make_shell()

        with mock.patch.object(
            type(shell), "_startup_state_focus_dispatch_ready", return_value=False
        ):
            self.assertTrue(shell._startup_should_hold_user_command("帮我看下这个"))
            self.assertFalse(shell._startup_should_hold_user_command("/help"))
            shell._mark_startup_user_turn_submitted("帮我看下这个")
            shell._enqueue_followup_command("帮我看下这个")
            self.assertTrue(shell._startup_should_hold_user_command("再补一句"))

        self.assertTrue(shell._startup_user_turn_submitted)

    def test_startup_turn_still_queues_until_proactive_opening_is_primed(self) -> None:
        shell = self._make_shell()

        with mock.patch.object(
            type(shell), "_startup_state_focus_dispatch_ready", return_value=True
        ):
            self.assertTrue(shell._startup_should_hold_user_command("帮我看下这个"))
        shell._startup_transcript_primed = True
        with mock.patch.object(
            type(shell), "_startup_state_focus_dispatch_ready", return_value=True
        ):
            self.assertFalse(shell._startup_should_hold_user_command("帮我看下这个"))

    def test_shell_constructor_defers_startup_opening_until_explicit_prime(
        self,
    ) -> None:
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

        with mock.patch.object(
            CliRuntime, "generate_opening_reply"
        ) as generate_opening_reply:
            shell = ProductizedShell(
                runtime, session_id=session.session_id, opened="Shaped new"
            )

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
            mock.patch.object(
                shell,
                "_render_startup_sequence",
                side_effect=record("startup-sequence"),
            ),
            mock.patch.object(
                shell, "_refresh_shell_frame", side_effect=record("refresh-frame")
            ),
            mock.patch.object(
                shell, "_prepare_startup_surface", side_effect=record("prepare-surface")
            ),
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


if __name__ == "__main__":
    unittest.main()
