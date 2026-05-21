"""Operator management helpers shared by the API and dashboard."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from packages.runtime_config import configured_external_skill_dirs
from packages.skills import (
    SkillHub,
    default_skill_hub_sources,
    load_skill_package_definition,
    operator_skill_catalog_entries,
)

from .api_runtime_console_ops import (
    _gateway,
    _logs,
    _mcp_catalog,
    _override_enabled,
    _profile_overrides,
    _settings,
    create_operator_mcp_tool,
    delete_operator_mcp_server,
    delete_operator_mcp_tool,
    discover_operator_mcp_server,
    gateway_action,
    patch_operator_global_config,
    patch_operator_settings,
    set_console_item_enabled,
    set_operator_mcp_tool_enabled,
    sync_operator_mcp_server,
    update_operator_mcp_tool,
)
from .api_runtime_http_dispatch_helpers import _cron_job_record


def _skills(
    app: Any,
    *,
    skill_overrides: Mapping[str, Any],
    global_config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_skill_ids: set[str] = set()
    for entry in operator_skill_catalog_entries(install_root=app.config.install_root):
        enabled = _override_enabled(skill_overrides, entry.skill_id, bool(entry.default_enabled))
        rows.append(
            {
                "skillId": entry.skill_id,
                "displayName": entry.display_name,
                "source": entry.source_label,
                "sourceId": entry.source_id,
                "summary": entry.summary,
                "version": entry.version,
                "enabled": enabled,
                "defaultEnabled": bool(entry.default_enabled),
                "override": skill_overrides.get(entry.skill_id),
                "reference": entry.reference,
                "instructionText": entry.instruction_text,
                "storageTier": entry.storage_tier,
                "toggleable": True,
                "promptIndexVisible": bool(enabled) and bool(entry.visibility.include_in_prompt_index),
                "metadata": dict(entry.metadata),
            }
        )
        seen_skill_ids.add(entry.skill_id)

    hub = SkillHub(
        sources=default_skill_hub_sources(
            external_dirs=configured_external_skill_dirs(global_config),
            install_root=app.config.install_root,
        )
    )
    for entry in hub.list():
        if entry.source_id in {"builtin", "elephant-installed", "elephant-authored"}:
            continue
        if entry.skill_id in seen_skill_ids:
            continue
        instruction_text = ""
        version = str(entry.metadata.get("version") or "")
        try:
            definition = load_skill_package_definition(Path(entry.entry_path))
        except Exception:
            definition = None
        if definition is not None:
            instruction_text = definition.instruction_text
            version = definition.version
        rows.append(
            {
                "skillId": entry.skill_id,
                "displayName": entry.display_name,
                "source": entry.source_label,
                "sourceId": entry.source_id,
                "summary": entry.summary,
                "version": version,
                "enabled": False,
                "defaultEnabled": False,
                "override": None,
                "reference": entry.reference,
                "instructionText": instruction_text,
                "storageTier": str(entry.metadata.get("storage_tier") or "external"),
                "toggleable": False,
                "promptIndexVisible": False,
                "metadata": dict(entry.metadata),
            }
        )
        seen_skill_ids.add(entry.skill_id)
    return rows


def _tools(app: Any, *, tool_overrides: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for tool in app.tool_runtime.list_tools(audience="operator"):
        enabled = _override_enabled(tool_overrides, tool.tool_id, bool(tool.enabled))
        rows.append(
            {
                "toolId": tool.tool_id,
                "displayName": tool.display_name,
                "description": tool.description,
                "family": tool.family,
                "enabled": enabled,
                "defaultEnabled": bool(tool.enabled),
                "override": tool_overrides.get(tool.tool_id),
                "available": tool.available,
                "availabilityReason": tool.availability.reason,
                "riskClass": tool.side_effects.risk_class,
                "approvalClass": tool.side_effects.approval_class,
                "readsState": tool.side_effects.reads_state,
                "writesState": tool.side_effects.writes_state,
                "touchesNetwork": tool.side_effects.touches_network,
                "touchesSecrets": tool.side_effects.touches_secrets,
                "requiredFields": tool.required_fields,
                "schema": dict(tool.schema),
                "provenance": tool.provenance,
                "backend": tool.backend,
                "metadata": dict(tool.metadata),
            }
        )
    return rows

def _cron_jobs(app: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for job in app.cron_runtime.list_jobs():
        rows.append(_cron_job_record(job))
    system_kinds = {str(row.get("systemKind") or "") for row in rows}
    system_jobs: list[dict[str, Any]] = []
    if "dream" not in system_kinds:
        dream_job = _dream_system_job(app)
        if dream_job is not None:
            system_jobs.append(dream_job)
    if "proactive-ask" not in system_kinds:
        proactive_job = _proactive_ask_system_job(app)
        if proactive_job is not None:
            system_jobs.append(proactive_job)
    rows = [*system_jobs, *rows]
    return rows


def _dream_system_job(app: Any) -> dict[str, Any] | None:
    """Build a synthetic job row exposing the built-in Dream learning pass."""
    try:
        list_jobs = getattr(app.repository, "list_learning_jobs", None)
        learning_jobs = tuple(list_jobs(limit=500)) if callable(list_jobs) else ()
        dream_jobs = tuple(
            job
            for job in learning_jobs
            if str(getattr(job, "trigger", "") or "").strip().lower() == "dream"
            or "dream" in str(getattr(job, "metadata", {}).get("features", "")).lower()
        )
        latest = dream_jobs[0] if dream_jobs else None
        last_run = None
        last_summary = "nightly long-horizon memory consolidation"
        if latest is not None:
            finished_at = getattr(latest, "finished_at", None)
            started_at = getattr(latest, "started_at", None)
            created_at = getattr(latest, "created_at", None)
            last_run = finished_at or started_at or created_at
            last_summary = (
                str(getattr(latest, "progress_detail", "") or "").strip()
                or str(getattr(latest, "summary", "") or "").strip()
                or last_summary
            )
        return {
            "jobId": "system:dream",
            "name": "Dream",
            "schedule": "nightly (built-in)",
            "scheduleKind": "system",
            "jobKind": "system",
            "status": "scheduled",
            "profileId": None,
            "eggId": None,
            "payload": {"type": "learning", "trigger": "dream", "features": "dream"},
            "skills": [],
            "createdAt": None,
            "updatedAt": None,
            "nextRunAt": None,
            "lastRunAt": last_run.isoformat() if last_run is not None else None,
            "runCount": len(dream_jobs),
            "lastSummary": last_summary,
            "isSystem": True,
            "systemKind": "dream",
            "canRunNow": True,
            "canPause": False,
            "canDelete": False,
        }
    except Exception:
        return None


def _proactive_ask_system_job(app: Any) -> dict[str, Any] | None:
    """Build a synthetic job row exposing the built-in proactive ask scheduler."""
    try:
        from packages.runtime_config import (
            global_config_path_for_state_dir,
            load_global_config,
            personal_model_question_config_from_global,
        )

        state_dir = app.repository.database_path.parent
        config = load_global_config(global_config_path_for_state_dir(state_dir), state_dir=state_dir)
        question_config = personal_model_question_config_from_global(config)
        proactive = question_config.get("proactive_ask") if isinstance(question_config, Mapping) else None
        if not isinstance(proactive, dict):
            proactive = {}
        enabled = proactive.get("enabled") is not False
        idle = int(proactive.get("idle_threshold_minutes") or 180)
        daily_max = int(proactive.get("daily_max") or 8)
        qh = proactive.get("quiet_hours")
        if isinstance(qh, (list, tuple)) and len(qh) == 2:
            qs, qe = int(qh[0]) % 24, int(qh[1]) % 24
        else:
            qs, qe = 23, 7
        return {
            "jobId": "system:proactive-ask",
            "name": "Proactive Questions",
            "schedule": "every 60s (built-in)",
            "scheduleKind": "interval",
            "jobKind": "system",
            "status": "scheduled" if enabled else "paused",
            "profileId": None,
            "eggId": None,
            "payload": {"type": "proactive_ask", "enabled": enabled, "idle_threshold_minutes": idle, "daily_max": daily_max, "quiet_hours": [qs, qe]},
            "skills": [],
            "createdAt": None,
            "updatedAt": None,
            "nextRunAt": None,
            "lastRunAt": None,
            "runCount": 0,
            "lastSummary": f"idle={idle}m, max={daily_max}/day, quiet={qs}:00–{qe}:00",
            "isSystem": True,
            "systemKind": "proactive-ask",
            "canRunNow": True,
            "canPause": True,
            "canDelete": False,
        }
    except Exception:
        return None


__all__ = [
    "_cron_jobs",
    "_dream_system_job",
    "_gateway",
    "_logs",
    "_mcp_catalog",
    "_profile_overrides",
    "_settings",
    "_skills",
    "_tools",
    "patch_operator_settings",
    "patch_operator_global_config",
    "create_operator_mcp_tool",
    "update_operator_mcp_tool",
    "delete_operator_mcp_tool",
    "sync_operator_mcp_server",
    "delete_operator_mcp_server",
    "set_operator_mcp_tool_enabled",
    "discover_operator_mcp_server",
    "set_console_item_enabled",
    "gateway_action",
]
