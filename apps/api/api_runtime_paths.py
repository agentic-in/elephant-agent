"""User-facing Path API and dashboard projections."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping
from urllib.parse import unquote

from packages.contracts.paths import (
    LearningSummaryRecord,
    PathRecord,
    PathStepRecord,
    UnderstandingCheckRecord,
)
from packages.storage.repository_support import DEFAULT_PERSONAL_MODEL_ID

from .api_runtime_support import (
    APIResponse,
    _jsonable,
    _optional_datetime,
    _optional_str,
    _read_json_bytes,
)

PATH_STEP_COLUMNS = (
    ("later", "Later"),
    ("next", "Next"),
    ("moving", "Moving"),
    ("checking", "Checking"),
    ("done", "Done"),
    ("stuck", "Stuck"),
    ("dropped", "Dropped"),
)


def paths_dashboard(repository: Any, *, personal_model_id: str = DEFAULT_PERSONAL_MODEL_ID) -> dict[str, Any]:
    paths = repository.list_paths(personal_model_id=personal_model_id)
    path_payloads = tuple(_path_payload(repository, path, include_steps=True) for path in paths)
    steps = tuple(
        step
        for path in paths
        for step in repository.list_path_steps(path_id=path.path_id)
    )
    columns = tuple(
        {
            "status": status,
            "title": title,
            "count": len([step for step in steps if step.status == status]),
            "steps": tuple(
                _path_step_payload(repository, step, include_summaries=True)
                for step in steps
                if step.status == status
            ),
        }
        for status, title in PATH_STEP_COLUMNS
    )
    pending_understanding = 0
    for step in steps:
        for summary in repository.list_learning_summaries(path_step_id=step.path_step_id):
            checks = repository.list_understanding_checks(summary_id=summary.summary_id, checked_by="user")
            if not checks or checks[0].status != "understood":
                pending_understanding += 1
    return {
        "paths": path_payloads,
        "columns": columns,
        "counts": {
            "paths": len(path_payloads),
            "steps": len(steps),
            "understanding_pending": pending_understanding,
        },
    }


def _dispatch_paths(self, method: str, parts: tuple[str, ...], body: bytes | None) -> APIResponse:
    normalized_method = method.upper()
    if normalized_method == "GET" and not parts:
        personal_model_id = DEFAULT_PERSONAL_MODEL_ID
        return APIResponse(200, {"paths": paths_dashboard(self.repository, personal_model_id=personal_model_id)})
    if normalized_method == "POST" and not parts:
        payload = _read_json_bytes(body)
        path = self.repository.create_path(
            personal_model_id=_payload_text(payload, "personal_model_id", "personalModelId", default=DEFAULT_PERSONAL_MODEL_ID),
            title=_required_payload_text(payload, "title"),
            description=_payload_text(payload, "description", "detail"),
            priority=_payload_text(payload, "priority", default="normal"),
            review_mode=_payload_text(payload, "review_mode", "reviewMode", default="ask_first"),
            owner_elephant_id=_payload_text(payload, "owner_elephant_id", "ownerElephantId"),
            metadata=_payload_mapping(payload.get("metadata")),
        )
        for index, step_payload in enumerate(_payload_list(payload.get("steps"))):
            self.repository.create_path_step(
                path_id=path.path_id,
                title=_required_payload_text(step_payload, "title"),
                description=_payload_text(step_payload, "description", "detail"),
                status=_payload_text(step_payload, "status", default="next"),
                order_index=index,
                assignee_elephant_id=_payload_text(step_payload, "assignee_elephant_id", "assigneeElephantId"),
                creator_elephant_id=_payload_text(step_payload, "creator_elephant_id", "creatorElephantId"),
                metadata=_payload_mapping(step_payload.get("metadata")),
            )
        return APIResponse(201, {"path": _path_payload(self.repository, path, include_steps=True)})

    if not parts:
        return APIResponse(404, {"error": "not_found"})
    path_id = unquote(parts[0])
    path = self.repository.load_path(path_id)
    if path is None:
        raise KeyError(path_id)

    if normalized_method == "GET" and len(parts) == 1:
        return APIResponse(200, {"path": _path_payload(self.repository, path, include_steps=True)})
    if normalized_method == "PATCH" and len(parts) == 1:
        payload = _read_json_bytes(body)
        updated = replace(
            path,
            title=_payload_text(payload, "title", default=path.title),
            description=_payload_text(payload, "description", "detail", default=path.description),
            status=_payload_text(payload, "status", default=path.status),
            priority=_payload_text(payload, "priority", default=path.priority),
            review_mode=_payload_text(payload, "review_mode", "reviewMode", default=path.review_mode),
            owner_elephant_id=_payload_text(payload, "owner_elephant_id", "ownerElephantId", default=path.owner_elephant_id),
            metadata=_payload_mapping(payload.get("metadata")) if "metadata" in payload else path.metadata,
        )
        self.repository.upsert_path(updated)
        return APIResponse(200, {"path": _path_payload(self.repository, updated, include_steps=True)})

    if len(parts) >= 2 and parts[1] == "steps":
        return _dispatch_path_steps(self, normalized_method, path, parts[2:], body)

    return APIResponse(404, {"error": "not_found"})


def _dispatch_path_steps(
    self,
    method: str,
    path: PathRecord,
    parts: tuple[str, ...],
    body: bytes | None,
) -> APIResponse:
    if method == "POST" and not parts:
        payload = _read_json_bytes(body)
        step = self.repository.create_path_step(
            path_id=path.path_id,
            title=_required_payload_text(payload, "title"),
            description=_payload_text(payload, "description", "detail"),
            status=_payload_text(payload, "status", default="next"),
            order_index=_payload_optional_int(payload, "order_index", "orderIndex"),
            assignee_elephant_id=_payload_text(payload, "assignee_elephant_id", "assigneeElephantId"),
            creator_elephant_id=_payload_text(payload, "creator_elephant_id", "creatorElephantId"),
            due_at=_optional_datetime(payload.get("due_at") or payload.get("dueAt")),
            related_episode_id=_optional_str(payload.get("related_episode_id") or payload.get("relatedEpisodeId")),
            related_loop_id=_optional_str(payload.get("related_loop_id") or payload.get("relatedLoopId")),
            metadata=_payload_mapping(payload.get("metadata")),
        )
        return APIResponse(201, {"step": _path_step_payload(self.repository, step, include_summaries=True)})
    if not parts:
        return APIResponse(404, {"error": "not_found"})
    step_id = unquote(parts[0])
    step = self.repository.load_path_step(step_id)
    if step is None or step.path_id != path.path_id:
        raise KeyError(step_id)
    if method == "GET" and len(parts) == 1:
        return APIResponse(200, {"step": _path_step_payload(self.repository, step, include_summaries=True)})
    if method == "PATCH" and len(parts) == 1:
        payload = _read_json_bytes(body)
        order_index = _payload_optional_int(payload, "order_index", "orderIndex", default=step.order_index)
        updated = replace(
            step,
            title=_payload_text(payload, "title", default=step.title),
            description=_payload_text(payload, "description", "detail", default=step.description),
            status=_payload_text(payload, "status", default=step.status),
            order_index=step.order_index if order_index is None else order_index,
            assignee_elephant_id=_payload_text(payload, "assignee_elephant_id", "assigneeElephantId", default=step.assignee_elephant_id),
            creator_elephant_id=_payload_text(payload, "creator_elephant_id", "creatorElephantId", default=step.creator_elephant_id),
            due_at=_optional_datetime(payload.get("due_at") or payload.get("dueAt")) if ("due_at" in payload or "dueAt" in payload) else step.due_at,
            metadata=_payload_mapping(payload.get("metadata")) if "metadata" in payload else step.metadata,
        )
        self.repository.upsert_path_step(updated)
        return APIResponse(200, {"step": _path_step_payload(self.repository, updated, include_summaries=True)})
    if method == "POST" and len(parts) == 2 and parts[1] == "learning-summary":
        payload = _read_json_bytes(body)
        summary = self.repository.write_learning_summary(
            path_step_id=step.path_step_id,
            what_done=_payload_text(payload, "what_done", "whatDone", "summary"),
            why_it_matters=_payload_text(payload, "why_it_matters", "whyItMatters"),
            how_it_was_done=_payload_text(payload, "how_it_was_done", "howItWasDone"),
            knowledge=_payload_text(payload, "knowledge"),
            human_takeaway=_payload_text(payload, "human_takeaway", "humanTakeaway"),
            run_id=_payload_text(payload, "run_id", "runId"),
            summary_type=_payload_text(payload, "summary_type", "summaryType", default="task"),
            created_by_elephant_id=_payload_text(payload, "created_by_elephant_id", "createdByElephantId"),
            metadata=_payload_mapping(payload.get("metadata")),
        )
        check = self.repository.write_understanding_check(
            summary_id=summary.summary_id,
            status="pending",
            checked_by=_payload_text(payload, "checked_by", "checkedBy", default="user"),
        )
        return APIResponse(201, {"summary": _learning_summary_payload(summary, check)})
    if method == "POST" and len(parts) == 2 and parts[1] == "understanding-check":
        payload = _read_json_bytes(body)
        summary_id = _payload_text(payload, "summary_id", "summaryId")
        if not summary_id:
            summaries = self.repository.list_learning_summaries(path_step_id=step.path_step_id, limit=1)
            if not summaries:
                raise KeyError("learning_summary")
            summary_id = summaries[0].summary_id
        status = _payload_text(payload, "status", default="")
        if not status:
            status = "understood" if bool(payload.get("understood", True)) else "needs_clarification"
        check = self.repository.write_understanding_check(
            summary_id=summary_id,
            status=status,
            checked_by=_payload_text(payload, "checked_by", "checkedBy", default="user"),
            note=_payload_text(payload, "note"),
            metadata=_payload_mapping(payload.get("metadata")),
        )
        return APIResponse(200, {"check": _understanding_check_payload(check)})
    return APIResponse(404, {"error": "not_found"})


def _path_payload(repository: Any, path: PathRecord, *, include_steps: bool = False) -> dict[str, Any]:
    payload = {
        "path_id": path.path_id,
        "personal_model_id": path.personal_model_id,
        "title": path.title,
        "description": path.description,
        "status": path.status,
        "priority": path.priority,
        "review_mode": path.review_mode,
        "owner_elephant_id": path.owner_elephant_id,
        "metadata": dict(path.metadata),
        "created_at": path.created_at,
        "updated_at": path.updated_at,
    }
    if include_steps:
        payload["steps"] = tuple(
            _path_step_payload(repository, step, include_summaries=True)
            for step in repository.list_path_steps(path_id=path.path_id)
        )
    return _jsonable(payload)


def _path_step_payload(repository: Any, step: PathStepRecord, *, include_summaries: bool = False) -> dict[str, Any]:
    payload = {
        "path_step_id": step.path_step_id,
        "path_id": step.path_id,
        "personal_model_id": step.personal_model_id,
        "title": step.title,
        "description": step.description,
        "status": step.status,
        "order_index": step.order_index,
        "assignee_elephant_id": step.assignee_elephant_id,
        "creator_elephant_id": step.creator_elephant_id,
        "due_at": step.due_at,
        "related_episode_id": step.related_episode_id,
        "related_loop_id": step.related_loop_id,
        "metadata": dict(step.metadata),
        "created_at": step.created_at,
        "updated_at": step.updated_at,
        "completed_at": step.completed_at,
    }
    if include_summaries:
        summaries = repository.list_learning_summaries(path_step_id=step.path_step_id)
        payload["learning_summaries"] = tuple(
            _learning_summary_payload(summary, _latest_check_for_summary(repository, summary))
            for summary in summaries
        )
    return _jsonable(payload)


def _learning_summary_payload(
    summary: LearningSummaryRecord,
    check: UnderstandingCheckRecord | None = None,
) -> dict[str, Any]:
    payload = {
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
        "metadata": dict(summary.metadata),
        "created_at": summary.created_at,
    }
    if check is not None:
        payload["understanding_check"] = _understanding_check_payload(check)
    return _jsonable(payload)


def _understanding_check_payload(check: UnderstandingCheckRecord) -> dict[str, Any]:
    return _jsonable(
        {
            "check_id": check.check_id,
            "path_step_id": check.path_step_id,
            "summary_id": check.summary_id,
            "status": check.status,
            "checked_by": check.checked_by,
            "checked_at": check.checked_at,
            "note": check.note,
            "metadata": dict(check.metadata),
            "created_at": check.created_at,
            "updated_at": check.updated_at,
        }
    )


def _latest_check_for_summary(repository: Any, summary: LearningSummaryRecord) -> UnderstandingCheckRecord | None:
    checks = repository.list_understanding_checks(summary_id=summary.summary_id, checked_by="user", limit=1)
    if checks:
        return checks[0]
    checks = repository.list_understanding_checks(summary_id=summary.summary_id, limit=1)
    return checks[0] if checks else None


def _required_payload_text(payload: Mapping[str, Any], *keys: str) -> str:
    text = _payload_text(payload, *keys)
    if not text:
        label = keys[0] if keys else "value"
        raise ValueError(f"missing required field: {label}")
    return text


def _payload_text(payload: Mapping[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        if key in payload:
            text = _optional_str(payload.get(key))
            return text or default
    return default


def _payload_optional_int(
    payload: Mapping[str, Any],
    *keys: str,
    default: int | None = None,
) -> int | None:
    for key in keys:
        if key in payload:
            value = payload.get(key)
            if value is None or str(value).strip() == "":
                return default
            return int(value)
    return default


def _payload_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _payload_list(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


__all__ = [
    "PATH_STEP_COLUMNS",
    "_dispatch_paths",
    "paths_dashboard",
]
