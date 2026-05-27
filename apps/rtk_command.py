"""CLI entrypoint for RTK terminal optimizer management."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import typer

from apps.runtime_layout import default_cli_state_dir


def command_main(
    argv: Sequence[str] | None = None,
    *,
    default_state_dir: Path | None = None,
) -> int:
    from apps.cli.typer_support import run_typer_app

    resolved_argv = list(argv) if argv is not None else None
    if resolved_argv == []:
        resolved_argv = ["doctor"]
    return run_typer_app(
        build_typer_app(default_state_dir=default_state_dir),
        resolved_argv,
        prog_name="elephant rtk",
    )


def build_typer_app(*, default_state_dir: Path | None = None) -> typer.Typer:
    from apps.cli.rtk_support import run_rtk_doctor, run_rtk_start, run_rtk_stop

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


__all__ = ["build_typer_app", "command_main"]
