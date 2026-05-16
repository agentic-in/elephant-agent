"""CLI entrypoint for the long-horizon supervisor.

``elephant supervisor run`` scans every loop_checkpoint row on a fixed
interval and reclaims crashed Loops (stale heartbeat) or wakes ripe
timers. Phase 1 only exposes foreground ``run`` plus ``scan-once`` so
operators can drive a supervisor tick from a script or cron. A full
detached-daemon mode with pid/log files (matching
``apps/cron_scheduler_command.py``) ships in Phase 4 alongside the
event bus.

The supervisor CLI reads the default CLI state dir so it picks up the
same sqlite database the rest of the runtime writes to. Operators
pointing at a different deployment pass ``--state-dir``.
"""

from __future__ import annotations

from pathlib import Path
import json
import logging
import signal
import sys
import threading
from typing import Sequence

import typer

from apps.runtime_layout import default_cli_state_dir

from packages.harness.supervisor import (
    DEFAULT_HEARTBEAT_STALE_TTL_SECONDS,
    DEFAULT_SUPERVISOR_INTERVAL_SECONDS,
    SupervisorTickResult,
    run_supervisor_loop,
    scan_once,
)
from packages.storage import RuntimeStorageRepository


logger = logging.getLogger("elephant.supervisor")


def _sqlite_path_for_state_dir(state_dir: Path) -> Path:
    """Resolve the sqlite database path the CLI runtime writes to.

    Checks both ``<state_dir>/elephant.sqlite3`` (current layout) and
    ``<state_dir>/state/elephant.sqlite3`` (legacy layout) so the
    supervisor works regardless of schema version.
    """
    current = state_dir / "elephant.sqlite3"
    if current.exists():
        return current
    return state_dir / "state" / "elephant.sqlite3"


def _format_decision(decision) -> str:
    return (
        f"{decision.decided_at.isoformat()} {decision.action} {decision.loop_id} "
        f"wc={decision.snapshot.wait_condition_kind or '<none>'} "
        f"retry_attempt={decision.snapshot.retry_attempt} "
        f"pending_after={len(decision.snapshot.replay_plans)}"
    )


def _print_tick(tick: SupervisorTickResult) -> None:
    if tick.scanned_count == 0 and not tick.decisions:
        return
    summary = (
        f"[supervisor] scanned={tick.scanned_count} decisions={len(tick.decisions)} "
        f"started={tick.tick_started_at.isoformat()} finished={tick.tick_finished_at.isoformat()}"
    )
    print(summary, flush=True)
    for decision in tick.decisions:
        print(f"  {_format_decision(decision)}", flush=True)


def _build_repository(state_dir: Path) -> RuntimeStorageRepository:
    db_path = _sqlite_path_for_state_dir(state_dir)
    repo = RuntimeStorageRepository(db_path)
    if db_path.exists():
        repo.bootstrap()
    return repo


def _stop_event_with_signals() -> threading.Event:
    stop = threading.Event()

    def _handler(signum, frame):  # pragma: no cover - signal handling
        logger.info("supervisor received signal %s; shutting down", signum)
        stop.set()

    try:
        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)
    except ValueError:
        # We're not on the main thread; signals unavailable. The caller
        # is responsible for stopping the loop.
        pass
    return stop


def command_main(
    argv: Sequence[str] | None = None,
    *,
    default_state_dir: Path | None = None,
) -> int:
    resolved_state_dir = default_state_dir or default_cli_state_dir()
    app = build_typer_app(default_state_dir=resolved_state_dir)
    resolved_argv = list(argv) if argv is not None else None
    if resolved_argv == []:
        resolved_argv = ["status"]
    from apps.cli.typer_support import run_typer_app

    return run_typer_app(app, resolved_argv, prog_name="elephant supervisor")


def build_typer_app(*, default_state_dir: Path) -> typer.Typer:
    app = typer.Typer(
        name="elephant supervisor",
        help="Run the long-horizon harness supervisor (crash scan + timer wake).",
        no_args_is_help=False,
        rich_markup_mode="rich",
        add_completion=False,
    )

    @app.callback(invoke_without_command=True)
    def main_callback(ctx: typer.Context) -> None:
        if ctx.invoked_subcommand is None:
            raise typer.Exit(0)

    @app.command("run")
    def run_command(
        state_dir: Path = typer.Option(default_state_dir, "--state-dir", help="CLI state dir."),
        interval_seconds: float = typer.Option(
            DEFAULT_SUPERVISOR_INTERVAL_SECONDS,
            "--interval-seconds",
            help="Seconds between scan ticks.",
        ),
        stale_ttl_seconds: float = typer.Option(
            DEFAULT_HEARTBEAT_STALE_TTL_SECONDS,
            "--stale-ttl-seconds",
            help="Heartbeat TTL after which a Loop is reclaimed as crashed.",
        ),
    ) -> None:
        repo = _build_repository(state_dir)
        print(
            f"[supervisor] running against {_sqlite_path_for_state_dir(state_dir)} "
            f"interval={interval_seconds:g}s stale_ttl={stale_ttl_seconds:g}s",
            flush=True,
        )
        stop = _stop_event_with_signals()
        run_supervisor_loop(
            repo,
            interval_seconds=interval_seconds,
            heartbeat_stale_ttl_seconds=stale_ttl_seconds,
            stop_event=stop,
            on_tick=_print_tick,
        )
        raise typer.Exit(0)

    @app.command("scan-once")
    def scan_once_command(
        state_dir: Path = typer.Option(default_state_dir, "--state-dir", help="CLI state dir."),
        stale_ttl_seconds: float = typer.Option(
            DEFAULT_HEARTBEAT_STALE_TTL_SECONDS,
            "--stale-ttl-seconds",
            help="Heartbeat TTL after which a Loop is reclaimed as crashed.",
        ),
        as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    ) -> None:
        repo = _build_repository(state_dir)
        tick = scan_once(repo, heartbeat_stale_ttl_seconds=stale_ttl_seconds)
        if as_json:
            payload = {
                "scanned_count": tick.scanned_count,
                "decisions": [
                    {
                        "loop_id": d.loop_id,
                        "action": d.action,
                        "detail": d.detail,
                        "wait_condition_kind": d.snapshot.wait_condition_kind,
                        "retry_attempt": d.snapshot.retry_attempt,
                        "decided_at": d.decided_at.isoformat(),
                    }
                    for d in tick.decisions
                ],
                "tick_started_at": tick.tick_started_at.isoformat(),
                "tick_finished_at": tick.tick_finished_at.isoformat(),
            }
            print(json.dumps(payload, indent=2), flush=True)
        else:
            _print_tick(tick)
        raise typer.Exit(0)

    @app.command("status")
    def status_command(
        state_dir: Path = typer.Option(default_state_dir, "--state-dir", help="CLI state dir."),
    ) -> None:
        repo = _build_repository(state_dir)
        loops = repo.list_loop_checkpoints(statuses=("active", "pending"))
        print(f"[supervisor] open loop checkpoints: {len(loops)}", flush=True)
        for loop in loops:
            hb = loop.heartbeat_at.isoformat() if loop.heartbeat_at else "<none>"
            kind = loop.wait_condition.kind if loop.wait_condition else "<none>"
            print(
                f"  {loop.run_id} status={loop.status} heartbeat_at={hb} wait_condition={kind} "
                f"pending_tools={len(loop.pending_tool_calls)} "
                f"crash_marker={loop.crash_marker or '<none>'}",
                flush=True,
            )
        raise typer.Exit(0)

    return app


def main(argv: Sequence[str] | None = None) -> int:
    return command_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
