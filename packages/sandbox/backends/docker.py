"""Docker container backend for sandbox execution.

Phase 2: Provides strong isolation via Docker containers with:
- network=none by default
- cgroup resource limits
- Read-only root filesystem
- Bind mount whitelist enforcement
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from ..config import SandboxConfig
from ..security_guard import SecurityGuard
from ..types import SandboxOutput, SessionHandle

# Default Docker image name
_DEFAULT_IMAGE = "elephant-sandbox"


class DockerBackend:
    """Environment backend that runs commands inside Docker containers.

    Each session maps to a long-lived container (created on first use).
    Commands are executed via ``docker exec`` so that filesystem state
    (including cwd) persists across calls within the same session.

    The container is started with:
    - ``--network none`` (no network access by default)
    - ``--read-only`` root filesystem with a tmpfs for /tmp, /home, /run
    - Resource limits via ``--memory``, ``--pids-limit``, etc.
    - Bind mounts validated through ``SecurityGuard.validate_bind_mounts``
    """

    BACKEND_ID = "docker"

    def __init__(
        self,
        config: SandboxConfig,
        *,
        image: str | None = None,
        docker_cli: str = "docker",
    ) -> None:
        self._config = config
        self._image = image or _DEFAULT_IMAGE
        self._docker_cli = docker_cli
        self._security_guard = SecurityGuard()
        self._sessions: dict[str, SessionHandle] = {}

    # ------------------------------------------------------------------
    # EnvironmentBackend protocol
    # ------------------------------------------------------------------

    def create_session(
        self, *, session_id: str, cwd: Path, env: dict[str, str],
    ) -> SessionHandle:
        sandbox_root = Path(tempfile.mkdtemp(prefix="elephant-sandbox-docker-"))
        snapshot_path = sandbox_root / ".snapshot.sh"
        cwd_file = sandbox_root / ".cwd"

        # Write initial cwd marker
        cwd_file.write_text(str(cwd), encoding="utf-8")
        snapshot_path.write_text(
            f"# Elephant docker sandbox snapshot for session {session_id}\n",
            encoding="utf-8",
        )

        # Validate bind mounts — cwd must be allowed
        mount_source = cwd.resolve()
        reason = self._security_guard.validate_sensitive_host_path(mount_source)
        if reason:
            raise PermissionError(
                f"Refusing to mount sensitive host path into container: {reason}"
            )

        # Build and start the container
        container_id = self._start_container(
            session_id=session_id,
            mount_source=mount_source,
            env=env,
        )

        handle = SessionHandle(
            session_id=session_id,
            backend_id=self.BACKEND_ID,
            sandbox_root=sandbox_root,
            cwd=cwd,
            snapshot_path=snapshot_path,
            cwd_file=cwd_file,
            attachments=(container_id,),
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
        container_id = self._container_id(handle)
        if container_id is None:
            return SandboxOutput(
                stdout="",
                stderr="sandbox container not found",
                returncode=1,
                cwd=None,
                timed_out=False,
                diagnostics=("container_not_found",),
            )

        # Resolve effective cwd and map to container path.
        # The host workspace is bind-mounted at /workspace inside the container,
        # so we must translate host paths to container paths.
        mount_source = handle.cwd.resolve()
        # The container writes pwd to /workspace/.cwd which maps to
        # mount_source/.cwd on the host (NOT sandbox_root/.cwd).
        container_cwd_host_file = mount_source / ".cwd"
        if cwd is not None:
            host_cwd = cwd
        else:
            try:
                # Read from the file that the container actually updates
                container_cwd_text = container_cwd_host_file.read_text(
                    encoding="utf-8"
                ).strip()
                host_cwd = self._container_to_host_path(
                    Path(container_cwd_text), mount_source
                )
            except (OSError, ValueError):
                host_cwd = handle.cwd
        effective_cwd = self._host_to_container_path(host_cwd, mount_source)

        # Build the wrapped command: cd, run, persist cwd
        cwd_file_container = "/workspace/.cwd"
        wrapped_command = (
            f"cd '{effective_cwd}' 2>/dev/null || true; "
            f"{command}; "
            f'_ec=$?; pwd > "{cwd_file_container}"; exit $_ec'
        )

        # Build env flags
        env_flags: list[str] = []
        if env:
            sanitized = self._security_guard.sanitize_env(
                dict(__import__("os").environ), extra_env=env,
            )
            for k, v in sanitized.items():
                env_flags.extend(["-e", f"{k}={v}"])
        env_flags.extend(["-e", "ELEPHANT_SANDBOX=1"])
        env_flags.extend(["-e", f"ELEPHANT_SANDBOX_SESSION={handle.session_id}"])

        # Execute via docker exec
        cmd = [
            self._docker_cli, "exec",
            *env_flags,
            "-w", str(effective_cwd),
            container_id,
            "bash", "-c", wrapped_command,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds + 5,  # Docker overhead buffer
            )
            timed_out = False
            diagnostics: list[str] = []
        except subprocess.TimeoutExpired:
            # Try to stop the container's current exec
            diagnostics = [f"command timed out after {timeout_seconds}s"]
            timed_out = True
            # Read whatever output we can
            result = subprocess.CompletedProcess(
                args=cmd, returncode=-1, stdout="", stderr="",
            )

        # Truncate stdout/stderr
        limits = self._config.resource_limits
        stdout_text = _truncate(result.stdout, limits.max_stdout_bytes)
        stderr_text = _truncate(result.stderr, limits.max_stderr_bytes)

        if len(result.stdout.encode("utf-8", errors="replace")) > limits.max_stdout_bytes:
            diagnostics.append("stdout truncated")
        if len(result.stderr.encode("utf-8", errors="replace")) > limits.max_stderr_bytes:
            diagnostics.append("stderr truncated")

        # Read updated cwd from mount_source/.cwd (written by container)
        mount_source = handle.cwd.resolve()
        try:
            container_cwd_host_file = mount_source / ".cwd"
            container_cwd_text = container_cwd_host_file.read_text(
                encoding="utf-8"
            ).strip()
            new_cwd = self._container_to_host_path(
                Path(container_cwd_text), mount_source
            )
        except (OSError, ValueError):
            new_cwd = handle.cwd

        return SandboxOutput(
            stdout=stdout_text,
            stderr=stderr_text,
            returncode=result.returncode if not timed_out else -1,
            cwd=new_cwd,
            timed_out=timed_out,
            diagnostics=tuple(diagnostics),
        )

    def kill_process(self, handle: SessionHandle, pid: int) -> bool:
        # For Docker, we kill the entire container
        container_id = self._container_id(handle)
        if container_id is None:
            return False
        try:
            subprocess.run(
                [self._docker_cli, "kill", container_id],
                capture_output=True, timeout=10,
            )
            return True
        except (subprocess.TimeoutExpired, OSError):
            return False

    def read_cwd(self, handle: SessionHandle) -> Path:
        mount_source = handle.cwd.resolve()
        container_cwd_host_file = mount_source / ".cwd"
        try:
            container_cwd_text = container_cwd_host_file.read_text(
                encoding="utf-8"
            ).strip()
            return self._container_to_host_path(
                Path(container_cwd_text), mount_source
            )
        except (OSError, ValueError):
            return handle.cwd

    def cleanup_session(self, handle: SessionHandle) -> None:
        container_id = self._container_id(handle)
        self._sessions.pop(handle.session_id, None)

        if container_id is not None:
            try:
                subprocess.run(
                    [self._docker_cli, "rm", "-f", container_id],
                    capture_output=True, timeout=15,
                )
            except (subprocess.TimeoutExpired, OSError):
                pass

        # Remove local sandbox root
        try:
            shutil.rmtree(handle.sandbox_root)
        except OSError:
            pass

    def health_check(self) -> bool:
        """Check if Docker is available and the sandbox image exists."""
        try:
            result = subprocess.run(
                [self._docker_cli, "image", "inspect", self._image],
                capture_output=True, timeout=10,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _host_to_container_path(host_path: Path, mount_source: Path) -> Path:
        """Map a host path to the corresponding container path.

        The host workspace at *mount_source* is bind-mounted at ``/workspace``
        inside the container, so ``mount_source/foo`` → ``/workspace/foo``.
        """
        try:
            relative = host_path.resolve().relative_to(mount_source)
            return Path("/workspace") / relative
        except ValueError:
            # Path is outside the mount source — default to /workspace
            return Path("/workspace")

    @staticmethod
    def _container_to_host_path(container_path: Path, mount_source: Path) -> Path:
        """Map a container path back to the corresponding host path.

        ``/workspace/foo`` → ``mount_source/foo``.
        """
        try:
            relative = container_path.relative_to("/workspace")
            return mount_source / relative
        except ValueError:
            return mount_source

    def _start_container(
        self, *, session_id: str, mount_source: Path, env: dict[str, str],
    ) -> str:
        """Start a Docker container and return its ID."""
        limits = self._config.resource_limits
        container_name = f"elephant-sandbox-{session_id}"

        # Remove any leftover container with the same name
        subprocess.run(
            [self._docker_cli, "rm", "-f", container_name],
            capture_output=True, timeout=10,
        )

        cmd = [
            self._docker_cli, "run",
            "-d",                        # detached
            "--name", container_name,
            "--network", "none",         # no network by default
            "--read-only",               # read-only root filesystem
            "--tmpfs", "/tmp:size=100m",
            "--tmpfs", "/home:size=100m,exec",
            "--tmpfs", "/run:size=10m",
            "--memory", f"{limits.max_memory_mb}m",
            "--pids-limit", str(limits.max_processes),
            "--stop-timeout", str(limits.max_wall_seconds),
            # Mount workspace
            "-v", f"{mount_source}:/workspace:rw",
            "-w", "/workspace",
        ]

        # Environment
        sanitized = self._security_guard.sanitize_env(
            dict(__import__("os").environ), extra_env=env,
        )
        for k, v in sanitized.items():
            cmd.extend(["-e", f"{k}={v}"])
        cmd.extend(["-e", "ELEPHANT_SANDBOX=1"])
        cmd.extend(["-e", f"ELEPHANT_SANDBOX_SESSION={session_id}"])

        cmd.append(self._image)

        # Keep container alive with a sleep
        cmd.extend(["sleep", str(limits.max_wall_seconds + 60)])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to start sandbox container: {result.stderr.strip()}"
            )

        container_id = result.stdout.strip()
        if not container_id:
            raise RuntimeError("Docker run returned empty container ID")

        # Write .cwd file inside the container (maps to mount_source/.cwd on host)
        subprocess.run(
            [
                self._docker_cli, "exec", container_id,
                "bash", "-c", "echo /workspace > /workspace/.cwd",
            ],
            capture_output=True, timeout=10,
        )

        return container_id

    def _container_id(self, handle: SessionHandle) -> str | None:
        """Get the container ID from session handle attachments."""
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
