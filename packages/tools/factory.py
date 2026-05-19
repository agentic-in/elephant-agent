"""Factory helpers for assembling configured tool runtimes."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from packages.security import SecurityPolicy

from .builtins import register_builtin_tools
from .runtime import (
    ApprovalGateway,
    SecurityApprovalGateway,
    ToolContextResolver,
    ToolRuntime,
)
from .surfaces import BuiltinToolDependencies


def build_tool_runtime(
    *,
    enabled_overrides: Mapping[str, bool],
    manifest_paths: tuple[Path, ...] = (),
    dependencies: BuiltinToolDependencies,
    approval_gateway: ApprovalGateway | None = None,
    context_resolver: ToolContextResolver | None = None,
) -> ToolRuntime:
    runtime = ToolRuntime(
        approval_gateway=approval_gateway,
        context_resolver=context_resolver,
    )
    register_builtin_tools(
        runtime,
        enabled_overrides=enabled_overrides,
        dependencies=dependencies,
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
) -> ToolRuntime:
    return build_tool_runtime(
        enabled_overrides=enabled_overrides,
        manifest_paths=manifest_paths,
        dependencies=dependencies,
        context_resolver=context_resolver,
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
]
