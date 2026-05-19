from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from packages.contracts.layers import Episode
from packages.storage import RuntimeStorageRepository


class StorageLearningJobsTest(unittest.TestCase):
    def test_learning_job_lifecycle_supports_queue_claim_retry_and_complete(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()
            model = repository.ensure_default_personal_model()
            state = repository.create_state(
                personal_model_id=model.personal_model_id,
                elephant_name="Atlas",
                elephant_id="atlas",
                state_id="state:atlas",
            )
            episode = Episode(
                episode_id="episode:atlas",
                state_id=state.state_id,
                personal_model_id=model.personal_model_id,
                entry_surface="cli",
                status="closed",
                started_at=datetime(2026, 4, 28, 10, tzinfo=UTC),
                ended_at=datetime(2026, 4, 28, 10, 5, tzinfo=UTC),
                exit_summary="session boundary",
                metadata={"closed_reason": "clear"},
            )
            repository.upsert_episode(episode)

            queued = repository.enqueue_learning_job(
                job_type="episode_boundary_learning",
                trigger="clear",
                personal_model_id=model.personal_model_id,
                state_id=state.state_id,
                episode_id=episode.episode_id,
                summary="fresh loop requested",
                metadata={"source": "test"},
            )

            self.assertEqual(queued.status, "queued")
            self.assertEqual(queued.progress_stage, "queued")
            self.assertEqual(len(repository.list_learning_jobs(state_id=state.state_id)), 1)

            claimed = repository.claim_learning_job(worker_id="worker-a")
            self.assertIsNotNone(claimed)
            assert claimed is not None
            self.assertEqual(claimed.status, "running")
            self.assertEqual(claimed.attempt_count, 1)

            progress = repository.update_learning_job_progress(
                claimed.job_id,
                worker_id="worker-a",
                progress_stage="reflecting",
                progress_detail="reflection window",
            )
            self.assertEqual(progress.progress_stage, "reflecting")
            result_written = repository.write_learning_job_result(
                claimed.job_id,
                {"status": "partial", "summary": "stored on job"},
                worker_id="worker-a",
            )
            self.assertEqual(result_written.result_json["status"], "partial")
            self.assertEqual(result_written.progress_stage, "result_written")

            retry = repository.fail_learning_job(
                claimed.job_id,
                worker_id="worker-a",
                error="temporary model outage",
                retry_delay_seconds=5,
            )
            self.assertEqual(retry.status, "queued")
            self.assertEqual(retry.progress_stage, "retrying")
            self.assertEqual(retry.last_error, "temporary model outage")

            reclaimed = repository.claim_learning_job(
                worker_id="worker-b",
                now=retry.available_at + timedelta(seconds=1) if retry.available_at is not None else None,
            )
            self.assertIsNotNone(reclaimed)
            assert reclaimed is not None
            self.assertEqual(reclaimed.attempt_count, 2)

            completed = repository.complete_learning_job(
                reclaimed.job_id,
                worker_id="worker-b",
                progress_detail="background learning completed",
            )
            self.assertEqual(completed.status, "completed")
            self.assertEqual(completed.progress_stage, "completed")

    def test_learning_job_deduplicates_per_episode_boundary_job_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()
            model = repository.ensure_default_personal_model()
            state = repository.create_state(
                personal_model_id=model.personal_model_id,
                elephant_name="Atlas",
                elephant_id="atlas",
                state_id="state:atlas",
            )
            episode = Episode(
                episode_id="episode:atlas",
                state_id=state.state_id,
                personal_model_id=model.personal_model_id,
                entry_surface="cli",
                status="closed",
                started_at=datetime(2026, 4, 28, 10, tzinfo=UTC),
                ended_at=datetime(2026, 4, 28, 10, 5, tzinfo=UTC),
                exit_summary="session boundary",
                metadata={},
            )
            repository.upsert_episode(episode)

            first = repository.enqueue_learning_job(
                job_type="episode_boundary_learning",
                trigger="clear",
                personal_model_id=model.personal_model_id,
                state_id=state.state_id,
                episode_id=episode.episode_id,
            )
            second = repository.enqueue_learning_job(
                job_type="episode_boundary_learning",
                trigger="exit",
                personal_model_id=model.personal_model_id,
                state_id=state.state_id,
                episode_id=episode.episode_id,
            )

            self.assertEqual(first.job_id, second.job_id)
            self.assertEqual(len(repository.list_learning_jobs(state_id=state.state_id)), 1)

    def test_learning_job_force_new_allows_manual_rerun_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()
            model = repository.ensure_default_personal_model()
            state = repository.create_state(
                personal_model_id=model.personal_model_id,
                elephant_name="Atlas",
                elephant_id="atlas",
                state_id="state:atlas",
            )
            episode = Episode(
                episode_id="episode:atlas",
                state_id=state.state_id,
                personal_model_id=model.personal_model_id,
                entry_surface="cli",
                status="closed",
                started_at=datetime(2026, 4, 28, 10, tzinfo=UTC),
                ended_at=datetime(2026, 4, 28, 10, 5, tzinfo=UTC),
                exit_summary="session boundary",
                metadata={},
            )
            repository.upsert_episode(episode)

            first = repository.enqueue_learning_job(
                job_type="episode_boundary_learning",
                trigger="episode_close",
                personal_model_id=model.personal_model_id,
                state_id=state.state_id,
                episode_id=episode.episode_id,
            )
            manual = repository.enqueue_learning_job(
                job_type="episode_boundary_learning",
                trigger="manual",
                personal_model_id=model.personal_model_id,
                state_id=state.state_id,
                episode_id=episode.episode_id,
                force_new=True,
            )

            self.assertNotEqual(first.job_id, manual.job_id)
            self.assertEqual(len(repository.list_learning_jobs(state_id=state.state_id)), 2)
            self.assertEqual(
                repository.load_learning_job_for_episode(
                    job_type="episode_boundary_learning", episode_id=episode.episode_id
                ).job_id,
                manual.job_id,
            )


if __name__ == "__main__":
    unittest.main()
