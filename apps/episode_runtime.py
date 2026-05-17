"""App-local Episode lifecycle helpers backed by canonical system-layer rows."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from uuid import uuid4

from packages.contracts.layers import Episode
from packages.continuity import (
    RelationshipPolicy,
    apply_episode_continuity_state,
    build_episode_continuity_state,
    build_relationship_policy,
)
from packages.contracts.runtime import (
    EpisodeContinuityState,
    PersonalModelRuntimeState,
)
from packages.kernel.episode_state_machine import EpisodeTransition, open_next_episode
from packages.storage import RuntimeStorageRepository


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class EpisodeLifecycleService:
    """App-local Episode lifecycle behavior on top of durable storage."""

    repository: RuntimeStorageRepository

    def _resolve_state_id(self, personal_model_id: str, elephant_id: str | None) -> str:
        """Find or create a State row and return its state_id."""
        if elephant_id:
            for state in self.repository.list_states(status="active"):
                if state.elephant_id == elephant_id:
                    return state.state_id
            # Create a new state for this elephant
            state = self.repository.create_state(
                personal_model_id=personal_model_id,
                elephant_id=elephant_id,
                elephant_name=elephant_id.replace("-", " ").title(),
                state_id=f"state:{elephant_id}",
                state_anchor=f"elephant:{elephant_id}",
                surface_bindings=("runtime",),
                metadata={"source": "episode_runtime"},
            )
            return state.state_id
        current = self.repository.current_state()
        if current is not None and current.personal_model_id == personal_model_id:
            return current.state_id
        default_id = f"state:{personal_model_id}:default"
        existing = self.repository.load_state(default_id)
        if existing is not None:
            return existing.state_id
        state = self.repository.create_state(
            personal_model_id=personal_model_id,
            elephant_id="",
            elephant_name=personal_model_id,
            state_id=default_id,
            state_anchor=f"personal-model:{personal_model_id}:default",
            surface_bindings=("runtime",),
            metadata={"source": "episode_runtime"},
        )
        return state.state_id

    def start_episode(
        self,
        profile: PersonalModelRuntimeState,
        *,
        elephant_id: str | None = None,
        episode_id: str | None = None,
        started_at: datetime | None = None,
    ) -> Episode:
        timestamp = started_at or _utc_now()
        state_id = self._resolve_state_id(profile.profile_id, elephant_id)
        episode = Episode(
            episode_id=episode_id or uuid4().hex,
            state_id=state_id,
            personal_model_id=profile.profile_id,
            entry_surface="cli",
            status="open",
            started_at=timestamp,
            updated_at=timestamp,
            elephant_id=elephant_id or "",
        )
        self.repository.upsert_personal_model_runtime_state(profile, updated_at=timestamp)
        self.repository.upsert_episode(episode)
        return episode

    def interrupt_episode(
        self,
        episode_id: str,
        *,
        interruption_state: str,
        interrupted_at: datetime | None = None,
    ) -> Episode:
        timestamp = interrupted_at or _utc_now()
        episode = self.repository.load_episode(episode_id)
        if episode is None:
            raise KeyError(episode_id)
        updated = replace(
            episode,
            status="paused",
            updated_at=timestamp,
            interruption_state=interruption_state,
        )
        self.repository.upsert_episode(updated)
        return updated

    def open_next_episode(
        self,
        episode_id: str,
        *,
        opened_at: datetime | None = None,
        child_episode_id: str | None = None,
        reason: str = "next_episode",
        summary: str = "",
    ) -> EpisodeTransition:
        return open_next_episode(
            self.repository,
            episode_id,
            reason=reason,
            summary=summary,
            current=opened_at or _utc_now(),
            episode_id=child_episode_id,
        )

    def episode_lineage(self, episode_id: str) -> tuple[Episode, ...]:
        return self.repository.episode_lineage(episode_id)

    def continuity_state(
        self,
        episode: Episode,
        *,
        lineage: tuple[Episode, ...] = (),
    ) -> EpisodeContinuityState:
        return build_episode_continuity_state(episode, lineage=lineage)

    def apply_continuity_state(
        self,
        episode: Episode,
        continuity: EpisodeContinuityState,
    ) -> Episode:
        return apply_episode_continuity_state(episode, continuity)

    def relationship_projection_policy(
        self,
        profile_mode: str,
        *,
        text_first: bool = True,
        preserve_relationship_timeline: bool = True,
        preserve_preferences: bool = True,
        preserve_corrections: bool = True,
        preserve_emotional_context: bool = True,
        allowed_signal_kinds: tuple[str, ...] = ("relationship", "preference", "continuity"),
    ) -> RelationshipPolicy:
        return build_relationship_policy(
            profile_mode=profile_mode,
            text_first=text_first,
            preserve_relationship_timeline=preserve_relationship_timeline,
            preserve_preferences=preserve_preferences,
            preserve_corrections=preserve_corrections,
            preserve_emotional_context=preserve_emotional_context,
            allowed_signal_kinds=allowed_signal_kinds,
        )


def install_app_episode_runtime(repository: RuntimeStorageRepository) -> EpisodeLifecycleService:
    """Build the app-owned Episode lifecycle service on top of repository methods."""

    return EpisodeLifecycleService(repository)


__all__ = [
    "EpisodeLifecycleService",
    "install_app_episode_runtime",
]
