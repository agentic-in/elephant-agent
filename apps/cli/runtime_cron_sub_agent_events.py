"""Event payload helpers for delegated sub-agent runs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def sub_agent_event_arguments(
    prepared_child: Mapping[str, Any],
    *,
    phase: str,
    detail: str,
    run_id: str | None,
    task_index: int | None,
    status: str | None,
) -> dict[str, Any]:
    child_session_id = str(prepared_child.get("session_id") or "")
    name = str(prepared_child.get("name") or "sub-agent")
    metadata = _sub_agent_child_metadata(prepared_child)
    display_name = str(metadata.get("baby_name") or "").strip() or str(metadata.get("baby_role") or "").strip() or name
    return {
        "name": display_name,
        "task": str(prepared_child.get("task") or ""),
        "sub_agent_child": True,
        "run_id": run_id or "",
        "task_index": task_index if task_index is not None else 0,
        "status": status or "",
        "phase": phase,
        "detail": detail,
        "child_episode_id": child_session_id,
        **{key: value for key, value in metadata.items() if value not in (None, "")},
    }


def _sub_agent_child_metadata(prepared_child: Mapping[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    child_metadata = prepared_child.get("child_metadata")
    if isinstance(child_metadata, Mapping):
        metadata.update({str(key): value for key, value in child_metadata.items() if str(key).strip()})
    baby = prepared_child.get("baby")
    if isinstance(baby, Mapping):
        _merge_baby_metadata(metadata, baby)
    backend = str(prepared_child.get("backend") or metadata.get("backend") or "").strip()
    if backend:
        metadata.setdefault("backend", backend)
    return metadata


def _merge_baby_metadata(metadata: dict[str, Any], baby: Mapping[str, Any]) -> None:
    baby_state = baby.get("state")
    runtime_record = baby.get("runtime")
    if baby_state is not None:
        metadata.setdefault("baby_id", str(getattr(baby_state, "elephant_id", "") or ""))
        metadata.setdefault("baby_state_id", str(getattr(baby_state, "state_id", "") or ""))
        metadata.setdefault("baby_name", _state_name(baby_state))
    if runtime_record is not None:
        metadata.setdefault("provider_id", str(getattr(runtime_record, "provider_id", "") or ""))
        metadata.setdefault("runtime_id", str(getattr(runtime_record, "runtime_id", "") or ""))
        metadata.setdefault("runtime_display_name", str(getattr(runtime_record, "display_name", "") or ""))
        metadata.setdefault("runtime_command", str(getattr(runtime_record, "command", "") or ""))
        metadata.setdefault("runtime_path", str(getattr(runtime_record, "resolved_path", "") or ""))
        metadata.setdefault("runtime_model", str(getattr(runtime_record, "default_model", "") or ""))
    metadata.setdefault("baby_role", str(baby.get("role_title") or ""))


def _state_name(state: Any) -> str:
    return str(
        getattr(state, "display_name", "")
        or getattr(state, "title", "")
        or getattr(state, "name", "")
        or ""
    )
