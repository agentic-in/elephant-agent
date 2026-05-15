"""Helper functions for HTTP dispatch routing in the API runtime."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from .api_runtime_support import _jsonable, _optional_str


def _elephant_id_from_name(name: str) -> str:
    """Convert elephant display name to elephant ID format."""
    import re
    return re.sub(r"[^a-zA-Z0-9_-]", "", name.lower().replace(" ", "-"))


def _session_compat_payload(payload: Any) -> Any:
    """Translate canonical episode payloads for the `/v1/sessions` surface."""
    payload = _jsonable(payload)
    if isinstance(payload, dict):
        translated = dict(payload)
        if isinstance(payload.get("episode"), dict):
            translated["session"] = _session_compat_aliases(payload["episode"])
            translated["episode_id"] = payload["episode"].get("episode_id")
        if isinstance(payload.get("parent_episode"), dict):
            translated["parent"] = _session_compat_aliases(payload["parent_episode"])
        if isinstance(payload.get("personal_model"), dict):
            translated["profile"] = payload["personal_model"]
        if "latest_loop" in payload:
            translated["latest_turn"] = (
                _loop_compat_aliases(payload["latest_loop"])
                if isinstance(payload.get("latest_loop"), dict)
                else None
            )
        if isinstance(payload.get("outcome"), dict):
            translated["outcome"] = _outcome_compat_aliases(payload["outcome"])
        if isinstance(payload.get("inspection"), dict):
            translated["inspection"] = _inspection_compat_aliases(payload["inspection"])
        if isinstance(payload.get("lineage"), list):
            translated["lineage"] = [
                _session_compat_aliases(item) if isinstance(item, dict) else item
                for item in payload["lineage"]
            ]
        return {
            **translated,
            "episode_id": translated.get("episode_id") or translated.get("session_id"),
        }
    return payload


def _session_compat_aliases(value: Any) -> Any:
    """Apply session field aliases to response values."""
    if isinstance(value, dict):
        return {
            **value,
            "session_id": value.get("episode_id"),
            "sessionId": value.get("episode_id"),
        }
    return value


def _loop_compat_aliases(value: Mapping[str, Any]) -> dict[str, Any]:
    translated = dict(value)
    if isinstance(value.get("outcome"), dict):
        translated["outcome"] = _outcome_compat_aliases(value["outcome"])
    return translated


def _inspection_compat_aliases(value: Mapping[str, Any]) -> dict[str, Any]:
    translated = dict(value)
    if isinstance(value.get("episode"), dict):
        translated["session"] = _session_compat_aliases(value["episode"])
    if isinstance(value.get("latest_loop"), dict):
        translated["latest_turn"] = _loop_compat_aliases(value["latest_loop"])
    return translated


def _outcome_compat_aliases(value: Mapping[str, Any]) -> dict[str, Any]:
    translated = dict(value)
    event = dict(value.get("event")) if isinstance(value.get("event"), dict) else {}
    if event:
        episode_id = event.get("episode_id")
        if episode_id:
            event.setdefault("session_id", episode_id)
            event.setdefault("sessionId", episode_id)
        translated["event"] = event
    return translated


def _cron_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Extract validated cron job payload."""
    job_payload = {
        key: value
        for key, value in (
            ("prompt", _optional_str(payload.get("prompt"))),
        )
        if value is not None
    }
    skills = _cron_skill_ids(payload.get("skills"))
    if skills:
        job_payload["skills"] = list(skills)
    extra_payload = payload.get("payload")
    if isinstance(extra_payload, Mapping):
        for key, value in extra_payload.items():
            if key not in job_payload:
                job_payload[str(key)] = value
    return job_payload


def _cron_skill_ids(value: object) -> tuple[str, ...]:
    """Extract unique skill IDs from various formats."""
    if value is None:
        return ()
    if isinstance(value, str):
        raw_items = value.replace("\n", ",").split(",")
    elif isinstance(value, (list, tuple)):
        raw_items = [str(item) for item in value]
    else:
        raw_items = [str(value)]
    return tuple(dict.fromkeys(item.strip() for item in raw_items if item.strip()))


def _cron_job_system_kind(job: Any) -> str | None:
    """Return the stable system-job kind for built-in cron rows."""
    action_kind = str(getattr(job, "action_kind", "") or "").strip().lower()
    if action_kind == "system":
        return "proactive-ask"
    payload = getattr(job, "payload", None)
    if isinstance(payload, Mapping):
        trigger = str(payload.get("trigger") or "").strip().lower()
        if action_kind == "learning" and trigger == "dream":
            return "dream"
    return None


def _cron_job_record(job) -> dict[str, Any]:
    """Serialize cron job record to API response format."""
    system_kind = _cron_job_system_kind(job)
    return {
        "jobId": job.job_id,
        "name": job.name,
        "schedule": job.schedule_text,
        "scheduleKind": job.schedule_kind,
        "jobKind": job.action_kind,
        "status": job.status,
        "profileId": job.profile_id,
        "eggId": job.elephant_id,
        "payload": dict(job.payload),
        "skills": list(_cron_skill_ids(job.payload.get("skills"))),
        "createdAt": job.created_at.isoformat(),
        "updatedAt": job.updated_at.isoformat(),
        "nextRunAt": job.next_run_at.isoformat() if job.next_run_at is not None else None,
        "lastRunAt": job.last_run_at.isoformat() if job.last_run_at is not None else None,
        "runCount": job.run_count,
        "lastSummary": job.last_summary,
        "isSystem": system_kind is not None,
        "systemKind": system_kind,
        "canRunNow": True,
        "canPause": True,
        "canDelete": system_kind is None,
    }


def _read_wsgi_body(environ: Mapping[str, Any]) -> bytes:
    """Read HTTP request body from WSGI environ."""
    body = environ.get("wsgi.input")
    if body is None:
        return b""
    raw_length = environ.get("CONTENT_LENGTH")
    try:
        length = int(str(raw_length)) if raw_length not in {None, ""} else 0
    except (TypeError, ValueError):
        length = 0
    if length <= 0:
        return b""
    return body.read(length)


__all__ = [
    "_elephant_id_from_name",
    "_session_compat_payload",
    "_session_compat_aliases",
    "_cron_payload",
    "_cron_skill_ids",
    "_cron_job_system_kind",
    "_cron_job_record",
    "_read_wsgi_body",
]
