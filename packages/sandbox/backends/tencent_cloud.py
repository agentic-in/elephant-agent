"""Tencent Cloud Agent Runtime sandbox backend.

Uses the Tencent Cloud Agent Runtime (based on E2B-compatible Cube Sandbox)
to execute commands in secure, isolated cloud environments.  Each session
maps to a remote cloud sandbox with full OS isolation via KVM/RustVMM.

The backend is E2B SDK-compatible — it uses the ``e2b`` Python package with
custom ``E2B_DOMAIN`` and ``E2B_API_KEY`` environment variables to route
requests through Tencent Cloud's infrastructure.

Key features:
- Hardware-level isolation (KVM/RustVMM microVMs)
- Sub-60ms cold start
- Full Linux OS per sandbox
- Network access controlled per sandbox
- Filesystem operations via E2B SDK
- Compatible with both ``e2b`` and ``e2b-code-interpreter`` packages

Requirements:
- ``e2b`` package installed (``pip install e2b``)
- Tencent Cloud API Key (``ark_`` prefixed)
- Sandbox template name created in Tencent Cloud console
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

from ..config import CloudProfileOptions, SandboxConfig
from ..security_guard import SecurityGuard
from ..types import EnvironmentBackend, SandboxOutput, SessionHandle


class TencentCloudSandboxProvider:
    """SDK provider for Tencent Cloud Agent Runtime (E2B-compatible).

    Implements the ``SDKProvider`` protocol from ``packages.sandbox.backends.sdk``
    using the E2B Python SDK with Tencent Cloud's custom domain and API key.

    Environment variables:
      - ``E2B_DOMAIN``: Set to ``ap-guangzhou.tencentags.com``
      - ``E2B_API_KEY``: Tencent Cloud API Key (``ark_`` prefixed)

    Config options (via *profile*):
      - ``template``: Sandbox template name from Tencent Cloud console
      - ``domain``: Tencent Cloud domain (default: ``ap-guangzhou.tencentags.com``)
      - ``api_key``: API key (or read from ``E2B_API_KEY`` env var)
      - ``timeout``: Sandbox lifetime timeout in seconds (default: 3600)
      - ``allow_internet``: Whether to allow internet access (default: True)
    """

    def __init__(
        self,
        config: SandboxConfig,
        profile: CloudProfileOptions | None = None,
    ) -> None:
        self._config = config
        self._profile = profile or config.effective_cloud()
        self._security_guard = SecurityGuard()
        self._sandboxes: dict[str, Any] = {}  # session_id -> Sandbox instance

    def create_sandbox(
        self, *, session_id: str, cwd: str, env: dict[str, str],
    ) -> str:
        """Create a remote cloud sandbox and return its ID.

        Sets E2B_DOMAIN and E2B_API_KEY before creating the sandbox so
        that the E2B SDK routes requests through Tencent Cloud.
        """
        cloud_opts = self._profile

        # Set environment variables for E2B SDK routing
        os.environ["E2B_DOMAIN"] = cloud_opts.domain
        if cloud_opts.api_key:
            os.environ["E2B_API_KEY"] = cloud_opts.api_key

        try:
            from e2b import Sandbox
        except ImportError as exc:
            raise ImportError(
                "Tencent Cloud sandbox backend requires the 'e2b' package. "
                "Install it with: pip install e2b"
            ) from exc

        # Build sandbox creation kwargs
        create_kwargs: dict[str, Any] = {
            "timeout": cloud_opts.timeout,
        }
        if cloud_opts.template:
            create_kwargs["template"] = cloud_opts.template
        if env:
            # Merge with our custom env vars
            create_kwargs["envs"] = {
                **env,
                "ELEPHANT_SANDBOX": "cloud",
                "ELEPHANT_SANDBOX_SESSION": session_id,
            }

        # Note: allow_internet_access is not available in all E2B versions;
        # we set it only when explicitly disabled
        if not cloud_opts.allow_internet:
            try:
                create_kwargs["allow_internet_access"] = False
            except TypeError:
                pass  # Older SDK versions don't support this parameter

        sandbox = Sandbox(**create_kwargs)
        sandbox_id = sandbox.sandbox_id

        # Store sandbox instance for later use
        self._sandboxes[session_id] = sandbox

        return sandbox_id

    def execute(
        self,
        sandbox_id: str,
        command: str,
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: int = 120,
    ) -> tuple[int, str, str, bool]:
        """Execute a command in the remote cloud sandbox.

        Returns ``(returncode, stdout, stderr, timed_out)``.
        """
        sandbox = self._find_sandbox_by_id(sandbox_id)
        if sandbox is None:
            return 1, "", "Sandbox instance not found", False

        try:
            run_kwargs: dict[str, Any] = {
                "timeout": timeout_seconds,
            }
            if cwd:
                run_kwargs["cwd"] = cwd
            if env:
                run_kwargs["envs"] = env

            result = sandbox.commands.run(command, **run_kwargs)
            return result.exit_code, result.stdout, result.stderr, False

        except Exception as exc:
            # Check for timeout
            if "timeout" in str(exc).lower() or "timed out" in str(exc).lower():
                return -1, "", str(exc), True
            # Other errors
            return 1, "", str(exc), False

    def kill(self, sandbox_id: str) -> bool:
        """Kill the cloud sandbox."""
        sandbox = self._find_sandbox_by_id(sandbox_id)
        if sandbox is None:
            return False
        try:
            sandbox.kill()
            return True
        except Exception:
            return False

    def destroy(self, sandbox_id: str) -> None:
        """Destroy the cloud sandbox and release resources."""
        sandbox = self._find_sandbox_by_id(sandbox_id)
        if sandbox is not None:
            try:
                sandbox.kill()
            except Exception:
                pass
        # Remove from internal tracking
        self._sandboxes = {
            k: v for k, v in self._sandboxes.items()
            if v.sandbox_id != sandbox_id
        }

    def health_check(self) -> bool:
        """Check if Tencent Cloud Agent Runtime is available.

        Verifies that the e2b package is installed and that either
        E2B_API_KEY or config.cloud.api_key is configured.
        """
        try:
            import e2b  # noqa: F401
        except ImportError:
            return False

        cloud_opts = self._profile
        api_key = cloud_opts.api_key or os.environ.get("E2B_API_KEY", "")
        return bool(api_key and api_key.startswith("ark_"))

    def get_sandbox_instance(self, session_id: str) -> Any:
        """Get the raw E2B Sandbox instance for a session (for advanced use)."""
        return self._sandboxes.get(session_id)

    def _find_sandbox_by_id(self, sandbox_id: str) -> Any:
        """Find a sandbox instance by its cloud sandbox_id."""
        for sandbox in self._sandboxes.values():
            if hasattr(sandbox, "sandbox_id") and sandbox.sandbox_id == sandbox_id:
                return sandbox
        return None


class TencentCloudBackend:
    """Environment backend for Tencent Cloud Agent Runtime.

    This backend implements the ``EnvironmentBackend`` protocol directly
    (without going through ``SDKBackend``) for full control over the
    E2B sandbox lifecycle, including filesystem operations and command
    execution with cwd tracking.

    Each session creates a remote cloud sandbox via the E2B SDK (routed
    through Tencent Cloud's domain). Commands are executed via
    ``sandbox.commands.run()`` with cwd and env forwarding.

    Security properties:
    - Full OS-level isolation (KVM/RustVMM microVM)
    - Network access controlled per sandbox
    - No local filesystem exposure
    - Environment variables sanitised before forwarding
    """

    BACKEND_ID = "cloud"

    def __init__(
        self,
        config: SandboxConfig,
        profile: CloudProfileOptions | None = None,
        path_mapper: "SandboxPathMapper | None" = None,
    ) -> None:
        from ..path_mapper import SandboxPathMapper as _SandboxPathMapper

        self._config = config
        self._profile = profile or config.effective_cloud()
        self._security_guard = SecurityGuard()
        self._path_mapper = path_mapper or _SandboxPathMapper()
        self._sessions: dict[str, SessionHandle] = {}
        self._sandboxes: dict[str, Any] = {}  # session_id -> Sandbox instance
        self._cwd_map: dict[str, str] = {}  # session_id -> remote cwd

    # ------------------------------------------------------------------
    # EnvironmentBackend protocol
    # ------------------------------------------------------------------

    def create_session(
        self, *, session_id: str, cwd: Path, env: dict[str, str],
    ) -> SessionHandle:
        sandbox_root = Path(tempfile.mkdtemp(prefix="elephant-sandbox-cloud-"))
        snapshot_path = sandbox_root / ".snapshot.sh"
        cwd_file = sandbox_root / ".cwd"

        # Track remote cwd (inside the cloud sandbox)
        remote_cwd = self._path_mapper.remote_cwd(str(cwd))
        self._cwd_map[session_id] = remote_cwd

        # Store remote cwd in cwd_file so read_cwd returns a remote path
        cwd_file.write_text(remote_cwd, encoding="utf-8")
        snapshot_path.write_text(
            f"# Elephant cloud sandbox snapshot for session {session_id}\n",
            encoding="utf-8",
        )

        # Create the remote cloud sandbox
        sandbox = self._create_cloud_sandbox(session_id, cwd, env)

        cloud_id = sandbox.sandbox_id
        _log.info(
            "sandbox.cloud_created pid=%d backend=%s session_id=%s sandbox_id=%s template=%s timeout_seconds=%s",
            os.getpid(),
            self.BACKEND_ID,
            session_id,
            cloud_id,
            self._profile.template or "-",
            self._profile.timeout,
        )

        # Verify it's a real cloud microVM by running a diagnostic command
        try:
            diag = sandbox.commands.run(
                "echo '---CLOUD-SANDBOX-VERIFY---'; "
                "uname -a; "
                "whoami; "
                "hostname; "
                "cat /etc/os-release 2>/dev/null | head -3; "
                "echo '---END---'",
                timeout=10,
            )
            _log.info("☁️ Sandbox diagnostics:\n%s", diag.stdout)
        except Exception as exc:
            _log.warning("☁️ Sandbox diagnostic failed: %s", exc)

        handle = SessionHandle(
            session_id=session_id,
            backend_id=self.BACKEND_ID,
            sandbox_root=sandbox_root,
            cwd=cwd,
            snapshot_path=snapshot_path,
            cwd_file=cwd_file,
            attachments=(cloud_id,),
        )
        self._sessions[session_id] = handle
        self._sandboxes[session_id] = sandbox
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
        sandbox = self._sandboxes.get(handle.session_id)
        if sandbox is None:
            return SandboxOutput(
                stdout="",
                stderr="Cloud sandbox not found",
                returncode=1,
                cwd=None,
                timed_out=False,
                diagnostics=("sandbox_not_found",),
            )

        # Resolve effective cwd — map local paths to remote sandbox paths
        if cwd is not None:
            effective_cwd = self._path_mapper.to_remote(str(cwd))
        else:
            effective_cwd = self._cwd_map.get(handle.session_id, "/home/user")

        # Build wrapped command that persists cwd after execution
        cwd_marker = f"/tmp/_elephant_cwd_{handle.session_id}"
        wrapped_command = (
            f"mkdir -p '{effective_cwd}' 2>/dev/null || true; "
            f"cd '{effective_cwd}' 2>/dev/null || true; "
            f"{command}; "
            f'_ec=$?; pwd > "{cwd_marker}"; exit $_ec'
        )

        # Always launch the shell from a stable, known-existing remote cwd.
        # The target working directory may not exist yet, so we create it and
        # `cd` into it inside the wrapped command instead of passing it as the
        # SDK-level cwd.
        launch_cwd = "/home/user"

        # Prepare env
        run_kwargs: dict[str, Any] = {
            "timeout": timeout_seconds,
            "cwd": launch_cwd,
        }
        if env:
            sanitized = self._security_guard.sanitize_env(
                dict(os.environ), extra_env=env,
            )
            sanitized["ELEPHANT_SANDBOX"] = "cloud"
            sanitized["ELEPHANT_SANDBOX_SESSION"] = handle.session_id
            run_kwargs["envs"] = sanitized

        try:
            result = sandbox.commands.run(wrapped_command, **run_kwargs)
            timed_out = False
            returncode = result.exit_code
            stdout_text = result.stdout or ""
            stderr_text = result.stderr or ""
            diagnostics: list[str] = []
        except Exception as exc:
            exc_msg = str(exc)
            if "timeout" in exc_msg.lower() or "timed out" in exc_msg.lower():
                timed_out = True
                returncode = -1
                diagnostics = [f"command timed out after {timeout_seconds}s"]
            else:
                timed_out = False
                returncode = 1
                diagnostics = [f"cloud sandbox error: {exc_msg[:200]}"]
            stdout_text = ""
            stderr_text = exc_msg

        # Read updated cwd from the marker file
        try:
            cwd_content = sandbox.files.read(cwd_marker, format="text")
            if cwd_content and cwd_content.strip():
                new_cwd = cwd_content.strip()
                self._cwd_map[handle.session_id] = new_cwd
                # Also update local cwd_file
                handle.cwd_file.write_text(new_cwd, encoding="utf-8")
        except Exception:
            new_cwd = effective_cwd

        # Truncate output
        limits = self._config.resource_limits
        stdout_text = _truncate(stdout_text, limits.max_stdout_bytes)
        stderr_text = _truncate(stderr_text, limits.max_stderr_bytes)

        if len(stdout_text.encode("utf-8", errors="replace")) > limits.max_stdout_bytes:
            diagnostics.append("stdout truncated")
        if len(stderr_text.encode("utf-8", errors="replace")) > limits.max_stderr_bytes:
            diagnostics.append("stderr truncated")

        return SandboxOutput(
            stdout=stdout_text,
            stderr=stderr_text,
            returncode=returncode,
            cwd=Path(new_cwd) if new_cwd else None,
            timed_out=timed_out,
            diagnostics=tuple(diagnostics),
        )

    def kill_process(self, handle: SessionHandle, pid: int) -> bool:
        # For cloud sandbox, we can't kill individual PIDs — kill the whole sandbox
        sandbox = self._sandboxes.get(handle.session_id)
        if sandbox is None:
            return False
        try:
            sandbox.kill()
            return True
        except Exception:
            return False

    def read_cwd(self, handle: SessionHandle) -> Path:
        try:
            return Path(handle.cwd_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return handle.cwd

    def cleanup_session(self, handle: SessionHandle) -> None:
        sandbox = self._sandboxes.pop(handle.session_id, None)
        self._cwd_map.pop(handle.session_id, None)
        self._sessions.pop(handle.session_id, None)

        if sandbox is not None:
            try:
                sandbox.kill()
            except Exception:
                pass

        try:
            shutil.rmtree(handle.sandbox_root)
        except OSError:
            pass

    def read_file(self, handle: SessionHandle, remote_path: str) -> str | None:
        """Read a file from the remote cloud sandbox.

        Returns file content as string, or None if the file does not exist.
        """
        sandbox = self._sandboxes.get(handle.session_id)
        if sandbox is None:
            return None
        try:
            return sandbox.files.read(remote_path, format="text")
        except Exception:
            return None

    def write_file(self, handle: SessionHandle, remote_path: str, content: str) -> bool:
        """Write a file to the remote cloud sandbox.

        Parent directories are created automatically. Returns True on success.
        Falls back to base64-encoded write via commands.run if filesystem.write fails.
        """
        sandbox = self._sandboxes.get(handle.session_id)
        if sandbox is None:
            _log.warning("write_file: sandbox not found for session %s", handle.session_id)
            return False
        try:
            # Ensure parent directory exists
            parent = str(Path(remote_path).parent)
            sandbox.commands.run(f"mkdir -p '{parent}'", timeout=10)
            sandbox.files.write(remote_path, content)
            return True
        except Exception as exc:
            _log.warning("write_file: filesystem.write failed for %s: %s, trying fallback", remote_path, exc)
            # Fallback: write via base64-encoded commands.run
            try:
                import base64
                content_b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
                sandbox.commands.run(
                    f"echo '{content_b64}' | base64 -d > '{remote_path}'",
                    timeout=15,
                )
                return True
            except Exception as fallback_exc:
                _log.error("write_file: fallback also failed for %s: %s", remote_path, fallback_exc)
                return False

    def list_dir(self, handle: SessionHandle, remote_path: str) -> list[str] | None:
        """List directory contents in the remote cloud sandbox.

        Returns list of entry names, or None on error.
        """
        sandbox = self._sandboxes.get(handle.session_id)
        if sandbox is None:
            return None
        try:
            result = sandbox.commands.run(
                f"ls -1 '{remote_path}' 2>/dev/null",
                timeout=10,
            )
            if result.exit_code != 0:
                return None
            return [line for line in (result.stdout or "").splitlines() if line.strip()]
        except Exception:
            return None

    def health_check(self) -> bool:
        """Check if Tencent Cloud Agent Runtime is available.

        Requires the ``e2b`` package and a configured API key.
        """
        try:
            import e2b  # noqa: F401
        except ImportError:
            return False

        cloud_opts = self._profile
        api_key = cloud_opts.api_key or os.environ.get("E2B_API_KEY", "")
        return bool(api_key)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create_cloud_sandbox(
        self, session_id: str, cwd: Path, env: dict[str, str],
    ) -> Any:
        """Create a cloud sandbox via E2B SDK (routed through Tencent Cloud)."""
        cloud_opts = self._profile

        # Set environment variables for E2B SDK routing
        os.environ["E2B_DOMAIN"] = cloud_opts.domain
        if cloud_opts.api_key:
            os.environ["E2B_API_KEY"] = cloud_opts.api_key

        try:
            from e2b import Sandbox
        except ImportError as exc:
            raise ImportError(
                "Tencent Cloud sandbox backend requires the 'e2b' package. "
                "Install it with: pip install e2b"
            ) from exc

        # Build sandbox creation kwargs
        create_kwargs: dict[str, Any] = {
            "timeout": cloud_opts.timeout,
        }
        if cloud_opts.template:
            create_kwargs["template"] = cloud_opts.template

        # Set sandbox env vars
        sandbox_envs: dict[str, str] = {}
        if env:
            sanitized = self._security_guard.sanitize_env(
                dict(os.environ), extra_env=env,
            )
            sandbox_envs.update(sanitized)
        sandbox_envs["ELEPHANT_SANDBOX"] = "cloud"
        sandbox_envs["ELEPHANT_SANDBOX_SESSION"] = session_id
        create_kwargs["envs"] = sandbox_envs

        # Internet access control
        if not cloud_opts.allow_internet:
            try:
                create_kwargs["allow_internet_access"] = False
            except TypeError:
                pass  # Older SDK versions may not support this

        return Sandbox(**create_kwargs)


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


# ---------------------------------------------------------------------------
# Factory for the cloud registry
# ---------------------------------------------------------------------------


class TencentCloudFactory:
    """``CloudBackendFactory`` that creates ``TencentCloudBackend`` instances."""

    def create(
        self,
        config: SandboxConfig,
        profile: CloudProfileOptions,
    ) -> EnvironmentBackend:
        return TencentCloudBackend(config, profile=profile)
