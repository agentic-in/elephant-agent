"""Growth and learning surface helpers for the CLI runtime."""

from __future__ import annotations

from packages.contracts.runtime import ExperienceRecord
from packages.growth import (
    GrowthUpdate,
    ProgressionProjection,
    ProgressionProjectionBuilder,
    ProgressionTransition,
)

_PROGRESSION_BUILDER = ProgressionProjectionBuilder()


def inspect_experiences(
    runtime,
    *,
    session_id: str | None = None,
    profile_id: str | None = None,
    statuses: tuple[str, ...] = (),
    limit: int | None = None,
) -> tuple[ExperienceRecord, ...]:
    """Return experience records. Procedural memory has been removed; returns empty."""
    return ()


def inspect_growth(runtime, *, session_id: str | None = None, profile_id: str | None = None) -> ProgressionProjection:
    resolved_profile_id = profile_id
    continuity_mode = "foreground"
    wake_action = ""
    resolved_session = None
    if resolved_profile_id is None:
        if session_id is None:
            raise ValueError("inspect_growth requires session_id or profile_id")
        resolved_session = runtime.inspect_session(session_id)
        resolved_profile_id = resolved_session.personal_model_id
    if session_id is not None:
        continuity = runtime.inspect_continuity(session_id=session_id)
        resolved_session = resolved_session or runtime.inspect_session(session_id)
        continuity_mode = "background" if resolved_session.parent_episode_id is not None else "foreground"
        wake_action = continuity.wake_action
    state = runtime.repository.load_personal_model_growth(resolved_profile_id)
    return _PROGRESSION_BUILDER.build(
        profile_id=resolved_profile_id,
        state=state,
        experiences=(),
        procedures=(),
        active_work_item=None,
        continuity_mode=continuity_mode,
        wake_action=wake_action,
    )


def inspect_growth_transition(runtime, update: GrowthUpdate, *, session_id: str) -> ProgressionTransition:
    session = runtime.inspect_session(session_id)
    continuity = runtime.inspect_continuity(session_id=session_id)
    return _PROGRESSION_BUILDER.transition(
        update,
        profile_id=session.personal_model_id,
        experiences=(),
        procedures=(),
        active_work_item=None,
        continuity_mode="background" if session.parent_episode_id is not None else "foreground",
        wake_action=continuity.wake_action,
    )
