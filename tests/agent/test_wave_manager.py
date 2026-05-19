from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "agent" / "scripts" / "wave_manager.py"
AGENTS_PATH = ROOT / "AGENTS.md"
CONTRIBUTING_PATH = ROOT / "CONTRIBUTING.md"
SPEC = importlib.util.spec_from_file_location("wave_manager", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class WaveManagerTests(unittest.TestCase):
    def test_registry_allows_empty_active_waves(self) -> None:
        registry = MODULE.load_registry()
        self.assertEqual(registry["waves"], {})
        self.assertEqual(registry["operator_model"]["user_talks_to"], "main_session_only")
        self.assertEqual(registry["operator_model"]["worker_model"], "gpt-5.4")
        self.assertEqual(
            registry["operator_model"]["assignment_strategy"],
            "maximize safe parallelism across ready disjoint tracks",
        )
        self.assertEqual(
            registry["operator_model"]["main_session_policy"],
            "launch ready parallel tracks, then return or review later",
        )
        self.assertEqual(
            registry["operator_model"]["ship_default"],
            "close each completed atomic branch with make agent-ship",
        )

    def test_parse_worktree_records(self) -> None:
        output = (
            "worktree /tmp/elephant\n"
            "HEAD abc123\n"
            "branch refs/heads/main\n"
            "\n"
            "worktree /tmp/elephant/.worktrees/fnd-1\n"
            "HEAD def456\n"
            "branch refs/heads/feat/fnd-1-contracts\n"
        )
        self.assertEqual(
            MODULE.parse_worktree_records(output),
            [
                {
                    "worktree": "/tmp/elephant",
                    "HEAD": "abc123",
                    "branch": "refs/heads/main",
                },
                {
                    "worktree": "/tmp/elephant/.worktrees/fnd-1",
                    "HEAD": "def456",
                    "branch": "refs/heads/feat/fnd-1-contracts",
                },
            ],
        )

    def test_docs_default_to_assignment_first_main_session_model(self) -> None:
        agents_text = AGENTS_PATH.read_text(encoding="utf-8")
        contributing_text = CONTRIBUTING_PATH.read_text(encoding="utf-8")

        self.assertIn("main session", agents_text)
        self.assertIn("main session", contributing_text)
        self.assertIn("parallel", agents_text)
        self.assertIn("parallel", contributing_text)
        self.assertNotIn("supervision loop", agents_text)
        self.assertNotIn("supervision loop", contributing_text)

    def test_show_wave_reports_unknown_when_registry_is_reset(self) -> None:
        with self.assertRaisesRegex(SystemExit, "unknown wave: wave-0"):
            MODULE.show_wave("wave-0", Path("/tmp/elephant/.worktrees"))

    @mock.patch.object(MODULE.subprocess, "run")
    def test_start_wave_reports_unknown_when_registry_is_reset(self, run_mock: mock.Mock) -> None:
        with self.assertRaisesRegex(SystemExit, "unknown wave: wave-0"):
            MODULE.start_wave("wave-0", Path("/tmp/fake-root"), "main")
        run_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
