from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

from apps.api.api_runtime_http_dispatch_helpers import _cron_job_record


class CronJobDispatchHelpersTest(unittest.TestCase):
    def test_nightly_dream_jobs_are_marked_as_system_jobs(self) -> None:
        now = datetime.now(timezone.utc)
        job = SimpleNamespace(
            job_id="cron:dream",
            name="Nightly dream",
            schedule_text="0 1 * * *",
            schedule_kind="cron",
            action_kind="learning",
            status="scheduled",
            profile_id=None,
            elephant_id=None,
            payload={
                "trigger": "dream",
                "summary": "nightly Personal Model consolidation",
            },
            created_at=now,
            updated_at=now,
            next_run_at=now,
            last_run_at=None,
            run_count=2,
            last_summary="learning job queued: learning-job:123 (dream)",
        )

        record = _cron_job_record(job)

        self.assertTrue(record["isSystem"])
        self.assertEqual(record["systemKind"], "dream")
        self.assertTrue(record["canRunNow"])
        self.assertTrue(record["canPause"])
        self.assertFalse(record["canDelete"])

    def test_diary_learning_jobs_are_not_system_jobs(self) -> None:
        now = datetime.now(timezone.utc)
        job = SimpleNamespace(
            job_id="cron:diary",
            name="Daily diary",
            schedule_text="0 2 * * *",
            schedule_kind="cron",
            action_kind="learning",
            status="scheduled",
            profile_id=None,
            elephant_id=None,
            payload={"trigger": "diary", "summary": "daily diary entry for yesterday"},
            created_at=now,
            updated_at=now,
            next_run_at=now,
            last_run_at=None,
            run_count=2,
            last_summary="learning job queued: learning-job:123 (diary)",
        )

        record = _cron_job_record(job)

        self.assertFalse(record["isSystem"])
        self.assertIsNone(record["systemKind"])
        self.assertTrue(record["canRunNow"])
        self.assertTrue(record["canPause"])
        self.assertTrue(record["canDelete"])


if __name__ == "__main__":
    unittest.main()
