"""CLI wiring for the Elephant operator tool surface."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
from typing import Any

from apps.daemon_command import daemon_is_running, daemon_pid_path, daemon_record_path, restart_daemon
from packages.operator import OperatorRuntimeManagementSurface


def build_cli_operator_surface(runtime: Any) -> OperatorRuntimeManagementSurface:
    cli_state_dir = runtime.paths.state_dir
    daemon_state_dir = cli_state_dir

    def _set_default_provider(parameters: Mapping[str, Any]) -> Mapping[str, Any]:
        provider_id = _required(parameters, "provider_id")
        runtime.set_default_provider(
            provider_id=provider_id,
            base_url=_optional(parameters, "base_url"),
            model_id=_optional(parameters, "model_id") or _optional(parameters, "default_model"),
            auth_method=_optional(parameters, "auth_method"),
            provider_kind=_optional(parameters, "provider_kind"),
            api_key=_optional(parameters, "api_key"),
            secret_env_var=_optional(parameters, "secret_env_var"),
            context_window_tokens=_optional_int(parameters, "context_window_tokens"),
            context_window_mode=_optional(parameters, "context_window_mode"),
            reasoning_effort=_optional(parameters, "reasoning_effort"),
            extra_headers=_optional_mapping(parameters, "extra_headers"),
        )
        return {"active_provider": dict(runtime.provider_summary())}

    return OperatorRuntimeManagementSurface(
        surface_label="cli",
        provider_summary=lambda: dict(runtime.provider_summary()),
        provider_doctor=lambda deep: dict(runtime.provider_doctor(deep=deep)),
        set_default_provider=_set_default_provider,
        daemon_status=lambda probe: daemon_status_record(daemon_state_dir, probe=probe),
        daemon_restart=lambda parameters: restart_daemon_from_operator_params(
            daemon_state_dir,
            cli_state_dir,
            parameters,
        ),
        skill_management=runtime,
        tool_runtime=lambda: runtime.tool_runtime,
        security_policy=lambda: runtime.security_policy,
    )


def _required(parameters: Mapping[str, Any], key: str) -> str:
    value = _optional(parameters, key)
    if value is None:
        raise ValueError(f"{key} is required")
    return value


def _optional(parameters: Mapping[str, Any], key: str) -> str | None:
    value = parameters.get(key) or parameters.get(_camel_case(key))
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(parameters: Mapping[str, Any], key: str) -> int | None:
    value = _optional(parameters, key)
    if value is None:
        return None
    return int(value.replace(",", ""))


def _optional_mapping(parameters: Mapping[str, Any], key: str) -> Mapping[str, str] | None:
    value = parameters.get(key) or parameters.get(_camel_case(key))
    if not isinstance(value, Mapping):
        return None
    return {str(item_key): str(item_value) for item_key, item_value in value.items()}


def _camel_case(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


__all__ = ["build_cli_operator_surface"]


def daemon_status_record(state_dir: Path, *, probe: bool) -> dict[str, Any]:
    pid_path = daemon_pid_path(state_dir)
    record_path = daemon_record_path(state_dir)
    record = _read_json_record(record_path)
    pid = _read_pid(pid_path) or _coerce_int(record.get("pid"))
    running = daemon_is_running(state_dir) if probe or record_path.exists() else _pid_is_running(pid)
    status = "running" if running else str(record.get("status") or "stopped")
    return {
        "status": status,
        "running": running,
        "pid": pid,
        "state_dir": str(state_dir),
        "pid_path": str(pid_path),
        "record_path": str(record_path),
        "log_path": str(record.get("log_path") or state_dir / "daemon.log"),
        "host": record.get("host") or "0.0.0.0",
        "port": record.get("port") or 8900,
        "started_at": record.get("started_at") or "",
        "stopped_at": record.get("stopped_at") or "",
        "last_error": record.get("last_error") or "",
        "record_status": record.get("status") or "",
    }


def restart_daemon_from_operator_params(
    state_dir: Path,
    cli_state_dir: Path,
    parameters: Mapping[str, Any],
) -> dict[str, Any]:
    before = daemon_status_record(state_dir, probe=True)
    rc = restart_daemon(
        state_dir,
        cli_state_dir,
        host=str(parameters.get("host") or before.get("host") or "0.0.0.0"),
        port=_coerce_int(parameters.get("port")) or _coerce_int(before.get("port")) or 8900,
        log_level=str(parameters.get("log_level") or parameters.get("logLevel") or "INFO"),
        timeout=float(parameters.get("timeout") or parameters.get("timeout_seconds") or 10.0),
        force=_coerce_bool(parameters.get("force"), default=False),
    )
    after = daemon_status_record(state_dir, probe=True)
    return {
        "status": "ok" if rc == 0 else "failed",
        "exit_code": rc,
        "before": before,
        "after": after,
    }


def _read_json_record(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _read_pid(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _pid_is_running(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _coerce_int(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _coerce_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "force"}
