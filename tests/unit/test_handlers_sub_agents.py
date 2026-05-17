"""Unit tests for packages.tools.handlers_sub_agents (sub-agents handler)."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.tools.handlers_sub_agents import (
    _int_value,
    _outcome_from_result,
    _string_list,
    _summary_from_result,
    _task_list,
    run_sub_agents_action,
)
from packages.tools.runtime import ToolInvocation, ToolRuntimeContext


def _invocation(**kwargs: object) -> ToolInvocation:
    return ToolInvocation(
        invocation_id="inv-1",
        tool_id="tool.sub_agents",
        session_id="sess-1",
        context=ToolRuntimeContext(cwd=Path.cwd()),
        arguments=kwargs,
    )


class _SubAgentsStub:
    def __init__(self) -> None:
        self.last_action: str = ""
        self.last_task: str | None = None
        self.last_tasks: tuple[dict[str, object], ...] | None = None

    def run_sub_agent(
        self,
        *,
        session_id: str,
        task: str,
        name: str | None = None,
        skills: tuple[str, ...] = (),
    ) -> dict[str, str]:
        self.last_action = "run"
        self.last_task = task
        return {"summary": f"ran: {task}", "status": "success"}

    def run_sub_agents(
        self,
        *,
        session_id: str,
        tasks: tuple[dict[str, object], ...],
        max_concurrency: int = 3,
    ) -> dict[str, str]:
        self.last_action = "run_batch"
        self.last_tasks = tasks
        return {"summary": f"ran {len(tasks)} tasks", "status": "success"}

    def start_sub_agents(
        self,
        *,
        session_id: str,
        tasks: tuple[dict[str, object], ...],
        max_concurrency: int = 3,
    ) -> dict[str, str]:
        self.last_action = "start"
        self.last_tasks = tasks
        return {"summary": "started", "status": "running", "run_id": "subrun-1"}

    def inspect_sub_agent_run(
        self,
        *,
        session_id: str,
        run_id: str,
        wait_timeout_seconds: float | None = None,
    ) -> dict[str, str]:
        self.last_action = "inspect"
        return {"summary": f"run {run_id} status", "status": "running"}

    def list_sub_agent_runs(self, *, session_id: str) -> dict[str, str]:
        self.last_action = "list"
        return {"summary": "no runs", "status": "ok"}


class TestStringValue(unittest.TestCase):
    def test_none_returns_default(self) -> None:
        self.assertEqual(_int_value(None, default=3), 3)

    def test_valid_int(self) -> None:
        self.assertEqual(_int_value("5", default=3), 5)

    def test_invalid_raises(self) -> None:
        with self.assertRaises(ValueError):
            _int_value("abc", default=3)


class TestStringList(unittest.TestCase):
    def test_none(self) -> None:
        self.assertEqual(_string_list(None), ())

    def test_comma_separated(self) -> None:
        self.assertEqual(_string_list("a, b, c"), ("a", "b", "c"))

    def test_list_input(self) -> None:
        self.assertEqual(_string_list(["a", "b"]), ("a", "b"))

    def test_mapping_filters_enabled(self) -> None:
        self.assertEqual(_string_list({"a": True, "b": False, "c": True}), ("a", "c"))

    def test_deduplicates(self) -> None:
        self.assertEqual(_string_list(["a", "a", "b"]), ("a", "b"))


class TestTaskList(unittest.TestCase):
    def test_none_returns_empty(self) -> None:
        self.assertEqual(_task_list(None), ())

    def test_valid_tasks(self) -> None:
        tasks = [{"task": "do stuff"}, {"prompt": "do other"}]
        result = _task_list(tasks)
        self.assertEqual(len(result), 2)

    def test_non_list_raises(self) -> None:
        with self.assertRaises(ValueError):
            _task_list("not a list")

    def test_missing_task_raises(self) -> None:
        with self.assertRaises(ValueError):
            _task_list([{"name": "no task"}])


class TestSummaryFromResult(unittest.TestCase):
    def test_with_summary(self) -> None:
        self.assertEqual(_summary_from_result({"summary": "done"}), "done")

    def test_without_summary(self) -> None:
        result = _summary_from_result({"status": "ok"})
        self.assertIn("status", result)

    def test_empty_result(self) -> None:
        self.assertEqual(_summary_from_result({}), "sub-agent finished")


class TestOutcomeFromResult(unittest.TestCase):
    def test_success(self) -> None:
        self.assertEqual(_outcome_from_result({"status": "running"}), "success")

    def test_error(self) -> None:
        self.assertEqual(_outcome_from_result({"status": "failed"}), "error")

    def test_empty_status(self) -> None:
        self.assertEqual(_outcome_from_result({}), "success")


class TestRunSubAgentsAction(unittest.TestCase):
    def test_none_surface_raises(self) -> None:
        inv = _invocation(action="run", task="hello")
        with self.assertRaises(RuntimeError):
            run_sub_agents_action(inv, surface=None)

    def test_unsupported_action(self) -> None:
        surface = _SubAgentsStub()
        inv = _invocation(action="fly", task="hello")
        with self.assertRaises(ValueError):
            run_sub_agents_action(inv, surface=surface)

    def test_run_single_task(self) -> None:
        surface = _SubAgentsStub()
        inv = _invocation(action="run", task="do something")
        result = run_sub_agents_action(inv, surface=surface)
        # run_sub_agents_action returns ExecutionResult or Mapping; the stub
        # returns a plain dict so the handler wraps it via tool_summary.
        self.assertIn("success", str(result.get("outcome", "")) + str(getattr(result, "outcome", "")))
        self.assertEqual(surface.last_action, "run")

    def test_run_with_prompt(self) -> None:
        surface = _SubAgentsStub()
        inv = _invocation(action="run", prompt="do something")
        result = run_sub_agents_action(inv, surface=surface)
        self.assertEqual(surface.last_task, "do something")

    def test_start_batch(self) -> None:
        surface = _SubAgentsStub()
        inv = _invocation(action="start", tasks=[{"task": "t1"}, {"task": "t2"}])
        result = run_sub_agents_action(inv, surface=surface)
        self.assertEqual(surface.last_action, "start")

    def test_status_requires_run_id(self) -> None:
        surface = _SubAgentsStub()
        inv = _invocation(action="status")
        with self.assertRaises(ValueError):
            run_sub_agents_action(inv, surface=surface)

    def test_status_with_run_id(self) -> None:
        surface = _SubAgentsStub()
        inv = _invocation(action="status", run_id="run-1")
        result = run_sub_agents_action(inv, surface=surface)
        self.assertEqual(surface.last_action, "inspect")

    def test_list(self) -> None:
        surface = _SubAgentsStub()
        inv = _invocation(action="list")
        result = run_sub_agents_action(inv, surface=surface)
        self.assertEqual(surface.last_action, "list")

    def test_both_task_and_tasks_raises(self) -> None:
        surface = _SubAgentsStub()
        inv = _invocation(action="run", task="t1", tasks=[{"task": "t2"}])
        with self.assertRaises(ValueError):
            run_sub_agents_action(inv, surface=surface)

    def test_no_task_or_tasks_raises(self) -> None:
        surface = _SubAgentsStub()
        inv = _invocation(action="run")
        with self.assertRaises(ValueError):
            run_sub_agents_action(inv, surface=surface)

    def test_skills_passed(self) -> None:
        surface = _SubAgentsStub()
        inv = _invocation(action="run", task="hello", skills=["skill-a"])
        run_sub_agents_action(inv, surface=surface)
        self.assertEqual(surface.last_action, "run")


if __name__ == "__main__":
    unittest.main()
