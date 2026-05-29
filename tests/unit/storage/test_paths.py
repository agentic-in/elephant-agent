from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from packages.contracts import SemanticIndexEntry
from packages.storage import RuntimeStorageRepository


class RuntimeStoragePathTest(unittest.TestCase):
    def test_path_step_summary_and_understanding_check_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()

            path = repository.create_path(
                title="Healthy rhythm",
                description="Sleep, food, and movement loop.",
                review_mode="trusted",
                owner_elephant_id="mother-elephant",
                metadata={"domain": "health"},
            )
            step = repository.create_path_step(
                path_id=path.path_id,
                title="Plan first week",
                description="Turn the direction into a small repeatable loop.",
                assignee_elephant_id="baby-coach",
            )
            moved_step = replace(step, status="done")
            repository.upsert_path_step(moved_step)
            summary = repository.write_learning_summary(
                path_step_id=step.path_step_id,
                what_done="Created the first weekly loop.",
                why_it_matters="It makes the path executable.",
                how_it_was_done="Split sleep and training into visible checks.",
                knowledge="Habit loops need tiny next actions.",
                human_takeaway="Small loops are easier to inspect.",
                created_by_elephant_id="baby-coach",
            )
            pending = repository.write_understanding_check(
                summary_id=summary.summary_id,
                status="pending",
            )
            understood = repository.write_understanding_check(
                summary_id=summary.summary_id,
                status="understood",
                note="I understand the loop.",
            )

            reloaded_path = repository.load_path(path.path_id)
            reloaded_step = repository.load_path_step(step.path_step_id)
            summaries = repository.list_learning_summaries(path_step_id=step.path_step_id)
            checks = repository.list_understanding_checks(summary_id=summary.summary_id)

        self.assertIsNotNone(reloaded_path)
        assert reloaded_path is not None
        self.assertEqual(reloaded_path.title, "Healthy rhythm")
        self.assertEqual(reloaded_path.review_mode, "trusted")
        self.assertEqual(reloaded_path.metadata["domain"], "health")
        self.assertIsNotNone(reloaded_step)
        assert reloaded_step is not None
        self.assertEqual(reloaded_step.status, "done")
        self.assertIsNotNone(reloaded_step.completed_at)
        self.assertEqual(summaries[0].what_done, "Created the first weekly loop.")
        self.assertEqual(pending.check_id, understood.check_id)
        self.assertEqual(checks[0].status, "understood")
        self.assertEqual(checks[0].note, "I understand the loop.")

    def test_learning_summary_and_understanding_check_drive_step_review_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()

            path = repository.create_path(title="Learn strength training")
            step = repository.create_path_step(
                path_id=path.path_id,
                title="Explain progressive overload",
                status="moving",
                assignee_elephant_id="baby-coach",
            )
            summary = repository.write_learning_summary(
                path_step_id=step.path_step_id,
                what_done="Explained the training principle and first practice.",
                why_it_matters="The user should understand why weights increase slowly.",
                how_it_was_done="Connected volume, intensity, rest, and recovery.",
                knowledge="Progressive overload needs small measurable increments.",
                human_takeaway="Track one lift and adjust only after it feels stable.",
            )
            checking_step = repository.load_path_step(step.path_step_id)
            repository.write_understanding_check(summary_id=summary.summary_id, status="understood")
            done_step = repository.load_path_step(step.path_step_id)
            repository.write_understanding_check(summary_id=summary.summary_id, status="needs_clarification")
            stuck_step = repository.load_path_step(step.path_step_id)

        self.assertIsNotNone(checking_step)
        self.assertIsNotNone(done_step)
        self.assertIsNotNone(stuck_step)
        assert checking_step is not None
        assert done_step is not None
        assert stuck_step is not None
        self.assertEqual(checking_step.status, "checking")
        self.assertEqual(done_step.status, "done")
        self.assertIsNotNone(done_step.completed_at)
        self.assertEqual(stuck_step.status, "stuck")
        self.assertIsNone(stuck_step.completed_at)

    def test_path_step_run_lifecycle_retry_and_learning_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()

            path = repository.create_path(title="Build calmer rhythm")
            step = repository.create_path_step(
                path_id=path.path_id,
                title="Design first loop",
                status="next",
                assignee_elephant_id="baby-coach",
            )
            queued = repository.create_path_step_run(
                path_step_id=step.path_step_id,
                run_id="run:first",
                status="queued",
                max_attempts=2,
            )
            queued_step = repository.load_path_step(step.path_step_id)
            running = repository.update_path_step_run(
                queued.run_id,
                status="running",
                progress_stage="research",
                progress_detail="Checking context",
                progress_current=1,
                progress_total=3,
                runtime_id="runtime:codex",
                work_dir="/tmp/elephant-run",
            )
            failed = repository.update_path_step_run(
                queued.run_id,
                status="failed",
                failure_reason="runtime_timeout",
            )
            stuck_step = repository.load_path_step(step.path_step_id)
            retry = repository.retry_path_step_run(
                failed.run_id,
                reason="runtime_timeout",
                run_id_override="run:retry",
            )
            retry_step = repository.load_path_step(step.path_step_id)
            summary = repository.write_learning_summary(
                path_step_id=step.path_step_id,
                run_id=retry.run_id,
                what_done="Built first loop.",
            )
            completed_retry = repository.load_path_step_run(retry.run_id)
            checking_step = repository.load_path_step(step.path_step_id)
            repository.write_understanding_check(summary_id=summary.summary_id, status="understood")
            done_step = repository.load_path_step(step.path_step_id)

        self.assertIsNotNone(queued_step)
        self.assertIsNotNone(stuck_step)
        self.assertIsNotNone(retry_step)
        self.assertIsNotNone(completed_retry)
        self.assertIsNotNone(checking_step)
        self.assertIsNotNone(done_step)
        assert queued_step is not None
        assert stuck_step is not None
        assert retry_step is not None
        assert completed_retry is not None
        assert checking_step is not None
        assert done_step is not None
        self.assertEqual(queued_step.status, "moving")
        self.assertEqual(running.progress_current, 1)
        self.assertEqual(running.progress_total, 3)
        self.assertEqual(running.runtime_id, "runtime:codex")
        self.assertEqual(failed.failure_reason, "runtime_timeout")
        self.assertEqual(stuck_step.status, "stuck")
        self.assertEqual(retry.attempt, 2)
        self.assertEqual(retry.metadata["retry_of"], "run:first")
        self.assertEqual(retry.metadata["retry_reason"], "runtime_timeout")
        self.assertEqual(retry_step.status, "moving")
        self.assertEqual(completed_retry.status, "completed")
        self.assertEqual(checking_step.status, "checking")
        self.assertEqual(done_step.status, "done")
        self.assertIsNotNone(done_step.completed_at)

    def test_path_step_run_queue_claim_lease_sweep_and_retry_parent_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()

            path = repository.create_path(title="Queue path")
            step = repository.create_path_step(
                path_id=path.path_id,
                title="Run through baby runtime",
                assignee_elephant_id="baby-queue",
            )
            queued = repository.create_path_step_run(
                path_step_id=step.path_step_id,
                run_id="run:queue:first",
                max_attempts=3,
            )

            claimed = repository.claim_path_step_run(
                runtime_id="runtime:baby-queue",
                assignee_elephant_id="baby-queue",
                lease_seconds=60,
            )
            unavailable = repository.claim_path_step_run(
                runtime_id="runtime:other",
                lease_seconds=60,
            )
            running = repository.start_path_step_run(
                queued.run_id,
                runtime_id="runtime:baby-queue",
                claim_token=claimed.claim_token if claimed is not None else "",
                lease_seconds=60,
            )
            heartbeat = repository.heartbeat_path_step_run(
                queued.run_id,
                runtime_id="runtime:baby-queue",
                claim_token=running.claim_token,
                lease_seconds=60,
                progress_stage="model_run",
                progress_detail="Running real work",
                progress_current=2,
                progress_total=4,
            )
            stale_at = datetime.now(timezone.utc) - timedelta(hours=2)
            repository.upsert_path_step_run(
                replace(
                    heartbeat,
                    heartbeat_at=stale_at,
                    lease_expires_at=stale_at,
                )
            )
            failed_runs = repository.sweep_path_step_runs(running_timeout_seconds=1)
            failed = repository.load_path_step_run(queued.run_id)
            retry = repository.maybe_retry_path_step_run(queued.run_id, reason="timeout")

        self.assertIsNotNone(claimed)
        assert claimed is not None
        self.assertEqual(claimed.status, "dispatched")
        self.assertEqual(claimed.runtime_id, "runtime:baby-queue")
        self.assertTrue(claimed.claim_token)
        self.assertIsNotNone(claimed.lease_expires_at)
        self.assertIsNone(claimed.started_at)
        self.assertIsNone(unavailable)
        self.assertEqual(running.status, "running")
        self.assertIsNotNone(running.started_at)
        self.assertEqual(heartbeat.progress_stage, "model_run")
        self.assertEqual(heartbeat.progress_current, 2)
        self.assertEqual(len(failed_runs), 1)
        self.assertIsNotNone(failed)
        assert failed is not None
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.failure_reason, "timeout")
        self.assertIsNone(failed.lease_expires_at)
        self.assertIsNotNone(retry)
        assert retry is not None
        self.assertEqual(retry.status, "queued")
        self.assertEqual(retry.parent_run_id, queued.run_id)
        self.assertEqual(retry.attempt, 2)
        self.assertEqual(retry.metadata["retry_of"], queued.run_id)
        self.assertEqual(retry.metadata["retry_reason"], "timeout")

    def test_path_step_comments_round_trip_and_cascade(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()

            path = repository.create_path(title="Comment path")
            step = repository.create_path_step(path_id=path.path_id, title="Discuss step")
            run = repository.create_path_step_run(path_step_id=step.path_step_id, run_id="run:comment")
            user_comment = repository.create_path_step_comment(
                path_step_id=step.path_step_id,
                body="Can you also include the edge case?",
                author_kind="user",
                author_id="user",
            )
            agent_comment = repository.create_path_step_comment(
                path_step_id=step.path_step_id,
                body="Included the edge case in the final result.",
                author_kind="elephant",
                author_id="baby-research",
                comment_type="run_output",
                run_id=run.run_id,
                parent_comment_id=user_comment.comment_id,
            )
            comments = repository.list_path_step_comments(path_step_id=step.path_step_id)
            run_comments = repository.list_path_step_comments(run_id=run.run_id)
            repository.delete_path_step(step.path_step_id)
            deleted_comment = repository.load_path_step_comment(user_comment.comment_id)

        self.assertEqual([comment.comment_id for comment in comments], [user_comment.comment_id, agent_comment.comment_id])
        self.assertEqual(run_comments[0].comment_id, agent_comment.comment_id)
        self.assertEqual(agent_comment.parent_comment_id, user_comment.comment_id)
        self.assertIsNone(deleted_comment)

    def test_delete_path_and_step_cascade_learning_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "state" / "elephant.sqlite3")
            repository.bootstrap()

            path = repository.create_path(title="Temporary direction")
            step = repository.create_path_step(path_id=path.path_id, title="Temporary step")
            run = repository.create_path_step_run(path_step_id=step.path_step_id, run_id="run:delete")
            summary = repository.write_learning_summary(
                path_step_id=step.path_step_id,
                run_id=run.run_id,
                what_done="Temporary work.",
            )
            repository.write_understanding_check(summary_id=summary.summary_id, status="pending")
            repository.upsert_semantic_index_entry(
                SemanticIndexEntry(
                    semantic_index_entry_id="semantic:path-step-delete",
                    owner_scope="personal_model",
                    source_id=f"path:learning_summary:{summary.summary_id}",
                    provider_id="stub-provider",
                    model_id="stub-model",
                    dimensions=4,
                    content_hash="sha256:path-step-delete",
                    personal_model_id=path.personal_model_id,
                    created_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
                    updated_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
                )
            )

            deleted_step = repository.delete_path_step(step.path_step_id)
            deleted_step_index = repository.load_semantic_index_entry("semantic:path-step-delete")

            self.assertTrue(deleted_step)
            self.assertIsNone(repository.load_path_step(step.path_step_id))
            self.assertIsNone(repository.load_path_step_run(run.run_id))
            self.assertIsNone(repository.load_learning_summary(summary.summary_id))
            self.assertIsNotNone(deleted_step_index)
            assert deleted_step_index is not None
            self.assertEqual(deleted_step_index.status, "deleted")
            self.assertEqual(deleted_step_index.metadata["deleted_by"], "path_step_delete")

            second_step = repository.create_path_step(path_id=path.path_id, title="Second temporary step")
            second_summary = repository.write_learning_summary(
                path_step_id=second_step.path_step_id,
                what_done="Second temporary work.",
            )
            repository.upsert_semantic_index_entry(
                SemanticIndexEntry(
                    semantic_index_entry_id="semantic:path-delete",
                    owner_scope="personal_model",
                    source_id=f"path:learning_summary:{second_summary.summary_id}",
                    provider_id="stub-provider",
                    model_id="stub-model",
                    dimensions=4,
                    content_hash="sha256:path-delete",
                    personal_model_id=path.personal_model_id,
                    created_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
                    updated_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
                )
            )
            deleted_path = repository.delete_path(path.path_id)
            deleted_path_index = repository.load_semantic_index_entry("semantic:path-delete")

            self.assertTrue(deleted_path)
            self.assertIsNone(repository.load_path(path.path_id))
            self.assertIsNone(repository.load_path_step(second_step.path_step_id))
            self.assertIsNotNone(deleted_path_index)
            assert deleted_path_index is not None
            self.assertEqual(deleted_path_index.status, "deleted")
            self.assertEqual(deleted_path_index.metadata["deleted_by"], "path_delete")


if __name__ == "__main__":
    unittest.main()
