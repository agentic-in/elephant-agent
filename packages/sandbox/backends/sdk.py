"""SDK backend for sandbox execution (Phase 4).

Phase 4: Provides integration with cloud SDK backends such as Modal,
Daytona, E2B, etc.  This is a pluggable backend that delegates to
external SDK providers for strong isolation with managed infrastructure.

Each SDK provider implements the ``SDKProvider`` protocol, and the
``SDKBackend`` wraps it to conform to the ``EnvironmentBackend``
interface.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ..config import SandboxConfig
from ..security_guard import SecurityGuard
from ..types import SandboxOutput, SessionHandle


@runtime_checkable
class SDKProvider(Protocol):
    """Protocol for SDK-based sandbox providers.

    Each provider must implement these methods to integrate with the
    ``SDKBackend``.  Providers are responsible for managing their own
    remote sandbox lifecycle.
    """

    def create_sandbox(
        self, *, session_id: str, cwd: str, env: dict[str, str],
    ) -> str:
        """Create a remote sandbox and return its ID."""
        ...

    def execute(
        self,
        sandbox_id: str,
        command: str,
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: int = 120,
    ) -> tuple[int, str, str, bool]:
        """Execute a command in the sandbox.

        Returns ``(returncode, stdout, stderr, timed_out)``.
        """
        ...

    def kill(self, sandbox_id: str) -> bool:
        """Kill the sandbox. Returns True if successful."""
        ...

    def destroy(self, sandbox_id: str) -> None:
        """Destroy the sandbox and release all resources."""
        ...

    def health_check(self) -> bool:
        """Check if the SDK provider is available and authenticated."""
        ...


class SDKBackend:
    """Environment backend that delegates to an SDK provider.

    The ``SDKBackend`` wraps an ``SDKProvider`` to conform to the
    ``EnvironmentBackend`` protocol.  This allows the sandbox system
    to use any cloud-based sandbox provider (Modal, Daytona, E2B, etc.)
    through a uniform interface.
    """

    BACKEND_ID = "sdk"

    def __init__(
        self,
        config: SandboxConfig,
        *,
        provider: SDKProvider,
    ) -> None:
        self._config = config
        self._provider = provider
        self._security_guard = SecurityGuard()
        self._sessions: dict[str, SessionHandle] = {}

    # ------------------------------------------------------------------
    # EnvironmentBackend protocol
    # ------------------------------------------------------------------

    def create_session(
        self, *, session_id: str, cwd: Path, env: dict[str, str],
    ) -> SessionHandle:
        sandbox_root = Path(tempfile.mkdtemp(prefix="elephant-sandbox-sdk-"))
        snapshot_path = sandbox_root / ".snapshot.sh"
        cwd_file = sandbox_root / ".cwd"

        cwd_file.write_text(str(cwd), encoding="utf-8")
        snapshot_path.write_text(
            f"# Elephant SDK sandbox snapshot for session {session_id}\n",
            encoding="utf-8",
        )

        # Create the remote sandbox via the SDK provider
        sandbox_id = self._provider.create_sandbox(
            session_id=session_id,
            cwd=str(cwd),
            env=self._security_guard.sanitize_env(
                dict(__import__("os").environ), extra_env=env,
            ),
        )

        handle = SessionHandle(
            session_id=session_id,
            backend_id=self.BACKEND_ID,
            sandbox_root=sandbox_root,
            cwd=cwd,
            snapshot_path=snapshot_path,
            cwd_file=cwd_file,
            attachments=(sandbox_id,),
        )
        self._sessions[session_id] = handle
        return handle

    def run_command(
        self,
        handle: SessionHandle,
        command: str,
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: int = 120,
    ) -> SandboxOutput:
        sandbox_id = self._sandbox_id(handle)
        if sandbox_id is None:
            return SandboxOutput(
                stdout="",
                stderr="SDK sandbox not found",
                returncode=1,
                cwd=None,
                timed_out=False,
                diagnostics=("sandbox_not_found",),
            )

        effective_cwd = str(cwd) if cwd is not None else str(handle.cwd)

        sanitized_env = None
        if env:
            sanitized_env = self._security_guard.sanitize_env(
                dict(__import__("os").environ), extra_env=env,
            )

        returncode, stdout, stderr, timed_out = self._provider.execute(
            sandbox_id,
            command,
            cwd=effective_cwd,
            env=sanitized_env,
            timeout_seconds=timeout_seconds,
        )

        # Truncate output
        limits = self._config.resource_limits
        stdout_text = _truncate(stdout, limits.max_stdout_bytes)
        stderr_text = _truncate(stderr, limits.max_stderr_bytes)

        diagnostics: list[str] = []
        if timed_out:
            diagnostics.append(f"command timed out after {timeout_seconds}s")
        if len(stdout.encode("utf-8", errors="replace")) > limits.max_stdout_bytes:
            diagnostics.append("stdout truncated")
        if len(stderr.encode("utf-8", errors="replace")) > limits.max_stderr_bytes:
            diagnostics.append("stderr truncated")

        return SandboxOutput(
            stdout=stdout_text,
            stderr=stderr_text,
            returncode=returncode,
            cwd=Path(effective_cwd),
            timed_out=timed_out,
            diagnostics=tuple(diagnostics),
        )

    def kill_process(self, handle: SessionHandle, pid: int) -> bool:
        sandbox_id = self._sandbox_id(handle)
        if sandbox_id is None:
            return False
        return self._provider.kill(sandbox_id)

    def read_cwd(self, handle: SessionHandle) -> Path:
        try:
            return Path(handle.cwd_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return handle.cwd

    def cleanup_session(self, handle: SessionHandle) -> None:
        sandbox_id = self._sandbox_id(handle)
        self._sessions.pop(handle.session_id, None)

        if sandbox_id is not None:
            try:
                self._provider.destroy(sandbox_id)
            except Exception:
                pass

        try:
            shutil.rmtree(handle.sandbox_root)
        except OSError:
            pass

    def health_check(self) -> bool:
        return self._provider.health_check()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sandbox_id(self, handle: SessionHandle) -> str | None:
        if handle.attachments:
            return handle.attachments[0]
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _truncate(text: str, max_bytes: int) -> str:
    """Truncate text to approximately *max_bytes* UTF-8 bytes."""
    raw = text.encode("utf-8", errors="replace")
    if len(raw) <= max_bytes:
        return text.strip()

    head_size = max_bytes // 2
    tail_size = max_bytes - head_size
    head = raw[:head_size].decode("utf-8", errors="replace")
    tail = raw[-tail_size:].decode("utf-8", errors="replace")
    omitted = len(raw) - head_size - tail_size
    return f"{head.rstrip()}\n... [output truncated, {omitted:,} bytes omitted] ...\n{tail.lstrip()}".strip()
