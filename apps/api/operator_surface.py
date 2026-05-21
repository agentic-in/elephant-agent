"""API wiring for the Elephant operator tool surface."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
from typing import Any

from apps.daemon_command import daemon_is_running, daemon_pid_path, daemon_record_path, restart_daemon
from packages.operator import OperatorRuntimeManagementSurface


def build_api_operator_surface(
    app: Any,
    *,
    skill_management: Any,
) -> OperatorRuntimeManagementSurface:
    cli_state_dir = app.repository.database_path.parent
    daemon_state_dir = cli_state_dir

    def _doctor(deep: bool) -> Mapping[str, Any]:
        if deep:
            return dict(app.doctor_provider())
        return {"active_provider": dict(app.model_provider.describe()), "checks": ()}

    def _set_default_provider(parameters: Mapping[str, Any]) -> Mapping[str, Any]:
        payload = provider_profile_payload_from_operator_params(parameters)
        result = dict(app.set_default_provider(payload))
        api_key = str(parameters.get("api_key") or parameters.get("apiKey") or "").strip()
        references = payload.get("secret_references")
        if api_key and isinstance(references, list) and references:
            reference = references[0]
            app.create_provider_key(
                {
                    "profileId": payload["profile_id"],
                    "providerId": payload["provider_id"],
                    "referenceId": reference["reference_id"],
                    "secretName": reference.get("secret_name", "api_token"),
                    "secretKey": reference.get("secret_key", "api_key"),
                    "metadata": reference.get("metadata", {}),
                    "value": api_key,
                }
            )
        return result

    return OperatorRuntimeManagementSurface(
        surface_label="api",
        provider_summary=lambda: dict(app.model_provider.describe()),
        provider_doctor=_doctor,
        set_default_provider=_set_default_provider,
        daemon_status=lambda probe: daemon_status_record(daemon_state_dir, probe=probe),
        daemon_restart=lambda parameters: restart_daemon_from_operator_params(
            daemon_state_dir,
            cli_state_dir,
            parameters,
        ),
        skill_management=skill_management,
        tool_runtime=lambda: app.tool_runtime,
        security_policy=None,
    )


__all__ = ["build_api_operator_surface"]


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


def provider_profile_payload_from_operator_params(parameters: Mapping[str, Any]) -> dict[str, Any]:
    provider_id = _required(parameters, "provider_id")
    profile_id = str(parameters.get("profile_id") or parameters.get("profileId") or f"provider-{provider_id}").strip()
    model_id = str(parameters.get("model_id") or parameters.get("modelId") or parameters.get("default_model") or "").strip()
    metadata: dict[str, str] = {}
    for source_key, target_key in (
        ("context_window_tokens", "context_window_tokens"),
        ("contextWindowTokens", "context_window_tokens"),
        ("context_window_mode", "context_window_mode"),
        ("contextWindowMode", "context_window_mode"),
        ("reasoning_effort", "reasoning_effort"),
        ("reasoningEffort", "reasoning_effort"),
    ):
        value = parameters.get(source_key)
        if value is not None and str(value).strip():
            metadata[target_key] = str(value).strip()
    payload: dict[str, Any] = {
        "profile_id": profile_id,
        "provider_id": provider_id,
        "metadata": metadata,
        "secret_references": [],
    }
    for source_key, target_key in (
        ("base_url", "base_url"),
        ("baseUrl", "base_url"),
        ("auth_method", "auth_method"),
        ("authMethod", "auth_method"),
        ("provider_kind", "provider_kind"),
        ("providerKind", "provider_kind"),
    ):
        value = parameters.get(source_key)
        if value is not None and str(value).strip():
            payload[target_key] = str(value).strip()
    if model_id:
        payload["default_model"] = model_id
    extra_headers = parameters.get("extra_headers") or parameters.get("extraHeaders")
    if isinstance(extra_headers, Mapping):
        payload["extra_headers"] = {str(key): str(value) for key, value in extra_headers.items()}
    secret_env_var = str(parameters.get("secret_env_var") or parameters.get("secretEnvVar") or "").strip()
    api_key = str(parameters.get("api_key") or parameters.get("apiKey") or "").strip()
    if secret_env_var or api_key:
        secret_metadata = {"storage": "local-vault"}
        if secret_env_var:
            secret_metadata["env_var"] = secret_env_var
        payload["secret_references"] = [
            {
                "reference_id": f"secret-{profile_id}-api-key",
                "provider_id": provider_id,
                "secret_name": "api_token",
                "secret_key": "api_key",
                "metadata": secret_metadata,
            }
        ]
    return payload


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


def _required(parameters: Mapping[str, Any], name: str) -> str:
    value = str(parameters.get(name) or parameters.get(_camel_case(name)) or "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _camel_case(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)
