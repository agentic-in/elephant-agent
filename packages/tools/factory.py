"""Factory helpers for assembling configured tool runtimes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, TYPE_CHECKING

from packages.runtime_config import load_rtk_from_config, load_sandbox_from_config, global_config_path_for_state_dir
from packages.security import SecurityPolicy

from .builtins import register_builtin_tools
from .runtime import ApprovalGateway, InMemoryToolExecutor, SecurityApprovalGateway, ToolContextResolver, ToolRuntime
from .surfaces import BuiltinToolDependencies

if TYPE_CHECKING:
    from packages.sandbox import SandboxConfig


def sandbox_config_from_state_dir(state_dir: str | Path) -> SandboxConfig | None:
    """Load the ``SandboxConfig`` from ``config.yaml`` if sandbox is active.

    Returns ``None`` when the sandbox section is missing or mode is ``off``.
    """
    from packages.sandbox import SandboxConfig

    config_path = global_config_path_for_state_dir(state_dir)
    try:
        from packages.runtime_config import load_global_config
        global_config = load_global_config(config_path, state_dir=state_dir)
    except OSError:
        return None
    section = load_sandbox_from_config(global_config)
    if not section:
        return None
    cfg = SandboxConfig.from_config_section(section)
    if not cfg.is_active:
        return None
    return cfg


def rtk_command_rewriter_from_state_dir(state_dir: str | Path):
    """Load the RTK terminal command rewriter from ``config.yaml`` if enabled."""
    config_path = global_config_path_for_state_dir(state_dir)
    try:
        from packages.runtime_config import load_global_config
        global_config = load_global_config(config_path, state_dir=state_dir)
    except OSError:
        return None
    rtk_config = load_rtk_from_config(global_config)
    if not bool(rtk_config.get("enabled", False)):
        return None
    from .rtk import RtkCommandRewriter

    return RtkCommandRewriter.from_config(rtk_config)


def build_tool_runtime(
    *,
    enabled_overrides: Mapping[str, bool],
    manifest_paths: tuple[Path, ...] = (),
    dependencies: BuiltinToolDependencies,
    approval_gateway: ApprovalGateway | None = None,
    context_resolver: ToolContextResolver | None = None,
    sandbox_config: SandboxConfig | None = None,
    state_dir: str | Path | None = None,
    sandbox_event_sink: Any | None = None,
    sandbox_event_source: str = "tool.runtime.sandbox",
) -> ToolRuntime:
    # Build the base executor; sandbox wraps it if active
    base_executor = InMemoryToolExecutor()

    # Auto-load sandbox config from config.yaml if not provided explicitly
    if sandbox_config is None and state_dir is not None:
        sandbox_config = sandbox_config_from_state_dir(state_dir)

    import logging as _logging
    _log = _logging.getLogger(__name__)
    effective_dependencies = dependencies
    terminal_command_rewriter = None
    if state_dir is not None:
        terminal_command_rewriter = rtk_command_rewriter_from_state_dir(state_dir)
    if terminal_command_rewriter is not None:
        effective_dependencies = replace(
            effective_dependencies,
            terminal_command_rewriter=terminal_command_rewriter,
            file_read_optimizer=terminal_command_rewriter,
        )

    if sandbox_config is not None and sandbox_config.is_active:
        from packages.sandbox import (
            SandboxEnvironment,
            SandboxProcessManager,
            SandboxToolExecutor,
            SecurityGuard,
        )
        from packages.sandbox.path_mapper import SandboxPathMapper
        from packages.runtime_layout import default_workspaces_dir, infer_install_root_from_state_dir

        # Build unified path mapper
        workspaces_dir: Path | None = None
        if state_dir is not None:
            install_root = infer_install_root_from_state_dir(Path(state_dir))
            workspaces_dir = default_workspaces_dir(install_root=install_root)
        sandbox_path_mapper = SandboxPathMapper(
            workspaces_dir=workspaces_dir,
            startup_cwd=dependencies.cwd,
        )

        # Inject browser sandbox env vars when cloud backend has browser_template
        if sandbox_config.backend == "cloud":
            _cloud_profile = sandbox_config.effective_cloud()
            if _cloud_profile.browser_template:
                import os as _os
                _os.environ.setdefault("ELEPHANT_BROWSER_CLOUD_PROVIDER", "tencent-cloud")
                _os.environ.setdefault("ELEPHANT_BROWSER_CLOUD_TEMPLATE", _cloud_profile.browser_template)
                if _cloud_profile.domain:
                    _os.environ.setdefault("E2B_DOMAIN", _cloud_profile.domain)
                if _cloud_profile.api_key:
                    _os.environ.setdefault("E2B_API_KEY", _cloud_profile.api_key)

        # Select backend based on config
        if sandbox_config.backend == "docker":
            from packages.sandbox.backends.docker import DockerBackend
            sandbox_backend = DockerBackend(sandbox_config)
        elif sandbox_config.backend == "ssh":
            from packages.sandbox.backends.ssh import SSHBackend

            ssh_opts = sandbox_config.ssh
            ssh_host = ssh_opts.host
            if not ssh_host:
                raise ValueError(
                    "SSH sandbox backend requires sandbox.ssh.host in config.yaml"
                )
            sandbox_backend = SSHBackend(
                sandbox_config,
                host=ssh_host,
                port=ssh_opts.port,
                user=ssh_opts.user or None,
                identity_file=(
                    Path(ssh_opts.identity_file)
                    if ssh_opts.identity_file
                    else None
                ),
            )
        elif sandbox_config.backend == "seatbelt":
            from packages.sandbox.backends.seatbelt import SeatbeltBackend
            sandbox_backend = SeatbeltBackend(sandbox_config)
            if not sandbox_backend.health_check():
                # Fall back to local if Seatbelt is not available
                from packages.sandbox.backends.local import LocalBackend
                sandbox_backend = LocalBackend(sandbox_config)
        elif sandbox_config.backend == "cloud":
            from packages.sandbox.backends.cloud_registry import get_cloud_backend
            sandbox_backend = get_cloud_backend(sandbox_config)
            # Inject path mapper into cloud backend
            if hasattr(sandbox_backend, "_path_mapper"):
                sandbox_backend._path_mapper = sandbox_path_mapper
            _log.debug("🛡️ Cloud sandbox backend created: %s health=%s", type(sandbox_backend).__name__, sandbox_backend.health_check())
            if not sandbox_backend.health_check():
                _log.warning("🛡️ Cloud backend health check FAILED, falling back to local")
                from packages.sandbox.backends.local import LocalBackend
                sandbox_backend = LocalBackend(sandbox_config)
        else:
            from packages.sandbox.backends.local import LocalBackend
            sandbox_backend = LocalBackend(sandbox_config)

        _log.debug("🛡️ Sandbox active: mode=%s backend=%s backend_class=%s",
                  sandbox_config.mode, sandbox_config.backend, type(sandbox_backend).__name__)
        sandbox_env = SandboxEnvironment(sandbox_config, sandbox_backend)
        sandbox_guard = SecurityGuard()
        sandbox_process_manager = SandboxProcessManager(
            config=sandbox_config,
            environment=sandbox_env,
            security_guard=sandbox_guard,
        )
        effective_dependencies = replace(
            effective_dependencies,
            process_manager=sandbox_process_manager,
        )
        executor: InMemoryToolExecutor | SandboxToolExecutor = SandboxToolExecutor(
            base_executor,
            sandbox_config,
            sandbox_env,
            sandbox_guard,
            path_mapper=sandbox_path_mapper,
            allowed_roots=(
                dependencies.cwd,
                *dependencies.additional_allowed_roots,
            ),
            cwd_resolver=dependencies.cwd_resolver,
            process_manager=sandbox_process_manager,
            event_sink=sandbox_event_sink,
            event_source=sandbox_event_source,
        )
    else:
        _log.debug("🛡️ Sandbox NOT active: config=%s is_active=%s",
                  type(sandbox_config).__name__ if sandbox_config else "None",
                  sandbox_config.is_active if sandbox_config else "N/A")
        executor = base_executor

    runtime = ToolRuntime(
        executor=executor,
        approval_gateway=approval_gateway,
        context_resolver=context_resolver,
    )
    register_builtin_tools(
        runtime,
        enabled_overrides=enabled_overrides,
        dependencies=effective_dependencies,
    )
    for path in manifest_paths:
        runtime.load_manifest(path)
    return runtime


def build_secured_tool_runtime(
    *,
    enabled_overrides: Mapping[str, bool],
    manifest_paths: tuple[Path, ...] = (),
    dependencies: BuiltinToolDependencies,
    security_policy: SecurityPolicy,
    telemetry: Any,
    source: str,
    auto_approve_deferred: bool = True,
    context_resolver: ToolContextResolver | None = None,
    sandbox_config: SandboxConfig | None = None,
    state_dir: str | Path | None = None,
) -> ToolRuntime:
    return build_tool_runtime(
        enabled_overrides=enabled_overrides,
        manifest_paths=manifest_paths,
        dependencies=dependencies,
        context_resolver=context_resolver,
        sandbox_config=sandbox_config,
        state_dir=state_dir,
        sandbox_event_sink=telemetry,
        sandbox_event_source=f"{source}.sandbox",
        approval_gateway=SecurityApprovalGateway(
            policy=security_policy,
            telemetry=telemetry,
            source=source,
            auto_approve_deferred=auto_approve_deferred,
        ),
    )


__all__ = [
    "build_secured_tool_runtime",
    "build_tool_runtime",
    "rtk_command_rewriter_from_state_dir",
    "sandbox_config_from_state_dir",
]
