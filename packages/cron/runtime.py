"""Durable scheduled jobs for Elephant Agent.

The built-in cron runtime keeps scheduling logic package-owned so CLI, gateway,
and future operator surfaces can all share one persistence and evaluation
model.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

try:
    import fcntl
except ModuleNotFoundError:  # pragma: no cover - Windows fallback.
    fcntl = None


class ScheduleParseError(ValueError):
    """Raised when a schedule string cannot be normalized or parsed."""


_SUPPORTED_ACTION_KINDS = frozenset({"prompt", "learning"})


@dataclass(frozen=True, slots=True)
class CronJob:
    job_id: str
    name: str
    schedule_text: str
    schedule_kind: str
    action_kind: str
    payload: Mapping[str, Any]
    profile_id: str | None
    elephant_id: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    run_count: int = 0
    interval_seconds: int | None = None
    cron_expression: str | None = None
    timezone_name: str | None = None
    last_summary: str | None = None


@dataclass(frozen=True, slots=True)
class CronJobExecution:
    job: CronJob
    outcome: str
    summary: str
    recorded_at: datetime


def _now() -> datetime:
    return datetime.now().astimezone()


def normalize_schedule_phrase(value: str) -> str:
    raw = " ".join(value.strip().split())
    lowered = raw.casefold()
    if lowered == "every morning":
        return "0 9 * * *"
    if lowered == "every afternoon":
        return "0 14 * * *"
    if lowered in {"every evening", "every night"}:
        return "0 19 * * *"
    match = re.fullmatch(r"(?:every day|daily) at (\d{1,2})(?::(\d{2}))?\s*(am|pm)?", lowered)
    if match is not None:
        hour = int(match.group(1))
        minute = int(match.group(2) or "0")
        meridiem = match.group(3)
        if meridiem == "pm" and hour < 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
        if hour > 23 or minute > 59:
            raise ScheduleParseError(f"invalid daily time: {value}")
        return f"{minute} {hour} * * *"
    return raw


class CronRuntime:
    def __init__(
        self,
        storage_path: Path,
        *,
        output_dir: Path | None = None,
        lock_path: Path | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.storage_path = storage_path
        self.output_dir = output_dir or storage_path.parent / "output"
        self.lock_path = lock_path or storage_path.parent / "cron.lock"
        self._clock = clock or _now
        self.ensure_layout()

    def ensure_layout(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def list_jobs(
        self,
        *,
        profile_id: str | None = None,
        elephant_id: str | None = None,
        include_inactive: bool = True,
    ) -> tuple[CronJob, ...]:
        jobs = self._load_jobs()
        filtered: list[CronJob] = []
        for job in jobs:
            if profile_id is not None and job.profile_id not in {None, profile_id}:
                continue
            if elephant_id is not None and job.elephant_id not in {None, elephant_id}:
                continue
            if not include_inactive and job.status != "scheduled":
                continue
            filtered.append(job)
        return tuple(
            sorted(
                filtered,
                key=lambda item: ((item.next_run_at or item.updated_at), item.name),
            )
        )

    def inspect_job(self, job_id: str) -> CronJob:
        for job in self._load_jobs():
            if job.job_id == job_id:
                return job
        raise KeyError(job_id)

    def create_job(
        self,
        *,
        name: str,
        schedule_text: str,
        payload: Mapping[str, Any],
        profile_id: str | None = None,
        elephant_id: str | None = None,
        timezone_name: str | None = None,
    ) -> CronJob:
        stored_payload = dict(payload)
        action_kind = str(stored_payload.pop("action_kind", "prompt")).strip() or "prompt"
        if action_kind == "prompt":
            prompt = str(stored_payload.get("prompt") or "").strip()
            if not prompt:
                raise ValueError("cron prompt jobs require a non-empty 'prompt' payload")
            stored_payload["prompt"] = prompt
        elif action_kind == "learning":
            trigger = str(stored_payload.get("trigger") or "").strip()
            if not trigger:
                raise ValueError("cron learning jobs require a non-empty 'trigger' payload")
        now = self._clock()
        normalized_schedule = normalize_schedule_phrase(schedule_text)
        parsed = _parse_schedule(normalized_schedule, now)
        job = CronJob(
            job_id=f"cron:{uuid4().hex[:10]}",
            name=name.strip() or "Elephant Agent job",
            schedule_text=normalized_schedule,
            schedule_kind=parsed["schedule_kind"],
            action_kind=action_kind,
            payload=stored_payload,
            profile_id=profile_id,
            elephant_id=elephant_id,
            status="scheduled",
            created_at=now,
            updated_at=now,
            next_run_at=parsed["next_run_at"],
            interval_seconds=parsed.get("interval_seconds"),
            cron_expression=parsed.get("cron_expression"),
            timezone_name=timezone_name,
        )
        jobs = list(self._load_jobs())
        jobs.append(job)
        self._write_jobs(jobs)
        return job

    def pause_job(self, job_id: str) -> CronJob:
        return self._update_job(job_id, lambda job: replace(job, status="paused", updated_at=self._clock()))

    def resume_job(self, job_id: str) -> CronJob:
        def _resume(job: CronJob) -> CronJob:
            if job.status == "completed":
                raise ValueError("completed jobs cannot be resumed")
            next_run_at = job.next_run_at or _parse_schedule(job.schedule_text, self._clock())["next_run_at"]
            return replace(
                job,
                status="scheduled",
                next_run_at=next_run_at,
                updated_at=self._clock(),
            )

        return self._update_job(job_id, _resume)

    def remove_job(self, job_id: str) -> CronJob:
        jobs = list(self._load_jobs())
        kept: list[CronJob] = []
        removed: CronJob | None = None
        for job in jobs:
            if job.job_id == job_id:
                removed = job
                continue
            kept.append(job)
        if removed is None:
            raise KeyError(job_id)
        self._write_jobs(kept)
        return removed

    def due_jobs(
        self,
        *,
        now: datetime | None = None,
        profile_id: str | None = None,
        elephant_id: str | None = None,
    ) -> tuple[CronJob, ...]:
        current = now or self._clock()
        due: list[CronJob] = []
        for job in self.list_jobs(profile_id=profile_id, elephant_id=elephant_id, include_inactive=False):
            if job.next_run_at is not None and job.next_run_at <= current:
                due.append(job)
        return tuple(due)

    def record_execution(
        self, job_id: str, *, outcome: str, summary: str, now: datetime | None = None
    ) -> CronJobExecution:
        recorded_at = now or self._clock()

        def _advance(job: CronJob) -> CronJob:
            run_count = job.run_count + 1
            if job.schedule_kind == "delay":
                return replace(
                    job,
                    status="completed",
                    run_count=run_count,
                    last_run_at=recorded_at,
                    updated_at=recorded_at,
                    last_summary=summary,
                    next_run_at=None,
                )
            next_run_at = _next_run_for_job(job, recorded_at)
            return replace(
                job,
                status="scheduled" if outcome != "paused" else "paused",
                run_count=run_count,
                last_run_at=recorded_at,
                updated_at=recorded_at,
                last_summary=summary,
                next_run_at=next_run_at,
            )

        updated = self._update_job(job_id, _advance)
        return CronJobExecution(job=updated, outcome=outcome, summary=summary, recorded_at=recorded_at)

    def begin_execution(self, job_id: str, *, now: datetime | None = None) -> CronJobExecution:
        recorded_at = now or self._clock()

        def _advance(job: CronJob) -> CronJob:
            run_count = job.run_count + 1
            if job.schedule_kind == "delay":
                return replace(
                    job,
                    status="completed",
                    run_count=run_count,
                    last_run_at=recorded_at,
                    updated_at=recorded_at,
                    last_summary=f"{job.name} started.",
                    next_run_at=None,
                )
            next_run_at = _next_run_for_job(job, recorded_at)
            return replace(
                job,
                status="scheduled",
                run_count=run_count,
                last_run_at=recorded_at,
                updated_at=recorded_at,
                last_summary=f"{job.name} started.",
                next_run_at=next_run_at,
            )

        updated = self._update_job(job_id, _advance)
        return CronJobExecution(
            job=updated,
            outcome="running",
            summary=f"{updated.name} started.",
            recorded_at=recorded_at,
        )

    def record_execution_result(
        self,
        job_id: str,
        *,
        outcome: str,
        summary: str,
        now: datetime | None = None,
    ) -> CronJobExecution:
        recorded_at = now or self._clock()

        def _finish(job: CronJob) -> CronJob:
            if outcome == "paused":
                status = "paused"
            elif job.schedule_kind == "delay":
                status = "completed"
            else:
                status = "scheduled"
            return replace(
                job,
                status=status,
                last_run_at=recorded_at,
                updated_at=recorded_at,
                last_summary=summary,
            )

        try:
            updated = self._update_job(job_id, _finish)
        except KeyError:
            # The job was paused or removed while its executor was still running
            # (e.g. a cron turn that autonomously called tool.cron.manage remove).
            # Don't crash the scheduler loop — synthesize a detached execution
            # record so the caller can log it and continue to the next job.
            return CronJobExecution(
                job=CronJob(
                    job_id=job_id,
                    name=job_id,
                    schedule_text="",
                    schedule_kind="vanished",
                    action_kind="prompt",
                    payload={},
                    profile_id=None,
                    elephant_id=None,
                    status="removed",
                    created_at=recorded_at,
                    updated_at=recorded_at,
                    last_run_at=recorded_at,
                    last_summary=summary,
                ),
                outcome="vanished",
                summary=summary,
                recorded_at=recorded_at,
            )
        return CronJobExecution(job=updated, outcome=outcome, summary=summary, recorded_at=recorded_at)

    def run_due(
        self,
        executor: Callable[[CronJob], tuple[str, str]],
        *,
        profile_id: str | None = None,
        elephant_id: str | None = None,
        now: datetime | None = None,
    ) -> tuple[CronJobExecution, ...]:
        executions: list[CronJobExecution] = []
        current = now or self._clock()
        with self._execution_lock() as acquired:
            if not acquired:
                return ()
            for job in self.due_jobs(now=current, profile_id=profile_id, elephant_id=elephant_id):
                started = self.begin_execution(job.job_id, now=current)
                try:
                    outcome, summary = executor(started.job)
                except Exception as error:  # pragma: no cover - executor wrappers usually catch.
                    outcome, summary = "failed", f"{started.job.name} failed: {error}"
                executions.append(
                    self.record_execution_result(
                        started.job.job_id,
                        outcome=outcome,
                        summary=summary,
                        now=current,
                    )
                )
        return tuple(executions)

    @contextmanager
    def _execution_lock(self):
        self.ensure_layout()
        stream = self.lock_path.open("a+", encoding="utf-8")
        acquired = False
        try:
            if fcntl is not None:
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except OSError:
                    yield False
                    return
            else:
                acquired = True
            yield True
        finally:
            if acquired and fcntl is not None:
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
            stream.close()

    def _update_job(self, job_id: str, updater: Callable[[CronJob], CronJob]) -> CronJob:
        jobs = list(self._load_jobs())
        updated_job: CronJob | None = None
        for index, job in enumerate(jobs):
            if job.job_id != job_id:
                continue
            updated_job = updater(job)
            jobs[index] = updated_job
            break
        if updated_job is None:
            raise KeyError(job_id)
        self._write_jobs(jobs)
        return updated_job

    def _load_jobs(self) -> tuple[CronJob, ...]:
        if not self.storage_path.exists():
            return ()
        payload = json.loads(self.storage_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            return ()
        jobs: list[CronJob] = []
        for item in payload:
            if not isinstance(item, Mapping):
                continue
            jobs.append(_job_from_payload(item))
        return tuple(jobs)

    def _write_jobs(self, jobs: list[CronJob]) -> None:
        self.ensure_layout()
        temp_path = self.storage_path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps([_job_payload(job) for job in jobs], indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp_path.replace(self.storage_path)


def _job_payload(job: CronJob) -> dict[str, Any]:
    payload = asdict(job)
    for field_name in ("created_at", "updated_at", "next_run_at", "last_run_at"):
        value = payload[field_name]
        payload[field_name] = value.isoformat() if value is not None else None
    return payload


def _job_from_payload(payload: Mapping[str, Any]) -> CronJob:
    return CronJob(
        job_id=str(payload["job_id"]),
        name=str(payload["name"]),
        schedule_text=str(payload["schedule_text"]),
        schedule_kind=str(payload["schedule_kind"]),
        action_kind=str(payload["action_kind"]),
        payload=dict(payload.get("payload", {})),
        profile_id=str(payload["profile_id"]) if payload.get("profile_id") is not None else None,
        elephant_id=str(payload["elephant_id"]) if payload.get("elephant_id") is not None else None,
        status=str(payload.get("status", "scheduled")),
        created_at=datetime.fromisoformat(str(payload["created_at"])),
        updated_at=datetime.fromisoformat(str(payload["updated_at"])),
        next_run_at=(
            datetime.fromisoformat(str(payload["next_run_at"])) if payload.get("next_run_at") is not None else None
        ),
        last_run_at=(
            datetime.fromisoformat(str(payload["last_run_at"])) if payload.get("last_run_at") is not None else None
        ),
        run_count=int(payload.get("run_count", 0)),
        interval_seconds=int(payload["interval_seconds"]) if payload.get("interval_seconds") is not None else None,
        cron_expression=str(payload["cron_expression"]) if payload.get("cron_expression") is not None else None,
        timezone_name=str(payload["timezone_name"]) if payload.get("timezone_name") is not None else None,
        last_summary=str(payload["last_summary"]) if payload.get("last_summary") is not None else None,
    )


def _parse_schedule(value: str, now: datetime) -> dict[str, Any]:
    normalized = normalize_schedule_phrase(value)
    delay_match = re.fullmatch(r"(\d+)([mhd])", normalized.casefold())
    if delay_match is not None:
        seconds = _duration_seconds(int(delay_match.group(1)), delay_match.group(2))
        return {
            "schedule_kind": "delay",
            "next_run_at": now + timedelta(seconds=seconds),
        }
    interval_match = re.fullmatch(r"every\s+(\d+)([mhd])", normalized.casefold())
    if interval_match is not None:
        seconds = _duration_seconds(int(interval_match.group(1)), interval_match.group(2))
        return {
            "schedule_kind": "interval",
            "next_run_at": now + timedelta(seconds=seconds),
            "interval_seconds": seconds,
        }
    if re.fullmatch(r"[^\s]+\s+[^\s]+\s+[^\s]+\s+[^\s]+\s+[^\s]+", normalized):
        next_run = _next_cron_datetime(normalized, now)
        return {
            "schedule_kind": "cron",
            "next_run_at": next_run,
            "cron_expression": normalized,
        }
    try:
        at = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ScheduleParseError(f"unsupported schedule format: {value}") from exc
    if at.tzinfo is None:
        at = at.replace(tzinfo=now.tzinfo)
    return {
        "schedule_kind": "delay",
        "next_run_at": at,
    }


def _next_run_for_job(job: CronJob, after: datetime) -> datetime | None:
    if job.schedule_kind == "interval":
        if job.interval_seconds is None:
            raise ScheduleParseError(f"interval job missing interval seconds: {job.job_id}")
        return after + timedelta(seconds=job.interval_seconds)
    if job.schedule_kind == "cron":
        if job.cron_expression is None:
            raise ScheduleParseError(f"cron job missing expression: {job.job_id}")
        return _next_cron_datetime(job.cron_expression, after)
    return None


def _duration_seconds(value: int, unit: str) -> int:
    if unit == "m":
        return value * 60
    if unit == "h":
        return value * 60 * 60
    if unit == "d":
        return value * 60 * 60 * 24
    raise ScheduleParseError(f"unsupported duration unit: {unit}")


def _next_cron_datetime(expression: str, after: datetime) -> datetime:
    parts = expression.split()
    if len(parts) != 5:
        raise ScheduleParseError(f"cron expression must have 5 fields: {expression}")
    minute_values = _expand_cron_field(parts[0], 0, 59)
    hour_values = _expand_cron_field(parts[1], 0, 23)
    day_values = _expand_cron_field(parts[2], 1, 31)
    month_values = _expand_cron_field(parts[3], 1, 12)
    weekday_values = _expand_cron_field(parts[4], 0, 6)
    candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(0, 366 * 24 * 60):
        cron_weekday = (candidate.weekday() + 1) % 7
        if (
            candidate.minute in minute_values
            and candidate.hour in hour_values
            and candidate.day in day_values
            and candidate.month in month_values
            and cron_weekday in weekday_values
        ):
            return candidate
        candidate += timedelta(minutes=1)
    raise ScheduleParseError(f"could not compute next run for cron expression: {expression}")


def _expand_cron_field(field: str, minimum: int, maximum: int) -> set[int]:
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        if part == "*":
            values.update(range(minimum, maximum + 1))
            continue
        step = 1
        if "/" in part:
            base, step_text = part.split("/", 1)
            step = int(step_text)
        else:
            base = part
        if base == "*":
            start = minimum
            end = maximum
        elif "-" in base:
            start_text, end_text = base.split("-", 1)
            start = int(start_text)
            end = int(end_text)
        else:
            start = int(base)
            end = int(base)
        if start < minimum or end > maximum or start > end:
            raise ScheduleParseError(f"invalid cron field '{field}'")
        values.update(range(start, end + 1, step))
    if not values:
        raise ScheduleParseError(f"invalid cron field '{field}'")
    return values
