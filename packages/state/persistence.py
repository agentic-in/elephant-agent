"""Persist canonical personal-AI records with ledger tracking."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
from uuid import uuid4

from .canonical import CanonicalPersonalModelRuntimeStateBundle
from .canonical import canonical_profile_ids
from .profile_from_claims import TOPIC_TO_FIELD, derive_profile_from_claims
from .projection import render_user_profile_projection_text
from .user_updates import apply_user_profile_update
from packages.contracts import ElephantIdentityRecord, Fact
from packages.state.rendered_views import (
    RenderedRelationshipView,
    RenderedUserProfileView,
)
from packages.evidence.recall_runtime import RecallRuntime
from packages.storage import RuntimeStorageRepository


@dataclass(frozen=True, slots=True)
class PersistedCanonicalState:
    elephant_identity: object | None
    user_profile: object | None
    relationship: object | None


@dataclass(frozen=True, slots=True)
class StoredIdentityLedgerEntry:
    entry_id: str
    elephant_id: str
    profile_id: str
    action: str
    summary: str
    metadata: dict[str, str]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class StoredUserProfileLedgerEntry:
    entry_id: str
    user_profile_id: str
    profile_id: str
    action: str
    summary: str
    metadata: dict[str, str]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class StoredRelationshipLedgerEntry:
    entry_id: str
    relationship_id: str
    profile_id: str
    action: str
    summary: str
    metadata: dict[str, str]
    created_at: datetime


def load_persisted_canonical_state(repository: RuntimeStorageRepository, profile_id: str) -> PersistedCanonicalState:
    load_elephant_identity = getattr(repository, "load_elephant_identity_for_profile", None)
    if load_elephant_identity is None:
        return _load_canonical_records(repository, profile_id)
    identity = load_elephant_identity(profile_id)
    return PersistedCanonicalState(
        elephant_identity=identity,
        user_profile=_render_user_profile_from_facts(repository, profile_id),
        relationship=_render_relationship_from_facts(repository, profile_id, identity=identity),
    )


def _active_pm_facts(repository: RuntimeStorageRepository, profile_id: str) -> tuple[Fact, ...]:
    list_facts = getattr(repository, "list_personal_model_facts", None)
    if not callable(list_facts):
        return ()
    return tuple(list_facts(personal_model_id=profile_id, status=("active",)))


def _render_user_profile_from_facts(
    repository: RuntimeStorageRepository, profile_id: str
) -> RenderedUserProfileView | None:
    facts = _active_pm_facts(repository, profile_id)
    ids = canonical_profile_ids(profile_id)
    view = RenderedUserProfileView(
        user_profile_id=ids.user_profile_id,
        profile_id=profile_id,
    )
    touched = False
    field_values = derive_profile_from_claims(facts)
    if field_values:
        view = apply_user_profile_update(view, field_values=field_values, append=True)
        touched = True
    for fact in facts:
        metadata = dict(getattr(fact, "metadata", {}) or {})
        topic = str(metadata.get("topic") or "").strip()
        component = str(metadata.get("canonical_component") or "").strip()
        component_kind = str(metadata.get("component_kind") or "").strip()
        if component != "user-profile" and component_kind != "user_profile" and topic not in TOPIC_TO_FIELD:
            continue
        text = str(getattr(fact, "text", "") or "")
        if text.strip() and topic not in TOPIC_TO_FIELD:
            view = apply_user_profile_update(view, text=text, append=True)
        touched = True
    return view


def _render_relationship_from_facts(
    repository: RuntimeStorageRepository,
    profile_id: str,
    *,
    identity: object | None,
) -> RenderedRelationshipView | None:
    facts = _active_pm_facts(repository, profile_id)
    ids = canonical_profile_ids(profile_id)
    elephant_id = str(getattr(identity, "elephant_id", "") or ids.elephant_id)
    interaction_preferences = _tuple_unique(str(item) for item in getattr(identity, "governance_flags", ()) or ())
    expectations = _tuple_unique(
        (f"initiative:{value}" for value in (str(getattr(identity, "initiative", "") or "").strip(),) if value),
        (
            f"relational_stance:{value}"
            for value in (str(getattr(identity, "relational_stance", "") or "").strip(),)
            if value
        ),
        (
            f"personality_preset:{value}"
            for value in (str(getattr(identity, "personality_preset", "") or "").strip(),)
            if value
        ),
    )
    trust_markers: list[str] = []
    repair_history: list[str] = []
    local_corrections: list[str] = []
    notes: list[str] = []
    for fact in facts:
        metadata = dict(getattr(fact, "metadata", {}) or {})
        topic = str(metadata.get("topic") or "").strip()
        component = str(metadata.get("canonical_component") or "").strip()
        component_kind = str(metadata.get("component_kind") or "").strip()
        if component != "relationship" and component_kind != "relationship" and topic != "identity.style.relationship":
            continue
        text = str(getattr(fact, "text", "") or "").strip()
        if not text:
            continue
        parsed = _parse_relationship_fact_content(text)
        interaction_preferences = _tuple_unique(interaction_preferences, parsed["interaction_preferences"])
        expectations = _tuple_unique(expectations, parsed["expectations"])
        trust_markers.extend(parsed["trust_markers"])
        repair_history.extend(parsed["repair_history"])
        local_corrections.extend(parsed["local_corrections"])
        notes.extend(parsed["continuity_notes"])
    if identity is None and not any(
        (
            interaction_preferences,
            expectations,
            trust_markers,
            repair_history,
            local_corrections,
            notes,
        )
    ):
        return None
    return RenderedRelationshipView(
        relationship_id=ids.relationship_id,
        profile_id=profile_id,
        elephant_id=elephant_id,
        user_profile_id=ids.user_profile_id,
        interaction_preferences=interaction_preferences,
        expectations=expectations,
        trust_markers=_tuple_unique(trust_markers),
        repair_history=_tuple_unique(repair_history),
        local_corrections=_tuple_unique(local_corrections),
        continuity_notes=_tuple_unique(notes),
    )


def _parse_relationship_fact_content(text: str) -> dict[str, tuple[str, ...]]:
    buckets: dict[str, list[str]] = {
        "interaction_preferences": [],
        "expectations": [],
        "trust_markers": [],
        "repair_history": [],
        "local_corrections": [],
        "continuity_notes": [],
    }
    label_to_bucket = {
        "interaction preference": "interaction_preferences",
        "expectation": "expectations",
        "trust marker": "trust_markers",
        "repair history": "repair_history",
        "local correction": "local_corrections",
        "continuity note": "continuity_notes",
    }
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        label, separator, value = line.partition(":")
        bucket = label_to_bucket.get(label.strip().lower()) if separator else None
        cleaned = value.strip() if bucket is not None else line
        if cleaned:
            buckets[bucket or "continuity_notes"].append(cleaned)
    return {key: _tuple_unique(values) for key, values in buckets.items()}


def _tuple_unique(*groups) -> tuple[str, ...]:
    values: list[str] = []
    for group in groups:
        for value in group:
            cleaned = str(value or "").strip()
            if cleaned and cleaned not in values:
                values.append(cleaned)
    return tuple(values)


def resolve_runtime_state(
    repository: RuntimeStorageRepository,
    *,
    state_id: str | None = None,
    episode_id: str | None = None,
    personal_model_id: str | None = None,
    elephant_id: str | None = None,
    state_anchor: str | None = None,
    status: str | None = "active",
    required: bool = False,
):
    explicit_state_id = str(state_id or "").strip()
    if explicit_state_id:
        state = repository.load_state(explicit_state_id)
        if state is not None:
            return state
    explicit_episode_id = str(episode_id or "").strip()
    if explicit_episode_id:
        stored_episode = repository.load_episode(explicit_episode_id)
        if stored_episode is not None:
            state = repository.load_state(stored_episode.state_id)
            if state is not None:
                return state
            if personal_model_id is None:
                personal_model_id = stored_episode.personal_model_id
    resolved_profile_id = str(personal_model_id or "").strip() or None
    resolved_elephant_id = str(elephant_id or "").strip() or None
    resolved_anchor = str(state_anchor or "").strip() or None
    states = repository.list_states(status=status) if status is not None else repository.list_states()
    if resolved_profile_id is not None:
        states = tuple(state for state in states if state.personal_model_id == resolved_profile_id)
    if resolved_anchor is not None:
        for state in states:
            if state.state_anchor == resolved_anchor:
                return state
    if resolved_elephant_id is not None:
        elephant_anchors = {resolved_elephant_id, f"elephant:{resolved_elephant_id}"}
        for state in states:
            if state.elephant_id == resolved_elephant_id or state.state_anchor in elephant_anchors:
                return state
    current = repository.current_state()
    if current is not None:
        if resolved_profile_id is not None and current.personal_model_id != resolved_profile_id:
            current = None
        if current is not None and resolved_anchor is not None and current.state_anchor != resolved_anchor:
            current = None
        if (
            current is not None
            and resolved_elephant_id is not None
            and current.elephant_id != resolved_elephant_id
            and current.state_anchor not in {resolved_elephant_id, f"elephant:{resolved_elephant_id}"}
        ):
            current = None
        if current is not None:
            return current
    if resolved_profile_id is not None and len(states) == 1:
        return states[0]
    if required:
        targets = (
            ", ".join(
                candidate
                for candidate in (
                    explicit_state_id,
                    explicit_episode_id,
                    resolved_anchor,
                    resolved_elephant_id,
                    resolved_profile_id or "",
                )
                if candidate
            )
            or "runtime-state"
        )
        raise KeyError(f"runtime state not found for {targets}")
    return None


def sync_canonical_profile_state(
    repository: RuntimeStorageRepository,
    bundle: CanonicalPersonalModelRuntimeStateBundle,
    *,
    previous: PersistedCanonicalState,
    sync_source: str,
    recall_runtime: RecallRuntime | None = None,
    surface: str = "",
    state_id: str | None = None,
    episode_id: str | None = None,
    user_directed: bool = True,
) -> PersistedCanonicalState:
    synced_at = datetime.now(timezone.utc)
    profile_id = bundle.elephant_identity.profile_id
    if recall_runtime is not None:
        _capture_canonical_profile_updates(
            repository,
            bundle,
            previous=previous,
            sync_source=sync_source,
            surface=surface,
            state_id=state_id,
            episode_id=episode_id,
            user_directed=user_directed,
            captured_at=synced_at,
        )
    upsert_elephant_identity = getattr(repository, "upsert_elephant_identity", None)
    append_identity_ledger = getattr(repository, "append_identity_ledger", None)
    append_user_profile_ledger = getattr(repository, "append_user_profile_ledger", None)
    append_relationship_ledger = getattr(repository, "append_relationship_ledger", None)
    if upsert_elephant_identity is None:
        _upsert_canonical_records(repository, bundle, synced_at=synced_at)
        return PersistedCanonicalState(
            elephant_identity=bundle.elephant_identity,
            user_profile=bundle.user_profile,
            relationship=bundle.relationship,
        )
    upsert_elephant_identity(bundle.elephant_identity, updated_at=synced_at)
    metadata = {
        "profile_id": profile_id,
        "sync_source": sync_source,
    }
    if bundle.elephant_identity.source_manifest_path is not None:
        metadata["manifest_path"] = bundle.elephant_identity.source_manifest_path
    if bundle.elephant_identity.source_elephant_path is not None:
        metadata["elephant_path"] = bundle.elephant_identity.source_elephant_path
    if bundle.user_profile.source_user_profile_path is not None:
        metadata["user_profile_path"] = bundle.user_profile.source_user_profile_path
    if _record_changed(previous.elephant_identity, bundle.elephant_identity) and append_identity_ledger is not None:
        append_identity_ledger(
            StoredIdentityLedgerEntry(
                entry_id=f"identity:{uuid4().hex}",
                elephant_id=bundle.elephant_identity.elephant_id,
                profile_id=profile_id,
                action="canonical_sync",
                summary=f"synchronized canonical elephant identity from {sync_source}",
                metadata={**metadata, "owner": "elephant"},
                created_at=synced_at,
            )
        )
    if _record_changed(previous.user_profile, bundle.user_profile) and append_user_profile_ledger is not None:
        append_user_profile_ledger(
            StoredUserProfileLedgerEntry(
                entry_id=f"user-profile:{uuid4().hex}",
                user_profile_id=bundle.user_profile.user_profile_id,
                profile_id=profile_id,
                action="canonical_sync",
                summary=f"synchronized canonical user profile from {sync_source}",
                metadata={**metadata, "owner": "user"},
                created_at=synced_at,
            )
        )
    if _record_changed(previous.relationship, bundle.relationship) and append_relationship_ledger is not None:
        append_relationship_ledger(
            StoredRelationshipLedgerEntry(
                entry_id=f"relationship:{uuid4().hex}",
                relationship_id=bundle.relationship.relationship_id,
                profile_id=profile_id,
                action="canonical_sync",
                summary=f"synchronized canonical relationship projection from {sync_source}",
                metadata={**metadata, "owner": "relationship"},
                created_at=synced_at,
            )
        )
    return PersistedCanonicalState(
        elephant_identity=bundle.elephant_identity,
        user_profile=bundle.user_profile,
        relationship=bundle.relationship,
    )


def _capture_canonical_profile_updates(
    repository: RuntimeStorageRepository,
    bundle: CanonicalPersonalModelRuntimeStateBundle,
    *,
    previous: PersistedCanonicalState,
    sync_source: str,
    surface: str,
    state_id: str | None,
    episode_id: str | None,
    user_directed: bool,
    captured_at: datetime,
) -> None:
    profile_id = bundle.elephant_identity.profile_id
    upsert_fact = getattr(repository, "upsert_personal_model_fact", None)
    if not callable(upsert_fact):
        raise RuntimeError("canonical personal-model fact writes require fact-backed storage")
    component_specs = (
        (
            "user-profile",
            previous.user_profile,
            bundle.user_profile,
            "user_profile",
            "identity",
            "identity.anchor.user_profile",
            _user_profile_capture_content(bundle.user_profile),
            "low",
        ),
        (
            "relationship",
            previous.relationship,
            bundle.relationship,
            "relationship",
            "identity",
            "identity.style.relationship",
            _relationship_capture_content(bundle.relationship),
            "medium",
        ),
    )
    for (
        component,
        prior_record,
        current_record,
        component_kind,
        lens,
        topic,
        content,
        sensitivity,
    ) in component_specs:
        if not _record_changed(prior_record, current_record):
            continue
        if not content.strip():
            continue
        upsert_fact(
            Fact(
                fact_id=_canonical_update_fact_id(profile_id, component),
                personal_model_id=profile_id,
                lens=lens,
                text=content,
                confidence=1.0 if user_directed else 0.72,
                committed_at=captured_at,
                source="user_explicit" if user_directed else "pm_agent_promote",
                source_episode_ids=(episode_id,) if episode_id else (),
                status="active",
                metadata={
                    "topic": topic,
                    "component_kind": component_kind,
                    "canonical_component": component,
                    "sync_source": sync_source,
                    "surface": surface,
                    "state_id": state_id or "",
                    "episode_id": episode_id or "",
                    "sensitivity": sensitivity,
                    "user_directed": "true" if user_directed else "false",
                    "recall_policy": "stable",
                    "retention_lifecycle": "durable",
                },
            )
        )


def _canonical_update_fact_id(profile_id: str, component: str) -> str:
    digest = hashlib.sha256(f"{profile_id}:{component}".encode("utf-8")).hexdigest()[:16]
    return f"fact:canonical:{component}:{digest}"


def _canonical_component_payload(record: object | None) -> dict[str, object] | None:
    if record is None:
        return None
    if isinstance(record, ElephantIdentityRecord):
        return _elephant_identity_payload(record)
    if isinstance(record, RenderedUserProfileView):
        return _user_profile_payload(record)
    if isinstance(record, RenderedRelationshipView):
        return _relationship_projection_payload(record)
    return None


def _identity_capture_content(record: ElephantIdentityRecord) -> str:
    parts = [
        f"Display name: {record.display_name}",
        f"Identity mode: {record.identity_mode}",
        f"Personality preset: {record.personality_preset}",
        f"Initiative: {record.initiative}",
        f"Relational stance: {record.relational_stance}",
        f"Working style contract: {record.working_style_contract}",
    ]
    if record.elephant_identity_text:
        parts.append(f"Elephant identity text: {record.elephant_identity_text}")
    return "\n".join(part for part in parts if part.strip())


def _user_profile_capture_content(record: RenderedUserProfileView) -> str:
    rendered = render_user_profile_projection_text(record)
    if rendered is not None and rendered.strip():
        return rendered
    parts = [
        *(
            (f"Preferred name: {record.preferred_name.strip()}",)
            if record.preferred_name and record.preferred_name.strip()
            else ()
        ),
        *(f"Biography: {item}" for item in record.biography_fragments if item.strip()),
        *(f"Boundary: {item}" for item in record.boundaries if item.strip()),
        *(f"Remember: {item}" for item in record.durable_notes if item.strip()),
    ]
    return "\n".join(part for part in parts if part.strip())


_SYSTEM_RELATIONSHIP_PREFERENCES = frozenset(
    {
        "text-first",
        "preserve-relationship-timeline",
        "preserve-preferences",
        "preserve-corrections",
        "preserve-emotional-context",
    }
)
_SYSTEM_RELATIONSHIP_EXPECTATION_PREFIXES = (
    "initiative:",
    "relational_stance:",
    "personality_label:",
)


def _relationship_capture_content(record: RenderedRelationshipView) -> str:
    user_preferences = tuple(
        item.strip()
        for item in record.interaction_preferences
        if item.strip() and item.strip() not in _SYSTEM_RELATIONSHIP_PREFERENCES
    )
    user_expectations = tuple(
        item.strip()
        for item in record.expectations
        if item.strip()
        and not any(item.strip().startswith(prefix) for prefix in _SYSTEM_RELATIONSHIP_EXPECTATION_PREFIXES)
    )
    parts = [
        *(f"Interaction preference: {item}" for item in user_preferences),
        *(f"Expectation: {item}" for item in user_expectations),
        *(f"Trust marker: {item}" for item in record.trust_markers if item.strip()),
        *(f"Repair history: {item}" for item in record.repair_history if item.strip()),
        *(f"Local correction: {item}" for item in record.local_corrections if item.strip()),
        *(f"Continuity note: {item}" for item in record.continuity_notes if item.strip()),
    ]
    return "\n".join(part for part in parts if part.strip())


def _record_changed(previous, current) -> bool:
    if previous is None:
        return True
    return replace(previous, created_at=None, updated_at=None) != replace(
        current,
        created_at=None,
        updated_at=None,
    )


def _load_canonical_records(repository: RuntimeStorageRepository, profile_id: str) -> PersistedCanonicalState:
    return PersistedCanonicalState(
        elephant_identity=repository.load_elephant_identity_for_profile(profile_id),
        user_profile=None,
        relationship=None,
    )


def _upsert_canonical_records(
    repository: RuntimeStorageRepository,
    bundle: CanonicalPersonalModelRuntimeStateBundle,
    *,
    synced_at: datetime,
) -> None:
    profile_id = bundle.elephant_identity.profile_id
    repository.ensure_default_personal_model(personal_model_id=profile_id)
    _sync_elephant_identity(repository, bundle.elephant_identity, synced_at=synced_at)
    repository.upsert_elephant_identity(bundle.elephant_identity, updated_at=synced_at)


def _sync_elephant_identity(
    repository: RuntimeStorageRepository,
    identity: ElephantIdentityRecord,
    *,
    synced_at: datetime,
) -> str | None:
    for state in repository.list_states():
        if state.elephant_id != identity.elephant_id:
            continue
        repository.upsert_state(
            replace(
                state,
                elephant_name=identity.display_name,
                identity_mode=identity.identity_mode,
                initiative=identity.initiative,
                posture=identity.relational_stance,
                working_style=identity.working_style_contract or identity.personality_preset,
                elephant_identity_text=identity.elephant_identity_text or state.elephant_identity_text,
                source_manifest=identity.source_manifest_path or state.source_manifest,
                metadata={**dict(state.metadata), "profile_id": identity.profile_id},
            ),
            updated_at=synced_at,
        )
        return state.state_id
    return None
