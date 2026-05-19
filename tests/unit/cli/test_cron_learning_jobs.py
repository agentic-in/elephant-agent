from __future__ import annotations

from datetime import date as date_type, timedelta
from types import SimpleNamespace
import unittest

from apps.cli.runtime_extensions_surface import CliRuntimeExtensionsMixin


class CronLearningJobTest(unittest.TestCase):
    def test_dream_cron_defaults_to_yesterday_for_dream_and_diary(self) -> None:
        captured: dict[str, object] = {}

        def schedule_learning_for_session(**kwargs: object) -> SimpleNamespace:
            captured.update(kwargs)
            return SimpleNamespace(job_id="job:dream")

        runtime = SimpleNamespace(schedule_learning_for_session=schedule_learning_for_session)
        cron_job = SimpleNamespace(
            name="Nightly dream",
            payload={
                "trigger": "dream",
                "summary": "nightly Personal Model, question, skill, and diary maintenance",
            },
        )

        outcome, summary = CliRuntimeExtensionsMixin._execute_cron_learning_job(  # type: ignore[misc]
            runtime,
            cron_job,
            session_id="session",
        )

        yesterday = (date_type.today() - timedelta(days=1)).isoformat()
        self.assertEqual(outcome, "success")
        self.assertIn("job:dream", summary)
        self.assertEqual(captured["trigger"], "dream")
        self.assertEqual(
            captured["metadata"],
            {"target_date": yesterday, "diary_target_date": yesterday},
        )


if __name__ == "__main__":
    unittest.main()
