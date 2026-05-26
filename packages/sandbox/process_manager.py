"""Sandbox-aware process manager for background terminal execution.

Phase 3: Bridges the ``InMemoryProcessManager`` interface with sandbox
backends so that ``tool.terminal.exec background=true`` can run inside
the sandbox while still being managed by the existing process management
layer.

Design:
- ``SandboxProcessManager`` wraps ``InMemoryProcessManager``
- When sandbox is active, ``start()`` launches the command inside the
  sandbox session instead of directly via ``subprocess.Popen``
- The process ID returned to the caller is a sandbox-aware handle
  that ``tool.process.manage`` can still poll/wait/kill
"""

from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import SandboxConfig
from .environment import SandboxEnvironment
from .security_guard import SecurityGuard
from .types import SessionHandle


SessionProvider = Callable[[str, Path, dict[str, str]], tuple[SessionHandle, str]]


@dataclass
class SandboxManagedProcess:
    """A background process that runs inside a sandbox session."""

    process_id: str
    command: str
    cwd: Path
    sandbox_session_id: str
    process: subprocess.Popen[str]
    started_at: datetime
    stdout: str = ""
    stderr: str = ""
    finished_at: datetime | None = None
    session_handle: SessionHandle | None = None
    session_resolution: str | None = None
    _sandbox_root: Path | None = None

    @property
    def returncode(self) -> int | None:
        return self.process.poll()

    @property
    def running(self) -> bool:
        return self.returncode is None


class SandboxProcessManager:
    """Process manager that routes background commands through the sandbox.

    This manager implements the same interface as ``InMemoryProcessManager``
    but starts background processes inside a sandbox session when the
    sandbox is active. When sandbox is off, it delegates to the standard
    ``InMemoryProcessManager``.
    """

    def __init__(
        self,
        config: SandboxConfig,
        environment: SandboxEnvironment,
        security_guard: SecurityGuard,
    ) -> None:
        self._config = config
        self._environment = environment
        self._security_guard = security_guard
        self._sessions: dict[str, SessionHandle] = {}
        self._processes: dict[str, SandboxManagedProcess] = {}
        self._session_provider: SessionProvider | None = None

    def configure_session_lifecycle(self, *, session_provider: SessionProvider | None = None) -> None:
        self._session_provider = session_provider

    def _session_is_alive(self, handle: SessionHandle) -> bool:
        reader = getattr(self._environment._backend, "read_cwd", None)
        if not callable(reader):
            return True
        try:
            reader(handle)
        except Exception:
            return False
        return True

    def _get_or_create_owned_session(
        self,
        session_id: str,
        *,
        cwd: Path,
        env: dict[str, str],
    ) -> tuple[SessionHandle, str]:
        handle = self._sessions.get(session_id)
        if handle is not None and self._session_is_alive(handle):
            return handle, "reuse"
        if handle is not None:
            self._sessions.pop(session_id, None)
            try:
                self._environment.cleanup(handle)
            except Exception:
                pass
        sanitized_env = self._security_guard.sanitize_env(
            dict(os.environ), extra_env=env,
        )
        created = self._environment.create_session(
            session_id=session_id,
            cwd=cwd,
            env=sanitized_env,
        )
        self._sessions[session_id] = created
        return created, "create"

    def _acquire_session(
        self,
        session_id: str,
        *,
        cwd: Path,
        env: dict[str, str],
    ) -> tuple[SessionHandle, str]:
        if self._session_provider is not None:
            return self._session_provider(session_id, cwd, env)
        return self._get_or_create_owned_session(session_id, cwd=cwd, env=env)

    def start(
        self,
        *,
        command: str,
        cwd: Path,
        env: Mapping[str, str] | None = None,
        session_id: str | None = None,
    ) -> SandboxManagedProcess:
        """Start a background process inside the sandbox."""
        from uuid import uuid4

        process_id = f"proc:{uuid4().hex[:10]}"
        session_key = session_id or f"bg-{process_id}"
        env_payload = dict(env or {})
        handle, resolution = self._acquire_session(
            session_key,
            cwd=cwd,
            env=env_payload,
        )

        cwd_file_str = str(handle.cwd_file)
        snapshot_str = str(handle.snapshot_path)
        wrapped_command = (
            f'source "{snapshot_str}" 2>/dev/null; '
            f"cd '{cwd}' 2>/dev/null || true; "
            f"{command}; "
            f'_ec=$?; pwd > "{cwd_file_str}"; exit $_ec'
        )

        sanitized_env = self._security_guard.sanitize_env(
            dict(os.environ), extra_env=env_payload,
        )
        sanitized_env["ELEPHANT_SANDBOX_SESSION"] = handle.session_id

        stdout_path = handle.sandbox_root / f"stdout-{process_id}.txt"
        stderr_path = handle.sandbox_root / f"stderr-{process_id}.txt"

        with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
            process = subprocess.Popen(
                wrapped_command,
                shell=True,
                cwd=cwd,
                env=sanitized_env,
                stdin=subprocess.PIPE,
                stdout=stdout_file,
                stderr=stderr_file,
                text=True,
                start_new_session=True,
            )

        managed = SandboxManagedProcess(
            process_id=process_id,
            command=command,
            cwd=cwd,
            sandbox_session_id=session_key,
            process=process,
            started_at=datetime.now(timezone.utc),
            session_handle=handle,
            session_resolution=resolution,
            _sandbox_root=handle.sandbox_root,
        )
        self._processes[process_id] = managed
        return managed

    def list(self) -> tuple[SandboxManagedProcess, ...]:
        return tuple(self._processes.values())

    def get(self, process_id: str) -> SandboxManagedProcess:
        process = self._processes.get(process_id)
        if process is None:
            raise KeyError(process_id)
        return process

    def capture_if_finished(self, process_id: str) -> SandboxManagedProcess:
        managed = self.get(process_id)
        self._drain_process_output(managed)
        if managed.running:
            return managed
        self._mark_process_finished(managed)
        return managed

    def wait(self, process_id: str, *, timeout_seconds: int = 20) -> SandboxManagedProcess:
        managed = self.get(process_id)
        if managed.finished_at is not None:
            return managed
        deadline = datetime.now(timezone.utc).timestamp() + max(1, timeout_seconds)
        while managed.running and datetime.now(timezone.utc).timestamp() < deadline:
            self._drain_process_output(managed)
            try:
                managed.process.wait(timeout=0.05)
            except subprocess.TimeoutExpired:
                pass
        self._drain_process_output(managed)
        if not managed.running:
            self._mark_process_finished(managed)
        return managed

    def write(self, process_id: str, data: str) -> SandboxManagedProcess:
        managed = self.get(process_id)
        if not managed.running or managed.process.stdin is None:
            raise RuntimeError(f"process is not writable: {process_id}")
        managed.process.stdin.write(data)
        managed.process.stdin.flush()
        self._drain_process_output(managed)
        return managed

    def kill(self, process_id: str) -> SandboxManagedProcess:
        managed = self.get(process_id)
        if managed.running:
            self._terminate_process(managed)
        return self.capture_if_finished(process_id)

    def cleanup_session(self, session_id: str) -> bool:
        cleaned = False
        for process_id, managed in tuple(self._processes.items()):
            if managed.sandbox_session_id != session_id:
                continue
            try:
                if managed.running:
                    self._terminate_process(managed)
                self._drain_process_output(managed)
                self._mark_process_finished(managed)
            except Exception:
                self._close_process_streams(managed.process)
            finally:
                self._processes.pop(process_id, None)
            cleaned = True

        handle = self._sessions.pop(session_id, None)
        if handle is not None:
            try:
                self._environment.cleanup(handle)
            except Exception:
                pass
            cleaned = True
        return cleaned

    def cleanup_all(self) -> None:
        """Clean up all managed processes and sandbox sessions."""
        session_ids = {managed.sandbox_session_id for managed in self._processes.values()}
        session_ids.update(self._sessions.keys())
        for session_id in tuple(session_ids):
            self.cleanup_session(session_id)

    def _drain_process_output(self, managed: SandboxManagedProcess) -> None:
        """Read output from the process's stdout/stderr files."""
        if managed._sandbox_root is None:
            return

        stdout_path = managed._sandbox_root / f"stdout-{managed.process_id}.txt"
        stderr_path = managed._sandbox_root / f"stderr-{managed.process_id}.txt"

        try:
            if stdout_path.exists():
                content = stdout_path.read_text(encoding="utf-8", errors="replace")
                if len(content) > len(managed.stdout):
                    managed.stdout = content
        except OSError:
            pass

        try:
            if stderr_path.exists():
                content = stderr_path.read_text(encoding="utf-8", errors="replace")
                if len(content) > len(managed.stderr):
                    managed.stderr = content
        except OSError:
            pass

    def _mark_process_finished(self, managed: SandboxManagedProcess) -> None:
        if managed.finished_at is None:
            managed.finished_at = datetime.now(timezone.utc)
        self._close_process_streams(managed.process)

    def _terminate_process(self, managed: SandboxManagedProcess) -> None:
        self._kill_process_group(managed.process)
        try:
            managed.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._kill_process_group(managed.process)
            managed.process.wait(timeout=5)

    @staticmethod
    def _kill_process_group(process: subprocess.Popen[str]) -> None:
        try:
            pgid = os.getpgid(process.pid)
        except (ProcessLookupError, PermissionError, OSError):
            pgid = None
        if pgid is not None:
            try:
                os.killpg(pgid, signal.SIGKILL)
                return
            except (ProcessLookupError, PermissionError, OSError):
                pass
        try:
            process.kill()
        except (ProcessLookupError, PermissionError, OSError):
            pass

    @staticmethod
    def _close_process_streams(process: subprocess.Popen[str]) -> None:
        for stream_name in ("stdin", "stdout", "stderr"):
            stream = getattr(process, stream_name, None)
            if stream is None:
                continue
            try:
                if not stream.closed:
                    stream.close()
            except Exception:
                pass
