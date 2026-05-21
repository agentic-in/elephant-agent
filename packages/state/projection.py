"""Project canonical identity, user, and relationship state into a runtime profile view."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from packages.contracts import ElephantIdentityRecord
from packages.state.rendered_views import RenderedRelationshipView, RenderedUserProfileView
from packages.contracts.runtime import PersonalModelRuntimeState

from .governance import render_user_profile_text as render_user_profile_content
from .loader import LoadedProfile
from .policy import CompanionSettings, resolve_personality_preset


def render_user_profile_projection_text(record: RenderedUserProfileView | None) -> str | None:
    if record is None:
        return None
    field_values: dict[str, str | None] = {
        "preferred_name": record.preferred_name,
        "locale": record.locale,
        "timezone": record.timezone,
        "boundaries": record.boundaries[0] if record.boundaries else None,
    }
    for fragment in record.biography_fragments:
        key, _, value = fragment.partition(":")
        if key and value:
            field_values[key.strip()] = value.strip()
    rendered = render_user_profile_content(durable_notes=record.durable_notes, **field_values)
    cleaned = rendered.strip()
    return cleaned or None


def overlay_canonical_profile_state(
    profile: LoadedProfile,
    *,
    identity_record: ElephantIdentityRecord | None = None,
    user_profile: RenderedUserProfileView | None = None,
    relationship_record: RenderedRelationshipView | None = None,
) -> LoadedProfile:
    state = profile.state
    if identity_record is not None:
        state = replace(
            state,
            display_name=identity_record.display_name,
        )
    companion = _project_companion_settings(
        profile.companion,
        mode=state.mode,
        identity_record=identity_record,
        relationship_record=relationship_record,
    )
    user_profile_text = render_user_profile_projection_text(user_profile) if user_profile is not None else profile.user_profile_text
    elephant_identity_text = profile.elephant_identity_text
    if identity_record is not None and identity_record.elephant_identity_text is not None:
        elephant_identity_text = identity_record.elephant_identity_text
    return LoadedProfile(
        state=state,
        companion=companion,
        profile_dir=profile.profile_dir,
        manifest_path=profile.manifest_path,
        elephant_identity_text=elephant_identity_text,
        user_profile_text=user_profile_text,
        user_profile_path=profile.user_profile_path,
        manifest=dict(profile.manifest),
    )


def build_loaded_profile_from_state(
    profile_state: PersonalModelRuntimeState,
    *,
    manifest: Mapping[str, object] | None = None,
    companion: CompanionSettings | None = None,
    profile_dir: str = "",
    manifest_path: str | None = None,
    elephant_identity_text: str | None = None,
    user_profile_text: str | None = None,
    user_profile_path: str | None = None,
    identity_record: ElephantIdentityRecord | None = None,
    user_profile: RenderedUserProfileView | None = None,
    relationship_record: RenderedRelationshipView | None = None,
) -> LoadedProfile:
    base = LoadedProfile(
        state=profile_state,
        companion=companion,
        profile_dir=profile_dir,
        manifest_path=manifest_path,
        elephant_identity_text=elephant_identity_text,
        user_profile_text=user_profile_text,
        user_profile_path=user_profile_path,
        manifest=dict(manifest or {}),
    )
    return overlay_canonical_profile_state(
        base,
        identity_record=identity_record,
        user_profile=user_profile,
        relationship_record=relationship_record,
    )


def _project_companion_settings(
    current: CompanionSettings | None,
    *,
    mode: str,
    identity_record: ElephantIdentityRecord | None,
    relationship_record: RenderedRelationshipView | None,
) -> CompanionSettings:
    resolved_current = current or _default_companion_settings(mode)
    if identity_record is None and relationship_record is None:
        return resolved_current
    governance_flags = set(identity_record.governance_flags if identity_record is not None else ())
    notes = relationship_record.continuity_notes if relationship_record is not None else resolved_current.notes
    requested_preset = (
        identity_record.personality_preset.strip()
        if identity_record is not None and identity_record.personality_preset.strip()
        else resolved_current.personality_preset
    )
    resolved_preset = resolve_personality_preset(requested_preset, mode=mode)
    personality = (
        resolved_current.personality
        if requested_preset == resolved_current.personality_preset
        else resolved_preset.traits
    )
    return CompanionSettings(
        text_first=_flag_enabled(governance_flags, positive="text-first", fallback=resolved_current.text_first),
        personality_preset=resolved_preset.preset_id,
        personality=personality,
        initiative=(
            identity_record.initiative.strip()
            if identity_record is not None and identity_record.initiative.strip()
            else resolved_current.initiative
        ),
        preserve_relationship_timeline=_flag_enabled(
            governance_flags,
            positive="preserve-relationship-timeline",
            negative="limit-relationship-timeline",
            fallback=resolved_current.preserve_relationship_timeline,
        ),
        preserve_preferences=_flag_enabled(
            governance_flags,
            positive="preserve-preferences",
            negative="limit-preferences",
            fallback=resolved_current.preserve_preferences,
        ),
        preserve_corrections=_flag_enabled(
            governance_flags,
            positive="preserve-corrections",
            negative="limit-corrections",
            fallback=resolved_current.preserve_corrections,
        ),
        preserve_emotional_context=_flag_enabled(
            governance_flags,
            positive="preserve-emotional-context",
            negative="limit-emotional-context",
            fallback=resolved_current.preserve_emotional_context,
        ),
        notes=notes,
    )


def _default_companion_settings(mode: str) -> CompanionSettings:
    preset = resolve_personality_preset(None, mode=mode)
    return CompanionSettings(
        personality_preset=preset.preset_id,
        personality=preset.traits,
    )


def _flag_enabled(
    flags: set[str],
    *,
    positive: str,
    fallback: bool,
    negative: str | None = None,
) -> bool:
    if positive in flags:
        return True
    if negative is not None and negative in flags:
        return False
    return fallback
