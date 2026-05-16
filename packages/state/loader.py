"""Runtime profile loader + operator extension-manifest reader.

Canonical identity, user, and relationship state live in structured DB rows
(`states`, `personal_models`) plus persisted component records
(`elephant_identity/v1`, `user_profile/v1`, `relationship/v1`). Read those via
:func:`load_runtime_profile` to obtain a ``LoadedProfile``.

Operator extension configuration — skill overrides, tool overrides, the lists
of extra skill packages / tool manifests the operator wants loaded — still
lives on disk as a JSON file (historical filename ``profile.json``), but that
file no longer owns identity: ``display_name``, ``mode``, and companion
settings are NOT read from it. :class:`ProfileLoader` only surfaces the
extension manifest so the skill and tool runtimes can reload it between
turns.

ELEPHANT.md authored identity files own the elephant's editable voice. This
loader reads durable State / PM rows; runtime surfaces overlay the authored file
before building an Episode-open prompt, then freeze that prompt for the Episode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Mapping

from packages.contracts.runtime import PersonalModelRuntimeState
from packages.storage import RuntimeStorageRepository
from packages.storage.repository_support import (
    DEFAULT_PERSONAL_MODEL_DISPLAY_NAME,
    DEFAULT_PERSONAL_MODEL_ID,
    canonical_personal_model_id,
)

from .policy import (
    CompanionSettings,
    normalize_profile_mode,
    resolve_personality_preset,
)

EXTENSIONS_MANIFEST_FILENAME = "profile.json"


@dataclass(frozen=True, slots=True)
class LoadedProfile:
    """Runtime read shape for identity + user + companion settings.

    Snapshot of what the prompt contract needs for one (personal_model, elephant)
    pair. Identity fields are derived from the canonical DB rows. The
    ``manifest`` map carries operator extension configuration (skill /
    tool overrides) read from ``profile.json``; it must not contain
    identity data.
    """

    state: PersonalModelRuntimeState
    companion: CompanionSettings | None
    profile_dir: str = ""
    manifest_path: str | None = None
    elephant_identity_text: str | None = None
    user_profile_text: str | None = None
    user_profile_path: str | None = None
    manifest: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProfileLoader:
    """Read operator extension configuration (skill / tool overrides).

    This class never looks at identity fields — ``display_name``,
    ``mode``, ``companion`` — they come from the canonical State row via
    :func:`load_runtime_profile` instead.
    """

    profile_dir: Path

    def load(
        self,
        *,
        profile_id: str | None = None,
        display_name: str | None = None,
        mode: str | None = None,
    ) -> LoadedProfile:
        del profile_id, display_name, mode  # legacy kwargs — identity no longer read here.
        manifest_path = self.profile_dir / EXTENSIONS_MANIFEST_FILENAME
        manifest = self._load_manifest(manifest_path)
        state = PersonalModelRuntimeState(
            profile_id=DEFAULT_PERSONAL_MODEL_ID,
            display_name=DEFAULT_PERSONAL_MODEL_DISPLAY_NAME,
            mode="companion",
            elephant_path=None,
            preferences=(),
            enabled_capabilities=(),
        )
        return LoadedProfile(
            state=state,
            companion=None,
            profile_dir=str(self.profile_dir),
            manifest_path=str(manifest_path) if manifest_path.exists() else None,
            manifest=dict(manifest),
        )

    def load_state(
        self,
        *,
        profile_id: str | None = None,
        display_name: str | None = None,
        mode: str | None = None,
    ) -> PersonalModelRuntimeState:
        return self.load(
            profile_id=profile_id,
            display_name=display_name,
            mode=mode,
        ).state

    def _load_manifest(self, manifest_path: Path) -> dict[str, Any]:
        if not manifest_path.exists():
            return {}
        with manifest_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError(f"{manifest_path} must contain a JSON object")
        return payload


def write_extensions_manifest(profile_dir: Path, manifest: Mapping[str, Any]) -> Path:
    """Write the operator extension manifest.

    Identity fields (``display_name``, ``mode``, ``companion``) are rejected —
    they must live on the State row, not on disk.
    """
    forbidden = {"display_name", "mode", "companion", "profile_id"}
    payload = {key: value for key, value in manifest.items() if key not in forbidden}
    path = profile_dir / EXTENSIONS_MANIFEST_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


# Legacy name retained while call sites migrate — forwards to the
# extension-manifest writer. Delete once every write path uses the new name.
write_profile_manifest = write_extensions_manifest


def companion_manifest_payload(companion: CompanionSettings | None) -> dict[str, Any] | None:
    """Serialize companion settings for transport or diagnostic views.

    Used only by diagnostic surfaces; never persisted back to disk as
    identity truth.
    """
    if companion is None:
        return None
    return {
        "text_first": companion.text_first,
        "personality_preset": companion.personality_preset,
        "personality": list(companion.personality),
        "initiative": companion.initiative,
        "preserve_relationship_timeline": companion.preserve_relationship_timeline,
        "preserve_preferences": companion.preserve_preferences,
        "preserve_corrections": companion.preserve_corrections,
        "preserve_emotional_context": companion.preserve_emotional_context,
        "notes": list(companion.notes),
    }


def profile_manifest_payload(
    loaded_profile: LoadedProfile,
    *,
    existing_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Operator-facing snapshot of a LoadedProfile (diagnostic only)."""
    manifest = dict(existing_manifest or {})
    manifest["profile_id"] = loaded_profile.state.profile_id
    manifest["display_name"] = loaded_profile.state.display_name
    manifest["mode"] = normalize_profile_mode(loaded_profile.state.mode)
    manifest["preferences"] = list(loaded_profile.state.preferences)
    manifest["enabled_capabilities"] = list(loaded_profile.state.enabled_capabilities)
    companion_payload = companion_manifest_payload(loaded_profile.companion)
    if companion_payload is None:
        manifest.pop("companion", None)
    else:
        manifest["companion"] = companion_payload
    return manifest


def load_runtime_profile(
    repository: RuntimeStorageRepository,
    *,
    personal_model_id: str | None = None,
    elephant_id: str | None = None,
    state_id: str | None = None,
    profile_loader: ProfileLoader | None = None,
) -> LoadedProfile:
    """Build a ``LoadedProfile`` from canonical DB rows.

    Resolution order:

    1. If ``state_id`` is given, load that State row.
    2. Else if ``elephant_id`` is given, resolve the State whose ``elephant_id``
       matches.
    3. Else if ``personal_model_id`` is given, fall back to the single
       active State for that personal model.
    4. Otherwise — no anchor at all — return a stub profile using the
       default personal-model id; callers that hit this path have not
       bound an identity yet.

    The returned profile's ``state.display_name`` is the companion's
    display name (``State.elephant_name``). The personal-model-global preferred
    username lives in ``RenderedUserProfileView.preferred_name`` and is projected
    into ``user_profile_text``.

    When ``profile_loader`` is given, its extension-manifest map is merged
    into the returned profile so that skill / tool override consumers keep
    working.
    """
    from .persistence import load_persisted_canonical_state
    from .projection import build_loaded_profile_from_state

    resolved_state = _resolve_state_row(
        repository,
        state_id=state_id,
        elephant_id=elephant_id,
        personal_model_id=personal_model_id,
    )
    manifest: Mapping[str, Any] = {}
    profile_dir = ""
    manifest_path: str | None = None
    if profile_loader is not None:
        overlay = profile_loader.load()
        manifest = overlay.manifest
        profile_dir = overlay.profile_dir
        manifest_path = overlay.manifest_path

    if resolved_state is None:
        stub = _stub_profile(personal_model_id=personal_model_id)
        # Even without an elephant anchor, honour the persisted personal-model
        # elephant_identity / user_profile records so the operator-facing "root
        # profile" view reflects settings the user has curated.
        canonical_pm_id = stub.state.profile_id
        try:
            persisted = load_persisted_canonical_state(repository, canonical_pm_id)
        except Exception:
            persisted = None
        overlay_elephant_identity_text: str | None = stub.elephant_identity_text
        overlay_user_profile_text: str | None = stub.user_profile_text
        overlay_companion = stub.companion
        if persisted is not None:
            if persisted.elephant_identity is not None:
                candidate_text = (persisted.elephant_identity.elephant_identity_text or "").strip() or None
                if candidate_text:
                    overlay_elephant_identity_text = candidate_text
                overlay_companion = _companion_settings_from_identity(
                    identity_record=persisted.elephant_identity,
                    relationship_record=persisted.relationship,
                    fallback_mode=stub.state.mode,
                )
            if persisted.user_profile is not None:
                overlay_user_profile_text = _user_profile_text_from_card(persisted.user_profile)
        return LoadedProfile(
            state=stub.state,
            companion=overlay_companion,
            profile_dir=profile_dir,
            manifest_path=manifest_path,
            elephant_identity_text=overlay_elephant_identity_text,
            user_profile_text=overlay_user_profile_text,
            user_profile_path=stub.user_profile_path,
            manifest=dict(manifest),
        )

    persisted = load_persisted_canonical_state(repository, resolved_state.personal_model_id)
    companion_settings = _companion_settings_from_identity(
        identity_record=persisted.elephant_identity,
        relationship_record=persisted.relationship,
        fallback_mode=resolved_state.identity_mode or "companion",
    )
    elephant_identity_text = (resolved_state.elephant_identity_text or "").strip() or None
    if elephant_identity_text is None and persisted.elephant_identity is not None:
        elephant_identity_text = (persisted.elephant_identity.elephant_identity_text or "").strip() or None
    companion_name = (resolved_state.elephant_name or "").strip()
    runtime_state = PersonalModelRuntimeState(
        profile_id=canonical_personal_model_id(resolved_state.personal_model_id),
        display_name=companion_name or DEFAULT_PERSONAL_MODEL_DISPLAY_NAME,
        mode=normalize_profile_mode(resolved_state.identity_mode or "companion"),
        elephant_path=None,
        preferences=(),
        enabled_capabilities=(),
    )
    user_profile_text_value = _user_profile_text_from_card(persisted.user_profile)
    return build_loaded_profile_from_state(
        runtime_state,
        manifest=manifest,
        companion=companion_settings,
        profile_dir=profile_dir,
        manifest_path=manifest_path,
        elephant_identity_text=elephant_identity_text,
        user_profile_text=user_profile_text_value,
        user_profile_path=None,
        identity_record=None,
        user_profile=None,
        relationship_record=None,
    )


def _stub_profile(*, personal_model_id: str | None) -> LoadedProfile:
    """Profile returned when the caller has no elephant anchor.

    Used when there is no ``state_id`` / ``elephant_id`` and multiple active
    herd live under the personal model — or no herd at all. We surface the
    brand name ``"Elephant Agent"`` so the prompt never renders nonsense like
    ``"You are You"`` and the operator UI has a clear "no elephant selected"
    label.
    """
    profile_id = canonical_personal_model_id(personal_model_id or DEFAULT_PERSONAL_MODEL_ID)
    preset = resolve_personality_preset(None, mode="companion")
    runtime_state = PersonalModelRuntimeState(
        profile_id=profile_id,
        display_name="Elephant Agent",
        mode="companion",
        elephant_path=None,
        preferences=(),
        enabled_capabilities=(),
    )
    companion = CompanionSettings(
        personality_preset=preset.preset_id,
        personality=preset.traits,
    )
    return LoadedProfile(
        state=runtime_state,
        companion=companion,
        profile_dir="",
        manifest_path=None,
        elephant_identity_text=None,
        user_profile_text=None,
        user_profile_path=None,
        manifest={},
    )


def _resolve_state_row(
    repository: RuntimeStorageRepository,
    *,
    state_id: str | None,
    elephant_id: str | None,
    personal_model_id: str | None,
):
    """Locate the canonical State row for a ``(state_id | elephant_id | personal_model)`` anchor.

    Resolution order:

    1. explicit ``state_id`` → exact match.
    2. explicit ``elephant_id`` → look up ``state:{elephant_id}`` then scan.
    3. bare ``personal_model_id`` with exactly one active State under it —
       safe to pick.
    4. bare ``personal_model_id`` with multiple active States → ``None``;
       callers must not surface an arbitrary one as "the" elephant because a
       personal model can own many herd, and picking one masks the
       ambiguity.
    """
    explicit_state_id = str(state_id or "").strip()
    if explicit_state_id:
        loaded = repository.load_state(explicit_state_id)
        if loaded is not None:
            return loaded
    explicit_elephant_id = str(elephant_id or "").strip()
    if explicit_elephant_id:
        derived_id = f"state:{explicit_elephant_id}"
        loaded = repository.load_state(derived_id)
        if loaded is not None:
            return loaded
        for candidate in repository.list_states():
            if candidate.elephant_id == explicit_elephant_id:
                return candidate
    explicit_personal_model_id = str(personal_model_id or "").strip()
    if explicit_personal_model_id:
        canonical = canonical_personal_model_id(explicit_personal_model_id)
        matching = tuple(
            state
            for state in repository.list_states(status="active")
            if state.personal_model_id == canonical
        )
        if len(matching) == 1:
            return matching[0]
    return None


def _companion_settings_from_identity(
    *,
    identity_record,
    relationship_record,
    fallback_mode: str,
) -> CompanionSettings:
    if identity_record is None:
        preset = resolve_personality_preset(None, mode=fallback_mode)
        notes = relationship_record.continuity_notes if relationship_record is not None else ()
        return CompanionSettings(
            personality_preset=preset.preset_id,
            personality=preset.traits,
            notes=notes,
        )
    governance_flags = set(identity_record.governance_flags or ())
    preset_id = identity_record.personality_preset or None
    preset = resolve_personality_preset(preset_id, mode=fallback_mode)
    notes = relationship_record.continuity_notes if relationship_record is not None else ()
    return CompanionSettings(
        text_first=_flag(governance_flags, positive="text-first", fallback=True),
        personality_preset=preset.preset_id,
        personality=preset.traits,
        initiative=identity_record.initiative or "gentle",
        preserve_relationship_timeline=_flag(
            governance_flags,
            positive="preserve-relationship-timeline",
            negative="limit-relationship-timeline",
            fallback=True,
        ),
        preserve_preferences=_flag(
            governance_flags,
            positive="preserve-preferences",
            negative="limit-preferences",
            fallback=True,
        ),
        preserve_corrections=_flag(
            governance_flags,
            positive="preserve-corrections",
            negative="limit-corrections",
            fallback=True,
        ),
        preserve_emotional_context=_flag(
            governance_flags,
            positive="preserve-emotional-context",
            negative="limit-emotional-context",
            fallback=True,
        ),
        notes=notes,
    )


def _flag(
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


def _user_profile_text_from_card(user_profile) -> str | None:
    if user_profile is None:
        return None
    from .projection import render_user_profile_projection_text

    return render_user_profile_projection_text(user_profile)
