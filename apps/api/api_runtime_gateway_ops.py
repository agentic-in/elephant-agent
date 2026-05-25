"""Gateway operator helpers for the API runtime console surface."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import logging
from pathlib import Path
from typing import Any
import asyncio
import json
import os
import re
import time

from .api_runtime_console_config import (
    _load_manifest_from_config,
    _logs,
    _read_json_file,
    _read_text_file,
    _write_manifest_to_config,
)

LOGGER = logging.getLogger(__name__)


GATEWAY_LOCAL_SECRET_ENV_FILE = "gateway-local-secrets.json"
DEFAULT_GATEWAY_ACCOUNT_ID = "default"

from .api_runtime_gateway_catalog import _GATEWAY_SERVICE_BY_KEY, _GATEWAY_SERVICE_SPECS


def _gateway_local_secret_env_path(gateway_dir: Path) -> Path:
    return gateway_dir / GATEWAY_LOCAL_SECRET_ENV_FILE


def _load_gateway_local_secret_env(gateway_dir: Path) -> dict[str, str]:
    payload = _read_json_file(_gateway_local_secret_env_path(gateway_dir))
    if not isinstance(payload, Mapping):
        return {}
    return {
        str(key): str(value) for key, value in payload.items() if str(value).strip()
    }


def _persist_gateway_local_secret_env(
    gateway_dir: Path, updates: Mapping[str, str]
) -> Path | None:
    filtered = {
        str(key): str(value).strip()
        for key, value in updates.items()
        if str(value).strip()
    }
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


def _delete_gateway_local_secret_env(
    gateway_dir: Path, keys: tuple[str, ...]
) -> Path | None:
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
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
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
    return (
        re.sub(r"[^A-Za-z0-9]+", "_", account_id.strip()).strip("_").upper()
        or "DEFAULT"
    )


def _default_gateway_secret_env_var(
    service: str, account_id: str, secret_key: str, default_env_var: str
) -> str:
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
            if (
                not isinstance(ref, Mapping)
                or str(ref.get("secret_key") or "") != secret_key
            ):
                continue
            metadata = ref.get("metadata")
            if isinstance(metadata, Mapping):
                text = str(metadata.get("env_var") or "").strip()
                if text:
                    return text
    return _default_gateway_secret_env_var(
        service, account_id, secret_key, default_env_var
    )


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
    gateway_manifest = (
        manifest.get("gateway") if isinstance(manifest, Mapping) else None
    )
    adapters = (
        gateway_manifest.get("adapters")
        if isinstance(gateway_manifest, Mapping)
        else None
    )
    adapters_payload = adapters if isinstance(adapters, Mapping) else {}
    local_secrets = _load_gateway_local_secret_env(gateway_dir)
    rows: list[dict[str, Any]] = []
    for spec in _GATEWAY_SERVICE_SPECS:
        service = str(spec["service"])
        adapter = adapters_payload.get(service)
        adapter_payload = adapter if isinstance(adapter, Mapping) else {}
        account_rows = (
            [
                dict(item)
                for item in adapter_payload.get("accounts", ())
                if isinstance(item, Mapping)
            ]
            if isinstance(adapter_payload.get("accounts"), (list, tuple))
            else []
        )
        primary_account = account_rows[0] if account_rows else {}
        account_id = str(
            primary_account.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID
        )
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
            secret_fields.append(
                {
                    "key": secret_key,
                    "label": str(field.get("label") or secret_key),
                    "hasValue": bool(local_secrets.get(env_var)),
                }
            )
        service_runtime_files = [
            row for row in runtime_files if _gateway_runtime_service_key(row) == service
        ]
        control = (
            adapter_payload.get("control")
            if isinstance(adapter_payload.get("control"), Mapping)
            else {}
        )
        configured_transport = str(
            primary_account.get("surface")
            or adapter_payload.get("surface")
            or spec.get("defaultTransport")
            or ""
        )
        enabled = adapter_payload.get("enabled") is True
        runtime_states = [_gateway_runtime_status(row) for row in service_runtime_files]
        is_running = any(state == "running" for state in runtime_states)
        is_starting = (not is_running) and any(
            state == "starting" for state in runtime_states
        )
        last_error = ""
        for row in service_runtime_files:
            content = row.get("content") if isinstance(row, Mapping) else None
            if isinstance(content, Mapping):
                err = str(content.get("last_error") or "").strip()
                if err:
                    last_error = err
                    break
        rows.append(
            {
                **{key: value for key, value in spec.items() if key != "secretFields"},
                "enabled": enabled,
                "configured": bool(account_rows),
                "configuredTransport": configured_transport,
                "accountCount": len(account_rows),
                "accounts": tuple(account_rows),
                "primaryAccountId": account_id,
                "eventPath": str(
                    primary_account.get("event_path")
                    or adapter_payload.get("event_path")
                    or spec.get("eventPath")
                    or ""
                ),
                "allowGroupChats": bool(control.get("allow_group_chats") is True),
                "secretFields": tuple(secret_fields),
                "runtimeFiles": tuple(service_runtime_files),
                "running": is_running,
                "starting": is_starting,
                "lastError": last_error,
                "runtimeStatus": (
                    "running"
                    if is_running
                    else (
                        "starting"
                        if is_starting
                        else "failed" if last_error else "stopped"
                    )
                ),
                "runtimeSource": "files" if service_runtime_files else "config",
                "runtimeDetails": {},
                "startedAt": None,
            }
        )
    return rows


def _gateway_runtime_files(gateway_dir: Path) -> list[dict[str, Any]]:
    runtime_files: list[dict[str, Any]] = []
    for path in sorted(
        (*gateway_dir.glob("*.runtime.json"), *gateway_dir.glob("*.pid"))
    ):
        if not path.is_file():
            continue
        runtime_files.append(
            {
                "name": path.name,
                "path": str(path),
                "updatedAt": datetime.fromtimestamp(
                    path.stat().st_mtime, UTC
                ).isoformat(),
                "content": (
                    _read_json_file(path)
                    if path.suffix == ".json"
                    else _read_text_file(path, max_chars=4_000)
                ),
            }
        )
    return runtime_files


def _gateway_runtime_bridge_services(
    runtime_bridge: Any | None,
) -> dict[str, dict[str, Any]]:
    if runtime_bridge is None or not hasattr(
        runtime_bridge, "gateway_runtime_snapshot"
    ):
        return {}
    try:
        snapshot = runtime_bridge.gateway_runtime_snapshot()
    except Exception:
        LOGGER.warning(
            "failed to read gateway runtime snapshot for API console", exc_info=True
        )
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
        if status_text not in {
            "idle",
            "running",
            "starting",
            "failed",
            "stopped",
            "skipped",
        }:
            status_text = "stopped"
        details = raw.get("details")
        rows[str(key)] = {
            "service": str(raw.get("service") or key).strip() or str(key),
            "status": status_text,
            "startedAt": str(
                raw.get("startedAt") or raw.get("started_at") or ""
            ).strip()
            or None,
            "lastError": str(
                raw.get("lastError") or raw.get("last_error") or ""
            ).strip(),
            "details": dict(details) if isinstance(details, Mapping) else {},
            "runtimeSource": str(raw.get("runtimeSource") or "daemon").strip()
            or "daemon",
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
                "runtimeDetails": (
                    bridge_row.get("details")
                    if isinstance(bridge_row.get("details"), Mapping)
                    else {}
                ),
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
    services = _gateway_services(
        gateway_dir=gateway_dir, state_dir=state_dir, runtime_files=runtime_files
    )
    services = _merge_gateway_runtime(services, runtime_bridge=runtime_bridge)
    return {
        "gatewayDir": str(gateway_dir),
        "exists": gateway_dir.exists(),
        "runtimeFiles": runtime_files,
        "logs": _logs(gateway_dir) if gateway_dir.exists() else [],
        "services": services,
        "configuredServiceCount": sum(
            1 for service in services if service["configured"]
        ),
        "runningServiceCount": sum(1 for service in services if service["running"]),
        "startingServiceCount": sum(
            1 for service in services if service.get("starting")
        ),
        "runtimeBridgeConnected": bool(
            _gateway_runtime_bridge_services(runtime_bridge)
        ),
    }


def _gateway_manifest(state_dir: Path) -> dict[str, Any]:
    manifest = _load_manifest_from_config(state_dir)
    return dict(manifest) if isinstance(manifest, Mapping) else {}


def _gateway_adapter_payload(
    manifest: Mapping[str, Any], service: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    gateway_payload = (
        manifest.get("gateway") if isinstance(manifest.get("gateway"), Mapping) else {}
    )
    adapters_payload = (
        gateway_payload.get("adapters")
        if isinstance(gateway_payload.get("adapters"), Mapping)
        else {}
    )
    adapter_payload = (
        adapters_payload.get(service)
        if isinstance(adapters_payload.get(service), Mapping)
        else {}
    )
    return dict(gateway_payload), dict(adapters_payload), dict(adapter_payload)


def _gateway_accounts(adapter_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    accounts = adapter_payload.get("accounts")
    if not isinstance(accounts, (list, tuple)):
        return []
    return [dict(account) for account in accounts if isinstance(account, Mapping)]


def _gateway_upsert_account(
    accounts: list[dict[str, Any]], account: Mapping[str, Any]
) -> list[dict[str, Any]]:
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


def _gateway_secret_reference(
    *, service: str, account_id: str, secret_key: str, env_var: str
) -> dict[str, Any]:
    normalized_account = (
        service
        if account_id == DEFAULT_GATEWAY_ACCOUNT_ID
        else f"{service}-{account_id}"
    )
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
        LOGGER.warning(
            "qrcode package unavailable for gateway QR matrix", exc_info=True
        )
        return ()
    qr = qrcode.QRCode(border=2)
    qr.add_data(scan_data)
    qr.make(fit=True)
    return tuple(tuple(1 if cell else 0 for cell in row) for row in qr.get_matrix())


def _gateway_configure_service(
    self, payload: Mapping[str, Any], *, service: str
) -> dict[str, Any]:
    spec = _GATEWAY_SERVICE_BY_KEY[service]
    config = (
        payload.get("config") if isinstance(payload.get("config"), Mapping) else payload
    )
    database_path = self.repository.database_path
    state_dir = database_path.parent
    gateway_dir = state_dir
    manifest = _gateway_manifest(state_dir)
    gateway_payload, adapters_payload, adapter_payload = _gateway_adapter_payload(
        manifest, service
    )
    accounts = _gateway_accounts(adapter_payload)
    account_id = (
        str(
            config.get("accountId")
            or config.get("account_id")
            or DEFAULT_GATEWAY_ACCOUNT_ID
        ).strip()
        or DEFAULT_GATEWAY_ACCOUNT_ID
    )
    existing_account = next(
        (
            account
            for account in accounts
            if str(account.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID)
            == account_id
        ),
        {},
    )
    transport = str(
        config.get("transport")
        or existing_account.get("surface")
        or adapter_payload.get("surface")
        or spec.get("defaultTransport")
        or ""
    ).strip()
    if transport not in tuple(spec.get("transports", ())):
        raise ValueError(
            f"gateway {service} transport must be one of {', '.join(spec.get('transports', ())) }"
        )
    enabled = (
        bool(config.get("enabled"))
        if isinstance(config.get("enabled"), bool)
        else bool(adapter_payload.get("enabled") is not False)
    )
    account_enabled = (
        bool(config.get("accountEnabled"))
        if isinstance(config.get("accountEnabled"), bool)
        else bool(existing_account.get("enabled") is not False)
    )
    event_path = str(
        config.get("eventPath")
        or config.get("event_path")
        or existing_account.get("event_path")
        or adapter_payload.get("event_path")
        or spec.get("eventPath")
        or ""
    ).strip()
    allow_group_chats = (
        bool(config.get("allowGroupChats"))
        if isinstance(config.get("allowGroupChats"), bool)
        else bool(
            (
                adapter_payload.get("control")
                if isinstance(adapter_payload.get("control"), Mapping)
                else {}
            ).get("allow_group_chats")
            is True
        )
    )
    secrets = (
        config.get("secrets") if isinstance(config.get("secrets"), Mapping) else {}
    )
    secret_fields = tuple(
        field for field in spec.get("secretFields", ()) if isinstance(field, Mapping)
    )
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
            _gateway_secret_reference(
                service=service,
                account_id=account_id,
                secret_key=secret_key,
                env_var=env_var,
            )
            for secret_key, env_var in env_payload.items()
        )
    elif env_payload:
        account_payload["env"] = env_payload
    for preserved_key in ("runtime", "token", "base_url", "user_id"):
        if preserved_key in existing_account and preserved_key not in account_payload:
            account_payload[preserved_key] = existing_account[preserved_key]
    allow_guild_ids = config.get("allowGuildIds")
    if isinstance(allow_guild_ids, list):
        account_payload["allow_guild_ids"] = [
            str(item).strip() for item in allow_guild_ids if str(item).strip()
        ]
    allow_channel_ids = config.get("allowChannelIds")
    if isinstance(allow_channel_ids, list):
        account_payload["allow_channel_ids"] = [
            str(item).strip() for item in allow_channel_ids if str(item).strip()
        ]
    adapter_payload["accounts"] = _gateway_upsert_account(accounts, account_payload)
    adapter_payload["surface"] = transport
    adapter_payload["enabled"] = enabled
    if event_path:
        adapter_payload["event_path"] = event_path
    control_payload = (
        dict(adapter_payload.get("control"))
        if isinstance(adapter_payload.get("control"), Mapping)
        else {}
    )
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


def _gateway_remove_account_credentials(
    gateway_dir: Path, *, service: str, account_id: str
) -> None:
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
            path.write_text(
                json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8"
            )
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


def _gateway_remove_service_account(
    self, payload: Mapping[str, Any], *, service: str
) -> dict[str, Any]:
    config = (
        payload.get("config") if isinstance(payload.get("config"), Mapping) else payload
    )
    database_path = self.repository.database_path
    state_dir = database_path.parent
    gateway_dir = state_dir
    manifest = _gateway_manifest(state_dir)
    gateway_payload, adapters_payload, adapter_payload = _gateway_adapter_payload(
        manifest, service
    )
    accounts = _gateway_accounts(adapter_payload)
    requested_id = str(
        config.get("accountId") or config.get("account_id") or ""
    ).strip()

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
    removed = next(
        (account for account in accounts if _row_id(account) == account_id), {}
    )
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
    _gateway_remove_account_credentials(
        gateway_dir, service=service, account_id=account_id
    )
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


__all__ = [
    "DEFAULT_GATEWAY_ACCOUNT_ID",
    "GATEWAY_LOCAL_SECRET_ENV_FILE",
    "_GATEWAY_SERVICE_BY_KEY",
    "_gateway",
    "_gateway_view",
    "_gateway_runtime_status",
    "_gateway_runtime_is_running",
    "_gateway_runtime_is_starting",
    "_pid_is_alive",
    "_gateway_configure_service",
    "_gateway_remove_service_account",
]
