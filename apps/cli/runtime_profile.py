"""Profile, continuity, and canonical identity methods for the CLI runtime."""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from packages.context import ContextAssemblyResult
from packages.contracts.runtime import ElephantIdentityRecord
from packages.state.rendered_views import RenderedRelationshipView, RenderedUserProfileView
from packages.continuity import ContinuityProjectionService
from packages.operator.runtime import (
    RecallEvidenceOperatorDetail,
    RecallEvidenceSearchHit,
    ProcedureOperatorDetail,
    build_canonical_procedure_detail,
    build_recall_evidence_operator_surface,
    build_procedure_operator_surface,
    build_profile_operator_surface,
)
from packages.state import (
    CompanionSettings,
    LoadedProfile,
    read_elephant_identity_file,
    user_profile_updates,
    is_companion_mode,
    normalize_profile_mode,
    render_default_elephant_identity,
    resolve_personality_preset,
    write_elephant_identity_file,
)
from packages.state.canonical import build_canonical_profile_state
from packages.state.persistence import load_persisted_canonical_state
from packages.state.projection import render_user_profile_projection_text
from packages.state.user_updates import apply_user_profile_update
from packages.security import ApprovalClass, SecurityRequest, evaluate_with_telemetry

from .runtime_cognition import _CliContextCapability
from .runtime_extensions import _PreviewTelemetrySink
from .runtime_snapshot import load_snapshot_state_focus
from .runtime_support import ContinuityStatus, _normalized_profile_text


_DEFAULT_ELEPHANT_FOCUS_MARKERS = (
    "open wake to continue the current elephant line",
    "is ready to continue the current elephant line",
)


def _elephant_identity_record_view(record: ElephantIdentityRecord) -> ElephantIdentityRecord:
    return record


def _state_focus_text(state) -> str:
    if state is None:
        return ""
    for candidate in (state.summary,):
        text = str(candidate or "").strip()
        if text and not any(marker in text.casefold() for marker in _DEFAULT_ELEPHANT_FOCUS_MARKERS):
            return text
    return ""


class CliRuntimeProfileMixin:
    def inspect_continuity(self, *, session_id: str | None = None) -> ContinuityStatus:
        session = self.inspect_session(session_id) if session_id is not None else self.latest_session()
        if session is None:
            raise KeyError("latest-session")
        elephant_id = self.elephant_id_for_session(session)
        # Resolve the session's elephant-bound profile so authored ELEPHANT.md
        # text reflects the actual bound elephant, not a personal-model stub.
        from packages.state import load_runtime_profile

        profile = load_runtime_profile(
            self.repository,
            personal_model_id=session.personal_model_id,
            elephant_id=elephant_id or None,
            profile_loader=self.profile_loader,
        )
        lineage = self.repository.episode_lineage(session.episode_id)
        voice_report = self.voice_doctor(profile_id=session.personal_model_id)
        state = None
        if elephant_id:
            state = self.state_for_elephant(elephant_id)
        if state is None:
            state = self.current_elephant_state()
        active_state_focus = _state_focus_text(state)
        identity = self.inspect_identity(profile_id=session.personal_model_id)
        relationship = self.inspect_relationship(profile_id=session.personal_model_id)
        continuity_report = ContinuityProjectionService().inspect(
            profile,
            session,
            lineage=lineage,
            active_state_focus=active_state_focus or None,
            identity_record=identity,
            relationship_record=relationship,
        )
        recovery = self._planning_recall_evidence_recovery(session)
        wake_action = "continue" if active_state_focus else "idle"
        wake_summary = active_state_focus if active_state_focus else "No durable elephant focus is available yet."
        wake_factors: tuple[str, ...] = tuple(("state-continuity", f"recall-scope={','.join(recovery.scope_episode_ids)}"))
        return ContinuityStatus(
            profile=profile,
            session=session,
            relationship_policy=continuity_report.relationship_policy,
            governance_summary=continuity_report.governance.identity.governance_summary,
            proactive_summary=continuity_report.governance.identity.proactive_summary,
            initiative=continuity_report.initiative,
            wake_action=wake_action,
            wake_summary=wake_summary,
            wake_factors=wake_factors,
            reengagement_style=continuity_report.reengagement_style,
            reengagement_prompt=continuity_report.reengagement_prompt,
            continuity_summary=continuity_report.summary,
            voice_status=str(voice_report["status"]),
            voice_identity_binding=str(
                voice_report.get("identity_binding") or continuity_report.voice_identity_binding
            ),
        )

    def inspect_context_frame(self, session_id: str) -> ContextAssemblyResult:
        session = self.inspect_session(session_id)
        recall_items = self.inspect_recall_evidence(session_id)
        state_focus = load_snapshot_state_focus(self, session_id=session_id)
        capability = _CliContextCapability(
            profile_loader=self.profile_loader,
            repository=self.repository,
            prompt_mode="full",
            snapshot_path=self.snapshot_path,
            total_tokens=self.active_provider_context_window(),
            tool_runtime=self.tool_runtime,
            skill_runtime=self.skill_runtime,
            skill_hub=self.skill_hub,
            skill_prompt_context=self.skill_prompt_context,
            install_root=self.paths.home_dir,
            workspaces_dir=self.paths.workspaces_dir,
        )
        return capability.assemble_detailed(session, (), recall_items, state_focus=state_focus)

    def inspect_profile_surface(self, session_id: str):
        session = self.inspect_session(session_id)
        profile = self._load_profile(session.personal_model_id)
        identity = self.inspect_identity(session_id=session_id)
        elephant_state = self.state_for_elephant(self.elephant_id_for_session(session))
        if elephant_state is not None:
            identity = replace(
                identity,
                display_name=elephant_state.elephant_name or identity.display_name,
                elephant_identity_text=elephant_state.elephant_identity_text or identity.elephant_identity_text,
            )
        return build_profile_operator_surface(
            session_id=session_id,
            profile_id=profile.state.profile_id,
            profile_mode=profile.state.mode,
            identity=identity,
            user=self.inspect_user(session_id=session_id),
            relationship=self.inspect_relationship(session_id=session_id),
        )

    def patch_profile_surface(self, session_id: str, payload: dict[str, object]):
        if any(
            key in payload
            for key in {
                "display_name",
                "name",
                "personality_preset",
                "initiative",
                "elephant_identity_text",
                "text",
                "content",
                "clear_elephant_identity",
            }
        ):
            display_name = str(payload.get("display_name") or payload.get("name") or "").strip() or None
            personality_preset = str(payload.get("personality_preset") or "").strip() or None
            initiative = str(payload.get("initiative") or "").strip() or None
            elephant_identity_text = str(payload.get("elephant_identity_text") or payload.get("text") or payload.get("content") or "").strip() or None
            self.update_identity_state(
                session_id=session_id,
                display_name=display_name,
                personality_preset=personality_preset,
                initiative=initiative,
                elephant_identity_text=elephant_identity_text,
                clear_elephant_identity=bool(payload.get("clear_elephant_identity", False)),
            )
        if any(key in payload for key in {"user_text", "user_content", "user_fields", "user_append", "user_clear"}):
            self.update_user_state(
                session_id=session_id,
                text=str(payload.get("user_text") or payload.get("user_content") or "").strip() or None,
                fields=payload.get("user_fields") if isinstance(payload.get("user_fields"), dict) else None,
                append=bool(payload.get("user_append", False)),
                clear=bool(payload.get("user_clear", False)),
            )
        if any(key in payload for key in {"relationship_text", "relationship_content", "relationship_append", "relationship_clear"}):
            self.update_relationship_state(
                session_id=session_id,
                text=str(payload.get("relationship_text") or payload.get("relationship_content") or "").strip() or None,
                append=bool(payload.get("relationship_append", False)),
                clear=bool(payload.get("relationship_clear", False)),
            )
        return self.inspect_profile_surface(session_id)

    def inspect_recall_evidence_surface(self, session_id: str):
        evidence_items = tuple(
            RecallEvidenceOperatorDetail(
                evidence=evidence,
                state=self.recall_evidence_state(evidence.evidence_id),
                lineage=self.recall_evidence_lineage(evidence.evidence_id),
            )
            for evidence in self.inspect_recall_evidence(session_id)
        )
        return build_recall_evidence_operator_surface(session_id=session_id, evidence_items=evidence_items)

    def search_recall_evidence_surface(self, session_id: str, *, query: str, limit: int = 5):
        retrieval = self.retrieve_evidence(session_id, query, limit=limit)
        evidence_items = tuple(
            RecallEvidenceOperatorDetail(
                evidence=evidence,
                state=self.recall_evidence_state(evidence.evidence_id),
                lineage=self.recall_evidence_lineage(evidence.evidence_id),
            )
            for evidence in self.inspect_recall_evidence(session_id)
        )
        return build_recall_evidence_operator_surface(
            session_id=session_id,
            evidence_items=evidence_items,
            search_query=query,
            search_hits=tuple(
                RecallEvidenceSearchHit(
                    evidence=candidate.evidence,
                    score=candidate.score,
                    reasons=tuple(reason.detail for reason in candidate.reasons if reason.detail),
                )
                for candidate in retrieval.candidates
            ),
            scope_reason=retrieval.scope_reason,
            index_policy=retrieval.index_policy,
        )

    def _canonical_procedure_details(self, session_id: str) -> tuple[ProcedureOperatorDetail, ...]:
        return ()  # Procedure projection removed.

    def inspect_procedure_surface(self, session_id: str, *, minimum_support: int = 2):
        session = self.inspect_session(session_id)
        del minimum_support
        return build_procedure_operator_surface(
            session_id=session_id,
            profile_id=session.personal_model_id,
            procedures=(),
            candidates=(),
        )

    def inspect_procedure_detail(self, session_id: str, procedure_id: str):
        raise KeyError(procedure_id)

    def patch_procedure_surface(self, session_id: str, procedure_id: str, payload: dict[str, object]):
        raise KeyError(procedure_id)

    def retire_procedure_surface(self, session_id: str, procedure_id: str):
        raise KeyError(procedure_id)

    def _coerce_str_tuple(self, value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            stripped = value.strip()
            return tuple(part.strip() for part in stripped.split(",") if part.strip()) if stripped else ()
        if isinstance(value, (list, tuple)):
            return tuple(str(item).strip() for item in value if str(item).strip())
        return (str(value).strip(),) if str(value).strip() else ()

    def _session_continuity_state(self, session_id: str, *, session):
        from packages.continuity import build_episode_continuity_state
        return build_episode_continuity_state(
            session,
            lineage=self.repository.episode_lineage(session_id),
        )

    def inspect_profile(self, profile_id: str) -> LoadedProfile:
        return self._load_profile(profile_id)

    def inspect_identity(
        self,
        *,
        session_id: str | None = None,
        profile_id: str | None = None,
    ) -> ElephantIdentityRecord:
        resolved_profile_id = self._resolve_extension_profile_id(
            session_id=session_id,
            profile_id=profile_id,
        )
        loaded = self._load_profile(resolved_profile_id)
        persisted = load_persisted_canonical_state(self.repository, loaded.state.profile_id).elephant_identity
        if persisted is not None:
            return _elephant_identity_record_view(persisted)
        return _elephant_identity_record_view(build_canonical_profile_state(loaded).elephant_identity)

    def inspect_user(
        self,
        *,
        session_id: str | None = None,
        profile_id: str | None = None,
    ) -> RenderedUserProfileView:
        resolved_profile_id = self._resolve_extension_profile_id(
            session_id=session_id,
            profile_id=profile_id,
        )
        loaded = self._load_profile(resolved_profile_id)
        persisted = load_persisted_canonical_state(self.repository, loaded.state.profile_id).user_profile
        if persisted is not None:
            return persisted
        return build_canonical_profile_state(loaded).user_profile

    def inspect_relationship(
        self,
        *,
        session_id: str | None = None,
        profile_id: str | None = None,
    ) -> RenderedRelationshipView:
        resolved_profile_id = self._resolve_extension_profile_id(
            session_id=session_id,
            profile_id=profile_id,
        )
        loaded = self._load_profile(resolved_profile_id)
        persisted = load_persisted_canonical_state(self.repository, loaded.state.profile_id).relationship
        if persisted is not None:
            return persisted
        return build_canonical_profile_state(loaded).relationship

    def current_profile(self) -> LoadedProfile:
        return self._load_profile(self.profile_loader.load_state().profile_id)

    def _authorize_write(
        self,
        *,
        operation: str,
        session_id: str | None = None,
        description: str | None = None,
        is_destructive: bool = False,
        metadata: Mapping[str, str] | None = None,
    ) -> None:
        result = evaluate_with_telemetry(
            self.security_policy,
            SecurityRequest(
                request_id=f"req:cli:{uuid4().hex[:8]}",
                approval_class=ApprovalClass.WRITE,
                operation=operation,
                episode_id=session_id,
                description=description,
                consent_given=True,
                is_destructive=is_destructive,
                metadata=dict(metadata or {}),
            ),
            _PreviewTelemetrySink(self.snapshot_path),
            source="cli.operator",
        )
        if not result.approved:
            raise PermissionError(result.rationale)

    def update_identity(
        self,
        *,
        profile_id: str | None = None,
        display_name: str | None = None,
        mode: str | None = None,
    ) -> LoadedProfile:
        loaded = self._load_profile(profile_id or self.current_profile().state.profile_id)
        self._authorize_write(
            operation="cli.identity.update",
            session_id=self.latest_session().episode_id if self.latest_session() is not None else None,
            description=display_name or loaded.state.display_name,
            metadata={"profile_id": loaded.state.profile_id},
        )
        resolved_mode = loaded.state.mode if mode is None else normalize_profile_mode(mode)
        resolved_companion = loaded.companion
        if mode is not None and not is_companion_mode(resolved_mode):
            resolved_companion = None
        elif is_companion_mode(resolved_mode) and resolved_companion is None:
            resolved_companion = CompanionSettings()
        updated_state = replace(
            loaded.state,
            display_name=loaded.state.display_name if display_name is None else display_name,
            mode=resolved_mode,
        )
        return self._persist_profile(
            LoadedProfile(
                state=updated_state,
                companion=resolved_companion,
                profile_dir=loaded.profile_dir,
                manifest_path=loaded.manifest_path,
                elephant_identity_text=loaded.elephant_identity_text,
                user_profile_text=loaded.user_profile_text,
                user_profile_path=loaded.user_profile_path,
                manifest=dict(loaded.manifest),
            ),
            sync_source="identity.update",
        )

    def update_companion_settings(
        self,
        *,
        session_id: str | None = None,
        profile_id: str | None = None,
        text_first: bool | None = None,
        initiative: str | None = None,
        personality_preset: str | None = None,
        personality: tuple[str, ...] | None = None,
        notes: tuple[str, ...] | None = None,
    ) -> LoadedProfile:
        resolved_profile_id = self._resolve_extension_profile_id(
            session_id=session_id,
            profile_id=profile_id,
        )
        loaded = self._load_profile(resolved_profile_id)
        latest_session = self.latest_session()
        self._authorize_write(
            operation="cli.personality.update",
            session_id=session_id or (latest_session.episode_id if latest_session is not None else None),
            description=personality_preset or initiative or "update identity settings",
            metadata={"profile_id": loaded.state.profile_id},
        )
        current = loaded.companion or CompanionSettings()
        resolved_preset = (
            current.personality_preset
            if personality_preset is None
            else resolve_personality_preset(personality_preset, mode=loaded.state.mode).preset_id
        )
        resolved_personality = current.personality if personality is None else personality
        if personality_preset is not None and personality is None:
            resolved_personality = resolve_personality_preset(resolved_preset, mode=loaded.state.mode).traits
        updated_companion = CompanionSettings(
            text_first=current.text_first if text_first is None else text_first,
            personality_preset=resolved_preset,
            personality=resolved_personality,
            initiative=current.initiative if initiative is None else initiative,
            preserve_relationship_timeline=current.preserve_relationship_timeline,
            preserve_preferences=current.preserve_preferences,
            preserve_corrections=current.preserve_corrections,
            preserve_emotional_context=current.preserve_emotional_context,
            notes=current.notes if notes is None else notes,
        )
        return self._persist_profile(
            LoadedProfile(
                state=loaded.state,
                companion=updated_companion,
                profile_dir=loaded.profile_dir,
                manifest_path=loaded.manifest_path,
                elephant_identity_text=loaded.elephant_identity_text,
                user_profile_text=loaded.user_profile_text,
                user_profile_path=loaded.user_profile_path,
                manifest=dict(loaded.manifest),
            ),
            sync_source="identity.settings.update",
        )

    def update_identity_state(
        self,
        *,
        session_id: str | None = None,
        profile_id: str | None = None,
        display_name: str | None = None,
        personality_preset: str | None = None,
        initiative: str | None = None,
        elephant_identity_text: str | None = None,
        clear_elephant_identity: bool = False,
    ) -> ElephantIdentityRecord:
        resolved_profile_id = self._resolve_extension_profile_id(session_id=session_id, profile_id=profile_id)
        target_session = self.inspect_session(session_id) if session_id is not None else None
        target_elephant_id = self.elephant_id_for_session(target_session) if target_session is not None else ""
        if display_name is not None:
            self.update_identity(profile_id=resolved_profile_id, display_name=display_name)
        if personality_preset is not None or initiative is not None:
            self.update_companion_settings(
                session_id=session_id,
                profile_id=resolved_profile_id,
                personality_preset=personality_preset,
                initiative=initiative,
            )
        loaded = self._load_profile(resolved_profile_id)
        if clear_elephant_identity or elephant_identity_text is not None:
            self._authorize_write(
                operation="cli.identity.surface.update",
                session_id=session_id or (self.latest_session().episode_id if self.latest_session() is not None else None),
                description="update elephant identity",
                metadata={"profile_id": resolved_profile_id, "elephant_id": target_elephant_id},
            )
            if target_session is not None and target_elephant_id:
                elephant_root = self.paths.elephant_file_path(target_elephant_id)
                next_state_text = (
                    render_default_elephant_identity(
                        display_name=display_name or loaded.state.display_name
                    )
                    if clear_elephant_identity
                    else (_normalized_profile_text(elephant_identity_text) or loaded.elephant_identity_text or "")
                )
                write_elephant_identity_file(elephant_root, next_state_text)
                refreshed_state_text = read_elephant_identity_file(elephant_root) or next_state_text
                elephant_state = self.ensure_elephant_state(
                    target_session,
                    elephant_identity_text=refreshed_state_text,
                    elephant_display_name=display_name,
                )
                base_identity = self.inspect_identity(profile_id=resolved_profile_id)
                return replace(
                    base_identity,
                    display_name=elephant_state.elephant_name or display_name or base_identity.display_name,
                    elephant_identity_text=elephant_state.elephant_identity_text or refreshed_state_text,
                )
            loaded = self._persist_profile(
                LoadedProfile(
                    state=loaded.state,
                    companion=loaded.companion,
                    profile_dir=loaded.profile_dir,
                    manifest_path=loaded.manifest_path,
                    elephant_identity_text=None if clear_elephant_identity else _normalized_profile_text(elephant_identity_text),
                    user_profile_text=loaded.user_profile_text,
                    user_profile_path=loaded.user_profile_path,
                    manifest=dict(loaded.manifest),
                ),
                sync_source="identity.state.update",
            )
        if target_session is not None and target_elephant_id and display_name is not None:
            refreshed_state_text = read_elephant_identity_file(self.paths.elephant_file_path(target_elephant_id)) or loaded.elephant_identity_text or ""
            elephant_state = self.ensure_elephant_state(
                target_session,
                elephant_identity_text=refreshed_state_text,
                elephant_display_name=display_name,
            )
            base_identity = self.inspect_identity(profile_id=resolved_profile_id)
            return replace(
                base_identity,
                display_name=elephant_state.elephant_name or display_name or base_identity.display_name,
                elephant_identity_text=elephant_state.elephant_identity_text or refreshed_state_text,
            )
        return self.inspect_identity(profile_id=resolved_profile_id)

    def update_user_state(
        self,
        *,
        session_id: str | None = None,
        profile_id: str | None = None,
        text: str | None = None,
        fields: Mapping[str, object] | None = None,
        append: bool = False,
        clear: bool = False,
    ) -> RenderedUserProfileView:
        resolved_profile_id = self._resolve_extension_profile_id(session_id=session_id, profile_id=profile_id)
        loaded = self._load_profile(resolved_profile_id)
        current_user = self.inspect_user(profile_id=resolved_profile_id)
        self._authorize_write(
            operation="cli.user.update",
            session_id=session_id or (self.latest_session().episode_id if self.latest_session() is not None else None),
            description="update user state",
            metadata={"profile_id": resolved_profile_id},
        )
        next_user = apply_user_profile_update(
            current_user,
            text=_normalized_profile_text(text),
            field_values=user_profile_updates(fields) if fields else None,
            append=append,
            clear=clear,
        )
        self._persist_profile(
            LoadedProfile(
                state=loaded.state,
                companion=loaded.companion,
                profile_dir=loaded.profile_dir,
                manifest_path=loaded.manifest_path,
                elephant_identity_text=loaded.elephant_identity_text,
                user_profile_text=render_user_profile_projection_text(next_user),
                user_profile_path=loaded.user_profile_path,
                manifest=dict(loaded.manifest),
            ),
            sync_source="user.update",
        )
        return self.inspect_user(profile_id=resolved_profile_id)

    def update_relationship_state(
        self,
        *,
        session_id: str | None = None,
        profile_id: str | None = None,
        text: str | None = None,
        append: bool = False,
        clear: bool = False,
    ) -> RenderedRelationshipView:
        resolved_profile_id = self._resolve_extension_profile_id(session_id=session_id, profile_id=profile_id)
        loaded = self._load_profile(resolved_profile_id)
        latest_session = self.latest_session()
        self._authorize_write(
            operation="cli.relationship.update",
            session_id=session_id or (latest_session.episode_id if latest_session is not None else None),
            description="update relationship continuity",
            metadata={"profile_id": resolved_profile_id},
        )
        current = loaded.companion or CompanionSettings()
        current_notes = tuple(note.strip() for note in current.notes if note.strip())
        normalized = tuple(line.strip() for line in (text or "").splitlines() if line.strip())
        if clear:
            next_notes: tuple[str, ...] = ()
        elif append:
            next_notes = current_notes + tuple(note for note in normalized if note not in current_notes)
        elif normalized:
            next_notes = normalized
        else:
            next_notes = current_notes
        updated_companion = CompanionSettings(
            text_first=current.text_first,
            personality_preset=current.personality_preset,
            personality=current.personality,
            initiative=current.initiative,
            preserve_relationship_timeline=current.preserve_relationship_timeline,
            preserve_preferences=current.preserve_preferences,
            preserve_corrections=current.preserve_corrections,
            preserve_emotional_context=current.preserve_emotional_context,
            notes=next_notes,
        )
        self._persist_profile(
            LoadedProfile(
                state=loaded.state,
                companion=updated_companion,
                profile_dir=loaded.profile_dir,
                manifest_path=loaded.manifest_path,
                elephant_identity_text=loaded.elephant_identity_text,
                user_profile_text=loaded.user_profile_text,
                user_profile_path=loaded.user_profile_path,
                manifest=dict(loaded.manifest),
            ),
            sync_source="relationship.update",
        )
        return self.inspect_relationship(profile_id=resolved_profile_id)
