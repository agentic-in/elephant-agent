"""SSH remote backend for sandbox execution.

Phase 3: Provides remote isolation by executing commands on a remote
host via SSH.  Each session maps to a persistent SSH connection with
a working directory on the remote host.

Requirements:
- ``paramiko`` or ``subprocess`` ssh client
- SSH key-based authentication (no password prompts)
- Remote host must have bash available
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from ..config import SandboxConfig
from ..security_guard import SecurityGuard
from ..types import SandboxOutput, SessionHandle


class SSHBackend:
    """Environment backend that runs commands on a remote host via SSH.

    Each session creates a remote working directory and maintains state
    across invocations.  Commands are executed via ``ssh <host> bash -c``.

    The SSH connection uses key-based authentication — the backend does
    **not** handle password prompts or interactive authentication.

    Security properties:
    - Commands run in the remote host's user context
    - Network isolation is the remote host's responsibility
    - Environment variables are sanitised before forwarding
    - Sensitive host paths are not auto-mounted (no bind mounts)
    """

    BACKEND_ID = "ssh"

    def __init__(
        self,
        config: SandboxConfig,
        *,
        host: str,
        port: int = 22,
        user: str | None = None,
        identity_file: Path | None = None,
        ssh_cli: str = "ssh",
    ) -> None:
        self._config = config
        self._host = host
        self._port = port
        self._user = user
        self._identity_file = identity_file
        self._ssh_cli = ssh_cli
        self._security_guard = SecurityGuard()
        self._sessions: dict[str, SessionHandle] = {}

    # ------------------------------------------------------------------
    # EnvironmentBackend protocol
    # ------------------------------------------------------------------

    def create_session(
        self, *, session_id: str, cwd: Path, env: dict[str, str],
    ) -> SessionHandle:
        sandbox_root = Path(tempfile.mkdtemp(prefix="elephant-sandbox-ssh-"))
        snapshot_path = sandbox_root / ".snapshot.sh"
        cwd_file = sandbox_root / ".cwd"

        # Create remote working directory
        remote_dir = f"/tmp/elephant-sandbox-{session_id}"
        self._exec_remote(f"mkdir -p {remote_dir}")

        # Write initial cwd marker
        cwd_file.write_text(remote_dir, encoding="utf-8")
        snapshot_path.write_text(
            f"# Elephant SSH sandbox snapshot for session {session_id}\n",
            encoding="utf-8",
        )

        handle = SessionHandle(
            session_id=session_id,
            backend_id=self.BACKEND_ID,
            sandbox_root=sandbox_root,
            cwd=Path(remote_dir),
            snapshot_path=snapshot_path,
            cwd_file=cwd_file,
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
        # Resolve effective cwd
        if cwd is not None:
            effective_cwd = str(cwd)
        else:
            try:
                effective_cwd = handle.cwd_file.read_text(encoding="utf-8").strip()
            except (OSError, ValueError):
                effective_cwd = str(handle.cwd)

        # Build the wrapped command
        cwd_file_remote = f"{effective_cwd}/.cwd"
        wrapped_command = (
            f"cd '{effective_cwd}' 2>/dev/null || true; "
            f"{command}; "
            f'_ec=$?; pwd > "{cwd_file_remote}"; exit $_ec'
        )

        # Build env forwarding
        env_prefix = ""
        if env:
            sanitized = self._security_guard.sanitize_env(
                dict(__import__("os").environ), extra_env=env,
            )
            env_parts = [f"{k}={v}" for k, v in sanitized.items()]
            env_parts.append("ELEPHANT_SANDBOX=1")
            env_parts.append(f"ELEPHANT_SANDBOX_SESSION={handle.session_id}")
            env_prefix = " ".join(f"export {p};" for p in env_parts) + " "

        full_command = env_prefix + wrapped_command

        # Execute via SSH
        ssh_args = self._ssh_args()
        cmd = [
            *ssh_args,
            f"bash -c {subprocess.list2cmdline([full_command])}",
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds + 10,  # SSH overhead buffer
            )
            timed_out = False
            diagnostics: list[str] = []
        except subprocess.TimeoutExpired:
            diagnostics = [f"command timed out after {timeout_seconds}s"]
            timed_out = True
            result = subprocess.CompletedProcess(
                args=cmd, returncode=-1, stdout="", stderr="",
            )

        # Truncate output
        limits = self._config.resource_limits
        stdout_text = _truncate(result.stdout, limits.max_stdout_bytes)
        stderr_text = _truncate(result.stderr, limits.max_stderr_bytes)

        if len(result.stdout.encode("utf-8", errors="replace")) > limits.max_stdout_bytes:
            diagnostics.append("stdout truncated")
        if len(result.stderr.encode("utf-8", errors="replace")) > limits.max_stderr_bytes:
            diagnostics.append("stderr truncated")

        # Read updated cwd from remote
        try:
            cwd_result = self._exec_remote(f"cat {cwd_file_remote}", timeout=5)
            if cwd_result.strip():
                new_cwd = Path(cwd_result.strip())
            else:
                new_cwd = Path(effective_cwd)
        except (subprocess.TimeoutExpired, OSError):
            new_cwd = Path(effective_cwd)

        return SandboxOutput(
            stdout=stdout_text,
            stderr=stderr_text,
            returncode=result.returncode if not timed_out else -1,
            cwd=new_cwd,
            timed_out=timed_out,
            diagnostics=tuple(diagnostics),
        )

    def kill_process(self, handle: SessionHandle, pid: int) -> bool:
        # Kill the remote process by PID
        try:
            self._exec_remote(f"kill -9 {pid} 2>/dev/null || true")
            return True
        except (subprocess.TimeoutExpired, OSError):
            return False

    def read_cwd(self, handle: SessionHandle) -> Path:
        try:
            return Path(handle.cwd_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return handle.cwd

    def cleanup_session(self, handle: SessionHandle) -> None:
        self._sessions.pop(handle.session_id, None)

        # Remove remote directory
        try:
            self._exec_remote(f"rm -rf /tmp/elephant-sandbox-{handle.session_id}", timeout=10)
        except (subprocess.TimeoutExpired, OSError):
            pass

        # Remove local sandbox root
        try:
            shutil.rmtree(handle.sandbox_root)
        except OSError:
            pass

    def health_check(self) -> bool:
        """Check if the SSH host is reachable."""
        try:
            result = subprocess.run(
                [*self._ssh_args(), "true"],
                capture_output=True,
                timeout=10,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ssh_args(self) -> list[str]:
        """Build the SSH CLI arguments."""
        args = [self._ssh_cli]
        args.extend(["-p", str(self._port)])
        args.extend(["-o", "StrictHostKeyChecking=accept-new"])
        args.extend(["-o", "ConnectTimeout=5"])
        args.extend(["-o", "BatchMode=yes"])  # No password prompts

        if self._identity_file is not None:
            args.extend(["-i", str(self._identity_file)])

        target = f"{self._user}@{self._host}" if self._user else self._host
        args.append(target)

        return args

    def _exec_remote(self, command: str, *, timeout: int = 30) -> str:
        """Execute a command on the remote host and return stdout."""
        ssh_args = self._ssh_args()
        result = subprocess.run(
            [*ssh_args, command],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"SSH remote command failed: {result.stderr.strip()}"
            )
        return result.stdout


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
