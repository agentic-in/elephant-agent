from __future__ import annotations

from types import SimpleNamespace
import unittest

from packages.contracts.runtime import LearningJob
from packages.reflect.evidence import _episode_turn_summary, _skill_catalog, build_evidence


class ReflectEvidenceObservabilityTests(unittest.TestCase):
    def test_skill_catalog_runtime_failure_is_logged(self) -> None:
        runtime = SimpleNamespace(list_skills=lambda: (_ for _ in ()).throw(RuntimeError("skills unavailable")))

        with self.assertLogs("packages.reflect.evidence", level="DEBUG") as logs:
            self.assertEqual(_skill_catalog(runtime), ())

        self.assertIn("Failed to list skills from reflect runtime", "\n".join(logs.output))

    def test_skill_catalog_nested_runtime_failure_is_logged(self) -> None:
        skill_runtime = SimpleNamespace(list_skills=lambda: (_ for _ in ()).throw(RuntimeError("skills unavailable")))
        runtime = SimpleNamespace(skill_runtime=skill_runtime)

        with self.assertLogs("packages.reflect.evidence", level="DEBUG") as logs:
            self.assertEqual(_skill_catalog(runtime), ())

        self.assertIn("Failed to list skills from reflect skill runtime", "\n".join(logs.output))

    def test_episode_turn_summary_loop_failure_is_logged(self) -> None:
        class Repository:
            def list_loops(self, **_: object) -> tuple[object, ...]:
                raise RuntimeError("loops unavailable")

        runtime = SimpleNamespace(repository=Repository())

        with self.assertLogs("packages.reflect.evidence", level="DEBUG") as logs:
            self.assertEqual(_episode_turn_summary(runtime, episode_id="episode"), ())

        self.assertIn("Failed to load reflect evidence episode loops", "\n".join(logs.output))

    def test_build_evidence_logs_fact_and_timezone_failures(self) -> None:
        class Repository:
            def load_episode(self, episode_id: str) -> object:
                del episode_id
                return SimpleNamespace(exit_summary="")

            def list_personal_model_facts(self, **_: object) -> tuple[object, ...]:
                raise RuntimeError("facts unavailable")

        runtime = SimpleNamespace(
            repository=Repository(),
            inspect_user=lambda **_: (_ for _ in ()).throw(RuntimeError("user unavailable")),
        )
        job = LearningJob(
            job_id="job",
            job_type="reflection",
            trigger="dream",
            status="queued",
            personal_model_id="pm",
            state_id="state",
            episode_id="episode",
        )

        with self.assertLogs("packages.reflect.evidence", level="DEBUG") as logs:
            evidence = build_evidence(runtime, job, (SimpleNamespace(feature_id="dream"),))

        rendered_logs = "\n".join(logs.output)
        self.assertIn("## Dream context", evidence)
        self.assertIn("Failed to load active Personal Model facts for reflect evidence", rendered_logs)
        self.assertIn("Failed to inspect user timezone for dream reflect evidence", rendered_logs)


if __name__ == "__main__":
    unittest.main()
