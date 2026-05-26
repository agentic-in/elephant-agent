from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from apps.api.api_runtime_impl import _ensure_system_cron_jobs
from apps.api.api_runtime_console import _cron_jobs, _dream_system_job


class _CronRuntime:
    def __init__(self, jobs: tuple[object, ...] = ()) -> None:
        self.jobs = list(jobs)
        self.created: list[dict[str, object]] = []

    def list_jobs(self) -> tuple[object, ...]:
        return tuple(self.jobs)

    def create_job(
        self,
        *,
        name: str,
        schedule_text: str,
        payload: dict[str, object],
    ) -> object:
        job = SimpleNamespace(
            job_id="cron:new-dream",
            name=name,
            schedule_text=schedule_text,
            action_kind=str(payload.get("action_kind") or "prompt"),
            payload=dict(payload),
        )
        self.jobs.append(job)
        self.created.append(
            {"name": name, "schedule_text": schedule_text, "payload": dict(payload)}
        )
        return job

    def remove_job(self, job_id: str) -> object:
        for index, job in enumerate(self.jobs):
            if getattr(job, "job_id", "") == job_id:
                return self.jobs.pop(index)
        raise KeyError(job_id)


class _Repository:
    database_path = SimpleNamespace(parent="/tmp/elephant-test")

    def list_learning_jobs(self, *, limit: int | None = None) -> tuple[object, ...]:
        return (
            SimpleNamespace(
                trigger="dream",
                metadata={"features": "dream"},
                progress_detail="dream completed",
                summary="reflect job",
                finished_at=datetime(2026, 5, 21, 1, 2, tzinfo=timezone.utc),
                started_at=None,
                created_at=None,
            ),
        )


def test_dream_system_job_is_visible_in_cron_projection() -> None:
    app = SimpleNamespace(cron_runtime=_CronRuntime(), repository=_Repository())

    rows = _cron_jobs(app)

    assert rows[0]["jobId"] == "system:dream"
    assert rows[0]["systemKind"] == "dream"
    assert rows[0]["canRunNow"] is True
    assert rows[0]["canDelete"] is False


def test_dream_system_job_summarizes_recent_learning_run() -> None:
    app = SimpleNamespace(repository=_Repository())

    row = _dream_system_job(app)

    assert row is not None
    assert row["runCount"] == 1
    assert row["lastSummary"] == "dream completed"
    assert row["lastRunAt"] == "2026-05-21T01:02:00+00:00"


def test_api_startup_self_heals_missing_dream_cron() -> None:
    cron_runtime = _CronRuntime()

    _ensure_system_cron_jobs(cron_runtime)  # type: ignore[arg-type]

    jobs = cron_runtime.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].name == "Nightly dream"
    assert jobs[0].payload["trigger"] == "dream"
    assert jobs[0].payload["metadata"]["features"] == "dream,questions,skill_affinity,skill_evolution,diary"
