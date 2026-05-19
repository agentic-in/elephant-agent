from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest

from packages.contracts import (
    ExperienceRecord,
    ProcedureRecord,
    PersonalModelGrowthState,
)
from packages.growth import (
    GrowthTurnSignals,
    ProgressionProjectionBuilder,
    ProgressionReplayCase,
    ProgressionSurfaceAudit,
    apply_turn_growth,
    build_growth_snapshot,
    build_progression_rollout_scorecard,
    default_progression_rollout_scorecard,
    default_growth_state,
    stage_for_level,
    unbounded_level_floor_score,
    xp_to_next_level,
)


class GrowthRuntimeTest(unittest.TestCase):
    def test_projection_stays_unbounded_and_uses_evidence_identity(self) -> None:
        builder = ProgressionProjectionBuilder()
        projection = builder.build(
            profile_id="profile-companion",
            state=PersonalModelGrowthState(
                profile_id="profile-companion",
                growth_score=unbounded_level_floor_score(41) + 25,
                total_dialogues=12,
                total_tokens=4_800,
            ),
        )

        self.assertGreater(projection.level, 40)
        self.assertEqual(projection.ring_index, 5)
        self.assertEqual(projection.cycle_label, "Evidence V")
        self.assertEqual(projection.identity_line, "Evidence V · learning the path")

    def test_projection_uses_understanding_labels_instead_of_titles(self) -> None:
        builder = ProgressionProjectionBuilder()
        high_power_state = PersonalModelGrowthState(
            profile_id="profile-companion",
            growth_score=unbounded_level_floor_score(21) + 20,
            total_dialogues=6,
            total_tokens=2_400,
        )
        active_work_item = SimpleNamespace(
            work_item_id="state-release",
            session_id="session-1",
            title="Close the release checklist",
            status="active",
            priority="high",
        )
        experiences = (
            ExperienceRecord(
                experience_id="experience:1",
                episode_id="session-1",
                personal_model_id="profile-companion",
                elephant_id=None,
                kind="execution",
                title="Closed the release checklist",
                summary="Captured durable execution evidence for the release flow.",
                status="captured",
            ),
        )

        without_reusable_learning = builder.build(
            profile_id="profile-companion",
            state=high_power_state,
            experiences=experiences,
            active_work_item=active_work_item,
        )
        with_reusable_learning = builder.build(
            profile_id="profile-companion",
            state=high_power_state,
            experiences=experiences,
            procedures=(
                ProcedureRecord(
                    procedure_id="procedure:release-checklist",
                    title="Release Checklist",
                    summary="Carry the release checklist forward cleanly.",
                    status="verified",
                ),
            ),
            active_work_item=active_work_item,
        )

        self.assertEqual(without_reusable_learning.cycle_label, "Evidence III")
        self.assertEqual(without_reusable_learning.stage_title, "carrying the path")
        self.assertEqual(with_reusable_learning.stage_title, "grounded in evidence")
        self.assertNotEqual(with_reusable_learning.stage_title, without_reusable_learning.stage_title)

    def test_stage_boundaries_follow_expected_level_ranges(self) -> None:
        self.assertEqual(stage_for_level(0).stage_id, "seed")
        self.assertEqual(stage_for_level(0).title, "Seed")
        self.assertEqual(stage_for_level(9).stage_id, "seed")
        self.assertEqual(stage_for_level(10).stage_id, "elephant")
        self.assertEqual(stage_for_level(10).title, "Elephant")
        self.assertEqual(stage_for_level(19).stage_id, "elephant")
        self.assertEqual(stage_for_level(20).stage_id, "scout")
        self.assertEqual(stage_for_level(20).title, "Scout")
        self.assertEqual(stage_for_level(29).stage_id, "scout")
        self.assertEqual(stage_for_level(30).stage_id, "elephant")
        self.assertEqual(stage_for_level(30).title, "Elephant Agent")
        self.assertEqual(stage_for_level(40).stage_id, "elephant")

    def test_level_curve_gets_harder_across_stage_boundaries(self) -> None:
        self.assertEqual(xp_to_next_level(0), 100)
        self.assertGreater(xp_to_next_level(10), xp_to_next_level(9))
        self.assertGreater(xp_to_next_level(20), xp_to_next_level(19))
        self.assertGreater(xp_to_next_level(30), xp_to_next_level(29))

    def test_first_turn_boost_and_second_turn_promotion_are_guaranteed(self) -> None:
        now = datetime.now(timezone.utc)
        initial = default_growth_state("profile-companion", now=now)

        first = apply_turn_growth(
            initial,
            GrowthTurnSignals(
                session_id="session-1",
                profile_id="profile-companion",
                total_tokens=64,
                captured_experiences=1,
                occurred_at=now,
            ),
        )
        first_snapshot = build_growth_snapshot(first.after.state)
        self.assertEqual(first_snapshot.level, 0)
        self.assertEqual(first_snapshot.state.growth_score, 40)
        self.assertEqual(first_snapshot.progress_percent, 40)
        self.assertEqual(first.reward_reasons[0].reason_id, "first-turn-boost")

        second = apply_turn_growth(
            first.after.state,
            GrowthTurnSignals(
                session_id="session-1",
                profile_id="profile-companion",
                total_tokens=64,
                captured_experiences=1,
                occurred_at=now,
            ),
        )
        second_snapshot = build_growth_snapshot(second.after.state)
        self.assertEqual(second_snapshot.level, 1)
        self.assertGreaterEqual(second_snapshot.state.growth_score, 100)
        self.assertEqual(second.reward_reasons[0].reason_id, "second-turn-promotion")

    def test_personal_model_understanding_signals_outrank_token_heavy_flat_turns(
        self,
    ) -> None:
        now = datetime(2026, 4, 18, tzinfo=timezone.utc)
        current = self._mature_state(now=now)

        meaningful = apply_turn_growth(
            current,
            GrowthTurnSignals(
                session_id="session-meaningful",
                profile_id=current.profile_id,
                total_tokens=620,
                captured_experiences=1,
                promoted_experiences=1,
                continuity_bonus=True,
                occurred_at=now,
                work_item_id="state-release",
                work_item_status="blocked",
                work_item_priority="high",
                progression_action="advance",
                resume_signal="resume",
                continuity_mode="background",
                execution_outcome="ok",
                experience_status="captured",
                active_work_item_present=True,
                plan_step_count=3,
                work_item_dependency_count=1,
                recall_count=2,
                context_work_item_count=1,
                tool_call_count=2,
                model_turn_count=2,
                blocked_work_item_count=1,
                work_item_evidence_refs=("artifact:blocker",),
                replay_evidence_refs=("evidence:resume-proof",),
                skill_ids=("skill.checks",),
                artifact_ids=("artifact:patch-note",),
                promoted_procedure_ids=("procedure:resume-checklist",),
                personal_model_fact_count=7,
                personal_model_lens_counts=(
                    ("identity", 2),
                    ("world", 2),
                    ("pulse", 2),
                    ("journey", 1),
                ),
                personal_model_topic_count=5,
                personal_model_new_fact_count=2,
                personal_model_updated_fact_count=1,
                personal_model_supported_fact_count=7,
                personal_model_evidence_ref_count=8,
                personal_model_high_confidence_fact_count=5,
                personal_model_rich_fact_count=3,
                personal_model_average_confidence=0.86,
                elapsed_since_last_turn_seconds=3 * 24 * 60 * 60,
            ),
        )
        flat = apply_turn_growth(
            current,
            GrowthTurnSignals(
                session_id="session-flat",
                profile_id=current.profile_id,
                total_tokens=9000,
                captured_experiences=1,
                occurred_at=now,
                execution_outcome="ok",
                experience_status="captured",
                elapsed_since_last_turn_seconds=3 * 24 * 60 * 60,
            ),
        )

        self.assertGreater(meaningful.delta_score, flat.delta_score)
        meaningful_reasons = {reason.reason_id: reason for reason in meaningful.reward_reasons}
        flat_reasons = {reason.reason_id: reason for reason in flat.reward_reasons}
        self.assertIn("understanding-coverage", meaningful_reasons)
        self.assertIn("understanding-richness", meaningful_reasons)
        self.assertIn("understanding-freshness", meaningful_reasons)
        self.assertIn("understanding-grounding", meaningful_reasons)
        self.assertIn("continuity", meaningful_reasons)
        self.assertIn("tokens-support", flat_reasons)
        self.assertLess(
            flat_reasons["tokens-support"].score,
            meaningful_reasons["understanding-freshness"].score,
        )
        self.assertLess(
            flat_reasons["tokens-support"].score,
            meaningful_reasons["understanding-grounding"].score,
        )

    def test_reward_reasons_keep_pm_freshness_and_grounding_traceable(self) -> None:
        now = datetime(2026, 4, 18, tzinfo=timezone.utc)
        update = apply_turn_growth(
            self._mature_state(now=now),
            GrowthTurnSignals(
                session_id="session-traceable",
                profile_id="profile-companion",
                total_tokens=512,
                captured_experiences=1,
                promoted_experiences=1,
                continuity_bonus=True,
                occurred_at=now,
                work_item_id="state-release",
                work_item_status="active",
                work_item_priority="high",
                progression_action="advance",
                resume_signal="resume",
                continuity_mode="background",
                execution_outcome="ok",
                experience_status="captured",
                active_work_item_present=True,
                plan_step_count=2,
                recall_count=1,
                context_work_item_count=1,
                replay_evidence_refs=("evidence:resume-proof",),
                promoted_procedure_ids=("procedure:resume-checklist",),
                work_item_evidence_refs=("artifact:brief",),
                personal_model_fact_count=5,
                personal_model_lens_counts=(
                    ("identity", 1),
                    ("world", 2),
                    ("pulse", 1),
                    ("journey", 1),
                ),
                personal_model_topic_count=4,
                personal_model_new_fact_count=1,
                personal_model_updated_fact_count=1,
                personal_model_supported_fact_count=5,
                personal_model_evidence_ref_count=6,
                personal_model_high_confidence_fact_count=3,
                personal_model_rich_fact_count=2,
                personal_model_average_confidence=0.82,
                elapsed_since_last_turn_seconds=12 * 60 * 60,
            ),
        )
        reasons = {reason.reason_id: reason for reason in update.reward_reasons}

        self.assertIn("evidence:resume-proof", reasons["continuity"].evidence_refs)
        self.assertIn("resume-signal=resume", reasons["continuity"].facts)
        self.assertIn("new-facts=1", reasons["understanding-freshness"].facts)
        self.assertIn("updated-facts=1", reasons["understanding-freshness"].facts)
        self.assertIn("supported-facts=5", reasons["understanding-grounding"].facts)
        self.assertIn("understanding-freshness:16", update.awarded_for)

    def test_support_terms_stay_bounded(self) -> None:
        now = datetime(2026, 4, 18, tzinfo=timezone.utc)
        update = apply_turn_growth(
            self._mature_state(now=now),
            GrowthTurnSignals(
                session_id="session-support",
                profile_id="profile-companion",
                total_tokens=100_000,
                occurred_at=now,
                execution_outcome="ok",
                experience_status="captured",
                elapsed_since_last_turn_seconds=60 * 60,
            ),
        )
        reasons = {reason.reason_id: reason for reason in update.reward_reasons}

        self.assertLessEqual(reasons["tokens-support"].score, 6)
        self.assertLessEqual(reasons["cadence-support"].score, 3)
        self.assertLessEqual(reasons["streak-support"].score, 6)
        self.assertTrue(reasons["tokens-support"].bounded)
        self.assertTrue(reasons["cadence-support"].bounded)
        self.assertTrue(reasons["streak-support"].bounded)

    def test_default_progression_rollout_scorecard_certifies_shadow_pack(self) -> None:
        scorecard = default_progression_rollout_scorecard()

        self.assertTrue(scorecard.certified)
        self.assertEqual(scorecard.rollout_mode, "shadow-certified")
        self.assertEqual(scorecard.fallback_mode, "baseline-snapshot")
        self.assertFalse(scorecard.explanation_drift_cases)
        gates = {gate.gate_id: gate for gate in scorecard.gates}
        self.assertTrue(all(gate.status == "pass" for gate in gates.values()))

        comparisons = {comparison.case_id: comparison for comparison in scorecard.comparisons}
        self.assertGreater(
            comparisons["meaningful-a"].delta_score,
            comparisons["trivial-a"].delta_score,
        )
        self.assertLess(comparisons["trivial-b"].delta_score, comparisons["trivial-a"].delta_score)
        self.assertIn("token-heavy", comparisons["trivial-b"].anti_grind_flags)
        self.assertTrue(
            any(condition.startswith("fallback to baseline-snapshot mode") for condition in scorecard.stop_conditions)
        )

    def test_progression_rollout_scorecard_falls_back_when_ui_budget_regresses(
        self,
    ) -> None:
        now = datetime(2026, 4, 18, tzinfo=timezone.utc)
        case = ProgressionReplayCase(
            case_id="meaningful-ui",
            label="meaningful replay bundle",
            difficulty_band="medium",
            pattern_family="meaningful-ui",
            classification="meaningful",
            initial_state=self._mature_state(now=now),
            profile_id="profile-companion",
            signals=GrowthTurnSignals(
                session_id="session-ui",
                profile_id="profile-companion",
                total_tokens=620,
                captured_experiences=1,
                promoted_experiences=1,
                continuity_bonus=True,
                occurred_at=now,
                work_item_id="state-release",
                work_item_status="blocked",
                work_item_priority="high",
                progression_action="advance",
                resume_signal="resume",
                continuity_mode="background",
                execution_outcome="ok",
                experience_status="captured",
                active_work_item_present=True,
                plan_step_count=3,
                work_item_dependency_count=1,
                recall_count=2,
                context_work_item_count=1,
                tool_call_count=2,
                model_turn_count=2,
                blocked_work_item_count=1,
                work_item_evidence_refs=("artifact:blocker",),
                replay_evidence_refs=("evidence:resume-proof",),
                skill_ids=("skill.checks",),
                artifact_ids=("artifact:patch-note",),
                promoted_procedure_ids=("procedure:resume-checklist",),
                elapsed_since_last_turn_seconds=3 * 24 * 60 * 60,
            ),
            active_work_item=SimpleNamespace(
                work_item_id="state-release",
                session_id="session-ui",
                title="Recover the blocked release lane",
                status="blocked",
                priority="high",
            ),
            experiences=(
                ExperienceRecord(
                    experience_id="experience:ui",
                    episode_id="session-ui",
                    personal_model_id="profile-companion",
                    elephant_id="elephant-1",
                    kind="execution",
                    title="Recovered the release blocker",
                    summary="Validated the patch and kept the thread intact.",
                    status="captured",
                ),
            ),
            procedures=(
                ProcedureRecord(
                    procedure_id="procedure:resume-checklist",
                    title="Resume Checklist",
                    summary="Carry a resumed blocker lane through validation.",
                    status="verified",
                ),
            ),
            continuity_mode="background",
            wake_action="recover the blocked release lane",
        )

        scorecard = build_progression_rollout_scorecard(
            (case,),
            surface_audit=ProgressionSurfaceAudit(
                progression_lines=12,
                current_focus_lines=3,
                next_move_lines=2,
                recall_reason_lines=1,
                explanation_lines=1,
            ),
        )

        self.assertEqual(scorecard.rollout_mode, "baseline-fallback")
        self.assertEqual(scorecard.fallback_mode, "baseline-snapshot")
        gates = {gate.gate_id: gate for gate in scorecard.gates}
        self.assertEqual(gates["continuity-ui"].status, "fail")

    def _mature_state(self, *, now: datetime) -> PersonalModelGrowthState:
        return PersonalModelGrowthState(
            profile_id="profile-companion",
            growth_score=140,
            total_dialogues=3,
            total_tokens=900,
            total_experiences=2,
            promoted_experiences=0,
            active_days=2,
            streak_days=1,
            first_dialogue_at=now - timedelta(days=5),
            last_dialogue_at=now - timedelta(days=3),
            last_active_day=(now - timedelta(days=3)).date().isoformat(),
            created_at=now - timedelta(days=5),
            updated_at=now - timedelta(days=3),
        )


if __name__ == "__main__":
    unittest.main()
