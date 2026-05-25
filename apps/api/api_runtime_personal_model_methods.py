"""Personal Model operator routes for the API runtime app."""

from __future__ import annotations

from dataclasses import replace
import logging
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from .api_runtime_internal_methods import _serialize
from .api_runtime_support import APIResponse, _now, _read_json_bytes


LOGGER = logging.getLogger(__name__)


def _dispatch_personal_model(
    self, method: str, parts: tuple[str, ...], body: bytes | None
) -> APIResponse:
    """Operator-surface writes against Personal Model claims and questions."""
    from packages.storage.repository_support import DEFAULT_PERSONAL_MODEL_ID
    from packages.understanding import PersonalModelUnderstandingSurface

    normalized = method.upper()

    if normalized == "PATCH" and parts == ("questions",):
        payload = _read_json_bytes(body)
        proactive_updates = _proactive_ask_updates(payload)
        if not proactive_updates:
            raise ValueError("provide idle_threshold_minutes, daily_max, quiet_hours, or learning_intensity")
        _persist_proactive_ask_config(self.repository.database_path.parent, proactive_updates)
        return APIResponse(200, {"proactive_ask": proactive_updates})

    if normalized == "POST" and len(parts) >= 3 and parts[0] == "questions":
        question_id = unquote(parts[1]).strip()
        action = parts[2].strip().lower()
        if action not in {"bump", "dismiss", "answer"}:
            return APIResponse(404, {"error": "not_found"})
        payload = _read_json_bytes(body) if body else {}
        personal_model_id = str(payload.get("personal_model_id") or DEFAULT_PERSONAL_MODEL_ID)
        if action == "bump":
            return _bump_personal_model_question(self, question_id, personal_model_id)

        surface = PersonalModelUnderstandingSurface(
            repository=self.repository,
            semantic_summary_indexer=getattr(self, "semantic_summary_indexer", None),
        )
        if action == "dismiss":
            result = surface.manage_personal_model_questions(
                str(payload.get("episode_id") or "dashboard"),
                action="dismiss",
                personal_model_id=personal_model_id,
                question_id=question_id,
                reason=str(payload.get("reason") or "user_opted_out"),
            )
            return APIResponse(200, {"personal_model": result})
        content = str(payload.get("content") or "").strip()
        if not content:
            raise ValueError("answer requires 'content'")
        result = surface.manage_personal_model_questions(
            str(payload.get("episode_id") or "dashboard"),
            action="answer",
            personal_model_id=personal_model_id,
            question_id=question_id,
            answer=content,
            reason="dashboard answer",
        )
        reflect_result: dict[str, Any] | None = None
        trigger_reflect = getattr(self, "trigger_reflect_job", None)
        if callable(trigger_reflect):
            try:
                reflect_result = trigger_reflect(trigger="question_answer", features="questions")
            except Exception:
                LOGGER.debug("failed to enqueue question refresh after answer", exc_info=True)
        return APIResponse(200, {"personal_model": result, "reflect": reflect_result})

    if normalized == "POST" and len(parts) >= 3 and parts[0] == "claims":
        payload = _read_json_bytes(body) if body else {}
        personal_model_id = str(payload.get("personal_model_id") or DEFAULT_PERSONAL_MODEL_ID).strip()
        return _dispatch_personal_model_claim(
            self,
            claim_id=unquote(parts[1]).strip(),
            action=parts[2].strip().lower(),
            payload=payload,
            personal_model_id=personal_model_id or DEFAULT_PERSONAL_MODEL_ID,
        )

    return APIResponse(404, {"error": "not_found"})


def _proactive_ask_updates(payload: dict[str, Any]) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if "idle_threshold_minutes" in payload:
        updates["idle_threshold_minutes"] = max(1, int(payload["idle_threshold_minutes"]))
    if "daily_max" in payload:
        updates["daily_max"] = max(1, int(payload["daily_max"]))
    if "quiet_hours" in payload:
        quiet_hours = payload["quiet_hours"]
        if isinstance(quiet_hours, (list, tuple)) and len(quiet_hours) == 2:
            updates["quiet_hours"] = [int(quiet_hours[0]) % 24, int(quiet_hours[1]) % 24]
    if "enabled" in payload:
        updates["enabled"] = bool(payload["enabled"])
    intensity = str(payload.get("learning_intensity") or "").strip().lower()
    if intensity in _INTENSITY_UPDATES and not updates:
        updates = dict(_INTENSITY_UPDATES[intensity])
    return updates


_INTENSITY_UPDATES = {
    "low": {"idle_threshold_minutes": 720, "daily_max": 2, "quiet_hours": [23, 7]},
    "medium": {"idle_threshold_minutes": 180, "daily_max": 8, "quiet_hours": [23, 7]},
    "high": {"idle_threshold_minutes": 60, "daily_max": 24, "quiet_hours": [1, 7]},
}


def _bump_personal_model_question(self, question_id: str, personal_model_id: str) -> APIResponse:
    list_open = getattr(self.repository, "list_open_questions", None)
    upsert = getattr(self.repository, "upsert_open_question", None)
    if not callable(list_open) or not callable(upsert):
        return APIResponse(500, {"error": "personal_model_questions_not_available"})
    candidates = list_open(personal_model_id=personal_model_id, status=("open", "asked"))
    target = next((q for q in candidates if q.question_id == question_id), None)
    if target is None:
        return APIResponse(404, {"error": "question_not_found"})
    bumped = replace(target, priority=min(1.0, max(target.priority, 0.85)))
    upsert(bumped)
    return APIResponse(200, {"personal_model": {"question_id": question_id, "priority": bumped.priority}})


def _dispatch_personal_model_claim(
    self,
    *,
    claim_id: str,
    action: str,
    payload: dict[str, Any],
    personal_model_id: str,
) -> APIResponse:
    if action not in {"correct", "forget", "dispute", "restore", "delete", "protect", "unprotect"}:
        return APIResponse(404, {"error": "not_found"})
    status = ("active", "retired", "disputed") if action in {"restore", "delete"} else "active"
    facts = tuple(self.repository.list_personal_model_facts(personal_model_id=personal_model_id, status=status))
    target = next((fact for fact in facts if fact.fact_id == claim_id), None)
    if target is None:
        return APIResponse(404, {"error": "claim_not_found"})
    metadata = dict(target.metadata or {})
    reason = str(payload.get("reason") or f"dashboard {action}").strip()
    if action in {"protect", "unprotect"}:
        return _set_personal_model_claim_protection(self, target, metadata, reason=reason, protect=action == "protect")
    if action == "delete":
        return _delete_personal_model_claim(self, target, metadata, reason=reason, personal_model_id=personal_model_id)
    return _update_personal_model_claim(
        self,
        target,
        metadata,
        action=action,
        payload=payload,
        reason=reason,
        personal_model_id=personal_model_id,
    )


def _set_personal_model_claim_protection(
    self,
    target: Any,
    metadata: dict[str, Any],
    *,
    reason: str,
    protect: bool,
) -> APIResponse:
    now = _now()
    if protect:
        next_metadata = {
            **metadata,
            "protected": "user",
            "protected_reason": reason or "dashboard protect",
            "projection_policy": str(metadata.get("projection_policy") or "tool_only"),
            "protected_at": now.isoformat(),
        }
    else:
        next_metadata = {
            **metadata,
            "protected": "user_unprotected",
            "protected_reason": reason or "dashboard unprotect",
            "unprotected_at": now.isoformat(),
        }
    updated = replace(target, metadata=next_metadata)
    self.repository.upsert_personal_model_fact(updated)
    return APIResponse(
        200,
        {"personal_model": {"action": "protect" if protect else "unprotect", "status": "active", "ref": target.fact_id, "claim": _serialize(updated)}},
    )


def _delete_personal_model_claim(
    self,
    target: Any,
    metadata: dict[str, Any],
    *,
    reason: str,
    personal_model_id: str,
) -> APIResponse:
    from packages.understanding.personal_model_governance import is_protected_topic

    if is_protected_topic(str(metadata.get("topic") or ""), metadata):
        return APIResponse(
            409,
            {"error": "protected_topic", "detail": "protected Personal Model topics must be unprotected before delete", "ref": target.fact_id},
        )
    now = _now()
    deleted = replace(
        target,
        status="deleted",
        metadata={
            **metadata,
            "deleted_by": "dashboard",
            "deleted_reason": reason,
            "deleted_at": now.isoformat(),
            "understanding_status": "deleted",
        },
    )
    self.repository.upsert_personal_model_fact(deleted)
    _deactivate_personal_model_claim_index_entries(self, target.fact_id, personal_model_id, now=now)
    return APIResponse(200, {"personal_model": {"action": "delete", "status": "deleted", "ref": target.fact_id}})


def _deactivate_personal_model_claim_index_entries(
    self,
    claim_id: str,
    personal_model_id: str,
    *,
    now: Any,
) -> None:
    list_entries = getattr(self.repository, "list_semantic_index_entries", None)
    upsert_entry = getattr(self.repository, "upsert_semantic_index_entry", None)
    if not callable(list_entries) or not callable(upsert_entry):
        return
    for entry in list_entries(personal_model_id=personal_model_id, owner_scope="personal_model"):
        if getattr(entry, "source_id", "") != claim_id:
            continue
        upsert_entry(
            replace(
                entry,
                status="deleted",
                updated_at=now,
                metadata={
                    **dict(getattr(entry, "metadata", {}) or {}),
                    "claim_status": "deleted",
                    "deactivated_by": "dashboard",
                },
            )
        )


def _update_personal_model_claim(
    self,
    target: Any,
    metadata: dict[str, Any],
    *,
    action: str,
    payload: dict[str, Any],
    reason: str,
    personal_model_id: str,
) -> APIResponse:
    from packages.understanding import PersonalModelUnderstandingSurface

    topic = str(payload.get("topic") or metadata.get("topic") or "").strip()
    if not topic:
        return APIResponse(409, {"error": "claim_missing_topic"})
    surface = PersonalModelUnderstandingSurface(
        repository=self.repository,
        semantic_summary_indexer=getattr(self, "semantic_summary_indexer", None),
    )
    result = surface.update_personal_model(
        str(payload.get("episode_id") or "dashboard"),
        action=action,
        lens=str(payload.get("lens") or target.lens),
        topic=topic,
        text=str(payload.get("text") or ""),
        ref=target.fact_id,
        reason=reason,
        source="user_corrected" if action == "correct" else "user_said",
        personal_model_id=personal_model_id,
    )
    return APIResponse(200, {"personal_model": result})


def _persist_proactive_ask_config(state_dir: Path, updates: dict[str, Any]) -> None:
    try:
        from packages.runtime_config import (
            global_config_path_for_state_dir,
            load_global_config,
            personal_model_question_config_from_global,
            write_global_config,
        )

        config_path = global_config_path_for_state_dir(state_dir)
        config = load_global_config(config_path, state_dir=state_dir)
        question_policy = personal_model_question_config_from_global(config)
        proactive = question_policy.get("proactive_ask") if isinstance(question_policy.get("proactive_ask"), dict) else {}
        proactive.update(updates)
        question_policy["proactive_ask"] = proactive
        question_policy.pop("learning_intensity", None)
        config["personal_model_questions"] = question_policy
        write_global_config(config_path, config)
    except Exception:  # pragma: no cover
        LOGGER.warning("failed to persist proactive ask question policy", exc_info=True)
        return
