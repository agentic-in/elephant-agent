"""Operator tool approval settings endpoint helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from packages.runtime_config import (
    global_config_path_for_state_dir,
    load_tool_approvals_from_config,
    save_tool_approvals_to_config,
)

from .api_runtime_console_ops import _settings, _text_list


def _bool_payload(value: object, *, fallback: bool = False) -> bool:
    if value is None:
        return fallback
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "enabled"}:
            return True
        if normalized in {"0", "false", "no", "off", "disabled"}:
            return False
    return bool(value)


def patch_tool_approval_settings(self, payload: Mapping[str, Any]) -> dict[str, Any]:
    database_path = self.repository.database_path
    state_dir = database_path.parent
    config_path = global_config_path_for_state_dir(database_path.parent)
    approvals_payload = {
        "enabled": _bool_payload(payload.get("enabled"), fallback=False),
        "tool_ids": _text_list(payload.get("toolIds", payload.get("tool_ids"))),
        "families": _text_list(payload.get("families")),
        "mcp_keywords": _text_list(payload.get("mcpKeywords", payload.get("mcp_keywords"))),
        "mcp_writes_or_strict_only": _bool_payload(
            payload.get(
                "mcpWritesOrStrictOnly",
                payload.get("mcp_writes_or_strict_only", True),
            ),
            fallback=True,
        ),
    }
    save_tool_approvals_to_config(
        config_path,
        state_dir=state_dir,
        approvals_payload=approvals_payload,
    )
    next_settings = _settings(state_dir, database_path)
    next_config = next_settings.get("globalConfig") if isinstance(next_settings.get("globalConfig"), Mapping) else {}
    return {
        "status": "ok",
        "globalConfigPath": str(config_path),
        "runtimeStatus": "runtime_policy_updated",
        "approvals": load_tool_approvals_from_config(next_config),
        "settings": next_settings,
    }


__all__ = ["patch_tool_approval_settings"]
