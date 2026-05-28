"""Local agent Herd helpers for API dispatch."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from packages.operator.local_agents import LocalAgentRuntimeRecord, scan_local_agents


def metadata_str_payload(payload: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        if key not in payload:
            continue
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            text = ", ".join(str(item).strip() for item in value if str(item).strip())
        else:
            text = str(value).strip()
        return text
    return None


def metadata_bool_payload(payload: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        if key not in payload:
            continue
        value = payload.get(key)
        if isinstance(value, bool):
            return "true" if value else "false"
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "on", "enabled"}:
            return "true"
        if text in {"0", "false", "no", "off", "disabled"}:
            return "false"
    return None


def herd_metadata_from_payload(payload: Mapping[str, Any], *, current: Mapping[str, str] | None = None) -> dict[str, str]:
    metadata = dict(current or {})
    text_fields = {
        "herd_kind": ("herd_kind", "herdKind", "role_kind", "roleKind"),
        "parent_elephant_id": ("parent_elephant_id", "parentElephantId", "parent_id", "parentId"),
        "role_title": ("role_title", "roleTitle"),
        "role_prompt": ("role_prompt", "rolePrompt"),
        "runtime_id": ("runtime_id", "runtimeId"),
        "provider_id": ("provider_id", "providerId"),
        "provider_model": ("provider_model", "providerModel", "runtime_model", "runtimeModel", "model_id", "modelId"),
        "engine_id": ("engine_id", "engineId", "engine", "runtime_engine", "runtimeEngine"),
        "tool_ids": ("tool_ids", "toolIds", "allowed_tools", "allowedTools", "allowed_tool_ids", "allowedToolIds"),
        "skill_ids": ("skill_ids", "skillIds", "skills"),
        "instruction": ("instruction", "instructions", "system_prompt", "systemPrompt"),
        "backend": ("backend", "execution_backend", "executionBackend"),
        "max_concurrency": ("max_concurrency", "maxConcurrency"),
    }
    for target, keys in text_fields.items():
        value = metadata_str_payload(payload, *keys)
        if value is not None:
            metadata[target] = value
    enabled = metadata_bool_payload(payload, "enabled", "isEnabled")
    if enabled is not None:
        metadata["enabled"] = enabled
    return metadata


def local_agent_payload(record: LocalAgentRuntimeRecord) -> dict[str, Any]:
    return dict(record.as_payload())


def scan_and_persist_local_agents(app: Any) -> tuple[LocalAgentRuntimeRecord, ...]:
    records = scan_local_agents()
    upsert = getattr(app.repository, "upsert_local_agent_runtimes", None)
    if callable(upsert):
        upsert(records)
    return records


def list_persisted_local_agents(app: Any) -> tuple[LocalAgentRuntimeRecord, ...]:
    list_records = getattr(app.repository, "list_local_agent_runtimes", None)
    if callable(list_records):
        return tuple(list_records())
    return ()


def baby_identity_text(*, display_name: str, role_title: str, role_prompt: str, provider_name: str) -> str:
    resolved_role = role_title or "local agent"
    detail = role_prompt or f"Use this baby elephant for {provider_name} local-agent work."
    return "\n".join(
        (
            f"# {display_name}",
            "",
            "## Role",
            "",
            f"{resolved_role}.",
            "",
            "## Operating Notes",
            "",
            detail,
        )
    )


def default_baby_display_name(record: LocalAgentRuntimeRecord, role_title: str = "") -> str:
    role = role_title.strip() or record.role_title or record.display_name
    return f"{record.display_name} {role}".strip()


def latest_episode_touch(episodes: tuple[Any, ...]) -> str:
    if not episodes:
        return ""
    latest = max(
        episodes,
        key=lambda episode: (
            getattr(episode, "updated_at", None)
            or getattr(episode, "started_at", None)
            or getattr(episode, "ended_at", None)
        ),
    )
    value = getattr(latest, "updated_at", None) or getattr(latest, "started_at", None) or getattr(latest, "ended_at", None)
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return isoformat(timespec="seconds")
        except TypeError:
            return isoformat()
    return str(value or "")
