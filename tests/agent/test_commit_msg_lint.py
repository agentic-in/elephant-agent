from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "agent" / "scripts" / "commit_msg_lint.py"
SPEC = importlib.util.spec_from_file_location("commit_msg_lint", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class CommitMessageLintTests(unittest.TestCase):
    def test_valid_subject(self) -> None:
        self.assertEqual(MODULE.lint_subject("feat(harness): bootstrap repo-native contract"), [])

    def test_rejects_missing_scope_separator(self) -> None:
        errors = MODULE.lint_subject("docs: bootstrap repo-native contract")
        self.assertTrue(errors)

    def test_rejects_terminal_period(self) -> None:
        errors = MODULE.lint_subject("docs(agent): explain validation ladder.")
        self.assertIn("commit subject must not end with a period", errors)


if __name__ == "__main__":
    unittest.main()
