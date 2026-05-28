"""Path API payload projection and request parsing helpers."""

from __future__ import annotations

from typing import Any, Mapping

from packages.contracts.paths import (
    LearningSummaryRecord,
    PathRecord,
    PathStepCommentRecord,
    PathStepRecord,
    PathStepRunRecord,
    UnderstandingCheckRecord,
)

from .api_runtime_support import _jsonable, _optional_str


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
    runs = repository.list_path_step_runs(path_step_id=step.path_step_id, limit=5)
    active_run = next((run for run in runs if run.status in {"queued", "dispatched", "running"}), None)
    comments = repository.list_path_step_comments(path_step_id=step.path_step_id, limit=50)
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
        "active_run": _path_step_run_payload(active_run) if active_run is not None else None,
        "runs": tuple(_path_step_run_payload(run) for run in runs),
        "comments": tuple(_path_step_comment_payload(comment) for comment in comments),
    }
    if include_summaries:
        summaries = repository.list_learning_summaries(path_step_id=step.path_step_id)
        payload["learning_summaries"] = tuple(
            _learning_summary_payload(summary, _latest_check_for_summary(repository, summary))
            for summary in summaries
        )
    return _jsonable(payload)


def _path_step_comment_payload(comment: PathStepCommentRecord | None) -> dict[str, Any] | None:
    if comment is None:
        return None
    return _jsonable(
        {
            "comment_id": comment.comment_id,
            "path_step_id": comment.path_step_id,
            "path_id": comment.path_id,
            "personal_model_id": comment.personal_model_id,
            "body": comment.body,
            "author_kind": comment.author_kind,
            "author_id": comment.author_id,
            "comment_type": comment.comment_type,
            "run_id": comment.run_id,
            "parent_comment_id": comment.parent_comment_id,
            "metadata": dict(comment.metadata),
            "created_at": comment.created_at,
            "updated_at": comment.updated_at,
        }
    )


def _path_step_run_payload(run: PathStepRunRecord | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return _jsonable(
        {
            "run_id": run.run_id,
            "path_step_id": run.path_step_id,
            "path_id": run.path_id,
            "personal_model_id": run.personal_model_id,
            "status": run.status,
            "attempt": run.attempt,
            "max_attempts": run.max_attempts,
            "parent_run_id": run.parent_run_id,
            "assignee_elephant_id": run.assignee_elephant_id,
            "runtime_id": run.runtime_id,
            "claim_token": run.claim_token,
            "session_id": run.session_id,
            "work_dir": run.work_dir,
            "progress_stage": run.progress_stage,
            "progress_detail": run.progress_detail,
            "progress_current": run.progress_current,
            "progress_total": run.progress_total,
            "failure_reason": run.failure_reason,
            "metadata": dict(run.metadata),
            "created_at": run.created_at,
            "started_at": run.started_at,
            "heartbeat_at": run.heartbeat_at,
            "lease_expires_at": run.lease_expires_at,
            "finished_at": run.finished_at,
        }
    )


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


def _payload_bool(payload: Mapping[str, Any], *keys: str, default: bool = False) -> bool:
    for key in keys:
        if key not in payload:
            continue
        value = payload.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        text = str(value or "").strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
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
