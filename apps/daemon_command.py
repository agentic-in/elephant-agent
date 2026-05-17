"""CLI entrypoint for the unified Elephant daemon.

``elephant daemon start`` runs all services (IM gateways, cron, supervisor,
learning worker) in a single process with a shared asyncio event loop.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import IO, Sequence

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]

import typer

from apps.runtime_layout import default_cli_state_dir, default_gateway_state_dir

DAEMON_SERVICE_KEY = "daemon"
DAEMON_TARGET = "unified"

_DAEMON_RECORD_NAME = "daemon.runtime.json"
_DAEMON_PID_NAME = "daemon.pid"
_DAEMON_LOG_NAME = "daemon.log"
_DAEMON_LOCK_NAME = "daemon.lock"


def _daemon_pid_path(state_dir: Path) -> Path:
    return state_dir / _DAEMON_PID_NAME


def _daemon_record_path(state_dir: Path) -> Path:
    return state_dir / _DAEMON_RECORD_NAME


def _daemon_log_path(state_dir: Path) -> Path:
    return state_dir / _DAEMON_LOG_NAME


def _daemon_lock_path(state_dir: Path) -> Path:
    return state_dir / _DAEMON_LOCK_NAME


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


def _utc_now_iso() -> str:
    from datetime import UTC, datetime
    return datetime.now(UTC).isoformat()


def _load_record(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_record(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _remove_file_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _acquire_daemon_lock(state_dir: Path, *, blocking: bool = True) -> IO[str] | None:
    """Acquire an exclusive startup lock to serialize concurrent daemon starts.

    Uses ``fcntl.flock`` on *daemon.lock* so that two ``daemon start`` commands
    racing from different terminals cannot both pass the PID-check / PID-write
    window (TOCTOU race).

    Args:
        blocking: When *True* (default) the call blocks until the lock is
            available.  When *False* the call returns *None* immediately if
            the lock cannot be acquired (used by ``_start_detached``).

    Returns:
        The open lock file object — the caller **must** keep it alive while
        the critical section is in progress and call
        :func:`_release_daemon_lock` when done.  Returns *None* only when
        *blocking* is *False* and the lock is held by another process.
    """
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = _daemon_lock_path(state_dir)
    lock_fd = lock_path.open("w", encoding="utf-8")

    if fcntl is None:
        # No fcntl (e.g. Windows) — no actual locking, just return the fd.
        return lock_fd

    flags = fcntl.LOCK_EX if blocking else (fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        fcntl.flock(lock_fd.fileno(), flags)
    except OSError:
        lock_fd.close()
        return None

    return lock_fd


def _release_daemon_lock(lock_fd: IO[str] | None) -> None:
    """Release the daemon startup lock previously acquired via :func:`_acquire_daemon_lock`."""
    if lock_fd is None:
        return
    if fcntl is not None:
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
    lock_fd.close()


def command_main(
    argv: Sequence[str] | None = None,
    *,
    default_state_dir: Path | None = None,
) -> int:
    from apps.cli.typer_support import run_typer_app

    resolved_argv = list(argv) if argv is not None else None
    if resolved_argv == []:
        resolved_argv = ["status"]
    return run_typer_app(
        build_typer_app(default_state_dir=default_state_dir),
        resolved_argv,
        prog_name="elephant daemon",
    )


def build_typer_app(*, default_state_dir: Path | None = None) -> typer.Typer:
    resolved_state_dir = default_state_dir or default_gateway_state_dir()
    resolved_cli_state_dir = default_cli_state_dir()

    app = typer.Typer(
        name="elephant daemon",
        help="Run all Elephant services (IM gateways, cron, supervisor, learning) in a single process.",
        no_args_is_help=True,
        rich_markup_mode="rich",
        add_completion=False,
    )

    @app.callback(invoke_without_command=True)
    def main_callback(ctx: typer.Context) -> None:
        pass

    @app.command("start")
    def start_command(
        state_dir: Path = typer.Option(resolved_state_dir, "--state-dir", help="Gateway state directory."),
        cli_state_dir: Path = typer.Option(resolved_cli_state_dir, "--cli-state-dir", help="CLI state directory."),
        host: str = typer.Option("0.0.0.0", "--host", help="HTTP listen host."),
        port: int = typer.Option(8900, "--port", help="HTTP listen port."),
        log_level: str = typer.Option("INFO", "--log-level", help="Log level: DEBUG, INFO, WARNING, ERROR."),
        detach: bool = typer.Option(False, "--detach", help="Start in a background process. This is the recommended way to run all Elephant services (IM gateways, cron, supervisor, learning worker) together."),
    ) -> None:
        if detach:
            raise typer.Exit(_start_detached(state_dir, cli_state_dir, host=host, port=port, log_level=log_level))
        raise typer.Exit(_run_foreground(state_dir, cli_state_dir, host=host, port=port, log_level=log_level))

    @app.command("stop")
    def stop_command(
        state_dir: Path = typer.Option(resolved_state_dir, "--state-dir", help="Gateway state directory."),
        timeout: float = typer.Option(10.0, "--timeout", help="Seconds to wait before forcing shutdown."),
        force: bool = typer.Option(False, "--force", help="Send SIGKILL if the process does not exit."),
    ) -> None:
        raise typer.Exit(_stop_daemon(state_dir, timeout=timeout, force=force))

    @app.command("status")
    def status_command(
        state_dir: Path = typer.Option(resolved_state_dir, "--state-dir", help="Gateway state directory."),
    ) -> None:
        raise typer.Exit(_show_status(state_dir))

    @app.command("restart")
    def restart_command(
        state_dir: Path = typer.Option(resolved_state_dir, "--state-dir", help="Gateway state directory."),
        cli_state_dir: Path = typer.Option(resolved_cli_state_dir, "--cli-state-dir", help="CLI state directory."),
        host: str = typer.Option("0.0.0.0", "--host", help="HTTP listen host."),
        port: int = typer.Option(8900, "--port", help="HTTP listen port."),
        log_level: str = typer.Option("INFO", "--log-level", help="Log level: DEBUG, INFO, WARNING, ERROR."),
        timeout: float = typer.Option(10.0, "--timeout", help="Seconds to wait before forcing shutdown."),
        force: bool = typer.Option(False, "--force", help="Send SIGKILL if the process does not exit."),
    ) -> None:
        _stop_daemon(state_dir, timeout=timeout, force=force)
        raise typer.Exit(_start_detached(state_dir, cli_state_dir, host=host, port=port, log_level=log_level))

    @app.command("logs")
    def logs_command(
        state_dir: Path = typer.Option(resolved_state_dir, "--state-dir", help="Gateway state directory."),
        tail: int = typer.Option(80, "--tail", help="Show the last N log lines."),
        follow: bool = typer.Option(False, "--follow", help="Keep streaming appended log output."),
        path: bool = typer.Option(False, "--path", help="Print the resolved log file path and exit."),
    ) -> None:
        log_path = _daemon_log_path(state_dir)
        if path:
            print(log_path)
            raise typer.Exit(0)
        if not log_path.exists():
            raise typer.Exit(1)
        lines = log_path.read_text(encoding="utf-8").splitlines()
        if tail > 0:
            for line in lines[-tail:]:
                print(line)
        if follow:
            import select

            with log_path.open("r", encoding="utf-8") as f:
                f.seek(0, 2)
                try:
                    while True:
                        chunk = f.read()
                        if chunk:
                            print(chunk, end="", flush=True)
                        time.sleep(0.4)
                except KeyboardInterrupt:
                    pass
        raise typer.Exit(0)

    return app


def _run_foreground(state_dir: Path, cli_state_dir: Path, *, host: str, port: int, log_level: str = "INFO") -> int:
    """Run the daemon in the foreground (blocking)."""
    from apps.daemon import run_daemon_foreground

    state_dir.mkdir(parents=True, exist_ok=True)
    pid_path = _daemon_pid_path(state_dir)
    record_path = _daemon_record_path(state_dir)

    # ── Singleton guard: acquire lock, then check PID ──
    # Blocking lock — will wait briefly if the parent of a --detach spawn
    # still holds it; once released we proceed and see our own PID in the file.
    lock_fd = _acquire_daemon_lock(state_dir, blocking=True)
    if lock_fd is None:
        # Should not happen with blocking=True, but be safe.
        print("Another Elephant daemon start is in progress.")
        return 1

    try:
        existing_pid = _read_pid(pid_path)
        if (
            existing_pid is not None
            and existing_pid != os.getpid()
            and _pid_is_running(existing_pid)
        ):
            print(f"Elephant daemon is already running with pid {existing_pid}.")
            return 1

        # Write PID file (under lock — prevents TOCTOU race)
        pid = os.getpid()
        pid_path.write_text(f"{pid}\n", encoding="utf-8")

        # Write runtime record
        _write_record(record_path, {
            "runtime_id": f"{DAEMON_SERVICE_KEY}:{DAEMON_TARGET}",
            "service_key": DAEMON_SERVICE_KEY,
            "target": DAEMON_TARGET,
            "status": "running",
            "pid": pid,
            "pid_path": str(pid_path),
            "log_path": str(_daemon_log_path(state_dir)),
            "record_path": str(record_path),
            "state_dir": str(state_dir),
            "cli_state_dir": str(cli_state_dir),
            "host": host,
            "port": port,
            "started_at": _utc_now_iso(),
        })
    finally:
        # Release startup lock — PID file now provides singleton protection.
        _release_daemon_lock(lock_fd)

    try:
        return run_daemon_foreground(
            state_dir=state_dir,
            cli_state_dir=cli_state_dir,
            host=host,
            port=port,
            log_level=log_level,
        )
    finally:
        _remove_file_if_exists(pid_path)
        record = _load_record(record_path) or {}
        record.update({"status": "stopped", "stopped_at": _utc_now_iso(), "pid": None})
        _write_record(record_path, record)


def _start_detached(state_dir: Path, cli_state_dir: Path, *, host: str, port: int, log_level: str = "INFO") -> int:
    """Start the daemon as a background process."""
    state_dir.mkdir(parents=True, exist_ok=True)
    pid_path = _daemon_pid_path(state_dir)
    record_path = _daemon_record_path(state_dir)
    log_path = _daemon_log_path(state_dir)

    # ── Singleton guard: acquire lock (non-blocking), then check PID ──
    lock_fd = _acquire_daemon_lock(state_dir, blocking=False)
    if lock_fd is None:
        print("Another Elephant daemon start is in progress.")
        return 1

    try:
        existing_pid = _read_pid(pid_path)
        if _pid_is_running(existing_pid):
            print(f"Elephant daemon is already running with pid {existing_pid}.")
            return 1

        command = [
            sys.executable,
            "-m",
            "apps.launcher",
            "daemon",
            "start",
            "--state-dir", str(state_dir),
            "--cli-state-dir", str(cli_state_dir),
            "--host", host,
            "--port", str(port),
            "--log-level", log_level,
        ]

        started_at = _utc_now_iso()
        log_path.parent.mkdir(parents=True, exist_ok=True)

        with log_path.open("ab") as log_stream:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=log_stream,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

        # Write PID file + record (still under lock — eliminates TOCTOU race)
        pid_path.write_text(f"{process.pid}\n", encoding="utf-8")
        _write_record(record_path, {
            "runtime_id": f"{DAEMON_SERVICE_KEY}:{DAEMON_TARGET}",
            "service_key": DAEMON_SERVICE_KEY,
            "target": DAEMON_TARGET,
            "status": "starting",
            "pid": process.pid,
            "pid_path": str(pid_path),
            "log_path": str(log_path),
            "record_path": str(record_path),
            "command": command,
            "state_dir": str(state_dir),
            "cli_state_dir": str(cli_state_dir),
            "host": host,
            "port": port,
            "started_at": started_at,
        })
    finally:
        # Release startup lock.  The PID file is now written and the child
        # process will re-acquire this lock inside its own _run_foreground().
        _release_daemon_lock(lock_fd)

    time.sleep(0.4)
    return_code = process.poll()
    if return_code is not None:
        _remove_file_if_exists(pid_path)
        record = _load_record(record_path) or {}
        record.update({
            "status": "failed",
            "pid": None,
            "stopped_at": _utc_now_iso(),
            "last_exit_code": return_code,
            "last_error": f"process exited with code {return_code}",
        })
        _write_record(record_path, record)
        print(f"Elephant daemon failed to start (exit {return_code}). Check {log_path}.")
        return 1

    # Update record to running
    record = _load_record(record_path) or {}
    record["status"] = "running"
    _write_record(record_path, record)

    print(f"Elephant daemon is now running in the background.")
    print(f"  PID: {process.pid}")
    print(f"  PID file: {pid_path}")
    print(f"  Log file: {log_path}")
    print(f"  HTTP: http://{host}:{port}")
    return 0


def _stop_daemon(state_dir: Path, *, timeout: float = 10.0, force: bool = False) -> int:
    """Stop the daemon process."""
    pid_path = _daemon_pid_path(state_dir)
    record_path = _daemon_record_path(state_dir)

    pid = _read_pid(pid_path)
    if not _pid_is_running(pid):
        _remove_file_if_exists(pid_path)
        record = _load_record(record_path) or {}
        if record.get("status") != "stopped":
            record.update({"status": "stopped", "stopped_at": _utc_now_iso(), "pid": None})
            _write_record(record_path, record)
        print("Elephant daemon is not running.")
        return 0

    print(f"Stopping Elephant daemon (pid {pid})...")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        _remove_file_if_exists(pid_path)
        print("Process already exited.")
        return 0
    except PermissionError as exc:
        print(f"Unable to stop process {pid}: {exc}")
        return 1

    # Wait for exit
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_is_running(pid):
            break
        time.sleep(0.2)
    else:
        if not force:
            print(f"Process {pid} did not exit within {timeout}s. Use --force to send SIGKILL.")
            return 1
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass

    _remove_file_if_exists(pid_path)
    record = _load_record(record_path) or {}
    record.update({"status": "stopped", "stopped_at": _utc_now_iso(), "pid": None})
    _write_record(record_path, record)
    print("Elephant daemon stopped.")
    return 0


def _show_status(state_dir: Path) -> int:
    """Show daemon status."""
    pid_path = _daemon_pid_path(state_dir)
    record_path = _daemon_record_path(state_dir)
    log_path = _daemon_log_path(state_dir)

    pid = _read_pid(pid_path)
    running = daemon_is_running(state_dir)
    record = _load_record(record_path) or {}

    # Try to recover PID from healthz when PID file is missing
    if running and pid is None:
        pid = _pid_from_healthz(state_dir)

    status = "running" if running else (record.get("status") or "stopped")

    # ── Header ──
    if running:
        status_icon = "\U0001f7e2"  # green circle
    else:
        status_icon = "\U0001f534"  # red circle
    print(f"\n  Elephant Daemon  {status_icon}  {status}")

    # ── Process info ──
    print()
    print(f"  PID          {pid or '—'}")
    started = record.get("started_at")
    stopped = record.get("stopped_at")
    if started:
        print(f"  Started      {_fmt_iso(started)}")
    if not running and stopped:
        print(f"  Stopped      {_fmt_iso(stopped)}")
    host = record.get("host", "0.0.0.0")
    port = record.get("port", 8900)
    print(f"  Listen       {host}:{port}")
    print(f"  Log          {log_path}")

    # ── Services table ──
    if running:
        try:
            import urllib.request
            url = f"http://127.0.0.1:{port}/healthz"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=3) as resp:
                health = json.loads(resp.read().decode("utf-8"))
                services = health.get("services", {})
                if services:
                    _print_services_table(services)
        except Exception:
            pass

    print()
    return 0


def _fmt_iso(iso_str: str) -> str:
    """Format an ISO timestamp to a more readable local time string."""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return iso_str


def _print_services_table(services: dict) -> None:
    """Print a compact, aligned services status table."""
    # Icons for each status
    icons = {
        "running": "\U0001f7e2",   # green circle
        "skipped": "\U000026AA",   # white circle
        "failed":  "\U0001f534",   # red circle
        "stopped": "\U0001f7e1",   # yellow circle
        "idle":    "\U000026AA",   # white circle
    }

    # Categorize services
    im_keys = ["telegram", "discord", "feishu", "dingding", "wecom", "weixin"]
    infra_keys = ["http", "cron", "supervisor", "learning_worker"]

    print()
    print("  IM Adapters")
    for key in im_keys:
        if key in services:
            info = services[key]
            s = info.get("status", "unknown")
            icon = icons.get(s, "\U000026AA")
            line = f"    {icon}  {key:<12} {s}"
            if s == "skipped" and info.get("last_error"):
                line += f"  ({info['last_error']})"
            elif s == "failed" and info.get("last_error"):
                line += f"  ({info['last_error']})"
            elif s == "running" and info.get("details"):
                # Show useful detail for running services
                details = info["details"]
                if isinstance(details, dict):
                    accounts = details.get("accounts")
                    if accounts:
                        acc_ids = ", ".join(a.get("account_id", "") for a in accounts if a.get("account_id"))
                        if acc_ids:
                            line += f"  ({acc_ids})"
            print(line)

    print()
    print("  Infrastructure")
    for key in infra_keys:
        if key in services:
            info = services[key]
            s = info.get("status", "unknown")
            icon = icons.get(s, "\U000026AA")
            line = f"    {icon}  {key:<12} {s}"
            if s == "failed" and info.get("last_error"):
                line += f"  ({info['last_error']})"
            print(line)


# ── Public API for other CLI commands ──────────────────────────


def daemon_pid_path(state_dir: Path) -> Path:
    """Return the daemon PID file path for the given state directory."""
    return _daemon_pid_path(state_dir)


def daemon_record_path(state_dir: Path) -> Path:
    """Return the daemon runtime record path for the given state directory."""
    return _daemon_record_path(state_dir)


def daemon_is_running(state_dir: Path) -> bool:
    """Check if the unified Elephant daemon is running for the given state directory.

    Primary check: PID file + ``os.kill(pid, 0)``.
    Fallback: HTTP probe to the healthz endpoint when the PID file is missing
    but the daemon may still be alive (e.g. PID file was accidentally deleted).
    """
    pid = _read_pid(_daemon_pid_path(state_dir))
    if _pid_is_running(pid):
        return True
    # Fallback: probe the HTTP healthz endpoint
    return _probe_daemon_http(state_dir)


def _probe_daemon_http(state_dir: Path) -> bool:
    """Try to reach the daemon's /healthz endpoint as a liveness fallback.

    Only probes when the runtime record file exists — this avoids false
    positives in test environments where a random tmp_path happens to reach
    a real daemon on the default port.
    """
    record_path = _daemon_record_path(state_dir)
    if not record_path.exists():
        return False
    record = _load_record(record_path) or {}
    port = record.get("port")
    if port is None:
        return False
    host = record.get("host", "0.0.0.0")
    addr = host if host != "0.0.0.0" else "127.0.0.1"
    try:
        import urllib.request
        url = f"http://{addr}:{port}/healthz"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                body = json.loads(resp.read().decode("utf-8"))
                return body.get("status") == "running"
    except Exception:
        pass
    return False


def _pid_from_healthz(state_dir: Path) -> int | None:
    """Retrieve the daemon PID from the /healthz endpoint."""
    record_path = _daemon_record_path(state_dir)
    if not record_path.exists():
        return None
    record = _load_record(record_path) or {}
    port = record.get("port")
    if port is None:
        return None
    host = record.get("host", "0.0.0.0")
    addr = host if host != "0.0.0.0" else "127.0.0.1"
    try:
        import urllib.request
        url = f"http://{addr}:{port}/healthz"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                body = json.loads(resp.read().decode("utf-8"))
                return body.get("pid")
    except Exception:
        pass
    return None


def start_daemon_detached(
    state_dir: Path,
    cli_state_dir: Path,
    *,
    host: str = "0.0.0.0",
    port: int = 8900,
    log_level: str = "INFO",
) -> int:
    """Start the unified Elephant daemon as a detached process.

    This is the public entry point for other CLI commands (gateway, cron)
    that need to start the daemon instead of per-adapter detached processes.
    """
    return _start_detached(state_dir, cli_state_dir, host=host, port=port, log_level=log_level)


def stop_daemon(
    state_dir: Path,
    *,
    timeout: float = 10.0,
    force: bool = False,
) -> int:
    """Stop the unified Elephant daemon.

    This is the public entry point for other CLI commands that need to
    stop the daemon.
    """
    return _stop_daemon(state_dir, timeout=timeout, force=force)


def restart_daemon(
    state_dir: Path,
    cli_state_dir: Path,
    *,
    host: str = "0.0.0.0",
    port: int = 8900,
    log_level: str = "INFO",
    timeout: float = 10.0,
    force: bool = False,
) -> int:
    """Restart the unified Elephant daemon (stop + start)."""
    _stop_daemon(state_dir, timeout=timeout, force=force)
    return _start_detached(state_dir, cli_state_dir, host=host, port=port, log_level=log_level)


if __name__ == "__main__":
    raise SystemExit(command_main())
