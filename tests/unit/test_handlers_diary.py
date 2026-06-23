"""Unit tests for packages.tools.handlers_diary (diary write + list)."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.tools.handlers_diary import _parse_entry_date, run_diary_list, run_diary_write
from packages.tools.runtime import ToolInvocation, ToolRuntimeContext


def _invocation(**kwargs: object) -> ToolInvocation:
    return ToolInvocation(
        invocation_id="inv-1",
        tool_id="tool.diary.write",
        session_id="sess-1",
        context=ToolRuntimeContext(cwd=Path.cwd(), personal_model_id="pm-1"),
        arguments=kwargs,
    )


class _DiaryStub:
    def __init__(self) -> None:
        self.written: dict[str, object] = {}
        self.listed: dict[str, object] = {}

    def write_diary_entry(
        self,
        *,
        personal_model_id: str,
        entry_date: str,
        content: str,
        source_episode_ids: tuple[str, ...] = (),
        metadata: object = None,
    ) -> dict[str, object]:
        self.written = {
            "personal_model_id": personal_model_id,
            "entry_date": entry_date,
            "content": content,
            "source_episode_ids": source_episode_ids,
        }
        return {"status": "ok", "entry_date": entry_date}

    def list_diary_entries(
        self,
        *,
        personal_model_id: str,
        limit: int = 30,
        before_date: str | None = None,
    ) -> dict[str, object]:
        self.listed = {
            "personal_model_id": personal_model_id,
            "limit": limit,
            "before_date": before_date,
        }
        return {"entries": []}


class TestParseEntryDate(unittest.TestCase):
    def test_valid_date(self) -> None:
        result = _parse_entry_date("2025-05-17")
        self.assertEqual(result.year, 2025)
        self.assertEqual(result.month, 5)
        self.assertEqual(result.day, 17)

    def test_invalid_date_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            _parse_entry_date("not-a-date")
        self.assertIn("YYYY-MM-DD", str(ctx.exception))


class TestRunDiaryWrite(unittest.TestCase):
    def test_none_surface_raises(self) -> None:
        inv = _invocation(entry_date="2025-05-17", content="Hello")
        with self.assertRaises(RuntimeError):
            run_diary_write(inv, surface=None)

    def test_write_success(self) -> None:
        surface = _DiaryStub()
        inv = _invocation(entry_date="2025-05-17", content="Today was good.")
        result = run_diary_write(inv, surface=surface)
        self.assertIn("2025-05-17", result["summary"])
        self.assertEqual(surface.written["entry_date"], "2025-05-17")
        self.assertEqual(surface.written["content"], "Today was good.")

    def test_missing_entry_date_raises(self) -> None:
        surface = _DiaryStub()
        inv = _invocation(content="Hello")
        with self.assertRaises(ValueError) as ctx:
            run_diary_write(inv, surface=surface)
        self.assertIn("entry_date", str(ctx.exception))

    def test_missing_content_raises(self) -> None:
        surface = _DiaryStub()
        inv = _invocation(entry_date="2025-05-17")
        with self.assertRaises(ValueError) as ctx:
            run_diary_write(inv, surface=surface)
        self.assertIn("content", str(ctx.exception))

    def test_source_episode_ids_passed(self) -> None:
        surface = _DiaryStub()
        inv = _invocation(
            entry_date="2025-05-17",
            content="Content",
            source_episode_ids=["ep-1", "ep-2"],
        )
        run_diary_write(inv, surface=surface)
        self.assertEqual(surface.written.get("source_episode_ids"), ("ep-1", "ep-2"))


class TestRunDiaryList(unittest.TestCase):
    def test_none_surface_raises(self) -> None:
        inv = _invocation()
        with self.assertRaises(RuntimeError):
            run_diary_list(inv, surface=None)

    def test_list_success(self) -> None:
        surface = _DiaryStub()
        inv = _invocation(limit=5)
        result = run_diary_list(inv, surface=surface)
        self.assertIn("entries", result)

    def test_limit_clamped(self) -> None:
        surface = _DiaryStub()
        inv = _invocation(limit=100)
        run_diary_list(inv, surface=surface)
        self.assertLessEqual(surface.listed["limit"], 30)

    def test_before_date_passed(self) -> None:
        surface = _DiaryStub()
        inv = _invocation(before_date="2025-05-01")
        run_diary_list(inv, surface=surface)
        self.assertEqual(surface.listed["before_date"], "2025-05-01")


if __name__ == "__main__":
    unittest.main()
