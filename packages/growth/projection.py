"""Derived projection model for Personal Model learning read surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from packages.contracts.runtime import ExperienceRecord, ProcedureRecord, PersonalModelGrowthState

from .runtime import (
    GROWTH_STAGES,
    GrowthSnapshot,
    GrowthStageDescriptor,
    GrowthUpdate,
    _PROMOTED_PROCEDURE_STATUSES,
    _canonical_active_days,
    _contains_any,
    _curve_stage_id_for_level,
    _dedupe_text,
    _local_day,
    _round_to_five,
    _roman_numeral,
    _utc_now,
    unbounded_level_floor_score,
    unbounded_level_for_score,
    unbounded_xp_to_next_level,
)


@dataclass(frozen=True, slots=True)
class ProgressionMasterySignal:
    axis: str
    score: int
    summary: str


@dataclass(frozen=True, slots=True)
class ProgressionChallengeTrack:
    track_id: str
    label: str
    summary: str
    status: str = "active"


@dataclass(frozen=True, slots=True)
class ProgressionRewardSummary:
    label: str
    summary: str


@dataclass(frozen=True, slots=True)
class ProgressionProjection:
    profile_id: str
    understanding_checkpoint: int
    ring_index: int
    ring_level: int
    stage_title: str
    understanding_focus: str
    mastery_vector: tuple[ProgressionMasterySignal, ...]
    power_score: int
    progress_to_next_level: float
    score_to_next_level: int
    momentum_state: str
    active_challenge_tracks: tuple[ProgressionChallengeTrack, ...]
    recent_reward_reasons: tuple[ProgressionRewardSummary, ...]
    anti_grind_flags: tuple[str, ...]
    updated_at: datetime | None
    growth_state: PersonalModelGrowthState
    brand_stage_id: str
    next_milestone: str = ""
    lifetime_days: int = 0
    canonical_dialogues: int = 0
    canonical_experiences: int = 0
    canonical_promoted_procedures: int = 0
    canonical_active_days: int = 0
    level_floor_score: int = 0
    next_level_score: int = 0

    @property
    def cycle_label(self) -> str:
        return f"Evidence {_roman_numeral(self.ring_index)}"

    @property
    def identity_line(self) -> str:
        return f"{self.cycle_label} · {self.stage_title}"

    @property
    def level(self) -> int:
        return self.understanding_checkpoint

    @property
    def progress_ratio(self) -> float:
        return self.progress_to_next_level

    @property
    def progress_percent(self) -> int:
        return int(round(self.progress_to_next_level * 100))

    @property
    def state(self) -> PersonalModelGrowthState:
        return self.growth_state

    @property
    def stage(self) -> GrowthStageDescriptor:
        brand_stage = next(
            (descriptor for descriptor in GROWTH_STAGES if descriptor.stage_id == self.brand_stage_id),
            GROWTH_STAGES[-1],
        )
        return GrowthStageDescriptor(
            stage_id=brand_stage.stage_id,
            display_name=self.stage_title,
            title=self.stage_title,
            logo_asset=brand_stage.logo_asset,
            min_level=brand_stage.min_level,
            max_level=brand_stage.max_level,
        )


@dataclass(frozen=True, slots=True)
class ProgressionTransition:
    before: ProgressionProjection
    after: ProgressionProjection
    delta_score: int

    @property
    def leveled_up(self) -> bool:
        return self.after.level > self.before.level

    @property
    def stage_changed(self) -> bool:
        return self.after.stage_title != self.before.stage_title


@dataclass(frozen=True, slots=True)
class ProgressionProjectionBuilder:
    """Builds the derived learning read model from canonical owners."""

    def build(
        self,
        *,
        profile_id: str,
        state: PersonalModelGrowthState | None = None,
        experiences: tuple[ExperienceRecord, ...] = (),
        procedures: tuple[ProcedureRecord, ...] = (),
        active_work_item: object | None = None,
        continuity_mode: str = "foreground",
        wake_action: str = "",
        updated_at: datetime | None = None,
    ) -> ProgressionProjection:
        power_state = _projection_state_from_canonical(
            profile_id=profile_id,
            state=state,
            experiences=experiences,
            procedures=procedures,
            updated_at=updated_at,
        )
        experience_count = len(experiences) if experiences else max(0, power_state.total_experiences)
        power_score = max(0, power_state.growth_score)
        understanding_checkpoint = unbounded_level_for_score(power_score)
        floor_score = unbounded_level_floor_score(understanding_checkpoint)
        next_cost = unbounded_xp_to_next_level(understanding_checkpoint)
        next_level_score = floor_score + next_cost
        score_into_level = max(0, power_score - floor_score)
        progress_ratio = 1.0 if next_cost == 0 else min(1.0, score_into_level / next_cost)

        ring_index = max(1, (understanding_checkpoint // 10) + 1)
        ring_level = understanding_checkpoint % 10
        promoted_procedures = sum(
            1 for procedure in procedures if procedure.status.strip().lower() in _PROMOTED_PROCEDURE_STATUSES
        )
        skill_refs = {
            skill_id
            for experience in experiences
            for skill_id in experience.related_skill_ids
            if str(skill_id).strip()
        }
        skill_refs.update(
            procedure.skill_id
            for procedure in procedures
            if procedure.skill_id is not None and str(procedure.skill_id).strip()
        )
        artifact_count = sum(len(experience.produced_artifact_ids) for experience in experiences)
        continuity_recoveries = sum(
            1
            for experience in experiences
            if _contains_any(
                f"{experience.title} {experience.summary} {' '.join(experience.tags)}",
                ("resume", "recovery", "continuity", "interrupt"),
            )
        )
        continuity_bonus = 4 if continuity_mode.strip().lower() != "foreground" else 0
        mastery_vector = (
            ProgressionMasterySignal(
                axis="execution",
                score=min(12, (4 if active_work_item is not None else 0) + min(4, experience_count) + min(4, artifact_count)),
                summary=(
                    f"Current focus is {str(getattr(active_work_item, 'title', '') or '')}."
                    if active_work_item is not None
                    else "No active current-work item is currently anchored for this projection."
                ),
            ),
            ProgressionMasterySignal(
                axis="continuity",
                score=min(12, continuity_bonus + min(4, continuity_recoveries) + min(4, power_state.streak_days)),
                summary=(
                    "Recovery context is active and the thread is being carried forward."
                    if continuity_mode.strip().lower() != "foreground"
                    else "Continuity is steady in the foreground thread."
                ),
            ),
            ProgressionMasterySignal(
                axis="learning",
                score=min(12, min(4, experience_count) + (promoted_procedures * 3)),
                summary=f"{experience_count} durable experience(s) and {promoted_procedures} promoted procedure(s) back the profile.",
            ),
            ProgressionMasterySignal(
                axis="capability",
                score=min(12, len(skill_refs) * 2 + min(4, promoted_procedures)),
                summary=(
                    f"{len(skill_refs)} reusable capability link(s) are attached to evidence or procedures."
                    if skill_refs
                    else "No reusable capability links have been promoted yet."
                ),
            ),
            ProgressionMasterySignal(
                axis="resilience",
                score=min(
                    12,
                    continuity_bonus
                    + (3 if power_state.streak_days >= 3 else max(0, power_state.streak_days - 1))
                    + (2 if active_work_item is not None and continuity_mode.strip().lower() != "foreground" else 0),
                ),
                summary=(
                    "The profile is recovering and compounding through durable return cadence."
                    if continuity_mode.strip().lower() != "foreground"
                    else "Resilience is currently driven by active-day return cadence."
                ),
            ),
        )
        understanding_focus = max(mastery_vector, key=lambda item: (item.score, item.axis)).axis
        understanding_rank = _understanding_rank(
            experience_count=experience_count,
            promoted_procedures=promoted_procedures,
            skill_link_count=len(skill_refs),
            active_work_item=active_work_item,
            continuity_mode=continuity_mode,
            continuity_recoveries=continuity_recoveries,
        )
        stage_title = _understanding_label_for(rank=understanding_rank)
        momentum_state = _momentum_state_for(power_state, continuity_mode=continuity_mode)
        challenges = _active_challenge_tracks(
            active_work_item=active_work_item,
            promoted_procedures=promoted_procedures,
            continuity_mode=continuity_mode,
            wake_action=wake_action,
            streak_days=power_state.streak_days,
        )
        reward_reasons = _recent_reward_summaries(
            active_work_item=active_work_item,
            continuity_mode=continuity_mode,
            experience_count=experience_count,
            promoted_procedures=promoted_procedures,
            skill_link_count=len(skill_refs),
        )
        anti_grind_flags = _anti_grind_flags(
            state=power_state,
            experience_count=experience_count,
            promoted_procedures=promoted_procedures,
            artifact_count=artifact_count,
        )

        return ProgressionProjection(
            profile_id=profile_id,
            understanding_checkpoint=understanding_checkpoint,
            ring_index=ring_index,
            ring_level=ring_level,
            stage_title=stage_title,
            understanding_focus=understanding_focus,
            mastery_vector=mastery_vector,
            power_score=power_score,
            progress_to_next_level=progress_ratio,
            score_to_next_level=max(0, next_cost - score_into_level),
            momentum_state=momentum_state,
            active_challenge_tracks=challenges,
            recent_reward_reasons=reward_reasons,
            anti_grind_flags=anti_grind_flags,
            updated_at=power_state.updated_at,
            growth_state=power_state,
            brand_stage_id=_brand_stage_id_for_level(understanding_checkpoint),
            next_milestone=_next_milestone_summary(
                understanding_checkpoint=understanding_checkpoint,
                score_to_next_level=max(0, next_cost - score_into_level),
            ),
            lifetime_days=_lifetime_days_for(power_state),
            canonical_dialogues=power_state.total_dialogues,
            canonical_experiences=experience_count,
            canonical_promoted_procedures=promoted_procedures,
            canonical_active_days=power_state.active_days,
            level_floor_score=floor_score,
            next_level_score=next_level_score,
        )

    def transition(
        self,
        update: GrowthUpdate,
        *,
        profile_id: str,
        experiences: tuple[ExperienceRecord, ...] = (),
        procedures: tuple[ProcedureRecord, ...] = (),
        active_work_item: object | None = None,
        continuity_mode: str = "foreground",
        wake_action: str = "",
        updated_at: datetime | None = None,
    ) -> ProgressionTransition:
        before = self.build(
            profile_id=profile_id,
            state=update.before.state,
            experiences=experiences,
            procedures=procedures,
            active_work_item=active_work_item,
            continuity_mode=continuity_mode,
            wake_action=wake_action,
            updated_at=updated_at,
        )
        after = self.build(
            profile_id=profile_id,
            state=update.after.state,
            experiences=experiences,
            procedures=procedures,
            active_work_item=active_work_item,
            continuity_mode=continuity_mode,
            wake_action=wake_action,
            updated_at=updated_at,
        )
        return ProgressionTransition(before=before, after=after, delta_score=update.delta_score)


def _brand_stage_id_for_level(level: int) -> str:
    curve_stage_id = _curve_stage_id_for_level(level)
    return "elephant" if curve_stage_id == "elephant_agent" else curve_stage_id


def _projection_state_from_canonical(
    *,
    profile_id: str,
    state: PersonalModelGrowthState | None,
    experiences: tuple[ExperienceRecord, ...],
    procedures: tuple[ProcedureRecord, ...],
    updated_at: datetime | None = None,
) -> PersonalModelGrowthState:
    promoted_procedures = sum(
        1 for procedure in procedures if procedure.status.strip().lower() in _PROMOTED_PROCEDURE_STATUSES
    )
    fallback_updated_at = updated_at or state.updated_at if state is not None else updated_at
    first_moment = min(
        (
            moment
            for experience in experiences
            for moment in (experience.created_at, experience.updated_at)
            if moment is not None
        ),
        default=(state.first_dialogue_at if state is not None else None) or _utc_now(),
    )
    last_moment = max(
        (
            moment
            for experience in experiences
            for moment in (experience.updated_at, experience.created_at)
            if moment is not None
        ),
        default=(state.last_dialogue_at if state is not None else None) or first_moment,
    )
    experience_count = len(experiences) if experiences else (state.total_experiences if state is not None else 0)
    canonical_active_days = _canonical_active_days(experiences) if experiences else (state.active_days if state is not None else 0)
    if state is not None:
        power_score = max(0, state.growth_score)
        total_dialogues = max(state.total_dialogues, experience_count)
        total_tokens = state.total_tokens
        streak_days = state.streak_days
    else:
        power_score = _round_to_five(
            (experience_count * 40)
            + (promoted_procedures * 80)
            + min(30, sum(len(experience.related_skill_ids) for experience in experiences) * 10)
        )
        total_dialogues = experience_count
        total_tokens = sum(max(0, len(experience.summary) + len(experience.title)) for experience in experiences)
        streak_days = min(max(1, canonical_active_days), 7) if experience_count else 0
    return PersonalModelGrowthState(
        profile_id=profile_id,
        growth_score=power_score,
        total_dialogues=total_dialogues,
        total_tokens=total_tokens,
        total_experiences=experience_count,
        promoted_experiences=promoted_procedures,
        active_days=max(canonical_active_days, state.active_days if state is not None else 0),
        streak_days=streak_days,
        first_dialogue_at=state.first_dialogue_at if state is not None and state.first_dialogue_at is not None else first_moment,
        last_dialogue_at=state.last_dialogue_at if state is not None and state.last_dialogue_at is not None else last_moment,
        last_active_day=(state.last_active_day if state is not None and state.last_active_day is not None else _local_day(last_moment).isoformat()),
        created_at=state.created_at if state is not None and state.created_at is not None else first_moment,
        updated_at=fallback_updated_at or last_moment,
    )


def _lifetime_days_for(state: PersonalModelGrowthState) -> int:
    if state.first_dialogue_at is None or state.last_dialogue_at is None:
        return 0
    return max(1, (_local_day(state.last_dialogue_at) - _local_day(state.first_dialogue_at)).days + 1)


def _understanding_rank(
    *,
    experience_count: int,
    promoted_procedures: int,
    skill_link_count: int,
    active_work_item: object | None,
    continuity_mode: str,
    continuity_recoveries: int,
) -> int:
    rank = 0
    if experience_count >= 1 or active_work_item is not None or continuity_mode.strip().lower() != "foreground":
        rank = 1
    if promoted_procedures >= 1:
        rank = 2
    if promoted_procedures >= 2 or skill_link_count >= 2 or continuity_recoveries >= 2:
        rank = 3
    if promoted_procedures >= 3 or (skill_link_count >= 3 and continuity_recoveries >= 1):
        rank = 4
    if promoted_procedures >= 5:
        rank = 5
    return rank


_UNDERSTANDING_LABELS = (
    "learning the path",
    "carrying the path",
    "grounded in evidence",
    "clearer with context",
    "correctable understanding",
    "durable understanding",
)


def _understanding_label_for(*, rank: int) -> str:
    clamped = max(0, min(rank, len(_UNDERSTANDING_LABELS) - 1))
    return _UNDERSTANDING_LABELS[clamped]


def _momentum_state_for(state: PersonalModelGrowthState, *, continuity_mode: str) -> str:
    if continuity_mode.strip().lower() != "foreground":
        return "recovered"
    if state.streak_days >= 5:
        return "compounding"
    if state.streak_days >= 2:
        return "steady"
    if state.total_dialogues > 0:
        return "steadying"
    return "idle"


def _active_challenge_tracks(
    *,
    active_work_item: object | None,
    promoted_procedures: int,
    continuity_mode: str,
    wake_action: str,
    streak_days: int,
) -> tuple[ProgressionChallengeTrack, ...]:
    tracks: list[ProgressionChallengeTrack] = []
    if active_work_item is not None:
        tracks.append(
            ProgressionChallengeTrack(
                track_id="current-focus",
                label="Keep the current focus visible",
                summary=str(getattr(active_work_item, 'title', '') or ''),
                status="active",
            )
        )
    if promoted_procedures <= 0:
        tracks.append(
            ProgressionChallengeTrack(
                track_id="reusable-learning",
                label="Save one reusable pattern",
                summary="Promote one reusable procedure so future turns can carry more than the transcript.",
                status="open",
            )
        )
    if continuity_mode.strip().lower() != "foreground":
        tracks.append(
            ProgressionChallengeTrack(
                track_id="recovery-chain",
                label="Carry the next path",
                summary=f"Keep {wake_action or 'the next lane'} connected to the Personal Model.",
                status="active",
            )
        )
    elif streak_days < 2:
        tracks.append(
            ProgressionChallengeTrack(
                track_id="return-cadence",
                label="Return once more",
                summary="Wake the same path again so the elephant can keep the current context warm.",
                status="steady",
            )
        )
    return tuple(tracks[:3])


def _recent_reward_summaries(
    *,
    active_work_item: object | None,
    continuity_mode: str,
    experience_count: int,
    promoted_procedures: int,
    skill_link_count: int,
) -> tuple[ProgressionRewardSummary, ...]:
    reasons: list[ProgressionRewardSummary] = []
    if active_work_item is not None:
        reasons.append(
            ProgressionRewardSummary(
                label="Work depth",
                summary=f"Current work is still anchored to {str(getattr(active_work_item, 'title', '') or '')}.",
            )
        )
    if promoted_procedures:
        reasons.append(
            ProgressionRewardSummary(
                label="Learning yield",
                summary=f"{promoted_procedures} promoted procedure(s) now make the learning reusable.",
            )
        )
    elif experience_count:
        reasons.append(
            ProgressionRewardSummary(
                label="Evidence yield",
                summary=f"{experience_count} durable experience(s) back the current understanding.",
            )
        )
    if continuity_mode.strip().lower() != "foreground":
        reasons.append(
            ProgressionRewardSummary(
                label="Continuity quality",
                summary="Background recovery is active, so the path can stay connected between sessions.",
            )
        )
    if skill_link_count:
        reasons.append(
            ProgressionRewardSummary(
                label="Capability leverage",
                summary=f"{skill_link_count} skill-linked capability path(s) are now reusable.",
            )
        )
    if not reasons:
        reasons.append(
            ProgressionRewardSummary(
                label="Momentum",
                summary="The Personal Model is still early; durable evidence has not accumulated yet.",
            )
        )
    return tuple(reasons[:3])


def _anti_grind_flags(
    *,
    state: PersonalModelGrowthState,
    experience_count: int,
    promoted_procedures: int,
    artifact_count: int,
) -> tuple[str, ...]:
    flags: list[str] = []
    if state.total_dialogues >= 4 and experience_count <= 1:
        flags.append("low-evidence-yield")
    if state.total_tokens >= 6_000 and promoted_procedures == 0:
        flags.append("token-heavy")
    if experience_count >= 4 and artifact_count == 0 and promoted_procedures == 0:
        flags.append("reusable-proof-gap")
    return tuple(flags)


def _next_milestone_summary(
    *,
    understanding_checkpoint: int,
    score_to_next_level: int,
) -> str:
    return f"{score_to_next_level} understanding signal until checkpoint {understanding_checkpoint + 1}."
