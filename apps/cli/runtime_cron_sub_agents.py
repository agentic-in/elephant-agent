"""Prompt composers for scheduled and delegated CLI runtime turns."""

from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor, as_completed, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import BoundedSemaphore, Lock
import traceback
from typing import Any
from uuid import uuid4

from packages.contracts.layers import Episode
from packages.contracts.runtime import ExecutionResult
from packages.cron import CronJob
from packages.operator.local_agent_adapters import run_local_agent_cli
from packages.tools.runtime import ToolInvocation, ToolLifecycleEvent
from apps.cli.runtime_cron_sub_agent_babies import (
    activate_provider_baby_profile,
    compose_local_cli_baby_prompt,
    compose_provider_baby_prompt,
    resolve_baby,
)
from apps.cli.runtime_cron_sub_agent_events import sub_agent_event_arguments


@dataclass(slots=True)
class _AsyncSubAgentRun:
    run_id: str
    parent_session_id: str
    tasks: tuple[Mapping[str, Any], ...]
    max_concurrency: int
    created_at: datetime
    results: list[Mapping[str, Any] | None]
    futures: tuple[Future, ...] = ()
    executor: ThreadPoolExecutor | None = None
    status: str = "running"
    completed_at: datetime | None = None
    lock: Lock = field(default_factory=Lock)


_ASYNC_SUB_AGENT_RUNS: dict[str, _AsyncSubAgentRun] = {}
_ASYNC_SUB_AGENT_RUNS_LOCK = Lock()
_LOCAL_CLI_SEMAPHORE = BoundedSemaphore(2)
_LOCAL_CLI_BABY_LOCKS: dict[str, Lock] = {}
_LOCAL_CLI_BABY_LOCKS_GUARD = Lock()


class _AllowedToolRuntime:
    def __init__(self, runtime: Any, allowed_tool_ids: tuple[str, ...]) -> None:
        self._runtime = runtime
        self._allowed_tool_ids = frozenset(allowed_tool_ids)
        self.descriptor = runtime.descriptor

    def _ensure_allowed(self, tool_id: str) -> None:
        if tool_id not in self._allowed_tool_ids:
            raise PermissionError(f"tool is not allowed for this sub-agent: {tool_id}")

    def describe(self, tool_id: str):
        if tool_id not in self._allowed_tool_ids:
            return None
        return self._runtime.describe(tool_id)

    def list_tools(self, **kwargs: Any) -> tuple[Any, ...]:
        return tuple(tool for tool in self._runtime.list_tools(**kwargs) if tool.tool_id in self._allowed_tool_ids)

    def invoke(self, tool_name: str, arguments: Mapping[str, Any], *, session_id: str, requester: str | None = None):
        self._ensure_allowed(tool_name)
        return self._runtime.invoke(tool_name, arguments, session_id=session_id, requester=requester)

    def subscribe(self, observer: Any):
        return self._runtime.subscribe(observer)

    def list_executions(self) -> tuple[Any, ...]:
        return self._runtime.list_executions()



def cron_skill_ids(value: object) -> tuple[str, ...]:
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


def compose_cron_prompt(runtime: Any, job: CronJob, *, user_prompt: str, session_id: str) -> str:
    skill_sections = _skill_sections(runtime, cron_skill_ids(job.payload.get("skills")), session_id=session_id)
    sections = [
        "[SYSTEM: This turn is running as a scheduled Elephant Agent cron job.]",
        "The scheduler will surface your final text response to the user via the bound IM channel; do not call tool.message.send from this job.",
        "Do not call tool.cron.manage from this job. You may not pause, resume, remove, or create cron jobs from inside a cron turn — the user alone controls the schedule.",
        "Produce the scheduled content unconditionally, exactly as requested by the task below. The time of day, whether the user is online, and recent silence are all irrelevant; the user set this schedule deliberately and expects output every tick.",
        "Only respond with the single literal token [SILENT] when the scheduled task is fundamentally impossible this tick (e.g. a required data source is broken). 'The user is asleep' or 'I have already greeted recently' are NOT valid reasons to be silent.",
        "",
        f"Cron job: {job.name} ({job.job_id})",
        f"Schedule: {job.schedule_text}",
    ]
    if skill_sections:
        sections.extend(["", "Scheduled skill references:", "\n\n".join(skill_sections)])
    sections.extend(["", f"Scheduled task:\n{user_prompt}"])
    return "\n".join(sections).strip()


def run_sub_agent_task(
    runtime: Any,
    *,
    session_id: str,
    task: str,
    name: str | None = None,
    skills: tuple[str, ...] = (),
    allowed_tools: tuple[str, ...] = (),
    system_prompt: str = "",
    learning_agent: bool = False,
    child_metadata: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    result = run_sub_agent_tasks(
        runtime,
        session_id=session_id,
        tasks=({"task": task, "name": name, "skills": skills, "allowed_tools": allowed_tools, "system_prompt": system_prompt, "learning_agent": learning_agent, "child_metadata": dict(child_metadata or {})},),
        max_concurrency=1,
    )
    results = tuple(result.get("results") or ())
    if not results:
        return {
            "name": name or "sub-agent",
            "summary": "sub-agent did not return a result",
            "skills": list(skills),
            "status": "failed",
        }
    return results[0]


def run_sub_agent_tasks(
    runtime: Any,
    *,
    session_id: str,
    tasks: tuple[Mapping[str, Any], ...],
    max_concurrency: int = 3,
) -> Mapping[str, Any]:
    if runtime.sub_agent_active:
        raise RuntimeError("nested sub-agent delegation is not allowed")
    normalized = tuple(_normalize_sub_agent_task(item) for item in tasks)
    if not normalized:
        raise ValueError("tool.sub_agents requires at least one task")
    workers = max(1, min(int(max_concurrency or 1), len(normalized), 3))
    prepared = tuple(
        _prepare_sub_agent_child(
            runtime,
            parent_session_id=session_id,
            task=item["task"],
            name=item.get("name"),
            skills=tuple(item.get("skills") or ()),
            allowed_tools=tuple(item.get("allowed_tools") or ()),
            system_prompt=str(item.get("system_prompt") or ""),
            learning_agent=bool(item.get("learning_agent")),
            child_metadata=item.get("child_metadata") if isinstance(item.get("child_metadata"), Mapping) else None,
            backend=str(item.get("backend") or ""),
            baby_id=str(item.get("baby_id") or ""),
            role=str(item.get("role") or ""),
            timeout_seconds=str(item.get("timeout_seconds") or ""),
        )
        for item in normalized
    )
    results: list[Mapping[str, Any] | None] = [None] * len(normalized)
    object.__setattr__(runtime, "sub_agent_active", True)
    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    _run_prepared_sub_agent_child,
                    runtime,
                    prepared_child=item,
                ): index
                for index, item in enumerate(prepared)
            }
            for future in as_completed(futures):
                index = futures[future]
                results[index] = future.result()
    finally:
        object.__setattr__(runtime, "sub_agent_active", False)
    resolved = tuple(item for item in results if item is not None)
    status = _aggregate_sub_agent_status(results)
    summary = "\n".join(
        f"{index + 1}. {item.get('name') or 'sub-agent'}: {item.get('summary') or item.get('status') or 'finished'}"
        for index, item in enumerate(resolved)
    )
    return {
        "summary": summary or "sub-agent pool finished",
        "results": list(resolved),
        "max_concurrency": workers,
        "status": status,
    }


def start_sub_agent_tasks(
    runtime: Any,
    *,
    session_id: str,
    tasks: tuple[Mapping[str, Any], ...],
    max_concurrency: int = 3,
) -> Mapping[str, Any]:
    if runtime.sub_agent_active:
        raise RuntimeError("nested sub-agent delegation is not allowed")
    normalized = tuple(_normalize_sub_agent_task(item) for item in tasks)
    if not normalized:
        raise ValueError("tool.sub_agents requires at least one task")
    workers = max(1, min(int(max_concurrency or 1), len(normalized), 3))
    prepared = tuple(
        _prepare_sub_agent_child(
            runtime,
            parent_session_id=session_id,
            task=item["task"],
            name=item.get("name"),
            skills=tuple(item.get("skills") or ()),
            allowed_tools=tuple(item.get("allowed_tools") or ()),
            system_prompt=str(item.get("system_prompt") or ""),
            learning_agent=bool(item.get("learning_agent")),
            child_metadata=item.get("child_metadata") if isinstance(item.get("child_metadata"), Mapping) else None,
            backend=str(item.get("backend") or ""),
            baby_id=str(item.get("baby_id") or ""),
            role=str(item.get("role") or ""),
            timeout_seconds=str(item.get("timeout_seconds") or ""),
        )
        for item in normalized
    )
    run_id = f"subrun-{uuid4().hex[:12]}"
    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"elephant-subagents-{run_id[-6:]}")
    run = _AsyncSubAgentRun(
        run_id=run_id,
        parent_session_id=session_id,
        tasks=normalized,
        max_concurrency=workers,
        created_at=datetime.now(timezone.utc),
        results=[None] * len(normalized),
        executor=executor,
    )
    futures: list[Future] = []
    for index, item in enumerate(prepared):
        future = executor.submit(
            _run_prepared_sub_agent_child,
            runtime,
            prepared_child=item,
            run_id=run_id,
            task_index=index,
        )
        future.add_done_callback(lambda completed, task_index=index: _record_async_sub_agent_result(run, task_index, completed))
        futures.append(future)
    run.futures = tuple(futures)
    with _ASYNC_SUB_AGENT_RUNS_LOCK:
        _ASYNC_SUB_AGENT_RUNS[run_id] = run
    return _sub_agent_run_payload(run)


def inspect_sub_agent_run(
    runtime: Any,
    *,
    session_id: str,
    run_id: str,
    wait_timeout_seconds: float | None = None,
) -> Mapping[str, Any]:
    del runtime
    run = _get_async_sub_agent_run(run_id)
    if run.parent_session_id != session_id:
        raise KeyError(f"sub-agent run is not attached to this session: {run_id}")
    if wait_timeout_seconds is not None:
        wait(run.futures, timeout=max(0.0, wait_timeout_seconds))
        _refresh_async_sub_agent_run(run)
    return _sub_agent_run_payload(run)


def list_sub_agent_runs(
    runtime: Any,
    *,
    session_id: str,
) -> Mapping[str, Any]:
    del runtime
    with _ASYNC_SUB_AGENT_RUNS_LOCK:
        runs = tuple(run for run in _ASYNC_SUB_AGENT_RUNS.values() if run.parent_session_id == session_id)
    return {
        "status": "completed",
        "summary": "\n".join(
            f"{run.run_id}: {run.status} ({_completed_sub_agent_count(run)}/{len(run.results)} done)"
            for run in runs
        )
        or "no sub-agent runs",
        "runs": [_sub_agent_run_payload(run) for run in runs],
    }


def _run_one_sub_agent_child(
    runtime: Any,
    *,
    parent_session_id: str,
    task: str,
    name: str | None,
    skills: tuple[str, ...],
) -> Mapping[str, Any]:
    prepared = _prepare_sub_agent_child(
        runtime,
        parent_session_id=parent_session_id,
        task=task,
        name=name,
        skills=skills,
        allowed_tools=(),
    )
    return _run_prepared_sub_agent_child(runtime, prepared_child=prepared)


def _prepare_sub_agent_child(
    runtime: Any,
    *,
    parent_session_id: str,
    task: str,
    name: str | None,
    skills: tuple[str, ...],
    allowed_tools: tuple[str, ...],
    system_prompt: str = "",
    learning_agent: bool = False,
    child_metadata: Mapping[str, Any] | None = None,
    backend: str = "",
    baby_id: str = "",
    role: str = "",
    timeout_seconds: str = "",
) -> Mapping[str, Any]:
    backend = backend.strip().lower()
    baby = resolve_baby(runtime, backend=backend, baby_id=baby_id, role=role) if backend in {"local_cli", "provider"} else None
    effective_metadata = dict(child_metadata or {})
    if baby is not None:
        baby_state = baby["state"]
        effective_metadata.update({
            "backend": backend,
            "baby_id": baby_state.elephant_id,
            "baby_state_id": baby_state.state_id,
            "baby_name": getattr(baby_state, "elephant_name", "") or baby_state.elephant_id,
            "baby_role": baby["role_title"],
            "provider_id": baby.get("provider_id", ""),
            "runtime_model": baby.get("provider_model", ""),
            "delegated_by": parent_session_id,
        })
        runtime_record = baby.get("runtime")
        if runtime_record is not None:
            effective_metadata.update({
                "runtime_id": runtime_record.runtime_id,
                "runtime_display_name": runtime_record.display_name,
                "runtime_path": runtime_record.resolved_path,
                "runtime_model": runtime_record.default_model,
            })
    child = _open_sub_agent_child_episode(
        runtime,
        parent_session_id,
        learning_agent=learning_agent,
        child_metadata=effective_metadata,
        state=baby["state"] if baby is not None else None,
    )
    child_session_id = child.episode_id
    if baby is not None and backend == "local_cli":
        prompt = compose_local_cli_baby_prompt(task=task, name=name, baby=baby)
    elif baby is not None and backend == "provider":
        prompt = compose_provider_baby_prompt(task=task, name=name, baby=baby)
    else:
        prompt = task if system_prompt.strip() else _compose_sub_agent_prompt(
            runtime,
            task=task,
            name=name,
            skills=skills,
            session_id=child_session_id,
        )
    return {
        "name": name or "sub-agent",
        "task": task,
        "prompt": prompt,
        "system_prompt": system_prompt.strip(),
        "session_id": child_session_id,
        "parent_session_id": parent_session_id,
        "skills": skills,
        "allowed_tools": tuple(dict.fromkeys(item.strip() for item in allowed_tools if item.strip())),
        "learning_agent": learning_agent,
        "child_metadata": effective_metadata,
        "backend": backend or "native",
        "baby": baby,
        "timeout_seconds": timeout_seconds or "1800",
    }


def _open_sub_agent_child_episode(
    runtime: Any,
    parent_session_id: str,
    *,
    learning_agent: bool = False,
    child_metadata: Mapping[str, Any] | None = None,
    state: Any | None = None,
) -> Episode:
    parent = runtime.repository.load_episode(parent_session_id)
    if parent is None:
        raise KeyError(f"episode not found: {parent_session_id}")
    child_state = state
    if child_state is None:
        child_state = runtime.repository.load_state(parent.state_id) if parent.state_id else None
    now = datetime.now(timezone.utc)
    metadata = {
        "episode_kind": "sub_agent",
        "parent_episode_id": parent.episode_id,
        "learning_agent": "true" if learning_agent else "false",
        "opened_at": now.isoformat(),
    }
    if child_metadata:
        metadata.update({str(key): value for key, value in child_metadata.items() if str(key).strip()})
    child = Episode(
        episode_id=uuid4().hex,
        state_id=child_state.state_id if child_state is not None else parent.state_id,
        personal_model_id=child_state.personal_model_id if child_state is not None else parent.personal_model_id,
        entry_surface=f"{parent.entry_surface}:sub_agent",
        elephant_id=child_state.elephant_id if child_state is not None else parent.elephant_id,
        status="open",
        started_at=now,
        updated_at=now,
        parent_episode_id=parent.episode_id,
        metadata=metadata,
    )
    runtime.repository.upsert_episode(child)
    return child


def _run_prepared_sub_agent_child(
    runtime: Any,
    *,
    prepared_child: Mapping[str, Any],
    run_id: str | None = None,
    task_index: int | None = None,
) -> Mapping[str, Any]:
    child_session_id = str(prepared_child["session_id"])
    name = str(prepared_child.get("name") or "sub-agent")
    skills = tuple(str(item) for item in prepared_child.get("skills") or ())
    prompt = str(prepared_child.get("prompt") or "")
    system_prompt = str(prepared_child.get("system_prompt") or "").strip()
    allowed_tools = tuple(str(item).strip() for item in prepared_child.get("allowed_tools") or () if str(item).strip())
    learning_agent_turn = bool(prepared_child.get("learning_agent"))
    started_at = datetime.now(timezone.utc)
    child_runtime = None
    unsubscribe = None
    unsubscribe_model_stream = None
    _emit_sub_agent_event(
        runtime,
        prepared_child=prepared_child,
        phase="execution.started",
        detail=f"started sub-agent {name}",
        run_id=run_id,
        task_index=task_index,
        requested_at=started_at,
    )
    try:
        if str(prepared_child.get("backend") or "").strip().lower() == "local_cli":
            return _run_prepared_local_cli_baby(
                runtime,
                prepared_child=prepared_child,
                name=name,
                prompt=prompt,
                skills=skills,
                run_id=run_id,
                task_index=task_index,
                started_at=started_at,
            )
        child_runtime = _create_child_runtime(runtime)
        isolated_snapshot = runtime.paths.state_dir / "sub-agent-snapshots" / f"{child_session_id}.json"
        isolated_snapshot.parent.mkdir(parents=True, exist_ok=True)
        object.__setattr__(child_runtime, "snapshot_path", isolated_snapshot)
        object.__setattr__(child_runtime, "sub_agent_active", True)
        if str(prepared_child.get("backend") or "").strip().lower() == "provider":
            activate_provider_baby_profile(runtime, child_runtime, prepared_child=prepared_child)
        child_runtime.prepare_session_surface(child_session_id)
        if allowed_tools or learning_agent_turn:
            # Scope tool runtime: learning agents with empty allowed_tools get NO
            # tools (e.g. compress only needs text output, not conversation search).
            scoped_tool_runtime = _AllowedToolRuntime(child_runtime.tool_runtime, allowed_tools)
            object.__setattr__(child_runtime, "tool_runtime", scoped_tool_runtime)
            child_runtime.model_provider.tool_runtime = scoped_tool_runtime
        unsubscribe = _relay_child_tool_events(runtime, child_runtime)
        unsubscribe_model_stream = _relay_child_model_stream(runtime, child_runtime)
        if learning_agent_turn:
            outcome = child_runtime._run_turn(
                session_id=child_session_id,
                prompt=prompt,
                event_type="turn.internal",
                source="learning.sub_agent",
                event_payload={
                    "message": f"learning sub-agent {name}",
                    "summary": f"learning sub-agent {name}",
                    "content": "",
                    "allow_embeddings": "false",
                    "context_mode": "learning_agent",
                    "system_prompt": system_prompt,
                },
                record_input_event=False,
                record_outcome_event=False,
                capture_experience=False,
                apply_growth=True,
            )
        else:
            outcome = child_runtime.explain_next_step(session_id=child_session_id, prompt=prompt)
        execution = outcome.execution
        status = "completed" if execution.outcome not in {"error", "failed"} else "failed"
        summary = _bounded_child_text(execution.summary)
        execution_id = execution.execution_id
        exit_code = 0 if status == "completed" else 1
        result_execution = execution
    except Exception as error:
        status = "failed"
        summary = _child_result_summary(
            {
                "summary": f"{type(error).__name__}: {error}",
                "status": status,
                "traceback": traceback.format_exc(limit=8),
            },
            output="",
            status=status,
        )
        execution_id = None
        exit_code = 1
        result_execution = ExecutionResult(
            execution_id=f"{child_session_id}:sub-agent",
            episode_id=child_session_id,
            outcome="error",
            summary=summary,
            side_effects=("sub_agents", "delegation"),
        )
    finally:
        if unsubscribe is not None:
            unsubscribe()
        if unsubscribe_model_stream is not None:
            unsubscribe_model_stream()
        close = getattr(child_runtime, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass
    result = {
        "name": name,
        "summary": summary,
        "skills": list(skills),
        "session_id": child_session_id,
        "child_episode_id": child_session_id,
        "status": status,
        "exit_code": exit_code,
        "execution_id": execution_id,
        "side_effects": tuple(result_execution.side_effects) if result_execution is not None else (),
    }
    child_metadata = prepared_child.get("child_metadata")
    if isinstance(child_metadata, Mapping):
        for key in ("backend", "baby_id", "baby_state_id", "baby_name", "baby_role", "provider_id", "runtime_id", "runtime_display_name", "runtime_model"):
            value = child_metadata.get(key)
            if value not in (None, ""):
                result[key] = value
    _emit_sub_agent_event(
        runtime,
        prepared_child=prepared_child,
        phase="execution.completed" if status == "completed" else "execution.failed",
        detail=summary,
        run_id=run_id,
        task_index=task_index,
        requested_at=started_at,
        execution=result_execution,
        status=status,
    )
    return result


def _run_prepared_local_cli_baby(
    runtime: Any,
    *,
    prepared_child: Mapping[str, Any],
    name: str,
    prompt: str,
    skills: tuple[str, ...],
    run_id: str | None,
    task_index: int | None,
    started_at: datetime,
) -> Mapping[str, Any]:
    child_session_id = str(prepared_child["session_id"])
    baby = prepared_child.get("baby")
    if not isinstance(baby, Mapping):
        raise RuntimeError("local_cli sub-agent is missing baby elephant binding")
    baby_state = baby["state"]
    runtime_record = baby["runtime"]
    lock = _local_cli_baby_lock(str(baby_state.elephant_id))
    with _LOCAL_CLI_SEMAPHORE:
        with lock:
            result = run_local_agent_cli(
                runtime_record,
                prompt=prompt,
                cwd=_local_cli_cwd(runtime, baby_state),
                model=str(getattr(runtime_record, "default_model", "") or ""),
                timeout_seconds=int(str(prepared_child.get("timeout_seconds") or "1800")),
            )
    status = "completed" if result.status == "completed" else "failed"
    summary = _bounded_child_text(result.summary)
    execution = ExecutionResult(
        execution_id=f"{child_session_id}:local-cli:{runtime_record.runtime_id}",
        episode_id=child_session_id,
        outcome="success" if status == "completed" else "error",
        summary=summary,
        side_effects=("sub_agents", "delegation", "local_agent_cli"),
    )
    payload = {
        "name": name,
        "summary": summary,
        "skills": list(skills),
        "session_id": child_session_id,
        "child_episode_id": child_session_id,
        "status": status,
        "exit_code": result.exit_code,
        "execution_id": execution.execution_id,
        "side_effects": tuple(execution.side_effects),
        "backend": "local_cli",
        "baby_id": str(baby_state.elephant_id),
        "baby_state_id": str(baby_state.state_id),
        "baby_role": str(baby.get("role_title") or ""),
        "provider_id": runtime_record.provider_id,
        "runtime_id": runtime_record.runtime_id,
    }
    _emit_sub_agent_event(
        runtime,
        prepared_child=prepared_child,
        phase="execution.completed" if status == "completed" else "execution.failed",
        detail=summary,
        run_id=run_id,
        task_index=task_index,
        requested_at=started_at,
        execution=execution,
        status=status,
    )
    return payload


def _local_cli_baby_lock(baby_id: str) -> Lock:
    with _LOCAL_CLI_BABY_LOCKS_GUARD:
        lock = _LOCAL_CLI_BABY_LOCKS.get(baby_id)
        if lock is None:
            lock = Lock()
            _LOCAL_CLI_BABY_LOCKS[baby_id] = lock
        return lock


def _local_cli_cwd(runtime: Any, baby_state: Any) -> Path:
    paths = getattr(runtime, "paths", None)
    workspaces_dir = getattr(paths, "workspaces_dir", None)
    if workspaces_dir is not None:
        path = Path(workspaces_dir) / str(getattr(baby_state, "elephant_id", "") or "local-agent")
        path.mkdir(parents=True, exist_ok=True)
        return path
    state_dir = getattr(paths, "state_dir", None)
    if state_dir is not None:
        return Path(state_dir)
    return Path.cwd()


def _create_child_runtime(runtime: Any) -> Any:
    return runtime.__class__.create(
        state_dir=runtime.paths.state_dir,
    )


def _relay_child_tool_events(parent_runtime: Any, child_runtime: Any):
    emitter = getattr(parent_runtime.tool_runtime, "_emit_event", None)
    subscribe = getattr(child_runtime.tool_runtime, "subscribe", None)
    if not callable(emitter) or not callable(subscribe):
        return None

    def _observer(event: Any) -> None:
        emitter(event)

    return subscribe(_observer)


def _relay_child_model_stream(parent_runtime: Any, child_runtime: Any):
    parent_provider = getattr(parent_runtime, "model_provider", None)
    child_provider = getattr(child_runtime, "model_provider", None)
    set_child_observer = getattr(child_provider, "set_stream_observer", None)
    if parent_provider is None or not callable(set_child_observer):
        return None

    previous_child_observer = getattr(child_provider, "_stream_observer", None)

    def _observer(delta: str, **metadata: Any) -> None:
        parent_observer = getattr(parent_provider, "_stream_observer", None)
        for observer in (parent_observer, previous_child_observer):
            if not callable(observer):
                continue
            try:
                observer(delta, **metadata)
            except TypeError:
                observer(delta)

    set_child_observer(_observer)

    def _unsubscribe() -> None:
        set_child_observer(previous_child_observer)

    return _unsubscribe


def _normalize_sub_agent_task(item: Mapping[str, Any]) -> Mapping[str, Any]:
    task = str(item.get("task") or item.get("prompt") or "").strip()
    if not task:
        raise ValueError("sub-agent tasks require 'task'")
    name = item.get("name")
    name_text = None if name is None else str(name).strip() or None
    skills = cron_skill_ids(item.get("skills"))
    allowed_tools = cron_skill_ids(item.get("allowed_tools") or item.get("allowed_tool_ids"))
    system_prompt = str(item.get("system_prompt") or "").strip()
    learning_agent = bool(item.get("learning_agent"))
    child_metadata = item.get("child_metadata") if isinstance(item.get("child_metadata"), Mapping) else {}
    backend = str(item.get("backend") or "native").strip().lower()
    if backend not in {"", "native", "local_cli", "provider"}:
        raise ValueError(f"unsupported sub-agent backend: {backend}")
    return {
        "task": task,
        "name": name_text,
        "skills": skills,
        "allowed_tools": allowed_tools,
        "system_prompt": system_prompt,
        "learning_agent": learning_agent,
        "child_metadata": dict(child_metadata),
        "backend": backend if backend in {"local_cli", "provider"} else "native",
        "baby_id": str(item.get("baby_id") or item.get("babyId") or "").strip(),
        "role": str(item.get("role") or "").strip(),
        "timeout_seconds": str(item.get("timeout_seconds") or item.get("timeoutSeconds") or "1800").strip(),
    }


def _aggregate_sub_agent_status(results: list[Mapping[str, Any] | None]) -> str:
    if any(item is None for item in results):
        return "running"
    if any(str(item.get("status") or "").lower() not in {"completed", "success"} for item in results if item):
        return "failed"
    return "completed"


def _record_async_sub_agent_result(run: _AsyncSubAgentRun, index: int, future: Future) -> None:
    try:
        result = future.result()
    except Exception as error:
        result = {
            "name": f"sub-agent-{index + 1}",
            "summary": f"sub-agent failed:\n{type(error).__name__}: {error}",
            "status": "failed",
            "exit_code": 1,
            "execution_id": None,
        }
    with run.lock:
        run.results[index] = result
        run.status = _aggregate_sub_agent_status(run.results)
        if run.status != "running":
            run.completed_at = datetime.now(timezone.utc)
            executor = run.executor
            run.executor = None
        else:
            executor = None
    if executor is not None:
        executor.shutdown(wait=False)


def _refresh_async_sub_agent_run(run: _AsyncSubAgentRun) -> None:
    for index, future in enumerate(run.futures):
        with run.lock:
            known = run.results[index] is not None
        if known or not future.done():
            continue
        _record_async_sub_agent_result(run, index, future)


def _get_async_sub_agent_run(run_id: str) -> _AsyncSubAgentRun:
    with _ASYNC_SUB_AGENT_RUNS_LOCK:
        run = _ASYNC_SUB_AGENT_RUNS.get(run_id)
    if run is None:
        raise KeyError(f"unknown sub-agent run: {run_id}")
    return run


def _completed_sub_agent_count(run: _AsyncSubAgentRun) -> int:
    with run.lock:
        return sum(1 for item in run.results if item is not None)


def _sub_agent_run_payload(run: _AsyncSubAgentRun) -> Mapping[str, Any]:
    _refresh_async_sub_agent_run(run)
    with run.lock:
        results = list(run.results)
        status = run.status
        completed = sum(1 for item in results if item is not None)
    total = len(results)
    resolved = [item for item in results if item is not None]
    summary_lines = [
        f"sub_agent_run_id: {run.run_id}",
        f"status: {status}",
        f"progress: {completed}/{total}",
    ]
    if status == "running":
        summary_lines.append(f"Use tool.sub_agents action=status run_id={run.run_id} to check progress, or action=join to wait.")
    for index, item in enumerate(resolved):
        summary_lines.append(
            f"{index + 1}. {item.get('name') or 'sub-agent'}: {item.get('summary') or item.get('status') or 'finished'}"
        )
    return {
        "run_id": run.run_id,
        "status": status,
        "summary": "\n".join(summary_lines),
        "results": resolved,
        "max_concurrency": run.max_concurrency,
        "completed_count": completed,
        "total_count": total,
    }


def _emit_sub_agent_event(
    runtime: Any,
    *,
    prepared_child: Mapping[str, Any],
    phase: str,
    detail: str,
    run_id: str | None,
    task_index: int | None,
    requested_at: datetime,
    execution: ExecutionResult | None = None,
    status: str | None = None,
) -> None:
    emitter = getattr(runtime.tool_runtime, "_emit_event", None)
    if not callable(emitter):
        return
    child_session_id = str(prepared_child.get("session_id") or "")
    invocation = ToolInvocation(
        invocation_id=f"{child_session_id}:tool.sub_agents.child:{run_id or 'run'}:{task_index if task_index is not None else 0}",
        tool_id="tool.sub_agents",
        session_id=child_session_id,
        arguments=sub_agent_event_arguments(
            prepared_child,
            phase=phase,
            detail=detail,
            run_id=run_id,
            task_index=task_index,
            status=status,
        ),
        requested_at=requested_at,
        requester="model",
    )
    emitter(
        ToolLifecycleEvent(
            event_id=f"{invocation.invocation_id}:{phase}",
            invocation=invocation,
            phase=phase,
            detail=detail,
            execution=execution,
            occurred_at=datetime.now(timezone.utc),
        )
    )


def _child_output_summary(output: str, *, status: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return f"sub-agent {status} with no output"
    selected = lines[-8:]
    summary = _bounded_child_text("\n".join(selected).strip())
    if status == "failed":
        return f"sub-agent failed:\n{summary}"
    return summary


def _child_result_summary(payload: Mapping[str, Any], *, output: str, status: str) -> str:
    summary = str(payload.get("summary") or "").strip()
    if not summary and output:
        summary = _child_output_summary(output, status=status)
    if not summary:
        summary = f"sub-agent {status} with no summary"
    summary = _bounded_child_text(summary)
    if status == "failed" and not summary.startswith("sub-agent failed"):
        return f"sub-agent failed:\n{summary}"
    return summary


def _bounded_child_text(value: str, *, limit: int = 12000) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}\n[truncated]"


def _compose_sub_agent_prompt(
    runtime: Any,
    *,
    task: str,
    name: str | None,
    skills: tuple[str, ...],
    session_id: str,
) -> str:
    sections = [
        "[SYSTEM: You are running as a bounded Elephant Agent sub-agent.]",
        "Return a concise final result for the parent agent.",
        "Do not call tool.sub_agents, tool.clarify, or tool.message.send.",
        "Use tools only when they materially advance this delegated task.",
        f"Sub-agent name: {name or 'sub-agent'}",
    ]
    skill_sections = _skill_sections(runtime, skills, session_id=session_id)
    if skill_sections:
        sections.extend(["", "Sub-agent skill references:", "\n\n".join(skill_sections)])
    sections.extend(["", f"Delegated task:\n{task}"])
    return "\n".join(sections).strip()


def _skill_sections(runtime: Any, skill_ids: tuple[str, ...], *, session_id: str) -> list[str]:
    sections: list[str] = []
    for skill_id in skill_ids:
        try:
            skill = runtime.inspect_skill(skill_id, session_id=session_id)
        except Exception as error:
            sections.append(f"Skill {skill_id}: unavailable ({error}).")
            continue
        sections.append(
            "\n".join(
                (
                    f"Skill: {skill.display_name} ({skill.skill_id})",
                    f"Summary: {skill.summary}",
                    "Full skill body: not injected automatically.",
                )
            )
        )
    return sections
