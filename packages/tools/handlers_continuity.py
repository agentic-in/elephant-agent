"""Continuity-native built-in tool handlers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from packages.contracts.runtime import ExecutionResult
from packages.cron import CronRuntime
from .handler_support import (
    optional_string,
    tool_summary,
)
from .runtime import ToolInvocation
from .surfaces import (
    TodoItem,
    TodoStore,
)


def _normalize_todo_status(value: object, *, default: str = "open") -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in {"open", "done"} else default


def run_todo_action(
    invocation: ToolInvocation,
    *,
    store: TodoStore,
) -> Mapping[str, Any]:
    action = str(invocation.arguments.get("action") or "").strip().lower()
    if not action:
        raise ValueError("tool.todo.manage requires an 'action' argument")
    session_id = invocation.session_id
    if action in {"list", "ls"}:
        items = store.list_items(session_id)
        lines = [_todo_line(item) for item in items] or ["<empty>"]
        return tool_summary(invocation, "\n".join(lines), side_effects=("todo", "scratchpad"))
    if action in {"add", "create"}:
        title = str(invocation.arguments.get("title") or "").strip()
        if not title:
            raise ValueError("tool.todo.manage create requires 'title'")
        item = store.upsert_item(
            session_id,
            title=title,
            status=_normalize_todo_status(invocation.arguments.get("status")),
            notes=str(invocation.arguments.get("notes") or ""),
        )
        return tool_summary(
            invocation,
            f"created: {_todo_line(item)}",
            side_effects=("todo", "scratchpad"),
        )
    if action == "clear":
        removed = store.clear(session_id)
        return tool_summary(invocation, f"cleared: {removed}", side_effects=("todo", "scratchpad"))
    item_id = optional_string(invocation.arguments.get("item_id"))
    if item_id is None:
        raise ValueError(f"tool.todo.manage action={action!r} requires 'item_id'")
    if action == "inspect":
        item = store.inspect_item(session_id, item_id)
        return tool_summary(
            invocation,
            "\n".join([_todo_line(item), f"notes: {item.notes or '<none>'}"]),
            side_effects=("todo", "scratchpad"),
        )
    if action in {"update", "complete", "reopen"}:
        current = store.inspect_item(session_id, item_id)
        status = {
            "complete": "done",
            "reopen": "open",
        }.get(
            action,
            _normalize_todo_status(invocation.arguments.get("status"), default=current.status),
        )
        item = store.upsert_item(
            session_id,
            item_id=item_id,
            title=optional_string(invocation.arguments.get("title")) or current.title,
            status=status,
            notes=optional_string(invocation.arguments.get("notes")) or current.notes,
            work_item_id=current.work_item_id,
        )
        return tool_summary(
            invocation,
            f"updated: {_todo_line(item)}",
            side_effects=("todo", "scratchpad"),
        )
    if action in {"remove", "delete"}:
        removed = store.remove_item(session_id, item_id)
        return tool_summary(
            invocation,
            f"removed: {_todo_line(removed)}",
            side_effects=("todo", "scratchpad"),
        )
    raise ValueError(f"tool.todo.manage does not support action={action!r}")


def run_cron_action(invocation: ToolInvocation, *, runtime: CronRuntime | None) -> ExecutionResult:
    if runtime is None:
        raise RuntimeError("cron runtime is not configured")
    action = str(invocation.arguments.get("action") or "").strip().lower()
    if not action:
        raise ValueError("tool.cron.manage requires an 'action' argument")
    if action in {"list", "ls"}:
        jobs = runtime.list_jobs(
            profile_id=optional_string(invocation.arguments.get("profile_id")),
            elephant_id=optional_string(invocation.arguments.get("elephant_id")),
        )
        summary = (
            "\n".join(
                f"{job.job_id} | {job.status} | {job.name} | {job.schedule_text} | {job.action_kind}" for job in jobs
            )
            or "<empty>"
        )
        return ExecutionResult(
            execution_id=invocation.invocation_id,
            episode_id=invocation.session_id,
            outcome="success",
            summary=summary,
            side_effects=("cron", "automation"),
        )
    if action == "create":
        name = optional_string(invocation.arguments.get("name")) or "Elephant Agent job"
        schedule = optional_string(invocation.arguments.get("schedule"))
        prompt = optional_string(invocation.arguments.get("prompt"))
        if not schedule:
            raise ValueError("cron create requires 'schedule'")
        if not prompt:
            raise ValueError("tool.cron.manage create requires 'prompt'")
        payload: dict[str, Any] = {"prompt": prompt}
        skills = _string_list(invocation.arguments.get("skills"))
        if skills:
            payload["skills"] = list(skills)
        job = runtime.create_job(
            name=name,
            schedule_text=schedule,
            payload=payload,
            profile_id=optional_string(invocation.arguments.get("profile_id")),
            elephant_id=optional_string(invocation.arguments.get("elephant_id"))
            or invocation.context.elephant_id
            or None,
        )
        return ExecutionResult(
            execution_id=invocation.invocation_id,
            episode_id=invocation.session_id,
            outcome="success",
            summary=(
                f"created {job.job_id}\n"
                f"name: {job.name}\n"
                f"schedule: {job.schedule_text}\n"
                f"job_kind: {job.action_kind}\n"
                f"skills: {', '.join(skills) if skills else '<none>'}\n"
                f"next_run_at: {job.next_run_at.isoformat() if job.next_run_at is not None else '<none>'}"
            ),
            side_effects=("cron", "automation"),
        )
    job_id = optional_string(invocation.arguments.get("job_id"))
    if not job_id:
        raise ValueError(f"cron action '{action}' requires 'job_id'")
    if action == "inspect":
        job = runtime.inspect_job(job_id)
        return ExecutionResult(
            execution_id=invocation.invocation_id,
            episode_id=invocation.session_id,
            outcome="success",
            summary=(
                f"{job.job_id}\n"
                f"name: {job.name}\n"
                f"status: {job.status}\n"
                f"schedule: {job.schedule_text}\n"
                f"action_kind: {job.action_kind}\n"
                f"skills: {', '.join(_string_list(job.payload.get('skills'))) or '<none>'}\n"
                f"next_run_at: {job.next_run_at.isoformat() if job.next_run_at is not None else '<none>'}\n"
                f"last_summary: {job.last_summary or '<none>'}"
            ),
            side_effects=("cron", "automation"),
        )
    if action == "pause":
        job = runtime.pause_job(job_id)
        summary = f"{job.job_id}\nstatus: {job.status}"
    elif action == "resume":
        job = runtime.resume_job(job_id)
        summary = (
            f"{job.job_id}\nstatus: {job.status}\n"
            f"next_run_at: {job.next_run_at.isoformat() if job.next_run_at is not None else '<none>'}"
        )
    elif action in {"remove", "delete"}:
        job = runtime.remove_job(job_id)
        summary = f"{job.job_id}\nstatus: removed"
    else:
        raise ValueError(f"unsupported cron action: {action}")
    return ExecutionResult(
        execution_id=invocation.invocation_id,
        episode_id=invocation.session_id,
        outcome="success",
        summary=summary,
        side_effects=("cron", "automation"),
    )


def _string_list(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raw_items = value.replace("\n", ",").split(",")
    elif isinstance(value, (list, tuple)):
        raw_items = [str(item) for item in value]
    else:
        raw_items = [str(value)]
    normalized = tuple(item.strip() for item in raw_items if item.strip())
    return tuple(dict.fromkeys(normalized))


def _todo_line(item: TodoItem) -> str:
    work_item_part = f" | work_item={item.work_item_id}" if item.work_item_id else ""
    return f"{item.item_id} | {item.status} | {item.title}{work_item_part}"


__all__ = [
    "run_cron_action",
    "run_todo_action",
]
