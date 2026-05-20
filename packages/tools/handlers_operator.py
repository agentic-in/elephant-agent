"""Operator-aware built-in tool handlers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from packages.contracts.runtime import ExecutionResult

from .handler_support import coerce_bool, coerce_choices, optional_string, tool_summary
from .runtime import ToolInvocation
from .surfaces import OperatorManagementSurface


def run_operator_inspect(
    invocation: ToolInvocation,
    *,
    surface: OperatorManagementSurface | None,
) -> Mapping[str, Any] | ExecutionResult:
    if surface is None:
        raise RuntimeError("operator management is not configured for this runtime")
    scope = optional_string(invocation.arguments.get("scope")) or "summary"
    include = coerce_choices(invocation.arguments.get("include"))
    probe = coerce_bool(invocation.arguments.get("probe"), default=False)
    payload = surface.inspect_operator(
        invocation.session_id,
        scope=scope,
        probe=probe,
        include=include,
    )
    return _operator_payload_result(
        invocation,
        payload,
        fallback_side_effects=("operator", "inspect"),
    )


def run_operator_manage(
    invocation: ToolInvocation,
    *,
    surface: OperatorManagementSurface | None,
) -> Mapping[str, Any] | ExecutionResult:
    if surface is None:
        raise RuntimeError("operator management is not configured for this runtime")
    phase = (optional_string(invocation.arguments.get("phase")) or "plan").lower()
    parameters = _coerce_mapping(invocation.arguments.get("parameters"))
    if phase == "plan":
        action = optional_string(invocation.arguments.get("action"))
        if action is None:
            raise ValueError("tool.operator.manage requires 'action' when phase=plan")
        payload = surface.plan_operator_action(
            invocation.session_id,
            action=action,
            base_snapshot_id=optional_string(invocation.arguments.get("base_snapshot_id")) or "",
            parameters=parameters,
        )
        return _operator_payload_result(
            invocation,
            payload,
            fallback_side_effects=("operator", "plan"),
        )
    if phase == "apply":
        plan_id = optional_string(invocation.arguments.get("plan_id"))
        if plan_id is None:
            raise ValueError("tool.operator.manage requires 'plan_id' when phase=apply")
        payload = surface.apply_operator_action(
            invocation.session_id,
            plan_id=plan_id,
            confirmation_token=optional_string(invocation.arguments.get("confirmation_token")) or "",
            parameters=parameters,
        )
        return _operator_payload_result(
            invocation,
            payload,
            fallback_side_effects=("operator", "apply"),
        )
    raise ValueError("tool.operator.manage phase must be plan or apply")


def _operator_payload_result(
    invocation: ToolInvocation,
    payload: Mapping[str, Any] | ExecutionResult,
    *,
    fallback_side_effects: tuple[str, ...],
) -> Mapping[str, Any] | ExecutionResult:
    if isinstance(payload, ExecutionResult):
        return payload
    if "summary" in payload:
        return payload
    outcome = "error" if payload.get("ok") is False else "success"
    return tool_summary(
        invocation,
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),
        outcome=outcome,
        side_effects=tuple(payload.get("side_effects", fallback_side_effects)),
    )


def _coerce_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


__all__ = ["run_operator_inspect", "run_operator_manage"]
