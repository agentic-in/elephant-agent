from __future__ import annotations

import json
from pathlib import Path
import unittest

SCENARIOS_PATH = Path(__file__).with_name("scenarios.yaml")


class ContinuityScenarioFixturesTest(unittest.TestCase):
    def test_continuity_scenarios_index_is_stable(self) -> None:
        payload = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(payload["track"], "CSR-4")
        self.assertEqual(
            [scenario["id"] for scenario in payload["scenarios"]],
            [
                "continuity.resume-after-gap",
                "continuity.interrupted-work",
                "continuity.recall-recovery",
                "continuity.explainable-next-step",
                "continuity.state-continuity",
                "continuity.correction-aware-recovery",
                "continuity.refocus-recovery",
            ],
        )
        for scenario in payload["scenarios"]:
            self.assertTrue((SCENARIOS_PATH.with_name(scenario["file"])).exists(), scenario["file"])

    def test_continuity_readme_stays_text_first_and_current_work_centered(self) -> None:
        readme = SCENARIOS_PATH.with_name("README.md").read_text(encoding="utf-8").lower()

        self.assertIn("current work", readme)
        self.assertIn("text-first", readme)
        self.assertNotIn("voice identity", readme)
        self.assertNotIn(" ".join(("goal", "graph")), readme)

    def test_state_continuity_fixture_declares_text_only_boundary(self) -> None:
        fixture = SCENARIOS_PATH.with_name("state-continuity.md").read_text(encoding="utf-8").lower()

        self.assertIn("text-only surface", fixture)
        self.assertIn("no voice transport", fixture)
        self.assertNotIn("later voice support", fixture)

    def test_companion_fixture_remains_the_text_first_identity_replacement(
        self,
    ) -> None:
        fixture = (
            (SCENARIOS_PATH.parents[1] / "companion" / "text-first-continuity.md").read_text(encoding="utf-8").lower()
        )

        self.assertIn("text-first", fixture)
        self.assertIn("without voice transport", fixture)
        self.assertNotIn("voice identity", fixture)

    def test_removed_planning_and_voice_fixture_paths_stay_deleted(self) -> None:
        removed_paths = (
            SCENARIOS_PATH.parents[1] / "planning" / "scenarios.yaml",
            SCENARIOS_PATH.parents[1] / "planning" / "test_planning_scenarios.py",
            SCENARIOS_PATH.with_name("proactive-voice-identity.md"),
        )

        for removed_path in removed_paths:
            with self.subTest(path=str(removed_path)):
                self.assertFalse(removed_path.exists())


if __name__ == "__main__":
    unittest.main()
