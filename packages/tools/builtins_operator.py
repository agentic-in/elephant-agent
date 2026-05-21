"""Operator tool definitions and handler wiring for the built-in catalog."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .handlers_operator import run_operator_inspect, run_operator_manage
from .runtime import ToolAvailability, ToolDefinition, ToolSideEffectMetadata
from .surfaces import BuiltinToolDependencies


def operator_tool_definitions(*, reason: str | None) -> tuple[ToolDefinition, ...]:
    availability = _availability(reason is None, reason)
    return (
        ToolDefinition(
            tool_id="tool.operator.inspect",
            display_name="Operator Inspect",
            version="2.0.0",
            family="operator",
            backend="operator-runtime",
            description="Inspect Elephant Agent runtime health, model/provider state, daemon state, and governed capability surfaces.",
            schema=_object_schema(
                properties={
                    "scope": {
                        "type": "string",
                        "enum": ["summary", "runtime", "provider", "daemon", "skills", "tools", "security", "all"],
                        "description": "Runtime surface to inspect. Use summary by default; all may be broader and slower.",
                    },
                    "probe": {
                        "type": "boolean",
                        "description": "Run live diagnostics when true; false may use cached or lightweight local state.",
                    },
                    "include": {
                        "oneOf": [{"type": "array", "items": {"type": "string"}}, {"type": "string"}],
                        "description": "Optional extra sections to include, separated by | when passed as a string.",
                    },
                },
            ),
            side_effects=ToolSideEffectMetadata(
                risk_class="low",
                approval_class="standard",
                writes_state=False,
                reads_state=True,
                categories=("operator", "inspect"),
                notes="Read-only operator diagnostics with secret redaction.",
            ),
            availability=availability,
            metadata={"kind": "built-in"},
        ),
        ToolDefinition(
            tool_id="tool.operator.manage",
            display_name="Operator Manager",
            version="2.0.0",
            family="operator",
            audience="operator",
            backend="operator-runtime",
            description=(
                "Operator-only two-phase self-management surface. Use phase=plan before any mutating phase=apply."
            ),
            schema=_object_schema(
                required=("phase",),
                properties={
                    "phase": {
                        "type": "string",
                        "enum": ["plan", "apply"],
                        "description": "plan is non-mutating and returns expected changes; apply requires a confirmed plan.",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["skill.enable", "skill.disable", "provider.set_default", "daemon.restart"],
                        "description": "Self-management action to plan. Mutating actions are applied only through phase=apply after confirmation.",
                    },
                    "base_snapshot_id": {
                        "type": "string",
                        "description": "Snapshot id returned by tool.operator.inspect; used to detect stale plans.",
                    },
                    "plan_id": {
                        "type": "string",
                        "description": "Plan id returned by phase=plan. Required for phase=apply.",
                    },
                    "confirmation_token": {
                        "type": "string",
                        "description": "Operator confirmation token required by the active surface for mutating actions.",
                    },
                    "parameters": {
                        "type": "object",
                        "description": "Action-specific structured parameters; secrets must not be passed unless the action explicitly supports secure references.",
                    },
                },
            ),
            side_effects=ToolSideEffectMetadata(
                risk_class="high",
                approval_class="strict",
                writes_state=True,
                reads_state=True,
                categories=("operator", "manage"),
                notes="Plans and applies controlled self-management actions through the operator runtime.",
            ),
            availability=availability,
            metadata={"kind": "built-in"},
        ),
    )


def operator_tool_handler(
    tool_id: str,
    *,
    dependencies: BuiltinToolDependencies,
):
    if tool_id == "tool.operator.inspect":
        return lambda invocation: run_operator_inspect(invocation, surface=dependencies.operator_surface)
    if tool_id == "tool.operator.manage":
        return lambda invocation: run_operator_manage(invocation, surface=dependencies.operator_surface)
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


__all__ = ["operator_tool_definitions", "operator_tool_handler"]
