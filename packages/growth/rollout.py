"""Replay scorecards and rollout gates for progression surfaces."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from packages.contracts.runtime import (
    ExperienceRecord,
    ProcedureRecord,
    PersonalModelGrowthState,
)

from .projection import ProgressionProjection, ProgressionProjectionBuilder
from .runtime import (
    GrowthRewardReason,
    GrowthSnapshot,
    GrowthTurnSignals,
    apply_turn_growth,
)

_ROLLOUT_FAIRNESS_MARGIN = 12.0
_ROLLOUT_VARIANCE_LIMIT = 12
_ROLLOUT_MIN_MOTIVATION_DELTA = 10
_ROLLOUT_MAX_PROGRESSION_SHARE = 0.45
_ROLLOUT_STOP_CONDITIONS = (
    "block rollout if meaningful work no longer outruns trivial repetition inside the same difficulty band",
    "block rollout if similar replay bundles drift in top explanation or exceed bounded score variance",
    "block rollout if progression UI grows past the continuity-first layout budget",
    "fallback to baseline-snapshot mode if any progression rollout gate regresses",
)


@dataclass(frozen=True, slots=True)
class ProgressionSurfaceAudit:
    progression_lines: int
    current_focus_lines: int
    next_move_lines: int
    recall_reason_lines: int
    explanation_lines: int = 0
    note: str = ""

    @property
    def continuity_lines(self) -> int:
        return self.current_focus_lines + self.next_move_lines + self.recall_reason_lines

    @property
    def progression_share(self) -> float:
        total = self.progression_lines + self.continuity_lines + self.explanation_lines
        if total <= 0:
            return 0.0
        return self.progression_lines / total


@dataclass(frozen=True, slots=True)
class ProgressionReplayCase:
    case_id: str
    label: str
    difficulty_band: str
    pattern_family: str
    classification: str
    initial_state: PersonalModelGrowthState
    signals: GrowthTurnSignals
    profile_id: str
    experiences: tuple[ExperienceRecord, ...] = ()
    procedures: tuple[ProcedureRecord, ...] = ()
    active_work_item: object | None = None
    continuity_mode: str = "foreground"
    wake_action: str = ""


@dataclass(frozen=True, slots=True)
class ProgressionShadowComparison:
    case_id: str
    label: str
    difficulty_band: str
    pattern_family: str
    classification: str
    legacy_before: GrowthSnapshot
    legacy_after: GrowthSnapshot
    projection_before: ProgressionProjection
    projection_after: ProgressionProjection
    delta_score: int
    reward_reasons: tuple[GrowthRewardReason, ...]
    explanation_labels: tuple[str, ...]
    anti_grind_flags: tuple[str, ...]
    fallback_mode: str = "baseline-snapshot"


@dataclass(frozen=True, slots=True)
class ProgressionRolloutMetric:
    metric_id: str
    label: str
    value: str
    threshold: str
    status: str
    summary: str


@dataclass(frozen=True, slots=True)
class ProgressionRolloutGate:
    gate_id: str
    label: str
    status: str
    summary: str


@dataclass(frozen=True, slots=True)
class ProgressionRolloutScorecard:
    rollout_mode: str
    fallback_mode: str
    shadow_mode: str
    metrics: tuple[ProgressionRolloutMetric, ...]
    gates: tuple[ProgressionRolloutGate, ...]
    comparisons: tuple[ProgressionShadowComparison, ...]
    explanation_drift_cases: tuple[str, ...]
    stop_conditions: tuple[str, ...]

    @property
    def certified(self) -> bool:
        return self.rollout_mode == "shadow-certified"

    @property
    def summary(self) -> str:
        if self.certified:
            return "shadow-certified"
        return f"blocked -> {self.fallback_mode}"


def replay_progression_cases(
    cases: tuple[ProgressionReplayCase, ...],
    *,
    builder: ProgressionProjectionBuilder | None = None,
) -> tuple[ProgressionShadowComparison, ...]:
    projection_builder = builder or ProgressionProjectionBuilder()
    comparisons: list[ProgressionShadowComparison] = []
    for case in cases:
        update = apply_turn_growth(case.initial_state, case.signals)
        transition = projection_builder.transition(
            update,
            profile_id=case.profile_id,
            experiences=case.experiences,
            procedures=case.procedures,
            active_work_item=case.active_work_item,
            continuity_mode=case.continuity_mode,
            wake_action=case.wake_action,
        )
        comparisons.append(
            ProgressionShadowComparison(
                case_id=case.case_id,
                label=case.label,
                difficulty_band=case.difficulty_band,
                pattern_family=case.pattern_family,
                classification=case.classification,
                legacy_before=update.before,
                legacy_after=update.after,
                projection_before=transition.before,
                projection_after=transition.after,
                delta_score=update.delta_score,
                reward_reasons=update.reward_reasons,
                explanation_labels=tuple(reason.label for reason in update.reward_reasons),
                anti_grind_flags=transition.after.anti_grind_flags,
            )
        )
    return tuple(comparisons)


def build_progression_rollout_scorecard(
    cases: tuple[ProgressionReplayCase, ...],
    *,
    surface_audit: ProgressionSurfaceAudit | None = None,
    builder: ProgressionProjectionBuilder | None = None,
) -> ProgressionRolloutScorecard:
    comparisons = replay_progression_cases(cases, builder=builder)
    fairness_margin = _fairness_margin_for(comparisons)
    worst_variance = _worst_variance_for(comparisons)
    explanation_drift_cases = _explanation_drift_cases_for(comparisons)
    minimum_motivation_delta = _minimum_motivation_delta_for(comparisons)
    progression_share = surface_audit.progression_share if surface_audit is not None else 1.0
    continuity_lines = surface_audit.continuity_lines if surface_audit is not None else 0
    progression_lines = surface_audit.progression_lines if surface_audit is not None else 0

    fairness_ok = fairness_margin >= _ROLLOUT_FAIRNESS_MARGIN
    variance_ok = worst_variance <= _ROLLOUT_VARIANCE_LIMIT and not explanation_drift_cases
    motivation_ok = minimum_motivation_delta >= _ROLLOUT_MIN_MOTIVATION_DELTA
    continuity_ok = (
        surface_audit is not None
        and progression_share <= _ROLLOUT_MAX_PROGRESSION_SHARE
        and continuity_lines >= progression_lines
    )

    metrics = (
        ProgressionRolloutMetric(
            metric_id="fairness-margin",
            label="Fairness margin",
            value=f"{fairness_margin:.1f}",
            threshold=f">= {_ROLLOUT_FAIRNESS_MARGIN:.1f}",
            status="pass" if fairness_ok else "fail",
            summary="Meaningful replay bundles should materially outrun trivial repetition inside the same band.",
        ),
        ProgressionRolloutMetric(
            metric_id="variance",
            label="Replay variance",
            value=str(worst_variance),
            threshold=f"<= {_ROLLOUT_VARIANCE_LIMIT}",
            status="pass" if variance_ok else "fail",
            summary="Similar replay bundles should stay within a bounded score spread and keep explanation labels stable.",
        ),
        ProgressionRolloutMetric(
            metric_id="motivation-floor",
            label="Motivation floor",
            value=str(minimum_motivation_delta),
            threshold=f">= {_ROLLOUT_MIN_MOTIVATION_DELTA}",
            status="pass" if motivation_ok else "fail",
            summary="Non-trivial work should still advance the bar enough to feel alive.",
        ),
        ProgressionRolloutMetric(
            metric_id="ui-budget",
            label="Continuity-first UI budget",
            value=f"{progression_share:.2f}",
            threshold=f"<= {_ROLLOUT_MAX_PROGRESSION_SHARE:.2f}",
            status="pass" if continuity_ok else "fail",
            summary="Progression must stay subordinate to current focus, next move, and recall grammar.",
        ),
    )
    gates = (
        ProgressionRolloutGate(
            gate_id="fairness",
            label="Anti-grind fairness",
            status="pass" if fairness_ok else "fail",
            summary=(
                f"meaningful minus trivial margin {fairness_margin:.1f}"
                if fairness_ok
                else f"margin {fairness_margin:.1f} fell below the replay threshold"
            ),
        ),
        ProgressionRolloutGate(
            gate_id="explainability",
            label="Explanation drift",
            status="pass" if variance_ok else "fail",
            summary=(
                "stable explanation labels and bounded variance across similar replay bundles"
                if variance_ok
                else (
                    f"drifted in {', '.join(explanation_drift_cases)}"
                    if explanation_drift_cases
                    else f"variance {worst_variance} exceeded the replay tolerance"
                )
            ),
        ),
        ProgressionRolloutGate(
            gate_id="motivation",
            label="Motivation floor",
            status="pass" if motivation_ok else "fail",
            summary=(
                f"minimum non-trivial delta {minimum_motivation_delta}"
                if motivation_ok
                else f"minimum non-trivial delta {minimum_motivation_delta} fell below the rollout floor"
            ),
        ),
        ProgressionRolloutGate(
            gate_id="continuity-ui",
            label="Continuity-first layout budget",
            status="pass" if continuity_ok else "fail",
            summary=(
                f"progression share {progression_share:.2f} with {continuity_lines} continuity-first lines"
                if continuity_ok
                else "progression surface no longer stays subordinate to continuity-first layout budget"
            ),
        ),
    )
    certified = all(gate.status == "pass" for gate in gates)
    return ProgressionRolloutScorecard(
        rollout_mode="shadow-certified" if certified else "baseline-fallback",
        fallback_mode="baseline-snapshot",
        shadow_mode="projection-shadow",
        metrics=metrics,
        gates=gates,
        comparisons=comparisons,
        explanation_drift_cases=tuple(explanation_drift_cases),
        stop_conditions=_ROLLOUT_STOP_CONDITIONS,
    )


def default_progression_rollout_scorecard() -> ProgressionRolloutScorecard:
    now = datetime(2026, 4, 18, tzinfo=timezone.utc)
    active_work_item = SimpleNamespace(
        work_item_id="state-focus-release",
        title="Recover the blocked release lane",
        status="blocked",
        priority="high",
    )
    meaningful_state = _certification_base_growth_state(
        "profile-rollout-meaningful", now=now, dialogues=5, experiences=3
    )
    trivial_state_a = _certification_base_growth_state("profile-rollout-trivial-a", now=now, dialogues=5, experiences=2)
    trivial_state_b = _certification_base_growth_state("profile-rollout-trivial-b", now=now, dialogues=7, experiences=2)
    cases = (
        ProgressionReplayCase(
            case_id="meaningful-a",
            label="resume release blocker",
            difficulty_band="medium",
            pattern_family="resume-release",
            classification="meaningful",
            initial_state=meaningful_state,
            profile_id="profile-rollout-meaningful",
            signals=_meaningful_rollout_signals("profile-rollout-meaningful", session_id="session-release-a", now=now),
            experiences=(
                ExperienceRecord(
                    experience_id="experience:resume-a",
                    episode_id="session-release-a",
                    personal_model_id="profile-rollout-meaningful",
                    elephant_id="elephant-release",
                    kind="execution",
                    title="Recovered the release blocker",
                    summary="Validated the patch and preserved continuity after a wake.",
                    status="captured",
                    related_skill_ids=("skill.checks",),
                    produced_artifact_ids=("artifact:patch-note",),
                    tags=("resume", "continuity"),
                ),
            ),
            procedures=(
                ProcedureRecord(
                    procedure_id="procedure:resume-checklist",
                    title="Resume Checklist",
                    summary="Carry a resumed blocker lane through validation.",
                    status="verified",
                    skill_id="skill.checks",
                ),
            ),
            active_work_item=active_work_item,
            continuity_mode="background",
            wake_action="recover the blocked release lane",
        ),
        ProgressionReplayCase(
            case_id="meaningful-b",
            label="resume release blocker again",
            difficulty_band="medium",
            pattern_family="resume-release",
            classification="meaningful",
            initial_state=replace(meaningful_state, growth_score=meaningful_state.growth_score + 10),
            profile_id="profile-rollout-meaningful",
            signals=_meaningful_rollout_signals(
                "profile-rollout-meaningful",
                session_id="session-release-b",
                now=now + timedelta(hours=2),
            ),
            experiences=(
                ExperienceRecord(
                    experience_id="experience:resume-b",
                    episode_id="session-release-b",
                    personal_model_id="profile-rollout-meaningful",
                    elephant_id="elephant-release",
                    kind="execution",
                    title="Recovered the release blocker again",
                    summary="Validated the blocker chain with reusable proof.",
                    status="captured",
                    related_skill_ids=("skill.checks",),
                    produced_artifact_ids=("artifact:release-proof",),
                    tags=("resume", "continuity"),
                ),
            ),
            procedures=(
                ProcedureRecord(
                    procedure_id="procedure:resume-checklist",
                    title="Resume Checklist",
                    summary="Carry a resumed blocker lane through validation.",
                    status="verified",
                    skill_id="skill.checks",
                ),
            ),
            active_work_item=active_work_item,
            continuity_mode="background",
            wake_action="recover the blocked release lane",
        ),
        ProgressionReplayCase(
            case_id="trivial-a",
            label="flat status reflection",
            difficulty_band="medium",
            pattern_family="status-reflection",
            classification="trivial",
            initial_state=trivial_state_a,
            profile_id="profile-rollout-trivial-a",
            signals=GrowthTurnSignals(
                session_id="session-flat-a",
                profile_id="profile-rollout-trivial-a",
                total_tokens=7_200,
                occurred_at=now,
                execution_outcome="ok",
                elapsed_since_last_turn_seconds=24 * 60 * 60,
            ),
        ),
        ProgressionReplayCase(
            case_id="trivial-b",
            label="flat status reflection repeat",
            difficulty_band="medium",
            pattern_family="status-reflection",
            classification="trivial",
            initial_state=trivial_state_b,
            profile_id="profile-rollout-trivial-b",
            signals=GrowthTurnSignals(
                session_id="session-flat-b",
                profile_id="profile-rollout-trivial-b",
                total_tokens=7_800,
                occurred_at=now + timedelta(hours=2),
                execution_outcome="ok",
                elapsed_since_last_turn_seconds=18 * 60 * 60,
            ),
        ),
    )
    return build_progression_rollout_scorecard(
        cases,
        surface_audit=ProgressionSurfaceAudit(
            progression_lines=7,
            current_focus_lines=6,
            next_move_lines=5,
            recall_reason_lines=3,
            explanation_lines=2,
            note="Current shell keeps progression as one compact block ahead of a larger continuity context block.",
        ),
    )


def _fairness_margin_for(comparisons: tuple[ProgressionShadowComparison, ...]) -> float:
    margins: list[float] = []
    difficulty_bands = {comparison.difficulty_band for comparison in comparisons}
    for band in difficulty_bands:
        meaningful = [
            comparison.delta_score
            for comparison in comparisons
            if comparison.difficulty_band == band and comparison.classification == "meaningful"
        ]
        trivial = [
            comparison.delta_score
            for comparison in comparisons
            if comparison.difficulty_band == band and comparison.classification == "trivial"
        ]
        if meaningful and trivial:
            margins.append(_mean(meaningful) - _mean(trivial))
    if not margins:
        return 0.0
    return min(margins)


def _worst_variance_for(comparisons: tuple[ProgressionShadowComparison, ...]) -> int:
    variances: list[int] = []
    pattern_families = {comparison.pattern_family for comparison in comparisons}
    for family in pattern_families:
        family_scores = [comparison.delta_score for comparison in comparisons if comparison.pattern_family == family]
        if len(family_scores) >= 2:
            variances.append(max(family_scores) - min(family_scores))
    if not variances:
        return 0
    return max(variances)


def _minimum_motivation_delta_for(
    comparisons: tuple[ProgressionShadowComparison, ...],
) -> int:
    non_trivial = [comparison.delta_score for comparison in comparisons if comparison.classification != "trivial"]
    if not non_trivial:
        return 0
    return min(non_trivial)


def _explanation_drift_cases_for(
    comparisons: tuple[ProgressionShadowComparison, ...],
) -> list[str]:
    drifted: list[str] = []
    pattern_families = {comparison.pattern_family for comparison in comparisons}
    for family in pattern_families:
        family_comparisons = [comparison for comparison in comparisons if comparison.pattern_family == family]
        if len(family_comparisons) < 2:
            continue
        lead_labels = {_lead_explanation_label(comparison) for comparison in family_comparisons}
        if len(lead_labels) > 1:
            drifted.append(family)
    return sorted(drifted)


def _lead_explanation_label(comparison: ProgressionShadowComparison) -> str:
    ranked = sorted(
        (reason for reason in comparison.reward_reasons if reason.score > 0),
        key=lambda item: (-item.score, item.reason_id),
    )
    if ranked:
        return ranked[0].label
    return comparison.explanation_labels[0] if comparison.explanation_labels else "none"


def _mean(values: list[int]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _certification_base_growth_state(
    profile_id: str,
    *,
    now: datetime,
    dialogues: int,
    experiences: int,
) -> PersonalModelGrowthState:
    return PersonalModelGrowthState(
        profile_id=profile_id,
        growth_score=180,
        total_dialogues=dialogues,
        total_tokens=1_400,
        total_experiences=experiences,
        active_days=3,
        streak_days=2,
        first_dialogue_at=now - timedelta(days=6),
        last_dialogue_at=now - timedelta(days=1),
        last_active_day=(now - timedelta(days=1)).date().isoformat(),
        created_at=now - timedelta(days=6),
        updated_at=now - timedelta(days=1),
    )


def _meaningful_rollout_signals(profile_id: str, *, session_id: str, now: datetime) -> GrowthTurnSignals:
    return GrowthTurnSignals(
        session_id=session_id,
        profile_id=profile_id,
        total_tokens=640,
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
        work_item_evidence_refs=("artifact:blocker", "artifact:patch-note"),
        replay_evidence_refs=("memory:resume-proof",),
        skill_ids=("skill.checks",),
        artifact_ids=("artifact:patch-note",),
        promoted_procedure_ids=("procedure:resume-checklist",),
        personal_model_fact_count=8,
        personal_model_lens_counts=(
            ("identity", 2),
            ("world", 2),
            ("pulse", 2),
            ("journey", 2),
        ),
        personal_model_topic_count=6,
        personal_model_new_fact_count=2,
        personal_model_updated_fact_count=1,
        personal_model_supported_fact_count=8,
        personal_model_evidence_ref_count=10,
        personal_model_high_confidence_fact_count=5,
        personal_model_rich_fact_count=4,
        personal_model_average_confidence=0.84,
        elapsed_since_last_turn_seconds=3 * 24 * 60 * 60,
    )
