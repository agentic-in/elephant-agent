"""Repository-backed Path management surface for built-in tools."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from packages.storage.repository_support import DEFAULT_PERSONAL_MODEL_ID


class RepositoryPathManagementSurface:
    """Adapter used by Mother Elephant to shape durable Paths and Flow Steps."""

    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def manage_paths(self, session_id: str, **kwargs: Any) -> Mapping[str, Any]:
        action = str(kwargs.get("action") or "list").strip().lower().replace("-", "_")
        if action in {"list", "ls"}:
            paths = self.repository.list_paths(
                personal_model_id=str(kwargs.get("personal_model_id") or DEFAULT_PERSONAL_MODEL_ID),
                status=_optional_status(kwargs.get("status")),
                limit=_optional_int(kwargs.get("limit")),
            )
            return {
                "action": "list",
                "paths": tuple(_path_summary(self.repository, path) for path in paths),
            }
        if action in {"create_path", "create"}:
            title = _required_text(kwargs, "title")
            path = self.repository.create_path(
                personal_model_id=str(kwargs.get("personal_model_id") or DEFAULT_PERSONAL_MODEL_ID),
                title=title,
                description=_text(kwargs.get("description")),
                priority=_text(kwargs.get("priority")) or "normal",
                review_mode=_text(kwargs.get("review_mode")) or "ask_first",
                owner_elephant_id=_text(kwargs.get("owner_elephant_id")),
                metadata=_mapping(kwargs.get("metadata")),
            )
            for index, step_payload in enumerate(_mapping_sequence(kwargs.get("steps"))):
                self.repository.create_path_step(
                    path_id=path.path_id,
                    title=_required_text(step_payload, "title"),
                    description=_text(step_payload.get("description")),
                    status=_text(step_payload.get("status")) or "next",
                    order_index=index,
                    assignee_elephant_id=_text(step_payload.get("assignee_elephant_id")),
                    creator_elephant_id=_text(step_payload.get("creator_elephant_id")),
                    metadata=_mapping(step_payload.get("metadata")),
                )
            return {"action": "create_path", "path": _path_summary(self.repository, path)}
        if action == "update_path":
            path = self.repository.load_path(_required_text(kwargs, "path_id"))
            if path is None:
                raise KeyError(str(kwargs.get("path_id")))
            updated = replace(
                path,
                title=_text(kwargs.get("title")) or path.title,
                description=_text(kwargs.get("description")) or path.description,
                status=_text(kwargs.get("status")) or path.status,
                priority=_text(kwargs.get("priority")) or path.priority,
                review_mode=_text(kwargs.get("review_mode")) or path.review_mode,
                owner_elephant_id=_text(kwargs.get("owner_elephant_id")) or path.owner_elephant_id,
            )
            self.repository.upsert_path(updated)
            return {"action": "update_path", "path": _path_summary(self.repository, updated)}
        if action in {"create_step", "add_step"}:
            step = self.repository.create_path_step(
                path_id=_required_text(kwargs, "path_id"),
                title=_required_text(kwargs, "title"),
                description=_text(kwargs.get("description")),
                status=_text(kwargs.get("status")) or "next",
                order_index=_optional_int(kwargs.get("order_index")),
                assignee_elephant_id=_text(kwargs.get("assignee_elephant_id")),
                creator_elephant_id=_text(kwargs.get("creator_elephant_id")),
                metadata=_mapping(kwargs.get("metadata")),
            )
            return {"action": "create_step", "step": _step_summary(self.repository, step)}
        if action in {"update_step", "move_step"}:
            step = self.repository.load_path_step(_required_text(kwargs, "path_step_id"))
            if step is None:
                raise KeyError(str(kwargs.get("path_step_id")))
            updated = replace(
                step,
                title=_text(kwargs.get("title")) or step.title,
                description=_text(kwargs.get("description")) or step.description,
                status=_text(kwargs.get("status")) or step.status,
                order_index=_optional_int(kwargs.get("order_index")) if kwargs.get("order_index") is not None else step.order_index,
                assignee_elephant_id=_text(kwargs.get("assignee_elephant_id")) or step.assignee_elephant_id,
            )
            self.repository.upsert_path_step(updated)
            return {"action": action, "step": _step_summary(self.repository, updated)}
        if action in {"write_summary", "learning_summary"}:
            summary = self.repository.write_learning_summary(
                path_step_id=_required_text(kwargs, "path_step_id"),
                what_done=_text(kwargs.get("what_done") or kwargs.get("summary")),
                why_it_matters=_text(kwargs.get("why_it_matters")),
                how_it_was_done=_text(kwargs.get("how_it_was_done")),
                knowledge=_text(kwargs.get("knowledge")),
                human_takeaway=_text(kwargs.get("human_takeaway")),
                run_id=_text(kwargs.get("run_id")),
                summary_type=_text(kwargs.get("summary_type")) or "task",
                created_by_elephant_id=_text(kwargs.get("created_by_elephant_id")),
                metadata=_mapping(kwargs.get("metadata")),
            )
            check = self.repository.write_understanding_check(summary_id=summary.summary_id, status="pending")
            return {"action": "write_summary", "summary": _summary_payload(summary), "understanding_check": _check_payload(check)}
        if action in {"check_understanding", "understanding_check"}:
            check = self.repository.write_understanding_check(
                summary_id=_required_text(kwargs, "summary_id"),
                status=_text(kwargs.get("status")) or "understood",
                checked_by=_text(kwargs.get("checked_by")) or "user",
                note=_text(kwargs.get("note")),
                metadata=_mapping(kwargs.get("metadata")),
            )
            return {"action": "check_understanding", "understanding_check": _check_payload(check)}
        raise ValueError(f"tool.paths.manage does not support action={action!r}")


def _path_summary(repository: Any, path: Any) -> Mapping[str, Any]:
    steps = repository.list_path_steps(path_id=path.path_id)
    return {
        "path_id": path.path_id,
        "title": path.title,
        "description": path.description,
        "status": path.status,
        "priority": path.priority,
        "review_mode": path.review_mode,
        "owner_elephant_id": path.owner_elephant_id,
        "step_count": len(steps),
        "steps": tuple(_step_summary(repository, step) for step in steps),
    }


def _step_summary(repository: Any, step: Any) -> Mapping[str, Any]:
    summaries = repository.list_learning_summaries(path_step_id=step.path_step_id)
    return {
        "path_step_id": step.path_step_id,
        "path_id": step.path_id,
        "title": step.title,
        "description": step.description,
        "status": step.status,
        "order_index": step.order_index,
        "assignee_elephant_id": step.assignee_elephant_id,
        "creator_elephant_id": step.creator_elephant_id,
        "summary_count": len(summaries),
        "learning_summaries": tuple(_summary_payload(summary) for summary in summaries),
    }


def _summary_payload(summary: Any) -> Mapping[str, Any]:
    return {
        "summary_id": summary.summary_id,
        "path_step_id": summary.path_step_id,
        "path_id": summary.path_id,
        "run_id": summary.run_id,
        "summary_type": summary.summary_type,
        "what_done": summary.what_done,
        "why_it_matters": summary.why_it_matters,
        "how_it_was_done": summary.how_it_was_done,
        "knowledge": summary.knowledge,
        "human_takeaway": summary.human_takeaway,
        "created_by_elephant_id": summary.created_by_elephant_id,
    }


def _check_payload(check: Any) -> Mapping[str, Any]:
    return {
        "check_id": check.check_id,
        "path_step_id": check.path_step_id,
        "summary_id": check.summary_id,
        "status": check.status,
        "checked_by": check.checked_by,
        "note": check.note,
    }


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = _text(payload.get(key))
    if not value:
        raise ValueError(f"missing required field: {key}")
    return value


def _text(value: object) -> str:
    return str(value or "").strip()


def _mapping(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _mapping_sequence(value: object) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _optional_int(value: object) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    return int(value)


def _optional_status(value: object) -> str | tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return tuple(_text(item) for item in value if _text(item))
    text = _text(value)
    return text or None


__all__ = ["RepositoryPathManagementSurface"]
