"""Support helpers for the reset storage repository."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Mapping

from packages.contracts.layers import Episode, Loop, PersonalModel, State, Step
from packages.contracts.runtime import LearningJob
from packages.contracts.support import SemanticIndexEntry

SCHEMA_VERSION = 1
SCHEMA_PATH = Path(__file__).with_name("schema.sql")

DEFAULT_PERSONAL_MODEL_ID = "you"
DEFAULT_PERSONAL_MODEL_DISPLAY_NAME = "You"


def canonical_personal_model_id(personal_model_id: str | None) -> str:
    """Return a stable Personal Model id without collapsing every user to `you`."""
    cleaned = str(personal_model_id or "").strip()
    return cleaned or DEFAULT_PERSONAL_MODEL_ID


def canonical_personal_model_ref(personal_model_id: str | None) -> str | None:
    cleaned = str(personal_model_id or "").strip()
    return None if not cleaned else canonical_personal_model_id(cleaned)


@dataclass(frozen=True, slots=True)
class StorageBootstrapState:
    database_path: str
    schema_version: int


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str:
    return (value or _utc_now()).isoformat()


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _json_text(values: tuple[str, ...]) -> str:
    return json.dumps(list(values), separators=(",", ":"))


def _tuple_text(payload: str) -> tuple[str, ...]:
    data = json.loads(payload)
    return tuple(str(item) for item in data)


def _json_mapping(values: Mapping[str, str]) -> str:
    return json.dumps(dict(values), separators=(",", ":"), sort_keys=True)


def _mapping_text(payload: str) -> dict[str, str]:
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return {str(key): str(value) for key, value in data.items()}


def _json_dict_text(values: Mapping[str, object]) -> str:
    return json.dumps(dict(values), separators=(",", ":"), sort_keys=True, default=str)


def _mapping_object(payload: str | None) -> dict[str, object]:
    if not payload:
        return {}
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return {str(key): value for key, value in data.items()}


def _row_mapping_object(row: sqlite3.Row, column_name: str) -> dict[str, object]:
    if column_name not in row.keys():
        return {}
    return _mapping_object(row[column_name])


def _personal_model_from_row(row: sqlite3.Row) -> PersonalModel:
    return PersonalModel(
        personal_model_id=canonical_personal_model_id(str(row["personal_model_id"])),
        display_name=str(row["display_name"]),
        status=str(row["status"]),
        created_at=_parse_datetime(str(row["created_at"])),
        updated_at=_parse_datetime(str(row["updated_at"])),
        metadata=_mapping_text(str(row["metadata_json"])),
    )


def _state_from_row(row: sqlite3.Row) -> State:
    return State(
        state_id=str(row["state_id"]),
        personal_model_id=canonical_personal_model_id(str(row["personal_model_id"])),
        state_anchor=str(row["state_anchor"]),
        status=str(row["status"]),
        elephant_id=str(row["elephant_id"]),
        elephant_name=str(row["elephant_name"]),
        identity_mode=str(row["identity_mode"]),
        posture=str(row["posture"]),
        capability_boundaries=_tuple_text(str(row["capability_boundaries_json"])),
        initiative=str(row["initiative"]),
        working_style=str(row["working_style"]),
        surface_bindings=_tuple_text(str(row["surface_bindings_json"])),
        safety_boundaries=_tuple_text(str(row["safety_boundaries_json"])),
        disclosure_boundaries=_tuple_text(str(row["disclosure_boundaries_json"])),
        source_manifest=str(row["source_manifest"]),
        elephant_identity_text=str(row["elephant_identity_text"]),
        summary=str(row["summary"]),
        current_context_note=str(row["current_context_note"]),
        created_at=_parse_datetime(str(row["created_at"])),
        updated_at=_parse_datetime(str(row["updated_at"])),
        metadata=_mapping_text(str(row["metadata_json"])),
    )


_LEGACY_EPISODE_STATUS_MAP: dict[str, str] = {
    "active": "open",
    "interrupted": "paused",
}


def _normalize_episode_status(raw: str) -> str:
    return _LEGACY_EPISODE_STATUS_MAP.get(raw, raw)


def _episode_from_row(row: sqlite3.Row) -> Episode:
    return Episode(
        episode_id=str(row["episode_id"]),
        state_id=str(row["state_id"]),
        personal_model_id=canonical_personal_model_id(str(row["personal_model_id"])),
        entry_surface=str(row["entry_surface"]),
        status=_normalize_episode_status(str(row["status"])),
        started_at=_parse_datetime(str(row["started_at"])),
        ended_at=_parse_datetime(str(row["ended_at"])) if row["ended_at"] is not None else None,
        updated_at=_parse_datetime(str(row["updated_at"])) if row["updated_at"] is not None else None,
        exit_summary=str(row["exit_summary"]),
        elephant_id=str(row["elephant_id"] or ""),
        parent_episode_id=str(row["parent_episode_id"]) if row["parent_episode_id"] else None,
        interruption_state=str(row["interruption_state"]) if row["interruption_state"] else None,
        metadata=_mapping_text(str(row["metadata_json"])),
    )


def _loop_from_row(row: sqlite3.Row) -> Loop:
    return Loop(
        loop_id=str(row["loop_id"]),
        episode_id=str(row["episode_id"]),
        state_id=str(row["state_id"]),
        personal_model_id=canonical_personal_model_id(str(row["personal_model_id"])),
        trigger_type=str(row["trigger_type"]),
        status=str(row["status"]),
        started_at=_parse_datetime(str(row["started_at"])),
        ended_at=_parse_datetime(str(row["ended_at"])) if row["ended_at"] is not None else None,
        summary=str(row["summary"]),
        outcome=str(row["outcome"]),
        metadata=_mapping_text(str(row["metadata_json"])),
    )


def _step_from_row(row: sqlite3.Row) -> Step:
    return Step(
        step_id=str(row["step_id"]),
        loop_id=str(row["loop_id"]),
        episode_id=str(row["episode_id"]),
        state_id=str(row["state_id"]),
        personal_model_id=canonical_personal_model_id(str(row["personal_model_id"])),
        phase=str(row["phase"]),
        action=str(row["action"]),
        status=str(row["status"]),
        sequence=int(row["sequence"]),
        created_at=_parse_datetime(str(row["created_at"])),
        summary=str(row["summary"]),
        outcome=str(row["outcome"]),
        payload_refs=_tuple_text(str(row["payload_refs_json"])),
        metadata=_mapping_text(str(row["metadata_json"])),
    )


def _semantic_index_entry_from_row(row: sqlite3.Row) -> SemanticIndexEntry:
    return SemanticIndexEntry(
        semantic_index_entry_id=str(row["semantic_index_entry_id"]),
        owner_scope=str(row["owner_scope"]),
        source_id=str(row["source_id"]),
        provider_id=str(row["provider_id"]),
        model_id=str(row["model_id"]),
        dimensions=int(row["dimensions"]),
        content_hash=str(row["content_hash"]),
        personal_model_id=canonical_personal_model_ref(str(row["personal_model_id"]) if row["personal_model_id"] is not None else None),
        state_id=str(row["state_id"]) if row["state_id"] is not None else None,
        backend=str(row["backend"]),
        vector_ref=str(row["vector_ref"]),
        status=str(row["status"]),
        created_at=_parse_datetime(str(row["created_at"])),
        updated_at=_parse_datetime(str(row["updated_at"])),
        metadata=_mapping_text(str(row["metadata_json"])),
    )


def _learning_job_from_row(row: sqlite3.Row) -> LearningJob:
    return LearningJob(
        job_id=str(row["job_id"]),
        job_type=str(row["job_type"]),
        trigger=str(row["trigger"]),
        status=str(row["status"]),
        personal_model_id=canonical_personal_model_id(str(row["personal_model_id"])),
        state_id=str(row["state_id"]),
        episode_id=str(row["episode_id"]),
        loop_id=str(row["loop_id"]) if row["loop_id"] is not None and str(row["loop_id"]).strip() else None,
        summary=str(row["summary"]),
        progress_stage=str(row["progress_stage"]),
        progress_detail=str(row["progress_detail"]),
        attempt_count=int(row["attempt_count"]),
        max_attempts=int(row["max_attempts"]),
        available_at=_parse_datetime(str(row["available_at"])),
        created_at=_parse_datetime(str(row["created_at"])),
        started_at=_parse_datetime(str(row["started_at"])) if row["started_at"] is not None else None,
        finished_at=_parse_datetime(str(row["finished_at"])) if row["finished_at"] is not None else None,
        worker_id=str(row["worker_id"]) if row["worker_id"] is not None and str(row["worker_id"]).strip() else None,
        last_error=str(row["last_error"]),
        metadata=_mapping_text(str(row["metadata_json"])),
        result_json=_row_mapping_object(row, "result_json"),
    )
