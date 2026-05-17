"""Session, recall, and profile persistence methods for the CLI runtime."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Any
from uuid import uuid4

from packages.contracts.layers import Episode
from packages.contracts.runtime import EvidenceRetrievalRequest, EvidenceRetrievalResult, RecallEvidence
from packages.evidence import (
    UnifiedRecallRequest,
    render_recall_hit,
    unified_recall,
)
from packages.state import (
    LoadedProfile,
    load_runtime_profile,
    read_elephant_identity_file,
)
from packages.state.canonical import build_canonical_profile_state
from packages.state.governance import parse_elephant_identity_display_name
from packages.state.loader import profile_manifest_payload
from packages.state.persistence import (
    load_persisted_canonical_state,
    resolve_runtime_state,
    sync_canonical_profile_state,
)

from .runtime_cognition import (
    _list_scope_recall_evidence,
    _recall_query_seed,
    _recall_query_with_relationship,
    _recall_scope_reason,
    _recall_scope_session_ids,
)
from .runtime_snapshot import load_snapshot_state_focus
from .runtime_support import (
    EggSummary,
    _PlanningRecallRecovery,
    _elephant_state_id,
    _coerce_str_tuple,
    _optional_datetime,
    _utc_now,
)

def _hidden_elephant_id(elephant_id: str) -> bool:
    return str(elephant_id or "").strip().startswith("learn-live")


def _user_visible_episode(episode: Episode) -> bool:
    metadata = dict(episode.metadata)
    if metadata.get("episode_kind") == "sub_agent":
        return False
    if metadata.get("transition_reason") == "sub_agent_child":
        return False
    if str(episode.entry_surface or "").endswith(":sub_agent"):
        return False
    return True


def _episode_opened_key(episode: Episode) -> tuple[datetime, str]:
    return (
        episode.started_at or episode.updated_at or datetime.min.replace(tzinfo=timezone.utc),
        episode.episode_id,
    )


def _latest_lineage_leaf(episodes: tuple[Episode, ...]) -> Episode:
    parent_ids = {episode.parent_episode_id for episode in episodes if episode.parent_episode_id}
    leaves = tuple(episode for episode in episodes if episode.episode_id not in parent_ids)
    candidates = leaves or episodes
    return max(candidates, key=_episode_opened_key)


class CliRuntimeRecordsMixin:
    def inspect_session(self, session_id: str) -> Episode:
        return self._load_session(session_id)

    def recent_sessions(self, *, limit: int = 5) -> tuple[Episode, ...]:
        return self._list_sessions(limit=limit)

    def list_herd(self, *, limit: int = 12) -> tuple[EggSummary, ...]:
        grouped: dict[str, list[Episode]] = {}
        for session in self._list_sessions():
            if not _user_visible_episode(session):
                continue
            elephant_id = self.elephant_id_for_session(session)
            if _hidden_elephant_id(elephant_id):
                continue
            grouped.setdefault(elephant_id, []).append(session)
        herd_items: list[EggSummary] = []
        for elephant_id, sessions in grouped.items():
            latest = _latest_lineage_leaf(tuple(sessions))
            herd_items.append(
                EggSummary(
                    elephant_id=elephant_id,
                    latest_session_id=latest.episode_id,
                    latest_status=latest.status,
                    updated_at=latest.updated_at,
                    session_count=len(sessions),
                )
            )
        herd = tuple(herd_items)
        ordered = tuple(sorted(herd, key=lambda item: (item.updated_at or datetime.min.replace(tzinfo=timezone.utc), item.elephant_id), reverse=True))
        return ordered[:limit]

    def latest_session_for_elephant(self, elephant_id: str) -> Episode | None:
        target = elephant_id.strip()
        if not target:
            return None
        candidates: list[Episode] = []
        for session in self._list_sessions():
            if not _user_visible_episode(session):
                continue
            if self.elephant_id_for_session(session) == target:
                candidates.append(session)
        return _latest_lineage_leaf(tuple(candidates)) if candidates else None

    def session_ids_for_elephant(self, elephant_id: str) -> tuple[str, ...]:
        target = elephant_id.strip()
        if not target:
            return ()
        return tuple(
            session.episode_id
            for session in self._list_sessions()
            if _user_visible_episode(session) and self.elephant_id_for_session(session) == target
        )

    def state_for_elephant(self, elephant_id: str):
        target = elephant_id.strip()
        if not target:
            return None
        return resolve_runtime_state(
            self.repository,
            state_id=_elephant_state_id(target),
            elephant_id=target,
            required=False,
        )

    def current_elephant_state(self):
        return self.repository.current_state()

    def ensure_elephant_state(
        self,
        session: Episode,
        *,
        elephant_identity_text: str | None = None,
        elephant_display_name: str | None = None,
        elephant_mode: str | None = None,
        elephant_companion=None,
    ):
        elephant_id = self.elephant_id_for_session(session)
        loaded = self._load_profile(session.personal_model_id)
        current_state = self.current_elephant_state()
        existing = self.state_for_elephant(elephant_id)
        elephant_file_identity = read_elephant_identity_file(self.paths.elephant_file_path(elephant_id))
        elephant_identity_text = elephant_file_identity or elephant_identity_text or loaded.elephant_identity_text or ""
        effective_display_name = (
            elephant_display_name
            or parse_elephant_identity_display_name(elephant_identity_text)
            or (existing.elephant_name if existing is not None and existing.elephant_name else "")
            or elephant_id.replace("-", " ").replace("_", " ").title()
            or loaded.state.display_name
        )
        effective_mode = elephant_mode or (existing.identity_mode if existing is not None else "") or loaded.state.mode
        effective_companion = elephant_companion or loaded.companion
        effective_initiative = (
            effective_companion.initiative
            if effective_companion is not None
            else (existing.initiative if existing is not None else "")
        )
        effective_working_style = (
            effective_companion.personality_preset
            if effective_companion is not None
            else (existing.working_style if existing is not None else "")
        )
        if existing is None:
            # Seed the Elephant State row with empty current context. Real context arrives via real turns.
            elephant_state = self.repository.create_state(
                state_id=_elephant_state_id(elephant_id),
                personal_model_id=session.personal_model_id,
                elephant_id=elephant_id,
                state_anchor=f"elephant:{elephant_id}",
                elephant_name=effective_display_name,
                identity_mode=effective_mode,
                initiative=effective_initiative,
                working_style=effective_working_style,
                surface_bindings=("cli",),
                elephant_identity_text=elephant_identity_text,
                summary="",
                metadata={"profile_id": session.personal_model_id},
            )
            return self.repository.load_state(elephant_state.state_id) or elephant_state
        # Preserve existing real context on re-sync.
        _seed_summary_markers = {
            "",
            f"{effective_display_name} is ready to continue the current elephant line.",
            "(fake)",
        }
        keep_summary = existing.summary if existing.summary not in _seed_summary_markers else ""
        keep_context_note = (
            existing.current_context_note
            if existing.current_context_note not in _seed_summary_markers
            else ""
        )
        updated = replace(
            existing,
            elephant_name=effective_display_name,
            identity_mode=effective_mode,
            initiative=effective_initiative,
            working_style=effective_working_style,
            surface_bindings=("cli",),
            elephant_identity_text=elephant_identity_text,
            summary=keep_summary,
            current_context_note=keep_context_note,
            metadata={**dict(existing.metadata), "profile_id": session.personal_model_id},
        )
        self.repository.upsert_state(updated)
        refreshed = self.repository.load_state(updated.state_id)
        if refreshed is None:
            raise RuntimeError(f"elephant state missing after sync: {updated.state_id}")
        return refreshed

    def delete_elephant(self, elephant_id: str) -> int:
        session_ids = self.session_ids_for_elephant(elephant_id)
        elephant_state = self.state_for_elephant(elephant_id)
        if not session_ids and elephant_state is None:
            return 0
        deleted_sessions = 0
        if session_ids:
            deleted_sessions = self.repository.delete_episodes(session_ids, delete_orphaned_profiles=False)
        if elephant_state is not None:
            self.repository.delete_state(elephant_state.state_id)
        self._delete_elephant_file_dirs((elephant_id,))
        return deleted_sessions

    def delete_all_elephants(self) -> tuple[int, int]:
        herd = self.list_herd(limit=4096)
        states = tuple(self.repository.list_states())
        elephant_ids = {elephant.elephant_id for elephant in herd}
        elephant_ids.update(state.elephant_id for state in states if state.elephant_id)
        session_ids = tuple(session.episode_id for session in self._list_sessions())
        if not session_ids and not states:
            return (0, 0)
        deleted_sessions = 0
        if session_ids:
            deleted_sessions = self.repository.delete_episodes(session_ids, delete_orphaned_profiles=False)
        for state in states:
            self.repository.delete_state(state.state_id)
        self._delete_elephant_file_dirs(tuple(elephant_ids))
        return (len(elephant_ids), deleted_sessions)

    def _profile_ids_for_sessions(self, session_ids: tuple[str, ...]) -> tuple[str, ...]:
        profile_ids: list[str] = []
        for session_id in session_ids:
            session = self.repository.load_episode_state(session_id)
            if session is not None and session.personal_model_id:
                profile_ids.append(session.personal_model_id)
        return tuple(profile_ids)

    def _delete_elephant_file_dirs(self, elephant_ids: tuple[str, ...]) -> None:
        cleaned_elephant_ids = tuple(dict.fromkeys(elephant_id.strip() for elephant_id in elephant_ids if elephant_id.strip()))
        for elephant_id in cleaned_elephant_ids:
            shutil.rmtree(self.paths.elephant_file_path(elephant_id), ignore_errors=True)

    def elephant_id_for_session(self, session: Episode) -> str:
        if session.elephant_id:
            return session.elephant_id
        # Infer from state_id: state:milo -> milo (exclude non-elephant states like state:xxx:default)
        state_id = str(getattr(session, "state_id", "") or "").strip()
        if state_id.startswith("state:") and ":" not in state_id[len("state:"):]:
            inferred = state_id[len("state:"):]
            if inferred:
                return inferred
        lineage = self.repository.episode_lineage(session.episode_id)
        origin = lineage[0].episode_id if lineage else session.episode_id
        return f"elephant-{origin[:8]}"

    def _list_sessions(self, *, limit: int | None = None) -> tuple[Episode, ...]:
        episodes = sorted(
            self.repository.list_episodes(),
            key=lambda episode: (
                _episode_opened_key(episode)[0].isoformat(),
                episode.episode_id,
            ),
            reverse=True,
        )
        if limit is not None:
            episodes = episodes[:limit]
        sessions: list[Episode] = []
        for episode in episodes:
            session = self.repository.load_episode_state(episode.episode_id)
            if session is not None:
                sessions.append(session)
        return tuple(sessions)

    def latest_session(self) -> Episode | None:
        sessions = self.recent_sessions(limit=1)
        if not sessions:
            return None
        return sessions[0]

    def _planning_recall_evidence_recovery(self, session: Episode, *, limit: int = 8) -> _PlanningRecallRecovery:
        from .runtime_records_planning import plan_recall_evidence_recovery

        return plan_recall_evidence_recovery(self, session, limit=limit)

    def _planning_recall_evidence(self, session: Episode, *, limit: int = 8) -> tuple[RecallEvidence, ...]:
        return self._planning_recall_evidence_recovery(session, limit=limit).recall_items

    def inspect_recall_evidence(self, session_id: str) -> tuple[RecallEvidence, ...]:
        return tuple(self.recall_runtime.store.list(episode_id=session_id))

    def inspect_recall_evidence_item(self, session_id: str, evidence_ref: str) -> RecallEvidence:
        evidence = self.recall_runtime.store.get(evidence_ref)
        if evidence is None or evidence.episode_id != session_id:
            raise KeyError(evidence_ref)
        return evidence

    def recall_evidence_state(self, evidence_ref: str) -> Mapping[str, object]:
        return self.recall_runtime.store.state(evidence_ref)

    def recall_evidence_lineage(self, evidence_ref: str) -> tuple[str, ...]:
        return self.recall_runtime.store.lineage(evidence_ref)

    def list_personal_model_facts(
        self,
        personal_model_id: str,
    ) -> tuple[object, ...]:
        del personal_model_id
        return ()

    def recall_evidence(
        self,
        session_id: str,
        *,
        query: str,
        scope: str = "all",
        time_range: object = None,
        limit: int = 5,
    ) -> Mapping[str, object]:
        """Hybrid recall across Personal Model / State / Episode summaries.

        Delegates to `unified_recall`, which runs the shared
        HybridSemanticSearcher (vector + BM25 + exact + ngram RRF) against
        the durable semantic index, then falls back to
        `rank_recall_candidates` (lexical + CJK) if the backend is cold or
        no hybrid hit comes back. No record ids are returned.
        """
        normalized_scope = scope.strip().lower() or "all"
        if normalized_scope not in {"personal_model", "state", "episodes", "episode", "steps", "sources", "all"}:
            normalized_scope = "all"
        capped = max(1, min(int(limit or 5), 10))

        if normalized_scope == "all":
            scopes: tuple[str, ...] = ("personal_model", "state", "episodes", "steps", "sources")
        else:
            scopes = (normalized_scope,)

        session = self.repository.load_episode_state(session_id)
        personal_model_id = str(getattr(session, "personal_model_id", "") or "").strip() or "you"
        state_id = str(getattr(session, "state_id", "") or "").strip() or None

        searcher = None
        bundle = getattr(self, "semantic_index_bundle", None)
        if bundle is not None:
            searcher = getattr(bundle, "searcher", None)

        from packages.evidence import recall_time_range_from_payload

        request = UnifiedRecallRequest(
            query=query,
            scopes=scopes,
            personal_model_id=personal_model_id,
            state_id=state_id,
            limit=capped,
            time_range=recall_time_range_from_payload(time_range),
        )
        embedding_service = getattr(getattr(self.recall_runtime, "retriever", None), "evidence_retriever", None)
        embedding_service = getattr(embedding_service, "embedding_service", None)
        ranked = unified_recall(
            request,
            repository=self.repository,
            searcher=searcher,
            embedding_service=embedding_service,
        )
        return {
            "scope": normalized_scope,
            "query": query.strip(),
            "time_range": dict(time_range) if isinstance(time_range, dict) else {},
            "hits": tuple(render_recall_hit(hit) for hit in ranked),
        }

    def _load_profile_source(self, profile_id: str) -> LoadedProfile:
        """Extension-manifest overlay — identity comes from the DB separately."""
        return self.profile_loader.load()

    def _load_profile(self, profile_id: str) -> LoadedProfile:
        loaded = load_runtime_profile(
            self.repository,
            personal_model_id=profile_id,
            profile_loader=self.profile_loader,
        )
        # Merge config.yaml extensions into the manifest so extension data is available
        from packages.runtime_config import load_extensions_from_config, global_config_path_for_state_dir, load_global_config
        config_path = global_config_path_for_state_dir(self.paths.state_dir)
        try:
            config = load_global_config(
                config_path,
                state_dir=self.paths.state_dir,
            )
            extensions = load_extensions_from_config(config)
            if extensions:
                merged_manifest = {**dict(loaded.manifest), **extensions}
                loaded = LoadedProfile(
                    state=loaded.state,
                    companion=loaded.companion,
                    profile_dir=loaded.profile_dir,
                    manifest_path=loaded.manifest_path,
                    elephant_identity_text=loaded.elephant_identity_text,
                    user_profile_text=loaded.user_profile_text,
                    user_profile_path=loaded.user_profile_path,
                    manifest=merged_manifest,
                )
        except (OSError, ValueError):
            pass
        return loaded

    def _load_session(self, session_id: str) -> Episode:
        session = self.repository.load_episode_state(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def _load_profile_manifest(self) -> dict[str, Any]:
        """Load extension manifest data from config.yaml."""
        from packages.runtime_config import load_extensions_from_config, global_config_path_for_state_dir, load_global_config
        config_path = global_config_path_for_state_dir(self.paths.state_dir)
        try:
            config = load_global_config(
                config_path,
                state_dir=self.paths.state_dir,
            )
            extensions = load_extensions_from_config(config)
            if extensions:
                return extensions
        except (OSError, ValueError):
            pass
        return {}

    def _write_profile_manifest(self, manifest: Mapping[str, Any]) -> None:
        """Write extension manifest data to config.yaml."""
        from packages.runtime_config import save_extensions_to_config, global_config_path_for_state_dir
        config_path = global_config_path_for_state_dir(self.paths.state_dir)
        save_extensions_to_config(
            config_path,
            state_dir=self.paths.state_dir,
            extensions=manifest,
        )

    def _persist_profile(
        self,
        loaded_profile: LoadedProfile,
        *,
        sync_source: str = "profile.persist",
    ) -> LoadedProfile:
        previous_canonical = load_persisted_canonical_state(self.repository, loaded_profile.state.profile_id)
        latest_session = self.latest_session()
        resolved_state = resolve_runtime_state(
            self.repository,
            personal_model_id=loaded_profile.state.profile_id,
            episode_id=(latest_session.episode_id if latest_session is not None and latest_session.personal_model_id == loaded_profile.state.profile_id else None),
            required=False,
        )
        # Persist identity to SQLite only; no longer writing profile.json
        self.repository.upsert_personal_model_runtime_state(loaded_profile.state)
        canonical_bundle = build_canonical_profile_state(
            loaded_profile,
            elephant_id=resolved_state.elephant_id if resolved_state is not None and resolved_state.elephant_id else None,
        )
        sync_canonical_profile_state(
            self.repository,
            canonical_bundle,
            previous=previous_canonical,
            sync_source=sync_source,
            recall_runtime=self.recall_runtime,
            surface="cli",
            state_id=resolved_state.state_id if resolved_state is not None else None,
            episode_id=(latest_session.episode_id if latest_session is not None and latest_session.personal_model_id == loaded_profile.state.profile_id else None),
        )
        reloaded = self._load_profile(loaded_profile.state.profile_id)
        self.repository.upsert_personal_model_runtime_state(reloaded.state)
        if latest_session is not None and latest_session.personal_model_id == reloaded.state.profile_id:
            self._write_snapshot(
                profile=reloaded.state,
                session=latest_session,
                work_items=(),
                recall_items=self.inspect_recall_evidence(latest_session.episode_id),
                plan=None,
                execution=None,
                delivery=None,
                stages=(),
                event=None,
                elephant_identity_text=reloaded.elephant_identity_text,
                state_focus=load_snapshot_state_focus(self, session_id=latest_session.episode_id),
            )
        return reloaded
