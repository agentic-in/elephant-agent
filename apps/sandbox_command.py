"""CLI entrypoint for sandbox management.

``elephant sandbox`` provides status, configure, and doctor sub-commands
for the sandbox isolation layer.
"""

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
    from packages.operator.typer_support import run_typer_app

    resolved_argv = list(argv) if argv is not None else None
    if resolved_argv == []:
        resolved_argv = ["status"]
    return run_typer_app(
        build_typer_app(default_state_dir=default_state_dir),
        resolved_argv,
        prog_name="elephant sandbox",
    )


def _cli_runtime(state_dir: Path):
    """Inline helper — avoids app-to-app import from apps.cli.cli_main_impl."""
    from apps.cli.runtime_impl import CliRuntime
    return CliRuntime.create(state_dir=Path(state_dir).expanduser())


def build_typer_app(*, default_state_dir: Path | None = None) -> typer.Typer:
    from apps.cli.cli_main_impl import _run_sandbox_status, _run_sandbox_configure, _run_sandbox_doctor, _run_sandbox_verify

    resolved_state_dir = default_state_dir or default_cli_state_dir()

    app = typer.Typer(
        name="elephant sandbox",
        help="Inspect, configure, or diagnose the sandbox isolation layer.",
        no_args_is_help=True,
        rich_markup_mode="rich",
        add_completion=False,
    )

    @app.callback(invoke_without_command=True)
    def sandbox_root(
        ctx: typer.Context,
        state_dir: Path = typer.Option(
            str(resolved_state_dir),
            "--state-dir",
            hidden=True,
        ),
    ) -> None:
        if ctx.invoked_subcommand is None:
            runtime = _cli_runtime(state_dir)
            raise typer.Exit(_run_sandbox_status(runtime))

    @app.command("status")
    def sandbox_status(ctx: typer.Context) -> None:
        """Show current sandbox configuration and backend health."""
        runtime = _cli_runtime(ctx.parent.params["state_dir"])  # type: ignore[index]
        raise typer.Exit(_run_sandbox_status(runtime))

    @app.command("configure")
    def sandbox_configure(
        ctx: typer.Context,
        mode: str | None = typer.Option(None, "--mode", help="Sandbox mode: off, all, non-main."),
        backend: str | None = typer.Option(None, "--backend", help="Sandbox backend: local, docker, ssh, seatbelt, cloud."),
        docker_image: str | None = typer.Option(None, "--docker-image", help="Docker image for docker backend."),
        ssh_host: str | None = typer.Option(None, "--ssh-host", help="SSH host for ssh backend."),
        ssh_port: int | None = typer.Option(None, "--ssh-port", help="SSH port for ssh backend."),
        ssh_user: str | None = typer.Option(None, "--ssh-user", help="SSH user for ssh backend."),
        ssh_identity_file: str | None = typer.Option(None, "--ssh-identity-file", help="SSH identity file for ssh backend."),
        cloud_provider: str | None = typer.Option(None, "--cloud-provider", help="Cloud provider name (e.g. tencent, e2b)."),
        cloud_profile: str | None = typer.Option(None, "--cloud-profile", help="Named cloud profile to activate (from clouds config)."),
        cloud_template: str | None = typer.Option(None, "--cloud-template", help="Cloud sandbox template ID."),
        cloud_browser_template: str | None = typer.Option(None, "--cloud-browser-template", help="Cloud browser sandbox template (e.g. browser-v1)."),
        cloud_domain: str | None = typer.Option(None, "--cloud-domain", help="Cloud sandbox API domain."),
        cloud_api_key: str | None = typer.Option(None, "--cloud-api-key", help="Cloud sandbox API key."),
        cloud_timeout: int | None = typer.Option(None, "--cloud-timeout", help="Cloud sandbox timeout in seconds."),
    ) -> None:
        """Configure sandbox mode, backend, and backend-specific options."""
        runtime = _cli_runtime(ctx.parent.params["state_dir"])  # type: ignore[index]
        raise typer.Exit(_run_sandbox_configure(
            runtime,
            mode=mode,
            backend=backend,
            docker_image=docker_image,
            ssh_host=ssh_host,
            ssh_port=ssh_port,
            ssh_user=ssh_user,
            ssh_identity_file=ssh_identity_file,
            cloud_provider=cloud_provider,
            cloud_profile=cloud_profile,
            cloud_template=cloud_template,
            cloud_browser_template=cloud_browser_template,
            cloud_domain=cloud_domain,
            cloud_api_key=cloud_api_key,
            cloud_timeout=cloud_timeout,
        ))

    @app.command("doctor")
    def sandbox_doctor(ctx: typer.Context) -> None:
        """Run sandbox health diagnostics."""
        runtime = _cli_runtime(ctx.parent.params["state_dir"])  # type: ignore[index]
        raise typer.Exit(_run_sandbox_doctor(runtime))

    @app.command("verify")
    def sandbox_verify(ctx: typer.Context) -> None:
        """Run live policy probes to verify sandbox enforcement."""
        runtime = _cli_runtime(ctx.parent.params["state_dir"])  # type: ignore[index]
        raise typer.Exit(_run_sandbox_verify(runtime))

    return app
