"""Canonical system-layer repository methods."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Mapping, Sequence
from uuid import uuid4

from packages.contracts import Episode, Loop, PersonalModel, State, Step
from packages.contracts.runtime import (
    PersonalModelRuntimeState,
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
    elephant_id: str | None = None,
    state_anchor: str | None = None,
    status: str | None = None,
) -> tuple[State, ...]:
    clauses: list[str] = []
    parameters: list[str] = []
    if personal_model_id is not None:
        clauses.append("personal_model_id = ?")
        parameters.append(canonical_personal_model_id(personal_model_id))
    if elephant_id is not None:
        clauses.append("elephant_id = ?")
        parameters.append(elephant_id)
    if state_anchor is not None:
        clauses.append("state_anchor = ?")
        parameters.append(state_anchor)
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


def list_episodes(
    self,
    *,
    state_id: str | None = None,
    personal_model_id: str | None = None,
    elephant_id: str | None = None,
    status: str | None = None,
    limit: int | None = None,
    newest_first: bool = False,
) -> tuple[Episode, ...]:
    sql = "SELECT * FROM episodes"
    clauses: list[str] = []
    parameters: list[str | int] = []
    if state_id is not None:
        clauses.append("state_id = ?")
        parameters.append(state_id)
    if personal_model_id is not None:
        clauses.append("personal_model_id = ?")
        parameters.append(canonical_personal_model_id(personal_model_id))
    if elephant_id is not None:
        clauses.append("elephant_id = ?")
        parameters.append(elephant_id)
    if status is not None:
        clauses.append("status = ?")
        parameters.append(status)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sort_direction = "DESC" if newest_first else "ASC"
    sql += f" ORDER BY started_at {sort_direction}, episode_id {sort_direction}"
    if limit is not None:
        sql += " LIMIT ?"
        parameters.append(max(0, int(limit)))
    with self.connection() as connection:
        rows = connection.execute(sql, tuple(parameters)).fetchall()
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


def list_loops(
    self,
    *,
    episode_id: str | None = None,
    state_id: str | None = None,
    personal_model_id: str | None = None,
    trigger_type: str | None = None,
    status: str | None = None,
    limit: int | None = None,
    newest_first: bool = False,
) -> tuple[Loop, ...]:
    sql = "SELECT * FROM loops"
    clauses: list[str] = []
    parameters: list[str | int] = []
    if episode_id is not None:
        clauses.append("episode_id = ?")
        parameters.append(episode_id)
    if state_id is not None:
        clauses.append("state_id = ?")
        parameters.append(state_id)
    if personal_model_id is not None:
        clauses.append("personal_model_id = ?")
        parameters.append(canonical_personal_model_id(personal_model_id))
    if trigger_type is not None:
        clauses.append("trigger_type = ?")
        parameters.append(trigger_type)
    if status is not None:
        clauses.append("status = ?")
        parameters.append(status)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sort_direction = "DESC" if newest_first else "ASC"
    sql += f" ORDER BY started_at {sort_direction}, loop_id {sort_direction}"
    if limit is not None:
        sql += " LIMIT ?"
        parameters.append(max(0, int(limit)))
    with self.connection() as connection:
        rows = connection.execute(sql, tuple(parameters)).fetchall()
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


def list_steps(
    self,
    *,
    loop_id: str | None = None,
    episode_id: str | None = None,
    episode_ids: tuple[str, ...] | None = None,
    state_id: str | None = None,
    personal_model_id: str | None = None,
    created_at_start: datetime | None = None,
    created_at_end: datetime | None = None,
    limit: int | None = None,
    newest_first: bool = False,
) -> tuple[Step, ...]:
    sql = "SELECT * FROM steps"
    clauses: list[str] = []
    parameters: list[str | int] = []
    if loop_id is not None:
        clauses.append("loop_id = ?")
        parameters.append(loop_id)
    if episode_id is not None:
        clauses.append("episode_id = ?")
        parameters.append(episode_id)
    if episode_ids is not None:
        if not episode_ids:
            return ()
        placeholders = ",".join("?" * len(episode_ids))
        clauses.append(f"episode_id IN ({placeholders})")
        parameters.extend(episode_ids)
    if state_id is not None:
        clauses.append("state_id = ?")
        parameters.append(state_id)
    if personal_model_id is not None:
        clauses.append("personal_model_id = ?")
        parameters.append(canonical_personal_model_id(personal_model_id))
    if created_at_start is not None:
        clauses.append("created_at >= ?")
        parameters.append(_iso(created_at_start))
    if created_at_end is not None:
        clauses.append("created_at <= ?")
        parameters.append(_iso(created_at_end))
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    if newest_first:
        sql += " ORDER BY created_at DESC, step_id DESC"
    else:
        sql += " ORDER BY sequence ASC, created_at ASC"
    if limit is not None:
        sql += " LIMIT ?"
        parameters.append(max(0, int(limit)))
    with self.connection() as connection:
        rows = connection.execute(sql, tuple(parameters)).fetchall()
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

