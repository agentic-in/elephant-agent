"""Canonical episode, state, and evidence methods for the API runtime app."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping
from uuid import uuid4

from apps.provider_runtime import provider_profile_from_payload
from packages.contracts import Episode, State
from packages.contracts.runtime import RecallEvidence, PersonalModelRuntimeState
from packages.evidence.recall_runtime import RecallRuntime
from packages.growth import ProgressionProjectionBuilder
from packages.kernel.episode_state_machine import open_next_episode as _open_next_episode
from packages.state.persistence import resolve_runtime_state
from packages.storage.repository_support import canonical_personal_model_id
from packages.operator.runtime import (
    RecallEvidenceOperatorDetail,
    RecallEvidenceSearchHit,
    ProcedureOperatorDetail,
    build_canonical_procedure_detail,
    build_recall_evidence_operator_surface,
)

from .api_runtime_support import (
    APIEpisodeCreationResult,
    APIEpisodeInspection,
    APIEpisodeLifecycleResult,
    APIEpisodeTransitionResult,
    APILoopRecord,
    APILoopResult,
    _now,
    _optional_str,
)
from .state_runtime import APIContinuityInspection

_PROGRESSION_BUILDER = ProgressionProjectionBuilder()


def _latest_loop_record(self, episode_id: str):
    loops = self._loops.get(episode_id, ())
    return loops[-1] if loops else None


def _canonical_procedure_details(self, episode: Episode) -> tuple[ProcedureOperatorDetail, ...]:
    return ()  # Procedural evidence removed.


def _ensure_episode_state(
    self,
    *,
    episode: Episode,
    personal_model: PersonalModelRuntimeState,
) -> State:
    elephant_id = str(episode.elephant_id or "").strip()
    personal_model_id = personal_model.profile_id
    state_anchor = f"elephant:{elephant_id}" if elephant_id else f"personal-model:{personal_model_id}:api"
    state_id = f"state:{elephant_id}" if elephant_id else f"state:{personal_model_id}:api"
    existing = resolve_runtime_state(
        self.repository,
        state_id=state_id,
        episode_id=episode.episode_id,
        personal_model_id=personal_model_id,
        elephant_id=elephant_id or None,
        state_anchor=state_anchor,
        required=False,
    )
    if existing is None:
        state = self.repository.create_state(
            personal_model_id=personal_model_id,
            state_id=state_id,
            state_anchor=state_anchor,
            elephant_id=elephant_id or f"api:{personal_model_id}",
            elephant_name=personal_model.display_name,
            identity_mode=personal_model.mode,
            surface_bindings=("api",),
            summary=f"{personal_model.display_name} is ready for API-bound continuity.",
            metadata={"personal_model_id": personal_model.profile_id, "episode_id": episode.episode_id},
        )
    else:
        state = replace(
            existing,
            elephant_name=personal_model.display_name,
            identity_mode=personal_model.mode,
            state_anchor=state_anchor,
            surface_bindings=tuple(sorted({*existing.surface_bindings, "api"})),
            metadata={**dict(existing.metadata), "personal_model_id": personal_model.profile_id, "episode_id": episode.episode_id},
        )
        self.repository.upsert_state(state)
    self.repository.switch_state(state.state_id)
    return state


def create_episode(
    self,
    *,
    personal_model_id: str,
    display_name: str,
    mode: str,
    elephant_id: str | None = None,
    elephant_path: str | None = None,
    preferences: tuple[str, ...] = (),
    enabled_capabilities: tuple[str, ...] = (),
    provider_profile: Mapping[str, Any] | None = None,
    episode_id: str | None = None,
) -> APIEpisodeCreationResult:
    personal_model = PersonalModelRuntimeState(
        profile_id=canonical_personal_model_id(personal_model_id),
        display_name=display_name,
        mode=mode,
        elephant_path=elephant_path,
        preferences=preferences,
        enabled_capabilities=enabled_capabilities,
    )
    if provider_profile is not None:
        active_profile = provider_profile_from_payload(provider_profile)
        self.auth_store.register(active_profile)
        self.model_provider.set_active_profile(
            provider_profile_id=active_profile.profile_id,
            provider_id=active_profile.provider_id,
        )
    elif self.model_provider.active_profile() is None and self.auth_store.list():
        active_profile = self.auth_store.list()[0]
        self.model_provider.set_active_profile(
            provider_profile_id=active_profile.profile_id,
            provider_id=active_profile.provider_id,
        )
    resolved_elephant_id = elephant_id or personal_model_id
    timestamp = _now()
    resolved_state_id = f"state:{resolved_elephant_id}" if resolved_elephant_id else f"state:{personal_model.profile_id}:api"
    episode = Episode(
        episode_id=episode_id or uuid4().hex,
        state_id=resolved_state_id,
        personal_model_id=personal_model.profile_id,
        entry_surface="api",
        elephant_id=resolved_elephant_id,
        status="open",
        started_at=timestamp,
        updated_at=timestamp,
    )
    self.repository.upsert_personal_model_runtime_state(personal_model, updated_at=timestamp)
    self.repository.upsert_episode_state(episode)
    state = _ensure_episode_state(self, episode=episode, personal_model=personal_model)
    self.personal_state.ensure_personal_model_state(
        personal_model,
        elephant_id=episode.elephant_id or personal_model.profile_id,
        state_id=state.state_id,
        episode_id=episode.episode_id,
        sync_source="api.create-episode",
    )
    return APIEpisodeCreationResult(
        personal_model=personal_model,
        state=state,
        episode=episode,
    )


def interrupt_episode(self, episode_id: str, *, interruption_state: str) -> APIEpisodeLifecycleResult:
    episode = self.repository.refresh_episode_state(
        episode_id,
        status="paused",
        interruption_state=interruption_state,
        updated_at=_now(),
    )
    return APIEpisodeLifecycleResult(episode=episode)


def open_next_episode(self, episode_id: str, *, child_episode_id: str | None = None) -> APIEpisodeTransitionResult:
    transition = _open_next_episode(
        self.repository,
        episode_id,
        reason="api_next_episode",
        current=_now(),
        episode_id=child_episode_id,
        entry_surface="api",
        semantic_summary_indexer=getattr(self, "semantic_summary_indexer", None),
    )
    return APIEpisodeTransitionResult(
        parent_episode=transition.parent_episode,
        episode=transition.episode,
        lineage=transition.lineage,
    )


def list_recall_evidence(self, episode_id: str) -> tuple[RecallEvidence, ...]:
    return tuple(self.recall_runtime.store.list(episode_id=episode_id))


def inspect_identity(
    self,
    *,
    state_id: str | None = None,
    episode_id: str | None = None,
    personal_model_id: str | None = None,
):
    return self.personal_state.inspect_identity(
        state_id=state_id,
        episode_id=episode_id,
        personal_model_id=personal_model_id,
    )


def update_identity_state(
    self,
    *,
    state_id: str | None = None,
    episode_id: str | None = None,
    personal_model_id: str | None = None,
    display_name: str | None = None,
    personality_preset: str | None = None,
    initiative: str | None = None,
    elephant_identity_text: str | None = None,
    clear_elephant_identity: bool = False,
):
    return self.personal_state.update_identity_state(
        state_id=state_id,
        episode_id=episode_id,
        personal_model_id=personal_model_id,
        display_name=display_name,
        personality_preset=personality_preset,
        initiative=initiative,
        elephant_identity_text=elephant_identity_text,
        clear_elephant_identity=clear_elephant_identity,
    )


def inspect_user(
    self,
    *,
    state_id: str | None = None,
    episode_id: str | None = None,
    personal_model_id: str | None = None,
):
    return self.personal_state.inspect_user(
        state_id=state_id,
        episode_id=episode_id,
        personal_model_id=personal_model_id,
    )


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
):
    return self.personal_state.update_user_state(
        state_id=state_id,
        episode_id=episode_id,
        personal_model_id=personal_model_id,
        text=text,
        fields=fields,
        append=append,
        clear=clear,
    )


def inspect_relationship(
    self,
    *,
    state_id: str | None = None,
    episode_id: str | None = None,
    personal_model_id: str | None = None,
):
    return self.personal_state.inspect_relationship(
        state_id=state_id,
        episode_id=episode_id,
        personal_model_id=personal_model_id,
    )


def update_relationship_state(
    self,
    *,
    state_id: str | None = None,
    episode_id: str | None = None,
    personal_model_id: str | None = None,
    text: str | None = None,
    append: bool = False,
    clear: bool = False,
):
    return self.personal_state.update_relationship_state(
        state_id=state_id,
        episode_id=episode_id,
        personal_model_id=personal_model_id,
        text=text,
        append=append,
        clear=clear,
    )


def inspect_continuity(self, state_id: str) -> APIContinuityInspection:
    return self.personal_state.inspect_continuity(state_id)


def inspect_context_frame(self, episode_id: str):
    episode = self.repository.load_episode_state(episode_id)
    if episode is None:
        raise KeyError(episode_id)
    recall_items = self.list_recall_evidence(episode_id)
    latest_loop = _latest_loop_record(self, episode_id)
    recent_loop_context = tuple(
        part
        for part in (
            str(latest_loop.request.get("prompt") or "").strip() if latest_loop is not None else "",
            latest_loop.outcome.execution.summary.strip() if latest_loop is not None else "",
        )
        if part
    )
    return self.context_runtime.assemble_detailed(
        episode,
        (),
        recall_items,
        recent_loop_context=recent_loop_context,
        profile_snapshot_refs=(
            f"personal_model:{episode.personal_model_id}:identity",
            f"personal_model:{episode.personal_model_id}:user",
            f"personal_model:{episode.personal_model_id}:relationship",
        ),
        state_focus=None,
    )


def inspect_recall_evidence_surface(self, episode_id: str):
    evidence_items = tuple(
        RecallEvidenceOperatorDetail(
            evidence=evidence,
            state=self.recall_runtime.store.state(evidence.evidence_id),
            lineage=self.recall_runtime.store.lineage(evidence.evidence_id),
        )
        for evidence in self.list_recall_evidence(episode_id)
    )
    return build_recall_evidence_operator_surface(session_id=episode_id, evidence_items=evidence_items)


def search_recall_evidence_surface(self, episode_id: str, *, query: str, limit: int = 5):
    retrieval = self.recall_runtime.retrieve(
        episode_id,
        query,
        work_item_ids=(),
        limit=limit,
    )
    evidence_items = tuple(
        RecallEvidenceOperatorDetail(
            evidence=evidence,
            state=self.recall_runtime.store.state(evidence.evidence_id),
            lineage=self.recall_runtime.store.lineage(evidence.evidence_id),
        )
        for evidence in self.list_recall_evidence(episode_id)
    )
    hits = tuple(
        RecallEvidenceSearchHit(evidence=candidate.evidence, score=candidate.score, reasons=candidate.reasons)
        for candidate in retrieval.candidates
    )
    return build_recall_evidence_operator_surface(
        session_id=episode_id,
        evidence_items=evidence_items,
        search_query=query,
        search_hits=hits,
        scope_reason=retrieval.scope_reason,
        index_policy=self.recall_runtime.index_policy(),
    )


def inspect_episode(self, episode_id: str) -> APIEpisodeInspection:
    episode = self.repository.load_episode_state(episode_id)
    if episode is None:
        raise KeyError(episode_id)
    personal_model = self.repository.load_personal_model_runtime_state(episode.personal_model_id)
    if personal_model is None:
        raise KeyError(episode.personal_model_id)
    stored_episode = self.repository.load_episode(episode_id)
    if stored_episode is None:
        raise KeyError(episode_id)
    state = self.repository.load_state(stored_episode.state_id)
    if state is None:
        raise KeyError(stored_episode.state_id)
    lineage = self.repository.episode_lineage(episode_id)
    latest_loop = _latest_loop_record(self, episode_id)
    recall_items = tuple(self.recall_runtime.store.list(episode_id=episode_id))
    provider_profile = self.model_provider.active_profile()
    procedures = tuple(detail.procedure for detail in _canonical_procedure_details(self, episode))
    progression = _PROGRESSION_BUILDER.build(
        profile_id=episode.personal_model_id,
        state=self.repository.load_personal_model_growth(episode.personal_model_id),
        experiences=(),
        procedures=procedures,
        active_work_item=None,
        continuity_mode="background" if episode.parent_episode_id is not None else "foreground",
        wake_action="next_episode" if episode.parent_episode_id is not None else "",
    )
    return APIEpisodeInspection(
        personal_model=personal_model,
        state=state,
        episode=episode,
        lineage=lineage,
        recall_items=recall_items,
        latest_loop=latest_loop,
        recall_count=len(recall_items),
        telemetry_count=len(self.telemetry.events),
        provider_profile=provider_profile,
        progression=progression,
    )
