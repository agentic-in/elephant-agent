"""Config-driven local tool approval policy helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from packages.runtime_config import normalize_tool_approval_config
from packages.tools import ToolDefinition


def tool_approval_policy_match(
    definition: ToolDefinition,
    approval_config: Mapping[str, Any] | None,
) -> tuple[bool, str]:
    config = normalize_tool_approval_config(approval_config)
    if not config["enabled"]:
        return False, "disabled"

    configured_tool_ids = {item.lower() for item in config["tool_ids"]}
    if definition.tool_id.lower() in configured_tool_ids:
        return True, "tool_id"

    configured_families = {item.lower() for item in config["families"]}
    if definition.family.lower() in configured_families:
        return True, "family"

    configured_keywords = [item.lower() for item in config["mcp_keywords"]]
    if definition.backend != "mcp" or not configured_keywords:
        return False, "no_match"

    writes_or_strict = (
        bool(definition.side_effects.writes_state)
        or definition.side_effects.approval_class.strip().lower() == "strict"
    )
    if config["mcp_writes_or_strict_only"] and not writes_or_strict:
        return False, "mcp_read_only"

    searchable = " ".join(
        str(value)
        for value in (
            definition.tool_id,
            definition.family,
            definition.backend,
            *definition.side_effects.categories,
            definition.metadata.get("serverId", ""),
            definition.metadata.get("toolName", ""),
        )
    ).lower()
    for keyword in configured_keywords:
        if keyword and keyword in searchable:
            return True, f"mcp_keyword:{keyword}"
    return False, "no_match"

