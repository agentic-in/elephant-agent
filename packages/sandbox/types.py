"""Core type definitions for the sandbox package."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class SandboxOutput:
    """Captured output from a sandboxed command execution."""

    stdout: str
    stderr: str
    returncode: int
    cwd: Path | None = None
    timed_out: bool = False
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SessionHandle:
    """Handle for an active sandbox session."""

    session_id: str
    backend_id: str
    sandbox_root: Path
    cwd: Path
    snapshot_path: Path
    cwd_file: Path
    attachments: tuple[str, ...] = ()


@runtime_checkable
class EnvironmentBackend(Protocol):
    """Protocol for sandbox environment backends."""

    def create_session(
        self, *, session_id: str, cwd: Path, env: dict[str, str]
    ) -> SessionHandle: ...

    def run_command(
        self,
        handle: SessionHandle,
        command: str,
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: int = 120,
    ) -> SandboxOutput: ...

    def kill_process(self, handle: SessionHandle, pid: int) -> bool: ...

    def read_cwd(self, handle: SessionHandle) -> Path: ...

    def cleanup_session(self, handle: SessionHandle) -> None: ...

    def health_check(self) -> bool: ...
