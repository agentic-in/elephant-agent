from __future__ import annotations

import json
import unittest

from apps.cli.runtime import CliRuntime
from tests.e2e.cli.cli_surface_test_base import (
    EMBEDDING_BOOTSTRAP_READY_PATTERN,
    EMBEDDING_BOOTSTRAP_STATUS_PATTERN,
    INTERACTIVE_STACK_AVAILABLE,
    CliSurfaceE2ETestBase,
)


class CliSurfaceE2ETest(CliSurfaceE2ETestBase):
    def test_setup_and_grow_cli_flow(self) -> None:
        overview = self._run()
        self.assertIn("Elephant Agent CLI", overview.stdout)
        self.assertIn("personal-model-first AI", overview.stdout)
        self.assertIn("Model what matters", overview.stdout)
        self.assertIn("elephant init", overview.stdout)
        self.assertIn("elephant wake", overview.stdout)
        self.assertIn("• herd", overview.stdout)
        self.assertIn("• status", overview.stdout)
        self.assertIn("• skills", overview.stdout)
        self.assertIn("• gateway", overview.stdout)
        self.assertIn("• dashboard", overview.stdout)
        self.assertNotIn("elephant chat", overview.stdout)
        self.assertNotIn("elephant providers", overview.stdout)
        self.assertNotIn("state_dir", overview.stdout)
        self.assertNotIn("profile_dir", overview.stdout)

        blocked = self._run("wake", "--message", "hello", check=False)
        self.assertEqual(blocked.returncode, 1)
        self.assertIn("Wake blocked", blocked.stdout)
        self.assertIn("elephant init", blocked.stdout)

        setup = self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "demo",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )
        self.assertIn("Elephant Agent init", setup.stdout)
        self.assertIn("Your Elephant Agent has shaped", setup.stdout)
        self.assertIn("Demo is awake", setup.stdout)
        self.assertIn("elephant · demo", setup.stdout)
        self.assertIn("status · ready", setup.stdout)
        self.assertIn("elephant wake", setup.stdout)
        self.assertIn("elephant herd new <name>", setup.stdout)
        self.assertIn("elephant gateway setup", setup.stdout)
        self.assertIn("elephant gateway doctor", setup.stdout)

        health = self._run("status")
        self.assertIn("Elephant Agent status", health.stdout)
        self.assertIn("provider_status · ready", health.stdout)
        self.assertIn("security_status · ready", health.stdout)
        self.assertIn("active_provider_model · openai/gpt-4o-mini", health.stdout)
        self.assertRegex(
            health.stdout,
            rf"active_provider_embedding_bootstrap · {EMBEDDING_BOOTSTRAP_STATUS_PATTERN}",
        )
        self.assertRegex(
            health.stdout,
            rf"active_provider_embedding_ready · {EMBEDDING_BOOTSTRAP_READY_PATTERN}",
        )
        self.assertNotIn("state_focus_mode", health.stdout)

        turn = self._run("wake", "--message", "Who are you?")
        self.assertIn("Elephant Agent turn", turn.stdout)
        self.assertIn("live-chat:Who are you?", turn.stdout)
        self.assertIn("cache_hit_rate · 28.6% (2/7 input tokens cached)", turn.stdout)
        chat_payload = next(
            (
                payload
                for payload in reversed(self.stub.payloads)
                if "Who are you?" in str(payload["messages"][-1]["content"])  # type: ignore[index]
            ),
            None,
        )
        self.assertIsNotNone(chat_payload)
        system_prompt = str(chat_payload["messages"][0]["content"])  # type: ignore[index]
        self.assertNotIn("### Who you are", system_prompt)
        self.assertIn("You are Demo", system_prompt)
        self.assertIn("### Your own voice", system_prompt)
        self.assertIn("### What I know so far", system_prompt)
        self.assertIn("### Understanding tools", system_prompt)
        self.assertIn("Use `tool.personal_model.search`", system_prompt)
        self.assertIn("Use `tool.conversation.search`", system_prompt)
        self.assertIn("### Runtime paths", system_prompt)
        self.assertNotIn("### Episode resume", system_prompt)
        self.assertNotIn("sub-agent child Episode opened", system_prompt)
        self.assertNotIn("OpenAI-compatible provider adapter", system_prompt)
        self.assertNotIn("Never claim to be Claude Code", system_prompt)
        self.assertNotIn("generic provider shell", turn.stdout)

    def test_setup_hands_off_to_wake_surface(self) -> None:
        setup = self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "aeon",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )
        setup_contains = (
            "Elephant Agent init",
            "Your Elephant Agent has shaped",
            "Aeon is awake",
            "elephant wake",
        )
        for needle in setup_contains:
            self.assertIn(needle, setup.stdout)
        for needle in ("Welcome back !", "Gateway setup"):
            self.assertNotIn(needle, setup.stdout)

        runtime = CliRuntime.create(state_dir=self.state_dir)
        state = runtime.state_for_elephant("aeon")
        self.assertIsNotNone(state)
        assert state is not None
        manifest_expectations = (
            (state.elephant_name, "Aeon"),
            (state.identity_mode, "companion"),
            (state.initiative, "gentle"),
            (state.working_style, "companion"),
        )
        for observed, expected in manifest_expectations:
            self.assertEqual(observed, expected)
        self.assertFalse((self.profile_dir / "ELEPHANT.md").exists())
        born_elephant = self._run("herd")
        self.assertIn("aeon · current · latest", born_elephant.stdout)

    def test_interactive_wake_help_surfaces_shell_commands(self) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "aeon",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )
        shell = self._run_in_tty(
            "/help\n/exit\n",
            "wake",
            initial_delay=4.0,
        )
        shell_contains = (
            "Elephant Agent",
            "Your elephant still knows the path.",
            "Personal Model first. Curious by design.",
            "What I know",
            "Skills for you",
            "Command palette",
            "/tools  - govern built-ins and manifest-backed tools",
            "/skills  - discover, inspect, and govern skill packages",
            "/cron  - govern built-in scheduled jobs",
            "Use /skills to inspect installed skills",
            "Elephant management stays in the CLI: elephant herd new <name>",
            "Tip: type / and keep typing to open the command palette.",
            "Elephant Agent stays by your side.",
        )
        for needle in shell_contains:
            self.assertIn(needle, shell)
        shell_absent = (
            "/resume latest|<elephant-id>|<session-id>",
            "/profile",
            "/activity",
            "/audit",
            "/frozen",
            "/whoami",
            "Welcome back !",
            "startup-reply:I already have the current work in view. What should I call you?",
            "I'll get a little grounding from you first",
            "What Work Are You In Right Now?",
            "Required",
            "Good To Have Today",
            "legacy first-work prompt copy",
            "🧠 Persistent memory · long-horizon decisions · long context",
            "assistant_display_name:",
            "opening_profile_gap:",
            "current_work_summary:",
            "Open the wake surface proactively before the user sends a new message.",
        )
        for needle in shell_absent:
            self.assertNotIn(needle, shell)
        self.assertNotIn("Start with the person", shell)
        self.assertNotIn("This Episode", shell)

    def test_launcher_help_lists_gateway_skills_and_dashboard(self) -> None:
        help_output = self._run_launcher("--help")
        self.assertIn("Elephant Agent launcher", help_output.stdout)
        self.assertIn("Elephant Agent is personal-model-first AI", help_output.stdout)
        self.assertEqual(
            help_output.stdout.count("Elephant Agent is personal-model-first AI"), 1
        )
        self.assertIn(
            "Warm, steady ways back to the elephant that remembers your path.",
            help_output.stdout,
        )
        self.assertIn(
            "🐘 Model what matters · 👂 Ask gently · 🐾 Follow the path",
            help_output.stdout,
        )
        self.assertIn("Commands", help_output.stdout)
        expected_order = [
            "• init",
            "• wake",
            "• dashboard",
            "• herd",
            "• provider",
            "• facts",
            "• reflect",
            "• skills",
            "• gateway",
            "• cron",
            "• status",
        ]
        positions = [help_output.stdout.index(entry) for entry in expected_order]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("• •", help_output.stdout)
        self.assertNotIn("Usage:", help_output.stdout)

    def test_launcher_no_args_prints_single_root_cli_surface(self) -> None:
        overview = self._run_launcher()
        self.assertNotIn("Welcome", overview.stdout)
        self.assertIn("Elephant Agent CLI", overview.stdout)
        self.assertIn(
            "🐘 Model what matters · 👂 Ask gently · 🐾 Follow the path",
            overview.stdout,
        )
        self.assertIn("Elephant Agent is personal-model-first AI", overview.stdout)
        self.assertEqual(
            overview.stdout.count("Elephant Agent is personal-model-first AI"), 1
        )
        self.assertIn("elephant init", overview.stdout)
        self.assertNotIn("• •", overview.stdout)
        self.assertNotIn("Usage:", overview.stdout)

    def test_launcher_rejects_removed_health_alias(self) -> None:
        result = self._run_launcher("health", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("No such command 'health'", result.stderr)
        self.assertNotIn("health", result.stdout)

    def test_launcher_dashboard_guides_to_daemon_surface(self) -> None:
        dashboard = self._run_launcher(
            "dashboard", "--no-open", "--skip-build", "--no-start", check=False
        )
        self.assertEqual(dashboard.returncode, 1)
        self.assertIn("Elephant Agent dashboard", dashboard.stdout)
        self.assertTrue(
            "dashboard frontend assets are not available" in dashboard.stdout
            or "dashboard is served by the Elephant daemon" in dashboard.stdout
        )
        self.assertNotIn("api_url · http://127.0.0.1:8000", dashboard.stdout)
        self.assertNotIn("ui_url · http://127.0.0.1:4174", dashboard.stdout)

    def test_grow_shell_rejects_removed_profile_command(self) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "seed",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )

        shell = self._run_in_tty(
            "/profile user set Preferred name: Bit\n/exit\n",
            "wake",
            enable_animation=True,
        )

        self.assertIn("Unknown command", shell)
        self.assertIn("/profile", shell)
        self.assertIn("Elephant Agent stays by your side.", shell)
        self.assertNotIn(f"live-chat:can you read {self.web_stub.url}?", shell)
        self.assertNotIn("<minimax:tool_call>", shell)
        self.assertNotIn("<invoke name=", shell)
        self.assertNotIn("Grow context", shell)
        self.assertNotIn("Runtime stages", shell)
        self.assertNotIn("Running a shared-runtime turn", shell)
        self.assertNotIn("/set-provider", shell)
        self.assertNotIn("/wake", shell)
        self.assertNotIn("/doctor", shell)

    def test_grow_shell_prioritizes_opening_reply_before_early_input(self) -> None:
        if not INTERACTIVE_STACK_AVAILABLE:
            self.skipTest("prompt_toolkit + rich are required for queued grow input")
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "queue",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )

        shell = self._run_in_tty(
            "slow first turn\n",
            "wake",
            followup_text="queued while growing\n/exit\n",
            followup_delay=0.2,
            enable_animation=True,
        )

        self.assertIn(
            "Bring whatever you want to work on; I will adapt from here.", shell
        )
        self.assertIn("closing elephant queue", shell)
        self.assertIn("Elephant Agent stays by your side.", shell)
        self.assertNotIn("live-chat:slow first turn", shell)
        self.assertNotIn("live-chat:queued while growing", shell)

    def test_wake_turn_updates_growth_after_first_turn(self) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "seed",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )

        turn = self._run(
            "wake",
            "--message",
            "hello there",
        )
        runtime = CliRuntime.create(state_dir=self.state_dir)
        seed_session = runtime.latest_session_for_elephant("seed")
        self.assertIsNotNone(seed_session)
        assert seed_session is not None
        growth = runtime.inspect_growth(session_id=seed_session.episode_id)

        self.assertIn("live-chat:hello there", turn.stdout)
        self.assertGreaterEqual(growth.level, 1)
        self.assertGreaterEqual(growth.state.growth_score, 40)
        self.assertGreaterEqual(growth.progress_percent, 0)
        self.assertGreaterEqual(growth.score_to_next_level, 0)
        self.assertEqual(growth.state.total_experiences, 1)
        self.assertEqual(growth.state.promoted_experiences, 0)

    def test_wake_turn_levels_up_growth_on_second_turn(self) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "seed",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )

        self._run(
            "wake",
            "--message",
            "hello there",
        )
        second_turn = self._run(
            "wake",
            "--message",
            "second turn",
        )
        runtime = CliRuntime.create(state_dir=self.state_dir)
        seed_session = runtime.latest_session_for_elephant("seed")
        self.assertIsNotNone(seed_session)
        assert seed_session is not None
        growth = runtime.inspect_growth(session_id=seed_session.episode_id)
        history_messages = json.loads(
            runtime.snapshot_path.read_text(encoding="utf-8")
        )["session_context_epoch"]["history_messages"]
        self.assertIsNotNone(seed_session.parent_episode_id)
        assert seed_session.parent_episode_id is not None
        parent = runtime.inspect_session(seed_session.parent_episode_id)

        self.assertIn("live-chat:second turn", second_turn.stdout)
        self.assertIn(seed_session.episode_id, runtime.session_ids_for_elephant("seed"))
        self.assertEqual(parent.status, "closed")
        self.assertIsNotNone(parent.parent_episode_id)
        self.assertEqual(parent.metadata.get("closed_reason"), "wake_boundary")
        self.assertFalse(
            any(message["content"] == "hello there" for message in history_messages)
        )
        self.assertTrue(
            any("second turn" in message["content"] for message in history_messages)
        )
        self.assertGreaterEqual(growth.level, 1)
        self.assertGreaterEqual(growth.state.growth_score, 100)
        self.assertGreaterEqual(growth.progress_percent, 0)
        self.assertGreaterEqual(growth.score_to_next_level, 0)
        self.assertGreaterEqual(growth.state.total_experiences, 2)
        self.assertEqual(growth.state.promoted_experiences, 0)

    def test_wake_turn_persists_growth_history_across_runtime_reloads(self) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "seed",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )

        self._run(
            "wake",
            "--message",
            "hello there",
        )
        self._run(
            "wake",
            "--message",
            "second turn",
        )
        runtime = CliRuntime.create(state_dir=self.state_dir)
        seed_session = runtime.latest_session_for_elephant("seed")
        self.assertIsNotNone(seed_session)
        assert seed_session is not None
        growth = runtime.inspect_growth(session_id=seed_session.episode_id)

        self.assertGreaterEqual(growth.level, 1)
        self.assertGreaterEqual(growth.state.total_dialogues, 2)
        self.assertGreaterEqual(growth.state.total_experiences, 2)
        self.assertGreater(growth.state.total_tokens, 0)

    def test_wake_interactive_entry_opens_single_herd_directly(self) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "seed",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )

        shell = self._run_in_tty(
            "",
            "wake",
            followup_text="/exit\n",
        )
        self.assertIn("Elephant Agent", shell)
        self.assertIn("What I know", shell)
        self.assertIn("Skills for you", shell)
        self.assertNotIn("This Episode", shell)
        self.assertNotIn("Choose elephant", shell)

    def test_interactive_grow_prompts_for_elephant_when_multiple_exist(self) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "seed",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )
        self._run("herd", "new", "alpha")
        self._run("herd", "new", "beta")

        shell = self._run_in_tty(
            "beta\n",
            "wake",
            followup_text="/exit\n",
        )
        self.assertIn("Choose elephant", shell)
        self.assertIn("Elephant Agent", shell)
        self.assertNotIn("This Episode", shell)
        self.assertIn("Beta", shell)

    def test_grow_debug_mode_surfaces_debug_elephant_context(self) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "seed",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )
        self._run("herd", "new", "debug")

        shell = self._run_in_tty(
            "who are you in debug\n/exit\n",
            "wake",
            "--elephant-id",
            "debug",
            "--debug",
        )
        self.assertIn("Debug", shell)
        self.assertIn("closing elephant debug", shell)
        self.assertIn(
            "Bring whatever you want to work on; I will adapt from here.", shell
        )
        self.assertIn("Elephant Agent stays by your side.", shell)


if __name__ == "__main__":
    unittest.main()
