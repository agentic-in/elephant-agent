"""Graceful in-place upgrade orchestration for installed Elephant Agent runtimes."""

from __future__ import annotations

from argparse import ArgumentParser, Namespace
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time

from apps.runtime_layout import default_cli_state_dir, default_gateway_state_dir
from packages.runtime_layout import infer_install_root_from_state_dir

_RUNTIME_SUFFIX = ".runtime.json"
_SQLITE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
_BACKUP_EXCLUDE_NAMES = {"venv", "backups", "__pycache__"}
_GATEWAY_SERVICES = {"discord", "feishu", "dingding", "weixin", "wecom"}


@dataclass(frozen=True, slots=True)
class ManagedRuntimeSnapshot:
    service_key: str
    target: str
    pid: int
    pid_path: Path
    record_path: Path
    state_dir: Path
    cli_state_dir: Path
    account_id: str | None = None
    host: str | None = None
    port: int | None = None
    interval_seconds: float | None = None

    @property
    def label(self) -> str:
        return f"{self.service_key}:{self.target} pid={self.pid}"


def _coerce_int(value: object) -> int | None:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _coerce_float(value: object) -> float | None:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _pid_is_running(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_json_object(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _pid_from_record(record: dict[str, object], record_path: Path) -> tuple[int | None, Path]:
    pid_path = Path(str(record.get("pid_path") or record_path.with_suffix(".pid")))
    pid = _coerce_int(record.get("pid"))
    if pid is None and pid_path.exists():
        try:
            pid = _coerce_int(pid_path.read_text(encoding="utf-8"))
        except OSError:
            pid = None
    return pid, pid_path


def _command_value(command: object, flag: str) -> str | None:
    if not isinstance(command, Sequence) or isinstance(command, (str, bytes)):
        return None
    parts = [str(part) for part in command]
    try:
        index = parts.index(flag)
    except ValueError:
        return None
    if index + 1 >= len(parts):
        return None
    return parts[index + 1]


def discover_running_runtimes(
    *,
    gateway_state_dir: Path,
    cli_state_dir: Path,
) -> tuple[ManagedRuntimeSnapshot, ...]:
    """Return managed gateway/cron runtimes that are currently alive."""
    if not gateway_state_dir.exists():
        return ()
    discovered: list[ManagedRuntimeSnapshot] = []
    seen: set[tuple[str, str, int]] = set()
    for record_path in sorted(gateway_state_dir.glob(f"*{_RUNTIME_SUFFIX}")):
        record = _read_json_object(record_path)
        if record is None:
            continue
        pid, pid_path = _pid_from_record(record, record_path)
        if not _pid_is_running(pid):
            continue
        service_key = _optional_text(record.get("service_key"))
        target = _optional_text(record.get("target")) or _optional_text(record.get("transport"))
        if not service_key or not target:
            stem = record_path.name[: -len(_RUNTIME_SUFFIX)]
            if "-" in stem:
                service_key = service_key or stem.split("-", 1)[0]
                target = target or stem.split("-", 1)[1]
        if not service_key or not target:
            continue
        state_dir = Path(str(record.get("state_dir") or gateway_state_dir))
        runtime_cli_state_dir = Path(str(record.get("cli_state_dir") or cli_state_dir))
        command = record.get("command")
        interval_seconds = _coerce_float(_command_value(command, "--interval-seconds"))
        key = (service_key, target, int(pid or 0))
        if key in seen:
            continue
        seen.add(key)
        discovered.append(
            ManagedRuntimeSnapshot(
                service_key=service_key,
                target=target,
                pid=int(pid or 0),
                pid_path=pid_path,
                record_path=record_path,
                state_dir=state_dir,
                cli_state_dir=runtime_cli_state_dir,
                account_id=_optional_text(record.get("account_id")),
                host=_optional_text(record.get("host")),
                port=_coerce_int(record.get("port")),
                interval_seconds=interval_seconds,
            )
        )
    return tuple(discovered)


def restart_argv_for_runtime(runtime: ManagedRuntimeSnapshot) -> list[str]:
    """Build a launcher argv that restarts one previously running runtime."""
    if runtime.service_key == "cron":
        argv = [
            "cron",
            "start",
            "--detach",
            "--target",
            runtime.target,
            "--state-dir",
            str(runtime.state_dir),
            "--cli-state-dir",
            str(runtime.cli_state_dir),
        ]
        if runtime.interval_seconds is not None:
            argv.extend(["--interval-seconds", f"{runtime.interval_seconds:g}"])
        return argv
    if runtime.service_key not in _GATEWAY_SERVICES:
        raise ValueError(f"unsupported managed runtime service: {runtime.service_key}")
    argv = ["gateway", runtime.service_key, "start"]
    if runtime.account_id:
        argv.append(runtime.account_id)
    argv.extend(
        [
            "--transport",
            runtime.target,
            "--detach",
            "--state-dir",
            str(runtime.state_dir),
            "--cli-state-dir",
            str(runtime.cli_state_dir),
        ]
    )
    if runtime.host:
        argv.extend(["--host", runtime.host])
    if runtime.port is not None:
        argv.extend(["--port", str(runtime.port)])
    return argv


def stop_runtime(runtime: ManagedRuntimeSnapshot, *, timeout_seconds: float, force: bool) -> str:
    """Ask one runtime to stop, escalating only after the grace timeout."""
    if not _pid_is_running(runtime.pid):
        return "already-stopped"
    try:
        os.kill(runtime.pid, signal.SIGTERM)
    except ProcessLookupError:
        return "already-stopped"
    deadline = time.monotonic() + max(timeout_seconds, 0.0)
    while time.monotonic() < deadline:
        if not _pid_is_running(runtime.pid):
            return "sigterm"
        time.sleep(0.2)
    if not force:
        raise RuntimeError(f"{runtime.label} did not exit within {timeout_seconds:g}s; rerun with --force-stop")
    try:
        os.kill(runtime.pid, signal.SIGKILL)
    except ProcessLookupError:
        return "sigterm"
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if not _pid_is_running(runtime.pid):
            return "sigkill"
        time.sleep(0.2)
    raise RuntimeError(f"{runtime.label} is still running after SIGKILL")


def pip_upgrade_command(*, channel: str, pip_spec: str | None) -> list[str]:
    base = [sys.executable, "-m", "pip", "install", "--upgrade"]
    if pip_spec:
        return [*base, pip_spec]
    if channel == "dev":
        return [*base, "--pre", "elephant"]
    if channel == "stable":
        return [*base, "elephant"]
    raise ValueError(f"unsupported channel: {channel}")


def _copy_sqlite_database(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as source:
            with sqlite3.connect(dst) as target:
                source.backup(target)
        shutil.copystat(src, dst, follow_symlinks=False)
    except sqlite3.Error:
        shutil.copy2(src, dst)


def _copy_state_tree(src: Path, dst: Path) -> None:
    if src.name in _BACKUP_EXCLUDE_NAMES:
        return
    if src.is_symlink():
        return
    if src.is_dir():
        dst.mkdir(parents=True, exist_ok=True)
        for child in src.iterdir():
            _copy_state_tree(child, dst / child.name)
        return
    if not src.is_file():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() in _SQLITE_SUFFIXES:
        _copy_sqlite_database(src, dst)
    else:
        shutil.copy2(src, dst)


def create_pre_upgrade_backup(home_dir: Path) -> Path:
    """Create a tar.gz backup of durable Elephant Agent state, excluding the venv."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_dir = home_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    output_path = backup_dir / f"pre-upgrade-{timestamp}.tar.gz"
    with tempfile.TemporaryDirectory(prefix="elephant-upgrade-") as tmp_raw:
        tmp_root = Path(tmp_raw) / "elephant-home"
        tmp_root.mkdir(parents=True, exist_ok=True)
        if home_dir.exists():
            for child in home_dir.iterdir():
                _copy_state_tree(child, tmp_root / child.name)
        with tarfile.open(output_path, "w:gz") as archive:
            archive.add(tmp_root, arcname="elephant-home")
    return output_path


def _upgrade_env(home_dir: Path, state_dir: Path, gateway_state_dir: Path) -> dict[str, str]:
    return {
        **os.environ,
        "ELEPHANT_HOME": str(home_dir),
        "ELEPHANT_HERD_DIR": str(state_dir),
        "ELEPHANT_GATEWAY_DIR": str(gateway_state_dir),
    }


def _run_checked(command: Sequence[str], *, env: dict[str, str], dry_run: bool = False) -> None:
    rendered = " ".join(command)
    print(f"  $ {rendered}")
    if dry_run:
        return
    subprocess.run(list(command), check=True, env=env)


def _bootstrap_storage(*, env: dict[str, str], state_dir: Path, dry_run: bool = False) -> None:
    code = (
        "from pathlib import Path\n"
        "from apps.cli.runtime import CliRuntime\n"
        f"CliRuntime.create(state_dir=Path({str(state_dir)!r}))\n"
        "print('Storage schema is current')\n"
    )
    _run_checked([sys.executable, "-c", code], env=env, dry_run=dry_run)


def _restart_runtime(runtime: ManagedRuntimeSnapshot, *, env: dict[str, str], dry_run: bool) -> bool:
    argv = restart_argv_for_runtime(runtime)
    command = [sys.executable, "-m", "apps.launcher", *argv]
    print(f"Restarting {runtime.service_key}:{runtime.target}")
    if dry_run:
        print(f"  $ {' '.join(command)}")
        return True
    result = subprocess.run(command, env=env)
    if result.returncode != 0:
        print(f"  restart failed with exit {result.returncode}")
        return False
    return True


def run_upgrade(args: Namespace) -> int:
    state_dir = Path(args.state_dir).expanduser().resolve()
    gateway_state_dir = Path(args.gateway_state_dir).expanduser().resolve()
    home_dir = infer_install_root_from_state_dir(state_dir)
    env = _upgrade_env(home_dir, state_dir, gateway_state_dir)
    dry_run = bool(args.dry_run)

    print("Elephant Agent graceful upgrade")
    print(f"  home:    {home_dir}")
    print(f"  state:   {state_dir}")
    print(f"  gateway: {gateway_state_dir}")

    runtimes = discover_running_runtimes(
        gateway_state_dir=gateway_state_dir,
        cli_state_dir=state_dir,
    )
    if runtimes:
        print("\nRunning managed runtimes:")
        for runtime in runtimes:
            print(f"  - {runtime.label}")
    else:
        print("\nRunning managed runtimes: none")

    if not args.no_backup:
        print("\nCreating pre-upgrade backup")
        if dry_run:
            print(f"  would write: {home_dir / 'backups' / 'pre-upgrade-<timestamp>.tar.gz'}")
        else:
            backup_path = create_pre_upgrade_backup(home_dir)
            print(f"  backup: {backup_path}")
    else:
        print("\nBackup skipped (--no-backup)")

    stopped: list[ManagedRuntimeSnapshot] = []
    try:
        for runtime in runtimes:
            print(f"Stopping {runtime.label}")
            if dry_run:
                print(f"  would send SIGTERM to {runtime.pid}")
                stopped.append(runtime)
                continue
            signal_name = stop_runtime(
                runtime,
                timeout_seconds=float(args.timeout),
                force=bool(args.force_stop),
            )
            print(f"  stopped: {signal_name}")
            stopped.append(runtime)

        print("\nUpgrading package")
        _run_checked(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--upgrade",
                "pip",
                "setuptools",
                "wheel",
            ],
            env=env,
            dry_run=dry_run,
        )
        _run_checked(
            pip_upgrade_command(channel=args.channel, pip_spec=args.pip_spec),
            env=env,
            dry_run=dry_run,
        )

        if not args.skip_browser_install:
            print("\nRefreshing browser runtime")
            command = [sys.executable, "-m", "playwright", "install", "chromium"]
            print(f"  $ {' '.join(command)}")
            if not dry_run:
                subprocess.run(command, env=env, check=False)

        print("\nBootstrapping storage with upgraded code")
        _bootstrap_storage(env=env, state_dir=state_dir, dry_run=dry_run)
    except Exception as exc:
        print(f"\nUpgrade failed: {exc}")
        if stopped and not args.skip_restart:
            print("\nRestarting previously stopped runtimes after failure")
            for runtime in stopped:
                _restart_runtime(runtime, env=env, dry_run=dry_run)
        return 1

    if stopped and not args.skip_restart:
        print("\nRestarting previously running runtimes")
        failures = 0
        for runtime in stopped:
            if not _restart_runtime(runtime, env=env, dry_run=dry_run):
                failures += 1
        if failures:
            print(f"\nUpgrade completed, but {failures} runtime(s) failed to restart.")
            return 2
    elif stopped:
        print("\nRuntime restart skipped (--skip-restart)")

    print("\nElephant Agent upgrade complete")
    return 0


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="elephant upgrade",
        description="Gracefully upgrade Elephant Agent in place with backup, managed-runtime stop, storage bootstrap, and restart.",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=default_cli_state_dir(),
        help="CLI state directory.",
    )
    parser.add_argument(
        "--gateway-state-dir",
        type=Path,
        default=default_gateway_state_dir(),
        help="Gateway runtime state directory.",
    )
    parser.add_argument(
        "--channel",
        choices=("dev", "stable"),
        default=os.environ.get("ELEPHANT_INSTALL_CHANNEL", "dev"),
        help="Package channel to install when --pip-spec is omitted.",
    )
    parser.add_argument(
        "--pip-spec",
        default=os.environ.get("ELEPHANT_PIP_SPEC", "") or None,
        help="Explicit pip-installable package spec.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Seconds to wait for each runtime to stop before escalation.",
    )
    parser.add_argument(
        "--force-stop",
        action="store_true",
        default=True,
        help="Send SIGKILL when a runtime ignores SIGTERM after --timeout.",
    )
    parser.add_argument(
        "--no-force-stop",
        action="store_false",
        dest="force_stop",
        help="Fail instead of sending SIGKILL after --timeout.",
    )
    parser.add_argument("--no-backup", action="store_true", help="Skip the pre-upgrade state backup.")
    parser.add_argument(
        "--skip-restart",
        action="store_true",
        help="Do not restart runtimes that were running before the upgrade.",
    )
    parser.add_argument(
        "--skip-browser-install",
        action="store_true",
        default=os.environ.get("ELEPHANT_SKIP_BROWSER_INSTALL") == "1",
        help="Skip Playwright Chromium refresh.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned upgrade without changing files or processes.",
    )
    return parser


def command_main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return run_upgrade(args)


def main(argv: Sequence[str] | None = None) -> int:
    return command_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
