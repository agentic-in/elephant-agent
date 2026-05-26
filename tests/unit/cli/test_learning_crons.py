from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any, Mapping

from apps.cli.cli_main_impl import _ensure_nightly_learning_crons


class _CronRuntimeStub:
    def __init__(self, jobs: list[SimpleNamespace]) -> None:
        self.jobs = list(jobs)
        self.removed: list[str] = []

    def list_jobs(self) -> list[SimpleNamespace]:
        return list(self.jobs)

    def remove_job(self, job_id: str) -> SimpleNamespace:
        for index, job in enumerate(self.jobs):
            if job.job_id == job_id:
                self.removed.append(job_id)
                return self.jobs.pop(index)
        raise KeyError(job_id)

    def create_job(self, *, name: str, schedule_text: str, payload: Mapping[str, Any]) -> SimpleNamespace:
        job = SimpleNamespace(
            job_id="cron:new-dream",
            name=name,
            schedule_text=schedule_text,
            action_kind=str(payload.get("action_kind", "prompt")),
            payload=dict(payload),
        )
        self.jobs.append(job)
        return job


class NightlyLearningCronTest(unittest.TestCase):
    def test_single_nightly_cron_removes_legacy_diary_and_creates_dream_bundle(self) -> None:
        diary = SimpleNamespace(
            job_id="cron:diary",
            name="Daily diary",
            action_kind="learning",
            payload={"trigger": "diary", "summary": "daily diary entry for yesterday"},
        )
        runtime = SimpleNamespace(cron_runtime=_CronRuntimeStub([diary]))

        _ensure_nightly_learning_crons(runtime)

        jobs = runtime.cron_runtime.list_jobs()
        self.assertEqual(runtime.cron_runtime.removed, ["cron:diary"])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].name, "Nightly dream")
        self.assertEqual(jobs[0].payload["trigger"], "dream")
        self.assertEqual(jobs[0].payload["metadata"]["features"], "dream,questions,skill_affinity,skill_evolution,diary")


if __name__ == "__main__":
    unittest.main()
