"""Canonical internal dashboard inspection methods."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
import json
from pathlib import Path
import sqlite3
from typing import Any

from .api_runtime_console import (
    _cron_jobs,
    _gateway,
    _logs,
    _mcp_catalog,
    _profile_overrides,
    _settings,
    _skills,
    _tools,
)
from .api_runtime_console_usage import normalize_token_usage_row
from .api_runtime_support import _jsonable, _now


_INTERNAL_DASHBOARD_QUERY_CONTRACT = (
    "Internal dashboard inspection is centered on Personal Model claims, PM history/source rows, Questions, Elephant State, Episode, Step, semantic recall, and provider status.",
    "Dashboard management bridges may operate skills, tools, MCP, cron, gateway, provider, and settings controls; durable user understanding remains Personal Model claims.",
    "Episode resume comes from State.current_context_note copied into Episode metadata at Episode open; live work belongs in Episode, Step, recall, or explicit task tools.",
    "Runtime trace starts from Episode and renders ordered Step facts rather than profile/session summaries.",
)


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    return _jsonable(value)


def _sort_items(items: tuple[Any, ...], *, id_field: str, time_field: str | None = None) -> tuple[Any, ...]:
    if time_field is None:
        return tuple(sorted(items, key=lambda item: str(getattr(item, id_field))))
    return tuple(
        sorted(
            items,
            key=lambda item: (str(getattr(item, time_field) or ""), str(getattr(item, id_field))),
            reverse=True,
        )
    )


def _dashboard_active_provider(active_provider: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider_id": active_provider.get("provider_id"),
        "source": active_provider.get("source"),
        "status": active_provider.get("status"),
        "model_id": active_provider.get("model_id") or active_provider.get("default_model"),
        "base_url": active_provider.get("base_url"),
        "context_window_tokens": active_provider.get("context_window_tokens"),
        "context_window_mode": active_provider.get("context_window_mode"),
        "embedding_bootstrap_status": active_provider.get("embedding_bootstrap_status"),
    }


def _dashboard_provider_doctor(provider_doctor: dict[str, Any], active_provider: dict[str, Any]) -> dict[str, Any]:
    doctor = dict(provider_doctor)
    if "active_provider" in doctor:
        doctor["active_provider"] = _dashboard_active_provider(active_provider)
    return doctor


def _connection(database_path: Any) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    return connection


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _query(
    connection: sqlite3.Connection,
    sql: str,
    params: tuple[object, ...] = (),
) -> list[dict[str, Any]]:
    try:
        rows = connection.execute(sql, params).fetchall()
    except sqlite3.Error:
        return []
    return [dict(row) for row in rows]


def _usage_int(value: object) -> int:
    try:
        return max(0, int(str(value or "0")))
    except (TypeError, ValueError):
        return 0


def _usage_metadata(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    try:
        payload = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _usage_created_day(row: Mapping[str, Any]) -> str:
    created_at = str(row.get("created_at") or row.get("createdAt") or "").strip()
    return created_at[:10] if len(created_at) >= 10 else "unknown"


def _usage_sort_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return (
        str(row.get("created_at") or row.get("createdAt") or ""),
        str(row.get("usage_id") or row.get("usageId") or ""),
    )


def _usage_summary(events: list[dict[str, Any]], *, step_fallback_count: int) -> dict[str, Any]:
    total = sum(_usage_int(row.get("total_tokens")) for row in events)
    recording_level = "runtime Step usage"
    if not events:
        recording_level = "no usage rows yet"
    return {
        "promptTokens": sum(_usage_int(row.get("prompt_tokens")) for row in events),
        "completionTokens": sum(_usage_int(row.get("completion_tokens")) for row in events),
        "totalTokens": total,
        "runtimeStepUsageEvents": step_fallback_count,
        "usageEvents": len(events),
        "recordingLevel": recording_level,
    }


def _usage_trend(events: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in events:
        day = _usage_created_day(row)
        bucket = grouped.setdefault(
            day,
            {
                "day": day,
                "promptTokens": 0,
                "completionTokens": 0,
                "totalTokens": 0,
                "turns": 0,
            },
        )
        bucket["promptTokens"] += _usage_int(row.get("prompt_tokens"))
        bucket["completionTokens"] += _usage_int(row.get("completion_tokens"))
        bucket["totalTokens"] += _usage_int(row.get("total_tokens"))
        bucket["turns"] += 1
    return tuple(sorted(grouped.values(), key=lambda row: str(row["day"]), reverse=True)[:90])


def _usage_by_elephant(events: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in events:
        elephant_id = str(
            row.get("eggId")
            or row.get("elephant_id")
            or row.get("profile_id")
            or row.get("session_id")
            or "unknown"
        )
        elephant_name = str(row.get("eggName") or row.get("elephant_name") or elephant_id)
        bucket = grouped.setdefault(
            elephant_id,
            {
                "eggId": elephant_id,
                "eggName": elephant_name,
                "promptTokens": 0,
                "completionTokens": 0,
                "totalTokens": 0,
                "turns": 0,
                "lastUsedAt": "",
            },
        )
        bucket["eggName"] = elephant_name
        bucket["promptTokens"] += _usage_int(row.get("prompt_tokens"))
        bucket["completionTokens"] += _usage_int(row.get("completion_tokens"))
        bucket["totalTokens"] += _usage_int(row.get("total_tokens"))
        bucket["turns"] += 1
        created_at = str(row.get("created_at") or "")
        if created_at > str(bucket["lastUsedAt"]):
            bucket["lastUsedAt"] = created_at
    return tuple(
        sorted(
            grouped.values(),
            key=lambda row: (_usage_int(row.get("totalTokens")), str(row.get("lastUsedAt") or "")),
            reverse=True,
        )[:50]
    )


def _step_usage_events(
    connection: sqlite3.Connection,
    *,
    ledger_execution_ids: set[str],
    ledger_source_event_ids: set[str],
) -> list[dict[str, Any]]:
    if not _table_exists(connection, "steps"):
        return []
    rows = _query(
        connection,
        """
        SELECT steps.step_id, steps.loop_id, steps.episode_id, steps.state_id,
               steps.personal_model_id, steps.action, steps.status, steps.summary,
               steps.payload_refs_json, steps.metadata_json, steps.created_at,
               states.elephant_id AS eggId, states.elephant_name AS eggName
        FROM steps
        LEFT JOIN states ON states.state_id = steps.state_id
        WHERE steps.metadata_json LIKE '%prompt_tokens%'
           OR steps.metadata_json LIKE '%completion_tokens%'
           OR steps.metadata_json LIKE '%total_tokens%'
        ORDER BY steps.created_at DESC, steps.step_id DESC
        LIMIT 500
        """,
    )
    events: list[dict[str, Any]] = []
    for row in rows:
        metadata = _usage_metadata(row.get("metadata_json"))
        prompt_tokens = _usage_int(metadata.get("prompt_tokens"))
        completion_tokens = _usage_int(metadata.get("completion_tokens"))
        total_tokens = _usage_int(metadata.get("total_tokens")) or prompt_tokens + completion_tokens
        if total_tokens <= 0:
            continue
        step_id = str(row.get("step_id") or "")
        execution_id = str(metadata.get("execution_id") or "").strip()
        if execution_id and execution_id in ledger_execution_ids:
            continue
        if step_id and step_id in ledger_source_event_ids:
            continue
        events.append(
            normalize_token_usage_row(
                {
                    "usage_id": f"step:{step_id}",
                    "session_id": row.get("state_id"),
                    "profile_id": row.get("personal_model_id"),
                    "run_id": row.get("loop_id"),
                    "source_event_id": step_id,
                    "provider_id": metadata.get("provider_id") or metadata.get("providerId") or "runtime",
                    "model_id": metadata.get("model_id") or metadata.get("modelId") or "runtime-step",
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "unit": "tokens",
                    "metadata_json": json.dumps(
                        {
                            **metadata,
                            "usage_source": "runtime_step",
                            "step_id": step_id,
                            "step_action": row.get("action"),
                        }
                    ),
                    "created_at": row.get("created_at"),
                    "eggId": row.get("eggId") or row.get("state_id"),
                    "eggName": row.get("eggName") or row.get("state_id"),
                    "source": "runtime_step",
                    "sourceLabel": "Runtime Step",
                }
            )
        )
    return events


def _canonical_usage(database_path: Any) -> dict[str, Any]:
    with _connection(database_path) as connection:
        step_events = _step_usage_events(
            connection,
            ledger_execution_ids=set(),
            ledger_source_event_ids=set(),
        )
    combined_events = sorted(
        step_events,
        key=_usage_sort_key,
        reverse=True,
    )
    return {
        "summary": _usage_summary(combined_events, step_fallback_count=len(step_events)),
        "tokenEvents": tuple(combined_events),
        "tokenTrend": _usage_trend(combined_events),
        "eggUsage": _usage_by_elephant(combined_events),
    }


def _metadata_value(item: Any, key: str) -> str:
    metadata = getattr(item, "metadata", {}) or {}
    if not isinstance(metadata, Mapping):
        return ""
    return str(metadata.get(key) or "").strip()


def _latest_time(items: tuple[Any, ...]) -> str | None:
    """Return the newest dashboard-safe timestamp from contract rows."""
    candidates: list[str] = []
    for item in items:
        for field in ("updated_at", "committed_at", "created_at", "started_at"):
            value = getattr(item, field, None)
            if value is None:
                continue
            isoformat = getattr(value, "isoformat", None)
            text = isoformat() if callable(isoformat) else str(value)
            if text:
                candidates.append(text)
            break
    return max(candidates) if candidates else None


def _learning_snapshot(
    self,
    *,
    state_dir: Path,
    states_by_id: Mapping[str, Any],
    episodes_by_id: Mapping[str, Any],
) -> dict[str, Any]:
    list_jobs = getattr(self.repository, "list_learning_jobs", None)
    jobs = tuple(list_jobs(limit=500)) if callable(list_jobs) else ()
    try:
        from apps.learning_worker_runtime import load_learning_worker_record, learning_worker_is_running

        worker = dict(load_learning_worker_record(state_dir) or {})
        worker.setdefault("running", learning_worker_is_running(state_dir))
    except Exception:
        worker = {"status": "unknown", "running": False}
    counts = {"queued": 0, "running": 0, "completed": 0, "failed": 0, "cancelled": 0}
    for job in jobs:
        status = str(getattr(job, "status", "") or "").strip().lower()
        if status in counts:
            counts[status] += 1
    rows = []
    for job in jobs:
        state = states_by_id.get(str(getattr(job, "state_id", "") or ""))
        episode = episodes_by_id.get(str(getattr(job, "episode_id", "") or ""))
        result_payload = getattr(job, "result_json", {})
        result_json = dict(result_payload) if isinstance(result_payload, Mapping) else {}
        rows.append(
            {
                **_serialize(job),
                "elephant_id": getattr(state, "elephant_id", "") if state is not None else "",
                "elephant_name": getattr(state, "elephant_name", "") if state is not None else "",
                "entry_surface": getattr(episode, "entry_surface", "") if episode is not None else "",
                "episode_status": getattr(episode, "status", "") if episode is not None else "",
                "result_status": str(result_json.get("status") or ""),
                "result_summary": str(result_json.get("summary") or ""),
                "learning_result": result_json,
                "result_record_count": 0,
                "result_fact_count": 0,
                "result_facts": (),
            }
        )
    latest_completed = next((row for row in rows if row.get("status") == "completed"), None)
    active_job = next((row for row in rows if row.get("status") == "running"), None)
    return {
        "worker": worker,
        "summary": {
            **counts,
            "total": len(jobs),
            "active_job_id": worker.get("active_job_id") or (active_job or {}).get("job_id"),
            "latest_completed_at": (latest_completed or {}).get("finished_at"),
        },
        "jobs": tuple(rows),
    }


def _operation_snapshot(self, *, active_provider: Mapping[str, Any], provider_doctor: Mapping[str, Any]) -> dict[str, Any]:
    database_path = self.repository.database_path
    state_dir = database_path.parent
    settings = _settings(state_dir, database_path)
    skill_overrides = _profile_overrides(state_dir, "skill_overrides")
    tool_overrides = _profile_overrides(state_dir, "tool_overrides")
    global_config = settings.get("globalConfig") if isinstance(settings.get("globalConfig"), Mapping) else {}
    provider_catalog = self.list_providers()
    provider_keys = self.list_provider_keys()
    embedding_provider = self.embedding_provider_summary()
    mcp = _mcp_catalog(config_path=Path(settings["globalConfigPath"]), config=global_config)
    return {
        "skills": tuple(_skills(self, skill_overrides=skill_overrides, global_config=global_config)),
        "tools": tuple(_tools(self, tool_overrides=tool_overrides)),
        "mcp": mcp,
        "cron": {"jobs": tuple(_cron_jobs(self))},
        "gateway": _gateway(
            state_dir,
            runtime_bridge=getattr(self, "gateway_runtime_bridge", None),
        ),
        "settings": settings,
        "usage": _canonical_usage(database_path),
        "logs": tuple(_logs(state_dir)),
        "models": {
            "activeProvider": _dashboard_active_provider(dict(active_provider)),
            "providers": tuple(provider_catalog.get("providers", ())),
            "doctor": _dashboard_provider_doctor(dict(provider_doctor), dict(active_provider)),
            "keys": tuple(provider_keys.get("keys", ())),
            "embeddingProvider": dict(embedding_provider),
        },
    }


_PERSONAL_MODEL_LENSES = (
    ("identity", "Identity", "Who the person is — durable attributes: character, values, style, and body."),
    ("world", "World", "What is around the person — environment: people, projects, tools, and places."),
    ("pulse", "Pulse", "How the person is right now — current state: chapter, focus, mood, and blockers."),
    ("journey", "Journey", "What the person has been through — accumulated experience: lessons, patterns, and decisions."),
)


_KNOWN_LENSES = frozenset(key for key, _, _ in _PERSONAL_MODEL_LENSES)


def _fact_lens_from_topic(fact: Any) -> str:
    """Derive canonical lens from topic prefix; fall back to stored lens field.

    Facts written before the lens/topic alignment was enforced may have a
    ``lens`` field that disagrees with the topic prefix.  The topic prefix is
    authoritative; fall back to the stored lens only when the topic is absent
    or its prefix is not a known lens.
    """
    metadata = getattr(fact, "metadata", {})
    if not isinstance(metadata, dict):
        try:
            metadata = dict(metadata or {})
        except Exception:
            metadata = {}
    topic = str(metadata.get("topic") or "").strip()
    if topic:
        prefix = topic.split(".")[0]
        if prefix in _KNOWN_LENSES:
            return prefix
    stored = str(getattr(fact, "lens", "") or "")
    return stored if stored in _KNOWN_LENSES else ""


def _personal_model_lens_summaries(
    *,
    model_facts: tuple[Any, ...],
) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    facts_by_lens = {key: [] for key, _, _ in _PERSONAL_MODEL_LENSES}
    for fact in model_facts:
        lens = _fact_lens_from_topic(fact)
        if lens in facts_by_lens:
            facts_by_lens[lens].append(fact)
    for key, label, description in _PERSONAL_MODEL_LENSES:
        lens_facts = tuple(facts_by_lens[key])
        latest = _latest_time(lens_facts)
        rows.append({
            "component_key": key,
            "lens": key,
            "label": label,
            "description": description,
            "claim_count": len(lens_facts),
            "active_claim_count": len(lens_facts),
            "latest_observation_at": latest,
            "status": "active" if lens_facts else "empty",
        })
    return tuple(rows)


def _step_metadata(step: Any) -> Mapping[str, str]:
    metadata = getattr(step, "metadata", None)
    return metadata if isinstance(metadata, Mapping) else {}


def _metadata_text(metadata: Mapping[str, str], key: str) -> str:
    return str(metadata.get(key) or "").strip()


def _metadata_int(metadata: Mapping[str, str], key: str) -> int:
    try:
        return max(0, int(str(metadata.get(key) or "0")))
    except (TypeError, ValueError):
        return 0


def _payload_ref_prompt(step: Any, source_payloads: Mapping[str, Mapping[str, Any]]) -> str:
    for ref in getattr(step, "payload_refs", ()) or ():
        payload = source_payloads.get(str(ref))
        if payload is None:
            continue
        prompt = str(payload.get("prompt") or payload.get("message") or payload.get("content") or "").strip()
        if prompt:
            return prompt
    return ""


def _step_event_type(step: Any) -> str:
    action = str(getattr(step, "action", "") or "")
    status = str(getattr(step, "status", "") or "")
    if action == "record_input":
        return "source_input"
    if action == "effective_user_query":
        return "user_query"
    if action == "assemble_context":
        return "context_bundle"
    if action == "compact_context":
        return "context_compaction"
    if action == "call_model" and status == "planned":
        return "system_prompt"
    if action == "call_model":
        return "llm_answer"
    if action == "call_tool" and status == "planned":
        return "tool_call"
    if action == "call_tool":
        return "tool_execute"
    if action == "write_state":
        return "state_write"
    if action in {"reflect", "run_reflection_window"}:
        return "personal_model_update"
    if action == "emit_response":
        return "final_response"
    if action == "checkpoint":
        return "checkpoint"
    return action or "step"


def _step_event_content(step: Any, source_payloads: Mapping[str, Mapping[str, Any]]) -> str:
    metadata = _step_metadata(step)
    event_type = _step_event_type(step)
    if event_type == "user_query":
        return _metadata_text(metadata, "effective_user_query") or _metadata_text(metadata, "user_query") or _payload_ref_prompt(step, source_payloads)
    if event_type == "source_input":
        return _metadata_text(metadata, "user_query") or _metadata_text(metadata, "raw_user_query") or _payload_ref_prompt(step, source_payloads)
    if event_type == "system_prompt":
        return _metadata_text(metadata, "system_prompt") or _metadata_text(metadata, "model_prompt")
    if event_type == "tool_call":
        arguments = _metadata_text(metadata, "tool_arguments")
        return f"{_metadata_text(metadata, 'tool_name')} {arguments}".strip()
    if event_type == "tool_execute":
        return _metadata_text(metadata, "tool_result") or str(getattr(step, "summary", "") or "")
    if event_type == "final_response":
        return _metadata_text(metadata, "final_response") or str(getattr(step, "summary", "") or "")
    if event_type == "llm_answer":
        return _metadata_text(metadata, "assistant_response") or str(getattr(step, "summary", "") or "")
    return str(getattr(step, "summary", "") or "")


def _dashboard_step_row(step: Any, source_payloads: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    metadata = _step_metadata(step)
    event_type = _step_event_type(step)
    return {
        **_serialize(step),
        "event_type": event_type,
        "content": _step_event_content(step, source_payloads),
        "detail": {
            "tool_name": _metadata_text(metadata, "tool_name"),
            "tool_arguments": _metadata_text(metadata, "tool_arguments"),
            "tool_result": _metadata_text(metadata, "tool_result"),
            "execution_id": _metadata_text(metadata, "execution_id"),
            "context_bundle_id": _metadata_text(metadata, "context_bundle_id"),
            "model_prompt": _metadata_text(metadata, "model_prompt"),
            "effective_user_query": _metadata_text(metadata, "effective_user_query"),
            "raw_user_query": _metadata_text(metadata, "raw_user_query") or _metadata_text(metadata, "user_query"),
            "recall_count": _metadata_text(metadata, "recall_count"),
            "recall_bytes": _metadata_text(metadata, "recall_bytes"),
            "assistant_reasoning": _metadata_text(metadata, "assistant_reasoning"),
        },
        "usage": {
            "prompt_tokens": _metadata_int(metadata, "prompt_tokens"),
            "completion_tokens": _metadata_int(metadata, "completion_tokens"),
            "total_tokens": _metadata_int(metadata, "total_tokens"),
            "cached_prompt_tokens": _metadata_int(metadata, "cached_prompt_tokens"),
            "cache_creation_prompt_tokens": _metadata_int(metadata, "cache_creation_prompt_tokens"),
        },
    }


def _runtime_traces(
    *,
    episodes: tuple[Any, ...],
    loops_by_episode: Mapping[str, tuple[Any, ...]],
    steps_by_loop: Mapping[str, tuple[Any, ...]],
    source_payloads: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    traces = []
    for episode in episodes:
        episode_loops = tuple(
            sorted(
                loops_by_episode.get(episode.episode_id, ()),
                key=lambda item: (str(getattr(item, "started_at", "") or ""), str(getattr(item, "loop_id", ""))),
            )
        )
        loop_rows = []
        timeline = []
        for loop in episode_loops:
            loop_steps = tuple(
                sorted(
                    steps_by_loop.get(loop.loop_id, ()),
                    key=lambda item: (int(getattr(item, "sequence", 0) or 0), str(getattr(item, "created_at", "") or "")),
                )
            )
            step_rows = tuple(_dashboard_step_row(step, source_payloads) for step in loop_steps)
            timeline.extend(step_rows)
            loop_rows.append({**_serialize(loop), "step_count": len(step_rows), "steps": step_rows})
        traces.append(
            {
                **_serialize(episode),
                "loop_count": len(loop_rows),
                "step_count": len(timeline),
                "loops": tuple(loop_rows),
                "timeline": tuple(timeline),
            }
        )
    return tuple(traces)


from .api_runtime_internal_sections import inspect_internal_dashboard
from .api_runtime_internal_triggers import delete_diary_entry, trigger_diary_write, trigger_reflect_job


__all__ = ["delete_diary_entry", "inspect_internal_dashboard", "trigger_diary_write", "trigger_reflect_job"]
