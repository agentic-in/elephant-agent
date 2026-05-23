"""Custom MCP tool runtime integration."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
import asyncio
import json
import os
import shlex
import subprocess
import threading
import time
from typing import Any

from packages.contracts.runtime import ExecutionResult

from .runtime import ToolAvailability, ToolDefinition, ToolHandler, ToolInvocation, ToolRuntime, ToolSideEffectMetadata

_MCP_TOOL_VERSION = "1.0.0"
_MCP_TOOL_KIND = "custom-mcp"
_MCP_CALL_TIMEOUT_MS = 120_000
_MCP_DISCOVERY_TIMEOUT_MS = 15_000
_COMMON_PATH_ENTRIES = (
    "/opt/homebrew/bin",
    "/opt/homebrew/sbin",
    "/usr/local/bin",
    "/usr/local/sbin",
    "/usr/bin",
    "/bin",
    "/usr/sbin",
    "/sbin",
)


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

    existing_custom_ids = {
        tool.tool_id
        for tool in runtime.list_tools()
        if _is_custom_mcp_tool(tool)
    }
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
        transport = str(server.get("transport") or ("http" if str(server.get("url") or "").strip() else "stdio")).strip().lower() or "stdio"
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


def discover_mcp_tools_sync(
    *,
    server_id: str,
    server_label: str,
    transport: str,
    command: str,
    args: tuple[str, ...],
    url: str,
    env: Mapping[str, str],
    headers: Mapping[str, str],
    cwd: str | Path,
    timeout_ms: int = _MCP_DISCOVERY_TIMEOUT_MS,
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        tools = _run_async(
            _discover_mcp_tools(
                transport=transport,
                command=command,
                args=args,
                url=url,
                env=env,
                headers=headers,
                cwd=Path(cwd),
                timeout_seconds=timeout_ms / 1000,
            )
        )
        return {
            "status": "ok",
            "serverId": server_id,
            "serverLabel": server_label,
            "transport": transport,
            "toolCount": len(tools),
            "durationMs": int((time.monotonic() - started) * 1000),
            "tools": tools,
            "returnCode": 0,
            "stdout": "",
            "stderr": "",
            "error": None,
        }
    except TimeoutError as exc:
        return _mcp_failure_result(
            server_id=server_id,
            server_label=server_label,
            transport=transport,
            duration_ms=int((time.monotonic() - started) * 1000),
            error=f"MCP discovery timed out after {timeout_ms}ms: {exc}",
        )
    except Exception as exc:
        return _mcp_failure_result(
            server_id=server_id,
            server_label=server_label,
            transport=transport,
            duration_ms=int((time.monotonic() - started) * 1000),
            error=_mcp_exception_message(exc),
        )


def _mcp_failure_result(
    *,
    server_id: str,
    server_label: str,
    transport: str,
    duration_ms: int,
    error: str,
) -> dict[str, Any]:
    return {
        "status": "failed",
        "serverId": server_id,
        "serverLabel": server_label,
        "transport": transport,
        "toolCount": 0,
        "durationMs": duration_ms,
        "tools": [],
        "returnCode": None,
        "stdout": "",
        "stderr": "",
        "error": error,
    }


async def _discover_mcp_tools(
    *,
    transport: str,
    command: str,
    args: tuple[str, ...],
    url: str,
    env: Mapping[str, str],
    headers: Mapping[str, str],
    cwd: Path,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    async def _list() -> list[dict[str, Any]]:
        async with _mcp_client_session(
            transport=transport,
            command=command,
            args=args,
            url=url,
            env=env,
            headers=headers,
            cwd=cwd,
        ) as session:
            result = await session.list_tools()
            return [_mcp_tool_payload(tool) for tool in result.tools]

    return await asyncio.wait_for(_list(), timeout=timeout_seconds)


def _call_mcp_tool_sync(
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
) -> dict[str, Any]:
    return _run_async(
        _call_mcp_tool(
            tool_name=tool_name,
            transport=transport,
            command=command,
            args=args,
            url=url,
            env=env,
            headers=headers,
            arguments=arguments,
            cwd=cwd,
        )
    )


async def _call_mcp_tool(
    *,
    tool_name: str,
    transport: str,
    command: str,
    args: tuple[str, ...],
    url: str,
    env: Mapping[str, str],
    headers: Mapping[str, str],
    arguments: Mapping[str, Any],
    cwd: Path,
) -> dict[str, Any]:
    async def _call() -> dict[str, Any]:
        async with _mcp_client_session(
            transport=transport,
            command=command,
            args=args,
            url=url,
            env=env,
            headers=headers,
            cwd=cwd,
        ) as session:
            result = await session.call_tool(tool_name, dict(arguments))
            return _model_dump(result)

    return await asyncio.wait_for(_call(), timeout=_MCP_CALL_TIMEOUT_MS / 1000)


@asynccontextmanager
async def _mcp_client_session(
    *,
    transport: str,
    command: str,
    args: tuple[str, ...],
    url: str,
    env: Mapping[str, str],
    headers: Mapping[str, str],
    cwd: Path,
):
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.sse import sse_client
        from mcp.client.stdio import stdio_client
        from mcp.client.streamable_http import streamablehttp_client
    except ImportError as exc:
        raise RuntimeError("Python package 'mcp' is required for custom MCP tools. Install project dependencies and retry.") from exc

    normalized_transport = (transport or "stdio").strip().lower() or "stdio"
    if normalized_transport == "stdio":
        resolved_command, command_args = _stdio_command_parts(command, args)
        server = StdioServerParameters(
            command=resolved_command,
            args=command_args,
            env=_mcp_process_env(env),
            cwd=cwd,
        )
        async with stdio_client(server) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session
        return

    if not url:
        raise ValueError("url is required for remote MCP transport")
    if normalized_transport == "sse":
        async with sse_client(url, headers=dict(headers)) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session
        return

    async with streamablehttp_client(url, headers=dict(headers)) as (read_stream, write_stream, _session_id):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            yield session


def _stdio_command_parts(command: str, args: tuple[str, ...]) -> tuple[str, list[str]]:
    command_text = str(command or "").strip()
    if not command_text:
        raise ValueError("command is required for stdio transport")
    command_parts = shlex.split(command_text)
    if not command_parts:
        raise ValueError("command is required for stdio transport")
    return command_parts[0], [*command_parts[1:], *args]


def _mcp_process_env(overrides: Mapping[str, str]) -> dict[str, str]:
    process_env = dict(os.environ)
    process_env["PATH"] = _merged_shell_path(process_env.get("PATH", ""))
    for key, value in overrides.items():
        normalized = str(key).strip()
        if normalized:
            process_env[normalized] = str(value)
    return process_env


def _merged_shell_path(current_path: str) -> str:
    entries: list[str] = []
    for path in (current_path, _login_shell_path(), os.defpath):
        entries.extend(path.split(os.pathsep))
    entries.extend(_COMMON_PATH_ENTRIES)
    home = str(Path.home())
    entries.extend([f"{home}/.local/bin", f"{home}/.cargo/bin", f"{home}/.npm-global/bin"])
    deduped: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        normalized = entry.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return os.pathsep.join(deduped)


@lru_cache(maxsize=1)
def _login_shell_path() -> str:
    shell = os.environ.get("SHELL", "").strip() or "/bin/zsh"
    if not Path(shell).exists():
        return ""
    try:
        completed = subprocess.run(
            [shell, "-lc", 'printf "%s" "$PATH"'],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _mcp_tool_payload(tool: Any) -> dict[str, Any]:
    payload = _model_dump(tool)
    schema = payload.get("inputSchema")
    if not isinstance(schema, Mapping):
        schema = {}
    return {
        "name": str(payload.get("name") or "").strip(),
        "description": str(payload.get("description") or "").strip(),
        "inputSchema": dict(schema),
    }


def _model_dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return dict(value.model_dump(mode="json", exclude_none=True))
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:
            result["error"] = exc

    thread = threading.Thread(target=_runner, name="elephant-mcp-client", daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


def _mcp_exception_message(exc: Exception) -> str:
    message = str(exc).strip()
    if isinstance(exc, FileNotFoundError):
        return f"{message}. If this command works in Terminal, use an absolute path or ensure the macOS app can see your shell PATH."
    if message:
        return message
    return exc.__class__.__name__


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
        try:
            result = _call_mcp_tool_sync(
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
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                execution_id=invocation.invocation_id,
                episode_id=invocation.session_id,
                outcome="failed",
                summary=(
                    f"MCP tool {server_id}.{tool_name} timed out after {_MCP_CALL_TIMEOUT_MS}ms"
                ),
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
        except TimeoutError:
            return ExecutionResult(
                execution_id=invocation.invocation_id,
                episode_id=invocation.session_id,
                outcome="failed",
                summary=f"MCP tool {server_id}.{tool_name} timed out after {_MCP_CALL_TIMEOUT_MS}ms",
                side_effects=("mcp", f"server={server_id}", f"transport={transport}"),
            )
        except Exception as exc:
            return ExecutionResult(
                execution_id=invocation.invocation_id,
                episode_id=invocation.session_id,
                outcome="failed",
                summary=f"MCP tool {server_id}.{tool_name} failed: {_mcp_exception_message(exc)}",
                side_effects=("mcp", f"server={server_id}", f"transport={transport}"),
            )

        summary = _mcp_result_summary(result)
        if bool(result.get("isError")):
            error_text = summary or "MCP tool execution failed"
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


def _mcp_result_summary(result: Mapping[str, Any]) -> str:
    return _json_summary(dict(result))


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
    "discover_mcp_tools_sync",
    "mcp_runtime_tool_id",
    "sync_custom_mcp_tools",
]
