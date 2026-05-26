"""Code execution launcher interface and implementations.

Phase 1B: Provides a small abstraction over how the code execution
subprocess is started.  The *local* launcher runs ``runner.py`` via
``subprocess.Popen`` directly (the original behaviour).  The *sandbox*
launcher routes the runner through ``LocalBackend.run_command`` so that
the child process is subject to the same resource limits, env
sanitisation, and process-group management as foreground terminal
commands.
"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .config import SandboxConfig
from .resource_governor import ResourceGovernor
from .security_guard import SecurityGuard
from .types import EnvironmentBackend, SessionHandle


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class CodeExecutionLauncher(Protocol):
    """Launches the code execution runner subprocess.

    Callers (``_run_code_subprocess``) prepare the staging directory,
    write ``snippet.py`` / ``runner.py``, and then hand off to a
    launcher to start the runner and wait for completion.
    """

    def start(
        self,
        *,
        runner_path: Path,
        child_cwd: Path,
        env: dict[str, str],
        stdout_path: Path,
        stderr_path: Path,
    ) -> subprocess.Popen:
        """Start the runner process and return the Popen handle."""
        ...

    def wait_and_collect(
        self,
        process: subprocess.Popen,
        *,
        timeout_seconds: int,
        stdout_path: Path,
        stderr_path: Path,
    ) -> tuple[int, bool, str, str, tuple[str, ...]]:
        """Wait for the process, enforce timeout, and return results.

        Returns ``(returncode, timed_out, stdout_text, stderr_text,
        diagnostics)``.
        """
        ...


# ---------------------------------------------------------------------------
# Local launcher (original behaviour)
# ---------------------------------------------------------------------------


class LocalCodeLauncher:
    """Launches the runner via ``subprocess.Popen`` directly.

    This is the default launcher when the sandbox is *off*, preserving
    the original code execution behaviour.
    """

    def start(
        self,
        *,
        runner_path: Path,
        child_cwd: Path,
        env: dict[str, str],
        stdout_path: Path,
        stderr_path: Path,
    ) -> subprocess.Popen:
        return subprocess.Popen(
            [self._child_python(), str(runner_path)],
            cwd=child_cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout_path.open("wb"),
            stderr=stderr_path.open("wb"),
        )

    def wait_and_collect(
        self,
        process: subprocess.Popen,
        *,
        timeout_seconds: int,
        stdout_path: Path,
        stderr_path: Path,
    ) -> tuple[int, bool, str, str, tuple[str, ...]]:
        timed_out = False
        deadline = time.monotonic() + timeout_seconds
        while process.poll() is None:
            if time.monotonic() > deadline:
                timed_out = True
                process.kill()
                break
            time.sleep(0.02)
        process.wait(timeout=5)

        stdout_text = self._read_limited(stdout_path)
        stderr_text = self._read_limited(stderr_path)
        diagnostics: list[str] = []
        if timed_out:
            diagnostics.append(f"code execution timed out after {timeout_seconds}s")
        return process.returncode, timed_out, stdout_text, stderr_text, tuple(diagnostics)

    # -- helpers --

    @staticmethod
    def _child_python() -> str:
        import sys

        return sys.executable

    @staticmethod
    def _read_limited(path: Path, *, limit: int = 50_000) -> str:
        try:
            payload = path.read_bytes()
        except OSError:
            return ""
        if len(payload) <= limit:
            return payload.decode("utf-8", errors="replace").strip()
        head_size = max(0, limit // 2)
        tail_size = max(0, limit - head_size)
        head = payload[:head_size].decode("utf-8", errors="replace")
        tail = payload[-tail_size:].decode("utf-8", errors="replace")
        omitted = len(payload) - head_size - tail_size
        return f"{head.rstrip()}\n... [output truncated, {omitted:,} bytes omitted] ...\n{tail.lstrip()}".strip()


# ---------------------------------------------------------------------------
# Sandbox launcher
# ---------------------------------------------------------------------------


SharedSessionProvider = Callable[[Path, dict[str, str]], tuple[SessionHandle, str]]


class SandboxCodeLauncher:
    """Launches the runner inside a sandbox session.

    The sandbox session is created (or reused) on the first invocation.
    The runner is executed via the configured backend (e.g. SeatbeltBackend,
    DockerBackend) so that the OS-level sandbox policy is applied in addition
    to resource limits and env sanitisation.

    The request/response directory protocol for tool RPC is preserved
    unchanged — the staging directory is still a host-tempdir that the
    parent process can observe.
    """

    def __init__(
        self,
        config: SandboxConfig,
        session_id: str,
        backend: EnvironmentBackend | None = None,
        event_sink: Any | None = None,
        event_source: str = "tool.runtime.sandbox",
        session_provider: SharedSessionProvider | None = None,
    ) -> None:
        from .backends.local import LocalBackend

        self._config = config
        self._session_id = session_id
        self._backend = backend or LocalBackend(config)
        self._governor = ResourceGovernor(config.resource_limits)
        self._security_guard = SecurityGuard()
        self._session: SessionHandle | None = None
        self._event_sink = event_sink
        self._event_source = event_source
        self._session_provider = session_provider
        self._owns_session = session_provider is None
        self._invocation_context: dict[str, str] = {}
        self._last_cwd: Path | None = None
        self._last_resolution: str | None = None

    def bind_invocation(self, *, invocation_id: str, episode_id: str, tool_id: str) -> None:
        self._invocation_context = {
            "invocation_id": invocation_id,
            "episode_id": episode_id,
            "tool_id": tool_id,
        }
        self._last_cwd = None
        self._last_resolution = None

    def _emit_sink_event(self, payload: Mapping[str, Any]) -> None:
        sink = self._event_sink
        emitter = getattr(sink, "emit", None)
        if callable(emitter):
            try:
                emitter(dict(payload))
            except Exception:
                return
            return
        if callable(sink):
            try:
                sink(dict(payload))
            except Exception:
                return

    def _sandbox_id(self, handle: SessionHandle | None) -> str | None:
        if handle is None or not handle.attachments:
            return None
        return handle.attachments[0]

    def _session_is_alive(self, handle: SessionHandle) -> bool:
        reader = getattr(self._backend, "read_cwd", None)
        if not callable(reader):
            return True
        try:
            reader(handle)
        except Exception:
            return False
        return True

    def release_session(self) -> None:
        self._session = None
        self._last_cwd = None
        self._last_resolution = None

    def _emit_sandbox_event(
        self,
        *,
        name: str,
        handle: SessionHandle,
        cwd: Path,
        resolution: str | None = None,
        **extra: Any,
    ) -> None:
        occurred_at = datetime.now(timezone.utc).isoformat()
        invocation_id = self._invocation_context.get("invocation_id", "")
        payload: dict[str, Any] = {
            "event_id": f"sandbox:{name}:{invocation_id or handle.session_id}:{occurred_at}",
            "event_type": "sandbox.lifecycle",
            "family": "sandbox",
            "name": name,
            "occurred_at": occurred_at,
            "source": self._event_source,
            "invocation_id": invocation_id or None,
            "episode_id": self._invocation_context.get("episode_id") or handle.session_id,
            "session_id": handle.session_id,
            "tool_id": self._invocation_context.get("tool_id") or "tool.code.execute",
            "backend": handle.backend_id,
            "sandbox_id": self._sandbox_id(handle),
            "cwd": str(cwd),
            "resolution": resolution,
        }
        for key, value in extra.items():
            payload[key] = value
        self._emit_sink_event(payload)

    def _emit_cloud_created(self, *, handle: SessionHandle, cwd: Path) -> None:
        if handle.backend_id != "cloud":
            return
        profile = self._config.effective_cloud()
        self._emit_sandbox_event(
            name="sandbox.cloud_created",
            handle=handle,
            cwd=cwd,
            template=profile.template or "-",
            timeout_seconds=profile.timeout,
            provider=profile.provider,
        )

    def _ensure_session(self, cwd: Path, env: dict[str, str]) -> SessionHandle:
        self._last_cwd = cwd
        if self._session is not None and self._session_is_alive(self._session):
            self._last_resolution = "reuse"
            self._emit_sandbox_event(
                name="sandbox.session",
                handle=self._session,
                cwd=cwd,
                resolution="reuse",
            )
            return self._session

        if self._session is not None:
            if self._owns_session:
                try:
                    self._backend.cleanup_session(self._session)
                except Exception:
                    pass
            self.release_session()
            self._last_cwd = cwd

        if self._session_provider is not None:
            handle, resolution = self._session_provider(cwd, env)
            self._session = handle
            self._last_resolution = resolution
        else:
            sanitized_env = self._security_guard.sanitize_env(dict(os.environ), extra_env=env)
            self._session = self._backend.create_session(
                session_id=self._session_id,
                cwd=cwd,
                env=sanitized_env,
            )
            self._last_resolution = "create"

        if self._session is None:
            raise RuntimeError("sandbox session provider returned no session")
        if self._last_resolution == "create":
            self._emit_cloud_created(handle=self._session, cwd=cwd)
        self._emit_sandbox_event(
            name="sandbox.session",
            handle=self._session,
            cwd=cwd,
            resolution=self._last_resolution,
        )
        return self._session

    def start(
        self,
        *,
        runner_path: Path,
        child_cwd: Path,
        env: dict[str, str],
        stdout_path: Path,
        stderr_path: Path,
    ) -> subprocess.Popen:
        session = self._ensure_session(child_cwd, env)

        # Build the shell command to run the Python runner
        import sys

        child_python = sys.executable
        wrapped_command = f"{child_python} {runner_path}"

        # Sanitise the environment
        sanitized_env = self._security_guard.sanitize_env(
            dict(os.environ), extra_env=env,
        )
        sanitized_env["ELEPHANT_SANDBOX_SESSION"] = session.session_id

        # Start process with sandbox constraints
        process = subprocess.Popen(
            wrapped_command,
            shell=True,
            cwd=child_cwd,
            env=sanitized_env,
            stdin=subprocess.DEVNULL,
            stdout=stdout_path.open("wb"),
            stderr=stderr_path.open("wb"),
            preexec_fn=self._governor.preexec_fn,
            start_new_session=True,
        )
        return process

    def wait_and_collect(
        self,
        process: subprocess.Popen,
        *,
        timeout_seconds: int,
        stdout_path: Path,
        stderr_path: Path,
    ) -> tuple[int, bool, str, str, tuple[str, ...]]:
        result = self._governor.govern_command(
            process,
            timeout_seconds=timeout_seconds,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        return (
            result.returncode,
            result.timed_out,
            result.stdout,
            result.stderr,
            result.diagnostics,
        )

    def trace_metadata(self) -> dict[str, str]:
        handle = self._session
        if handle is None:
            return {}
        metadata: dict[str, str] = {
            "sandbox_backend": str(handle.backend_id or "").strip(),
            "sandbox_backend_class": type(self._backend).__name__,
        }
        sandbox_id = self._sandbox_id(handle)
        if sandbox_id:
            metadata["sandbox_id"] = sandbox_id
        if self._last_cwd is not None:
            metadata["sandbox_cwd"] = str(self._last_cwd)
        if self._last_resolution:
            metadata["sandbox_resolution"] = self._last_resolution
            metadata["sandbox_cached_session"] = "true" if self._last_resolution == "reuse" else "false"
        if handle.backend_id == "cloud":
            profile = self._config.effective_cloud()
            provider = str(profile.provider or "").strip()
            template = str(profile.template or "").strip()
            if provider:
                metadata["sandbox_provider"] = provider
            if template:
                metadata["sandbox_template"] = template
            if profile.timeout:
                metadata["sandbox_timeout_seconds"] = str(profile.timeout)
        return metadata

    def cleanup(self) -> None:
        if self._session is not None and self._owns_session:
            try:
                self._backend.cleanup_session(self._session)
            except Exception:
                pass
        self.release_session()
