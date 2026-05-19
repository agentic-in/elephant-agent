from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

import apps.cli.shell as cli_shell
import apps.cli.shell_composer as shell_composer


class ShellComposerPromptToolkitTests(unittest.TestCase):
    def _make_shell(self) -> SimpleNamespace:
        return SimpleNamespace(
            runtime=SimpleNamespace(paths=SimpleNamespace(state_dir=Path("/tmp/elephant-shell-tests"))),
            _composer_divider=lambda: "divider",
            _prompt_label=lambda: "divider\n› ",
            _prompt_style=lambda: None,
            _build_key_bindings=lambda **_kwargs: mock.sentinel.bindings,
            _prompt_continuation=lambda: "  ",
        )

    def test_read_command_runs_prompt_session_in_thread_when_loop_is_active(
        self,
    ) -> None:
        shell = self._make_shell()
        captured: dict[str, object] = {}

        class _FakePromptSession:
            def __init__(self, **kwargs):
                captured["session_init"] = kwargs

            def prompt(self, *args, **kwargs):
                captured["prompt_args"] = args
                captured["prompt_kwargs"] = kwargs
                return "hello from prompt"

        with (
            mock.patch.object(shell_composer, "PROMPT_TOOLKIT_AVAILABLE", True),
            mock.patch.object(shell_composer, "PromptSession", _FakePromptSession),
            mock.patch.object(shell_composer, "prompt_toolkit_composer_available", return_value=False),
            mock.patch.object(shell_composer, "shell_history", return_value=mock.sentinel.history),
            mock.patch.object(shell_composer, "prompt_toolkit_loop_running", return_value=True),
            mock.patch.object(
                shell_composer,
                "prompt_toolkit_output_without_cpr",
                return_value=mock.sentinel.output,
            ),
            mock.patch.object(cli_shell, "ShellCompleter", return_value=mock.sentinel.completer),
        ):
            result = shell_composer.read_command(shell)

        self.assertEqual(result, "hello from prompt")
        self.assertIs(captured["session_init"]["completer"], mock.sentinel.completer)
        self.assertIs(captured["session_init"]["output"], mock.sentinel.output)
        self.assertTrue(captured["prompt_kwargs"]["in_thread"])

    def test_read_command_runs_application_in_thread_when_loop_is_active(self) -> None:
        shell = self._make_shell()
        captured: dict[str, object] = {}

        class _FakeApplication:
            def __init__(self, **kwargs):
                captured["application_init"] = kwargs

            def run(self, **kwargs):
                captured["run_kwargs"] = kwargs
                return "hello from app"

            def invalidate(self):
                return None

            def exit(self, result=None):
                return result

        buffer = SimpleNamespace(text="")

        with (
            mock.patch.object(shell_composer, "PROMPT_TOOLKIT_AVAILABLE", True),
            mock.patch.object(shell_composer, "prompt_toolkit_composer_available", return_value=True),
            mock.patch.object(shell_composer, "build_prompt_buffer", return_value=buffer),
            mock.patch.object(
                shell_composer,
                "build_input_window",
                return_value=mock.sentinel.input_window,
            ),
            mock.patch.object(
                shell_composer,
                "build_command_palette",
                return_value=mock.sentinel.command_palette,
            ),
            mock.patch.object(shell_composer, "build_composer_body", return_value=mock.sentinel.body),
            mock.patch.object(
                shell_composer,
                "prompt_toolkit_output_without_cpr",
                return_value=mock.sentinel.output,
            ),
            mock.patch.object(shell_composer, "Application", _FakeApplication),
            mock.patch.object(
                shell_composer,
                "Layout",
                side_effect=lambda body, focused_element=None: (body, focused_element),
            ),
            mock.patch.object(shell_composer, "prompt_toolkit_loop_running", return_value=True),
        ):
            result = shell_composer.read_command(shell)

        self.assertEqual(result, "hello from app")
        self.assertEqual(
            captured["application_init"]["layout"],
            (mock.sentinel.body, mock.sentinel.input_window),
        )
        self.assertIs(captured["application_init"]["output"], mock.sentinel.output)
        self.assertTrue(captured["run_kwargs"]["in_thread"])


class GhostHintMatchTests(unittest.TestCase):
    """Unit coverage for the inline `/command` ghost-hint matcher."""

    def _shell_with_specs(self, command_specs, skill_specs=()) -> SimpleNamespace:
        return SimpleNamespace(
            command_specs=tuple(command_specs),
            _skill_slash_specs=tuple(skill_specs),
        )

    def test_returns_none_for_empty_or_non_slash_text(self) -> None:
        shell = self._shell_with_specs(
            (SimpleNamespace(name="/status", description="check on me"),),
        )
        self.assertIsNone(shell_composer._ghost_hint_match(shell, ""))
        self.assertIsNone(shell_composer._ghost_hint_match(shell, "hello there"))
        # `/` alone matches the first slash command — it's a valid prefix.
        match = shell_composer._ghost_hint_match(
            self._shell_with_specs((SimpleNamespace(name="/status", description="s"),)),
            "/",
        )
        self.assertIsNotNone(match)

    def test_returns_tail_and_description_for_prefix(self) -> None:
        shell = self._shell_with_specs(
            (
                SimpleNamespace(name="/status", description="where Elephant Agent stands"),
                SimpleNamespace(name="/models", description="pick the model"),
            ),
        )
        match = shell_composer._ghost_hint_match(shell, "/st")
        self.assertIsNotNone(match)
        assert match is not None  # narrow for the type checker
        tail, description = match
        self.assertEqual(tail, "atus")
        self.assertEqual(description, "where Elephant Agent stands")

    def test_exact_match_returns_none(self) -> None:
        shell = self._shell_with_specs(
            (SimpleNamespace(name="/status", description="s"),),
        )
        self.assertIsNone(shell_composer._ghost_hint_match(shell, "/status"))

    def test_space_in_first_line_disables_hint(self) -> None:
        shell = self._shell_with_specs(
            (SimpleNamespace(name="/status", description="s"),),
        )
        # Once args begin, we stop offering command-name hints.
        self.assertIsNone(shell_composer._ghost_hint_match(shell, "/status --json"))

    def test_skills_considered_after_built_ins(self) -> None:
        shell = self._shell_with_specs(
            command_specs=(SimpleNamespace(name="/status", description="s"),),
            skill_specs=(SimpleNamespace(command="/plan", summary="plan a task"),),
        )
        match = shell_composer._ghost_hint_match(shell, "/pl")
        self.assertIsNotNone(match)
        assert match is not None
        tail, description = match
        self.assertEqual(tail, "an")
        self.assertEqual(description, "plan a task")

    def test_case_insensitive_prefix(self) -> None:
        shell = self._shell_with_specs(
            (SimpleNamespace(name="/Status", description="mixed case in spec"),),
        )
        match = shell_composer._ghost_hint_match(shell, "/st")
        self.assertIsNotNone(match)
        assert match is not None
        # Tail is sliced from the original name — case preserved.
        self.assertEqual(match[0], "atus")

    def test_no_match_for_unknown_prefix(self) -> None:
        shell = self._shell_with_specs(
            (SimpleNamespace(name="/status", description="s"),),
        )
        self.assertIsNone(shell_composer._ghost_hint_match(shell, "/xyz"))


class LastUserMessageTests(unittest.TestCase):
    """Unit coverage for the Up-arrow retry helper."""

    def _shell_with_transcript(self, entries) -> SimpleNamespace:
        return SimpleNamespace(transcript=list(entries))

    def _entry(self, kind: str, body: str) -> SimpleNamespace:
        return SimpleNamespace(kind=kind, body=body)

    def test_empty_transcript_returns_empty(self) -> None:
        shell = self._shell_with_transcript(())
        self.assertEqual(shell_composer._last_user_message(shell), "")

    def test_picks_most_recent_user_entry(self) -> None:
        shell = self._shell_with_transcript(
            [
                self._entry("user", "first"),
                self._entry("assistant", "reply"),
                self._entry("user", "second"),
                self._entry("assistant", "second reply"),
            ]
        )
        self.assertEqual(shell_composer._last_user_message(shell), "second")

    def test_skips_blank_user_entries(self) -> None:
        shell = self._shell_with_transcript(
            [
                self._entry("user", "real message"),
                self._entry("user", "   "),
            ]
        )
        self.assertEqual(shell_composer._last_user_message(shell), "real message")

    def test_missing_transcript_attr_does_not_raise(self) -> None:
        shell = SimpleNamespace()
        self.assertEqual(shell_composer._last_user_message(shell), "")


if __name__ == "__main__":
    unittest.main()
