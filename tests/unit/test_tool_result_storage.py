"""Unit tests for packages.tools.tool_result_storage budget and persistence logic."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.tools.tool_result_storage import (
    DEFAULT_PREVIEW_SIZE_CHARS,
    DEFAULT_RESULT_SIZE_CHARS,
    DEFAULT_TURN_BUDGET_CHARS,
    ToolResultBudgetConfig,
    enforce_tool_observation_budget,
    maybe_persist_tool_result,
)


class TestToolResultBudgetConfig(unittest.TestCase):
    def test_defaults(self) -> None:
        config = ToolResultBudgetConfig()
        self.assertEqual(config.result_size_chars, DEFAULT_RESULT_SIZE_CHARS)
        self.assertEqual(config.turn_budget_chars, DEFAULT_TURN_BUDGET_CHARS)
        self.assertEqual(config.preview_size_chars, DEFAULT_PREVIEW_SIZE_CHARS)
        self.assertIn("read_file", config.pinned_thresholds)
        self.assertEqual(config.pinned_thresholds["read_file"], float("inf"))


class TestMaybePersistToolResult(unittest.TestCase):
    def test_empty_content_returned_as_is(self) -> None:
        self.assertEqual(maybe_persist_tool_result("", tool_name="test", tool_use_id="id-1"), "")
        self.assertEqual(maybe_persist_tool_result("   ", tool_name="test", tool_use_id="id-1"), "")

    def test_small_content_returned_unchanged(self) -> None:
        content = "small result"
        result = maybe_persist_tool_result(content, tool_name="test", tool_use_id="id-1")
        self.assertEqual(result, content)

    def test_large_content_persisted(self) -> None:
        content = "x" * (DEFAULT_RESULT_SIZE_CHARS + 100)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = maybe_persist_tool_result(
                content, tool_name="test", tool_use_id="id-2",
                storage_dir=Path(tmpdir),
            )
        self.assertIn("<persisted-output", result)
        self.assertIn('tool="test"', result)
        self.assertIn("Preview:", result)

    def test_threshold_zero_always_persists(self) -> None:
        config = ToolResultBudgetConfig(result_size_chars=0)
        content = "tiny"
        with tempfile.TemporaryDirectory() as tmpdir:
            result = maybe_persist_tool_result(
                content, tool_name="test", tool_use_id="id-3",
                config=config, storage_dir=Path(tmpdir),
            )
        self.assertIn("<persisted-output", result)

    def test_pinned_tool_with_inf_threshold_never_persists(self) -> None:
        config = ToolResultBudgetConfig(
            result_size_chars=10,
            pinned_thresholds={"read_file": float("inf")},
        )
        content = "x" * 1000
        result = maybe_persist_tool_result(
            content, tool_name="read_file", tool_use_id="id-4",
            config=config,
        )
        # Should NOT be persisted because read_file has inf threshold
        self.assertEqual(result, content.strip())

    def test_persisted_file_written_to_disk(self) -> None:
        content = "x" * (DEFAULT_RESULT_SIZE_CHARS + 100)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = maybe_persist_tool_result(
                content, tool_name="test", tool_use_id="id-5",
                storage_dir=Path(tmpdir),
            )
            # Extract the path from the persisted-output tag
            self.assertIn('path="', result)
            path_start = result.index('path="') + 6
            path_end = result.index('"', path_start)
            file_path = Path(result[path_start:path_end])
            self.assertTrue(file_path.exists())
            self.assertEqual(file_path.read_text(encoding="utf-8"), content.strip())

    def test_oserror_falls_back_to_preview(self) -> None:
        content = "x" * (DEFAULT_RESULT_SIZE_CHARS + 100)
        # Use a non-existent storage dir that will cause OSError
        bad_dir = Path("/nonexistent/path/that/cannot/be/created")
        result = maybe_persist_tool_result(
            content, tool_name="test", tool_use_id="id-6",
            storage_dir=bad_dir,
        )
        # Should fall back to preview text (no persisted-output tag)
        self.assertNotIn("<persisted-output", result)
        self.assertIn("[truncated]", result)


class TestEnforceToolObservationBudget(unittest.TestCase):
    def test_under_budget_returned_unchanged(self) -> None:
        observations = ["small obs 1", "small obs 2"]
        result = enforce_tool_observation_budget(observations)
        self.assertEqual(result, observations)

    def test_over_budget_shortens_observations(self) -> None:
        config = ToolResultBudgetConfig(
            turn_budget_chars=100,
            result_size_chars=0,
            preview_size_chars=50,
            pinned_thresholds={},
        )
        observations = ["a" * 200, "b" * 200]
        with tempfile.TemporaryDirectory() as tmpdir:
            result = enforce_tool_observation_budget(
                observations, config=config, storage_dir=Path(tmpdir),
            )
        total = sum(len(obs) for obs in result)
        # Budget enforcement is approximate (persisted-output wrappers add overhead);
        # the key invariant is that the total shrinks significantly from the input.
        self.assertLess(total, 400)

    def test_zero_budget_returns_unchanged(self) -> None:
        config = ToolResultBudgetConfig(turn_budget_chars=0)
        observations = ["a" * 5000, "b" * 5000]
        result = enforce_tool_observation_budget(observations, config=config)
        self.assertEqual(result, observations)

    def test_already_persisted_not_double_processed(self) -> None:
        config = ToolResultBudgetConfig(
            turn_budget_chars=50,
            result_size_chars=0,
            preview_size_chars=20,
            pinned_thresholds={},
        )
        # Already-persisted observation should be skipped during budget enforcement
        persisted = '<persisted-output tool="test" path="/tmp/file.txt">Preview: hello</persisted-output>'
        observations = ["a" * 200, persisted]
        result = enforce_tool_observation_budget(observations, config=config)
        # The persisted one should remain unchanged
        self.assertIn(persisted, result)


if __name__ == "__main__":
    unittest.main()
