"""Repository-backed Path management surface for built-in tools."""

from __future__ import annotations

from dataclasses import replace
import logging
from typing import Any, Mapping
from uuid import uuid4

from packages.context.epoch_store import FileEpochStore
from packages.context.session_projection import SessionContextEpoch
from packages.contracts.runtime import PromptMessage
from packages.storage.repository_support import DEFAULT_PERSONAL_MODEL_ID

LOGGER = logging.getLogger(__name__)


class RepositoryPathManagementSurface:
    """Adapter used by Mother Elephant to shape durable Paths and Flow Steps."""

    def __init__(self, repository: Any, *, semantic_summary_indexer: Any | None = None) -> None:
        self.repository = repository
        self.semantic_summary_indexer = semantic_summary_indexer

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
                review_mode=_text(kwargs.get("review_mode")) or "trusted",
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
            owner_elephant_id = (
                _text(kwargs.get("owner_elephant_id"))
                if "owner_elephant_id" in kwargs
                else path.owner_elephant_id
            )
            updated = replace(
                path,
                title=_text(kwargs.get("title")) or path.title,
                description=_text(kwargs.get("description")) or path.description,
                status=_text(kwargs.get("status")) or path.status,
                priority=_text(kwargs.get("priority")) or path.priority,
                review_mode=_text(kwargs.get("review_mode")) or path.review_mode,
                owner_elephant_id=owner_elephant_id,
            )
            self.repository.upsert_path(updated)
            return {"action": "update_path", "path": _path_summary(self.repository, updated)}
        if action == "delete_path":
            path_id = _required_text(kwargs, "path_id")
            deleted = self.repository.delete_path(path_id)
            return {"action": "delete_path", "path_id": path_id, "deleted": deleted}
        if action == "create_baby":
            display_name = _text(kwargs.get("display_name")) or _required_text(kwargs, "title")
            elephant_id = _text(kwargs.get("elephant_id")) or _slug_elephant_id(display_name)
            personal_model_id = _text(kwargs.get("personal_model_id")) or DEFAULT_PERSONAL_MODEL_ID
            role_title = _text(kwargs.get("role_title")) or display_name
            role_prompt = _text(kwargs.get("role_prompt") or kwargs.get("instruction")) or f"Use this baby elephant for {role_title} work."
            provider_id = _text(kwargs.get("provider_id"))
            provider_model = _text(kwargs.get("provider_model") or kwargs.get("model_id"))
            runtime_id = _text(kwargs.get("runtime_id"))
            engine_id = _text(kwargs.get("engine_id") or kwargs.get("engine"))
            tool_ids = _text_sequence(kwargs.get("tool_ids") or kwargs.get("allowed_tools") or kwargs.get("allowed_tool_ids"))
            skill_ids = _text_sequence(kwargs.get("skill_ids") or kwargs.get("skills"))
            backend = _text(kwargs.get("backend")) or (
                "provider" if provider_id or provider_model else "local_cli" if runtime_id else "native"
            )
            metadata = {
                **_mapping(kwargs.get("metadata")),
                "herd_kind": "baby",
                "parent_elephant_id": _text(kwargs.get("parent_elephant_id")) or "mother-elephant",
                "role_title": role_title,
                "role_prompt": role_prompt,
                "instruction": role_prompt,
                "runtime_id": runtime_id,
                "engine_id": engine_id,
                "provider_id": provider_id,
                "provider_model": provider_model,
                "tool_ids": ", ".join(tool_ids),
                "skill_ids": ", ".join(skill_ids),
                "enabled": _text(kwargs.get("enabled")) or "true",
                "max_concurrency": _text(kwargs.get("max_concurrency")) or "1",
                "backend": backend,
            }
            identity_text = _text(kwargs.get("elephant_identity_text") or kwargs.get("identity_text"))
            if not identity_text:
                identity_text = (
                    f"# {display_name}\n\n"
                    f"Role: {role_title}\n\n"
                    f"{role_prompt}"
                )
            state = self.repository.create_state(
                personal_model_id=personal_model_id,
                state_id=f"state:{elephant_id}",
                state_anchor=f"elephant:{elephant_id}",
                elephant_id=elephant_id,
                elephant_name=display_name,
                identity_mode="baby",
                initiative="delegated",
                working_style="provider_agent" if backend == "provider" else "local_agent" if backend == "local_cli" else "delegated_specialist",
                surface_bindings=("api", "dashboard"),
                elephant_identity_text=identity_text,
                summary=f"{display_name} is available as a baby elephant for {role_title}.",
                metadata={key: value for key, value in metadata.items() if value},
            )
            return {"action": "create_baby", "baby": _baby_payload(state)}
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
            assignee_elephant_id = (
                _text(kwargs.get("assignee_elephant_id"))
                if "assignee_elephant_id" in kwargs
                else step.assignee_elephant_id
            )
            updated = replace(
                step,
                title=_text(kwargs.get("title")) or step.title,
                description=_text(kwargs.get("description")) or step.description,
                status=_text(kwargs.get("status")) or step.status,
                order_index=_optional_int(kwargs.get("order_index")) if kwargs.get("order_index") is not None else step.order_index,
                assignee_elephant_id=assignee_elephant_id,
            )
            self.repository.upsert_path_step(updated)
            return {"action": action, "step": _step_summary(self.repository, updated)}
        if action == "delete_step":
            step_id = _required_text(kwargs, "path_step_id")
            step = self.repository.load_path_step(step_id)
            path_id = "" if step is None else step.path_id
            deleted = self.repository.delete_path_step(step_id)
            return {"action": "delete_step", "path_step_id": step_id, "path_id": path_id, "deleted": deleted}
        if action in {"create_run", "start_run"}:
            run = self.repository.create_path_step_run(
                path_step_id=_required_text(kwargs, "path_step_id"),
                status=_text(kwargs.get("run_status") or kwargs.get("status")) or "queued",
                attempt=_optional_int(kwargs.get("attempt")),
                max_attempts=_optional_int(kwargs.get("max_attempts")) or 3,
                assignee_elephant_id=_text(kwargs.get("assignee_elephant_id")),
                runtime_id=_text(kwargs.get("runtime_id")),
                session_id=_text(kwargs.get("session_id")) or session_id,
                work_dir=_text(kwargs.get("work_dir")),
                progress_stage=_text(kwargs.get("progress_stage")),
                progress_detail=_text(kwargs.get("progress_detail")),
                progress_current=_optional_int(kwargs.get("progress_current")) or 0,
                progress_total=_optional_int(kwargs.get("progress_total")) or 0,
                failure_reason=_text(kwargs.get("failure_reason")),
                metadata=_mapping(kwargs.get("metadata")),
                run_id=_text(kwargs.get("run_id")) or None,
            )
            step = self.repository.load_path_step(run.path_step_id)
            return {
                "action": "create_run",
                "run": _run_payload(run),
                "step": _step_summary(self.repository, step) if step is not None else None,
            }
        if action == "update_run":
            run = self.repository.update_path_step_run(
                _required_text(kwargs, "run_id"),
                status=_text(kwargs.get("run_status") or kwargs.get("status")) or None,
                progress_stage=_text(kwargs.get("progress_stage")) or None,
                progress_detail=_text(kwargs.get("progress_detail")) or None,
                progress_current=_optional_int(kwargs.get("progress_current")),
                progress_total=_optional_int(kwargs.get("progress_total")),
                failure_reason=_text(kwargs.get("failure_reason")) or None,
                runtime_id=_text(kwargs.get("runtime_id")) or None,
                session_id=_text(kwargs.get("session_id")) or None,
                work_dir=_text(kwargs.get("work_dir")) or None,
                assignee_elephant_id=(
                    _text(kwargs.get("assignee_elephant_id"))
                    if "assignee_elephant_id" in kwargs
                    else None
                ),
                metadata=_mapping(kwargs.get("metadata")),
            )
            step = self.repository.load_path_step(run.path_step_id)
            return {
                "action": "update_run",
                "run": _run_payload(run),
                "step": _step_summary(self.repository, step) if step is not None else None,
            }
        if action == "retry_run":
            run = self.repository.retry_path_step_run(
                _required_text(kwargs, "run_id"),
                reason=_text(kwargs.get("reason")) or "manual_retry",
            )
            step = self.repository.load_path_step(run.path_step_id)
            return {
                "action": "retry_run",
                "run": _run_payload(run),
                "step": _step_summary(self.repository, step) if step is not None else None,
            }
        if action in {"write_comment", "comment"}:
            path_step_id = _required_text(kwargs, "path_step_id")
            comment = self.repository.create_path_step_comment(
                path_step_id=path_step_id,
                body=_required_text(kwargs, "body", "content", "text"),
                author_kind=_text(kwargs.get("author_kind")) or "elephant",
                author_id=_text(kwargs.get("author_id") or kwargs.get("created_by_elephant_id")),
                comment_type=_text(kwargs.get("comment_type")) or "run_output",
                run_id=_text(kwargs.get("run_id")),
                parent_comment_id=_text(kwargs.get("parent_comment_id")),
                metadata=_mapping(kwargs.get("metadata")),
            )
            _project_path_comment_to_epoch(self.repository, session_id, comment)
            return {"action": "write_comment", "comment": _comment_payload(comment)}
        if action in {"write_summary", "learning_summary"}:
            path_step_id = _resolve_summary_path_step_id(self.repository, kwargs)
            summary = self.repository.write_learning_summary(
                path_step_id=path_step_id,
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
            self._index_learning_summary(summary)
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

    def _index_learning_summary(self, summary: Any) -> None:
        indexer = self.semantic_summary_indexer
        index_learning_summary = getattr(indexer, "index_learning_summary", None)
        if not callable(index_learning_summary):
            return
        try:
            step = self.repository.load_path_step(summary.path_step_id)
            path = self.repository.load_path(summary.path_id)
            index_learning_summary(summary, path_step=step, path=path)
        except Exception:
            LOGGER.debug("Path learning summary semantic indexing failed.", exc_info=True)
            return


def _path_summary(repository: Any, path: Any) -> Mapping[str, Any]:
    steps = repository.list_path_steps(path_id=path.path_id)
    return {
        "path_id": path.path_id,
        "title": path.title,
        "description": path.description,
        "status": path.status,
        "priority": path.priority,
        "owner_elephant_id": path.owner_elephant_id,
        "step_count": len(steps),
        "steps": tuple(_step_summary(repository, step) for step in steps),
    }


def _step_summary(repository: Any, step: Any) -> Mapping[str, Any]:
    summaries = repository.list_learning_summaries(path_step_id=step.path_step_id)
    runs = repository.list_path_step_runs(path_step_id=step.path_step_id, limit=5)
    comments = repository.list_path_step_comments(path_step_id=step.path_step_id, limit=10)
    active_run = next((run for run in runs if run.status in {"queued", "dispatched", "running"}), None)
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
        "comments": tuple(_comment_payload(comment) for comment in comments),
        "active_run": _run_payload(active_run),
        "runs": tuple(_run_payload(run) for run in runs),
    }


def _comment_payload(comment: Any) -> Mapping[str, Any]:
    return {
        "comment_id": comment.comment_id,
        "path_step_id": comment.path_step_id,
        "path_id": comment.path_id,
        "body": comment.body,
        "author_kind": comment.author_kind,
        "author_id": comment.author_id,
        "comment_type": comment.comment_type,
        "run_id": comment.run_id,
        "parent_comment_id": comment.parent_comment_id,
        "created_at": comment.created_at.isoformat() if comment.created_at is not None else "",
        "updated_at": comment.updated_at.isoformat() if comment.updated_at is not None else "",
        "metadata": dict(comment.metadata),
    }


def _run_payload(run: Any | None) -> Mapping[str, Any] | None:
    if run is None:
        return None
    return {
        "run_id": run.run_id,
        "path_step_id": run.path_step_id,
        "path_id": run.path_id,
        "status": run.status,
        "attempt": run.attempt,
        "max_attempts": run.max_attempts,
        "parent_run_id": run.parent_run_id,
        "assignee_elephant_id": run.assignee_elephant_id,
        "runtime_id": run.runtime_id,
        "session_id": run.session_id,
        "work_dir": run.work_dir,
        "progress_stage": run.progress_stage,
        "progress_detail": run.progress_detail,
        "progress_current": run.progress_current,
        "progress_total": run.progress_total,
        "failure_reason": run.failure_reason,
        "created_at": run.created_at.isoformat() if run.created_at is not None else "",
        "started_at": run.started_at.isoformat() if run.started_at is not None else "",
        "heartbeat_at": run.heartbeat_at.isoformat() if run.heartbeat_at is not None else "",
        "lease_expires_at": run.lease_expires_at.isoformat() if run.lease_expires_at is not None else "",
        "finished_at": run.finished_at.isoformat() if run.finished_at is not None else "",
        "metadata": dict(run.metadata),
    }


def _baby_payload(state: Any) -> Mapping[str, Any]:
    metadata = dict(getattr(state, "metadata", {}) or {})
    return {
        "state_id": getattr(state, "state_id", ""),
        "elephant_id": getattr(state, "elephant_id", ""),
        "display_name": getattr(state, "elephant_name", ""),
        "herd_kind": metadata.get("herd_kind", "baby"),
        "parent_elephant_id": metadata.get("parent_elephant_id", ""),
        "role_title": metadata.get("role_title", ""),
        "role_prompt": metadata.get("role_prompt", ""),
        "instruction": metadata.get("instruction", ""),
        "runtime_id": metadata.get("runtime_id", ""),
        "engine_id": metadata.get("engine_id", ""),
        "provider_id": metadata.get("provider_id", ""),
        "provider_model": metadata.get("provider_model", ""),
        "tool_ids": metadata.get("tool_ids", ""),
        "skill_ids": metadata.get("skill_ids", ""),
        "backend": metadata.get("backend", ""),
        "max_concurrency": metadata.get("max_concurrency", ""),
        "enabled": metadata.get("enabled", "true"),
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


def _resolve_summary_path_step_id(repository: Any, payload: Mapping[str, Any]) -> str:
    direct = _text(payload.get("path_step_id") or payload.get("step_id"))
    if direct:
        return direct
    run_id = _text(payload.get("run_id"))
    if run_id:
        run = repository.load_path_step_run(run_id)
        if run is None:
            raise KeyError(run_id)
        return run.path_step_id
    path_id = _text(payload.get("path_id"))
    personal_model_id = _text(payload.get("personal_model_id")) or DEFAULT_PERSONAL_MODEL_ID
    status = _optional_status(payload.get("step_status") or payload.get("status"))
    title = _text(payload.get("step_title") or payload.get("title"))
    candidates = tuple(
        step
        for step in repository.list_path_steps(
            path_id=path_id or None,
            personal_model_id=None if path_id else personal_model_id,
            status=status,
            limit=20,
        )
        if not title or step.title.strip().lower() == title.lower()
    )
    if len(candidates) == 1:
        return candidates[0].path_step_id
    active_candidates = tuple(step for step in candidates if step.status in {"moving", "checking", "next"})
    if len(active_candidates) == 1:
        return active_candidates[0].path_step_id
    if candidates:
        rendered = ", ".join(f"{step.path_step_id} ({step.status}: {step.title})" for step in candidates[:5])
        raise ValueError(f"missing required field: path_step_id; multiple candidate steps found: {rendered}")
    raise ValueError("missing required field: path_step_id")


def _required_text(payload: Mapping[str, Any], key: str, *alternate_keys: str) -> str:
    for candidate in (key, *alternate_keys):
        value = _text(payload.get(candidate))
        if value:
            return value
    raise ValueError(f"missing required field: {key}")


def _text(value: object) -> str:
    return str(value or "").strip()


def _mapping(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): _metadata_text(item) for key, item in value.items()}


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


def _text_sequence(value: object) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(_text(item) for item in value if _text(item))
    text = _text(value)
    if not text:
        return ()
    return tuple(part.strip() for part in text.split(",") if part.strip())


def _metadata_text(value: object) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(_text(item) for item in value if _text(item))
    return _text(value)


def _slug_elephant_id(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    slug = "-".join(part for part in slug.split("-") if part)
    if not slug:
        slug = "baby-elephant"
    return f"baby-{slug[:42].strip('-')}-{uuid4().hex[:8]}"


def _project_path_comment_to_epoch(repository: Any, session_id: str, comment: Any) -> None:
    body = _text(getattr(comment, "body", ""))
    path_step_id = _text(getattr(comment, "path_step_id", ""))
    comment_id = _text(getattr(comment, "comment_id", ""))
    if not body or not path_step_id or not comment_id:
        return
    metadata = dict(getattr(comment, "metadata", {}) or {})
    episode_id = _text(metadata.get("episode_id")) or _text(session_id)
    if not episode_id:
        return
    author_kind = _text(getattr(comment, "author_kind", "")).lower()
    if author_kind == "user":
        role = "user"
    elif author_kind == "system":
        role = "system"
    else:
        role = "assistant"
    created_at = getattr(comment, "created_at", None)
    message_metadata = {
        "projection_surface": "path_step",
        "path_step_comment_id": comment_id,
        "path_step_id": path_step_id,
        "path_id": _text(getattr(comment, "path_id", "")),
        "comment_type": _text(getattr(comment, "comment_type", "")),
        "author_kind": _text(getattr(comment, "author_kind", "")),
        "author_id": _text(getattr(comment, "author_id", "")),
        "run_id": _text(getattr(comment, "run_id", "")),
    }
    if created_at is not None:
        message_metadata["created_at"] = created_at.isoformat()
    try:
        store = FileEpochStore(repository.database_path.parent)
        epoch = store.load(episode_id) or SessionContextEpoch(session_id=episode_id)
    except Exception:
        LOGGER.debug("Unable to load Path comment epoch projection", exc_info=True)
        return
    scoped_messages_by_id = {
        _text(message.metadata.get("path_step_comment_id")): message
        for message in epoch.history_messages
        if _text(message.metadata.get("projection_surface")) == "path_step"
        and _text(message.metadata.get("path_step_id")) == path_step_id
        and _text(message.metadata.get("path_step_comment_id"))
    }
    scoped_messages_by_id[comment_id] = PromptMessage(
        role=role,
        content=body,
        metadata=message_metadata,
    )
    retained_messages = tuple(
        message
        for message in epoch.history_messages
        if not (
            _text(message.metadata.get("projection_surface")) == "path_step"
            and _text(message.metadata.get("path_step_id")) == path_step_id
        )
    )
    scoped_messages = tuple(sorted(scoped_messages_by_id.values(), key=_path_comment_message_sort_key))
    try:
        store.save(replace(epoch, history_messages=(*retained_messages, *scoped_messages)))
    except Exception:
        LOGGER.debug("Unable to save Path comment epoch projection", exc_info=True)


def _path_comment_message_sort_key(message: PromptMessage) -> tuple[str, str]:
    metadata = dict(getattr(message, "metadata", {}) or {})
    return (
        _text(metadata.get("created_at")),
        _text(metadata.get("path_step_comment_id")),
    )


__all__ = ["RepositoryPathManagementSurface"]
