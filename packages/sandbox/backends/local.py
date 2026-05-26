"""Local filesystem backend for sandbox execution."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

from ..config import SandboxConfig
from ..resource_governor import ResourceGovernor
from ..security_guard import SecurityGuard
from ..types import SandboxOutput, SessionHandle


class LocalBackend:
    """Environment backend that runs commands on the local host.

    Each session gets a temporary directory under the system temp root.
    Commands are executed via ``subprocess.Popen`` with a snapshot script
    that preserves working-directory state across invocations.
    """

    BACKEND_ID = "local"

    def __init__(self, config: SandboxConfig) -> None:
        self._config = config
        self._governor = ResourceGovernor(config.resource_limits)
        self._security_guard = SecurityGuard()
        self._sessions: dict[str, SessionHandle] = {}

    def create_session(
        self, *, session_id: str, cwd: Path, env: dict[str, str],
    ) -> SessionHandle:
        sandbox_root = Path(tempfile.mkdtemp(prefix="elephant-sandbox-"))
        snapshot_path = sandbox_root / ".snapshot.sh"
        cwd_file = sandbox_root / ".cwd"

        # Write initial snapshot that sources the cwd marker
        snapshot_path.write_text(
            f"# Elephant sandbox snapshot for session {session_id}\n"
            f'if [ -f "{cwd_file}" ]; then\n'
            f'  cd "$(cat "{cwd_file}")" 2>/dev/null || true\n'
            f"fi\n",
            encoding="utf-8",
        )

        # Write initial cwd
        cwd_file.write_text(str(cwd), encoding="utf-8")

        handle = SessionHandle(
            session_id=session_id,
            backend_id=self.BACKEND_ID,
            sandbox_root=sandbox_root,
            cwd=cwd,
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
            effective_cwd = cwd
        else:
            try:
                effective_cwd = Path(handle.cwd_file.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                effective_cwd = handle.cwd

        # Ensure effective_cwd exists
        effective_cwd = effective_cwd.resolve()

        # Build the shell command: source snapshot, run command, persist cwd
        cwd_file_str = str(handle.cwd_file)
        snapshot_str = str(handle.snapshot_path)
        wrapped_command = (
            f'source "{snapshot_str}" 2>/dev/null; '
            f"cd '{effective_cwd}' 2>/dev/null || true; "
            f"{command}; "
            f'_ec=$?; pwd > "{cwd_file_str}"; exit $_ec'
        )

        # Prepare environment
        base_env = dict(os.environ)
        sanitized_env = self._security_guard.sanitize_env(base_env, extra_env=env)
        sanitized_env["ELEPHANT_SANDBOX_SESSION"] = handle.session_id

        # Output files inside sandbox root
        stdout_path = handle.sandbox_root / "stdout.txt"
        stderr_path = handle.sandbox_root / "stderr.txt"

        with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
            process = subprocess.Popen(
                wrapped_command,
                shell=True,
                cwd=effective_cwd,
                env=sanitized_env,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                preexec_fn=self._governor.preexec_fn,
                start_new_session=True,
            )

            result = self._governor.govern_command(
                process,
                timeout_seconds=timeout_seconds,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )

        # Update cwd from cwd_file if command changed directory
        try:
            new_cwd_text = handle.cwd_file.read_text(encoding="utf-8").strip()
            if new_cwd_text:
                result = SandboxOutput(
                    stdout=result.stdout,
                    stderr=result.stderr,
                    returncode=result.returncode,
                    cwd=Path(new_cwd_text),
                    timed_out=result.timed_out,
                    diagnostics=result.diagnostics,
                )
        except (OSError, ValueError):
            pass

        return result

    def kill_process(self, handle: SessionHandle, pid: int) -> bool:
        try:
            pgid = os.getpgid(pid)
            os.killpg(pgid, signal.SIGKILL)
            return True
        except (ProcessLookupError, PermissionError, OSError):
            return False

    def read_cwd(self, handle: SessionHandle) -> Path:
        try:
            return Path(handle.cwd_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return handle.cwd

    def cleanup_session(self, handle: SessionHandle) -> None:
        self._sessions.pop(handle.session_id, None)
        try:
            shutil.rmtree(handle.sandbox_root)
        except OSError:
            pass

    def health_check(self) -> bool:
        return True
