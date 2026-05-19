from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "agent" / "scripts" / "ship.py"
AGENTS_PATH = ROOT / "AGENTS.md"
CONTRIBUTING_PATH = ROOT / "CONTRIBUTING.md"
CHECKLIST_PATH = ROOT / "docs" / "agent" / "feature-complete-checklist.md"
SPEC = importlib.util.spec_from_file_location("ship", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ShipTests(unittest.TestCase):
    def test_parse_status_paths_handles_rename_and_untracked(self) -> None:
        lines = [
            " M README.md",
            "R  docs/old.md -> docs/new.md",
            "?? docs/system-design/provisional-foundation.md",
        ]
        self.assertEqual(
            MODULE.parse_status_paths(lines),
            [
                "README.md",
                "docs/new.md",
                "docs/system-design/provisional-foundation.md",
            ],
        )

    def test_ensure_branch_uses_override(self) -> None:
        self.assertEqual(MODULE.ensure_branch("docs/design"), "docs/design")

    @mock.patch.object(MODULE, "git")
    def test_resolve_base_ref_prefers_origin_main(self, git_mock: mock.Mock) -> None:
        git_mock.side_effect = [
            mock.Mock(returncode=0, stdout="sha\n", stderr=""),
        ]
        self.assertEqual(MODULE.resolve_base_ref(""), "origin/main")

    @mock.patch.object(MODULE, "git")
    def test_resolve_base_ref_falls_back_to_empty(self, git_mock: mock.Mock) -> None:
        git_mock.side_effect = [
            mock.Mock(returncode=1, stdout="", stderr=""),
            mock.Mock(returncode=1, stdout="", stderr=""),
        ]
        self.assertEqual(MODULE.resolve_base_ref(""), "")

    def test_harness_defaults_completed_repo_work_to_agent_ship(self) -> None:
        agents_text = AGENTS_PATH.read_text(encoding="utf-8")
        contributing_text = CONTRIBUTING_PATH.read_text(encoding="utf-8")
        checklist_text = CHECKLIST_PATH.read_text(encoding="utf-8")

        self.assertIn("do not stop at validation only", agents_text)
        self.assertIn("default closeout path", contributing_text)
        self.assertIn("repo-visible completed work has been shipped", checklist_text)
        self.assertIn("push the current branch to `origin`", contributing_text)


if __name__ == "__main__":
    unittest.main()
