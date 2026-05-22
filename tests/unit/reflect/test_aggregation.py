from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from packages.reflect.aggregation import aggregate_signals, build_candidate_key
from packages.reflect.types import ToolTrajectorySignal


class _Repository:
    def __init__(self, facts) -> None:
        self._facts = tuple(facts)

    def list_personal_model_facts(self, **_: object):
        return self._facts


def _existing_candidate(*, candidate_key: str, review_status: str, occurrence_count: int = 3, confidence: str = "0.72"):
    return SimpleNamespace(
        fact_id=f"fact:{candidate_key}",
        status="active",
        committed_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
        text="stored optimization candidate",
        metadata={
            "topic": f"world.skills.optimization.new.{candidate_key}",
            "candidate_key": candidate_key,
            "review_status": review_status,
            "occurrence_count": str(occurrence_count),
            "confidence": confidence,
            "optimization_type": "create_new",
            "signal_type": "recurring_sequence",
        },
    )


class AggregationTest(unittest.TestCase):
    def test_unmatched_signal_becomes_create_new_candidate(self) -> None:
        repository = _Repository(())
        signal = ToolTrajectorySignal(
            signal_id="sig-1",
            signal_type="recurring_sequence",
            tool_names=("tool.terminal.exec", "tool.file.read"),
            episode_ids=("ep-1", "ep-2", "ep-3"),
            occurrence_count=3,
            confidence=0.74,
            summary="tool sequence repeated",
        )

        candidates = aggregate_signals((signal,), repository, personal_model_id="pm")

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].optimization_type, "create_new")
        self.assertIsNone(candidates[0].target_skill_id)

    def test_matching_skill_splits_candidates_by_optimization_type(self) -> None:
        repository = _Repository(
            (
                SimpleNamespace(
                    metadata={
                        "topic": "world.skills.affinity.python_development",
                        "skill_id": "python-development",
                        "index_id": "python_development",
                    }
                ),
            )
        )
        skill = SimpleNamespace(
            skill_id="python-development",
            display_name="Python Development",
            instruction_text="Use tool.terminal.exec before tool.file.read and recover from tool.terminal.exec failures.",
        )
        recurring = ToolTrajectorySignal(
            signal_id="sig-recurring",
            signal_type="recurring_sequence",
            tool_names=("tool.terminal.exec", "tool.file.read"),
            episode_ids=("ep-1", "ep-2", "ep-3"),
            occurrence_count=3,
            confidence=0.72,
            summary="tool sequence repeated",
        )
        recovery = ToolTrajectorySignal(
            signal_id="sig-recovery",
            signal_type="error_recovery",
            tool_names=("tool.terminal.exec", "tool.file.read"),
            episode_ids=("ep-1", "ep-4"),
            occurrence_count=2,
            confidence=0.7,
            summary="tool recovery repeated",
        )

        candidates = aggregate_signals(
            (recurring, recovery),
            repository,
            personal_model_id="pm",
            skills=(skill,),
            max_candidates=10,
        )

        self.assertEqual(len(candidates), 2)
        self.assertEqual({candidate.optimization_type for candidate in candidates}, {"update_procedure", "add_error_handling"})
        self.assertEqual({candidate.target_skill_id for candidate in candidates}, {"python-development"})

    def test_existing_rejected_candidate_is_suppressed_when_evidence_is_not_stronger(self) -> None:
        signal = ToolTrajectorySignal(
            signal_id="sig-recurring",
            signal_type="recurring_sequence",
            tool_names=("tool.terminal.exec", "tool.file.read"),
            episode_ids=("ep-1", "ep-2", "ep-3"),
            occurrence_count=3,
            confidence=0.72,
            summary="tool sequence repeated",
        )
        candidate_key = build_candidate_key("create_new", signal, target_index_id=None)
        repository = _Repository((_existing_candidate(candidate_key=candidate_key, review_status="rejected"),))

        candidates = aggregate_signals((signal,), repository, personal_model_id="pm")

        self.assertEqual(candidates, ())

    def test_rejected_candidate_can_reappear_when_new_evidence_is_materially_stronger(self) -> None:
        signal = ToolTrajectorySignal(
            signal_id="sig-recurring",
            signal_type="recurring_sequence",
            tool_names=("tool.terminal.exec", "tool.file.read"),
            episode_ids=("ep-1", "ep-2", "ep-3", "ep-4", "ep-5"),
            occurrence_count=5,
            confidence=0.86,
            summary="tool sequence repeated more often",
        )
        candidate_key = build_candidate_key("create_new", signal, target_index_id=None)
        repository = _Repository(
            (
                _existing_candidate(
                    candidate_key=candidate_key,
                    review_status="rejected",
                    occurrence_count=3,
                    confidence="0.72",
                ),
            )
        )

        candidates = aggregate_signals((signal,), repository, personal_model_id="pm")

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].candidate_key, candidate_key)
        self.assertEqual(candidates[0].metadata["occurrence_count"], "5")


if __name__ == "__main__":
    unittest.main()
