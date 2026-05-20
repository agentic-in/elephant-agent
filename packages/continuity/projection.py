"""Continuity projections built on canonical personal-AI state."""

from __future__ import annotations

from dataclasses import dataclass

from packages.contracts import Episode
from packages.contracts.runtime import (
    ElephantIdentityRecord,
    EpisodeContinuityState,
)
from packages.state.rendered_views import RenderedRelationshipView
from packages.state import CompanionGovernanceState, LoadedProfile, build_companion_governance_state
from .runtime import (
    RelationshipPolicy,
    build_relationship_policy,
    build_episode_continuity_state,
)


@dataclass(frozen=True, slots=True)
class ContinuityProjection:
    governance: CompanionGovernanceState
    continuity: EpisodeContinuityState
    relationship_policy: RelationshipPolicy
    initiative: str
    reengagement_style: str
    reengagement_prompt: str
    user_governed: bool
    voice_identity_binding: str
    summary: str


@dataclass(frozen=True, slots=True)
class ContinuityProjectionService:
    def inspect(
        self,
        profile: LoadedProfile,
        session: Episode,
        *,
        lineage: tuple[Episode, ...] = (),
        active_state_focus: str | None = None,
        identity_record: ElephantIdentityRecord | None = None,
        relationship_record: RenderedRelationshipView | None = None,
    ) -> ContinuityProjection:
        del identity_record
        governance = build_companion_governance_state(profile)
        continuity = build_episode_continuity_state(
            session,
            lineage=lineage,
        )
        companion = profile.companion
        relationship_policy = build_relationship_policy(
            profile.state.mode,
            text_first=companion.text_first if companion is not None else True,
            preserve_relationship_timeline=(
                companion.preserve_relationship_timeline if companion is not None else True
            ),
            preserve_preferences=companion.preserve_preferences if companion is not None else True,
            preserve_corrections=companion.preserve_corrections if companion is not None else True,
            preserve_emotional_context=(
                companion.preserve_emotional_context if companion is not None else True
            ),
        )
        continuity_notes = (
            relationship_record.continuity_notes
            if relationship_record is not None
            else governance.identity.continuity_notes
        )
        prompt, style = _reengagement_prompt(
            continuity=continuity,
            continuity_notes=continuity_notes,
            active_state_focus=active_state_focus,
        )
        return ContinuityProjection(
            governance=governance,
            continuity=continuity,
            relationship_policy=relationship_policy,
            initiative="",
            reengagement_style=style,
            reengagement_prompt=prompt,
            user_governed=True,
            voice_identity_binding="voice remains subordinate to the same text-first identity path",
            summary=_continuity_summary(
                continuity=continuity,
                relationship_policy=relationship_policy,
                onboarding_ready=governance.onboarding.ready,
                reengagement_style=style,
            ),
        )


def _reengagement_prompt(
    *,
    continuity: EpisodeContinuityState,
    continuity_notes: tuple[str, ...],
    active_state_focus: str | None,
) -> tuple[str, str]:
    note_text = ", ".join(continuity_notes) if continuity_notes else "preserve the active elephant without overreaching"
    focus_clause = f" keep active elephant focus visible: {active_state_focus}." if active_state_focus else ""
    style = "steady-follow-through"
    prompt = (
        f"Preserve continuity explicitly and keep the next step legible; "
        f"continuity cues: {note_text}.{focus_clause}"
    )
    return prompt, style


def _continuity_summary(
    *,
    continuity: EpisodeContinuityState,
    relationship_policy: RelationshipPolicy,
    onboarding_ready: bool,
    reengagement_style: str,
) -> str:
    onboarding = "identity-ready" if onboarding_ready else "onboarding-pending"
    return (
        f"{continuity.summary}; reengagement={reengagement_style}; "
        f"{onboarding}; relationship_policy={relationship_policy.summary()}"
    )
