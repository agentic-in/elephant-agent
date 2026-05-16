"""Standalone cron scheduler daemon command."""

from __future__ import annotations

from argparse import ArgumentParser, Namespace, SUPPRESS
from pathlib import Path
from types import SimpleNamespace
from typing import Sequence

import typer

from apps.daemon_command import daemon_is_running
from apps.gateway.cron_service import build_cron_scheduler_service
from apps.gateway.gateway_main_runtime import (
    _gateway_runtime_environ,
    _run_logs,
    _run_status,
    _run_stop,
)
from apps.runtime_layout import (
    default_cli_state_dir,
    default_gateway_state_dir,
)

from .cli.typer_support import run_typer_app


def command_main(
    argv: Sequence[str] | None = None,
    *,
    default_state_dir: Path | None = None,
    default_control_state_dir: Path | None = None,
) -> int:
    defaults = {
        "state_dir": default_state_dir or default_gateway_state_dir(),
        "cli_state_dir": default_control_state_dir or default_cli_state_dir(),
    }
    resolved_argv = list(argv) if argv is not None else None
    if resolved_argv == []:
        resolved_argv = ["status"]
    return run_typer_app(build_typer_app(defaults=defaults), resolved_argv, prog_name="elephant cron")


def _build_parser(*, defaults: dict[str, Path]) -> ArgumentParser:
    common = ArgumentParser(add_help=False)
    common.add_argument("--state-dir", type=Path, default=defaults["state_dir"])
    common.add_argument("--cli-state-dir", type=Path, default=defaults["cli_state_dir"])
    common.add_argument("--elephant-id", default="elephant:gateway")

    parser = ArgumentParser(prog="elephant cron", description="Manage the Elephant Agent cron scheduler daemon.")
    subparsers = parser.add_subparsers(dest="command")

    start = subparsers.add_parser("start", parents=[common], help="Start the cron scheduler.")
    _add_start_options(start)
    start.set_defaults(command_action="start")

    run = subparsers.add_parser("run", parents=[common], help="Run the cron scheduler in the foreground.")
    _add_start_options(run)
    run.add_argument("--once", action="store_true", help="Run one scheduler tick and exit.")
    run.set_defaults(command_action="run", detach=False)

    status = subparsers.add_parser("status", parents=[common], help="Show cron scheduler status.")
    _add_target_options(status)
    status.set_defaults(command_action="status")

    stop = subparsers.add_parser("stop", parents=[common], help="Stop the cron scheduler.")
    _add_stop_options(stop)
    stop.set_defaults(command_action="stop")

    restart = subparsers.add_parser("restart", parents=[common], help="Restart the cron scheduler.")
    _add_start_options(restart)
    restart.add_argument("--timeout", type=float, default=10.0, help=SUPPRESS)
    restart.add_argument("--force", action="store_true", help=SUPPRESS)
    restart.set_defaults(command_action="restart", detach=True)

    logs = subparsers.add_parser("logs", parents=[common], help="Show cron scheduler logs.")
    _add_logs_options(logs)
    logs.set_defaults(command_action="logs")
    parser.set_defaults(command_action="status")
    return parser


def _add_target_options(parser: ArgumentParser) -> None:
    parser.set_defaults(runtime_target="scheduler")
    parser.add_argument("--target", dest="runtime_target", choices=("configured", "scheduler"), default="scheduler", help=SUPPRESS)


def _add_start_options(parser: ArgumentParser) -> None:
    _add_target_options(parser)
    parser.add_argument("--detach", action="store_true", help="Start in a background process and return immediately.")
    parser.add_argument("--interval-seconds", type=float, default=60.0, help="Seconds between scheduler ticks.")


def _add_stop_options(parser: ArgumentParser) -> None:
    _add_target_options(parser)
    parser.add_argument("--timeout", type=float, default=10.0, help="Seconds to wait before failing or forcing.")
    parser.add_argument("--force", action="store_true", help="Send SIGKILL when the process does not exit.")


def _add_logs_options(parser: ArgumentParser) -> None:
    _add_target_options(parser)
    parser.add_argument("--tail", type=int, default=80, help="Show the last N log lines.")
    parser.add_argument("--follow", action="store_true", help="Keep streaming appended log output.")
    parser.add_argument("--path", action="store_true", help="Print the resolved log file path and exit.")


def _build_service(args: Namespace):
    args.state_dir.mkdir(parents=True, exist_ok=True)
    app = SimpleNamespace(state_dir=str(args.state_dir))
    environ = _gateway_runtime_environ(args.state_dir, cli_state_dir=args.cli_state_dir)
    service = build_cron_scheduler_service(
        app=app,
        default_cli_state_dir=str(args.cli_state_dir),
        environ=environ,
        runtime_state_dir=args.state_dir,
    )
    service.delivery_callback = _build_delivery_callback(args, environ=environ)
    return service


def _build_delivery_callback(args: Namespace, *, environ):
    """Build a delivery callback that fans out to every configured IM adapter.

    Each cron execution is offered to every adapter; each adapter's ``deliver_cron_result``
    filters on its own ``adapter_id`` and only the one that owns the elephant's identity record
    actually sends.
    """
    from apps.gateway.cron_service import build_gateway_cron_delivery_callback

    return build_gateway_cron_delivery_callback(
        state_dir=args.state_dir,
        cli_state_dir=args.cli_state_dir,
        environ=environ,
    )


def _namespace(**kwargs: object) -> Namespace:
    return Namespace(**kwargs)


def _cron_start_via_daemon(args: Namespace) -> int:
    """Start the unified Elephant daemon for cron --detach.

    The cron scheduler runs inside the unified daemon alongside IM adapters,
    supervisor, and learning worker. When ``cron start --detach`` is invoked
    we redirect to the daemon.
    """
    from apps.daemon_command import (
        daemon_is_running,
        start_daemon_detached,
        _read_pid,
        _daemon_pid_path,
    )

    state_dir = args.state_dir
    cli_state_dir = args.cli_state_dir

    if daemon_is_running(state_dir):
        pid = _read_pid(_daemon_pid_path(state_dir))
        print(f"Elephant daemon is already running (pid {pid}).")
        print("Cron is managed by the unified daemon.")
        return 0

    print("Starting unified Elephant daemon (cron, adapters, supervisor, learning)...")
    return start_daemon_detached(state_dir, cli_state_dir)


def build_typer_app(*, defaults: dict[str, Path]) -> typer.Typer:
    app = typer.Typer(
        name="elephant cron",
        help="Manage the Elephant Agent cron scheduler daemon.",
        no_args_is_help=False,
        rich_markup_mode="rich",
        add_completion=False,
    )

    def _common_args(
        state_dir: Path | None,
        cli_state_dir: Path | None,
        elephant_id: str,
    ) -> Namespace:
        return _namespace(
            state_dir=(state_dir or defaults["state_dir"]),
            cli_state_dir=(cli_state_dir or defaults.get("cli_state_dir") or defaults["state_dir"]),
            elephant_id=elephant_id,
        )

    @app.callback(invoke_without_command=True)
    def main_callback(ctx: typer.Context) -> None:
        # Only short-circuit when no subcommand was invoked; otherwise let the
        # selected subcommand run. Previously this unconditionally called
        # typer.Exit(0), which made `elephant cron start --detach` appear to
        # succeed without ever spawning the scheduler.
        if ctx.invoked_subcommand is None:
            raise typer.Exit(0)

    @app.command("start")
    def start_command(
        state_dir: Path | None = typer.Option(None, "--state-dir", hidden=True),
        cli_state_dir: Path | None = typer.Option(None, "--cli-state-dir", hidden=True),
        elephant_id: str = typer.Option("elephant:gateway", "--elephant-id", help="Scoped runtime elephant id for scheduler operations."),
        target: str = typer.Option("scheduler", "--target", help="Runtime target to inspect or launch."),
        detach: bool = typer.Option(False, "--detach", help="Start in a background process and return immediately."),
        interval_seconds: float = typer.Option(60.0, "--interval-seconds", help="Seconds between scheduler ticks."),
    ) -> None:
        args = _common_args(state_dir, cli_state_dir, elephant_id)
        args.runtime_target = target
        args.detach = detach
        args.interval_seconds = interval_seconds
        if detach:
            # Cron now runs inside the unified daemon
            raise typer.Exit(_cron_start_via_daemon(args))
        service = _build_service(args)
        raise typer.Exit(int(service.run_scheduler(interval_seconds=float(interval_seconds), once=False) or 0))

    @app.command("run")
    def run_command(
        state_dir: Path | None = typer.Option(None, "--state-dir", hidden=True),
        cli_state_dir: Path | None = typer.Option(None, "--cli-state-dir", hidden=True),
        elephant_id: str = typer.Option("elephant:gateway", "--elephant-id", help="Scoped runtime elephant id for scheduler operations."),
        target: str = typer.Option("scheduler", "--target", help="Runtime target to inspect or launch."),
        interval_seconds: float = typer.Option(60.0, "--interval-seconds", help="Seconds between scheduler ticks."),
        once: bool = typer.Option(False, "--once", help="Run one scheduler tick and exit."),
    ) -> None:
        args = _common_args(state_dir, cli_state_dir, elephant_id)
        args.runtime_target = target
        args.detach = False
        args.interval_seconds = interval_seconds
        args.once = once
        service = _build_service(args)
        raise typer.Exit(int(service.run_scheduler(interval_seconds=float(interval_seconds), once=bool(once)) or 0))

    @app.command("status")
    def status_command(
        state_dir: Path | None = typer.Option(None, "--state-dir", hidden=True),
        cli_state_dir: Path | None = typer.Option(None, "--cli-state-dir", hidden=True),
        elephant_id: str = typer.Option("elephant:gateway", "--elephant-id", help="Scoped runtime elephant id for scheduler operations."),
        target: str = typer.Option("scheduler", "--target", help="Runtime target to inspect or launch."),
    ) -> None:
        args = _common_args(state_dir, cli_state_dir, elephant_id)
        args.runtime_target = target
        service = _build_service(args)
        raise typer.Exit(_run_status(args, service=service))

    @app.command("stop")
    def stop_command(
        state_dir: Path | None = typer.Option(None, "--state-dir", hidden=True),
        cli_state_dir: Path | None = typer.Option(None, "--cli-state-dir", hidden=True),
        elephant_id: str = typer.Option("elephant:gateway", "--elephant-id", help="Scoped runtime elephant id for scheduler operations."),
        target: str = typer.Option("scheduler", "--target", help="Runtime target to inspect or launch."),
        timeout: float = typer.Option(10.0, "--timeout", help="Seconds to wait before failing or forcing."),
        force: bool = typer.Option(False, "--force", help="Send SIGKILL when the process does not exit."),
    ) -> None:
        args = _common_args(state_dir, cli_state_dir, elephant_id)
        args.runtime_target = target
        args.timeout = timeout
        args.force = force
        if daemon_is_running(args.state_dir):
            from apps.daemon_command import stop_daemon
            raise typer.Exit(stop_daemon(args.state_dir, timeout=timeout, force=force))
        print("Elephant daemon is not running. Nothing to stop.")
        raise typer.Exit(0)

    @app.command("restart")
    def restart_command(
        state_dir: Path | None = typer.Option(None, "--state-dir", hidden=True),
        cli_state_dir: Path | None = typer.Option(None, "--cli-state-dir", hidden=True),
        elephant_id: str = typer.Option("elephant:gateway", "--elephant-id", help="Scoped runtime elephant id for scheduler operations."),
        target: str = typer.Option("scheduler", "--target", help="Runtime target to inspect or launch."),
        detach: bool = typer.Option(True, "--detach/--foreground", help="Restart in the background by default, or keep it in the foreground."),
        interval_seconds: float = typer.Option(60.0, "--interval-seconds", help="Seconds between scheduler ticks."),
        timeout: float = typer.Option(10.0, "--timeout", hidden=True),
        force: bool = typer.Option(False, "--force", hidden=True),
    ) -> None:
        args = _common_args(state_dir, cli_state_dir, elephant_id)
        args.runtime_target = target
        args.detach = detach
        args.interval_seconds = interval_seconds
        args.timeout = timeout
        args.force = force
        if daemon_is_running(args.state_dir):
            from apps.daemon_command import restart_daemon
            raise typer.Exit(restart_daemon(
                args.state_dir,
                args.cli_state_dir,
                timeout=timeout,
                force=force,
            ))
        # No daemon running — start a fresh daemon
        raise typer.Exit(_cron_start_via_daemon(args))

    @app.command("logs")
    def logs_command(
        state_dir: Path | None = typer.Option(None, "--state-dir", hidden=True),
        cli_state_dir: Path | None = typer.Option(None, "--cli-state-dir", hidden=True),
        elephant_id: str = typer.Option("elephant:gateway", "--elephant-id", help="Scoped runtime elephant id for scheduler operations."),
        target: str = typer.Option("scheduler", "--target", help="Runtime target to inspect or launch."),
        tail: int = typer.Option(80, "--tail", help="Show the last N log lines."),
        follow: bool = typer.Option(False, "--follow", help="Keep streaming appended log output."),
        path: bool = typer.Option(False, "--path", help="Print the resolved log file path and exit."),
    ) -> None:
        args = _common_args(state_dir, cli_state_dir, elephant_id)
        args.runtime_target = target
        args.tail = tail
        args.follow = follow
        args.path = path
        service = _build_service(args)
        raise typer.Exit(_run_logs(args, service=service))

    return app


def main(argv: Sequence[str] | None = None) -> int:
    return command_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
