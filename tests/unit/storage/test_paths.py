from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
