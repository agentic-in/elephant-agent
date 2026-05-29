"""CLI entrypoint for sandbox management.

``elephant sandbox`` provides on/off/status/allow/deny sub-commands
for the sandbox isolation layer with a mode-based abstraction.

New commands (sandbox-ux):
  - elephant sandbox on [--mode readonly|safe|dev|open]
  - elephant sandbox off
  - elephant sandbox status
  - elephant sandbox allow network/read/write/env
  - elephant sandbox deny network/read/write/env
  - elephant sandbox doctor
  - elephant sandbox verify

Legacy commands (backward compat):
  - elephant sandbox configure (still works for old-format config)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Sequence

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
    """Inline helper -- avoids app-to-app import from apps.cli.cli_main_impl."""
    from apps.cli.runtime_impl import CliRuntime
    return CliRuntime.create(state_dir=Path(state_dir).expanduser())


def _load_sandbox_config(runtime):
    """Load sandbox config from config.yaml, falling back to defaults."""
    from packages.runtime_config import load_global_config, load_sandbox_from_config, global_config_path_for_state_dir
    from packages.sandbox.config import SandboxConfig

    config_path = global_config_path_for_state_dir(runtime.paths.state_dir)
    try:
        global_config = load_global_config(config_path, state_dir=runtime.paths.state_dir)
    except OSError:
        return SandboxConfig()
    section = load_sandbox_from_config(global_config)
    if not section:
        return SandboxConfig()
    return SandboxConfig.from_config_section(section)


def _save_sandbox_config(runtime, config) -> None:
    """Persist sandbox config to config.yaml."""
    from packages.runtime_config import save_sandbox_to_config, global_config_path_for_state_dir
    config_path = global_config_path_for_state_dir(runtime.paths.state_dir)
    save_sandbox_to_config(
        config_path,
        state_dir=runtime.paths.state_dir,
        sandbox_payload=config.to_config_section(),
    )


def build_typer_app(*, default_state_dir: Path | None = None) -> typer.Typer:
    from apps.cli.cli_main_impl import _run_sandbox_doctor, _run_sandbox_verify

    resolved_state_dir = default_state_dir or default_cli_state_dir()

    app = typer.Typer(
        name="elephant sandbox",
        help="Manage sandbox isolation: on/off, modes, allow/deny overrides.",
        no_args_is_help=True,
        rich_markup_mode="rich",
        add_completion=False,
    )

    # --- Shared state-dir option via callback ---

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
            raise typer.Exit(_run_status(runtime))

    # ------------------------------------------------------------------
    # elephant sandbox on [--mode MODE]
    # ------------------------------------------------------------------

    @app.command("on")
    def sandbox_on(
        ctx: typer.Context,
        mode: str = typer.Option("safe", "--mode", "-m", help="Mode: readonly, safe, dev, open."),
    ) -> None:
        """Enable the sandbox (default mode: safe)."""
        from packages.sandbox.config import SandboxConfig, _NEW_MODE_VALUES

        valid_modes = ("readonly", "safe", "dev", "open")
        if mode not in valid_modes:
            typer.echo(f"Error: invalid mode '{mode}'. Choose from: {', '.join(valid_modes)}", err=True)
            raise typer.Exit(1)

        runtime = _cli_runtime(ctx.parent.params["state_dir"])  # type: ignore[index]
        config = _load_sandbox_config(runtime)

        # Build new config with the specified mode
        new_config = SandboxConfig(
            mode=mode,
            backend="seatbelt",
            scope=config.scope,
            workspace_access="ro" if mode == "readonly" else "rw",
            resource_limits=config.resource_limits,
            seatbelt=config.seatbelt,
            cloud=config.cloud,
            clouds=config.clouds,
            cloud_profile=config.cloud_profile,
            allow_delta=config.allow_delta,
            deny_delta=config.deny_delta,
        )
        _save_sandbox_config(runtime, new_config)
        typer.echo(f"Sandbox ON (mode: {mode})")
        raise typer.Exit(0)

    # ------------------------------------------------------------------
    # elephant sandbox off
    # ------------------------------------------------------------------

    @app.command("off")
    def sandbox_off(ctx: typer.Context) -> None:
        """Disable the sandbox."""
        from packages.sandbox.config import SandboxConfig

        runtime = _cli_runtime(ctx.parent.params["state_dir"])  # type: ignore[index]
        config = _load_sandbox_config(runtime)

        new_config = SandboxConfig(
            mode="off",
            backend=config.backend,
            scope=config.scope,
            workspace_access=config.workspace_access,
            resource_limits=config.resource_limits,
            seatbelt=config.seatbelt,
            cloud=config.cloud,
            clouds=config.clouds,
            cloud_profile=config.cloud_profile,
            allow_delta=config.allow_delta,
            deny_delta=config.deny_delta,
        )
        _save_sandbox_config(runtime, new_config)
        typer.echo("Sandbox OFF")
        raise typer.Exit(0)

    # ------------------------------------------------------------------
    # elephant sandbox status
    # ------------------------------------------------------------------

    @app.command("status")
    def sandbox_status(ctx: typer.Context) -> None:
        """Show current sandbox configuration and status."""
        runtime = _cli_runtime(ctx.parent.params["state_dir"])  # type: ignore[index]
        raise typer.Exit(_run_status(runtime))

    # ------------------------------------------------------------------
    # elephant sandbox allow
    # ------------------------------------------------------------------

    allow_app = typer.Typer(
        name="allow",
        help="Relax sandbox restrictions (add allow overrides).",
        no_args_is_help=True,
    )
    app.add_typer(allow_app, name="allow")

    @allow_app.command("network")
    def allow_network(ctx: typer.Context) -> None:
        """Allow network access (override mode's network restriction)."""
        runtime = _cli_runtime(ctx.parent.parent.params["state_dir"])  # type: ignore[index]
        config = _load_sandbox_config(runtime)
        allow = dict(config.allow_delta)
        allow["network"] = True
        # Remove deny.network if set
        deny = dict(config.deny_delta)
        deny.pop("network", None)
        new_config = _replace_deltas(config, allow_delta=allow, deny_delta=deny)
        _save_sandbox_config(runtime, new_config)
        typer.echo("Allowed: network access")
        raise typer.Exit(0)

    @allow_app.command("read")
    def allow_read(
        ctx: typer.Context,
        path: str = typer.Argument(..., help="Path to allow reading."),
    ) -> None:
        """Allow reading a specific path."""
        runtime = _cli_runtime(ctx.parent.parent.params["state_dir"])  # type: ignore[index]
        config = _load_sandbox_config(runtime)
        allow = dict(config.allow_delta)
        read_list = list(allow.get("read") or [])
        if path not in read_list:
            read_list.append(path)
        allow["read"] = read_list
        new_config = _replace_deltas(config, allow_delta=allow)
        _save_sandbox_config(runtime, new_config)
        typer.echo(f"Allowed: read {path}")
        raise typer.Exit(0)

    @allow_app.command("write")
    def allow_write(
        ctx: typer.Context,
        path: str = typer.Argument(..., help="Path to allow writing."),
    ) -> None:
        """Allow writing to a specific path."""
        runtime = _cli_runtime(ctx.parent.parent.params["state_dir"])  # type: ignore[index]
        config = _load_sandbox_config(runtime)
        allow = dict(config.allow_delta)
        write_list = list(allow.get("write") or [])
        if path not in write_list:
            write_list.append(path)
        allow["write"] = write_list
        new_config = _replace_deltas(config, allow_delta=allow)
        _save_sandbox_config(runtime, new_config)
        typer.echo(f"Allowed: write {path}")
        raise typer.Exit(0)

    @allow_app.command("env")
    def allow_env(
        ctx: typer.Context,
        var_name: str = typer.Argument(..., help="Environment variable to exempt from filtering."),
    ) -> None:
        """Exempt an environment variable from secret filtering."""
        runtime = _cli_runtime(ctx.parent.parent.params["state_dir"])  # type: ignore[index]
        config = _load_sandbox_config(runtime)
        allow = dict(config.allow_delta)
        env_list = list(allow.get("env") or [])
        if var_name not in env_list:
            env_list.append(var_name)
        allow["env"] = env_list
        new_config = _replace_deltas(config, allow_delta=allow)
        _save_sandbox_config(runtime, new_config)
        typer.echo(f"Allowed: env {var_name}")
        raise typer.Exit(0)

    # ------------------------------------------------------------------
    # elephant sandbox deny
    # ------------------------------------------------------------------

    deny_app = typer.Typer(
        name="deny",
        help="Tighten sandbox restrictions (add deny overrides).",
        no_args_is_help=True,
    )
    app.add_typer(deny_app, name="deny")

    @deny_app.command("network")
    def deny_network(ctx: typer.Context) -> None:
        """Deny network access (override mode's network setting)."""
        runtime = _cli_runtime(ctx.parent.parent.params["state_dir"])  # type: ignore[index]
        config = _load_sandbox_config(runtime)
        deny = dict(config.deny_delta)
        deny["network"] = True
        # Remove allow.network if set
        allow = dict(config.allow_delta)
        allow.pop("network", None)
        new_config = _replace_deltas(config, allow_delta=allow, deny_delta=deny)
        _save_sandbox_config(runtime, new_config)
        typer.echo("Denied: network access")
        raise typer.Exit(0)

    @deny_app.command("read")
    def deny_read(
        ctx: typer.Context,
        path: str = typer.Argument(..., help="Glob pattern to deny reading."),
    ) -> None:
        """Deny reading paths matching a glob pattern."""
        runtime = _cli_runtime(ctx.parent.parent.params["state_dir"])  # type: ignore[index]
        config = _load_sandbox_config(runtime)
        deny = dict(config.deny_delta)
        read_list = list(deny.get("read") or [])
        if path not in read_list:
            read_list.append(path)
        deny["read"] = read_list
        new_config = _replace_deltas(config, deny_delta=deny)
        _save_sandbox_config(runtime, new_config)
        typer.echo(f"Denied: read {path}")
        raise typer.Exit(0)

    @deny_app.command("write")
    def deny_write(
        ctx: typer.Context,
        path: str = typer.Argument(..., help="Path to deny writing."),
    ) -> None:
        """Deny writing to a specific path."""
        runtime = _cli_runtime(ctx.parent.parent.params["state_dir"])  # type: ignore[index]
        config = _load_sandbox_config(runtime)
        deny = dict(config.deny_delta)
        write_list = list(deny.get("write") or [])
        if path not in write_list:
            write_list.append(path)
        deny["write"] = write_list
        new_config = _replace_deltas(config, deny_delta=deny)
        _save_sandbox_config(runtime, new_config)
        typer.echo(f"Denied: write {path}")
        raise typer.Exit(0)

    @deny_app.command("env")
    def deny_env(
        ctx: typer.Context,
        var_name: str = typer.Argument(..., help="Environment variable to force-filter."),
    ) -> None:
        """Force-filter an environment variable."""
        runtime = _cli_runtime(ctx.parent.parent.params["state_dir"])  # type: ignore[index]
        config = _load_sandbox_config(runtime)
        deny = dict(config.deny_delta)
        env_list = list(deny.get("env") or [])
        if var_name not in env_list:
            env_list.append(var_name)
        deny["env"] = env_list
        new_config = _replace_deltas(config, deny_delta=deny)
        _save_sandbox_config(runtime, new_config)
        typer.echo(f"Denied: env {var_name}")
        raise typer.Exit(0)

    # ------------------------------------------------------------------
    # Legacy: elephant sandbox configure (backward compat)
    # ------------------------------------------------------------------

    @app.command("configure", hidden=True)
    def sandbox_configure(
        ctx: typer.Context,
        mode: str | None = typer.Option(None, "--mode", help="Sandbox mode: off, all, non-main, readonly, safe, dev, open."),
        backend: str | None = typer.Option(None, "--backend", help="Sandbox backend: local, docker, ssh, seatbelt, cloud."),
        docker_image: str | None = typer.Option(None, "--docker-image", help="Docker image for docker backend."),
        ssh_host: str | None = typer.Option(None, "--ssh-host", help="SSH host for ssh backend."),
        ssh_port: int | None = typer.Option(None, "--ssh-port", help="SSH port for ssh backend."),
        ssh_user: str | None = typer.Option(None, "--ssh-user", help="SSH user for ssh backend."),
        ssh_identity_file: str | None = typer.Option(None, "--ssh-identity-file", help="SSH identity file."),
        cloud_provider: str | None = typer.Option(None, "--cloud-provider", help="Cloud provider name."),
        cloud_profile: str | None = typer.Option(None, "--cloud-profile", help="Named cloud profile."),
        cloud_template: str | None = typer.Option(None, "--cloud-template", help="Cloud sandbox template ID."),
        cloud_browser_template: str | None = typer.Option(None, "--cloud-browser-template", help="Cloud browser template."),
        cloud_domain: str | None = typer.Option(None, "--cloud-domain", help="Cloud sandbox API domain."),
        cloud_api_key: str | None = typer.Option(None, "--cloud-api-key", help="Cloud sandbox API key."),
        cloud_timeout: int | None = typer.Option(None, "--cloud-timeout", help="Cloud sandbox timeout."),
    ) -> None:
        """Configure sandbox (legacy format). Use 'on/off/allow/deny' instead."""
        from apps.cli.cli_main_impl import _run_sandbox_configure
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

    # ------------------------------------------------------------------
    # elephant sandbox violations
    # ------------------------------------------------------------------

    @app.command("violations")
    def sandbox_violations(
        ctx: typer.Context,
        limit: int = typer.Option(20, "--limit", "-n", help="Number of recent violations to show."),
        clear: bool = typer.Option(False, "--clear", help="Clear violation history."),
    ) -> None:
        """Show recent sandbox-denied operations."""
        from packages.sandbox.violations import ViolationStore
        from pathlib import Path

        # Violations are global (not per-herd), stored in ~/.elephant/
        store = ViolationStore(Path.home() / ".elephant")

        if clear:
            count = store.clear()
            typer.echo(f"Cleared {count} violation(s).")
            raise typer.Exit(0)

        violations = store.recent(limit=limit)
        if not violations:
            typer.echo("No sandbox violations recorded.")
            typer.echo("  Violations are logged when sandbox blocks an operation.")
            raise typer.Exit(0)

        typer.echo(f"Recent sandbox violations ({len(violations)} entries):\n")
        for v in violations:
            typer.echo(f"  {v.format_short()}")
            if v.command:
                typer.echo(f"     Command: {v.command}")
            typer.echo("")

        typer.echo(f"Log: {store.log_path}")
        typer.echo("Tip: use --clear to reset, or `elephant sandbox allow` to permit operations.")
        raise typer.Exit(0)

    # ------------------------------------------------------------------
    # elephant sandbox doctor
    # ------------------------------------------------------------------

    @app.command("doctor")
    def sandbox_doctor(ctx: typer.Context) -> None:
        """Run sandbox health diagnostics."""
        runtime = _cli_runtime(ctx.parent.params["state_dir"])  # type: ignore[index]
        raise typer.Exit(_run_sandbox_doctor(runtime))

    # ------------------------------------------------------------------
    # elephant sandbox verify
    # ------------------------------------------------------------------

    @app.command("verify")
    def sandbox_verify(ctx: typer.Context) -> None:
        """Run live policy probes to verify sandbox enforcement."""
        runtime = _cli_runtime(ctx.parent.params["state_dir"])  # type: ignore[index]
        raise typer.Exit(_run_sandbox_verify(runtime))

    return app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _replace_deltas(
    config,
    *,
    allow_delta: dict[str, Any] | None = None,
    deny_delta: dict[str, Any] | None = None,
):
    """Create a new SandboxConfig with updated allow/deny deltas."""
    from packages.sandbox.config import SandboxConfig

    return SandboxConfig(
        mode=config.mode,
        backend=config.backend,
        scope=config.scope,
        workspace_access=config.workspace_access,
        resource_limits=config.resource_limits,
        docker=config.docker,
        ssh=config.ssh,
        seatbelt=config.seatbelt,
        cloud=config.cloud,
        clouds=config.clouds,
        cloud_profile=config.cloud_profile,
        allow_delta=allow_delta if allow_delta is not None else config.allow_delta,
        deny_delta=deny_delta if deny_delta is not None else config.deny_delta,
    )


def _run_status(runtime) -> int:
    """Render sandbox status in the new format."""
    from packages.sandbox.config import _NEW_MODE_VALUES

    config = _load_sandbox_config(runtime)

    if not config.is_active:
        typer.echo("Sandbox: OFF")
        typer.echo("  Run `elephant sandbox on` to enable (default mode: safe)")
        return 0

    # Count overrides
    override_count = 0
    allow = config.allow_delta
    deny = config.deny_delta
    if allow.get("network"):
        override_count += 1
    if deny.get("network"):
        override_count += 1
    override_count += len(allow.get("read") or [])
    override_count += len(allow.get("write") or [])
    override_count += len(allow.get("env") or [])
    override_count += len(deny.get("read") or [])
    override_count += len(deny.get("write") or [])
    override_count += len(deny.get("env") or [])

    override_suffix = f" + {override_count} overrides" if override_count else ""

    if config.is_new_mode:
        typer.echo(f"Sandbox: ON ({config.mode}{override_suffix})")
        typer.echo(f"  Platform:  macOS (seatbelt)")
        typer.echo("")

        # Network status
        if config.mode in ("dev", "open"):
            net_status = "open"
        else:
            net_status = "isolated"
        # Apply overrides
        if allow.get("network"):
            net_status = "open (allow override)"
        if deny.get("network"):
            net_status = "denied (deny override)"
        typer.echo(f"  Network: {net_status}")

        # Writable
        typer.echo("  Writable:")
        if config.mode != "readonly":
            typer.echo("    + cwd (workspace)")
        for p in (allow.get("write") or []):
            typer.echo(f"    + {p} (allow)")
        typer.echo("    - .git/hooks (protected)")
        typer.echo("    - .claude/settings* (protected)")

        # Readable
        typer.echo("  Readable:")
        if config.mode == "open":
            typer.echo("    + all paths")
        else:
            typer.echo("    + system whitelist + cwd")
        for p in (allow.get("read") or []):
            typer.echo(f"    + {p} (allow)")
        typer.echo("    - ~/.ssh, ~/.aws, ~/.gnupg (protected)")
        for p in (deny.get("read") or []):
            typer.echo(f"    - {p} (deny)")

        # Env
        exempt_env = allow.get("env") or []
        if exempt_env:
            typer.echo(f"  Env exempted: {', '.join(exempt_env)}")
        typer.echo("  Env filtered: KEY/TOKEN/SECRET/PASSWORD")
    else:
        # Legacy status display
        typer.echo(f"Sandbox: ON (legacy mode: {config.mode})")
        typer.echo(f"  Backend:  {config.backend}")
        typer.echo(f"  Scope:    {config.scope}")
        typer.echo(f"  Access:   {config.workspace_access}")
        if config.backend == "seatbelt":
            typer.echo(f"  Network:  {'open' if config.seatbelt.allow_network else 'isolated'}")

    return 0
