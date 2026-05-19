"""Unit tests for the deep-pass CLI polish features.

Covers:
  * turn_metrics.condense_tool_summary
  * shell_render._fold_long_body + _recovery_quick_fix_hint
  * shell_ui.wrap_file_hyperlink + terminal_supports_hyperlinks
"""

from __future__ import annotations

import os
from types import SimpleNamespace
import unittest

from apps.cli import shell_render, shell_ui, turn_metrics


# ─────────────────────────── condense_tool_summary ───────────────────────────


class CondenseToolSummaryTests(unittest.TestCase):
    def test_empty_events_returns_empty_string(self) -> None:
        self.assertEqual(turn_metrics.condense_tool_summary([]), "")

    def test_single_success_returns_verb(self) -> None:
        self.assertEqual(
            turn_metrics.condense_tool_summary([("tool.file.read", True, 1)]),
            "read",
        )

    def test_repeated_tool_collapses_to_count(self) -> None:
        result = turn_metrics.condense_tool_summary(
            [
                ("tool.file.read", True, 1),
                ("tool.file.read", True, 2),
                ("tool.file.read", True, 3),
            ]
        )
        self.assertEqual(result, "read × 3")

    def test_mixed_tools_join_with_middle_dot(self) -> None:
        result = turn_metrics.condense_tool_summary(
            [
                ("tool.file.read", True, 1),
                ("tool.file.read", True, 2),
                ("tool.file.patch", True, 3),
                ("tool.file.search", True, 4),
            ]
        )
        # Order follows Counter.most_common — read (2) first, then two ties.
        self.assertIn("read × 2", result)
        self.assertIn("edited", result)
        self.assertIn("searched", result)
        parts = result.split(" · ")
        self.assertEqual(parts[0], "read × 2")
        self.assertIn("edited", parts)
        self.assertIn("searched", parts)

    def test_single_failure_surfaces_with_failed_suffix(self) -> None:
        result = turn_metrics.condense_tool_summary(
            [
                ("tool.file.read", True, 1),
                ("tool.terminal.exec", False, 2),
            ]
        )
        self.assertEqual(result, "read · ran failed")

    def test_multiple_failures_collapse_to_count(self) -> None:
        result = turn_metrics.condense_tool_summary(
            [
                ("tool.terminal.exec", False, 1),
                ("tool.file.read", False, 2),
                ("tool.file.patch", False, 3),
            ]
        )
        self.assertIn("3 failures", result)

    def test_unknown_tool_falls_back_to_last_segment(self) -> None:
        self.assertEqual(
            turn_metrics.condense_tool_summary([("tool.novel.widget", True, 1)]),
            "widget",
        )

    def test_tool_id_with_underscores_gets_spaces(self) -> None:
        # "tool.foo.my_cool_thing" -> "my cool thing"
        result = turn_metrics.condense_tool_summary([("tool.foo.my_cool_thing", True, 1)])
        self.assertEqual(result, "my cool thing")


# ────────────────────────────── _fold_long_body ──────────────────────────────


class FoldLongBodyTests(unittest.TestCase):
    def _entry(self, kind: str, body: str) -> SimpleNamespace:
        return SimpleNamespace(kind=kind, title="Test", body=body, meta="")

    def _shell(self) -> SimpleNamespace:
        return SimpleNamespace()

    def test_short_body_is_not_folded(self) -> None:
        shell = self._shell()
        body, folded = shell_render._fold_long_body(shell, self._entry("notice", "short text"))
        self.assertFalse(folded)
        self.assertEqual(body, "short text")

    def test_long_body_folds_and_stores_full_version(self) -> None:
        shell = self._shell()
        long_body = "\n".join(f"line {index}" for index in range(80))
        body, folded = shell_render._fold_long_body(shell, self._entry("notice", long_body))
        self.assertTrue(folded)
        self.assertIn("/expand last", body)
        self.assertEqual(shell._folded_entry_bodies["__last__"], long_body)

    def test_chat_kinds_are_never_folded(self) -> None:
        shell = self._shell()
        long_body = "x" * 10_000
        for kind in ("assistant", "user", "growth", "tooltrace", "recovery"):
            body, folded = shell_render._fold_long_body(shell, self._entry(kind, long_body))
            self.assertFalse(folded, f"kind {kind!r} should not be folded")
            self.assertEqual(body, long_body)

    def test_char_threshold_triggers_fold_even_on_few_lines(self) -> None:
        shell = self._shell()
        # 5 lines but very long chars → still folds.
        body, folded = shell_render._fold_long_body(
            shell,
            self._entry("notice", "x" * 4000),
        )
        self.assertTrue(folded)


# ────────────────────────── _recovery_quick_fix_hint ─────────────────────────


class RecoveryQuickFixHintTests(unittest.TestCase):
    def test_invalid_key_hint(self) -> None:
        hint = shell_render._recovery_quick_fix_hint("Invalid key: c-/ is not recognized")
        self.assertIn("F1", hint)
        self.assertIn("?", hint)

    def test_rate_limit_hint(self) -> None:
        hint = shell_render._recovery_quick_fix_hint("Rate limit exceeded from provider")
        self.assertIn("rate-limiting", hint)

    def test_no_match_returns_empty(self) -> None:
        self.assertEqual(shell_render._recovery_quick_fix_hint("some random unexpected error"), "")

    def test_match_is_case_insensitive(self) -> None:
        self.assertIn("rate-limiting", shell_render._recovery_quick_fix_hint("RATE LIMIT"))


# ─────────────────────────── wrap_file_hyperlink ─────────────────────────────


class WrapFileHyperlinkTests(unittest.TestCase):
    def setUp(self) -> None:
        # Snapshot relevant env vars so tests don't leak into each other.
        self._env_snapshot = {
            key: os.environ.get(key) for key in ("TERM_PROGRAM", "TERM", "NO_COLOR", "ELEPHANT_NO_HYPERLINKS")
        }
        for key in self._env_snapshot:
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        for key, value in self._env_snapshot.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_unsupported_terminal_returns_raw_label(self) -> None:
        os.environ["TERM"] = "dumb"
        self.assertEqual(shell_ui.wrap_file_hyperlink("/abs/path", label="path"), "path")

    def test_supported_terminal_wraps_with_osc8(self) -> None:
        os.environ["TERM_PROGRAM"] = "iTerm.app"
        wrapped = shell_ui.wrap_file_hyperlink("/abs/path", line=42, label="path:42")
        self.assertIn("\x1b]8;;file:///abs/path#L42\x1b\\", wrapped)
        self.assertTrue(wrapped.endswith("\x1b]8;;\x1b\\"))
        self.assertIn("path:42", wrapped)

    def test_no_color_suppresses_hyperlinks(self) -> None:
        os.environ["TERM_PROGRAM"] = "iTerm.app"
        os.environ["NO_COLOR"] = "1"
        self.assertFalse(shell_ui.terminal_supports_hyperlinks())
        self.assertEqual(shell_ui.wrap_file_hyperlink("/abs", label="abs"), "abs")

    def test_elephant_no_hyperlinks_opt_out(self) -> None:
        os.environ["TERM_PROGRAM"] = "iTerm.app"
        os.environ["ELEPHANT_NO_HYPERLINKS"] = "1"
        self.assertFalse(shell_ui.terminal_supports_hyperlinks())

    def test_empty_path_returns_label(self) -> None:
        os.environ["TERM_PROGRAM"] = "iTerm.app"
        self.assertEqual(shell_ui.wrap_file_hyperlink("", label="fallback"), "fallback")

    def test_line_hint_omitted_when_absent(self) -> None:
        os.environ["TERM_PROGRAM"] = "iTerm.app"
        wrapped = shell_ui.wrap_file_hyperlink("/abs", label="abs")
        self.assertIn("file:///abs", wrapped)
        self.assertNotIn("#L", wrapped)

    def test_friendly_term_without_term_program(self) -> None:
        # Kitty sets TERM=xterm-kitty without a TERM_PROGRAM on some hosts.
        os.environ["TERM"] = "xterm-kitty"
        self.assertTrue(shell_ui.terminal_supports_hyperlinks())


if __name__ == "__main__":
    unittest.main()
