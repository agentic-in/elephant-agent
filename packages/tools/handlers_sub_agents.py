"""Sub-agent built-in tool handler."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from packages.contracts.runtime import ExecutionResult

from .handler_support import optional_string, tool_summary
from .runtime import ToolInvocation
from .surfaces import SubAgentsSurface


def run_sub_agents_action(
    invocation: ToolInvocation,
    *,
    surface: SubAgentsSurface | None,
) -> ExecutionResult:
    if surface is None:
        raise RuntimeError("sub-agents are not configured for this runtime")
    action = str(invocation.arguments.get("action") or "run").strip().lower()
    if action not in {"run", "start", "status", "check", "join", "wait", "list"}:
        raise ValueError(f"tool.sub_agents does not support action={action!r}")
    if action in {"status", "check", "join", "wait"}:
        run_id = optional_string(invocation.arguments.get("run_id") or invocation.arguments.get("sub_agent_run_id"))
        if run_id is None:
            raise ValueError("tool.sub_agents status/join requires 'run_id'")
        wait_timeout_seconds = None
        if action in {"join", "wait"}:
            wait_timeout_seconds = float(
                _int_value(
                    invocation.arguments.get("timeout_seconds"),
                    default=3600,
                    name="timeout_seconds",
                )
            )
        result = surface.inspect_sub_agent_run(
            session_id=invocation.session_id,
            run_id=run_id,
            wait_timeout_seconds=wait_timeout_seconds,
        )
        if isinstance(result, ExecutionResult):
            return result
        return tool_summary(
            invocation,
            _summary_from_result(result),
            outcome=_outcome_from_result(result),
            side_effects=("sub_agents", "delegation"),
        )
    if action == "list":
        result = surface.list_sub_agent_runs(session_id=invocation.session_id)
        if isinstance(result, ExecutionResult):
            return result
        return tool_summary(
            invocation,
            _summary_from_result(result),
            outcome=_outcome_from_result(result),
            side_effects=("sub_agents", "delegation"),
        )
    tasks = _task_list(invocation.arguments.get("tasks"))
    if tasks:
        if invocation.arguments.get("task") is not None or invocation.arguments.get("prompt") is not None:
            raise ValueError("tool.sub_agents accepts either 'task' or 'tasks', not both")
        runner = surface.start_sub_agents if action == "start" else surface.run_sub_agents
        result = runner(
            session_id=invocation.session_id,
            tasks=tasks,
            max_concurrency=_int_value(
                invocation.arguments.get("max_concurrency"),
                default=3,
                name="max_concurrency",
            ),
        )
        if isinstance(result, ExecutionResult):
            return result
        return tool_summary(
            invocation,
            _summary_from_result(result),
            outcome=_outcome_from_result(result),
            side_effects=("sub_agents", "delegation"),
        )
    task = optional_string(invocation.arguments.get("task") or invocation.arguments.get("prompt"))
    if task is None:
        raise ValueError("tool.sub_agents requires 'task' or 'tasks'")
    if action == "start":
        result = surface.start_sub_agents(
            session_id=invocation.session_id,
            tasks=(
                {
                    "task": task,
                    "name": optional_string(invocation.arguments.get("name")),
                    "skills": _string_list(invocation.arguments.get("skills")),
                },
            ),
            max_concurrency=1,
        )
    else:
        result = surface.run_sub_agent(
            session_id=invocation.session_id,
            task=task,
            name=optional_string(invocation.arguments.get("name")),
            skills=_string_list(invocation.arguments.get("skills")),
        )
    if isinstance(result, ExecutionResult):
        return result
    return tool_summary(
        invocation,
        _summary_from_result(result),
        outcome=_outcome_from_result(result),
        side_effects=("sub_agents", "delegation"),
    )


def _string_list(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raw_items = value.replace("\n", ",").split(",")
    elif isinstance(value, Mapping):
        raw_items = [str(key) for key, enabled in value.items() if enabled]
    elif isinstance(value, (list, tuple)):
        raw_items = [str(item) for item in value]
    else:
        raw_items = [str(value)]
    return tuple(dict.fromkeys(item.strip() for item in raw_items if item.strip()))


def _task_list(value: object) -> tuple[Mapping[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("tool.sub_agents 'tasks' must be an array")
    tasks: list[Mapping[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("tool.sub_agents tasks must be objects")
        task = optional_string(item.get("task") or item.get("prompt"))
        if task is None:
            raise ValueError("tool.sub_agents tasks require 'task'")
        tasks.append(
            {
                "task": task,
                "name": optional_string(item.get("name")),
                "skills": _string_list(item.get("skills")),
            }
        )
    return tuple(tasks)


def _int_value(value: object, *, default: int, name: str = "max_concurrency") -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _summary_from_result(result: Mapping[str, Any]) -> str:
    summary = str(result.get("summary") or "").strip()
    if summary:
        return summary
    return "\n".join(f"{key}: {value}" for key, value in sorted(result.items())) or "sub-agent finished"


def _outcome_from_result(result: Mapping[str, Any]) -> str:
    status = str(result.get("status") or "").strip().lower()
    if status in {"failed", "error"}:
        return "error"
    return "success"


__all__ = ["run_sub_agents_action"]
