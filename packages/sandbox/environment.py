"""Sandbox environment facade wrapping a backend and config."""

from __future__ import annotations

from pathlib import Path

from .config import SandboxConfig
from .types import EnvironmentBackend, SandboxOutput, SessionHandle


class SandboxEnvironment:
    """High-level sandbox environment that delegates to a backend."""

    def __init__(self, config: SandboxConfig, backend: EnvironmentBackend) -> None:
        self._config = config
        self._backend = backend

    def create_session(
        self, *, session_id: str, cwd: Path, env: dict[str, str],
    ) -> SessionHandle:
        return self._backend.create_session(
            session_id=session_id, cwd=cwd, env=env,
        )

    def execute(
        self,
        handle: SessionHandle,
        command: str,
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: int | None = None,
    ) -> SandboxOutput:
        effective_timeout = timeout_seconds if timeout_seconds is not None else self._config.resource_limits.max_wall_seconds
        return self._backend.run_command(
            handle,
            command,
            cwd=cwd,
            env=env,
            timeout_seconds=effective_timeout,
        )

    def cleanup(self, handle: SessionHandle) -> None:
        self._backend.cleanup_session(handle)
