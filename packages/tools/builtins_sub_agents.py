"""Sub-agent tool definition and handler wiring."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .handlers_sub_agents import run_sub_agents_action
from .runtime import ToolAvailability, ToolDefinition, ToolSideEffectMetadata
from .surfaces import BuiltinToolDependencies


def sub_agents_tool_definitions(*, reason: str | None) -> tuple[ToolDefinition, ...]:
    return (
        ToolDefinition(
            tool_id="tool.sub_agents",
            display_name="Sub Agents",
            version="2.0.0",
            family="sub_agents",
            backend="runtime",
            description="Run, start, inspect, or join one bounded sub-agent task or a small parallel pool with optional skill guidance.",
            schema=_object_schema(
                properties={
                    "action": {
                        "type": "string",
                        "enum": ["run", "start", "status", "check", "join", "wait", "list"],
                        "description": "Whether to run synchronously, start in the background, inspect, wait for, or list sub-agent runs.",
                    },
                    "run_id": {"type": "string", "description": "Background sub-agent run id returned by action=start."},
                    "sub_agent_run_id": {
                        "type": "string",
                        "description": "Alias for run_id when checking or joining a background sub-agent run.",
                    },
                    "name": {"type": "string", "description": "Optional label for a single sub-agent task."},
                    "task": {"type": "string", "description": "Single assignment. Mutually exclusive with tasks."},
                    "prompt": {"type": "string", "description": "Alias for task. Mutually exclusive with tasks."},
                    "backend": {
                        "type": "string",
                        "enum": ["native", "local_cli", "provider"],
                        "description": "Execution backend. Use local_cli for an enabled baby backed by a local agent CLI, or provider for an enabled baby backed by the configured model provider.",
                    },
                    "baby_id": {"type": "string", "description": "Baby elephant id to use when backend=local_cli or backend=provider."},
                    "role": {"type": "string", "description": "Baby elephant role title to resolve when baby_id is omitted."},
                    "tasks": {
                        "type": "array",
                        "description": "Small parallel pool of assignments. Mutually exclusive with top-level task/prompt. Each child cannot call tool.sub_agents, tool.clarify, or tool.message.send.",
                        "items": _object_schema(
                            required=("task",),
                            properties={
                                "name": {"type": "string", "description": "Optional label for this sub-agent task."},
                                "task": {"type": "string", "description": "Assignment for this sub-agent task."},
                                "prompt": {"type": "string", "description": "Alias for task in a task-list item."},
                                "backend": {
                                    "type": "string",
                                    "enum": ["native", "local_cli", "provider"],
                                    "description": "Execution backend for this task.",
                                },
                                "baby_id": {"type": "string", "description": "Baby elephant id to use when backend=local_cli or backend=provider."},
                                "role": {"type": "string", "description": "Baby elephant role title to resolve when baby_id is omitted."},
                                "skills": {
                                    "oneOf": [
                                        {"type": "array", "items": {"type": "string"}},
                                        {"type": "string"},
                                        {"type": "object", "additionalProperties": {"type": "boolean"}},
                                    ],
                                },
                            },
                        ),
                    },
                    "max_concurrency": {"type": "integer", "minimum": 1, "maximum": 3, "description": "Maximum parallel child tasks for tasks; default is 3."},
                    "timeout_seconds": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 3600,
                        "description": "Maximum seconds for action=join or action=wait to wait for completion.",
                    },
                    "skills": {
                        "oneOf": [
                            {"type": "array", "items": {"type": "string"}},
                            {"type": "string"},
                            {"type": "object", "additionalProperties": {"type": "boolean"}},
                        ],
                        "description": "Skill ids to load for a single top-level task.",
                    },
                },
            ),
            side_effects=ToolSideEffectMetadata(
                risk_class="medium",
                approval_class="standard",
                writes_state=True,
                reads_state=True,
                categories=("sub_agents", "delegation"),
                notes="Delegates a bounded task to a runtime-managed sub-agent turn; nested delegation is blocked by the surface.",
            ),
            availability=_availability(reason is None, reason),
            metadata={"kind": "built-in"},
        ),
    )


def sub_agents_tool_handler(
    tool_id: str,
    *,
    dependencies: BuiltinToolDependencies,
):
    if tool_id == "tool.sub_agents":
        return lambda invocation: run_sub_agents_action(invocation, surface=dependencies.sub_agents_surface)
    return None


def _availability(is_available: bool, reason: str | None) -> ToolAvailability:
    return ToolAvailability(is_available=is_available, reason=None if is_available else reason)


def _object_schema(
    *,
    properties: Mapping[str, Any],
    required: tuple[str, ...] = (),
) -> Mapping[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": dict(properties),
    }
    if required:
        schema["required"] = list(required)
    return schema
