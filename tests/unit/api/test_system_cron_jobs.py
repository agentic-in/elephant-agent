from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from apps.api.api_runtime_console import _cron_jobs, _dream_system_job


class _CronRuntime:
    def list_jobs(self) -> tuple[object, ...]:
        return ()


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
