"""Unit tests for packages.tools.handlers_continuity (todo + cron handlers)."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.tools.handlers_continuity import (
    _normalize_todo_status,
    _string_list,
    run_todo_action,
)
from packages.tools.runtime import ToolInvocation, ToolRuntimeContext
from packages.tools.surfaces import InMemorySessionTodoStore, TodoItem


def _invocation(action: str, **kwargs: object) -> ToolInvocation:
    return ToolInvocation(
        invocation_id="inv-1",
        tool_id="tool.todo.manage",
        session_id="sess-1",
        context=ToolRuntimeContext(cwd=Path.cwd()),
        arguments={"action": action, **kwargs},
    )


class TestNormalizeTodoStatus(unittest.TestCase):
    def test_valid_statuses(self) -> None:
        self.assertEqual(_normalize_todo_status("open"), "open")
        self.assertEqual(_normalize_todo_status("done"), "done")
        self.assertEqual(_normalize_todo_status("DONE"), "done")
        self.assertEqual(_normalize_todo_status("Open"), "open")

    def test_invalid_returns_default(self) -> None:
        self.assertEqual(_normalize_todo_status("in_progress"), "open")
        self.assertEqual(_normalize_todo_status(""), "open")
        self.assertEqual(_normalize_todo_status(None, default="done"), "done")


class TestStringList(unittest.TestCase):
    def test_none(self) -> None:
        self.assertEqual(_string_list(None), ())

    def test_comma_separated(self) -> None:
        self.assertEqual(_string_list("a, b, c"), ("a", "b", "c"))

    def test_list(self) -> None:
        self.assertEqual(_string_list(["a", "b"]), ("a", "b"))

    def test_deduplicates(self) -> None:
        self.assertEqual(_string_list(["a", "a", "b"]), ("a", "b"))


class TestRunTodoAction(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemorySessionTodoStore()

    def test_requires_action(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            run_todo_action(_invocation(""), store=self.store)
        self.assertIn("action", str(ctx.exception))

    def test_list_empty(self) -> None:
        result = run_todo_action(_invocation("list"), store=self.store)
        self.assertIn("<empty>", result["summary"])

    def test_add(self) -> None:
        result = run_todo_action(_invocation("add", title="Buy milk"), store=self.store)
        self.assertIn("Buy milk", result["summary"])
        self.assertIn("created", result["summary"])

    def test_add_requires_title(self) -> None:
        with self.assertRaises(ValueError):
            run_todo_action(_invocation("add"), store=self.store)

    def test_list_after_add(self) -> None:
        run_todo_action(_invocation("add", title="Task 1"), store=self.store)
        result = run_todo_action(_invocation("list"), store=self.store)
        self.assertIn("Task 1", result["summary"])
        self.assertNotIn("<empty>", result["summary"])

    def test_complete(self) -> None:
        item = self.store.upsert_item("sess-1", title="Task")
        result = run_todo_action(
            _invocation("complete", item_id=item.item_id), store=self.store
        )
        self.assertIn("done", result["summary"])

    def test_reopen(self) -> None:
        item = self.store.upsert_item("sess-1", title="Task", status="done")
        result = run_todo_action(
            _invocation("reopen", item_id=item.item_id), store=self.store
        )
        self.assertIn("open", result["summary"])

    def test_update_title(self) -> None:
        item = self.store.upsert_item("sess-1", title="Old title")
        result = run_todo_action(
            _invocation("update", item_id=item.item_id, title="New title"),
            store=self.store,
        )
        self.assertIn("New title", result["summary"])

    def test_inspect(self) -> None:
        item = self.store.upsert_item("sess-1", title="Task", notes="some notes")
        result = run_todo_action(
            _invocation("inspect", item_id=item.item_id), store=self.store
        )
        self.assertIn("some notes", result["summary"])

    def test_remove(self) -> None:
        item = self.store.upsert_item("sess-1", title="Task")
        result = run_todo_action(
            _invocation("remove", item_id=item.item_id), store=self.store
        )
        self.assertIn("removed", result["summary"])

    def test_delete_alias(self) -> None:
        item = self.store.upsert_item("sess-1", title="Task")
        result = run_todo_action(
            _invocation("delete", item_id=item.item_id), store=self.store
        )
        self.assertIn("removed", result["summary"])

    def test_clear(self) -> None:
        self.store.upsert_item("sess-1", title="Task 1")
        self.store.upsert_item("sess-1", title="Task 2")
        result = run_todo_action(_invocation("clear"), store=self.store)
        self.assertIn("cleared", result["summary"])
        self.assertEqual(len(self.store.list_items("sess-1")), 0)

    def test_action_requiring_item_id_without_it(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            run_todo_action(_invocation("update"), store=self.store)
        self.assertIn("item_id", str(ctx.exception))

    def test_unsupported_action(self) -> None:
        with self.assertRaises(ValueError):
            run_todo_action(_invocation("teleport"), store=self.store)

    def test_ls_alias(self) -> None:
        result = run_todo_action(_invocation("ls"), store=self.store)
        self.assertIn("<empty>", result["summary"])

    def test_create_alias(self) -> None:
        result = run_todo_action(_invocation("create", title="New task"), store=self.store)
        self.assertIn("created", result["summary"])


class TestRunCronAction(unittest.TestCase):
    def test_none_runtime_raises(self) -> None:
        from packages.tools.handlers_continuity import run_cron_action
        inv = _invocation("list")
        with self.assertRaises(RuntimeError):
            run_cron_action(inv, runtime=None)


if __name__ == "__main__":
    unittest.main()
