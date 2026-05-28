from __future__ import annotations

from datetime import UTC, date, datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import warnings
from uuid import uuid4

from apps.cli.runtime import CliRuntime
from packages.contracts.runtime import LearningJob

LEARNING_JOB_TYPE = "episode_boundary_learning"
DEFAULT_WORKER_IDLE_SECONDS = 20.0
_WORKER_RECORD_NAME = "learning-worker.runtime.json"
_WORKER_LOG_NAME = "learning-worker.log"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _runtime_id() -> str:
    return "learning-worker"


def learning_worker_record_path(state_dir: Path) -> Path:
    return state_dir / _WORKER_RECORD_NAME


def learning_worker_log_path(state_dir: Path) -> Path:
    return state_dir / _WORKER_LOG_NAME


def load_learning_worker_record(state_dir: Path) -> dict[str, object] | None:
    path = learning_worker_record_path(state_dir)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _pid_active(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def learning_worker_is_running(state_dir: Path) -> bool:
    record = load_learning_worker_record(state_dir)
    if record is None:
        return False
    try:
        pid = int(record.get("pid") or 0)
    except (TypeError, ValueError):
        return False
    return _pid_active(pid)


def _write_learning_worker_record(
    state_dir: Path,
    *,
    pid: int | None,
    status: str,
    command: list[str] | None = None,
    active_job_id: str | None = None,
    current_stage: str | None = None,
    started_at: str | None = None,
    stopped_at: str | None = None,
    last_exit_code: int | None = None,
) -> dict[str, object]:
    record_path = learning_worker_record_path(state_dir)
    log_path = learning_worker_log_path(state_dir)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_learning_worker_record(state_dir) or {}
    payload: dict[str, object] = {
        "runtime_id": _runtime_id(),
        "status": status,
        "pid": pid,
        "pid_active": _pid_active(pid),
        "pid_path": None,
        "record_path": str(record_path),
        "log_path": str(log_path),
        "command": command or existing.get("command") or [],
        "state_dir": str(state_dir),
        "active_job_id": active_job_id or None,
        "current_stage": current_stage or "",
        "started_at": started_at or existing.get("started_at") or _utc_now().isoformat(),
        "stopped_at": stopped_at,
        "last_exit_code": last_exit_code,
        "updated_at": _utc_now().isoformat(),
    }
    record_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def ensure_learning_worker_running(
    *,
    state_dir: Path,
    idle_seconds: float = DEFAULT_WORKER_IDLE_SECONDS,
    python_executable: str | None = None,
) -> bool:
    if learning_worker_is_running(state_dir):
        return False
    command = [
        python_executable or sys.executable,
        "-m",
        "apps.learning_worker_command",
        "--state-dir",
        str(state_dir),
        "--idle-seconds",
        str(idle_seconds),
    ]
    repo_root = Path(__file__).resolve().parents[1]
    log_path = learning_worker_log_path(state_dir)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab") as log_stream:
        process = subprocess.Popen(
            command,
            cwd=str(repo_root),
            stdin=subprocess.DEVNULL,
            stdout=log_stream,
            stderr=log_stream,
            start_new_session=True,
        )
    worker_pid = process.pid
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            category=ResourceWarning,
            message=r"subprocess \d+ is still running",
        )
        del process
    _write_learning_worker_record(
        state_dir,
        pid=worker_pid,
        status="running",
        command=command,
        started_at=_utc_now().isoformat(),
    )
    return True


def stop_learning_worker(*, state_dir: Path, reason: str = "operator requested stop") -> dict[str, object]:
    record = load_learning_worker_record(state_dir) or {}
    pid = None
    try:
        pid = int(record.get("pid") or 0)
    except (TypeError, ValueError):
        pid = None
    active_job_id = str(record.get("active_job_id") or "").strip()
    if active_job_id:
        runtime = CliRuntime.create(state_dir=state_dir)
        mark_learning_job_terminal_failure(
            runtime,
            job_id=active_job_id,
            worker_id="learning-worker.kill",
            error=reason,
        )
    stopped = False
    if pid and _pid_active(pid):
        try:
            os.kill(pid, signal.SIGTERM)
            stopped = True
        except OSError:
            stopped = False
    payload = _write_learning_worker_record(
        state_dir,
        pid=None,
        status="stopped",
        active_job_id=None,
        current_stage=reason,
        stopped_at=_utc_now().isoformat(),
        last_exit_code=-15 if stopped else record.get("last_exit_code") if record else None,
    )
    return {**payload, "stopped_pid": pid or None, "signal_sent": stopped}


def mark_learning_job_terminal_failure(runtime: CliRuntime, *, job_id: str, worker_id: str, error: str) -> None:
    failed_at = _utc_now().isoformat()
    detail = str(error or "learning worker failed").strip()
    with runtime.repository.connection() as connection:
        connection.execute(
            """
            UPDATE learning_jobs
            SET status = 'failed',
                progress_stage = 'failed',
                progress_detail = ?,
                available_at = ?,
                finished_at = ?,
                worker_id = ?,
                last_error = ?
            WHERE job_id = ? AND status = 'running'
            """,
            (detail, failed_at, failed_at, worker_id, detail, job_id),
        )
        connection.commit()


def _complete_without_learning(runtime: CliRuntime, job: LearningJob, *, worker_id: str, detail: str) -> None:
    runtime.repository.update_learning_job_progress(
        job.job_id,
        worker_id=worker_id,
        progress_stage="skipped",
        progress_detail=detail,
    )
    runtime.repository.complete_learning_job(
        job.job_id,
        worker_id=worker_id,
        progress_detail=detail,
    )


def close_finished_learning_child_episode(runtime: CliRuntime, job: LearningJob, *, child_episode_id: str) -> bool:
    """Close the child episode created by the learning agent. Records are kept for dashboard history."""
    child_id = str(child_episode_id or "").strip()
    if not child_id or child_id == job.episode_id:
        return False
    child = runtime.repository.load_episode(child_id)
    if child is None:
        return False
    metadata = dict(getattr(child, "metadata", {}) or {})
    if metadata.get("parent_episode_id") != job.episode_id:
        return False
    if child.personal_model_id != job.personal_model_id or child.state_id != job.state_id:
        return False
    # Close by updating status via upsert
    from dataclasses import replace as _replace
    closed = _replace(child, status="closed")
    runtime.repository.upsert_episode(closed)
    return True


def _enqueue_onboarding_letter_after_init(runtime: CliRuntime, job: LearningJob) -> None:
    if str(job.trigger or "").strip().lower() not in {"init", "init_profile"}:
        return
    try:
        entries = runtime.repository.list_diary_entries(personal_model_id=job.personal_model_id, limit=30)
    except Exception:
        entries = ()
    for entry in entries:
        metadata = dict(getattr(entry, "metadata", {}) or {})
        if metadata.get("kind") == "onboarding_letter" or metadata.get("source") == "onboarding_letter":
            return
    try:
        existing_jobs = runtime.repository.list_learning_jobs(
            personal_model_id=job.personal_model_id,
            episode_id=job.episode_id,
            limit=30,
        )
    except Exception:
        existing_jobs = ()
    for existing in existing_jobs:
        if str(getattr(existing, "trigger", "") or "").strip().lower() == "onboarding_letter":
            return
    try:
        runtime.repository.enqueue_learning_job(
            job_type=LEARNING_JOB_TYPE,
            trigger="onboarding_letter",
            personal_model_id=job.personal_model_id,
            state_id=job.state_id,
            episode_id=job.episode_id,
            loop_id=None,
            summary="first onboarding letter",
            metadata={
                "source": "onboarding_letter",
                "letter_kind": "onboarding_letter",
                "target_date": date.today().isoformat(),
                "parent_learning_job_id": job.job_id,
            },
            force_new=True,
        )
    except Exception:
        return


def _enqueue_onboarding_paths_after_init(runtime: CliRuntime, job: LearningJob) -> None:
    if str(job.trigger or "").strip().lower() not in {"init", "init_profile"}:
        return
    try:
        existing_paths = runtime.repository.list_paths(personal_model_id=job.personal_model_id, limit=5)
    except Exception:
        existing_paths = ()
    if existing_paths:
        return
    try:
        existing_jobs = runtime.repository.list_learning_jobs(
            personal_model_id=job.personal_model_id,
            episode_id=job.episode_id,
            limit=30,
        )
    except Exception:
        existing_jobs = ()
    for existing in existing_jobs:
        if str(getattr(existing, "trigger", "") or "").strip().lower() == "onboarding_paths":
            return
    try:
        runtime.repository.enqueue_learning_job(
            job_type=LEARNING_JOB_TYPE,
            trigger="onboarding_paths",
            personal_model_id=job.personal_model_id,
            state_id=job.state_id,
            episode_id=job.episode_id,
            loop_id=None,
            summary="first Path planning",
            metadata={
                "source": "onboarding_paths",
                "parent_learning_job_id": job.job_id,
            },
            force_new=True,
        )
    except Exception:
        return


def run_background_learning_agent(runtime: CliRuntime, job: LearningJob):
    """Run the current background learning agent implementation.

    `apps.learning_agents` remains a compatibility import path, but the worker
    runtime owns the callable used by learning jobs.
    """
    from packages.reflect.runner import run_reflect_agent

    return run_reflect_agent(runtime, job)


def run_learning_job(runtime: CliRuntime, job: LearningJob, *, worker_id: str) -> None:
    repository = runtime.repository
    episode = repository.load_episode(job.episode_id)
    state = repository.load_state(job.state_id)
    if episode is None or state is None:
        _complete_without_learning(
            runtime,
            job,
            worker_id=worker_id,
            detail="episode or state is no longer available",
        )
        return
    repository.update_learning_job_progress(
        job.job_id,
        worker_id=worker_id,
        progress_stage="agent_starting",
        progress_detail="starting background learning agent",
    )
    result = run_background_learning_agent(runtime, job)
    if result.child_episode_id:
        close_finished_learning_child_episode(runtime, job, child_episode_id=result.child_episode_id)
    repository.complete_learning_job(
        job.job_id,
        worker_id=worker_id,
        progress_detail=f"{result.status}: {result.summary} (result={result.result_source_id})",
    )
    _enqueue_onboarding_letter_after_init(runtime, job)
    _enqueue_onboarding_paths_after_init(runtime, job)


def run_learning_worker(
    *,
    state_dir: Path,
    idle_seconds: float = DEFAULT_WORKER_IDLE_SECONDS,
    once: bool = False,
) -> int:
    runtime = CliRuntime.create(state_dir=state_dir)
    worker_id = f"learning-worker:{os.getpid()}:{uuid4().hex[:8]}"
    record_command = [
        sys.executable,
        "-m",
        "apps.learning_worker_command",
        "--state-dir",
        str(state_dir),
        "--idle-seconds",
        str(idle_seconds),
    ]
    if once:
        record_command.append("--once")
    started_at = _utc_now().isoformat()
    _write_learning_worker_record(
        state_dir,
        pid=os.getpid(),
        status="running",
        command=record_command,
        started_at=started_at,
    )
    last_activity = time.monotonic()
    try:
        while True:
            job = runtime.repository.claim_learning_job(worker_id=worker_id)
            if job is None:
                if once:
                    break
                if time.monotonic() - last_activity >= max(1.0, idle_seconds):
                    break
                _write_learning_worker_record(
                    state_dir,
                    pid=os.getpid(),
                    status="idle",
                    command=record_command,
                    started_at=started_at,
                )
                time.sleep(0.5)
                continue
            last_activity = time.monotonic()
            _write_learning_worker_record(
                state_dir,
                pid=os.getpid(),
                status="running",
                command=record_command,
                active_job_id=job.job_id,
                current_stage=job.progress_stage,
                started_at=started_at,
            )
            try:
                run_learning_job(runtime, job, worker_id=worker_id)
            except Exception as error:
                message = str(error).strip() or error.__class__.__name__
                runtime.repository.fail_learning_job(
                    job.job_id,
                    worker_id=worker_id,
                    error=message,
                    retry_delay_seconds=min(60, max(5, job.attempt_count * 5)),
                )
            finally:
                _write_learning_worker_record(
                    state_dir,
                    pid=os.getpid(),
                    status="running",
                    command=record_command,
                    started_at=started_at,
                )
            if once:
                break
        return 0
    finally:
        _write_learning_worker_record(
            state_dir,
            pid=None,
            status="stopped",
            command=record_command,
            started_at=started_at,
            stopped_at=_utc_now().isoformat(),
            last_exit_code=0,
        )
