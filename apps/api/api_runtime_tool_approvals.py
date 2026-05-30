"""HTTP-facing helpers for pending tool approval records."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from .api_runtime_support import _jsonable


def pending_tool_approval_records(self, *, episode_id: str) -> tuple[dict[str, Any], ...]:
    pending = getattr(self.tool_runtime, "list_pending_approvals", None)
    if not callable(pending):
        return ()
    return tuple(item.to_record() for item in pending(session_id=episode_id))


def resolve_tool_approval(
    self,
    *,
    episode_id: str,
    approval_token: str,
    approved: bool,
) -> dict[str, Any]:
    tool_runtime = getattr(self, "tool_runtime", None)
    method_name = "approve_pending" if approved else "deny_pending"
    resolver = getattr(tool_runtime, method_name, None)
    if not callable(resolver):
        raise RuntimeError("tool approval resolution is not available")
    record = resolver(
        approval_token,
        session_id=episode_id,
        approver="macOS Chat",
    )
    return {
        "episode_id": episode_id,
        "approval_token": approval_token,
        "approval": _jsonable(record.approval),
        "execution": _jsonable(record.result),
        "tool_event": tool_execution_record_event(record),
    }


def tool_execution_record_event(record: Any) -> dict[str, Any]:
    invocation = getattr(record, "invocation", None)
    approval = getattr(record, "approval", None)
    execution = getattr(record, "result", None)
    outcome = str(getattr(execution, "outcome", "") or "").lower()
    status = "completed" if outcome in {"", "ok", "success"} else outcome
    return {
        "type": "tool.lifecycle",
        "event_type": "tool_execute",
        "id": str(getattr(record, "execution_id", "") or getattr(invocation, "invocation_id", "") or uuid4().hex),
        "invocation_id": str(getattr(invocation, "invocation_id", "") or ""),
        "name": str(getattr(invocation, "tool_id", "") or "tool"),
        "tool_name": str(getattr(invocation, "tool_id", "") or "tool"),
        "status": status,
        "phase": "execution.completed" if status == "completed" else status,
        "detail": str(getattr(record, "detail", "") or ""),
        "arguments": dict(getattr(invocation, "arguments", {}) or {}),
        "tool_arguments": dict(getattr(invocation, "arguments", {}) or {}),
        "result": str(getattr(execution, "summary", "") or ""),
        "tool_result": str(getattr(execution, "summary", "") or ""),
        "approval": _jsonable(approval) if approval is not None else None,
        "execution": _jsonable(execution) if execution is not None else None,
    }
