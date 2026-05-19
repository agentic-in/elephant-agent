from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from packages.cron import CronRuntime, normalize_schedule_phrase


class CronRuntimeTest(unittest.TestCase):
    def _runtime(self, *, now: datetime | None = None) -> tuple[CronRuntime, Path]:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        root = Path(tempdir.name)
        storage_path = root / "cron" / "jobs.json"
        clock_now = now or datetime(2026, 4, 12, 9, 0, tzinfo=timezone.utc)
        runtime = CronRuntime(storage_path, clock=lambda: clock_now)
        return runtime, storage_path

    def test_normalize_schedule_phrase_handles_common_daily_aliases(self) -> None:
        self.assertEqual(normalize_schedule_phrase("every morning"), "0 9 * * *")
        self.assertEqual(normalize_schedule_phrase("daily at 7pm"), "0 19 * * *")

    def test_create_and_pause_resume_remove_job(self) -> None:
        runtime, storage_path = self._runtime()

        created = runtime.create_job(
            name="Morning hello",
            schedule_text="every morning",
            payload={"prompt": "say good morning"},
            profile_id="elephant:atlas",
            elephant_id="atlas",
        )
        paused = runtime.pause_job(created.job_id)
        resumed = runtime.resume_job(created.job_id)
        removed = runtime.remove_job(created.job_id)

        self.assertEqual(created.action_kind, "prompt")
        self.assertEqual(paused.status, "paused")
        self.assertEqual(resumed.status, "scheduled")
        self.assertEqual(removed.job_id, created.job_id)
        self.assertTrue(storage_path.exists())
        self.assertEqual(storage_path.name, "jobs.json")
        self.assertTrue((storage_path.parent / "output").is_dir())
        self.assertEqual(runtime.list_jobs(), ())

    def test_due_interval_job_executes_and_reschedules(self) -> None:
        base = datetime(2026, 4, 12, 9, 0, tzinfo=timezone.utc)
        runtime, _ = self._runtime(now=base)
        job = runtime.create_job(
            name="Web check",
            schedule_text="every 2h",
            payload={"prompt": "check agentic ai news"},
            profile_id="elephant:atlas",
            elephant_id="atlas",
        )

        due = runtime.due_jobs(
            now=base + timedelta(hours=2, minutes=1),
            profile_id="elephant:atlas",
            elephant_id="atlas",
        )
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0].job_id, job.job_id)

        executions = runtime.run_due(
            lambda current: ("success", f"ran {current.name}"),
            now=base + timedelta(hours=2, minutes=1),
            profile_id="elephant:atlas",
            elephant_id="atlas",
        )

        self.assertEqual(len(executions), 1)
        self.assertTrue(runtime.lock_path.exists())
        self.assertEqual(executions[0].summary, "ran Web check")
        updated = runtime.inspect_job(job.job_id)
        self.assertEqual(updated.run_count, 1)
        self.assertEqual(updated.status, "scheduled")
        self.assertIsNotNone(updated.next_run_at)

    def test_create_job_requires_non_empty_prompt_payload(self) -> None:
        runtime, _ = self._runtime()

        with self.assertRaisesRegex(ValueError, "non-empty 'prompt' payload"):
            runtime.create_job(
                name="Broken job",
                schedule_text="every morning",
                payload={},
            )

    def test_due_job_advances_before_executor_runs(self) -> None:
        base = datetime(2026, 4, 12, 9, 0, tzinfo=timezone.utc)
        runtime, _ = self._runtime(now=base)
        job = runtime.create_job(
            name="Long scan",
            schedule_text="every 1h",
            payload={"prompt": "scan"},
        )

        def executor(current):
            advanced = runtime.inspect_job(current.job_id)
            self.assertEqual(advanced.run_count, 1)
            self.assertGreater(advanced.next_run_at, base + timedelta(hours=1, minutes=1))
            return ("success", "finished")

        runtime.run_due(executor, now=base + timedelta(hours=1, minutes=1))

        updated = runtime.inspect_job(job.job_id)
        self.assertEqual(updated.run_count, 1)
        self.assertEqual(updated.last_summary, "finished")

    def test_profile_scoped_due_jobs_include_global_jobs(self) -> None:
        base = datetime(2026, 4, 12, 9, 0, tzinfo=timezone.utc)
        runtime, _ = self._runtime(now=base)
        job = runtime.create_job(
            name="Dashboard job",
            schedule_text="1h",
            payload={"prompt": "scan"},
        )

        due = runtime.due_jobs(
            now=base + timedelta(hours=1, minutes=1),
            profile_id="elephant:atlas",
            elephant_id="atlas",
        )

        self.assertEqual(tuple(item.job_id for item in due), (job.job_id,))

    def test_run_due_tolerates_executor_removing_job(self) -> None:
        """Regression test for `KeyError: 'cron:...'` crash.

        The cron LLM agent has access to `tool.cron.manage` which exposes
        ``pause/remove``. If an executor (the LLM) removes the very job it is
        currently running, `record_execution_result` used to raise KeyError and
        crash the scheduler loop. The runtime now absorbs the vanished-job case
        so one misbehaving turn cannot take down the whole scheduler.
        """
        base = datetime(2026, 4, 12, 9, 0, tzinfo=timezone.utc)
        runtime, _ = self._runtime(now=base)
        job = runtime.create_job(
            name="Self-deleting job",
            schedule_text="every 1h",
            payload={"prompt": "do"},
        )

        def executor(current):
            # Simulate the LLM calling tool.cron.manage remove on itself mid-turn.
            runtime.remove_job(current.job_id)
            return ("success", "did a thing then removed itself")

        executions = runtime.run_due(
            executor,
            now=base + timedelta(hours=1, minutes=1),
        )

        self.assertEqual(len(executions), 1)
        self.assertEqual(executions[0].outcome, "vanished")
        self.assertEqual(executions[0].summary, "did a thing then removed itself")
        # Job really is gone — the loop did not resurrect it.
        self.assertEqual(runtime.list_jobs(), ())
