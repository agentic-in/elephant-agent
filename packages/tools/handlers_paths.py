"""Built-in tool handler for durable Path management."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .handler_support import tool_summary
from .runtime import ToolInvocation
from .surfaces import PathManagementSurface


def run_path_action(
    invocation: ToolInvocation,
    *,
    surface: PathManagementSurface | None,
) -> Mapping[str, Any]:
    if surface is None:
        raise RuntimeError("Path management is not configured")
    action = str(invocation.arguments.get("action") or "").strip()
    if not action:
        raise ValueError("tool.paths.manage requires an 'action' argument")
    result = surface.manage_paths(invocation.session_id, **dict(invocation.arguments))
    summary = _compact_summary(result)
    return tool_summary(
        invocation,
        summary,
        side_effects=("paths", "flow", "learning"),
        trace_metadata={"action": action},
    )


def _compact_summary(result: Mapping[str, Any]) -> str:
    action = str(result.get("action") or "paths")
    if "path" in result:
        path = result["path"]
        if isinstance(path, Mapping):
            return f"{action}: {path.get('path_id')} | {path.get('title')} | {path.get('review_mode')}"
    if "step" in result:
        step = result["step"]
        if isinstance(step, Mapping):
            return f"{action}: {step.get('path_step_id')} | {step.get('status')} | {step.get('title')}"
    if "summary" in result:
        summary = result["summary"]
        if isinstance(summary, Mapping):
            return f"{action}: {summary.get('summary_id')} | understanding pending"
    paths = result.get("paths")
    if isinstance(paths, (list, tuple)):
        lines = [f"{action}: {len(paths)} paths"]
        for path in paths[:12]:
            if isinstance(path, Mapping):
                lines.append(f"- {path.get('path_id')} | {path.get('review_mode')} | {path.get('title')}")
                steps = path.get("steps")
                if isinstance(steps, (list, tuple)):
                    for step in steps[:8]:
                        if isinstance(step, Mapping):
                            lines.append(f"  - {step.get('path_step_id')} | {step.get('status')} | {step.get('title')}")
        return "\n".join(lines)
    return action


__all__ = ["run_path_action"]
