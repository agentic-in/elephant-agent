"""Process management built-in tool handlers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .handler_support import coerce_int, optional_string, tool_summary
from .runtime import ToolInvocation
from .surfaces import InMemoryProcessManager, ManagedProcess


def run_process_action(invocation: ToolInvocation, *, manager: InMemoryProcessManager) -> Mapping[str, Any]:
    action = str(invocation.arguments.get("action") or "").strip().lower()
    if not action:
        raise ValueError("tool.process.manage requires an 'action' argument")
    if action in {"list", "ls"}:
        processes = manager.list()
        lines = [
            f"{process.process_id} | {'running' if process.running else f'exited({process.returncode})'} | {process.command}"
            for process in processes
        ] or ["<empty>"]
        return tool_summary(invocation, "\n".join(lines), side_effects=("process",))
    process_id = optional_string(invocation.arguments.get("process_id"))
    if process_id is None:
        raise ValueError(f"tool.process.manage action={action!r} requires 'process_id'")
    if action in {"poll", "inspect"}:
        managed = manager.capture_if_finished(process_id)
        return tool_summary(invocation, _process_summary(managed), side_effects=("process",))
    if action == "wait":
        managed = manager.wait(
            process_id,
            timeout_seconds=max(1, min(coerce_int(invocation.arguments.get("timeout_seconds"), default=20), 120)),
        )
        return tool_summary(invocation, _process_summary(managed), side_effects=("process",))
    if action == "write":
        data = str(invocation.arguments.get("input") or "")
        manager.write(process_id, data)
        managed = manager.get(process_id)
        return tool_summary(
            invocation,
            (
                f"process_id: {managed.process_id}\n"
                f"status: {'running' if managed.running else 'finished'}\n"
                f"input_written: {len(data)} bytes"
            ),
            side_effects=("process",),
        )
    if action == "kill":
        managed = manager.kill(process_id)
        return tool_summary(invocation, _process_summary(managed), side_effects=("process",))
    raise ValueError(f"tool.process.manage does not support action={action!r}")


def _process_summary(process: ManagedProcess) -> str:
    status = "running" if process.running else f"exited({process.returncode})"
    parts = [
        f"process_id: {process.process_id}",
        f"status: {status}",
        f"cwd: {process.cwd}",
        f"command: {process.command}",
    ]
    if process.stdout:
        parts.append("stdout:")
        parts.append(process.stdout.rstrip())
    if process.stderr:
        parts.append("stderr:")
        parts.append(process.stderr.rstrip())
    return "\n".join(parts)


__all__ = ["run_process_action"]
