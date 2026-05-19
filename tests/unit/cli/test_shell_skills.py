from __future__ import annotations

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from apps.cli.runtime import CliRuntime
from apps.cli.shell import Document, ProductizedShell, ShellCompleter


class ShellSkillSlashTest(unittest.TestCase):
    def _make_shell(self) -> ProductizedShell:
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
        return ProductizedShell(runtime, session_id=session.session_id, opened="Shaped new")

    def _fake_outcome(self, summary: str = "Used the skill.") -> SimpleNamespace:
        return SimpleNamespace(
            execution=SimpleNamespace(
                summary=summary,
                prompt_tokens=10,
                completion_tokens=6,
                total_tokens=16,
                outcome="ok",
            ),
            stages=(),
            plan=None,
            work_items=(),
            recall_items=(),
        )

    def test_command_palette_hides_dynamic_skill_slash_commands(self) -> None:
        shell = self._make_shell()
        completer = ShellCompleter(shell)

        completions = {item.text for item in completer.get_completions(Document("/apple"), None)}

        self.assertNotIn("/apple-notes", completions)
        self.assertNotIn("/apple-reminders", completions)

    def test_skill_slash_command_without_instruction_loads_skill_metadata(self) -> None:
        shell = self._make_shell()

        with mock.patch.object(
            shell,
            "_run_tool_with_progress",
            return_value=SimpleNamespace(summary="loaded"),
        ):
            handled = shell._handle_slash_command("/apple-notes")

        self.assertFalse(handled)
        self.assertEqual(shell.transcript[-1].title, "Skill loaded")
        self.assertIn("display_name: Apple Notes", shell.transcript[-1].body)
        self.assertIn("run: /apple-notes <instruction>", shell.transcript[-1].body)

    def test_skill_slash_command_with_instruction_injects_skill_guidance_into_turn(
        self,
    ) -> None:
        shell = self._make_shell()

        with mock.patch.object(
            shell,
            "_run_tool_with_progress",
            return_value=SimpleNamespace(summary="loaded"),
        ):
            with mock.patch.object(shell, "_render_pending_entries", return_value=None):
                with mock.patch.object(shell, "_refresh_shell_frame", return_value=None):
                    with mock.patch.object(
                        shell,
                        "_run_turn_with_progress",
                        return_value=self._fake_outcome("Notes opened."),
                    ) as run_turn:
                        handled = shell._handle_slash_command("/apple-notes open Notes and create a travel checklist")

        self.assertFalse(handled)
        prompt = run_turn.call_args.args[0]
        self.assertIn(
            '[SYSTEM: This turn references the "Apple Notes" skill from the frozen skill index.]',
            prompt,
        )
        self.assertIn("User request: open Notes and create a travel checklist", prompt)
        self.assertEqual(shell.transcript[-2].kind, "user")
        self.assertEqual(
            shell.transcript[-2].body,
            "/apple-notes open Notes and create a travel checklist",
        )
        self.assertEqual(shell.transcript[-1].kind, "assistant")
        self.assertIn("Notes opened.", shell.transcript[-1].body)


if __name__ == "__main__":
    unittest.main()
