"""Canonical personal-state and continuity services for the API surface."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import re
from typing import Any, cast

from packages.continuity import ContinuityProjection, ContinuityProjectionService
from packages.contracts import ElephantIdentityRecord, Episode, Fact
from packages.state.rendered_views import RenderedRelationshipView, RenderedUserProfileView
from packages.contracts.runtime import PersonalModelRuntimeState
from packages.evidence.recall_runtime import RecallRuntime
from packages.state import user_profile_updates
from packages.state.canonical import build_canonical_profile_state
from packages.state.persistence import (
    load_persisted_canonical_state,
    resolve_runtime_state,
    sync_canonical_profile_state,
)
from packages.state.projection import build_loaded_profile_from_state, render_user_profile_projection_text
from packages.state.user_updates import apply_user_profile_update
from packages.storage import RuntimeStorageRepository
from packages.storage.repository_support import canonical_personal_model_id


@dataclass(frozen=True, slots=True)
class APIContinuityInspection:
    personal_model: PersonalModelRuntimeState
    state: Any
    episode: Episode
    identity: ElephantIdentityRecord
    user: RenderedUserProfileView
    relationship: RenderedRelationshipView
    continuity: ContinuityProjection
    wake_action: str
    wake_summary: str
    wake_factors: tuple[str, ...]

    def to_record(self) -> dict[str, Any]:
        return {
            "personal_model": self.personal_model,
            "state": self.state,
            "episode": self.episode,
            "identity": self.identity,
            "user": self.user,
            "relationship": self.relationship,
            "continuity": self.continuity,
            "wake_action": self.wake_action,
            "wake_summary": self.wake_summary,
            "wake_factors": self.wake_factors,
        }


@dataclass(frozen=True, slots=True)
class _CanonicalStateRecords:
    identity: ElephantIdentityRecord
    user: RenderedUserProfileView
    relationship: RenderedRelationshipView


@dataclass(frozen=True, slots=True)
class APIStateService:
    repository: RuntimeStorageRepository
    recall_runtime: RecallRuntime

    def ensure_personal_model_state(
        self,
        personal_model: PersonalModelRuntimeState,
        *,
        elephant_id: str | None = None,
        state_id: str | None = None,
        episode_id: str | None = None,
        sync_source: str = "api.bootstrap",
    ) -> _CanonicalStateRecords:
        canonical_personal_model = replace(
            personal_model,
            profile_id=canonical_personal_model_id(personal_model.profile_id),
        )
        resolved_state = resolve_runtime_state(
            self.repository,
            state_id=state_id,
            episode_id=episode_id,
            personal_model_id=canonical_personal_model.profile_id,
            elephant_id=elephant_id,
            required=False,
        )
        resolved_elephant_id = elephant_id or (resolved_state.elephant_id if resolved_state is not None and resolved_state.elephant_id else None)
        persisted = load_persisted_canonical_state(self.repository, canonical_personal_model.profile_id)
        if (
            persisted.elephant_identity is not None
            and persisted.user_profile is not None
            and persisted.relationship is not None
        ):
            return _CanonicalStateRecords(
                identity=cast(ElephantIdentityRecord, persisted.elephant_identity),
                user=cast(RenderedUserProfileView, persisted.user_profile),
                relationship=cast(RenderedRelationshipView, persisted.relationship),
            )
        bundle = build_canonical_profile_state(
            build_loaded_profile_from_state(canonical_personal_model),
            elephant_id=resolved_elephant_id,
        )
        synced = sync_canonical_profile_state(
            self.repository,
            bundle,
            previous=persisted,
            sync_source=sync_source,
            recall_runtime=self.recall_runtime,
            surface="api",
            state_id=resolved_state.state_id if resolved_state is not None else state_id,
            episode_id=episode_id,
        )
        return _CanonicalStateRecords(
            identity=cast(ElephantIdentityRecord, synced.elephant_identity),
            user=cast(RenderedUserProfileView, synced.user_profile),
            relationship=cast(RenderedRelationshipView, synced.relationship),
        )

    def inspect_identity(
        self,
        *,
        state_id: str | None = None,
        episode_id: str | None = None,
        personal_model_id: str | None = None,
    ) -> ElephantIdentityRecord:
        personal_model = self._resolve_personal_model(
            state_id=state_id,
            episode_id=episode_id,
            personal_model_id=personal_model_id,
        )
        return self.ensure_personal_model_state(personal_model, state_id=state_id).identity

    def inspect_user(
        self,
        *,
        state_id: str | None = None,
        episode_id: str | None = None,
        personal_model_id: str | None = None,
    ) -> RenderedUserProfileView:
        personal_model = self._resolve_personal_model(
            state_id=state_id,
            episode_id=episode_id,
            personal_model_id=personal_model_id,
        )
        return self.ensure_personal_model_state(personal_model, state_id=state_id, episode_id=episode_id).user

    def inspect_relationship(
        self,
        *,
        state_id: str | None = None,
        episode_id: str | None = None,
        personal_model_id: str | None = None,
    ) -> RenderedRelationshipView:
        personal_model = self._resolve_personal_model(
            state_id=state_id,
            episode_id=episode_id,
            personal_model_id=personal_model_id,
        )
        return self.ensure_personal_model_state(personal_model, state_id=state_id, episode_id=episode_id).relationship

    def update_identity_state(
        self,
        *,
        state_id: str | None = None,
        episode_id: str | None = None,
        personal_model_id: str | None = None,
        display_name: str | None = None,
        elephant_identity_text: str | None = None,
        clear_elephant_identity: bool = False,
    ) -> ElephantIdentityRecord:
        personal_model = self._resolve_personal_model(
            state_id=state_id,
            episode_id=episode_id,
            personal_model_id=personal_model_id,
        )
        resolved_state = resolve_runtime_state(
            self.repository,
            state_id=state_id,
            episode_id=episode_id,
            personal_model_id=canonical_personal_model_id(personal_model.profile_id),
            required=False,
        )
        current = self.ensure_personal_model_state(personal_model, state_id=state_id, episode_id=episode_id)
        identity_record = replace(
            current.identity,
            display_name=display_name if display_name is not None else current.identity.display_name,
        )
        loaded = build_loaded_profile_from_state(
            personal_model,
            identity_record=identity_record,
            user_profile=current.user,
            relationship_record=current.relationship,
        )
        if clear_elephant_identity or elephant_identity_text is not None:
            loaded = replace(
                loaded,
                elephant_identity_text=None if clear_elephant_identity else _normalized_text(elephant_identity_text),
            )
        bundle = build_canonical_profile_state(
            loaded,
            elephant_id=resolved_state.elephant_id if resolved_state is not None and resolved_state.elephant_id else None,
        )
        synced = sync_canonical_profile_state(
            self.repository,
            bundle,
            previous=load_persisted_canonical_state(self.repository, canonical_personal_model_id(personal_model.profile_id)),
            sync_source="api.identity.update",
            recall_runtime=self.recall_runtime,
            surface="api",
            state_id=resolved_state.state_id if resolved_state is not None else state_id,
            episode_id=episode_id,
        )
        return cast(ElephantIdentityRecord, synced.elephant_identity)

    def update_user_state(
        self,
        *,
        state_id: str | None = None,
        episode_id: str | None = None,
        personal_model_id: str | None = None,
        text: str | None = None,
        fields: dict[str, object] | None = None,
        append: bool = False,
        clear: bool = False,
        split_personal_model_facts: bool = False,
    ) -> RenderedUserProfileView:
        personal_model = self._resolve_personal_model(
            state_id=state_id,
            episode_id=episode_id,
            personal_model_id=personal_model_id,
        )
        resolved_state = resolve_runtime_state(
            self.repository,
            state_id=state_id,
            episode_id=episode_id,
            personal_model_id=canonical_personal_model_id(personal_model.profile_id),
            required=False,
        )
        current = self.ensure_personal_model_state(personal_model, state_id=state_id, episode_id=episode_id)
        loaded = build_loaded_profile_from_state(
            personal_model,
            identity_record=current.identity,
            user_profile=current.user,
            relationship_record=current.relationship,
        )
        field_updates = user_profile_updates(fields) if fields else None
        normalized_text = _normalized_text(text)
        next_user = apply_user_profile_update(
            current.user,
            text=normalized_text,
            field_values=field_updates,
            append=append,
            clear=clear,
        )
        bundle = build_canonical_profile_state(
            replace(loaded, user_profile_text=render_user_profile_projection_text(next_user)),
            elephant_id=resolved_state.elephant_id if resolved_state is not None and resolved_state.elephant_id else None,
        )
        synced = sync_canonical_profile_state(
            self.repository,
            bundle,
            previous=load_persisted_canonical_state(self.repository, canonical_personal_model_id(personal_model.profile_id)),
            sync_source="api.user.update",
            recall_runtime=self.recall_runtime,
            surface="api",
            state_id=resolved_state.state_id if resolved_state is not None else state_id,
            episode_id=episode_id,
        )
        if split_personal_model_facts:
            _replace_user_profile_capture_with_split_facts(
                self.repository,
                personal_model_id=personal_model.profile_id,
                fields=field_updates or {},
                text=normalized_text,
                state_id=resolved_state.state_id if resolved_state is not None else state_id,
                episode_id=episode_id,
                captured_at=datetime.now(timezone.utc),
            )
        return cast(RenderedUserProfileView, synced.user_profile)

    def update_relationship_state(
        self,
        *,
        state_id: str | None = None,
        episode_id: str | None = None,
        personal_model_id: str | None = None,
        text: str | None = None,
        append: bool = False,
        clear: bool = False,
    ) -> RenderedRelationshipView:
        personal_model = self._resolve_personal_model(
            state_id=state_id,
            episode_id=episode_id,
            personal_model_id=personal_model_id,
        )
        resolved_state = resolve_runtime_state(
            self.repository,
            state_id=state_id,
            episode_id=episode_id,
            personal_model_id=canonical_personal_model_id(personal_model.profile_id),
            required=False,
        )
        current = self.ensure_personal_model_state(
            personal_model,
            state_id=state_id,
            episode_id=episode_id,
        )
        loaded = build_loaded_profile_from_state(
            personal_model,
            identity_record=current.identity,
            user_profile=current.user,
            relationship_record=current.relationship,
        )
        companion = loaded.companion or CompanionSettings()
        current_notes = tuple(note.strip() for note in companion.notes if note.strip())
        normalized = tuple(line.strip() for line in (text or "").splitlines() if line.strip())
        if clear:
            next_notes: tuple[str, ...] = ()
        elif append:
            next_notes = current_notes + tuple(note for note in normalized if note not in current_notes)
        elif normalized:
            next_notes = normalized
        else:
            next_notes = current_notes
        bundle = build_canonical_profile_state(
            replace(loaded, companion=replace(companion, notes=next_notes)),
            elephant_id=resolved_state.elephant_id if resolved_state is not None and resolved_state.elephant_id else None,
        )
        synced = sync_canonical_profile_state(
            self.repository,
            bundle,
            previous=load_persisted_canonical_state(self.repository, canonical_personal_model_id(personal_model.profile_id)),
            sync_source="api.relationship.update",
            recall_runtime=self.recall_runtime,
            surface="api",
            state_id=resolved_state.state_id if resolved_state is not None else state_id,
            episode_id=episode_id,
        )
        return cast(RenderedRelationshipView, synced.relationship)

    def inspect_continuity(self, state_id: str) -> APIContinuityInspection:
        state = self._state(state_id)
        episodes = self.repository.list_episodes(state_id=state_id)
        if not episodes:
            raise KeyError(state_id)
        latest_episode = self.repository.load_episode_state(episodes[-1].episode_id)
        if latest_episode is None:
            raise KeyError(episodes[-1].episode_id)
        personal_model = self._personal_model(state.personal_model_id)
        records = self.ensure_personal_model_state(
            personal_model,
            elephant_id=state.elephant_id or None,
            state_id=state_id,
        )
        loaded = build_loaded_profile_from_state(
            personal_model,
            identity_record=records.identity,
            user_profile=records.user,
            relationship_record=records.relationship,
        )
        lineage = self.repository.episode_lineage(latest_episode.episode_id)
        active_state_focus = state.summary or None
        continuity = ContinuityProjectionService().inspect(
            loaded,
            latest_episode,
            lineage=lineage,
            active_state_focus=active_state_focus,
            identity_record=records.identity,
            relationship_record=records.relationship,
        )
        wake_action = "continue" if active_state_focus else "idle"
        wake_summary = active_state_focus if active_state_focus else "No durable elephant focus is available yet."
        wake_factors = ("state-continuity",) if active_state_focus else ("state-empty",)
        return APIContinuityInspection(
            personal_model=personal_model,
            state=state,
            episode=latest_episode,
            identity=records.identity,
            user=records.user,
            relationship=records.relationship,
            continuity=continuity,
            wake_action=wake_action,
            wake_summary=wake_summary,
            wake_factors=wake_factors,
        )

    def _resolve_personal_model(
        self,
        *,
        state_id: str | None,
        episode_id: str | None,
        personal_model_id: str | None,
    ) -> PersonalModelRuntimeState:
        if personal_model_id is not None:
            return self._personal_model(canonical_personal_model_id(personal_model_id))
        if state_id is not None:
            return self._personal_model(self._state(state_id).personal_model_id)
        if episode_id is not None:
            return self._personal_model(self._episode(episode_id).personal_model_id)
        raise ValueError("state_id, episode_id, or personal_model_id is required")

    def _personal_model(self, personal_model_id: str) -> PersonalModelRuntimeState:
        canonical_id = canonical_personal_model_id(personal_model_id)
        personal_model = self.repository.load_personal_model_runtime_state(canonical_id)
        if personal_model is None:
            raise KeyError(canonical_id)
        return personal_model

    def _state(self, state_id: str):
        state = self.repository.load_state(state_id)
        if state is None:
            raise KeyError(state_id)
        return state

    def _episode(self, episode_id: str) -> Episode:
        episode = self.repository.load_episode_state(episode_id)
        if episode is None:
            raise KeyError(episode_id)
        return episode


def _normalized_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


_INIT_PROFILE_FACT_FIELDS: dict[str, tuple[str, str, str, bool]] = {
    "preferred_name": ("identity", "identity.anchor.name.preferred", "low", False),
    "current_work": ("pulse", "pulse.chapter.work.role", "low", False),
    "school": ("world", "world.institutions.school.current", "low", True),
    "current_city": ("world", "world.places.city.current", "low", False),
    "gender": ("identity", "identity.anchor.gender.self_description", "low", False),
    "birth_date": ("identity", "identity.anchor.birth.date", "medium", False),
    "mbti": ("identity", "identity.character.mbti.type", "low", False),
    "hobbies": ("identity", "identity.style.hobbies.personal", "low", False),
    "dream": ("journey", "journey.direction.long_term", "low", True),
    "creative_hobby": ("identity", "identity.style.hobbies.creative", "low", True),
    "media_hobby": ("identity", "identity.style.hobbies.media", "low", True),
    "movement_hobby": ("identity", "identity.style.hobbies.movement", "low", True),
    "boundaries": ("identity", "identity.body.boundary.personal", "high", True),
    "safety_boundaries": ("identity", "identity.body.boundary.personal", "high", True),
    "first_language": ("identity", "identity.style.language.first", "low", False),
    "blog": ("world", "world.links.blog", "low", True),
    "linkedin": ("world", "world.links.linkedin", "low", True),
    "twitter": ("world", "world.links.twitter", "low", True),
    "personal_logo": ("identity", "identity.anchor.logo.personal", "low", True),
    "inner_landscape": ("identity", "identity.pattern.inner_landscape", "medium", True),
    "value_anchor": ("identity", "identity.values.anchor", "medium", True),
    "pressure_pattern": ("pulse", "pulse.pattern.pressure", "medium", True),
    "recovery_style": ("pulse", "pulse.pattern.recovery", "medium", True),
    "decision_compass": ("journey", "journey.decision.compass", "medium", True),
}

_INIT_PROFILE_FIELD_ALIASES = {
    "linked_in": "linkedin",
    "linkedin_url": "linkedin",
    "blog_url": "blog",
    "twitter_url": "twitter",
    "x_url": "twitter",
    "personal_logo_path": "personal_logo",
    "preferredname": "preferred_name",
}


def _replace_user_profile_capture_with_split_facts(
    repository: RuntimeStorageRepository,
    *,
    personal_model_id: str,
    fields: dict[str, str],
    text: str | None,
    state_id: str | None,
    episode_id: str | None,
    captured_at: datetime,
) -> None:
    upsert_fact = getattr(repository, "upsert_personal_model_fact", None)
    list_facts = getattr(repository, "list_personal_model_facts", None)
    if not callable(upsert_fact) or not callable(list_facts):
        return
    profile_id = canonical_personal_model_id(personal_model_id)
    values = _split_profile_values(fields=fields, text=text)
    if values.get("boundaries") and values.get("safety_boundaries") == values["boundaries"]:
        values.pop("safety_boundaries", None)
    for field_id, value in sorted(values.items()):
        spec = _INIT_PROFILE_FACT_FIELDS.get(field_id)
        if spec is None:
            spec = ("identity", f"identity.profile.{field_id}", "low", True)
        lens, topic, sensitivity, keep_label = spec
        fact_text = f"{field_id}: {value}" if keep_label else value
        upsert_fact(
            Fact(
                fact_id=_init_profile_fact_id(profile_id, field_id),
                personal_model_id=profile_id,
                lens=lens,
                text=fact_text,
                confidence=1.0,
                committed_at=captured_at,
                source="user_explicit",
                source_episode_ids=(episode_id,) if episode_id else (),
                status="active",
                metadata={
                    "topic": topic,
                    "component_kind": "user_profile",
                    "sync_source": "api.user.update",
                    "surface": "api",
                    "state_id": state_id or "",
                    "episode_id": episode_id or "",
                    "sensitivity": sensitivity,
                    "user_directed": "true",
                    "recall_policy": "stable",
                    "retention_lifecycle": "durable",
                    "init_profile_field": field_id,
                },
            )
        )

    for fact in list_facts(personal_model_id=profile_id, status=("active",)):
        metadata = dict(fact.metadata or {})
        if metadata.get("canonical_component") != "user-profile":
            continue
        if metadata.get("sync_source") != "api.user.update":
            continue
        upsert_fact(
            replace(
                fact,
                status="deleted",
                metadata={
                    **metadata,
                    "deleted_by": "init_profile_fact_split",
                    "split_profile_fields": "true",
                },
            )
        )


def _split_profile_values(*, fields: dict[str, str], text: str | None) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in (text or "").splitlines():
        if ":" not in raw_line:
            continue
        raw_key, raw_value = raw_line.split(":", 1)
        key = _init_profile_field_key(raw_key)
        value = raw_value.strip()
        if key and value:
            values[key] = value
    for raw_key, raw_value in fields.items():
        key = _init_profile_field_key(raw_key)
        value = str(raw_value or "").strip()
        if key and value:
            values[key] = value
    return values


def _init_profile_field_key(value: object) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return _INIT_PROFILE_FIELD_ALIASES.get(key, key)


def _init_profile_fact_id(profile_id: str, field_id: str) -> str:
    digest = hashlib.sha256(f"{profile_id}:init-profile:{field_id}".encode("utf-8")).hexdigest()[:16]
    return f"fact:init-profile:{field_id}:{digest}"


__all__ = ["APIContinuityInspection", "APIStateService"]
