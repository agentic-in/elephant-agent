"""Canonical system-layer repository methods."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Mapping, Sequence
from uuid import uuid4

from packages.contracts import Episode, Loop, PersonalModel, State, Step
from packages.contracts.runtime import (
    LearningJob,
    LoopState,
    LoopStep,
    PendingToolCall,
    PersonalModelGrowthState,
    PersonalModelRuntimeState,
    RetryState,
    WaitCondition,
)

from .repository_support import (
    DEFAULT_PERSONAL_MODEL_DISPLAY_NAME,
    DEFAULT_PERSONAL_MODEL_ID,
    _episode_from_row,
    _iso,
    _json_dict_text,
    _json_mapping,
    _json_text,
    _learning_job_from_row,
    _loop_from_row,
    _mapping_object,
    _personal_model_from_row,
    _state_from_row,
    _step_from_row,
    canonical_personal_model_id,
    canonical_personal_model_ref,
)


def upsert_personal_model(
    self,
    model: PersonalModel,
    *,
    updated_at: datetime | None = None,
) -> None:
    canonical_id = canonical_personal_model_id(model.personal_model_id)
    timestamp = _iso(updated_at)
    created_at = _iso(model.created_at) if model.created_at is not None else timestamp
    updated = _iso(model.updated_at) if model.updated_at is not None else timestamp
    with self.connection() as connection:
        existing = connection.execute(
            "SELECT created_at FROM personal_models WHERE personal_model_id = ?",
            (canonical_id,),
        ).fetchone()
        if existing is not None:
            created_at = str(existing["created_at"])
        connection.execute(
            """
            INSERT INTO personal_models (
                personal_model_id,
                display_name,
                status,
                metadata_json,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(personal_model_id) DO UPDATE SET
                display_name = excluded.display_name,
                status = excluded.status,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                canonical_id,
                model.display_name,
                model.status,
                _json_mapping(dict(model.metadata)),
                created_at,
                updated,
            ),
        )
        connection.commit()


def load_personal_model(self, personal_model_id: str) -> PersonalModel | None:
    canonical_id = canonical_personal_model_id(personal_model_id)
    with self.connection() as connection:
        row = connection.execute(
            """
            SELECT personal_model_id, display_name, status, metadata_json, created_at, updated_at
            FROM personal_models
            WHERE personal_model_id = ?
            """,
            (canonical_id,),
        ).fetchone()
    if row is None:
        return None
    return _personal_model_from_row(row)


def list_personal_models(self) -> tuple[PersonalModel, ...]:
    with self.connection() as connection:
        rows: Sequence[object] = connection.execute(
            """
            SELECT personal_model_id, display_name, status, metadata_json, created_at, updated_at
            FROM personal_models
            ORDER BY created_at ASC, personal_model_id ASC
            """
        ).fetchall()
    return tuple(_personal_model_from_row(row) for row in rows)


def ensure_default_personal_model(
    self,
    *,
    personal_model_id: str = DEFAULT_PERSONAL_MODEL_ID,
    display_name: str = DEFAULT_PERSONAL_MODEL_DISPLAY_NAME,
) -> PersonalModel:
    canonical_id = canonical_personal_model_id(personal_model_id)
    existing = self.load_personal_model(canonical_id)
    if existing is not None:
        _ensure_coverage_gap_question_bank(self, canonical_id)
        return existing
    model = PersonalModel(
        personal_model_id=canonical_id,
        display_name=display_name,
        status="active",
    )
    self.upsert_personal_model(model)
    loaded = self.load_personal_model(canonical_id)
    if loaded is None:
        raise RuntimeError("default PersonalModel was not persisted")
    _ensure_coverage_gap_question_bank(self, canonical_id)
    return loaded


def _ensure_coverage_gap_question_bank(self, personal_model_id: str) -> None:
    """No-op. Questions are now created by the background learning agent."""
    return


def create_state(
    self,
    *,
    personal_model_id: str = DEFAULT_PERSONAL_MODEL_ID,
    elephant_name: str,
    elephant_id: str | None = None,
    state_id: str | None = None,
    state_anchor: str | None = None,
    identity_mode: str = "",
    posture: str = "",
    capability_boundaries: tuple[str, ...] = (),
    initiative: str = "",
    working_style: str = "",
    surface_bindings: tuple[str, ...] = (),
    safety_boundaries: tuple[str, ...] = (),
    disclosure_boundaries: tuple[str, ...] = (),
    source_manifest: str = "",
    elephant_identity_text: str = "",
    summary: str = "",
    current_context_note: str = "",
    metadata: dict[str, str] | None = None,
) -> State:
    canonical_id = canonical_personal_model_id(personal_model_id)
    self.ensure_default_personal_model(personal_model_id=canonical_id)
    resolved_state_id = state_id or f"state-{uuid4().hex}"
    resolved_elephant_id = elephant_id or f"elephant-{uuid4().hex}"
    state = State(
        state_id=resolved_state_id,
        personal_model_id=canonical_id,
        state_anchor=state_anchor or resolved_elephant_id,
        status="active",
        elephant_id=resolved_elephant_id,
        elephant_name=elephant_name,
        identity_mode=identity_mode,
        posture=posture,
        capability_boundaries=capability_boundaries,
        initiative=initiative,
        working_style=working_style,
        surface_bindings=surface_bindings,
        safety_boundaries=safety_boundaries,
        disclosure_boundaries=disclosure_boundaries,
        source_manifest=source_manifest,
        elephant_identity_text=elephant_identity_text,
        summary=summary,
        current_context_note=current_context_note,
        metadata=metadata or {},
    )
    self.upsert_state(state)
    loaded = self.load_state(resolved_state_id)
    if loaded is None:
        raise RuntimeError("elephant State was not persisted")
    return loaded


def upsert_state(
    self,
    state: State,
    *,
    updated_at: datetime | None = None,
) -> None:
    canonical_id = canonical_personal_model_id(state.personal_model_id)
    timestamp = _iso(updated_at)
    created_at = _iso(state.created_at) if state.created_at is not None else timestamp
    updated = _iso(state.updated_at) if state.updated_at is not None else timestamp
    with self.connection() as connection:
        existing = connection.execute(
            "SELECT created_at FROM states WHERE state_id = ?",
            (state.state_id,),
        ).fetchone()
        if existing is not None:
            created_at = str(existing["created_at"])
        connection.execute(
            """
            INSERT INTO states (
                state_id,
                personal_model_id,
                state_anchor,
                status,
                elephant_id,
                elephant_name,
                identity_mode,
                posture,
                capability_boundaries_json,
                initiative,
                working_style,
                surface_bindings_json,
                safety_boundaries_json,
                disclosure_boundaries_json,
                source_manifest,
                elephant_identity_text,
                summary,
                current_context_note,
                metadata_json,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(state_id) DO UPDATE SET
                personal_model_id = excluded.personal_model_id,
                state_anchor = excluded.state_anchor,
                status = excluded.status,
                elephant_id = excluded.elephant_id,
                elephant_name = excluded.elephant_name,
                identity_mode = excluded.identity_mode,
                posture = excluded.posture,
                capability_boundaries_json = excluded.capability_boundaries_json,
                initiative = excluded.initiative,
                working_style = excluded.working_style,
                surface_bindings_json = excluded.surface_bindings_json,
                safety_boundaries_json = excluded.safety_boundaries_json,
                disclosure_boundaries_json = excluded.disclosure_boundaries_json,
                source_manifest = excluded.source_manifest,
                elephant_identity_text = excluded.elephant_identity_text,
                summary = excluded.summary,
                current_context_note = excluded.current_context_note,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                state.state_id,
                canonical_id,
                state.state_anchor,
                state.status,
                state.elephant_id,
                state.elephant_name,
                state.identity_mode,
                state.posture,
                _json_text(state.capability_boundaries),
                state.initiative,
                state.working_style,
                _json_text(state.surface_bindings),
                _json_text(state.safety_boundaries),
                _json_text(state.disclosure_boundaries),
                state.source_manifest,
                state.elephant_identity_text,
                state.summary,
                state.current_context_note,
                _json_mapping(dict(state.metadata)),
                created_at,
                updated,
            ),
        )
        connection.commit()


def load_state(self, state_id: str) -> State | None:
    with self.connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM states
            WHERE state_id = ?
            """,
            (state_id,),
        ).fetchone()
    if row is None:
        return None
    return _state_from_row(row)


def list_states(
    self,
    *,
    personal_model_id: str | None = None,
    status: str | None = None,
) -> tuple[State, ...]:
    clauses: list[str] = []
    parameters: list[str] = []
    if personal_model_id is not None:
        clauses.append("personal_model_id = ?")
        parameters.append(canonical_personal_model_id(personal_model_id))
    if status is not None:
        clauses.append("status = ?")
        parameters.append(status)
    where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""
    with self.connection() as connection:
        rows: Sequence[object] = connection.execute(
            "SELECT * FROM states"
            + (" " + where_sql if where_sql else "")
            + " ORDER BY created_at ASC, state_id ASC",
            tuple(parameters),
        ).fetchall()
    return tuple(_state_from_row(row) for row in rows)


def current_state(self) -> State | None:
    with self.connection() as connection:
        row = connection.execute(
            """
            SELECT states.*
            FROM current_state_bindings
            JOIN states ON states.state_id = current_state_bindings.state_id
            WHERE current_state_bindings.binding_id = 'current'
            """
        ).fetchone()
    if row is None:
        return None
    return _state_from_row(row)


def switch_state(self, state_id: str, *, selected_at: datetime | None = None) -> State:
    state = self.load_state(state_id)
    if state is None:
        raise KeyError(f"State not found: {state_id}")
    with self.connection() as connection:
        connection.execute(
            """
            INSERT INTO current_state_bindings (binding_id, state_id, selected_at)
            VALUES ('current', ?, ?)
            ON CONFLICT(binding_id) DO UPDATE SET
                state_id = excluded.state_id,
                selected_at = excluded.selected_at
            """,
            (state_id, _iso(selected_at)),
        )
        connection.commit()
    return state


def delete_state(self, state_id: str) -> None:
    with self.connection() as connection:
        connection.execute("DELETE FROM states WHERE state_id = ?", (state_id,))
        connection.commit()


def upsert_episode(self, episode: Episode) -> None:
    canonical_id = canonical_personal_model_id(episode.personal_model_id)
    # Ensure the personal model and state exist (FK constraints)
    self.ensure_default_personal_model(personal_model_id=canonical_id)
    existing_state = self.load_state(episode.state_id)
    if existing_state is None:
        self.create_state(
            personal_model_id=canonical_id,
            elephant_id=episode.elephant_id or "",
            elephant_name=episode.elephant_id.replace("-", " ").title() if episode.elephant_id else canonical_id,
            state_id=episode.state_id,
            state_anchor=f"episode:{episode.episode_id}",
            surface_bindings=(episode.entry_surface,),
            metadata={"source": "episode_upsert"},
        )
    with self.connection() as connection:
        connection.execute(
            """
            INSERT INTO episodes (
                episode_id, state_id, personal_model_id, entry_surface, status,
                started_at, ended_at, updated_at, exit_summary,
                elephant_id, parent_episode_id, interruption_state, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(episode_id) DO UPDATE SET
                state_id = excluded.state_id,
                personal_model_id = excluded.personal_model_id,
                entry_surface = excluded.entry_surface,
                status = excluded.status,
                started_at = excluded.started_at,
                ended_at = excluded.ended_at,
                updated_at = excluded.updated_at,
                exit_summary = excluded.exit_summary,
                elephant_id = excluded.elephant_id,
                parent_episode_id = excluded.parent_episode_id,
                interruption_state = excluded.interruption_state,
                metadata_json = excluded.metadata_json
            """,
            (
                episode.episode_id,
                episode.state_id,
                canonical_id,
                episode.entry_surface,
                episode.status,
                _iso(episode.started_at),
                _iso(episode.ended_at) if episode.ended_at is not None else None,
                _iso(episode.updated_at) if episode.updated_at is not None else None,
                episode.exit_summary,
                episode.elephant_id or "",
                episode.parent_episode_id,
                episode.interruption_state,
                _json_mapping(dict(episode.metadata)),
            ),
        )
        connection.commit()


def load_episode(self, episode_id: str) -> Episode | None:
    with self.connection() as connection:
        row = connection.execute("SELECT * FROM episodes WHERE episode_id = ?", (episode_id,)).fetchone()
    return None if row is None else _episode_from_row(row)


def list_episodes(self, *, state_id: str | None = None) -> tuple[Episode, ...]:
    sql = "SELECT * FROM episodes"
    parameters: tuple[str, ...] = ()
    if state_id is not None:
        sql += " WHERE state_id = ?"
        parameters = (state_id,)
    sql += " ORDER BY started_at ASC, episode_id ASC"
    with self.connection() as connection:
        rows = connection.execute(sql, parameters).fetchall()
    return tuple(_episode_from_row(row) for row in rows)


def upsert_loop(self, loop: Loop) -> None:
    canonical_id = canonical_personal_model_id(loop.personal_model_id)
    with self.connection() as connection:
        connection.execute(
            """
            INSERT INTO loops (
                loop_id, episode_id, state_id, personal_model_id, trigger_type,
                status, started_at, ended_at, summary, outcome, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(loop_id) DO UPDATE SET
                episode_id = excluded.episode_id,
                state_id = excluded.state_id,
                personal_model_id = excluded.personal_model_id,
                trigger_type = excluded.trigger_type,
                status = excluded.status,
                started_at = excluded.started_at,
                ended_at = excluded.ended_at,
                summary = excluded.summary,
                outcome = excluded.outcome,
                metadata_json = excluded.metadata_json
            """,
            (
                loop.loop_id,
                loop.episode_id,
                loop.state_id,
                canonical_id,
                loop.trigger_type,
                loop.status,
                _iso(loop.started_at),
                _iso(loop.ended_at) if loop.ended_at is not None else None,
                loop.summary,
                loop.outcome,
                _json_mapping(dict(loop.metadata)),
            ),
        )
        connection.commit()


def load_loop(self, loop_id: str) -> Loop | None:
    with self.connection() as connection:
        row = connection.execute("SELECT * FROM loops WHERE loop_id = ?", (loop_id,)).fetchone()
    return None if row is None else _loop_from_row(row)


def list_loops(self, *, episode_id: str | None = None) -> tuple[Loop, ...]:
    sql = "SELECT * FROM loops"
    parameters: tuple[str, ...] = ()
    if episode_id is not None:
        sql += " WHERE episode_id = ?"
        parameters = (episode_id,)
    sql += " ORDER BY started_at ASC, loop_id ASC"
    with self.connection() as connection:
        rows = connection.execute(sql, parameters).fetchall()
    return tuple(_loop_from_row(row) for row in rows)


def upsert_step(self, step: Step) -> None:
    canonical_id = canonical_personal_model_id(step.personal_model_id)
    with self.connection() as connection:
        connection.execute(
            """
            INSERT INTO steps (
                step_id, loop_id, episode_id, state_id, personal_model_id,
                phase, action, status, sequence, summary, outcome,
                payload_refs_json, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(step_id) DO UPDATE SET
                loop_id = excluded.loop_id,
                episode_id = excluded.episode_id,
                state_id = excluded.state_id,
                personal_model_id = excluded.personal_model_id,
                phase = excluded.phase,
                action = excluded.action,
                status = excluded.status,
                sequence = excluded.sequence,
                summary = excluded.summary,
                outcome = excluded.outcome,
                payload_refs_json = excluded.payload_refs_json,
                metadata_json = excluded.metadata_json,
                created_at = excluded.created_at
            """,
            (
                step.step_id,
                step.loop_id,
                step.episode_id,
                step.state_id,
                canonical_id,
                step.phase,
                step.action,
                step.status,
                step.sequence,
                step.summary,
                step.outcome,
                _json_text(step.payload_refs),
                _json_mapping(dict(step.metadata)),
                _iso(step.created_at),
            ),
        )
        connection.commit()


def load_step(self, step_id: str) -> Step | None:
    with self.connection() as connection:
        row = connection.execute("SELECT * FROM steps WHERE step_id = ?", (step_id,)).fetchone()
    return None if row is None else _step_from_row(row)


def list_steps(self, *, loop_id: str | None = None) -> tuple[Step, ...]:
    sql = "SELECT * FROM steps"
    parameters: tuple[str, ...] = ()
    if loop_id is not None:
        sql += " WHERE loop_id = ?"
        parameters = (loop_id,)
    sql += " ORDER BY sequence ASC, created_at ASC"
    with self.connection() as connection:
        rows = connection.execute(sql, parameters).fetchall()
    return tuple(_step_from_row(row) for row in rows)


def _parse_datetime(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_optional_datetime(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    return _parse_datetime(value)


def _iso_optional_datetime(value: datetime | None) -> str | None:
    return None if value is None else _iso(value)


def _parse_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return ()
    if not isinstance(parsed, list):
        return ()
    return tuple(str(item) for item in parsed if str(item))


def _json_metadata(values: Mapping[str, object]) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for key, value in values.items():
        if value is None:
            continue
        if isinstance(value, (tuple, list, dict)):
            metadata[str(key)] = json.dumps(value, separators=(",", ":"), sort_keys=True, default=str)
        else:
            metadata[str(key)] = str(value)
    return metadata


def _profile_metadata(profile: PersonalModelRuntimeState) -> dict[str, str]:
    return _json_metadata(
        {
            "mode": profile.mode,
            "elephant_path": profile.elephant_path,
            "preferences": tuple(profile.preferences),
            "enabled_capabilities": tuple(profile.enabled_capabilities),
            "learning_intensity": profile.learning_intensity,
        }
    )


def _profile_from_personal_model(model: PersonalModel) -> PersonalModelRuntimeState:
    return PersonalModelRuntimeState(
        profile_id=model.personal_model_id,
        display_name=model.display_name,
        mode=model.metadata.get("mode", "default"),
        elephant_path=model.metadata.get("elephant_path") or None,
        preferences=_parse_tuple(model.metadata.get("preferences")),
        enabled_capabilities=_parse_tuple(model.metadata.get("enabled_capabilities")),
        learning_intensity=str(model.metadata.get("learning_intensity") or "medium").strip().lower() or "medium",
    )


def upsert_personal_model_runtime_state(
    self,
    profile: PersonalModelRuntimeState,
    *,
    updated_at: datetime | None = None,
) -> None:
    canonical_id = canonical_personal_model_id(profile.profile_id)
    existing = self.load_personal_model(canonical_id)
    model = PersonalModel(
        personal_model_id=canonical_id,
        display_name=profile.display_name,
        status=existing.status if existing is not None else "active",
        created_at=existing.created_at if existing is not None else updated_at,
        updated_at=updated_at,
        metadata=_profile_metadata(profile),
    )
    self.upsert_personal_model(model, updated_at=updated_at)


def load_personal_model_runtime_state(self, profile_id: str) -> PersonalModelRuntimeState | None:
    model = self.load_personal_model(canonical_personal_model_id(profile_id))
    if model is None:
        return None
    return _profile_from_personal_model(model)


def _state_elephant_name(elephant_id: str, fallback: str) -> str:
    return elephant_id.replace("-", " ").replace("_", " ").title() if elephant_id else fallback


def _state_for_elephant(self, elephant_id: str, personal_model_id: str) -> State | None:
    for state in self.list_states(personal_model_id=personal_model_id):
        if state.elephant_id == elephant_id:
            return state
    return None


def _episode_metadata(episode: Episode, previous: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build metadata dict for an episode (legacy compatibility)."""
    metadata = dict(previous or {})
    metadata.update(
        _json_metadata(
            {
                "updated_at": _iso(episode.updated_at) if episode.updated_at else "",
                "elephant_id": episode.elephant_id,
                "parent_episode_id": episode.parent_episode_id,
                "interruption_state": episode.interruption_state,
            }
        )
    )
    return metadata


def upsert_episode_state(self, episode: Episode) -> None:
    """Compatibility: accepts Episode and upserts it directly."""
    self.upsert_episode(episode)


def load_episode_state(self, episode_id: str) -> Episode | None:
    """Compatibility: returns Episode directly."""
    return self.load_episode(episode_id)


def refresh_episode_state(
    self,
    episode_id: str,
    *,
    status: str,
    interruption_state: str | None,
    updated_at: datetime,
) -> Episode:
    episode = self.load_episode(episode_id)
    if episode is None:
        raise KeyError(episode_id)
    from dataclasses import replace
    updated = replace(
        episode,
        status=status,
        updated_at=updated_at,
        interruption_state=interruption_state,
    )
    self.upsert_episode(updated)
    return updated


def record_episode_transition(
    self,
    parent_episode_id: str,
    child_episode_id: str,
    transitioned_at: datetime,
    *,
    reason: str = "",
) -> None:
    parent = self.load_episode(parent_episode_id)
    if parent is None:
        raise KeyError(parent_episode_id)
    transition_count = int(parent.metadata.get("transition_count", "0") or 0) + 1
    self.upsert_episode(
        Episode(
            episode_id=parent.episode_id,
            state_id=parent.state_id,
            personal_model_id=parent.personal_model_id,
            entry_surface=parent.entry_surface,
            status=parent.status,
            started_at=parent.started_at,
            ended_at=parent.ended_at,
            updated_at=parent.updated_at,
            exit_summary=parent.exit_summary,
            elephant_id=parent.elephant_id,
            parent_episode_id=parent.parent_episode_id,
            interruption_state=parent.interruption_state,
            metadata={
                **dict(parent.metadata),
                "transition_count": str(transition_count),
                "last_child_episode_id": child_episode_id,
                "last_transition_at": _iso(transitioned_at),
                "last_transition_reason": reason,
            },
        )
    )


def episode_lineage(self, episode_id: str) -> tuple[Episode, ...]:
    lineage: list[Episode] = []
    seen: set[str] = set()
    current = self.load_episode(episode_id)
    while current is not None and current.episode_id not in seen:
        lineage.append(current)
        seen.add(current.episode_id)
        if current.parent_episode_id is None:
            break
        current = self.load_episode(current.parent_episode_id)
    return tuple(reversed(lineage))


def delete_episodes(
    self,
    episode_ids: tuple[str, ...],
    *,
    delete_orphaned_profiles: bool = False,
) -> int:
    resolved_episode_ids = tuple(dict.fromkeys(episode_id.strip() for episode_id in episode_ids if episode_id.strip()))
    if not resolved_episode_ids:
        return 0
    profile_ids: list[str] = []
    deleted = 0
    with self.connection() as connection:
        for episode_id in resolved_episode_ids:
            row = connection.execute(
                "SELECT personal_model_id FROM episodes WHERE episode_id = ?",
                (episode_id,),
            ).fetchone()
            if row is None:
                continue
            profile_ids.append(str(row["personal_model_id"]))
            cursor = connection.execute("DELETE FROM episodes WHERE episode_id = ?", (episode_id,))
            deleted += cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
        connection.commit()
    if delete_orphaned_profiles and profile_ids:
        self.delete_orphaned_profiles(tuple(profile_ids))
    return deleted


def delete_orphaned_profiles(
    self,
    profile_ids: tuple[str, ...],
) -> int:
    resolved_profile_ids = tuple(
        dict.fromkeys(
            canonical_personal_model_id(profile_id)
            for profile_id in profile_ids
            if str(profile_id).strip()
        )
    )
    if not resolved_profile_ids:
        return 0
    deleted = 0
    with self.connection() as connection:
        for profile_id in resolved_profile_ids:
            remaining_episode = connection.execute(
                "SELECT 1 FROM episodes WHERE personal_model_id = ? LIMIT 1",
                (profile_id,),
            ).fetchone()
            if remaining_episode is not None:
                continue
            cursor = connection.execute(
                "DELETE FROM personal_models WHERE personal_model_id = ?",
                (profile_id,),
            )
            deleted += cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
        connection.commit()
    return deleted


def upsert_personal_model_growth(
    self,
    state: PersonalModelGrowthState,
) -> None:
    canonical_id = canonical_personal_model_id(state.profile_id)
    now = datetime.now(timezone.utc)
    with self.connection() as connection:
        connection.execute(
            """INSERT INTO personal_model_growth (
                profile_id, growth_score, total_dialogues, total_tokens,
                total_experiences, promoted_experiences, active_days, streak_days,
                first_dialogue_at, last_dialogue_at, last_active_day,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(profile_id) DO UPDATE SET
                growth_score = excluded.growth_score,
                total_dialogues = excluded.total_dialogues,
                total_tokens = excluded.total_tokens,
                total_experiences = excluded.total_experiences,
                promoted_experiences = excluded.promoted_experiences,
                active_days = excluded.active_days,
                streak_days = excluded.streak_days,
                first_dialogue_at = excluded.first_dialogue_at,
                last_dialogue_at = excluded.last_dialogue_at,
                last_active_day = excluded.last_active_day,
                updated_at = excluded.updated_at
            """,
            (
                canonical_id,
                state.growth_score,
                state.total_dialogues,
                state.total_tokens,
                state.total_experiences,
                state.promoted_experiences,
                state.active_days,
                state.streak_days,
                _iso_optional_datetime(state.first_dialogue_at),
                _iso_optional_datetime(state.last_dialogue_at),
                state.last_active_day,
                _iso_optional_datetime(state.created_at) or _iso(now),
                _iso_optional_datetime(state.updated_at) or _iso(now),
            ),
        )
        connection.commit()


def load_personal_model_growth(
    self,
    profile_id: str,
) -> PersonalModelGrowthState | None:
    canonical_id = canonical_personal_model_id(profile_id)
    with self.connection() as connection:
        row = connection.execute(
            "SELECT * FROM personal_model_growth WHERE profile_id = ?",
            (canonical_id,),
        ).fetchone()
    if row is None:
        return None
    return PersonalModelGrowthState(
        profile_id=str(row[0]),
        growth_score=int(row[1]),
        total_dialogues=int(row[2]),
        total_tokens=int(row[3]),
        total_experiences=int(row[4]),
        promoted_experiences=int(row[5]),
        active_days=int(row[6]),
        streak_days=int(row[7]),
        first_dialogue_at=_parse_optional_datetime(row[8]),
        last_dialogue_at=_parse_optional_datetime(row[9]),
        last_active_day=row[10] if row[10] is not None else None,
        created_at=_parse_optional_datetime(row[11]),
        updated_at=_parse_optional_datetime(row[12]),
    )


def enqueue_learning_job(
    self,
    *,
    job_type: str,
    trigger: str,
    personal_model_id: str,
    state_id: str,
    episode_id: str,
    loop_id: str | None = None,
    summary: str = "",
    metadata: Mapping[str, str] | None = None,
    available_at: datetime | None = None,
    max_attempts: int = 3,
    force_new: bool = False,
) -> LearningJob:
    canonical_id = canonical_personal_model_id(personal_model_id)
    existing = None if force_new else load_learning_job_for_episode(self, job_type=job_type, episode_id=episode_id)
    if existing is not None and existing.status in {"queued", "running", "completed"}:
        return existing
    created_at = datetime.now(timezone.utc)
    job_id = existing.job_id if existing is not None else f"learning-job:{uuid4().hex}"
    queued = LearningJob(
        job_id=job_id,
        job_type=job_type,
        trigger=trigger,
        status="queued",
        personal_model_id=canonical_id,
        state_id=state_id,
        episode_id=episode_id,
        loop_id=loop_id,
        summary=summary,
        progress_stage="queued",
        progress_detail="queued for background learning",
        attempt_count=existing.attempt_count if existing is not None else 0,
        max_attempts=max(1, max_attempts),
        available_at=available_at or created_at,
        created_at=existing.created_at if existing is not None else created_at,
        started_at=None,
        finished_at=None,
        worker_id=None,
        last_error="",
        metadata=dict(metadata or (existing.metadata if existing is not None else {})),
        result_json=dict(existing.result_json) if existing is not None else {},
    )
    with self.connection() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO learning_jobs (
                job_id,
                job_type,
                trigger,
                status,
                personal_model_id,
                state_id,
                episode_id,
                loop_id,
                summary,
                progress_stage,
                progress_detail,
                attempt_count,
                max_attempts,
                available_at,
                created_at,
                started_at,
                finished_at,
                worker_id,
                last_error,
                metadata_json,
                result_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                queued.job_id,
                queued.job_type,
                queued.trigger,
                queued.status,
                queued.personal_model_id,
                queued.state_id,
                queued.episode_id,
                queued.loop_id or "",
                queued.summary,
                queued.progress_stage,
                queued.progress_detail,
                queued.attempt_count,
                queued.max_attempts,
                _iso(queued.available_at),
                _iso(queued.created_at),
                _iso_optional_datetime(queued.started_at),
                _iso_optional_datetime(queued.finished_at),
                queued.worker_id or "",
                queued.last_error,
                _json_mapping(dict(queued.metadata)),
                _json_dict_text(dict(queued.result_json)),
            ),
        )
        connection.commit()
    loaded = self.load_learning_job(queued.job_id)
    if loaded is None:
        raise RuntimeError("learning job was not persisted")
    return loaded


def load_learning_job(self, job_id: str) -> LearningJob | None:
    with self.connection() as connection:
        row = connection.execute(
            "SELECT * FROM learning_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
    if row is None:
        return None
    return _learning_job_from_row(row)



def load_learning_job_for_episode(self, *, job_type: str, episode_id: str) -> LearningJob | None:
    with self.connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM learning_jobs
            WHERE job_type = ? AND episode_id = ?
            ORDER BY created_at DESC, job_id DESC
            LIMIT 1
            """,
            (job_type, episode_id),
        ).fetchone()
    if row is None:
        return None
    return _learning_job_from_row(row)



def list_learning_jobs(
    self,
    *,
    statuses: tuple[str, ...] = (),
    state_id: str | None = None,
    personal_model_id: str | None = None,
    episode_id: str | None = None,
    limit: int | None = None,
) -> tuple[LearningJob, ...]:
    clauses: list[str] = []
    parameters: list[object] = []
    if statuses:
        placeholders = ", ".join("?" for _ in statuses)
        clauses.append(f"status IN ({placeholders})")
        parameters.extend(statuses)
    if state_id is not None:
        clauses.append("state_id = ?")
        parameters.append(state_id)
    if personal_model_id is not None:
        clauses.append("personal_model_id = ?")
        parameters.append(canonical_personal_model_id(personal_model_id))
    if episode_id is not None:
        clauses.append("episode_id = ?")
        parameters.append(episode_id)
    where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""
    limit_sql = ""
    if limit is not None and limit > 0:
        limit_sql = " LIMIT ?"
        parameters.append(limit)
    with self.connection() as connection:
        rows: Sequence[object] = connection.execute(
            "SELECT * FROM learning_jobs"
            + (" " + where_sql if where_sql else "")
            + " ORDER BY created_at DESC, job_id DESC" + limit_sql,
            tuple(parameters),
        ).fetchall()
    return tuple(_learning_job_from_row(row) for row in rows)



def claim_learning_job(self, *, worker_id: str, now: datetime | None = None) -> LearningJob | None:
    claimed_at = now or datetime.now(timezone.utc)
    with self.connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """
            SELECT *
            FROM learning_jobs
            WHERE status = 'queued'
              AND available_at <= ?
            ORDER BY available_at ASC, created_at ASC, job_id ASC
            LIMIT 1
            """,
            (_iso(claimed_at),),
        ).fetchone()
        if row is None:
            connection.commit()
            return None
        connection.execute(
            """
            UPDATE learning_jobs
            SET status = 'running',
                progress_stage = 'starting',
                progress_detail = 'worker claimed job',
                attempt_count = attempt_count + 1,
                started_at = ?,
                finished_at = NULL,
                worker_id = ?,
                last_error = ''
            WHERE job_id = ?
            """,
            (_iso(claimed_at), worker_id, str(row["job_id"])),
        )
        connection.commit()
    return self.load_learning_job(str(row["job_id"]))



def update_learning_job_progress(
    self,
    job_id: str,
    *,
    worker_id: str,
    progress_stage: str,
    progress_detail: str = "",
) -> LearningJob:
    with self.connection() as connection:
        connection.execute(
            """
            UPDATE learning_jobs
            SET progress_stage = ?,
                progress_detail = ?,
                worker_id = ?
            WHERE job_id = ?
            """,
            (progress_stage, progress_detail, worker_id, job_id),
        )
        connection.commit()
    loaded = self.load_learning_job(job_id)
    if loaded is None:
        raise KeyError(job_id)
    return loaded



def write_learning_job_result(
    self,
    job_id: str,
    result: Mapping[str, object],
    *,
    worker_id: str = "learning-result",
    progress_detail: str = "learning result written",
    overwrite: bool = False,
) -> LearningJob:
    existing = self.load_learning_job(job_id)
    if existing is None:
        raise KeyError(job_id)
    if existing.result_json and not overwrite:
        raise ValueError(f"learning result already written for job: {job_id}")
    payload = dict(result)
    with self.connection() as connection:
        connection.execute(
            """
            UPDATE learning_jobs
            SET result_json = ?,
                progress_stage = 'result_written',
                progress_detail = ?,
                worker_id = ?
            WHERE job_id = ?
            """,
            (_json_dict_text(payload), progress_detail, worker_id, job_id),
        )
        connection.commit()
    loaded = self.load_learning_job(job_id)
    if loaded is None:
        raise KeyError(job_id)
    return loaded



def complete_learning_job(
    self,
    job_id: str,
    *,
    worker_id: str,
    finished_at: datetime | None = None,
    progress_detail: str = "background learning completed",
) -> LearningJob:
    completed_at = finished_at or datetime.now(timezone.utc)
    with self.connection() as connection:
        connection.execute(
            """
            UPDATE learning_jobs
            SET status = 'completed',
                progress_stage = 'completed',
                progress_detail = ?,
                finished_at = ?,
                worker_id = ?
            WHERE job_id = ?
            """,
            (progress_detail, _iso(completed_at), worker_id, job_id),
        )
        connection.commit()
    loaded = self.load_learning_job(job_id)
    if loaded is None:
        raise KeyError(job_id)
    return loaded



def fail_learning_job(
    self,
    job_id: str,
    *,
    worker_id: str,
    error: str,
    finished_at: datetime | None = None,
    retry_delay_seconds: int = 0,
) -> LearningJob:
    failed_at = finished_at or datetime.now(timezone.utc)
    existing = self.load_learning_job(job_id)
    if existing is None:
        raise KeyError(job_id)
    will_retry = existing.attempt_count < existing.max_attempts
    next_status = "queued" if will_retry else "failed"
    next_stage = "retrying" if will_retry else "failed"
    next_detail = "retry scheduled" if will_retry else "background learning failed"
    available_at = failed_at if retry_delay_seconds <= 0 else failed_at.replace(microsecond=0) + timedelta(seconds=retry_delay_seconds)
    with self.connection() as connection:
        connection.execute(
            """
            UPDATE learning_jobs
            SET status = ?,
                progress_stage = ?,
                progress_detail = ?,
                available_at = ?,
                finished_at = ?,
                worker_id = ?,
                last_error = ?
            WHERE job_id = ?
            """,
            (
                next_status,
                next_stage,
                next_detail,
                _iso(available_at),
                _iso(failed_at) if not will_retry else None,
                worker_id,
                error.strip(),
                job_id,
            ),
        )
        connection.commit()
    loaded = self.load_learning_job(job_id)
    if loaded is None:
        raise KeyError(job_id)
    return loaded



_LOOP_STATE_SCHEMA_VERSION = 2


def _wait_condition_to_mapping(condition: WaitCondition | None) -> Mapping[str, object] | None:
    if condition is None:
        return None
    payload = dict(condition.payload or {})
    event_match = dict(condition.event_match or {}) if condition.event_match is not None else None
    return {
        "kind": condition.kind,
        "payload": payload,
        "wake_at": _iso_optional_datetime(condition.wake_at),
        "event_topic": condition.event_topic,
        "event_match": event_match,
        "tool_handle_id": condition.tool_handle_id,
        "created_at": _iso_optional_datetime(condition.created_at),
        "auto_wake": condition.auto_wake,
    }


def _wait_condition_from_mapping(value: object) -> WaitCondition | None:
    if value is None:
        return None
    parsed = _maybe_json_mapping(value)
    if parsed is None:
        return None
    kind = str(parsed.get("kind") or "").strip()
    if not kind:
        return None
    payload_raw = parsed.get("payload") or {}
    payload = {str(k): str(v) for k, v in dict(payload_raw).items()} if isinstance(payload_raw, Mapping) else {}
    event_match_raw = parsed.get("event_match")
    event_match: Mapping[str, str] | None
    if isinstance(event_match_raw, Mapping):
        event_match = {str(k): str(v) for k, v in event_match_raw.items()}
    else:
        event_match = None
    return WaitCondition(
        kind=kind,
        payload=payload,
        wake_at=_parse_optional_datetime(parsed.get("wake_at")),
        event_topic=(str(parsed.get("event_topic")) if parsed.get("event_topic") else None),
        event_match=event_match,
        tool_handle_id=(str(parsed.get("tool_handle_id")) if parsed.get("tool_handle_id") else None),
        created_at=_parse_optional_datetime(parsed.get("created_at")),
        auto_wake=bool(parsed.get("auto_wake", True)),
    )


def _retry_state_to_mapping(state: RetryState | None) -> Mapping[str, object] | None:
    if state is None:
        return None
    return {
        "attempt": int(state.attempt),
        "last_error_kind": state.last_error_kind,
        "last_error_detail": state.last_error_detail,
        "next_retry_at": _iso_optional_datetime(state.next_retry_at),
        "idempotency_key": state.idempotency_key,
    }


def _retry_state_from_mapping(value: object) -> RetryState | None:
    if value is None:
        return None
    parsed = _maybe_json_mapping(value)
    if parsed is None:
        return None
    return RetryState(
        attempt=int(parsed.get("attempt") or 0),
        last_error_kind=str(parsed.get("last_error_kind") or ""),
        last_error_detail=str(parsed.get("last_error_detail") or ""),
        next_retry_at=_parse_optional_datetime(parsed.get("next_retry_at")),
        idempotency_key=(str(parsed.get("idempotency_key")) if parsed.get("idempotency_key") else None),
    )


def _pending_tool_call_to_mapping(call: PendingToolCall) -> Mapping[str, object]:
    arguments = dict(call.arguments or {})
    return {
        "call_id": call.call_id,
        "tool_name": call.tool_name,
        "arguments": arguments,
        "started_at": _iso_optional_datetime(call.started_at),
        "step_id": call.step_id,
        "handle_id": call.handle_id,
        "status": call.status,
        "idempotency_key": call.idempotency_key,
    }


def _pending_tool_calls_to_list(calls: tuple[PendingToolCall, ...]) -> list[Mapping[str, object]]:
    return [_pending_tool_call_to_mapping(call) for call in calls]


def _pending_tool_calls_from_value(value: object) -> tuple[PendingToolCall, ...]:
    if value is None:
        return ()
    parsed: object
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return ()
    else:
        parsed = value
    if not isinstance(parsed, list):
        return ()
    calls: list[PendingToolCall] = []
    for item in parsed:
        if not isinstance(item, Mapping):
            continue
        started_at = _parse_optional_datetime(item.get("started_at")) or datetime.now(timezone.utc)
        arguments_raw = item.get("arguments") or {}
        arguments = dict(arguments_raw) if isinstance(arguments_raw, Mapping) else {}
        calls.append(
            PendingToolCall(
                call_id=str(item.get("call_id") or ""),
                tool_name=str(item.get("tool_name") or ""),
                arguments=arguments,
                started_at=started_at,
                step_id=str(item.get("step_id") or ""),
                handle_id=(str(item.get("handle_id")) if item.get("handle_id") else None),
                status=str(item.get("status") or "dispatched"),
                idempotency_key=(
                    str(item.get("idempotency_key"))
                    if item.get("idempotency_key") is not None and str(item.get("idempotency_key")).strip()
                    else None
                ),
            )
        )
    return tuple(calls)


def _maybe_json_mapping(value: object) -> Mapping[str, object] | None:
    """Decode a JSON-encoded mapping stored in Loop.metadata.

    ``_json_metadata`` persists dict/list values as JSON strings so the
    sqlite text columns stay text. Reading them back therefore needs a
    JSON decode step. Any value that cannot be parsed into a mapping
    returns None so callers can fall back to defaults.
    """
    if isinstance(value, Mapping):
        return {str(k): v for k, v in value.items()}
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            parsed = json.loads(stripped)
        except (TypeError, ValueError):
            return None
        if isinstance(parsed, Mapping):
            return {str(k): v for k, v in parsed.items()}
    return None


def _active_evidence_refs_from_value(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (tuple, list)):
        return tuple(str(item) for item in value if str(item).strip())
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return ()
        try:
            parsed = json.loads(stripped)
        except (TypeError, ValueError):
            return ()
        if isinstance(parsed, list):
            return tuple(str(item) for item in parsed if str(item).strip())
    return ()


def migrate_loop_state_metadata(metadata: Mapping[str, object]) -> dict[str, object]:
    """Normalize Loop.metadata into schema v2 shape.

    v1 rows (pre-harness) only carried the legacy budget reason in
    ``waiting_reason``. v2 writers always emit ``schema_version=2`` and the
    new keys (``wait_condition``, ``pending_tool_calls``, ``retry_state``,
    ``partial_assistant``, ``context_bundle_id``, ``active_evidence_refs``,
    ``heartbeat_at``, ``crash_marker``). The return value is a plain
    dictionary suitable for ``LoopState`` construction (not for
    re-serialization).
    """
    data = dict(metadata)
    schema_version = int(data.get("schema_version") or 0)
    if schema_version >= _LOOP_STATE_SCHEMA_VERSION:
        return data
    legacy_reason = (str(data.get("waiting_reason") or "").strip()) or None
    if legacy_reason and "wait_condition" not in data:
        data["wait_condition"] = {
            "kind": "budget_exhausted",
            "payload": {"legacy_reason": legacy_reason},
            "auto_wake": False,
        }
    data.setdefault("pending_tool_calls", [])
    data.setdefault("partial_assistant", None)
    data.setdefault("context_bundle_id", None)
    data.setdefault("active_evidence_refs", [])
    data.setdefault("retry_state", None)
    data.setdefault("heartbeat_at", None)
    data.setdefault("crash_marker", None)
    data["schema_version"] = _LOOP_STATE_SCHEMA_VERSION
    return data


def _loop_metadata(run: LoopState) -> dict[str, str]:
    return _json_metadata(
        {
            "kind": "loop_checkpoint",
            "schema_version": _LOOP_STATE_SCHEMA_VERSION,
            "source_event_id": run.source_event_id,
            "prompt": run.prompt,
            "phase": run.phase,
            "step_count": run.step_count,
            "model_turn_count": run.model_turn_count,
            "tool_call_count": run.tool_call_count,
            "max_model_turns": run.max_model_turns,
            "max_wall_time_seconds": run.max_wall_time_seconds,
            "waiting_reason": run.waiting_reason,
            "continuation_prompt": run.continuation_prompt,
            "last_summary": run.last_summary,
            "wait_condition": _wait_condition_to_mapping(run.wait_condition),
            "pending_tool_calls": _pending_tool_calls_to_list(run.pending_tool_calls),
            "partial_assistant": run.partial_assistant,
            "context_bundle_id": run.context_bundle_id,
            "active_evidence_refs": list(run.active_evidence_refs),
            "retry_state": _retry_state_to_mapping(run.retry_state),
            "heartbeat_at": _iso_optional_datetime(run.heartbeat_at),
            "crash_marker": run.crash_marker,
        }
    )


def _loop_state_from_loop(loop: Loop) -> LoopState:
    metadata = migrate_loop_state_metadata(dict(loop.metadata))
    return LoopState(
        run_id=loop.loop_id,
        episode_id=loop.episode_id,
        source_event_id=str(metadata.get("source_event_id") or ""),
        prompt=str(metadata.get("prompt") or ""),
        status=loop.status,
        phase=str(metadata.get("phase") or "model"),
        step_count=int(metadata.get("step_count") or 0),
        model_turn_count=int(metadata.get("model_turn_count") or 0),
        tool_call_count=int(metadata.get("tool_call_count") or 0),
        max_model_turns=int(metadata.get("max_model_turns") or 0),
        max_wall_time_seconds=int(metadata.get("max_wall_time_seconds") or 0),
        created_at=loop.started_at,
        updated_at=loop.ended_at or loop.started_at,
        waiting_reason=(str(metadata.get("waiting_reason")) if metadata.get("waiting_reason") else None),
        continuation_prompt=(
            str(metadata.get("continuation_prompt")) if metadata.get("continuation_prompt") else None
        ),
        last_summary=(str(metadata.get("last_summary")) if metadata.get("last_summary") else None),
        schema_version=int(metadata.get("schema_version") or _LOOP_STATE_SCHEMA_VERSION),
        wait_condition=_wait_condition_from_mapping(metadata.get("wait_condition")),
        pending_tool_calls=_pending_tool_calls_from_value(metadata.get("pending_tool_calls")),
        partial_assistant=(
            str(metadata.get("partial_assistant")) if metadata.get("partial_assistant") else None
        ),
        context_bundle_id=(
            str(metadata.get("context_bundle_id")) if metadata.get("context_bundle_id") else None
        ),
        active_evidence_refs=_active_evidence_refs_from_value(metadata.get("active_evidence_refs")),
        retry_state=_retry_state_from_mapping(metadata.get("retry_state")),
        heartbeat_at=_parse_optional_datetime(metadata.get("heartbeat_at")),
        crash_marker=(str(metadata.get("crash_marker")) if metadata.get("crash_marker") else None),
    )


def upsert_loop_checkpoint(self, run: LoopState, *, verify: bool = True) -> None:
    episode = self.load_episode(run.episode_id)
    if episode is None:
        episode_state = self.load_episode_state(run.episode_id)
        if episode_state is None:
            raise KeyError(run.episode_id)
        self.upsert_episode_state(episode_state)
        episode = self.load_episode(run.episode_id)
    if episode is None:
        raise KeyError(run.episode_id)
    state = self.load_state(episode.state_id)
    if state is None:
        raise KeyError(episode.state_id)
    existing = self.load_loop(run.run_id)
    loop = Loop(
        loop_id=run.run_id,
        episode_id=episode.episode_id,
        state_id=state.state_id,
        personal_model_id=episode.personal_model_id,
        trigger_type="model_tool_checkpoint",
        status=run.status,
        started_at=run.created_at,
        ended_at=run.updated_at if run.status in {"completed", "failed"} else None,
        summary=run.last_summary or (existing.summary if existing is not None else ""),
        outcome=run.waiting_reason or (existing.outcome if existing is not None else ""),
        metadata=_loop_metadata(run),
    )
    self.upsert_loop(loop)
    if verify:
        reloaded = _verify_loop_checkpoint_roundtrip(self, run)
        if reloaded is None:
            raise RuntimeError(
                f"loop checkpoint verify failed: run {run.run_id} did not round-trip"
            )


def _verify_loop_checkpoint_roundtrip(self, run: LoopState) -> LoopState | None:
    """Load the checkpoint back and confirm the key fields survive.

    We do not compare every field for equality — timestamps may be
    normalized, optional values may collapse — but we do require that:
      * the run reloads,
      * status / phase / step counters match what we just wrote,
      * the v2 envelope (schema_version=2) was persisted,
      * any wait_condition kind the caller chose round-tripped.

    Returning None signals the caller that the write did not land
    correctly; the caller raises so the runtime can treat park as
    refused rather than assume durable persistence.
    """
    loop = self.load_loop(run.run_id)
    if loop is None:
        return None
    reloaded = _loop_state_from_loop(loop)
    if reloaded.schema_version < _LOOP_STATE_SCHEMA_VERSION:
        return None
    if reloaded.status != run.status:
        return None
    if reloaded.phase != run.phase:
        return None
    if reloaded.step_count != run.step_count:
        return None
    if reloaded.model_turn_count != run.model_turn_count:
        return None
    if reloaded.tool_call_count != run.tool_call_count:
        return None
    if (run.wait_condition is None) != (reloaded.wait_condition is None):
        return None
    if run.wait_condition is not None and reloaded.wait_condition is not None:
        if run.wait_condition.kind != reloaded.wait_condition.kind:
            return None
    return reloaded


def list_loop_checkpoints(
    self,
    *,
    statuses: tuple[str, ...] = ("active", "pending"),
    heartbeat_before: datetime | None = None,
    personal_model_id: str | None = None,
    state_id: str | None = None,
    limit: int | None = None,
) -> tuple[LoopState, ...]:
    """Return loop checkpoints, filtered for supervisor use.

    The supervisor scans for loops whose heartbeat is older than a
    staleness TTL to reclaim crashed runs. The resume path also needs
    to locate parked loops by state or personal model. This helper
    walks ``list_loops`` (which already reads every Loop row) and
    filters client-side — Loop counts per episode stay bounded so the
    linear scan is fine for Phase 1.
    """
    kept: list[LoopState] = []
    active_status_filter = set(str(status) for status in statuses if str(status).strip())
    for loop in self.list_loops():
        if loop.metadata.get("kind") != "loop_checkpoint":
            continue
        if active_status_filter and loop.status not in active_status_filter:
            continue
        if state_id is not None and loop.state_id != state_id:
            continue
        if personal_model_id is not None:
            if canonical_personal_model_id(loop.personal_model_id) != canonical_personal_model_id(
                personal_model_id
            ):
                continue
        run = _loop_state_from_loop(loop)
        if heartbeat_before is not None:
            hb = run.heartbeat_at
            if hb is None:
                # No heartbeat recorded yet; treat as stale so long-lived rows
                # from an older writer still become supervisor candidates.
                pass
            elif hb > heartbeat_before:
                continue
        kept.append(run)
    kept.sort(
        key=lambda item: (
            item.heartbeat_at or item.updated_at or item.created_at,
            item.run_id,
        )
    )
    if limit is not None and limit > 0:
        kept = kept[:limit]
    return tuple(kept)


def load_latest_open_loop_checkpoint(
    self,
    episode_id: str,
) -> LoopState | None:
    candidates = [
        loop
        for loop in self.list_loops(episode_id=episode_id)
        if loop.metadata.get("kind") == "loop_checkpoint" and loop.status in {"active", "pending"}
    ]
    if not candidates:
        return None
    latest = sorted(
        candidates,
        key=lambda loop: ((loop.ended_at or loop.started_at).isoformat(), loop.started_at.isoformat(), loop.loop_id),
        reverse=True,
    )[0]
    return _loop_state_from_loop(latest)


def append_loop_checkpoint_step(self, step: LoopStep) -> None:
    loop = self.load_loop(step.run_id)
    if loop is None:
        raise KeyError(step.run_id)
    phase = "acting" if step.kind == "tool" else "reasoning"
    self.upsert_step(
        Step(
            step_id=step.step_id,
            loop_id=loop.loop_id,
            episode_id=loop.episode_id,
            state_id=loop.state_id,
            personal_model_id=loop.personal_model_id,
            phase=phase,
            action=step.kind,
            status="completed",
            sequence=step.step_index,
            summary=step.title,
            outcome=step.outcome or "",
            payload_refs=(),
            metadata=_json_metadata(
                {
                    "checkpoint_kind": step.kind,
                    "content": step.content,
                    "tool_name": step.tool_name,
                }
            ),
            created_at=step.created_at,
        )
    )


def _step_to_loop_step(step: Step) -> LoopStep:
    metadata = dict(step.metadata)
    return LoopStep(
        step_id=step.step_id,
        run_id=step.loop_id,
        episode_id=step.episode_id,
        step_index=step.sequence,
        kind=metadata.get("checkpoint_kind", step.action),
        title=step.summary,
        content=metadata.get("content", step.summary),
        created_at=step.created_at,
        outcome=step.outcome or None,
        tool_name=metadata.get("tool_name") or None,
    )


def list_loop_checkpoint_steps(
    self,
    run_id: str,
    *,
    limit: int | None = None,
) -> tuple[LoopStep, ...]:
    steps = tuple(reversed(self.list_steps(loop_id=run_id)))
    if limit is not None:
        steps = steps[:limit]
    return tuple(_step_to_loop_step(step) for step in steps)
