"""Personal Model HTTP dispatch helpers for the API runtime app."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from urllib.parse import unquote

from .api_runtime_internal_methods import _serialize
from .api_runtime_support import APIResponse, _now, _read_json_bytes


def _dispatch_personal_model(
    self, method: str, parts: tuple[str, ...], body: bytes | None
) -> APIResponse:
    """Operator-surface writes against Personal Model claims and questions.

    Routes:
      * ``PATCH /v1/operator/personal-model/questions`` — update proactive question cadence.
      * ``POST  /v1/operator/personal-model/questions/{id}/bump``
      * ``POST  /v1/operator/personal-model/questions/{id}/dismiss``
      * ``POST  /v1/operator/personal-model/questions/{id}/answer``
      * ``POST  /v1/operator/personal-model/claims/{id}/correct``
      * ``POST  /v1/operator/personal-model/claims/{id}/forget``
      * ``POST  /v1/operator/personal-model/claims/{id}/restore``
      * ``POST  /v1/operator/personal-model/claims/{id}/delete``
      * ``POST  /v1/operator/personal-model/claims/{id}/protect``
      * ``POST  /v1/operator/personal-model/claims/{id}/unprotect``
    """
    from packages.storage.repository_support import DEFAULT_PERSONAL_MODEL_ID
    from packages.understanding import PersonalModelUnderstandingSurface

    normalized = method.upper()

    if normalized == "PATCH" and parts == ("questions",):
        payload = _read_json_bytes(body)
        # New format: accepts proactive_ask config directly (idle_threshold_minutes, daily_max, quiet_hours).
        # Legacy: also accepts learning_intensity for migration.
        proactive_updates: dict[str, Any] = {}
        if "idle_threshold_minutes" in payload:
            proactive_updates["idle_threshold_minutes"] = max(1, int(payload["idle_threshold_minutes"]))
        if "daily_max" in payload:
            proactive_updates["daily_max"] = max(1, int(payload["daily_max"]))
        if "quiet_hours" in payload:
            qh = payload["quiet_hours"]
            if isinstance(qh, (list, tuple)) and len(qh) == 2:
                proactive_updates["quiet_hours"] = [int(qh[0]) % 24, int(qh[1]) % 24]
        if "enabled" in payload:
            proactive_updates["enabled"] = bool(payload["enabled"])
        # Legacy migration: map learning_intensity → numeric values.
        intensity = str(payload.get("learning_intensity") or "").strip().lower()
        if intensity in {"low", "medium", "high"} and not proactive_updates:
            _INTENSITY_MAP = {
                "low": {"idle_threshold_minutes": 720, "daily_max": 2, "quiet_hours": [23, 7]},
                "medium": {"idle_threshold_minutes": 180, "daily_max": 8, "quiet_hours": [23, 7]},
                "high": {"idle_threshold_minutes": 60, "daily_max": 24, "quiet_hours": [1, 7]},
            }
            proactive_updates = _INTENSITY_MAP[intensity]
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
        if action == "dismiss":
            surface = PersonalModelUnderstandingSurface(repository=self.repository, semantic_summary_indexer=getattr(self, "semantic_summary_indexer", None))
            result = surface.manage_personal_model_questions(
                str(payload.get("episode_id") or "dashboard"),
                action="dismiss",
                personal_model_id=personal_model_id,
                question_id=question_id,
                reason=str(payload.get("reason") or "user_opted_out"),
            )
            return APIResponse(200, {"personal_model": result})
        if action == "answer":
            content = str(payload.get("content") or "").strip()
            if not content:
                raise ValueError("answer requires 'content'")
            surface = PersonalModelUnderstandingSurface(repository=self.repository, semantic_summary_indexer=getattr(self, "semantic_summary_indexer", None))
            result = surface.manage_personal_model_questions(
                str(payload.get("episode_id") or "dashboard"),
                action="answer",
                personal_model_id=personal_model_id,
                question_id=question_id,
                answer=content,
                reason="dashboard answer",
            )
            return APIResponse(200, {"personal_model": result})

    if normalized == "POST" and len(parts) >= 3 and parts[0] == "claims":
        claim_id = unquote(parts[1]).strip()
        action = parts[2].strip().lower()
        if action not in {"correct", "forget", "dispute", "restore", "delete", "protect", "unprotect"}:
            return APIResponse(404, {"error": "not_found"})
        payload = _read_json_bytes(body) if body else {}
        personal_model_id = str(payload.get("personal_model_id") or DEFAULT_PERSONAL_MODEL_ID).strip() or DEFAULT_PERSONAL_MODEL_ID
        facts = tuple(self.repository.list_personal_model_facts(personal_model_id=personal_model_id, status=("active", "retired", "disputed") if action in {"restore", "delete"} else "active"))
        target = next((fact for fact in facts if fact.fact_id == claim_id), None)
        if target is None:
            return APIResponse(404, {"error": "claim_not_found"})
        metadata = dict(target.metadata or {})
        reason = str(payload.get("reason") or f"dashboard {action}").strip()
        if action in {"protect", "unprotect"}:
            now = _now()
            if action == "protect":
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
            return APIResponse(200, {"personal_model": {"action": action, "status": "active", "ref": claim_id, "claim": _serialize(updated)}})
        if action == "delete":
            from packages.understanding.personal_model_governance import is_protected_topic

            if is_protected_topic(str(metadata.get("topic") or ""), metadata):
                return APIResponse(409, {"error": "protected_topic", "detail": "protected Personal Model topics must be unprotected before delete", "ref": claim_id})
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
            list_entries = getattr(self.repository, "list_semantic_index_entries", None)
            upsert_entry = getattr(self.repository, "upsert_semantic_index_entry", None)
            if callable(list_entries) and callable(upsert_entry):
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
            return APIResponse(200, {"personal_model": {"action": "delete", "status": "deleted", "ref": claim_id}})
        topic = str(payload.get("topic") or metadata.get("topic") or "").strip()
        if not topic:
            return APIResponse(409, {"error": "claim_missing_topic"})
        surface = PersonalModelUnderstandingSurface(repository=self.repository, semantic_summary_indexer=getattr(self, "semantic_summary_indexer", None))
        result = surface.update_personal_model(
            str(payload.get("episode_id") or "dashboard"),
            action=action,
            lens=str(payload.get("lens") or target.lens),
            topic=topic,
            text=str(payload.get("text") or ""),
            ref=claim_id,
            reason=reason,
            source="user_corrected" if action == "correct" else "user_said",
            personal_model_id=personal_model_id,
        )
        return APIResponse(200, {"personal_model": result})

    return APIResponse(404, {"error": "not_found"})


def _persist_proactive_ask_config(state_dir, updates: dict) -> None:
    try:
        from packages.runtime_config import (
            personal_model_question_config_from_global,
            global_config_path_for_state_dir,
            load_global_config,
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
        return
