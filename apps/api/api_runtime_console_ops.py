"""Console config, gateway, and custom MCP operations."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any
import json
import logging
import subprocess
import sys

from packages.tools import sync_custom_mcp_tools
from packages.tools.mcp import discover_mcp_tools_sync
from packages.runtime_config import (
    global_config_path_for_state_dir,
    global_config_schema,
    load_global_config,
    parse_global_config_text,
    read_global_config_text,
    write_global_config,
)

from .api_runtime_console_config import (
    _load_manifest_from_config,
    _logs,
    _write_manifest_to_config,
)
from .api_runtime_gateway_ops import (
    _GATEWAY_SERVICE_BY_KEY,
    _gateway,
    _gateway_configure_service,
    _gateway_remove_service_account,
    _gateway_runtime_is_running,
    _gateway_runtime_is_starting,
    _gateway_runtime_status,
    _gateway_view,
    _pid_is_alive,
)
from .api_runtime_gateway_weixin import (
    _gateway_weixin_qr_poll,
    _gateway_weixin_qr_start,
)

LOGGER = logging.getLogger(__name__)


def gateway_action(self, payload: Mapping[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action") or "status").strip().lower()
    service = str(payload.get("service") or "feishu").strip().lower()
    if service not in _GATEWAY_SERVICE_BY_KEY:
        raise ValueError(
            "gateway service must be one of " + ", ".join(_GATEWAY_SERVICE_BY_KEY)
        )
    if action == "qr-start":
        if service != "weixin":
            raise ValueError("gateway QR setup is only supported for weixin")
        return _gateway_weixin_qr_start(self, payload)
    if action == "qr-poll":
        if service != "weixin":
            raise ValueError("gateway QR polling is only supported for weixin")
        return _gateway_weixin_qr_poll(self, payload)
    if action == "configure":
        return _gateway_configure_service(self, payload, service=service)
    if action == "remove":
        return _gateway_remove_service_account(self, payload, service=service)
    if action not in {"status", "doctor", "start", "stop", "restart"}:
        raise ValueError(
            "gateway action must be status, doctor, start, stop, restart, configure, remove, qr-start, or qr-poll"
        )
    database_path = self.repository.database_path
    state_dir = database_path.parent
    command = [sys.executable, "-m", "apps.gateway", service, action]
    account_id = str(
        payload.get("accountId") or payload.get("account_id") or ""
    ).strip()
    if account_id:
        command.append(account_id)
    transport = str(
        payload.get("transport") or payload.get("runtimeTarget") or ""
    ).strip()
    if transport:
        command.extend(["--transport", transport])
    command.extend(
        [
            "--state-dir",
            str(state_dir),
            "--cli-state-dir",
            str(state_dir),
        ]
    )
    if action == "start":
        command.append("--detach")
    if action in {"stop", "restart"} and bool(payload.get("force")):
        command.append("--force")
    result = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    return {
        "status": "ok" if result.returncode == 0 else "failed",
        "service": service,
        "action": action,
        "returnCode": result.returncode,
        "stdout": result.stdout[-8_000:],
        "stderr": result.stderr[-8_000:],
        "gateway": _gateway_view(self, state_dir),
    }


def _settings(state_dir: Path, database_path: Path) -> dict[str, Any]:
    manifest = _load_manifest_from_config(state_dir)
    config_path = global_config_path_for_state_dir(database_path.parent)
    global_config = load_global_config(config_path, state_dir=state_dir)
    return {
        "eggDir": str(state_dir),
        "profileManifest": manifest if isinstance(manifest, Mapping) else {},
        "globalConfigPath": str(config_path),
        "globalConfigExists": config_path.exists(),
        "globalConfig": global_config,
        "globalConfigYaml": read_global_config_text(
            config_path, fallback=global_config
        ),
        "globalConfigSchema": global_config_schema(),
    }


def _profile_overrides(state_dir: Path, key: str) -> Mapping[str, Any]:
    manifest = _load_manifest_from_config(state_dir)
    if not isinstance(manifest, Mapping):
        return {}
    value = manifest.get(key)
    return value if isinstance(value, Mapping) else {}


def _override_enabled(
    overrides: Mapping[str, Any], item_id: str, default: bool
) -> bool:
    value = overrides.get(item_id)
    if isinstance(value, Mapping) and isinstance(value.get("enabled"), bool):
        return bool(value["enabled"])
    return default


def _skill_catalog_review_status(self, item_id: str) -> str:
    try:
        from packages.skills import operator_skill_catalog_entries

        for entry in operator_skill_catalog_entries(install_root=self.config.install_root):
            if entry.skill_id == item_id:
                return str(entry.metadata.get("review_status") or "").strip().lower()
    except Exception:
        LOGGER.warning(
            "failed to inspect skill review status before writing console override",
            extra={"skill_id": item_id},
            exc_info=True,
        )
    return ""


def _mapping_rows(value: object) -> dict[str, dict[str, Any]]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): dict(item)
        for key, item in value.items()
        if str(key).strip() and isinstance(item, Mapping)
    }


def _text_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            parsed = json.loads(stripped)
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
        return [item.strip() for item in stripped.split(",") if item.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _object_payload(value: object, *, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return {}
        try:
            value = json.loads(stripped)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError(f"{field} must be a JSON object") from error
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return {str(key): item for key, item in value.items() if str(key).strip()}


def _string_object_payload(value: object, *, field: str) -> dict[str, str]:
    return {
        str(key): str(item)
        for key, item in _object_payload(value, field=field).items()
        if str(key).strip()
    }


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _required_text(value: object, *, field: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValueError(f"{field} is required")
    return text


def _mcp_tool_key(server_id: str, tool_name: str) -> str:
    return f"{server_id}:{tool_name}"


def _mcp_servers(config: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return _mapping_rows(config.get("mcp_servers"))


def _mcp_overrides(config: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return _mapping_rows(config.get("mcp_overrides"))


def _mcp_catalog(*, config_path: Path, config: Mapping[str, Any]) -> dict[str, Any]:
    server_rows: list[dict[str, Any]] = []
    tool_rows: list[dict[str, Any]] = []
    overrides = _mcp_overrides(config)
    for server_id, server in sorted(_mcp_servers(config).items()):
        tools = _mapping_rows(server.get("tools"))
        label = str(server.get("label") or server_id).strip() or server_id
        command = str(server.get("command") or "").strip()
        url = str(server.get("url") or "").strip()
        transport = (
            str(server.get("transport") or ("http" if url else "stdio")).strip()
            or "stdio"
        )
        env = (
            _mapping_rows({"env": server.get("env")}).get("env", {})
            if isinstance(server.get("env"), Mapping)
            else {}
        )
        headers = (
            _mapping_rows({"headers": server.get("headers")}).get("headers", {})
            if isinstance(server.get("headers"), Mapping)
            else {}
        )
        env_keys = sorted(str(key) for key in env if str(key).strip())
        header_keys = sorted(str(key) for key in headers if str(key).strip())
        server_rows.append(
            {
                "serverId": server_id,
                "label": label,
                "transport": transport,
                "command": command,
                "args": _text_list(server.get("args")),
                "url": url,
                "env": {key: str(value) for key, value in env.items()},
                "envKeys": env_keys,
                "headers": {key: str(value) for key, value in headers.items()},
                "headerKeys": header_keys,
                "toolCount": len(tools),
                "provenance": f"{config_path}#mcp_servers.{server_id}",
            }
        )
        available = bool(command or url)
        availability_reason = (
            "" if available else "server command or url is not configured"
        )
        for tool_name, tool in sorted(tools.items()):
            tool_key = _mcp_tool_key(server_id, tool_name)
            default_enabled = bool(tool.get("enabled", True))
            enabled = _override_enabled(overrides, tool_key, default_enabled)
            schema = (
                dict(tool.get("schema", {}))
                if isinstance(tool.get("schema"), Mapping)
                else {}
            )
            metadata = (
                dict(tool.get("metadata", {}))
                if isinstance(tool.get("metadata"), Mapping)
                else {}
            )
            tool_rows.append(
                {
                    "toolId": f"mcp.{server_id}.{tool_name}",
                    "toolKey": tool_key,
                    "toolName": tool_name,
                    "source": "custom-mcp",
                    "sourceKind": "mcp",
                    "serverId": server_id,
                    "serverLabel": label,
                    "transport": transport,
                    "command": command,
                    "args": _text_list(server.get("args")),
                    "url": url,
                    "env": {key: str(value) for key, value in env.items()},
                    "envKeys": env_keys,
                    "headers": {key: str(value) for key, value in headers.items()},
                    "headerKeys": header_keys,
                    "displayName": str(tool.get("display_name") or tool_name).strip()
                    or tool_name,
                    "description": str(tool.get("description") or "").strip(),
                    "family": str(tool.get("family") or "mcp").strip() or "mcp",
                    "enabled": enabled,
                    "defaultEnabled": default_enabled,
                    "override": overrides.get(tool_key),
                    "available": available,
                    "availabilityReason": availability_reason,
                    "riskClass": str(tool.get("risk_class") or "medium").strip()
                    or "medium",
                    "approvalClass": str(
                        tool.get("approval_class") or "standard"
                    ).strip()
                    or "standard",
                    "readsState": bool(tool.get("reads_state", False)),
                    "writesState": bool(tool.get("writes_state", False)),
                    "touchesNetwork": bool(tool.get("touches_network", False)),
                    "touchesSecrets": bool(tool.get("touches_secrets", False)),
                    "requiredFields": (
                        tuple(
                            str(item)
                            for item in schema.get("required", [])
                            if str(item).strip()
                        )
                        if isinstance(schema.get("required"), list)
                        else ()
                    ),
                    "schema": schema,
                    "provenance": f"{config_path}#mcp_servers.{server_id}.tools.{tool_name}",
                    "backend": "mcp",
                    "metadata": metadata,
                }
            )
    return {
        "configPath": str(config_path),
        "servers": server_rows,
        "tools": tool_rows,
    }


def _load_operator_global_config(
    database_path: Path,
) -> tuple[Path, Path, dict[str, Any]]:
    state_dir = database_path.parent
    config_path = global_config_path_for_state_dir(database_path.parent)
    config = load_global_config(config_path, state_dir=state_dir)
    return state_dir, config_path, dict(config)


def _sync_operator_mcp_runtime(
    app: Any, *, config_path: Path, config: Mapping[str, Any]
) -> str:
    runtime = getattr(app, "tool_runtime", None)
    if runtime is None:
        return "tool_runtime_unavailable"
    sync_custom_mcp_tools(
        runtime, config_path=config_path, config=config, cwd=Path.cwd()
    )
    return "runtime_reloaded"


def _pruned_mcp_server(server: Mapping[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key in ("label", "transport", "command", "url"):
        text = _optional_text(server.get(key))
        if text is not None:
            cleaned[key] = text
    args = _text_list(server.get("args"))
    if args:
        cleaned["args"] = args
    env = {
        str(key): str(value)
        for key, value in _mapping_rows({"env": server.get("env")})
        .get("env", {})
        .items()
    }
    if env:
        cleaned["env"] = env
    headers = {
        str(key): str(value)
        for key, value in _mapping_rows({"headers": server.get("headers")})
        .get("headers", {})
        .items()
    }
    if headers:
        cleaned["headers"] = headers
    tools = _mapping_rows(server.get("tools"))
    if tools:
        cleaned["tools"] = tools
    return cleaned


def _apply_mcp_server_payload(
    server: Mapping[str, Any], payload: Mapping[str, Any]
) -> dict[str, Any]:
    next_server = dict(server)
    for config_key, payload_key in (
        ("label", "serverLabel"),
        ("transport", "transport"),
        ("command", "command"),
        ("url", "url"),
    ):
        if payload_key not in payload:
            continue
        text = _optional_text(payload.get(payload_key))
        if text is None:
            next_server.pop(config_key, None)
        else:
            next_server[config_key] = text
    if "args" in payload:
        args = _text_list(payload.get("args"))
        if args:
            next_server["args"] = args
        else:
            next_server.pop("args", None)
    if "env" in payload:
        env = _string_object_payload(payload.get("env"), field="env")
        if env:
            next_server["env"] = env
        else:
            next_server.pop("env", None)
    if "headers" in payload:
        headers = _string_object_payload(payload.get("headers"), field="headers")
        if headers:
            next_server["headers"] = headers
        else:
            next_server.pop("headers", None)
    return next_server


def _apply_mcp_tool_payload(
    tool: Mapping[str, Any], payload: Mapping[str, Any]
) -> dict[str, Any]:
    next_tool = dict(tool)
    for config_key, payload_key in (
        ("display_name", "displayName"),
        ("description", "description"),
        ("family", "family"),
        ("risk_class", "riskClass"),
        ("approval_class", "approvalClass"),
    ):
        if payload_key not in payload:
            continue
        text = _optional_text(payload.get(payload_key))
        if text is None:
            next_tool.pop(config_key, None)
        else:
            next_tool[config_key] = text
    for config_key, payload_key in (
        ("reads_state", "readsState"),
        ("writes_state", "writesState"),
        ("touches_network", "touchesNetwork"),
        ("touches_secrets", "touchesSecrets"),
    ):
        if payload_key in payload:
            next_tool[config_key] = bool(payload.get(payload_key))
    if "defaultEnabled" in payload:
        next_tool["enabled"] = bool(payload.get("defaultEnabled"))
    elif "enabled" in payload and "displayName" in payload:
        next_tool["enabled"] = bool(payload.get("enabled"))
    if "schema" in payload:
        schema = _object_payload(payload.get("schema"), field="schema")
        if schema:
            next_tool["schema"] = schema
        else:
            next_tool.pop("schema", None)
    if "metadata" in payload:
        metadata = _object_payload(payload.get("metadata"), field="metadata")
        if metadata:
            next_tool["metadata"] = metadata
        else:
            next_tool.pop("metadata", None)
    if "enabled" not in next_tool:
        next_tool["enabled"] = True
    return next_tool


def create_operator_mcp_tool(self, payload: Mapping[str, Any]) -> dict[str, Any]:
    database_path = self.repository.database_path
    state_dir, config_path, config = _load_operator_global_config(database_path)
    server_id = _required_text(payload.get("serverId"), field="serverId")
    tool_name = _optional_text(payload.get("toolName")) or _default_mcp_tool_name()
    servers = _mcp_servers(config)
    server = dict(servers.get(server_id, {}))
    tools = _mapping_rows(server.get("tools"))
    if tool_name in tools:
        raise ValueError(f"MCP tool already exists: {server_id}:{tool_name}")
    server = _apply_mcp_server_payload(server, payload)
    tools[tool_name] = _apply_mcp_tool_payload({}, payload)
    server["tools"] = tools
    servers[server_id] = _pruned_mcp_server(server)
    next_config = dict(config)
    next_config["mcp_servers"] = servers
    write_global_config(config_path, next_config)
    runtime_status = _sync_operator_mcp_runtime(
        self, config_path=config_path, config=next_config
    )
    return {
        "status": "ok",
        "action": "created",
        "toolKey": _mcp_tool_key(server_id, tool_name),
        "globalConfigPath": str(config_path),
        "runtimeStatus": runtime_status,
        "settings": _settings(state_dir, database_path),
        "mcp": _mcp_catalog(config_path=config_path, config=next_config),
    }


def update_operator_mcp_tool(self, payload: Mapping[str, Any]) -> dict[str, Any]:
    database_path = self.repository.database_path
    state_dir, config_path, config = _load_operator_global_config(database_path)
    server_id = _required_text(payload.get("serverId"), field="serverId")
    tool_name = _required_text(payload.get("toolName"), field="toolName")
    servers = _mcp_servers(config)
    server = servers.get(server_id)
    if server is None:
        raise KeyError(server_id)
    next_server = _apply_mcp_server_payload(server, payload)
    tools = _mapping_rows(next_server.get("tools"))
    existing_tool = tools.get(tool_name)
    if existing_tool is None:
        raise KeyError(_mcp_tool_key(server_id, tool_name))
    tools[tool_name] = _apply_mcp_tool_payload(existing_tool, payload)
    next_server["tools"] = tools
    servers[server_id] = _pruned_mcp_server(next_server)
    next_config = dict(config)
    next_config["mcp_servers"] = servers
    write_global_config(config_path, next_config)
    runtime_status = _sync_operator_mcp_runtime(
        self, config_path=config_path, config=next_config
    )
    return {
        "status": "ok",
        "action": "updated",
        "toolKey": _mcp_tool_key(server_id, tool_name),
        "globalConfigPath": str(config_path),
        "runtimeStatus": runtime_status,
        "settings": _settings(state_dir, database_path),
        "mcp": _mcp_catalog(config_path=config_path, config=next_config),
    }


def delete_operator_mcp_tool(self, payload: Mapping[str, Any]) -> dict[str, Any]:
    database_path = self.repository.database_path
    state_dir, config_path, config = _load_operator_global_config(database_path)
    server_id = _required_text(payload.get("serverId"), field="serverId")
    tool_name = _required_text(payload.get("toolName"), field="toolName")
    tool_key = _mcp_tool_key(server_id, tool_name)
    servers = _mcp_servers(config)
    server = servers.get(server_id)
    if server is None:
        raise KeyError(server_id)
    next_server = dict(server)
    tools = _mapping_rows(next_server.get("tools"))
    overrides = _mcp_overrides(config)
    if tool_name not in tools:
        if tools:
            raise KeyError(tool_key)
        servers.pop(server_id, None)
        for override_key in tuple(overrides):
            if override_key == tool_key or override_key.startswith(f"{server_id}:"):
                overrides.pop(override_key, None)
    else:
        tools.pop(tool_name, None)
        overrides.pop(tool_key, None)
        if tools:
            next_server["tools"] = tools
            servers[server_id] = _pruned_mcp_server(next_server)
        else:
            servers.pop(server_id, None)
            for override_key in tuple(overrides):
                if override_key.startswith(f"{server_id}:"):
                    overrides.pop(override_key, None)
    next_config = dict(config)
    next_config["mcp_servers"] = servers
    next_config["mcp_overrides"] = overrides
    write_global_config(config_path, next_config)
    runtime_status = _sync_operator_mcp_runtime(
        self, config_path=config_path, config=next_config
    )
    return {
        "status": "ok",
        "action": "deleted",
        "toolKey": tool_key,
        "globalConfigPath": str(config_path),
        "runtimeStatus": runtime_status,
        "settings": _settings(state_dir, database_path),
        "mcp": _mcp_catalog(config_path=config_path, config=next_config),
    }


def sync_operator_mcp_server(self, payload: Mapping[str, Any]) -> dict[str, Any]:
    database_path = self.repository.database_path
    state_dir, config_path, config = _load_operator_global_config(database_path)
    server_id = _required_text(payload.get("serverId"), field="serverId")
    discovered_tools = _mcp_discovered_tool_rows({"tools": payload.get("tools", ())})
    if not discovered_tools:
        raise ValueError(
            "Verify connection first so Elephant Agent can sync at least one MCP tool."
        )
    servers = _mcp_servers(config)
    server_exists = server_id in servers
    existing_server = dict(servers.get(server_id, {}))
    next_server = _apply_mcp_server_payload(existing_server, payload)
    transport = (
        str(
            next_server.get("transport")
            or ("http" if str(next_server.get("url") or "").strip() else "stdio")
        )
        .strip()
        .lower()
        or "stdio"
    )
    headers = (
        _mapping_rows({"headers": next_server.get("headers")}).get("headers", {})
        if isinstance(next_server.get("headers"), Mapping)
        else {}
    )
    existing_tools = _mapping_rows(existing_server.get("tools"))
    merged_tools = _merge_discovered_mcp_tools(
        existing_tools, discovered_tools, transport=transport, headers=headers
    )
    next_server["tools"] = merged_tools
    servers[server_id] = _pruned_mcp_server(next_server)
    overrides = _mcp_overrides(config)
    discovered_names = set(merged_tools)
    for override_key in tuple(overrides):
        if not override_key.startswith(f"{server_id}:"):
            continue
        _, tool_name = override_key.split(":", 1)
        if tool_name not in discovered_names:
            overrides.pop(override_key, None)
    next_config = dict(config)
    next_config["mcp_servers"] = servers
    next_config["mcp_overrides"] = overrides
    write_global_config(config_path, next_config)
    runtime_status = _sync_operator_mcp_runtime(
        self, config_path=config_path, config=next_config
    )
    return {
        "status": "ok",
        "action": "updated" if server_exists else "created",
        "serverId": server_id,
        "toolCount": len(merged_tools),
        "runtimeStatus": runtime_status,
        "globalConfigPath": str(config_path),
        "settings": _settings(state_dir, database_path),
        "mcp": _mcp_catalog(config_path=config_path, config=next_config),
    }


def delete_operator_mcp_server(self, payload: Mapping[str, Any]) -> dict[str, Any]:
    database_path = self.repository.database_path
    state_dir, config_path, config = _load_operator_global_config(database_path)
    server_id = _required_text(payload.get("serverId"), field="serverId")
    servers = _mcp_servers(config)
    if server_id not in servers:
        raise KeyError(server_id)
    servers.pop(server_id, None)
    overrides = _mcp_overrides(config)
    for override_key in tuple(overrides):
        if override_key.startswith(f"{server_id}:"):
            overrides.pop(override_key, None)
    next_config = dict(config)
    next_config["mcp_servers"] = servers
    next_config["mcp_overrides"] = overrides
    write_global_config(config_path, next_config)
    runtime_status = _sync_operator_mcp_runtime(
        self, config_path=config_path, config=next_config
    )
    return {
        "status": "ok",
        "action": "deleted",
        "serverId": server_id,
        "runtimeStatus": runtime_status,
        "globalConfigPath": str(config_path),
        "settings": _settings(state_dir, database_path),
        "mcp": _mcp_catalog(config_path=config_path, config=next_config),
    }


def set_operator_mcp_tool_enabled(self, payload: Mapping[str, Any]) -> dict[str, Any]:
    database_path = self.repository.database_path
    state_dir, config_path, config = _load_operator_global_config(database_path)
    server_id = _required_text(payload.get("serverId"), field="serverId")
    tool_name = _required_text(payload.get("toolName"), field="toolName")
    enabled = bool(payload.get("enabled"))
    servers = _mcp_servers(config)
    server = servers.get(server_id)
    if server is None or tool_name not in _mapping_rows(server.get("tools")):
        raise KeyError(_mcp_tool_key(server_id, tool_name))
    overrides = _mcp_overrides(config)
    tool_key = _mcp_tool_key(server_id, tool_name)
    overrides[tool_key] = {"enabled": enabled}
    next_config = dict(config)
    next_config["mcp_overrides"] = overrides
    write_global_config(config_path, next_config)
    runtime_status = _sync_operator_mcp_runtime(
        self, config_path=config_path, config=next_config
    )
    return {
        "status": "ok",
        "kind": "mcp_tool",
        "itemId": tool_key,
        "enabled": enabled,
        "runtimeStatus": runtime_status,
        "globalConfigPath": str(config_path),
        "settings": _settings(state_dir, database_path),
        "mcp": _mcp_catalog(config_path=config_path, config=next_config),
    }


def _mcp_discover_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    server_id = _required_text(payload.get("serverId"), field="serverId")
    transport = _optional_text(payload.get("transport")) or "stdio"
    transport = transport.lower()
    if transport not in {"stdio", "http", "streamable-http", "sse"}:
        raise ValueError("transport must be stdio, http, streamable-http, or sse")
    command = _optional_text(payload.get("command"))
    url = _optional_text(payload.get("url"))
    if transport == "stdio" and command is None:
        raise ValueError("command is required for stdio transport")
    if transport != "stdio" and url is None:
        raise ValueError("url is required for remote MCP transport")
    return {
        "serverId": server_id,
        "serverLabel": _optional_text(payload.get("serverLabel")) or server_id,
        "transport": transport,
        "command": command,
        "args": _text_list(payload.get("args")),
        "url": url,
        "env": _string_object_payload(payload.get("env") or {}, field="env"),
        "headers": _string_object_payload(
            payload.get("headers") or {}, field="headers"
        ),
    }


def _mcp_discovered_tool_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in payload.get("tools", ()):
        if not isinstance(item, Mapping):
            continue
        schema = (
            dict(item.get("inputSchema", {}))
            if isinstance(item.get("inputSchema"), Mapping)
            else {}
        )
        rows.append(
            {
                "name": str(item.get("name") or "").strip(),
                "description": str(item.get("description") or "").strip(),
                "inputSchema": schema,
                "enabled": bool(item.get("enabled", True)),
                "requiredFields": (
                    tuple(
                        str(field)
                        for field in schema.get("required", [])
                        if str(field).strip()
                    )
                    if isinstance(schema.get("required"), list)
                    else ()
                ),
                "options": (
                    [
                        option
                        for option in item.get("options", [])
                        if isinstance(option, Mapping)
                    ]
                    if isinstance(item.get("options"), list)
                    else []
                ),
            }
        )
    return rows


def _merge_discovered_mcp_tools(
    existing_tools: Mapping[str, dict[str, Any]],
    discovered_tools: list[dict[str, Any]],
    *,
    transport: str,
    headers: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    synced_tools: dict[str, dict[str, Any]] = {}
    for discovered in discovered_tools:
        tool_name = _required_text(discovered.get("name"), field="tools[].name")
        next_tool = dict(existing_tools.get(tool_name, {}))
        description = _optional_text(discovered.get("description"))
        schema = (
            dict(discovered.get("inputSchema", {}))
            if isinstance(discovered.get("inputSchema"), Mapping)
            else {}
        )
        if not _optional_text(next_tool.get("display_name")):
            next_tool["display_name"] = tool_name
        if description is not None or "description" not in next_tool:
            next_tool["description"] = description or ""
        if schema or "schema" not in next_tool:
            next_tool["schema"] = schema
        next_tool.setdefault("family", "mcp")
        next_tool.setdefault("risk_class", "medium")
        next_tool.setdefault("approval_class", "standard")
        if "enabled" in discovered:
            next_tool["enabled"] = bool(discovered.get("enabled"))
        else:
            next_tool.setdefault("enabled", True)
        next_tool.setdefault("reads_state", False)
        next_tool.setdefault("writes_state", False)
        next_tool.setdefault("touches_network", transport != "stdio")
        next_tool.setdefault("touches_secrets", bool(headers))
        synced_tools[tool_name] = next_tool
    return synced_tools


def discover_operator_mcp_server(self, payload: Mapping[str, Any]) -> dict[str, Any]:
    probe = _mcp_discover_payload(payload)
    result = discover_mcp_tools_sync(
        server_id=str(probe["serverId"]),
        server_label=str(probe["serverLabel"]),
        transport=str(probe["transport"]),
        command=str(probe.get("command") or ""),
        args=tuple(str(arg) for arg in probe.get("args", ())),
        url=str(probe.get("url") or ""),
        env={
            str(key): str(value) for key, value in dict(probe.get("env") or {}).items()
        },
        headers={
            str(key): str(value)
            for key, value in dict(probe.get("headers") or {}).items()
        },
        cwd=Path(__file__).resolve().parents[2],
    )
    tools = _mcp_discovered_tool_rows({"tools": result.get("tools", ())})
    error_text = str(result.get("error") or "").strip()
    status = (
        str(result.get("status") or ("failed" if error_text else "ok")).strip()
        or "failed"
    )
    return {
        "status": status,
        "serverId": probe["serverId"],
        "serverLabel": probe["serverLabel"],
        "transport": probe["transport"],
        "toolCount": len(tools),
        "durationMs": result.get("durationMs"),
        "tools": tools,
        "returnCode": result.get("returnCode"),
        "stdout": str(result.get("stdout") or "")[-8_000:],
        "stderr": str(result.get("stderr") or "")[-8_000:],
        "error": error_text or None,
    }


def patch_operator_settings(self, payload: Mapping[str, Any]) -> dict[str, Any]:
    database_path = self.repository.database_path
    state_dir = database_path.parent
    manifest = payload.get("profileManifest")
    if not isinstance(manifest, Mapping):
        raise ValueError("profileManifest must be an object")
    if not str(manifest.get("profile_id") or "").strip():
        raise ValueError("profileManifest.profile_id is required")
    manifest_path = _write_manifest_to_config(state_dir, manifest)
    return {
        "status": "ok",
        "profileManifestPath": str(manifest_path),
        "settings": _settings(state_dir, database_path),
    }


def patch_operator_global_config(self, payload: Mapping[str, Any]) -> dict[str, Any]:
    database_path = self.repository.database_path
    state_dir = database_path.parent
    config_path = global_config_path_for_state_dir(database_path.parent)
    raw_text = payload.get("yamlText")
    if isinstance(raw_text, str):
        config = parse_global_config_text(raw_text)
    else:
        config = payload.get("config")
    if not isinstance(config, Mapping):
        raise ValueError("config must be an object or yamlText must parse to an object")
    write_global_config(config_path, config)
    runtime_status = _sync_operator_mcp_runtime(
        self, config_path=config_path, config=config
    )
    next_settings = _settings(state_dir, database_path)
    return {
        "status": "ok",
        "globalConfigPath": str(config_path),
        "runtimeStatus": runtime_status,
        "settings": next_settings,
    }


def set_console_item_enabled(
    self, *, kind: str, item_id: str, enabled: bool
) -> dict[str, Any]:
    database_path = self.repository.database_path
    state_dir = database_path.parent
    config_path = global_config_path_for_state_dir(database_path.parent)
    manifest = _load_manifest_from_config(state_dir)
    if not isinstance(manifest, Mapping):
        manifest = {}
    section = "skill_overrides" if kind == "skill" else "tool_overrides"
    overrides = (
        dict(manifest.get(section, {}))
        if isinstance(manifest.get(section), Mapping)
        else {}
    )
    previous_override = overrides.get(item_id)
    next_override = dict(previous_override) if isinstance(previous_override, Mapping) else {}
    next_override["enabled"] = bool(enabled)
    if kind == "skill" and bool(enabled):
        review_status = str(next_override.get("review_status") or "").strip().lower()
        if review_status == "pending" or (
            not review_status and _skill_catalog_review_status(self, item_id) == "pending"
        ):
            next_override["review_status"] = "approved"
    overrides[item_id] = next_override
    next_manifest = dict(manifest)
    next_manifest[section] = overrides
    _write_manifest_to_config(state_dir, next_manifest)
    runtime_status = "profile_override_written"
    if kind == "tool":
        try:
            self.tool_runtime.set_enabled(item_id, bool(enabled))
            runtime_status = "runtime_reloaded"
        except KeyError:
            runtime_status = "profile_override_written_tool_not_loaded"
    elif hasattr(self, "skill_runtime"):
        skill_runtime = getattr(self, "skill_runtime")
        try:
            skill_runtime.set_enabled(item_id, bool(enabled))
            runtime_status = "runtime_reloaded"
        except Exception:
            LOGGER.warning(
                "failed to update loaded skill runtime after console override",
                extra={"skill_id": item_id, "enabled": bool(enabled)},
                exc_info=True,
            )
            runtime_status = "profile_override_written_skill_not_loaded"
    return {
        "status": "ok",
        "kind": kind,
        "itemId": item_id,
        "enabled": bool(enabled),
        "runtimeStatus": runtime_status,
        "profileManifestPath": str(config_path),
    }


def _default_mcp_tool_name() -> str:
    return "tool"


__all__ = [
    "_gateway",
    "_logs",
    "_mcp_catalog",
    "_profile_overrides",
    "_settings",
    "discover_operator_mcp_server",
    "gateway_action",
    "patch_operator_global_config",
    "patch_operator_settings",
    "set_console_item_enabled",
    "set_operator_mcp_tool_enabled",
    "create_operator_mcp_tool",
    "update_operator_mcp_tool",
    "delete_operator_mcp_tool",
]
