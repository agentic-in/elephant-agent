"""Root-level app bridge for constructing CLI runtimes from other app surfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def create_cli_runtime_for_app_support(state_dir: Path, *, warm_embedding: bool = True) -> Any:
    """Build a CLI runtime for top-level app composition sources."""
    from apps.cli.runtime import CliRuntime

    return CliRuntime.create(state_dir=state_dir, warm_embedding=warm_embedding)


def create_cli_runtime_for_gateway_control(profile_dir: Path, state_dir: Path) -> Any:
    """Build the CLI runtime used by gateway remote-control bridges."""
    return create_cli_runtime_for_app_support(state_dir=state_dir)


__all__ = [
    "create_cli_runtime_for_app_support",
    "create_cli_runtime_for_gateway_control",
]
