"""CLI entrypoint for RTK terminal optimizer management."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import typer

from apps.runtime_layout import default_cli_state_dir
from packages.operator.typer_support import run_typer_app
from packages.runtime_config import (
    global_config_path_for_state_dir,
    load_global_config,
    load_rtk_from_config,
    save_rtk_to_config,
)
from packages.tools.rtk import probe_rtk, resolve_rtk_binary


def run_rtk_doctor(state_dir: Path) -> int:
    config_path = global_config_path_for_state_dir(state_dir)
    config = load_global_config(config_path, state_dir=state_dir)
    rtk_config = load_rtk_from_config(config)
    enabled = bool(rtk_config.get("enabled", False))
    binary = str(rtk_config.get("binary") or "rtk")
    timeout = int(rtk_config.get("rewrite_timeout_seconds") or 2)
    probe = probe_rtk(binary, timeout_seconds=timeout)

    print("RTK terminal optimizer")
    print(f"enabled: {'yes' if enabled else 'no'}")
    print(f"config: {config_path}")
    print(f"binary: {binary}")
    print(f"resolved_binary: {probe.binary if probe.binary else resolve_rtk_binary(binary) or '<not found>'}")
    if probe.version:
        print(f"version: {probe.version}")
    print(f"rewrite_probe: {'ok' if probe.ok else 'not-ready'}")
    if probe.rewrite_exit_code is not None:
        print(f"rewrite_exit_code: {probe.rewrite_exit_code}")
    if probe.rewrite_output:
        print(f"rewrite_output: {probe.rewrite_output}")
    if probe.error:
        print(f"error: {probe.error}")
    print("coverage: non-sandbox foreground tool.terminal.exec, large non-exact tool.file.read")
    print("out_of_scope: sandbox terminal exec, background terminal processes")
    return 0 if probe.ok or not enabled else 1


def run_rtk_start(state_dir: Path, *, binary: str | None = None) -> int:
    config_path = global_config_path_for_state_dir(state_dir)
    config = load_global_config(config_path, state_dir=state_dir)
    current = load_rtk_from_config(config)
    requested_binary = binary or str(current.get("binary") or "rtk")
    timeout = int(current.get("rewrite_timeout_seconds") or 2)
    probe = probe_rtk(requested_binary, timeout_seconds=timeout)
    if not probe.ok:
        print("RTK terminal optimizer was not enabled.")
        print(f"binary: {requested_binary}")
        if probe.error:
            print(f"error: {probe.error}")
        return 1

    payload = {
        **current,
        "enabled": True,
        "binary": probe.binary,
        "rewrite_timeout_seconds": timeout,
    }
    save_rtk_to_config(config_path, state_dir=state_dir, rtk_payload=payload)
    print("RTK terminal optimizer enabled.")
    print(f"binary: {probe.binary}")
    print("coverage: non-sandbox foreground tool.terminal.exec, large non-exact tool.file.read")
    return 0


def run_rtk_stop(state_dir: Path) -> int:
    config_path = global_config_path_for_state_dir(state_dir)
    config = load_global_config(config_path, state_dir=state_dir)
    current = load_rtk_from_config(config)
    save_rtk_to_config(
        config_path,
        state_dir=state_dir,
        rtk_payload={**current, "enabled": False},
    )
    print("RTK terminal optimizer disabled.")
    print(f"binary: {current.get('binary') or 'rtk'}")
    return 0


def command_main(
    argv: Sequence[str] | None = None,
    *,
    default_state_dir: Path | None = None,
) -> int:
    resolved_argv = list(argv) if argv is not None else None
    if resolved_argv == []:
        resolved_argv = ["doctor"]
    return run_typer_app(
        build_typer_app(default_state_dir=default_state_dir),
        resolved_argv,
        prog_name="elephant rtk",
    )


def build_typer_app(*, default_state_dir: Path | None = None) -> typer.Typer:
    resolved_state_dir = default_state_dir or default_cli_state_dir()
    app = typer.Typer(
        name="elephant rtk",
        help="Manage RTK terminal output optimization.",
        no_args_is_help=True,
        rich_markup_mode="rich",
        add_completion=False,
    )

    @app.callback(invoke_without_command=True)
    def rtk_root(
        ctx: typer.Context,
        state_dir: Path = typer.Option(
            str(resolved_state_dir),
            "--state-dir",
            hidden=True,
        ),
    ) -> None:
        if ctx.invoked_subcommand is None:
            raise typer.Exit(run_rtk_doctor(state_dir))

    @app.command("doctor")
    def rtk_doctor(ctx: typer.Context) -> None:
        """Run RTK optimizer diagnostics."""
        raise typer.Exit(run_rtk_doctor(ctx.parent.params["state_dir"]))  # type: ignore[index]

    @app.command("start")
    def rtk_start(
        ctx: typer.Context,
        binary: str | None = typer.Option(None, "--binary", help="Path or name of the rtk binary."),
    ) -> None:
        """Enable RTK rewriting for non-sandbox foreground terminal commands."""
        raise typer.Exit(run_rtk_start(ctx.parent.params["state_dir"], binary=binary))  # type: ignore[index]

    @app.command("stop")
    def rtk_stop(ctx: typer.Context) -> None:
        """Disable RTK terminal command rewriting."""
        raise typer.Exit(run_rtk_stop(ctx.parent.params["state_dir"]))  # type: ignore[index]

    return app


__all__ = ["build_typer_app", "command_main", "run_rtk_doctor", "run_rtk_start", "run_rtk_stop"]
