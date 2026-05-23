"""Console config, gateway, and custom MCP operations."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from typing import Any

from packages.tools import sync_custom_mcp_tools
from packages.tools.mcp import discover_mcp_tools_sync
from packages.runtime_config import (
    global_config_path_for_state_dir,
    global_config_schema,
    load_global_config,
    load_extensions_from_config,
    save_extensions_to_config,
    save_provider_to_config,
    parse_global_config_text,
    read_global_config_text,
    write_global_config,
)


def _write_manifest_to_config(state_dir: Path, manifest: Mapping[str, Any]) -> Path:
    """Write manifest data (gateway, extensions) to config.yaml.

    Treats the fields *present* in ``manifest`` as authoritative:

    - If ``manifest["gateway"]`` is a Mapping, the persisted gateway
      section is *replaced* by it (not merged). This ensures keys
      removed from the manifest (e.g. dropping the last account) are
      actually dropped on disk.
    - If ``manifest["gateway"]`` is explicitly ``None`` or an empty
      Mapping, the gateway section is deleted from config. Callers
      signal "drop this section" by setting ``manifest["gateway"] =
      None``.
    - If ``manifest`` omits ``gateway`` entirely, the persisted
      gateway section is left untouched. This preserves compatibility
      with callers (e.g. operator settings patcher) that only care
      about other sections.
    """
    config_path = global_config_path_for_state_dir(state_dir)
    config = load_global_config(config_path, state_dir=state_dir)
    # Gateway section
    if "gateway" in manifest:
        gateway_payload = manifest.get("gateway")
        if isinstance(gateway_payload, Mapping) and gateway_payload:
            # Replace rather than merge so removed keys are honoured.
            config["gateway"] = dict(gateway_payload)
        else:
            # Explicit None / empty mapping — delete the section.
            config.pop("gateway", None)
    # (else: caller omitted gateway entirely — leave persisted value alone.)
    # Provider section
    provider_profile = manifest.get("provider_profile")
    if isinstance(provider_profile, Mapping):
        models = config.get("models", {})
        models["provider"] = dict(provider_profile)
        models["default_provider_source"] = "config"
        config["models"] = models
    # Extension keys
    extension_keys = ("tool_manifests", "skill_manifests", "skill_overrides", "tool_overrides", "skill_packages")
    extensions = config.get("extensions", {})
    for key in extension_keys:
        if key in manifest:
            extensions[key] = manifest[key]
    if extensions:
        config["extensions"] = extensions
    write_global_config(config_path, config)
    return config_path


def _read_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _load_manifest_from_config(state_dir: Path) -> dict[str, Any]:
    """Load manifest data (gateway, extensions) from config.yaml for the given state_dir."""
    from packages.runtime_config import global_config_path_for_state_dir
    config_path = global_config_path_for_state_dir(state_dir)
    try:
        config = load_global_config(config_path, state_dir=state_dir)
        result: dict[str, Any] = {}
        extensions = load_extensions_from_config(config)
        if extensions:
            result.update(extensions)
        gateway = config.get("gateway")
        if isinstance(gateway, Mapping):
            result["gateway"] = dict(gateway)
        return result
    except (OSError, ValueError):
        pass
    return {}


def _read_text_file(path: Path, *, max_chars: int = 20_000) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


GATEWAY_LOCAL_SECRET_ENV_FILE = "gateway-local-secrets.json"
DEFAULT_GATEWAY_ACCOUNT_ID = "default"

_GATEWAY_SERVICE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "service": "weixin",
        "label": "WeChat",
        "adapterId": "messaging.weixin",
        "surface": "weixin-ilink",
        "defaultTransport": "ilink",
        "transports": ("ilink",),
        "summary": "WeChat iLink bridge with the same scan-to-login QR flow as `elephant gateway setup`.",
        "eventPath": "/weixin/events",
        "secretFields": (),
        "supportsDirectConfig": True,
        "setupNote": "Click Connect & start WeChat, scan the QR with WeChat, then Dashboard automatically detects confirmation and starts the bridge.",
    },
    {
        "service": "feishu",
        "label": "Feishu",
        "adapterId": "messaging.feishu",
        "surface": "feishu-messaging",
        "defaultTransport": "long-connection",
        "transports": ("long-connection",),
        "summary": "Feishu bot long-connection bridge for p2p and group chat messages.",
        "eventPath": "/feishu/events",
        "secretFields": (
            {"key": "app_id", "label": "App ID", "defaultEnvVar": "ELEPHANT_FEISHU_APP_ID"},
            {"key": "app_secret", "label": "App Secret", "defaultEnvVar": "ELEPHANT_FEISHU_APP_SECRET"},
        ),
        "supportsDirectConfig": True,
    },
    {
        "service": "discord",
        "label": "Discord",
        "adapterId": "messaging.discord",
        "surface": "discord-gateway",
        "defaultTransport": "gateway",
        "transports": ("gateway",),
        "summary": "Discord bot gateway bridge for DMs, channels, and threads.",
        "secretFields": (
            {"key": "bot_token", "label": "Bot token", "defaultEnvVar": "ELEPHANT_DISCORD_BOT_TOKEN"},
        ),
        "supportsDirectConfig": True,
    },
    {
        "service": "dingding",
        "label": "DingDing",
        "adapterId": "messaging.dingding",
        "surface": "dingding-stream",
        "defaultTransport": "stream",
        "transports": ("stream",),
        "summary": "DingDing stream bridge for chatbot messages.",
        "secretFields": (
            {"key": "client_id", "label": "Client ID", "defaultEnvVar": "ELEPHANT_DINGDING_CLIENT_ID"},
            {"key": "client_secret", "label": "Client Secret", "defaultEnvVar": "ELEPHANT_DINGDING_CLIENT_SECRET"},
            {"key": "robot_code", "label": "Robot Code", "defaultEnvVar": "ELEPHANT_DINGDING_ROBOT_CODE"},
        ),
        "supportsDirectConfig": True,
    },
    {
        "service": "wecom",
        "label": "WeCom",
        "adapterId": "messaging.wecom",
        "surface": "wecom-websocket",
        "defaultTransport": "websocket",
        "transports": ("websocket",),
        "summary": "WeCom AI Bot WebSocket bridge for chats and groups.",
        "secretFields": (
            {"key": "bot_id", "label": "Bot ID", "defaultEnvVar": "ELEPHANT_WECOM_BOT_ID"},
            {"key": "secret", "label": "Secret", "defaultEnvVar": "ELEPHANT_WECOM_SECRET"},
        ),
        "supportsDirectConfig": True,
    },
)
_GATEWAY_SERVICE_BY_KEY = {str(spec["service"]): spec for spec in _GATEWAY_SERVICE_SPECS}


def _tail_lines(path: Path, *, max_lines: int = 160) -> tuple[str, ...]:
    text = _read_text_file(path, max_chars=80_000)
    if not text:
        return ()
    return tuple(text.splitlines()[-max_lines:])


def _logs(state_dir: Path) -> list[dict[str, Any]]:
    candidates = [
        *state_dir.glob("*.log"),
    ]
    seen: set[Path] = set()
    rows: list[dict[str, Any]] = []
    for path in sorted(candidates):
        resolved = path.resolve()
        if resolved in seen or not path.is_file():
            continue
        seen.add(resolved)
        rows.append(
            {
                "name": path.name,
                "path": str(path),
                "size": path.stat().st_size,
                "updatedAt": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
                "tail": _tail_lines(path),
            }
        )
    return rows


def _gateway_local_secret_env_path(gateway_dir: Path) -> Path:
    return gateway_dir / GATEWAY_LOCAL_SECRET_ENV_FILE


def _load_gateway_local_secret_env(gateway_dir: Path) -> dict[str, str]:
    payload = _read_json_file(_gateway_local_secret_env_path(gateway_dir))
    if not isinstance(payload, Mapping):
        return {}
    return {str(key): str(value) for key, value in payload.items() if str(value).strip()}


def _persist_gateway_local_secret_env(gateway_dir: Path, updates: Mapping[str, str]) -> Path | None:
    filtered = {str(key): str(value).strip() for key, value in updates.items() if str(value).strip()}
    if not filtered:
        return None
    gateway_dir.mkdir(parents=True, exist_ok=True)
    path = _gateway_local_secret_env_path(gateway_dir)
    payload = _load_gateway_local_secret_env(gateway_dir)
    payload.update(filtered)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def _delete_gateway_local_secret_env(gateway_dir: Path, keys: tuple[str, ...]) -> Path | None:
    if not keys:
        return None
    path = _gateway_local_secret_env_path(gateway_dir)
    payload = _load_gateway_local_secret_env(gateway_dir)
    changed = False
    for key in keys:
        if key in payload:
            payload.pop(key, None)
            changed = True
    if not changed:
        return None
    if payload:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    else:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    return path


def _gateway_account_suffix(account_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", account_id.strip()).strip("_").upper() or "DEFAULT"


def _default_gateway_secret_env_var(service: str, account_id: str, secret_key: str, default_env_var: str) -> str:
    if account_id == DEFAULT_GATEWAY_ACCOUNT_ID:
        return default_env_var
    return f"ELEPHANT_{service.upper()}_{_gateway_account_suffix(account_id)}_{secret_key.upper()}"


def _gateway_account_secret_env_var(
    *,
    service: str,
    account: Mapping[str, Any],
    account_id: str,
    secret_key: str,
    default_env_var: str,
) -> str:
    env_payload = account.get("env")
    if isinstance(env_payload, Mapping):
        text = str(env_payload.get(secret_key) or "").strip()
        if text:
            return text
    secret_refs = account.get("secret_references")
    if isinstance(secret_refs, (list, tuple)):
        for ref in secret_refs:
            if not isinstance(ref, Mapping) or str(ref.get("secret_key") or "") != secret_key:
                continue
            metadata = ref.get("metadata")
            if isinstance(metadata, Mapping):
                text = str(metadata.get("env_var") or "").strip()
                if text:
                    return text
    return _default_gateway_secret_env_var(service, account_id, secret_key, default_env_var)


def _gateway_runtime_service_key(row: Mapping[str, Any]) -> str:
    content = row.get("content")
    if isinstance(content, Mapping):
        return str(content.get("service_key") or "")
    name = str(row.get("name") or "")
    return name.split("-", 1)[0] if "-" in name else ""


def _pid_is_alive(pid: Any) -> bool | None:
    """Return True if pid is a live process, False if dead, None if no pid recorded."""
    if pid is None:
        return None
    try:
        pid_int = int(pid)
    except (ValueError, TypeError):
        return False
    if pid_int <= 0:
        return False
    try:
        os.kill(pid_int, 0)
    except OSError:
        return False
    return True


def _gateway_runtime_status(row: Mapping[str, Any]) -> str:
    """Return one of 'running', 'starting', 'failed', 'stopped'.

    Collapses recorded runtime status against actual pid liveness so the
    dashboard reflects reality (e.g. a 'running' record whose pid died is
    reported as 'stopped').
    """
    content = row.get("content")
    if not isinstance(content, Mapping):
        return "stopped"
    recorded = str(content.get("status") or "").lower()
    alive = _pid_is_alive(content.get("pid"))
    if recorded == "running":
        if alive is False:
            return "stopped"
        return "running"
    if recorded == "starting":
        if alive is False:
            return "stopped"
        return "starting"
    if recorded == "failed":
        return "failed"
    return "stopped"


def _gateway_runtime_is_running(row: Mapping[str, Any]) -> bool:
    return _gateway_runtime_status(row) == "running"


def _gateway_runtime_is_starting(row: Mapping[str, Any]) -> bool:
    return _gateway_runtime_status(row) == "starting"


def _gateway_services(
    *,
    gateway_dir: Path,
    state_dir: Path | None,
    runtime_files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    manifest = _load_manifest_from_config(state_dir) if state_dir is not None else None
    gateway_manifest = manifest.get("gateway") if isinstance(manifest, Mapping) else None
    adapters = gateway_manifest.get("adapters") if isinstance(gateway_manifest, Mapping) else None
    adapters_payload = adapters if isinstance(adapters, Mapping) else {}
    local_secrets = _load_gateway_local_secret_env(gateway_dir)
    rows: list[dict[str, Any]] = []
    for spec in _GATEWAY_SERVICE_SPECS:
        service = str(spec["service"])
        adapter = adapters_payload.get(service)
        adapter_payload = adapter if isinstance(adapter, Mapping) else {}
        account_rows = [dict(item) for item in adapter_payload.get("accounts", ()) if isinstance(item, Mapping)] if isinstance(adapter_payload.get("accounts"), (list, tuple)) else []
        primary_account = account_rows[0] if account_rows else {}
        account_id = str(primary_account.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID)
        secret_fields = []
        for field in spec.get("secretFields", ()):
            if not isinstance(field, Mapping):
                continue
            secret_key = str(field.get("key") or "").strip()
            default_env_var = str(field.get("defaultEnvVar") or "").strip()
            env_var = _gateway_account_secret_env_var(
                service=service,
                account=primary_account,
                account_id=account_id,
                secret_key=secret_key,
                default_env_var=default_env_var,
            )
            secret_fields.append({
                "key": secret_key,
                "label": str(field.get("label") or secret_key),
                "hasValue": bool(local_secrets.get(env_var)),
            })
        service_runtime_files = [row for row in runtime_files if _gateway_runtime_service_key(row) == service]
        control = adapter_payload.get("control") if isinstance(adapter_payload.get("control"), Mapping) else {}
        configured_transport = str(primary_account.get("surface") or adapter_payload.get("surface") or spec.get("defaultTransport") or "")
        enabled = adapter_payload.get("enabled") is True
        runtime_states = [_gateway_runtime_status(row) for row in service_runtime_files]
        is_running = any(state == "running" for state in runtime_states)
        is_starting = (not is_running) and any(state == "starting" for state in runtime_states)
        last_error = ""
        for row in service_runtime_files:
            content = row.get("content") if isinstance(row, Mapping) else None
            if isinstance(content, Mapping):
                err = str(content.get("last_error") or "").strip()
                if err:
                    last_error = err
                    break
        rows.append({
            **{key: value for key, value in spec.items() if key != "secretFields"},
            "enabled": enabled,
            "configured": bool(account_rows),
            "configuredTransport": configured_transport,
            "accountCount": len(account_rows),
            "accounts": tuple(account_rows),
            "primaryAccountId": account_id,
            "eventPath": str(primary_account.get("event_path") or adapter_payload.get("event_path") or spec.get("eventPath") or ""),
            "allowGroupChats": bool(control.get("allow_group_chats") is True),
            "secretFields": tuple(secret_fields),
            "runtimeFiles": tuple(service_runtime_files),
            "running": is_running,
            "starting": is_starting,
            "lastError": last_error,
            "runtimeStatus": "running" if is_running else "starting" if is_starting else "failed" if last_error else "stopped",
            "runtimeSource": "files" if service_runtime_files else "config",
            "runtimeDetails": {},
            "startedAt": None,
        })
    return rows


def _gateway_runtime_files(gateway_dir: Path) -> list[dict[str, Any]]:
    runtime_files: list[dict[str, Any]] = []
    for path in sorted((*gateway_dir.glob("*.runtime.json"), *gateway_dir.glob("*.pid"))):
        if not path.is_file():
            continue
        runtime_files.append(
            {
                "name": path.name,
                "path": str(path),
                "updatedAt": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
                "content": _read_json_file(path) if path.suffix == ".json" else _read_text_file(path, max_chars=4_000),
            }
        )
    return runtime_files


def _gateway_runtime_bridge_services(runtime_bridge: Any | None) -> dict[str, dict[str, Any]]:
    if runtime_bridge is None or not hasattr(runtime_bridge, "gateway_runtime_snapshot"):
        return {}
    try:
        snapshot = runtime_bridge.gateway_runtime_snapshot()
    except Exception:
        return {}
    if not isinstance(snapshot, Mapping):
        return {}
    services_payload = snapshot.get("services")
    if not isinstance(services_payload, Mapping):
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for key, raw in services_payload.items():
        if not isinstance(raw, Mapping):
            continue
        status_text = str(raw.get("status") or "").strip().lower()
        if status_text not in {"idle", "running", "starting", "failed", "stopped", "skipped"}:
            status_text = "stopped"
        details = raw.get("details")
        rows[str(key)] = {
            "service": str(raw.get("service") or key).strip() or str(key),
            "status": status_text,
            "startedAt": str(raw.get("startedAt") or raw.get("started_at") or "").strip() or None,
            "lastError": str(raw.get("lastError") or raw.get("last_error") or "").strip(),
            "details": dict(details) if isinstance(details, Mapping) else {},
            "runtimeSource": str(raw.get("runtimeSource") or "daemon").strip() or "daemon",
        }
    return rows


def _merge_gateway_runtime(
    services: list[dict[str, Any]],
    *,
    runtime_bridge: Any | None,
) -> list[dict[str, Any]]:
    bridge_rows = _gateway_runtime_bridge_services(runtime_bridge)
    if not bridge_rows:
        return services
    merged: list[dict[str, Any]] = []
    for row in services:
        service = str(row.get("service") or "")
        bridge_row = bridge_rows.get(service)
        if bridge_row is None:
            merged.append(row)
            continue
        status_text = str(bridge_row.get("status") or "stopped")
        merged.append(
            {
                **row,
                "running": status_text == "running",
                "starting": status_text == "starting",
                "lastError": str(bridge_row.get("lastError") or ""),
                "runtimeStatus": status_text,
                "runtimeSource": bridge_row.get("runtimeSource") or "daemon",
                "runtimeDetails": bridge_row.get("details") if isinstance(bridge_row.get("details"), Mapping) else {},
                "startedAt": bridge_row.get("startedAt"),
            }
        )
    return merged


def _gateway_runtime_bridge_for_app(app: Any) -> Any | None:
    bridge = getattr(app, "gateway_runtime_bridge", None)
    return bridge if hasattr(bridge, "gateway_runtime_snapshot") else None


def _gateway_view(app: Any, state_dir: Path) -> dict[str, Any]:
    return _gateway(state_dir, runtime_bridge=_gateway_runtime_bridge_for_app(app))


def _gateway(state_dir: Path, *, runtime_bridge: Any | None = None) -> dict[str, Any]:
    # Gateway shares CLI's state dir — runtime status files sit directly in it
    # (no legacy `<state_dir>/gateway` subdir).
    gateway_dir = state_dir
    runtime_files = _gateway_runtime_files(gateway_dir)
    services = _gateway_services(gateway_dir=gateway_dir, state_dir=state_dir, runtime_files=runtime_files)
    services = _merge_gateway_runtime(services, runtime_bridge=runtime_bridge)
    return {
        "gatewayDir": str(gateway_dir),
        "exists": gateway_dir.exists(),
        "runtimeFiles": runtime_files,
        "logs": _logs(gateway_dir) if gateway_dir.exists() else [],
        "services": services,
        "configuredServiceCount": sum(1 for service in services if service["configured"]),
        "runningServiceCount": sum(1 for service in services if service["running"]),
        "startingServiceCount": sum(1 for service in services if service.get("starting")),
        "runtimeBridgeConnected": bool(_gateway_runtime_bridge_services(runtime_bridge)),
    }


def _gateway_manifest(state_dir: Path) -> dict[str, Any]:
    manifest = _load_manifest_from_config(state_dir)
    return dict(manifest) if isinstance(manifest, Mapping) else {}


def _gateway_adapter_payload(manifest: Mapping[str, Any], service: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    gateway_payload = manifest.get("gateway") if isinstance(manifest.get("gateway"), Mapping) else {}
    adapters_payload = gateway_payload.get("adapters") if isinstance(gateway_payload.get("adapters"), Mapping) else {}
    adapter_payload = adapters_payload.get(service) if isinstance(adapters_payload.get(service), Mapping) else {}
    return dict(gateway_payload), dict(adapters_payload), dict(adapter_payload)


def _gateway_accounts(adapter_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    accounts = adapter_payload.get("accounts")
    if not isinstance(accounts, (list, tuple)):
        return []
    return [dict(account) for account in accounts if isinstance(account, Mapping)]


def _gateway_upsert_account(accounts: list[dict[str, Any]], account: Mapping[str, Any]) -> list[dict[str, Any]]:
    account_id = str(account.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID)
    updated = False
    rows: list[dict[str, Any]] = []
    for existing in accounts:
        if str(existing.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID) == account_id:
            rows.append(dict(account))
            updated = True
        else:
            rows.append(existing)
    if not updated:
        rows.append(dict(account))
    return rows


def _gateway_secret_reference(*, service: str, account_id: str, secret_key: str, env_var: str) -> dict[str, Any]:
    normalized_account = service if account_id == DEFAULT_GATEWAY_ACCOUNT_ID else f"{service}-{account_id}"
    return {
        "reference_id": f"secret-{normalized_account}-{secret_key.replace('_', '-')}",
        "provider_id": _GATEWAY_SERVICE_BY_KEY[service]["adapterId"],
        "secret_name": secret_key,
        "secret_key": secret_key,
        "metadata": {"env_var": env_var},
    }


def _gateway_qr_matrix(scan_data: str) -> tuple[tuple[int, ...], ...]:
    try:
        import qrcode
    except Exception:
        return ()
    qr = qrcode.QRCode(border=2)
    qr.add_data(scan_data)
    qr.make(fit=True)
    return tuple(tuple(1 if cell else 0 for cell in row) for row in qr.get_matrix())


def _gateway_weixin_session_store(self) -> dict[str, dict[str, Any]]:
    store = getattr(self, "_gateway_weixin_qr_sessions", None)
    if not isinstance(store, dict):
        store = {}
        setattr(self, "_gateway_weixin_qr_sessions", store)
    return store


def _gateway_weixin_config_from_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    config = payload.get("config") if isinstance(payload.get("config"), Mapping) else payload
    return dict(config)


def _gateway_weixin_qr_payload(session_id: str, session_state: Mapping[str, Any], *, status: str = "wait") -> dict[str, Any]:
    scan_data = str(session_state.get("qrScanData") or "")
    return {
        "status": status,
        "service": "weixin",
        "action": "qr",
        "sessionId": session_id,
        "qrcode": session_state.get("qrcode"),
        "qrcodeUrl": session_state.get("qrcodeUrl"),
        "qrScanData": scan_data,
        "qrMatrix": _gateway_qr_matrix(scan_data) if scan_data else (),
        "expiresAt": session_state.get("expiresAt"),
    }


async def _fetch_weixin_qr(*, bot_type: str) -> dict[str, Any]:
    from apps.gateway import weixin_support as wx

    if not wx.check_weixin_requirements():
        raise RuntimeError("WeChat QR login requires aiohttp and cryptography. Install gateway WeChat dependencies first.")
    async with wx.aiohttp.ClientSession(trust_env=True, connector=wx._make_ssl_connector()) as session:
        return await wx._api_get(
            session,
            base_url=wx.ILINK_BASE_URL,
            endpoint=f"{wx.EP_GET_BOT_QR}?bot_type={bot_type}",
            timeout_ms=wx.QR_TIMEOUT_MS,
        )


async def _poll_weixin_qr(*, qrcode: str, base_url: str) -> dict[str, Any]:
    from apps.gateway import weixin_support as wx

    if not wx.check_weixin_requirements():
        raise RuntimeError("WeChat QR login requires aiohttp and cryptography. Install gateway WeChat dependencies first.")
    async with wx.aiohttp.ClientSession(trust_env=True, connector=wx._make_ssl_connector()) as session:
        return await wx._api_get(
            session,
            base_url=base_url,
            endpoint=f"{wx.EP_GET_QR_STATUS}?qrcode={qrcode}",
            timeout_ms=wx.QR_TIMEOUT_MS,
        )


def _gateway_weixin_qr_start(self, payload: Mapping[str, Any]) -> dict[str, Any]:
    qr_resp = asyncio.run(_fetch_weixin_qr(bot_type=str(payload.get("botType") or "3")))
    qrcode_value = str(qr_resp.get("qrcode") or "")
    qrcode_url = str(qr_resp.get("qrcode_img_content") or "")
    if not qrcode_value:
        raise ValueError("WeChat QR response did not include qrcode")
    session_id = f"weixin-qr-{int(time.time() * 1000)}"
    scan_data = qrcode_url if qrcode_url else qrcode_value
    expires_at = datetime.fromtimestamp(time.time() + 480, UTC).isoformat()
    session_state = {
        "qrcode": qrcode_value,
        "qrcodeUrl": qrcode_url,
        "qrScanData": scan_data,
        "baseUrl": "https://ilinkai.weixin.qq.com",
        "expiresAt": expires_at,
        "config": _gateway_weixin_config_from_payload(payload),
    }
    _gateway_weixin_session_store(self)[session_id] = session_state
    return _gateway_weixin_qr_payload(session_id, session_state, status="wait")


def _gateway_persist_weixin_credentials(self, credentials: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    from apps.gateway import weixin_support as wx

    database_path = self.repository.database_path
    state_dir = database_path.parent
    manifest = _gateway_manifest(state_dir)
    gateway_payload, adapters_payload, adapter_payload = _gateway_adapter_payload(manifest, "weixin")
    accounts = _gateway_accounts(adapter_payload)
    account_id = str(credentials.get("account_id") or credentials.get("ilink_bot_id") or "").strip()
    token = str(credentials.get("token") or credentials.get("bot_token") or "").strip()
    if not account_id or not token:
        raise ValueError("WeChat QR confirmation did not include account_id and token")
    wx.save_weixin_account(
        str(state_dir),
        account_id=account_id,
        token=token,
        base_url=str(credentials.get("base_url") or credentials.get("baseurl") or wx.ILINK_BASE_URL),
        user_id=str(credentials.get("user_id") or credentials.get("ilink_user_id") or ""),
    )
    control_payload = dict(adapter_payload.get("control")) if isinstance(adapter_payload.get("control"), Mapping) else {}
    allow_group_chats = bool(config.get("allowGroupChats")) if isinstance(config.get("allowGroupChats"), bool) else bool(control_payload.get("allow_group_chats") is True)
    account_payload: dict[str, Any] = {
        "account_id": account_id,
        "token": token,
        "base_url": str(credentials.get("base_url") or credentials.get("baseurl") or wx.ILINK_BASE_URL),
        "user_id": str(credentials.get("user_id") or credentials.get("ilink_user_id") or ""),
        "surface": "ilink",
        "enabled": bool(config.get("accountEnabled")) if isinstance(config.get("accountEnabled"), bool) else True,
    }
    event_path = str(config.get("eventPath") or config.get("event_path") or adapter_payload.get("event_path") or "/weixin/events").strip()
    if event_path:
        account_payload["event_path"] = event_path
    adapter_payload["accounts"] = _gateway_upsert_account(accounts, account_payload)
    adapter_payload["surface"] = "ilink"
    adapter_payload["enabled"] = bool(config.get("enabled")) if isinstance(config.get("enabled"), bool) else True
    adapter_payload["event_path"] = event_path
    control_payload.pop("default_elephant_id", None)
    control_payload.pop("default_session_id", None)
    control_payload.pop("auto_create_elephant", None)
    if allow_group_chats:
        control_payload["allow_group_chats"] = True
    else:
        control_payload.pop("allow_group_chats", None)
    if control_payload:
        adapter_payload["control"] = control_payload
    else:
        adapter_payload.pop("control", None)
    adapters_payload["weixin"] = adapter_payload
    gateway_payload["adapters"] = adapters_payload
    manifest["gateway"] = gateway_payload
    manifest_path = _write_manifest_to_config(state_dir, manifest)
    return {
        "profileManifestPath": str(manifest_path),
        "gateway": _gateway_view(self, state_dir),
    }


def _gateway_weixin_qr_poll(self, payload: Mapping[str, Any]) -> dict[str, Any]:
    session_id = str(payload.get("sessionId") or payload.get("session_id") or "").strip()
    store = _gateway_weixin_session_store(self)
    session_state = store.get(session_id)
    if not session_id or session_state is None:
        raise ValueError("WeChat QR session is missing or expired; start QR setup again")
    if time.time() > datetime.fromisoformat(str(session_state["expiresAt"])).timestamp():
        store.pop(session_id, None)
        return {**_gateway_weixin_qr_payload(session_id, session_state, status="expired"), "message": "QR session expired; start again."}
    status_resp = asyncio.run(_poll_weixin_qr(qrcode=str(session_state["qrcode"]), base_url=str(session_state.get("baseUrl") or "https://ilinkai.weixin.qq.com")))
    status = str(status_resp.get("status") or "wait")
    if status == "scaned_but_redirect":
        redirect_host = str(status_resp.get("redirect_host") or "").strip()
        if redirect_host:
            session_state["baseUrl"] = f"https://{redirect_host}"
        return {**_gateway_weixin_qr_payload(session_id, session_state, status=status), "message": "Redirected QR polling host."}
    if status == "confirmed":
        credentials = {
            "account_id": str(status_resp.get("ilink_bot_id") or ""),
            "token": str(status_resp.get("bot_token") or ""),
            "base_url": str(status_resp.get("baseurl") or "https://ilinkai.weixin.qq.com"),
            "user_id": str(status_resp.get("ilink_user_id") or ""),
        }
        persisted = _gateway_persist_weixin_credentials(self, credentials, dict(session_state.get("config") or {}))
        store.pop(session_id, None)
        return {
            **_gateway_weixin_qr_payload(session_id, session_state, status="confirmed"),
            "message": f"WeChat connected as {credentials['account_id']}",
            "credentials": {"account_id": credentials["account_id"], "base_url": credentials["base_url"], "user_id": credentials["user_id"]},
            **persisted,
        }
    if status == "need_verifycode":
        return {**_gateway_weixin_qr_payload(session_id, session_state, status=status), "message": "Scanned. Please confirm the verification code on your phone to continue."}
    return {**_gateway_weixin_qr_payload(session_id, session_state, status=status), "message": "Scan the QR with WeChat and confirm login."}


def _gateway_configure_service(self, payload: Mapping[str, Any], *, service: str) -> dict[str, Any]:
    spec = _GATEWAY_SERVICE_BY_KEY[service]
    config = payload.get("config") if isinstance(payload.get("config"), Mapping) else payload
    database_path = self.repository.database_path
    state_dir = database_path.parent
    gateway_dir = state_dir
    manifest = _gateway_manifest(state_dir)
    gateway_payload, adapters_payload, adapter_payload = _gateway_adapter_payload(manifest, service)
    accounts = _gateway_accounts(adapter_payload)
    account_id = str(config.get("accountId") or config.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID).strip() or DEFAULT_GATEWAY_ACCOUNT_ID
    existing_account = next((account for account in accounts if str(account.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID) == account_id), {})
    transport = str(config.get("transport") or existing_account.get("surface") or adapter_payload.get("surface") or spec.get("defaultTransport") or "").strip()
    if transport not in tuple(spec.get("transports", ())):
        raise ValueError(f"gateway {service} transport must be one of {', '.join(spec.get('transports', ())) }")
    enabled = bool(config.get("enabled")) if isinstance(config.get("enabled"), bool) else bool(adapter_payload.get("enabled") is not False)
    account_enabled = bool(config.get("accountEnabled")) if isinstance(config.get("accountEnabled"), bool) else bool(existing_account.get("enabled") is not False)
    event_path = str(config.get("eventPath") or config.get("event_path") or existing_account.get("event_path") or adapter_payload.get("event_path") or spec.get("eventPath") or "").strip()
    allow_group_chats = bool(config.get("allowGroupChats")) if isinstance(config.get("allowGroupChats"), bool) else bool((adapter_payload.get("control") if isinstance(adapter_payload.get("control"), Mapping) else {}).get("allow_group_chats") is True)
    secrets = config.get("secrets") if isinstance(config.get("secrets"), Mapping) else {}
    secret_fields = tuple(field for field in spec.get("secretFields", ()) if isinstance(field, Mapping))
    env_payload: dict[str, str] = {}
    secret_updates: dict[str, str] = {}
    for field in secret_fields:
        secret_key = str(field.get("key") or "").strip()
        default_env_var = str(field.get("defaultEnvVar") or "").strip()
        env_var = _gateway_account_secret_env_var(
            service=service,
            account={},
            account_id=account_id,
            secret_key=secret_key,
            default_env_var=default_env_var,
        )
        env_payload[secret_key] = env_var
        raw_secret = str(secrets.get(secret_key) or "").strip()
        if raw_secret:
            secret_updates[env_var] = raw_secret
    account_payload: dict[str, Any] = {
        "account_id": account_id,
        "surface": transport,
        "enabled": account_enabled,
    }
    if event_path:
        account_payload["event_path"] = event_path
    if service == "feishu":
        account_payload["secret_references"] = tuple(
            _gateway_secret_reference(service=service, account_id=account_id, secret_key=secret_key, env_var=env_var)
            for secret_key, env_var in env_payload.items()
        )
    elif env_payload:
        account_payload["env"] = env_payload
    for preserved_key in ("runtime", "token", "base_url", "user_id"):
        if preserved_key in existing_account and preserved_key not in account_payload:
            account_payload[preserved_key] = existing_account[preserved_key]
    allow_guild_ids = config.get("allowGuildIds")
    if isinstance(allow_guild_ids, list):
        account_payload["allow_guild_ids"] = [str(item).strip() for item in allow_guild_ids if str(item).strip()]
    allow_channel_ids = config.get("allowChannelIds")
    if isinstance(allow_channel_ids, list):
        account_payload["allow_channel_ids"] = [str(item).strip() for item in allow_channel_ids if str(item).strip()]
    adapter_payload["accounts"] = _gateway_upsert_account(accounts, account_payload)
    adapter_payload["surface"] = transport
    adapter_payload["enabled"] = enabled
    if event_path:
        adapter_payload["event_path"] = event_path
    control_payload = dict(adapter_payload.get("control")) if isinstance(adapter_payload.get("control"), Mapping) else {}
    control_payload.pop("default_elephant_id", None)
    control_payload.pop("default_session_id", None)
    control_payload.pop("auto_create_elephant", None)
    if allow_group_chats:
        control_payload["allow_group_chats"] = True
    else:
        control_payload.pop("allow_group_chats", None)
    if control_payload:
        adapter_payload["control"] = control_payload
    else:
        adapter_payload.pop("control", None)
    adapters_payload[service] = adapter_payload
    gateway_payload["adapters"] = adapters_payload
    manifest["gateway"] = gateway_payload
    manifest_path = _write_manifest_to_config(state_dir, manifest)
    secret_path = _persist_gateway_local_secret_env(gateway_dir, secret_updates)
    return {
        "status": "ok",
        "service": service,
        "action": "configured",
        "profileManifestPath": str(manifest_path),
        "secretPath": str(secret_path) if secret_path is not None else None,
        "gateway": _gateway_view(self, state_dir),
    }


def _gateway_remove_account_credentials(gateway_dir: Path, *, service: str, account_id: str) -> None:
    """Remove persisted credential files for the given service account."""
    # WeChat stores credentials in gateway_dir/weixin/accounts/{account_id}.json
    # Other services may use similar patterns in the future.
    account_file = gateway_dir / service / "accounts" / f"{account_id}.json"
    if account_file.is_file():
        try:
            account_file.unlink()
        except OSError:
            pass
    # Also remove the sync buffer file if present
    sync_file = gateway_dir / service / "accounts" / f"{account_id}.sync.json"
    if sync_file.is_file():
        try:
            sync_file.unlink()
        except OSError:
            pass


def _gateway_cleanup_stale_runtime_files(gateway_dir: Path, *, service: str) -> None:
    """Update runtime.json files to 'stopped' when the recorded PID is no longer alive.

    Applies to both 'running' and 'starting' records — a process that never
    reached the running state should not linger as 'starting' forever.
    """
    for path in gateway_dir.glob(f"{service}*.runtime.json"):
        if not path.is_file():
            continue
        try:
            content = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(content, dict):
            continue
        recorded = str(content.get("status") or "").lower()
        if recorded not in ("running", "starting"):
            continue
        pid = content.get("pid")
        if pid is None:
            # No pid on a 'starting' record is ambiguous; leave it alone so a
            # freshly-launched process has a moment to write its pid.
            continue
        try:
            pid_int = int(pid)
            if pid_int > 0:
                os.kill(pid_int, 0)
                # PID is alive — leave it alone
                continue
        except (ValueError, TypeError):
            pass
        except OSError:
            pass
        # PID is not alive — mark as stopped
        content["status"] = "stopped"
        content["stopped_at"] = datetime.now(UTC).isoformat()
        content["last_error"] = f"process exited unexpectedly (was {recorded})"
        try:
            path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
    # Also clean up stale .pid files
    for pid_path in gateway_dir.glob(f"{service}*.pid"):
        if not pid_path.is_file():
            continue
        try:
            pid_int = int(pid_path.read_text(encoding="utf-8").strip())
            if pid_int > 0:
                os.kill(pid_int, 0)
                continue  # still alive
        except (OSError, ValueError):
            pass
        try:
            pid_path.unlink()
        except OSError:
            pass


def _gateway_remove_service_account(self, payload: Mapping[str, Any], *, service: str) -> dict[str, Any]:
    config = payload.get("config") if isinstance(payload.get("config"), Mapping) else payload
    database_path = self.repository.database_path
    state_dir = database_path.parent
    gateway_dir = state_dir
    manifest = _gateway_manifest(state_dir)
    gateway_payload, adapters_payload, adapter_payload = _gateway_adapter_payload(manifest, service)
    accounts = _gateway_accounts(adapter_payload)
    requested_id = str(config.get("accountId") or config.get("account_id") or "").strip()

    def _row_id(row: Mapping[str, Any]) -> str:
        return str(row.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID)

    existing_ids = [_row_id(account) for account in accounts]
    # Resolve account_id with tolerant fallbacks:
    # 1. If requested_id matches an existing account, use it.
    # 2. Else if there is exactly one configured account, remove it (user
    #    clearly intended to clear the service).
    # 3. Else if requested_id is empty and a primary fallback exists, use the
    #    default id; but if that doesn't match either, fail loudly.
    resolved_id: str | None = None
    reason = ""
    if requested_id and requested_id in existing_ids:
        resolved_id = requested_id
    elif not requested_id and DEFAULT_GATEWAY_ACCOUNT_ID in existing_ids:
        resolved_id = DEFAULT_GATEWAY_ACCOUNT_ID
    elif len(accounts) == 1:
        resolved_id = existing_ids[0]
        if requested_id and requested_id != resolved_id:
            reason = f"requested accountId {requested_id!r} not found; removed the only configured account {resolved_id!r}"
    else:
        # Ambiguous: either multiple accounts and id didn't match, or zero accounts.
        if not accounts:
            return {
                "status": "ok",
                "service": service,
                "action": "removed",
                "accountId": requested_id or DEFAULT_GATEWAY_ACCOUNT_ID,
                "removedAccountId": None,
                "remainingAccounts": [],
                "reason": "no accounts configured",
                "profileManifestPath": "",
                "secretPath": None,
                "gateway": _gateway_view(self, state_dir),
            }
        return {
            "status": "failed",
            "service": service,
            "action": "remove",
            "accountId": requested_id,
            "reason": f"accountId {requested_id!r} not found",
            "remainingAccounts": existing_ids,
            "gateway": _gateway_view(self, state_dir),
        }

    account_id = resolved_id
    removed = next((account for account in accounts if _row_id(account) == account_id), {})
    remaining = [account for account in accounts if _row_id(account) != account_id]
    secret_env_vars = tuple(
        _gateway_account_secret_env_var(
            service=service,
            account=removed,
            account_id=account_id,
            secret_key=str(field.get("key") or ""),
            default_env_var=str(field.get("defaultEnvVar") or ""),
        )
        for field in _GATEWAY_SERVICE_BY_KEY[service].get("secretFields", ())
        if isinstance(field, Mapping)
    )
    secret_path = _delete_gateway_local_secret_env(gateway_dir, secret_env_vars)
    if remaining:
        adapter_payload["accounts"] = remaining
        adapters_payload[service] = adapter_payload
    else:
        adapters_payload.pop(service, None)
    if adapters_payload:
        gateway_payload["adapters"] = adapters_payload
        manifest["gateway"] = gateway_payload
    else:
        # Signal to _write_manifest_to_config that the persisted gateway
        # section should be deleted, not left alone. An explicit None
        # means "drop this section", whereas popping the key would be
        # interpreted as "caller did not want to touch gateway".
        manifest["gateway"] = None
    manifest_path = _write_manifest_to_config(state_dir, manifest)
    # Clean up persisted credential files (e.g. weixin/accounts/{account_id}.json)
    # so a fresh QR scan can re-create them without stale token interference.
    _gateway_remove_account_credentials(gateway_dir, service=service, account_id=account_id)
    # If this was the last account for the service, sweep the accounts directory
    # for any leftover json files so nothing resurrects the account on restart.
    if not remaining:
        accounts_dir = gateway_dir / service / "accounts"
        if accounts_dir.is_dir():
            for leftover in accounts_dir.glob("*.json"):
                try:
                    leftover.unlink()
                except OSError:
                    pass
    # Clean up stale runtime files so the dashboard does not report a phantom "running" state.
    _gateway_cleanup_stale_runtime_files(gateway_dir, service=service)
    return {
        "status": "ok",
        "service": service,
        "action": "removed",
        "accountId": account_id,
        "removedAccountId": account_id,
        "remainingAccounts": [_row_id(row) for row in remaining],
        "reason": reason,
        "profileManifestPath": str(manifest_path),
        "secretPath": str(secret_path) if secret_path is not None else None,
        "gateway": _gateway_view(self, state_dir),
    }


def gateway_action(self, payload: Mapping[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action") or "status").strip().lower()
    service = str(payload.get("service") or "feishu").strip().lower()
    if service not in _GATEWAY_SERVICE_BY_KEY:
        raise ValueError("gateway service must be one of " + ", ".join(_GATEWAY_SERVICE_BY_KEY))
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
        raise ValueError("gateway action must be status, doctor, start, stop, restart, configure, remove, qr-start, or qr-poll")
    database_path = self.repository.database_path
    state_dir = database_path.parent
    command = [sys.executable, "-m", "apps.gateway", service, action]
    account_id = str(payload.get("accountId") or payload.get("account_id") or "").strip()
    if account_id:
        command.append(account_id)
    transport = str(payload.get("transport") or payload.get("runtimeTarget") or "").strip()
    if transport:
        command.extend(["--transport", transport])
    command.extend([
        "--state-dir",
        str(state_dir),
        "--cli-state-dir",
        str(state_dir),
    ])
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
        "globalConfigYaml": read_global_config_text(config_path, fallback=global_config),
        "globalConfigSchema": global_config_schema(),
    }


def _profile_overrides(state_dir: Path, key: str) -> Mapping[str, Any]:
    manifest = _load_manifest_from_config(state_dir)
    if not isinstance(manifest, Mapping):
        return {}
    value = manifest.get(key)
    return value if isinstance(value, Mapping) else {}


def _override_enabled(overrides: Mapping[str, Any], item_id: str, default: bool) -> bool:
    value = overrides.get(item_id)
    if isinstance(value, Mapping) and isinstance(value.get("enabled"), bool):
        return bool(value["enabled"])
    return default


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
        transport = str(server.get("transport") or ("http" if url else "stdio")).strip() or "stdio"
        env = _mapping_rows({"env": server.get("env")}).get("env", {}) if isinstance(server.get("env"), Mapping) else {}
        headers = _mapping_rows({"headers": server.get("headers")}).get("headers", {}) if isinstance(server.get("headers"), Mapping) else {}
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
        availability_reason = "" if available else "server command or url is not configured"
        for tool_name, tool in sorted(tools.items()):
            tool_key = _mcp_tool_key(server_id, tool_name)
            default_enabled = bool(tool.get("enabled", True))
            enabled = _override_enabled(overrides, tool_key, default_enabled)
            schema = dict(tool.get("schema", {})) if isinstance(tool.get("schema"), Mapping) else {}
            metadata = dict(tool.get("metadata", {})) if isinstance(tool.get("metadata"), Mapping) else {}
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
                    "displayName": str(tool.get("display_name") or tool_name).strip() or tool_name,
                    "description": str(tool.get("description") or "").strip(),
                    "family": str(tool.get("family") or "mcp").strip() or "mcp",
                    "enabled": enabled,
                    "defaultEnabled": default_enabled,
                    "override": overrides.get(tool_key),
                    "available": available,
                    "availabilityReason": availability_reason,
                    "riskClass": str(tool.get("risk_class") or "medium").strip() or "medium",
                    "approvalClass": str(tool.get("approval_class") or "standard").strip() or "standard",
                    "readsState": bool(tool.get("reads_state", False)),
                    "writesState": bool(tool.get("writes_state", False)),
                    "touchesNetwork": bool(tool.get("touches_network", False)),
                    "touchesSecrets": bool(tool.get("touches_secrets", False)),
                    "requiredFields": tuple(str(item) for item in schema.get("required", []) if str(item).strip()) if isinstance(schema.get("required"), list) else (),
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


def _load_operator_global_config(database_path: Path) -> tuple[Path, Path, dict[str, Any]]:
    state_dir = database_path.parent
    config_path = global_config_path_for_state_dir(database_path.parent)
    config = load_global_config(config_path, state_dir=state_dir)
    return state_dir, config_path, dict(config)


def _sync_operator_mcp_runtime(app: Any, *, config_path: Path, config: Mapping[str, Any]) -> str:
    runtime = getattr(app, "tool_runtime", None)
    if runtime is None:
        return "tool_runtime_unavailable"
    sync_custom_mcp_tools(runtime, config_path=config_path, config=config, cwd=Path.cwd())
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
    env = {str(key): str(value) for key, value in _mapping_rows({"env": server.get("env")}).get("env", {}).items()}
    if env:
        cleaned["env"] = env
    headers = {
        str(key): str(value)
        for key, value in _mapping_rows({"headers": server.get("headers")}).get("headers", {}).items()
    }
    if headers:
        cleaned["headers"] = headers
    tools = _mapping_rows(server.get("tools"))
    if tools:
        cleaned["tools"] = tools
    return cleaned


def _apply_mcp_server_payload(server: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
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


def _apply_mcp_tool_payload(tool: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
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
    runtime_status = _sync_operator_mcp_runtime(self, config_path=config_path, config=next_config)
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
    runtime_status = _sync_operator_mcp_runtime(self, config_path=config_path, config=next_config)
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
    runtime_status = _sync_operator_mcp_runtime(self, config_path=config_path, config=next_config)
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
        raise ValueError("Verify connection first so Elephant Agent can sync at least one MCP tool.")
    servers = _mcp_servers(config)
    server_exists = server_id in servers
    existing_server = dict(servers.get(server_id, {}))
    next_server = _apply_mcp_server_payload(existing_server, payload)
    transport = str(next_server.get("transport") or ("http" if str(next_server.get("url") or "").strip() else "stdio")).strip().lower() or "stdio"
    headers = _mapping_rows({"headers": next_server.get("headers")}).get("headers", {}) if isinstance(next_server.get("headers"), Mapping) else {}
    existing_tools = _mapping_rows(existing_server.get("tools"))
    merged_tools = _merge_discovered_mcp_tools(existing_tools, discovered_tools, transport=transport, headers=headers)
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
    runtime_status = _sync_operator_mcp_runtime(self, config_path=config_path, config=next_config)
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
    runtime_status = _sync_operator_mcp_runtime(self, config_path=config_path, config=next_config)
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
    runtime_status = _sync_operator_mcp_runtime(self, config_path=config_path, config=next_config)
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
        "headers": _string_object_payload(payload.get("headers") or {}, field="headers"),
    }


def _mcp_discovered_tool_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in payload.get("tools", ()):
        if not isinstance(item, Mapping):
            continue
        schema = dict(item.get("inputSchema", {})) if isinstance(item.get("inputSchema"), Mapping) else {}
        rows.append(
            {
                "name": str(item.get("name") or "").strip(),
                "description": str(item.get("description") or "").strip(),
                "inputSchema": schema,
                "enabled": bool(item.get("enabled", True)),
                "requiredFields": tuple(str(field) for field in schema.get("required", []) if str(field).strip()) if isinstance(schema.get("required"), list) else (),
                "options": [option for option in item.get("options", []) if isinstance(option, Mapping)] if isinstance(item.get("options"), list) else [],
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
        schema = dict(discovered.get("inputSchema", {})) if isinstance(discovered.get("inputSchema"), Mapping) else {}
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
        env={str(key): str(value) for key, value in dict(probe.get("env") or {}).items()},
        headers={str(key): str(value) for key, value in dict(probe.get("headers") or {}).items()},
        cwd=Path(__file__).resolve().parents[2],
    )
    tools = _mcp_discovered_tool_rows({"tools": result.get("tools", ())})
    error_text = str(result.get("error") or "").strip()
    status = str(result.get("status") or ("failed" if error_text else "ok")).strip() or "failed"
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
    runtime_status = _sync_operator_mcp_runtime(self, config_path=config_path, config=config)
    next_settings = _settings(state_dir, database_path)
    return {
        "status": "ok",
        "globalConfigPath": str(config_path),
        "runtimeStatus": runtime_status,
        "settings": next_settings,
    }


def set_console_item_enabled(self, *, kind: str, item_id: str, enabled: bool) -> dict[str, Any]:
    database_path = self.repository.database_path
    state_dir = database_path.parent
    config_path = global_config_path_for_state_dir(database_path.parent)
    manifest = _load_manifest_from_config(state_dir)
    if not isinstance(manifest, Mapping):
        manifest = {}
    section = "skill_overrides" if kind == "skill" else "tool_overrides"
    overrides = dict(manifest.get(section, {})) if isinstance(manifest.get(section), Mapping) else {}
    overrides[item_id] = {"enabled": bool(enabled)}
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
