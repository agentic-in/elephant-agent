"""macOS Seatbelt sandbox backend.

Uses ``/usr/bin/sandbox-exec`` to apply macOS Seatbelt policies that restrict
filesystem and network access for command execution.  This is the same kernel-
level sandbox that OpenAI Codex CLI uses on macOS.

Seatbelt provides:
- Filesystem read/write control per path
- Network outbound/inbound control
- Process execution restrictions
- IPC and Mach restrictions

This backend requires macOS.  On other platforms, :meth:`health_check` returns
``False`` so the executor can fall back to :class:`LocalBackend`.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

from ..config import SandboxConfig
from ..resource_governor import ResourceGovernor
from ..security_guard import SecurityGuard
from ..types import SandboxOutput, SessionHandle

_SANDBOX_EXEC_PATH = "/usr/bin/sandbox-exec"


# ---------------------------------------------------------------------------
# Policy generation
# ---------------------------------------------------------------------------

def _seatbelt_policy(
    *,
    writable_roots: tuple[Path, ...] = (),
    readable_roots: tuple[Path, ...] = (),
    allow_network: bool = False,
    allow_network_loopback: bool = False,
) -> str:
    """Generate a Seatbelt policy string (version 1).

    The policy follows a default-deny model inspired by Codex's base policy:
    - ``(deny default)`` blocks everything not explicitly allowed
    - Allow process execution and forking (needed for shell commands)
    - Allow reading the entire filesystem by default (tools need it)
    - Restrict writes to only the specified writable roots
    - Control network based on configuration

    Parameters
    ----------
    writable_roots:
        Paths where the sandboxed process is allowed to write.
    readable_roots:
        Additional paths that are explicitly allowed for reading (beyond
        the default allow-all-read policy).
    allow_network:
        Allow all outbound network access.
    allow_network_loopback:
        Allow only loopback (127.0.0.1) and Unix domain socket networking.
    """
    rules: list[str] = ["(version 1)", "(deny default)"]

    # --- Process lifecycle ---
    rules.append("(allow process-exec)")
    rules.append("(allow process-fork)")

    # --- Filesystem: default allow read ---
    # Tools need to read system libraries, interpreters, etc.
    rules.append("(allow file-read*)")

    # --- Filesystem: writable roots ---
    for root in writable_roots:
        resolved = str(root.resolve())
        rules.append(f'(allow file-write* (subpath "{resolved}"))')

    # --- /dev/null and /dev/urandom: needed for basic shell ops ---
    rules.append('(allow file-write* (subpath "/dev/null"))')
    rules.append('(allow file-write* (subpath "/dev/urandom"))')

    # --- macOS /tmp is actually /private/tmp ---
    # Ensure /tmp writes work even if not in writable_roots
    rules.append('(allow file-write* (subpath "/private/tmp"))')

    # --- IPC and Mach: needed for subprocess, pipes, PTY ---
    rules.append("(allow ipc-sysv*)")
    rules.append("(allow mach-lookup)")

    # --- Sysctl: needed for system info queries ---
    rules.append("(allow sysctl-read)")

    # --- Signal: allow sending signals within the process group ---
    rules.append("(allow signal (target same-sandbox))")

    # --- Network ---
    if allow_network:
        rules.append("(allow network-outbound)")
        rules.append("(allow network-inbound)")
    elif allow_network_loopback:
        # Deny all TCP/UDP outbound, then allow Unix domain sockets for IPC
        # This allows local proxy communication via Unix sockets but blocks
        # all remote network access (similar to Codex's ProxyRouted mode)
        rules.append("(deny network-outbound)")
        rules.append("(allow network-outbound (remote unix-socket))")
        rules.append("(allow network-inbound (local unix-socket))")

    return "\n".join(rules)


# ---------------------------------------------------------------------------
# Seatbelt backend
# ---------------------------------------------------------------------------

class SeatbeltBackend:
    """macOS Seatbelt sandbox backend using ``/usr/bin/sandbox-exec``.

    Each session gets a temporary directory and a Seatbelt policy file that
    restricts the sandboxed process based on the :class:`SandboxConfig`.

    This backend extends :class:`LocalBackend` semantics but wraps every
    ``subprocess.Popen`` call with ``sandbox-exec -f <policy> -- <command>``.
    """

    BACKEND_ID = "seatbelt"

    def __init__(self, config: SandboxConfig) -> None:
        self._config = config
        self._governor = ResourceGovernor(config.resource_limits)
        self._security_guard = SecurityGuard()
        self._sessions: dict[str, SessionHandle] = {}

    # --- EnvironmentBackend Protocol ---

    def create_session(
        self,
        *,
        session_id: str,
        cwd: Path,
        env: dict[str, str],
    ) -> SessionHandle:
        sandbox_root = Path(tempfile.mkdtemp(prefix="elephant-seatbelt-"))
        snapshot_path = sandbox_root / ".snapshot.sh"
        cwd_file = sandbox_root / ".cwd"
        policy_path = sandbox_root / ".seatbelt.sbpl"

        # Write initial snapshot that sources the cwd marker
        snapshot_path.write_text(
            f"# Elephant Seatbelt sandbox snapshot for session {session_id}\n"
            f'if [ -f "{cwd_file}" ]; then\n'
            f'  cd "$(cat "{cwd_file}")" 2>/dev/null || true\n'
            f"fi\n",
            encoding="utf-8",
        )
        cwd_file.write_text(str(cwd), encoding="utf-8")

        # Generate Seatbelt policy
        writable_roots = self._resolve_writable_roots(cwd)
        policy = _seatbelt_policy(
            writable_roots=writable_roots,
            allow_network=self._config.seatbelt.allow_network,
            allow_network_loopback=self._config.seatbelt.allow_network_loopback,
        )
        policy_path.write_text(policy, encoding="utf-8")

        handle = SessionHandle(
            session_id=session_id,
            backend_id=self.BACKEND_ID,
            sandbox_root=sandbox_root,
            cwd=cwd,
            snapshot_path=snapshot_path,
            cwd_file=cwd_file,
            attachments=(str(policy_path),),
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
        sanitized_env["ELEPHANT_SANDBOX"] = "seatbelt"

        # Retrieve policy path from attachments
        policy_path = self._policy_path(handle)

        # Wrap with sandbox-exec, running the command through /bin/sh
        sandbox_argv = [_SANDBOX_EXEC_PATH, "-f", str(policy_path), "--", "/bin/sh", "-c", wrapped_command]

        # Output files inside sandbox root
        stdout_path = handle.sandbox_root / "stdout.txt"
        stderr_path = handle.sandbox_root / "stderr.txt"

        with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
            process = subprocess.Popen(
                sandbox_argv,
                shell=False,
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

        # Check if the sandbox-exec itself failed (policy error)
        diagnostics = list(result.diagnostics)
        if result.returncode == 134 and not result.stdout.strip():
            diagnostics.append("seatbelt: sandbox-exec aborted (policy error or violation)")

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
                    diagnostics=tuple(diagnostics) or result.diagnostics,
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
        """Check if Seatbelt sandbox is available on this platform.

        Returns ``True`` only on macOS when ``/usr/bin/sandbox-exec`` exists
        and is executable.
        """
        if sys.platform != "darwin":
            return False
        return os.path.isfile(_SANDBOX_EXEC_PATH) and os.access(_SANDBOX_EXEC_PATH, os.X_OK)

    # --- Internal helpers ---

    def _resolve_writable_roots(self, cwd: Path) -> tuple[Path, ...]:
        """Determine which paths the sandboxed process may write to."""
        roots: list[Path] = []

        # Always allow writing to the sandbox's own temp directory
        # (it will be added after creation)

        # Workspace access determines cwd writability
        if self._config.workspace_access in ("ro", "rw"):
            roots.append(cwd.resolve())

        # Always allow writing to system temp directories
        roots.append(Path(tempfile.gettempdir()).resolve())

        # macOS /tmp -> /private/tmp
        tmp_resolved = Path("/tmp").resolve()
        if tmp_resolved != Path(tempfile.gettempdir()).resolve():
            roots.append(tmp_resolved)

        return tuple(dict.fromkeys(roots))  # deduplicate preserving order

    @staticmethod
    def _policy_path(handle: SessionHandle) -> Path:
        """Retrieve the Seatbelt policy file path from session attachments."""
        for attachment in handle.attachments:
            path = Path(attachment)
            if path.suffix == ".sbpl":
                return path
        # Fallback: generate on-the-fly (should not happen in normal flow)
        return handle.sandbox_root / ".seatbelt.sbpl"
