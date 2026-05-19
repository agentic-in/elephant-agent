"""Custom MCP tool runtime integration."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import json
import subprocess
import tempfile
from typing import Any

from packages.contracts.runtime import ExecutionResult

from .runtime import (
    ToolAvailability,
    ToolDefinition,
    ToolHandler,
    ToolInvocation,
    ToolRuntime,
    ToolSideEffectMetadata,
)

_MCP_TOOL_VERSION = "1.0.0"
_MCP_TOOL_KIND = "custom-mcp"
_MCP_CALL_TIMEOUT_MS = 120_000


def mcp_runtime_tool_id(server_id: str, tool_name: str) -> str:
    return f"mcp.{server_id}.{tool_name}"


def sync_custom_mcp_tools(
    runtime: ToolRuntime,
    *,
    config_path: str | Path,
    config: Mapping[str, Any],
    cwd: str | Path | None = None,
) -> tuple[str, ...]:
    desired: dict[str, tuple[ToolDefinition, ToolHandler]] = {}
    for definition, handler in custom_mcp_runtime_entries(config_path=config_path, config=config, cwd=cwd):
        desired[definition.tool_id] = (definition, handler)

    existing_custom_ids = {tool.tool_id for tool in runtime.list_tools() if _is_custom_mcp_tool(tool)}
    for stale_tool_id in sorted(existing_custom_ids - set(desired)):
        runtime.unregister_tool(stale_tool_id)
    for tool_id, (definition, handler) in desired.items():
        runtime.register_tool(definition, handler=handler)
    return tuple(sorted(desired))


def custom_mcp_runtime_entries(
    *,
    config_path: str | Path,
    config: Mapping[str, Any],
    cwd: str | Path | None = None,
) -> tuple[tuple[ToolDefinition, ToolHandler], ...]:
    root = Path(cwd) if cwd is not None else Path.cwd()
    config_ref = Path(config_path)
    overrides = _mapping_rows(config.get("mcp_overrides"))
    entries: list[tuple[ToolDefinition, ToolHandler]] = []
    for server_id, server in sorted(_mapping_rows(config.get("mcp_servers")).items()):
        transport = (
            str(server.get("transport") or ("http" if str(server.get("url") or "").strip() else "stdio"))
            .strip()
            .lower()
            or "stdio"
        )
        label = str(server.get("label") or server_id).strip() or server_id
        command = str(server.get("command") or "").strip()
        url = str(server.get("url") or "").strip()
        args = _text_list(server.get("args"))
        env = _string_map(server.get("env"))
        headers = _string_map(server.get("headers"))
        available = bool(command or url)
        availability_reason = "" if available else "server command or url is not configured"
        tools = _mapping_rows(server.get("tools"))
        for tool_name, tool in sorted(tools.items()):
            tool_key = _mcp_tool_key(server_id, tool_name)
            default_enabled = bool(tool.get("enabled", True))
            enabled = _override_enabled(overrides, tool_key, default_enabled)
            schema = dict(tool.get("schema", {})) if isinstance(tool.get("schema"), Mapping) else {}
            description = str(tool.get("description") or "").strip()
            family = str(tool.get("family") or "mcp").strip() or "mcp"
            risk_class = str(tool.get("risk_class") or "medium").strip() or "medium"
            approval_class = str(tool.get("approval_class") or "standard").strip() or "standard"
            touches_network = bool(tool.get("touches_network", False)) or transport != "stdio"
            touches_secrets = bool(tool.get("touches_secrets", False)) or bool(headers)
            definition = ToolDefinition(
                tool_id=mcp_runtime_tool_id(server_id, tool_name),
                display_name=str(tool.get("display_name") or tool_name).strip() or tool_name,
                version=str(tool.get("version") or _MCP_TOOL_VERSION),
                description=description,
                schema=schema,
                side_effects=ToolSideEffectMetadata(
                    risk_class=risk_class,
                    approval_class=approval_class,
                    writes_state=bool(tool.get("writes_state", False)),
                    reads_state=bool(tool.get("reads_state", False)),
                    touches_network=touches_network,
                    touches_secrets=touches_secrets,
                    categories=("mcp", family, server_id),
                    notes=f"Custom MCP tool from server {label}.",
                ),
                enabled=enabled,
                family=family,
                audience="model",
                availability=ToolAvailability(
                    is_available=available,
                    reason=None if available else availability_reason,
                ),
                backend="mcp",
                metadata={
                    "kind": _MCP_TOOL_KIND,
                    "source": "custom-mcp",
                    "sourceKind": "mcp",
                    "serverId": server_id,
                    "serverLabel": label,
                    "toolName": tool_name,
                    "toolKey": tool_key,
                    "transport": transport,
                },
                provenance=f"{config_ref}#mcp_servers.{server_id}.tools.{tool_name}",
            )
            handler = _build_mcp_tool_handler(
                server_id=server_id,
                tool_name=tool_name,
                transport=transport,
                command=command,
                args=args,
                url=url,
                env=env,
                headers=headers,
                cwd=root,
            )
            entries.append((definition, handler))
    return tuple(entries)


def _is_custom_mcp_tool(tool: ToolDefinition) -> bool:
    return tool.backend == "mcp" and str(tool.metadata.get("kind") or "") == _MCP_TOOL_KIND


def _mcp_tool_key(server_id: str, tool_name: str) -> str:
    return f"{server_id}:{tool_name}"


def _override_enabled(overrides: Mapping[str, Any], tool_key: str, default_enabled: bool) -> bool:
    entry = overrides.get(tool_key)
    if isinstance(entry, Mapping) and "enabled" in entry:
        return bool(entry.get("enabled"))
    return default_enabled


def _mapping_rows(payload: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, Mapping):
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for key, value in payload.items():
        normalized_key = str(key).strip()
        if not normalized_key or not isinstance(value, Mapping):
            continue
        rows[normalized_key] = {str(item_key): item_value for item_key, item_value in value.items()}
    return rows


def _string_map(payload: Any) -> dict[str, str]:
    if not isinstance(payload, Mapping):
        return {}
    values: dict[str, str] = {}
    for key, value in payload.items():
        normalized_key = str(key).strip()
        if not normalized_key:
            continue
        values[normalized_key] = str(value)
    return values


def _text_list(payload: Any) -> tuple[str, ...]:
    if not isinstance(payload, list | tuple):
        return ()
    values: list[str] = []
    for item in payload:
        text = str(item).strip()
        if text:
            values.append(text)
    return tuple(values)


def _build_mcp_tool_handler(
    *,
    server_id: str,
    tool_name: str,
    transport: str,
    command: str,
    args: tuple[str, ...],
    url: str,
    env: Mapping[str, str],
    headers: Mapping[str, str],
    cwd: Path,
) -> ToolHandler:
    def _handler(invocation: ToolInvocation) -> ExecutionResult:
        command_line, tempdir = _mcporter_call_command(
            server_id=server_id,
            tool_name=tool_name,
            transport=transport,
            command=command,
            args=args,
            url=url,
            env=env,
            headers=headers,
            arguments=invocation.arguments,
            cwd=cwd,
        )
        try:
            try:
                completed = subprocess.run(
                    command_line,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=_MCP_CALL_TIMEOUT_MS / 1000,
                    check=False,
                )
            finally:
                if tempdir is not None:
                    tempdir.cleanup()
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                execution_id=invocation.invocation_id,
                episode_id=invocation.session_id,
                outcome="failed",
                summary=(f"MCP tool {server_id}.{tool_name} timed out after {_MCP_CALL_TIMEOUT_MS}ms"),
                side_effects=("mcp", f"server={server_id}", f"transport={transport}"),
            )
        except OSError as exc:
            return ExecutionResult(
                execution_id=invocation.invocation_id,
                episode_id=invocation.session_id,
                outcome="failed",
                summary=f"MCP tool {server_id}.{tool_name} failed to start: {exc}",
                side_effects=("mcp", f"server={server_id}", f"transport={transport}"),
            )

        summary = _mcporter_output_summary(completed.stdout)
        if completed.returncode != 0:
            error_text = (completed.stderr or summary or "MCP tool execution failed").strip()
            return ExecutionResult(
                execution_id=invocation.invocation_id,
                episode_id=invocation.session_id,
                outcome="failed",
                summary=error_text,
                side_effects=("mcp", f"server={server_id}", f"transport={transport}"),
            )
        return ExecutionResult(
            execution_id=invocation.invocation_id,
            episode_id=invocation.session_id,
            outcome="success",
            summary=summary or f"MCP tool {server_id}.{tool_name} completed with no output.",
            side_effects=("mcp", f"server={server_id}", f"transport={transport}"),
        )

    return _handler


def _mcporter_call_command(
    *,
    server_id: str,
    tool_name: str,
    transport: str,
    command: str,
    args: tuple[str, ...],
    url: str,
    env: Mapping[str, str],
    headers: Mapping[str, str],
    arguments: Mapping[str, Any],
    cwd: Path,
) -> tuple[list[str], tempfile.TemporaryDirectory[str] | None]:
    serialized_arguments = json.dumps(dict(arguments), ensure_ascii=False, default=str)
    if transport == "stdio":
        command_line = [
            "npx",
            "--yes",
            "mcporter",
            "call",
            "--stdio",
            command,
            "--name",
            server_id,
            "--cwd",
            str(cwd),
        ]
        for value in args:
            command_line.extend(["--stdio-arg", value])
        for key, value in env.items():
            command_line.extend(["--env", f"{key}={value}"])
        command_line.extend(
            [
                tool_name,
                "--args",
                serialized_arguments,
                "--output",
                "json",
                "--timeout",
                str(_MCP_CALL_TIMEOUT_MS),
            ]
        )
        return command_line, None

    tempdir: tempfile.TemporaryDirectory[str] | None = tempfile.TemporaryDirectory(prefix="elephant-mcporter-call-")
    config_path = Path(tempdir.name) / "mcporter.json"
    entry: dict[str, Any] = {
        "url": url,
    }
    if headers:
        entry["headers"] = dict(headers)
    if transport in {"streamable-http", "sse"}:
        entry["transportType"] = transport
    config_path.write_text(json.dumps({"mcpServers": {server_id: entry}}, indent=2), encoding="utf-8")
    command_line = [
        "npx",
        "--yes",
        "mcporter",
        "--config",
        str(config_path),
        "call",
        f"{server_id}.{tool_name}",
        "--args",
        serialized_arguments,
        "--output",
        "json",
        "--timeout",
        str(_MCP_CALL_TIMEOUT_MS),
    ]
    if url.startswith("http://"):
        command_line.append("--allow-http")
    return command_line, tempdir


def _mcporter_output_summary(stdout: str) -> str:
    text = str(stdout or "").strip()
    if not text:
        return ""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text
    return _json_summary(payload)


def _json_summary(payload: Any) -> str:
    if isinstance(payload, Mapping):
        for key in ("summary", "message", "text"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        content = payload.get("content")
        if isinstance(content, list):
            lines: list[str] = []
            for item in content:
                if not isinstance(item, Mapping):
                    continue
                block_type = str(item.get("type") or "").strip().lower()
                if block_type == "text":
                    block_text = str(item.get("text") or "").strip()
                    if block_text:
                        lines.append(block_text)
                    continue
                if block_type:
                    body = {str(key): value for key, value in item.items() if key != "type"}
                    lines.append(f"[{block_type}] {json.dumps(body, ensure_ascii=False, default=str)}")
            if lines:
                return "\n".join(lines)
        for key in ("result", "output", "data"):
            if key in payload:
                return json.dumps(payload[key], ensure_ascii=False, indent=2, default=str)
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


__all__ = [
    "custom_mcp_runtime_entries",
    "mcp_runtime_tool_id",
    "sync_custom_mcp_tools",
]
