"""Gateway managed-runtime persistence and process helpers."""

from __future__ import annotations
import asyncio
from argparse import SUPPRESS, ArgumentParser, Namespace
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import getpass
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import time
import warnings
from wsgiref.simple_server import make_server

import packages.operator.wizard as cli_wizard
from packages.operator.shell_stack import Align, Console, Group, Panel, RICH_AVAILABLE, Table, Text
from packages.operator.shell_ui import (
    BRAND_ACCENT,
    BRAND_ACCENT_STRONG,
    BRAND_LIGHT,
    BRAND_MUTED,
    resolve_elephant_version as _resolve_elephant_version,
    render_elephant_mark,
)
from apps.provider_runtime import load_runtime_local_secret_env
from apps.runtime_layout import default_cli_state_dir, default_gateway_state_dir
from packages.gateway_core import DEFAULT_GATEWAY_ACCOUNT_ID
from packages.runtime_config import save_extensions_to_config, global_config_path_for_state_dir, load_extensions_from_config, load_global_config

from . import (
    DEFAULT_DISCORD_BOT_TOKEN_ENV,
    DEFAULT_FEISHU_APP_ID_ENV,
    DEFAULT_FEISHU_APP_SECRET_ENV,
    DEFAULT_FEISHU_EVENT_PATH,
    FEISHU_ADAPTER_ID,
    GatewayHttpService,
    GatewayManagedRuntime,
    GatewayManagedService,
    SUPPORTED_DISCORD_TRANSPORTS,
    SUPPORTED_FEISHU_TRANSPORTS,
    build_gateway_app,
    build_gateway_plugin_registry,
    create_gateway_web_app,
)
from .discord import DISCORD_PY_PIP_SPEC, DiscordGatewayService
from .feishu import FEISHU_SDK_PIP_SPEC, FeishuGatewayService

GATEWAY_LOCAL_SECRET_ENV_FILE = "gateway-local-secrets.json"

try:
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings as PromptKeyBindings
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.layout import Layout
    from prompt_toolkit.shortcuts import input_dialog
    from prompt_toolkit.styles import Style as PromptStyle

    PROMPT_TOOLKIT_DIALOGS_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - optional wizard polish
    Application = None
    PromptKeyBindings = None
    HSplit = None
    Window = None
    FormattedTextControl = None
    Layout = None
    input_dialog = None
    PromptStyle = None
    PROMPT_TOOLKIT_DIALOGS_AVAILABLE = False


from .gateway_main_wizard import *  # noqa: F401,F403

def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None

def _mapping_payload(value: object, *, path: str) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be a JSON object")
    return {str(key): item for key, item in value.items()}

def _load_profile_manifest(state_dir: Path) -> dict[str, object]:
    """Load gateway and extension data from the canonical config.yaml."""
    try:
        config_path = global_config_path_for_state_dir(state_dir)
        config = load_global_config(config_path, state_dir=state_dir)
    except (OSError, ValueError):
        return {}

    manifest: dict[str, object] = {}
    gateway_payload = _mapping(config.get("gateway"))
    if gateway_payload is not None:
        manifest["gateway"] = dict(gateway_payload)
    extensions = load_extensions_from_config(config)
    if extensions:
        manifest.update(extensions)
    return manifest

def _gateway_local_secret_env_path(state_dir: Path) -> Path:
    return state_dir / GATEWAY_LOCAL_SECRET_ENV_FILE

def _load_gateway_local_secret_env(state_dir: Path) -> dict[str, str]:
    path = _gateway_local_secret_env_path(state_dir)
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a JSON object")
    resolved: dict[str, str] = {}
    for key, value in payload.items():
        text = str(value).strip()
        if text:
            resolved[str(key)] = text
    return resolved

def _persist_gateway_local_secret_env(
    state_dir: Path,
    updates: Mapping[str, str],
) -> Path | None:
    filtered = {str(key): str(value).strip() for key, value in updates.items() if str(value).strip()}
    if not filtered:
        return None
    state_dir.mkdir(parents=True, exist_ok=True)
    path = _gateway_local_secret_env_path(state_dir)
    payload = _load_gateway_local_secret_env(state_dir)
    payload.update(filtered)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path

def _delete_gateway_local_secret_env(
    state_dir: Path,
    keys: Sequence[str],
) -> Path | None:
    normalized_keys = tuple(str(key).strip() for key in keys if str(key).strip())
    if not normalized_keys:
        return None
    path = _gateway_local_secret_env_path(state_dir)
    payload = _load_gateway_local_secret_env(state_dir)
    changed = False
    for key in normalized_keys:
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
        return path
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    return path

def _gateway_runtime_environ(
    state_dir: Path,
    *,
    cli_state_dir: Path | None = None,
) -> dict[str, str]:
    env = load_runtime_local_secret_env(default_cli_state_dir())
    env.update(load_runtime_local_secret_env(cli_state_dir or state_dir))
    env.update(_load_gateway_local_secret_env(state_dir))
    env.update(os.environ)
    return env

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

def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None

def _resolved_cli_account_id(args: Namespace) -> str | None:
    raw_account_id = getattr(args, "account_id", None)
    direct = _optional_text(raw_account_id) if isinstance(raw_account_id, str) else None
    if direct is not None:
        return direct
    raw_account_id_flag = getattr(args, "account_id_flag", None)
    if not isinstance(raw_account_id_flag, str):
        return None
    return _optional_text(raw_account_id_flag)

def _coerce_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()

def _load_runtime_record(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return {str(key): value for key, value in payload.items()}

def _write_runtime_record(path: Path, record: GatewayRuntimeRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(record), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

def _build_runtime_record(
    args: Namespace,
    *,
    runtime: GatewayManagedRuntime,
    status: str,
    pid: int | None,
    existing: Mapping[str, object] | None = None,
    command: Sequence[str] | None = None,
    started_at: str | None = None,
    stopped_at: str | None = None,
    last_exit_code: int | None = None,
    last_error: str | None = None,
) -> GatewayRuntimeRecord:
    existing_payload = dict(existing or {})
    command_payload = tuple(
        str(value)
        for value in (command or existing_payload.get("command") or ())
    )
    cli_state_dir = _optional_text(getattr(args, "cli_state_dir", None)) or _optional_text(
        existing_payload.get("cli_state_dir")
    )
    host = _optional_text(getattr(args, "host", None)) or _optional_text(existing_payload.get("host"))
    port = _coerce_int(getattr(args, "port", None))
    if port is None:
        port = _coerce_int(existing_payload.get("port"))
    if status == "running":
        stopped_at = None
        last_exit_code = None
        last_error = None
    else:
        if last_exit_code is None:
            last_exit_code = _coerce_int(existing_payload.get("last_exit_code"))
        if last_error is None:
            last_error = _optional_text(existing_payload.get("last_error"))
    if stopped_at is None and status != "running":
        stopped_at = _optional_text(existing_payload.get("stopped_at"))
    if started_at is None:
        started_at = _optional_text(existing_payload.get("started_at"))
    if started_at is None and status in {"starting", "running"}:
        started_at = _utc_now_iso()
    return GatewayRuntimeRecord(
        runtime_id=runtime.runtime_id,
        service_key=runtime.service_key,
        target=runtime.target,
        status=status,
        pid=pid,
        pid_path=str(runtime.pid_path),
        log_path=str(runtime.log_path),
        record_path=str(runtime.record_path),
        command=command_payload,
        state_dir=str(getattr(args, "state_dir", runtime.pid_path.parent)),
        cli_state_dir=cli_state_dir,
        account_id=_optional_text(getattr(args, "account_id", None))
        or _optional_text(existing_payload.get("account_id")),
        host=host,
        port=port,
        started_at=started_at,
        stopped_at=stopped_at,
        last_exit_code=last_exit_code,
        last_error=last_error,
        transport=runtime.target,
    )

def _runtime_state(runtime: GatewayManagedRuntime) -> dict[str, object]:
    record = _load_runtime_record(runtime.record_path) or {}
    pid_from_file = _read_pid(runtime.pid_path)
    pid_from_record = _coerce_int(record.get("pid"))
    pid = pid_from_file if pid_from_file is not None else pid_from_record
    pid_active = _pid_is_running(pid)
    record_status = _optional_text(record.get("status")) or "stopped"
    if pid_active:
        status = "running"
    elif record_status == "failed":
        status = "failed"
    else:
        status = "stopped"
    return {
        "record": record,
        "pid": pid,
        "pid_from_file": pid_from_file,
        "pid_from_record": pid_from_record,
        "pid_active": pid_active,
        "stale_pid": pid_from_file is not None and not pid_active,
        "status": status,
    }

def _remove_file_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return

def _wait_for_pid_exit(pid: int, *, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + max(timeout_seconds, 0.0)
    while time.monotonic() < deadline:
        if not _pid_is_running(pid):
            return True
        time.sleep(0.2)
    return not _pid_is_running(pid)

def _terminate_pid(pid: int, *, timeout_seconds: float, force: bool) -> str | None:
    if timeout_seconds < 0:
        raise SystemExit("--timeout must be zero or a positive number.")
    if not _pid_is_running(pid):
        return None
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return None
    except PermissionError as exc:
        raise SystemExit(f"Unable to stop process {pid}: {exc}") from exc
    if _wait_for_pid_exit(pid, timeout_seconds=timeout_seconds):
        return signal.Signals(signal.SIGTERM).name
    if not force:
        raise SystemExit(
            f"Process {pid} did not exit within {timeout_seconds:g}s. Retry with `--force` to send SIGKILL."
        )
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return signal.Signals(signal.SIGTERM).name
    except PermissionError as exc:
        raise SystemExit(f"Unable to force-stop process {pid}: {exc}") from exc
    if _wait_for_pid_exit(pid, timeout_seconds=max(timeout_seconds, 2.0)):
        return signal.Signals(signal.SIGKILL).name
    raise SystemExit(f"Process {pid} is still running after SIGKILL.")

def _resolve_runtime_target_argument(
    args: Namespace,
    *,
    service: GatewayManagedService | None = None,
) -> str:
    requested_target = str(getattr(args, "runtime_target", "configured") or "configured")
    if requested_target != "configured":
        return requested_target
    if service is None:
        raise SystemExit(
            "Resolving the configured runtime target requires an active gateway service profile."
        )
    return service.configured_runtime_target()

def _process_command_contains(pid: int, needles: Sequence[str]) -> bool:
    """Return True if the process command line contains all of the given needles.

    Uses `ps` for portability (no psutil dependency). Returns False if the pid
    is not inspectable (e.g. exited, permission denied).
    """
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            text=True,
            capture_output=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        return False
    command_line = (result.stdout or "").strip()
    if not command_line:
        return False
    return all(needle in command_line for needle in needles)


def _command_tokens(command_line: str) -> tuple[str, ...]:
    try:
        return tuple(shlex.split(command_line))
    except ValueError:
        return tuple(part for part in command_line.split() if part)


def _path_text_matches(left: str, right: Path) -> bool:
    try:
        return Path(left).expanduser().resolve() == right.expanduser().resolve()
    except OSError:
        return str(Path(left).expanduser()) == str(right.expanduser())


def _gateway_service_process_matches(
    command_line: str,
    *,
    service_key: str,
    state_dir: Path,
) -> bool:
    tokens = _command_tokens(command_line)
    if not tokens:
        return False
    if "gateway" not in tokens or service_key not in tokens or "start" not in tokens:
        return False
    for index, token in enumerate(tokens[:-2]):
        if token == "gateway" and tokens[index + 1] == service_key and tokens[index + 2] == "start":
            break
    else:
        return False
    if "--state-dir" not in tokens:
        return False
    state_index = tokens.index("--state-dir")
    if state_index + 1 >= len(tokens):
        return False
    return _path_text_matches(tokens[state_index + 1], state_dir)


def _discover_gateway_service_processes(
    *,
    service_key: str,
    state_dir: Path,
) -> tuple[int, ...]:
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    if result.returncode != 0:
        return ()
    pids: list[int] = []
    for raw_line in (result.stdout or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        pid_text, _, command_line = line.partition(" ")
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        if pid == os.getpid() or not command_line.strip():
            continue
        if _gateway_service_process_matches(
            command_line,
            service_key=service_key,
            state_dir=state_dir,
        ):
            pids.append(pid)
    return tuple(dict.fromkeys(pids))


def _kill_stale_service_processes(
    args: Namespace,
    *,
    service: GatewayManagedService,
    runtime: GatewayManagedRuntime,
) -> list[int]:
    """Kill any lingering detached processes for the same service_key.

    Scenario: a developer starts a gateway (pid P1) against an older
    repository checkout, later updates code + migrates the DB, and now P1 is
    running pre-migration Python that chokes on the newer schema. When the
    user re-starts from the dashboard, we proactively terminate stale siblings
    so there is only ever one live bridge per service_key.

    The currently-tracked pid (``runtime.pid_path``) is never killed here —
    the caller's existing "already running" path handles that.
    """
    killed: list[int] = []
    state_dir = Path(args.state_dir) if args.state_dir is not None else None
    if state_dir is None or not state_dir.exists():
        return killed
    service_key = str(runtime.service_key or "")
    if not service_key:
        return killed
    current_pid_path = runtime.pid_path
    current_pids = {
        pid
        for pid in (
            _read_pid(runtime.pid_path),
            _coerce_int((_load_runtime_record(runtime.record_path) or {}).get("pid")),
        )
        if pid is not None and pid > 0
    }
    needles = ("gateway", service_key, "start")
    for pid_path in sorted(state_dir.glob(f"{service_key}*.pid")):
        if pid_path.resolve() == current_pid_path.resolve():
            continue
        try:
            pid_raw = pid_path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        try:
            pid = int(pid_raw)
        except ValueError:
            _remove_file_if_exists(pid_path)
            continue
        if pid <= 0:
            _remove_file_if_exists(pid_path)
            continue
        if pid in current_pids:
            continue
        try:
            os.kill(pid, 0)
        except OSError:
            # Process no longer exists; drop the stale pid file.
            _remove_file_if_exists(pid_path)
            continue
        if not _process_command_contains(pid, needles):
            # Alive, but not actually our service — leave it alone.
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            continue
        # Give it up to 2 seconds to exit cleanly before SIGKILL.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                break
            time.sleep(0.1)
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        killed.append(pid)
        _remove_file_if_exists(pid_path)
        # Mark the matching runtime.json as stopped so the dashboard stops
        # reporting phantom 'running' / 'starting' state for the dead sibling.
        record_path = pid_path.with_suffix(".runtime.json")
        if record_path.is_file():
            try:
                record = json.loads(record_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                record = None
            if isinstance(record, dict):
                record["status"] = "stopped"
                record["stopped_at"] = _utc_now_iso()
                record["last_error"] = "replaced by newer start (stale sibling process)"
                try:
                    record_path.write_text(
                        json.dumps(record, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except OSError:
                    pass
    for pid in _discover_gateway_service_processes(service_key=service_key, state_dir=state_dir):
        if pid in current_pids or pid in killed:
            continue
        if not _pid_is_running(pid):
            continue
        _terminate_pid(pid, timeout_seconds=2.0, force=True)
        killed.append(pid)
    return killed


def _run_start_detached(
    args: Namespace,
    *,
    service: GatewayManagedService,
    target: str,
    action: str = "startup",
) -> int:
    # Proactively reap any stale detached siblings for this service_key so we
    # never have two generations of gateway code fighting over the same
    # runtime DB (e.g. post-migration schema mismatches).
    service.prepare_managed_runtime(action=action, target=target)
    runtime = service.managed_runtime(args=args, target=target)
    stale_killed = _kill_stale_service_processes(args, service=service, runtime=runtime)
    if stale_killed:
        print(
            f"Terminated {len(stale_killed)} stale {runtime.service_key} process(es): "
            f"{', '.join(str(pid) for pid in stale_killed)}"
        )
    state = _runtime_state(runtime)
    existing_pid = state["pid"]
    if state["pid_active"]:
        raise SystemExit(
            f"{runtime.label} is already running in the background with pid {existing_pid}."
        )
    args.state_dir.mkdir(parents=True, exist_ok=True)
    command = service.build_detached_runtime_command(args=args, target=target)
    started_at = _utc_now_iso()
    with runtime.log_path.open("ab") as log_stream:
        process = subprocess.Popen(
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=_gateway_runtime_environ(
                args.state_dir,
                cli_state_dir=args.cli_state_dir,
            ),
        )
    runtime.pid_path.write_text(f"{process.pid}\n", encoding="utf-8")
    _write_runtime_record(
        runtime.record_path,
        _build_runtime_record(
            args,
            runtime=runtime,
            status="starting",
            pid=process.pid,
            existing=state["record"],
            command=command,
            started_at=started_at,
        ),
    )
    time.sleep(0.4)
    return_code = process.poll()
    if return_code is not None:
        _remove_file_if_exists(runtime.pid_path)
        log_excerpt = ""
        try:
            excerpt_lines = runtime.log_path.read_text(encoding="utf-8").splitlines()[-20:]
        except OSError:
            excerpt_lines = []
        if excerpt_lines:
            log_excerpt = "\nRecent log output:\n" + "\n".join(excerpt_lines)
        _write_runtime_record(
            runtime.record_path,
            _build_runtime_record(
                args,
                runtime=runtime,
                status="failed",
                pid=None,
                existing=state["record"],
                command=command,
                started_at=started_at,
                stopped_at=_utc_now_iso(),
                last_exit_code=return_code,
                last_error=f"process exited with code {return_code}",
            ),
        )
        raise SystemExit(
            f"{runtime.label} failed to stay up in the background (exit {return_code})."
            f" Check {runtime.log_path}.{log_excerpt}"
        )
    _write_runtime_record(
        runtime.record_path,
        _build_runtime_record(
            args,
            runtime=runtime,
            status="running",
            pid=process.pid,
            existing=state["record"],
            command=command,
            started_at=started_at,
            stopped_at=None,
            last_exit_code=None,
            last_error=None,
        ),
    )
    print(f"Elephant Agent Gateway {runtime.label} is now running in the background.")
    print(f"PID: {process.pid}")
    print(f"PID file: {runtime.pid_path}")
    print(f"Log file: {runtime.log_path}")
    print(f"Runtime record: {runtime.record_path}")
    print(f"Follow logs: {service.managed_runtime_log_hint(target=target)}")
    # Legacy per-adapter starts are intentionally detached and owned by their
    # runtime record after this point. Avoid noisy ResourceWarning output when
    # tests run with warnings enabled.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            category=ResourceWarning,
            message=r"subprocess \d+ is still running",
        )
        del process
    return 0

def _read_log_excerpt(path: Path, *, tail: int) -> tuple[str, ...]:
    if tail < 0:
        raise SystemExit("--tail must be zero or a positive integer.")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SystemExit(f"Unable to read log file {path}: {exc}") from exc
    if tail == 0:
        return ()
    return tuple(lines[-tail:])

def _follow_log_file(path: Path) -> None:
    with path.open("r", encoding="utf-8") as stream:
        stream.seek(0, os.SEEK_END)
        while True:
            chunk = stream.read()
            if chunk:
                print(chunk, end="")
                sys.stdout.flush()
                continue
            time.sleep(0.4)
            try:
                current_size = path.stat().st_size
            except OSError:
                current_size = stream.tell()
            if current_size < stream.tell():
                stream.seek(0)

def _format_runtime_command(record: Mapping[str, object]) -> str:
    command = record.get("command")
    if not isinstance(command, (list, tuple)):
        return "<none>"
    parts = [str(part) for part in command if str(part)]
    if not parts:
        return "<none>"
    return shlex.join(parts)

def _run_status(args: Namespace, *, service: GatewayManagedService | None = None) -> int:
    if service is None:
        raise TypeError("_run_status requires a managed gateway service")
    target = _resolve_runtime_target_argument(args, service=service)
    runtime = service.managed_runtime(args=args, target=target)
    state = _runtime_state(runtime)
    record = state["record"]
    print("Elephant Agent Gateway runtime status")
    print(f"runtime_id: {runtime.runtime_id}")
    print(f"service_key: {runtime.service_key}")
    print(f"target: {runtime.target}")
    print(f"status: {state['status']}")
    print(f"recorded_status: {record.get('status') or '<none>'}")
    print(f"pid: {state['pid'] if state['pid'] is not None else '<none>'}")
    print(f"pid_active: {'yes' if state['pid_active'] else 'no'}")
    print(f"stale_pid_file: {'yes' if state['stale_pid'] else 'no'}")
    print(f"pid_file: {runtime.pid_path}")
    print(f"log_file: {runtime.log_path}")
    print(f"record_file: {runtime.record_path}")
    print(f"started_at: {record.get('started_at') or '<none>'}")
    print(f"stopped_at: {record.get('stopped_at') or '<none>'}")
    print(f"last_exit_code: {record.get('last_exit_code') if record.get('last_exit_code') is not None else '<none>'}")
    print(f"last_error: {record.get('last_error') or '<none>'}")
    print(f"account_id: {record.get('account_id') or '<none>'}")
    print(f"command: {_format_runtime_command(record)}")
    requested_account_id = _resolved_cli_account_id(args)
    if hasattr(service, "describe"):
        from .gateway_main_parser import (
            _discord_account_status_lines,
            _feishu_async_status_lines,
            _render_discord_account_line,
            _render_feishu_account_line,
            _selected_account_payloads,
        )

        description = service.describe()
        service_key = str(getattr(service, "service_key", "") or "")
        if service_key == "discord":
            for line in _discord_account_status_lines(description):
                print(line)
            for account in _selected_account_payloads(
                description,
                account_id=requested_account_id,
                provider="discord",
            ):
                print(_render_discord_account_line(account, prefix="account"))
        elif service_key == "feishu":
            for line in _feishu_async_status_lines(description):
                print(line)
            for account in _selected_account_payloads(
                description,
                account_id=requested_account_id,
                provider="feishu",
            ):
                print(_render_feishu_account_line(account, prefix="account"))
    return 0

def _stop_managed_runtime(
    args: Namespace,
    *,
    service: GatewayManagedService,
    target: str,
) -> tuple[str, str | None, GatewayManagedRuntime]:
    runtime = service.managed_runtime(args=args, target=target)
    state = _runtime_state(runtime)
    record = state["record"]
    pid = _coerce_int(state["pid"])
    if pid is None or not state["pid_active"]:
        if state["stale_pid"]:
            _remove_file_if_exists(runtime.pid_path)
        _write_runtime_record(
            runtime.record_path,
            _build_runtime_record(
                args,
                runtime=runtime,
                status="stopped",
                pid=None,
                existing=record,
                stopped_at=_utc_now_iso(),
            ),
        )
        return "already-stopped", None, runtime
    signal_name = _terminate_pid(pid, timeout_seconds=args.timeout, force=args.force)
    _remove_file_if_exists(runtime.pid_path)
    _write_runtime_record(
        runtime.record_path,
        _build_runtime_record(
            args,
            runtime=runtime,
            status="stopped",
            pid=None,
            existing=record,
            stopped_at=_utc_now_iso(),
            last_exit_code=0,
            last_error=None,
        ),
    )
    return "stopped", signal_name, runtime

def _run_stop(args: Namespace, *, service: GatewayManagedService | None = None) -> int:
    if service is None:
        raise TypeError("_run_stop requires a managed gateway service")
    target = _resolve_runtime_target_argument(args, service=service)
    outcome, signal_name, runtime = _stop_managed_runtime(
        args,
        service=service,
        target=target,
    )
    if outcome == "already-stopped":
        print(f"{runtime.label} is not running.")
    else:
        print(f"Stopped Elephant Agent Gateway {runtime.label}.")
        print(f"Signal: {signal_name or '<none>'}")
    print(f"Log file: {runtime.log_path}")
    print(f"Runtime record: {runtime.record_path}")
    return 0

def _run_restart(args: Namespace, *, service: GatewayManagedService | None = None) -> int:
    if service is None:
        raise TypeError("_run_restart requires a managed gateway service")
    target = _resolve_runtime_target_argument(args, service=service)
    runtime = service.managed_runtime(args=args, target=target)
    print(f"Restarting Elephant Agent Gateway {runtime.label}.")
    outcome, _, _ = _stop_managed_runtime(args, service=service, target=target)
    if outcome == "already-stopped":
        print("No running detached runtime was found; starting a fresh background process.")
    return _run_start_detached(args, service=service, target=target, action="restart")

def _run_logs(args: Namespace, *, service: GatewayManagedService | None = None) -> int:
    if service is None:
        raise TypeError("_run_logs requires a managed gateway service")
    if _resolved_cli_account_id(args) is None and getattr(service, "service_key", "") != "cron":
        raise SystemExit("logs requires <account-id>")
    target = _resolve_runtime_target_argument(args, service=service)
    runtime = service.managed_runtime(args=args, target=target)
    state = _runtime_state(runtime)
    if args.path:
        print(runtime.log_path)
        return 0
    if not runtime.log_path.exists():
        running_hint = (
            f" Background pid {state['pid']} is still recorded." if state["pid_active"] else ""
        )
        raise SystemExit(
            f"No log file found for {runtime.label} at {runtime.log_path}."
            f" Start it with `{service.managed_runtime_log_hint(target=target).replace(' logs ', ' start ').replace('--follow', '--detach')}` first.{running_hint}"
        )
    excerpt = _read_log_excerpt(runtime.log_path, tail=args.tail)
    if excerpt:
        print("\n".join(excerpt))
    if args.follow:
        if not excerpt:
            print(f"Following {runtime.log_path} (Ctrl-C to stop)")
        try:
            _follow_log_file(runtime.log_path)
        except KeyboardInterrupt:
            return 0
    return 0

__all__ = [
    "_mapping",
    "_mapping_payload",
    "_load_profile_manifest",
    "_gateway_local_secret_env_path",
    "_load_gateway_local_secret_env",
    "_persist_gateway_local_secret_env",
    "_delete_gateway_local_secret_env",
    "_gateway_runtime_environ",
    "_read_pid",
    "_pid_is_running",
    "_optional_text",
    "_coerce_int",
    "_utc_now_iso",
    "_load_runtime_record",
    "_write_runtime_record",
    "_build_runtime_record",
    "_runtime_state",
    "_remove_file_if_exists",
    "_wait_for_pid_exit",
    "_terminate_pid",
    "_resolve_runtime_target_argument",
    "_run_start_detached",
    "_read_log_excerpt",
    "_follow_log_file",
    "_format_runtime_command",
    "_run_status",
    "_stop_managed_runtime",
    "_run_stop",
    "_run_restart",
    "_run_logs",
]
