"""Tool-facing Personal Model question management surface."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from packages.contracts import OpenQuestion
from packages.contracts.personal_model import (
    ALLOWED_LENSES,
    ALLOWED_QUESTION_SOURCES,
    ALLOWED_QUESTION_STATUSES,
    ALLOWED_SENSITIVITIES,
)
from packages.storage.repository_support import DEFAULT_PERSONAL_MODEL_ID


class CuriosityQuestionManagementSurface:
    """CRUD and selection surface for OpenQuestion rows and bank templates."""

    def __init__(self, *, repository: Any) -> None:
        self.repository = repository

    def manage_questions(
        self,
        session_id: str,
        *,
        action: str,
        personal_model_id: str = "",
        question_id: str = "",
        status: str = "",
        lens: str = "",
        sub_lens: str = "",
        text: str = "",
        rationale: str = "",
        priority: float | None = None,
        sensitivity: str = "",
        source: str = "",
        metadata: Mapping[str, str] | None = None,
        reason: str = "",
        surface: str = "tool.personal_model.questions",
        user_response_episode_id: str = "",
        generated_fact_ids: Sequence[str] = (),
        limit: int = 10,
    ) -> Mapping[str, Any]:
        normalized = action.strip().lower()
        pm_id = self._personal_model_id(session_id, personal_model_id)
        if normalized in {"list", "ls"}:
            return {
                "action": "list",
                "questions": self._list(pm_id, status=status, lens=lens, sub_lens=sub_lens, limit=limit),
            }
        if normalized in {"inspect", "view"}:
            return {
                "action": "inspect",
                "question": self._question_payload(self._load(pm_id, question_id)),
            }
        if normalized in {"bank", "templates"}:
            return {
                "action": "bank",
                "templates": [],
                "note": "Static question bank removed. Questions are now created by the learning agent.",
            }
        if normalized == "create":
            question = self._create(
                pm_id,
                question_id=question_id,
                lens=lens,
                sub_lens=sub_lens,
                text=text,
                rationale=rationale,
                priority=priority,
                sensitivity=sensitivity,
                source=source,
                metadata=metadata,
            )
            return {"action": "create", "question": self._question_payload(question)}
        if normalized == "update":
            question = self._update(
                pm_id,
                question_id=question_id,
                status=status,
                lens=lens,
                sub_lens=sub_lens,
                text=text,
                rationale=rationale,
                priority=priority,
                sensitivity=sensitivity,
                source=source,
                metadata=metadata,
            )
            return {"action": "update", "question": self._question_payload(question)}
        if normalized in {"select", "choose"}:
            question = self._load(pm_id, question_id)
            return {"action": "select", "selected": self._question_payload(question)}
        if normalized in {"ask", "asked"}:
            question = self._mark(pm_id, question_id, status="asked", surface=surface)
            return {"action": "ask", "question": self._question_payload(question)}
        if normalized == "answer":
            question = self._mark(
                pm_id,
                question_id,
                status="answered",
                user_response_episode_id=user_response_episode_id or session_id,
                generated_fact_ids=generated_fact_ids,
            )
            return {"action": "answer", "question": self._question_payload(question)}
        if normalized == "dismiss":
            question = self._mark(pm_id, question_id, status="dismissed", reason=reason)
            return {"action": "dismiss", "question": self._question_payload(question)}
        if normalized in {"reopen", "open"}:
            question = self._mark(pm_id, question_id, status="open")
            return {"action": "reopen", "question": self._question_payload(question)}
        if normalized == "stale":
            question = self._mark(pm_id, question_id, status="stale", reason=reason)
            return {"action": "stale", "question": self._question_payload(question)}
        if normalized in {"delete", "remove"}:
            deleted = self._delete(pm_id, question_id)
            return {
                "action": "delete",
                "question_id": deleted.question_id,
                "status": "deleted",
            }
        raise ValueError(f"tool.personal_model.questions unsupported action: {action!r}")

    def _personal_model_id(self, session_id: str, explicit: str) -> str:
        if explicit.strip():
            pm_id = explicit.strip()
        else:
            episode = self.repository.load_episode_state(session_id)
            pm_id = str(getattr(episode, "personal_model_id", "") or "").strip()
        pm_id = pm_id or DEFAULT_PERSONAL_MODEL_ID
        ensure = getattr(self.repository, "ensure_default_personal_model", None)
        if callable(ensure):
            ensure(personal_model_id=pm_id)
        return pm_id

    def _list(
        self,
        personal_model_id: str,
        *,
        status: str,
        lens: str,
        sub_lens: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        statuses: str | tuple[str, ...]
        statuses = (
            tuple(item.strip() for item in status.replace("|", ",").split(",") if item.strip()) if status else "open"
        )
        questions = self.repository.list_open_questions(
            personal_model_id=personal_model_id,
            status=statuses,
            lens=lens.strip() or None,
            sub_lens=sub_lens.strip() or None,
            limit=max(1, min(int(limit or 10), 50)),
        )
        return [self._question_payload(question) for question in questions]

    def _load(self, personal_model_id: str, question_id: str) -> OpenQuestion:
        resolved_id = question_id.strip()
        if not resolved_id:
            raise ValueError("tool.personal_model.questions requires question_id for this action")
        questions = self.repository.list_open_questions(
            personal_model_id=personal_model_id,
            status=tuple(ALLOWED_QUESTION_STATUSES),
            limit=None,
        )
        for question in questions:
            if question.question_id == resolved_id:
                return question
        if "/" in resolved_id:
            lens, sub_lens = (part.strip() for part in resolved_id.split("/", 1))
            matches = [question for question in questions if question.lens == lens and question.sub_lens == sub_lens]
            if matches:
                return sorted(
                    matches,
                    key=lambda q: (q.status != "open", -q.priority, q.created_at),
                )[0]
        raise KeyError(resolved_id)

    def _create(
        self,
        personal_model_id: str,
        *,
        question_id: str,
        lens: str,
        sub_lens: str,
        text: str,
        rationale: str,
        priority: float | None,
        sensitivity: str,
        source: str,
        metadata: Mapping[str, str] | None,
    ) -> OpenQuestion:
        resolved_lens = _normalized_choice(lens, ALLOWED_LENSES, default="knowledge", field="lens")
        resolved_sub_lens = sub_lens.strip() or "agent.generated"
        resolved_text = text.strip()
        if not resolved_text:
            raise ValueError("tool.personal_model.questions create requires text")
        resolved_source = _normalized_choice(source, ALLOWED_QUESTION_SOURCES, default="contextual", field="source")
        question = OpenQuestion(
            question_id=question_id.strip() or f"oq:{personal_model_id}:{resolved_sub_lens}:{uuid4().hex[:8]}",
            personal_model_id=personal_model_id,
            lens=resolved_lens,
            sub_lens=resolved_sub_lens,
            text=resolved_text,
            rationale=rationale.strip() or "agent-managed Personal Model question",
            priority=_priority(priority, default=0.55),
            sensitivity=_normalized_choice(sensitivity, ALLOWED_SENSITIVITIES, default="low", field="sensitivity"),
            source=resolved_source,
            created_at=datetime.now(timezone.utc),
            status="open",
            metadata={
                "managed_by": "tool.personal_model.questions",
                **dict(metadata or {}),
            },
        )
        self.repository.upsert_open_question(question)
        return question

    def _update(self, personal_model_id: str, *, question_id: str, **updates: Any) -> OpenQuestion:
        current = self._load(personal_model_id, question_id)
        metadata_update = updates.get("metadata")
        merged_metadata = dict(current.metadata)
        if isinstance(metadata_update, Mapping):
            merged_metadata.update({str(k): str(v) for k, v in metadata_update.items()})
        values: dict[str, Any] = {"metadata": merged_metadata}
        if str(updates.get("status") or "").strip():
            values["status"] = _normalized_choice(str(updates["status"]), ALLOWED_QUESTION_STATUSES, field="status")
        if str(updates.get("lens") or "").strip():
            values["lens"] = _normalized_choice(str(updates["lens"]), ALLOWED_LENSES, field="lens")
        if str(updates.get("sub_lens") or "").strip():
            values["sub_lens"] = str(updates["sub_lens"]).strip()
        if str(updates.get("text") or "").strip():
            values["text"] = str(updates["text"]).strip()
        if str(updates.get("rationale") or "").strip():
            values["rationale"] = str(updates["rationale"]).strip()
        if updates.get("priority") is not None:
            values["priority"] = _priority(updates.get("priority"), default=current.priority)
        if str(updates.get("sensitivity") or "").strip():
            values["sensitivity"] = _normalized_choice(
                str(updates["sensitivity"]), ALLOWED_SENSITIVITIES, field="sensitivity"
            )
        if str(updates.get("source") or "").strip():
            values["source"] = _normalized_choice(str(updates["source"]), ALLOWED_QUESTION_SOURCES, field="source")
        updated = replace(current, **values)
        self.repository.upsert_open_question(updated)
        return updated

    def _mark(
        self,
        personal_model_id: str,
        question_id: str,
        *,
        status: str,
        surface: str = "",
        reason: str = "",
        user_response_episode_id: str = "",
        generated_fact_ids: Sequence[str] = (),
    ) -> OpenQuestion:
        current = self._load(personal_model_id, question_id)
        self.repository.mark_open_question(
            question_id=current.question_id,
            status=status,
            surface=surface or None,
            dismissed_reason=reason or None,
            user_response_episode_id=user_response_episode_id or None,
            generated_fact_ids=tuple(str(item) for item in generated_fact_ids if str(item).strip()) or None,
        )
        return self._load(personal_model_id, question_id)

    def _delete(self, personal_model_id: str, question_id: str) -> OpenQuestion:
        current = self._load(personal_model_id, question_id)
        delete = getattr(self.repository, "delete_open_question", None)
        if callable(delete):
            delete(question_id=current.question_id)
            return current
        with self.repository.connection() as connection:
            connection.execute(
                "DELETE FROM personal_model_open_questions WHERE question_id = ?",
                (current.question_id,),
            )
            connection.commit()
        return current

    @staticmethod
    def _question_payload(question: OpenQuestion) -> dict[str, Any]:
        return {
            "question_id": question.question_id,
            "personal_model_id": question.personal_model_id,
            "lens": question.lens,
            "sub_lens": question.sub_lens,
            "text": question.text,
            "rationale": question.rationale,
            "priority": question.priority,
            "sensitivity": question.sensitivity,
            "source": question.source,
            "status": question.status,
            "asked_count": question.asked_count,
            "last_asked_at": question.last_asked_at.isoformat() if question.last_asked_at else "",
            "last_asked_surface": question.last_asked_surface or "",
            "dismissed_reason": question.dismissed_reason or "",
            "metadata": dict(question.metadata),
        }


def _normalized_choice(
    value: str,
    allowed: set[str] | frozenset[str],
    *,
    default: str | None = None,
    field: str,
) -> str:
    normalized = str(value or default or "").strip().lower()
    if normalized not in allowed:
        raise ValueError(f"{field} must be one of {sorted(allowed)}: {value!r}")
    return normalized


def _priority(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0.0, min(1.0, parsed))


__all__ = ["CuriosityQuestionManagementSurface"]
