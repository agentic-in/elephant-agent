"""macOS Seatbelt sandbox backend.

Uses ``/usr/bin/sandbox-exec`` with inline policy (``-p``) and parameterized
paths (``-D``) to apply macOS Seatbelt policies that restrict filesystem and
network access for command execution.

Security architecture (inspired by Codex CLI / Chromium sandbox):
- Policy delivered inline (``-p``) — not via temp file — to prevent tampering
- Paths passed as ``-D KEY=VALUE`` parameters to prevent policy injection
- Writable roots have exclusion rules for ``.git``, ``.codex``, ``.claude``
- mach-lookup restricted to named service whitelist
- Credential directories (~/.ssh, ~/.aws, etc.) explicitly deny-read

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
from importlib import resources as importlib_resources
from pathlib import Path

from ..config import SandboxConfig
from ..resource_governor import ResourceGovernor
from ..security_guard import SecurityGuard
from ..types import SandboxOutput, SessionHandle

_SANDBOX_EXEC_PATH = "/usr/bin/sandbox-exec"


# ---------------------------------------------------------------------------
# Policy builder
# ---------------------------------------------------------------------------


def _load_base_policy() -> str:
    """Load the static base policy template from the package."""
    try:
        ref = importlib_resources.files(__package__) / "seatbelt_base_policy.sbpl"
        return ref.read_text(encoding="utf-8")
    except (TypeError, FileNotFoundError, OSError):
        # Fallback: load relative to this file
        policy_path = Path(__file__).parent / "seatbelt_base_policy.sbpl"
        return policy_path.read_text(encoding="utf-8")


def _load_platform_defaults() -> str:
    """Load the platform defaults read-whitelist policy."""
    try:
        ref = importlib_resources.files(__package__) / "seatbelt_platform_defaults.sbpl"
        return ref.read_text(encoding="utf-8")
    except (TypeError, FileNotFoundError, OSError):
        policy_path = Path(__file__).parent / "seatbelt_platform_defaults.sbpl"
        return policy_path.read_text(encoding="utf-8")


_BASE_POLICY_CACHE: str | None = None
_PLATFORM_DEFAULTS_CACHE: str | None = None


def _get_base_policy() -> str:
    global _BASE_POLICY_CACHE
    if _BASE_POLICY_CACHE is None:
        _BASE_POLICY_CACHE = _load_base_policy()
    return _BASE_POLICY_CACHE


def _get_platform_defaults() -> str:
    global _PLATFORM_DEFAULTS_CACHE
    if _PLATFORM_DEFAULTS_CACHE is None:
        _PLATFORM_DEFAULTS_CACHE = _load_platform_defaults()
    return _PLATFORM_DEFAULTS_CACHE


class SeatbeltPolicyBuilder:
    """Builds a Seatbelt policy with parameterized paths.

    Usage::

        builder = SeatbeltPolicyBuilder(config)
        builder.add_writable_root(cwd, exclusions=[...])
        policy_text, params = builder.render()
        # params is a list like ["-DWRITABLE_ROOT_0=/path", "-DHOME_SSH=/path/.ssh", ...]
    """

    def __init__(self, config: SandboxConfig) -> None:
        self._config = config
        self._writable_roots: list[tuple[Path, list[str]]] = []
        self._params: dict[str, str] = {}
        self._extra_policy_lines: list[str] = []
        self._network_lines: list[str] = []

    def add_writable_root(self, path: Path, exclusions: list[str] | None = None) -> None:
        """Add a writable root with optional protected-path exclusion patterns.

        *exclusions* are Seatbelt regex patterns that deny writes within the root
        (e.g. ``r"(^|/)\\.git(/.*)?$"`` to protect ``.git`` directories).
        """
        self._writable_roots.append((path.resolve(), exclusions or []))

    def add_credential_deny(self, home: Path) -> None:
        """Add deny-read rules for common credential directories."""
        credential_dirs = {
            "HOME_SSH": home / ".ssh",
            "HOME_AWS": home / ".aws",
            "HOME_GNUPG": home / ".gnupg",
            "HOME_KUBE": home / ".kube",
            "HOME_DOCKER": home / ".docker",
        }
        for param_key, dir_path in credential_dirs.items():
            self._params[param_key] = str(dir_path.resolve())

    def add_sandbox_tmpdir(self, tmpdir: Path) -> None:
        """Set the sandbox temporary directory parameter."""
        self._params["SANDBOX_TMPDIR"] = str(tmpdir.resolve())

    def add_network_rules(self) -> None:
        """Add network rules based on config."""
        seatbelt_opts = self._config.seatbelt
        if seatbelt_opts.allow_network:
            self._network_lines.extend([
                "; full network access",
                "(allow network-outbound)",
                "(allow network-inbound)",
            ])
            # Include network Mach services
            self._network_lines.append(self._load_network_policy())
        elif seatbelt_opts.allow_network_loopback:
            self._network_lines.extend([
                "; loopback-only network: deny remote, allow unix sockets",
                "(deny network-outbound)",
                "(allow network-outbound (remote unix-socket))",
                "(allow network-inbound (local unix-socket))",
            ])
        # else: no network rules → deny default blocks all

    def add_network_proxy(self, env: dict[str, str] | None = None) -> None:
        """Add proxy-routed network rules based on environment variables.

        Parses HTTP_PROXY/HTTPS_PROXY/ALL_PROXY to allow only proxy
        localhost ports and Unix sockets.
        """
        from ..proxy import extract_proxy_config

        seatbelt_opts = self._config.seatbelt
        proxy_config = extract_proxy_config(
            env=env,
            extra_unix_sockets=getattr(seatbelt_opts, "extra_unix_sockets", ()),
        )

        if not proxy_config.has_proxy:
            return

        # If network is fully allowed, proxy rules are redundant
        if seatbelt_opts.allow_network:
            return

        # Override simple loopback rules with precise proxy-routed rules
        self._network_lines.clear()
        self._network_lines.append("; proxy-routed network mode")

        # Allow connections only to proxy ports on localhost
        for port in proxy_config.loopback_ports:
            self._network_lines.append(
                f'(allow network-outbound (remote ip "localhost:{port}"))'
            )

        # Allow Unix socket connections for proxy
        for index, socket_path in enumerate(proxy_config.unix_sockets):
            param_key = f"UNIX_SOCKET_{index}"
            self._params[param_key] = socket_path
            self._network_lines.append(
                f'(allow network-outbound (remote unix-socket (subpath (param "{param_key}"))))'
            )
            # Socket may need file-read/write for connection
            self._network_lines.append(
                f'(allow file-read* file-write* (literal (param "{param_key}")))'
            )

        # Include network Mach services for TLS/DNS
        self._network_lines.append(self._load_network_policy())

    def add_deny_read_globs(self, globs: tuple[str, ...] | list[str] = ()) -> None:
        """Add deny-read rules converted from glob patterns.

        Converts each glob pattern to a Seatbelt regex and emits
        ``(deny file-read* (regex #"..."))`` rules.
        """
        from ..glob_to_regex import format_seatbelt_deny_read

        for pattern in globs:
            rule = format_seatbelt_deny_read(pattern)
            if rule:
                self._extra_policy_lines.append(rule)

    def add_deny_write_paths(self, paths: tuple[str, ...] | list[str] = ()) -> None:
        """Add deny-write rules for specific paths.

        Each path becomes a ``(deny file-write* (subpath "..."))`` rule
        that takes precedence over any allow-write rules.
        """
        for path_str in paths:
            resolved = str(Path(path_str).expanduser().resolve())
            param_key = f"DENY_WRITE_{len(self._params)}"
            self._params[param_key] = resolved
            self._extra_policy_lines.append(
                f'(deny file-write* (subpath (param "{param_key}")))'
            )

    def add_toolchain_paths(self, home: Path) -> None:
        """Add common developer toolchain paths as readable + executable.

        Auto-detects installed version managers (pyenv, nvm, rustup, etc.)
        and adds their directories to the read+exec whitelist.
        """
        _TOOLCHAIN_DIRS = (
            ".pyenv", ".nvm", ".fnm", ".rustup", ".cargo",
            ".local", "go", ".volta", ".bun", ".deno",
            ".sdkman", ".jabba", ".rbenv",
        )
        lines: list[str] = []
        for dirname in _TOOLCHAIN_DIRS:
            toolchain_path = home / dirname
            if toolchain_path.exists():
                param_key = f"TOOLCHAIN_{dirname.lstrip('.').upper()}"
                self._params[param_key] = str(toolchain_path.resolve())
                lines.append(f'(allow file-read* file-test-existence file-map-executable (subpath (param "{param_key}")))')
        if lines:
            self._extra_policy_lines.append("; --- Developer toolchain paths ---")
            self._extra_policy_lines.extend(lines)

    @staticmethod
    def _load_network_policy() -> str:
        """Load the network policy SBPL fragment."""
        try:
            ref = importlib_resources.files(__package__) / "seatbelt_network_policy.sbpl"
            return ref.read_text(encoding="utf-8")
        except (TypeError, FileNotFoundError, OSError):
            policy_path = Path(__file__).parent / "seatbelt_network_policy.sbpl"
            return policy_path.read_text(encoding="utf-8")

    def render(self) -> tuple[str, list[str]]:
        """Render the complete policy and -D parameter list.

        Returns:
            A tuple of (policy_text, params_argv) where params_argv is a list
            of strings like ["-DWRITABLE_ROOT_0=/path", "-DHOME_SSH=/path", ...].
        """
        sections: list[str] = []
        seatbelt_opts = self._config.seatbelt

        # 1. Base policy (static template — includes sysctl whitelist, PTY, mach)
        base = _get_base_policy()

        # Phase 2: If restrict_file_read is enabled, remove the blanket
        # (allow file-read*) from base and replace with platform defaults.
        if seatbelt_opts.restrict_file_read:
            # Remove the blanket file-read* line from base policy
            base_lines = base.splitlines()
            filtered_lines = []
            for line in base_lines:
                stripped = line.strip()
                # Remove the blanket allow but keep credential deny rules
                if stripped == "(allow file-read*)" and "credential" not in line.lower():
                    filtered_lines.append("; (allow file-read*) — REMOVED by restrict_file_read mode")
                else:
                    filtered_lines.append(line)
            sections.append("\n".join(filtered_lines))

            # Add platform defaults (precise read whitelist)
            sections.append("; --- Platform defaults: precise read whitelist ---")
            sections.append(_get_platform_defaults())

            # Writable roots are implicitly readable
            readable_from_writable = self._render_readable_from_writable_roots()
            if readable_from_writable:
                sections.append(readable_from_writable)

            # Extra readable paths from config
            extra_readable = self._render_extra_readable_paths()
            if extra_readable:
                sections.append(extra_readable)
        else:
            sections.append(base)

        # 2. Dynamic writable-root rules
        writable_section = self._render_writable_roots()
        if writable_section:
            sections.append(writable_section)

        # 3. Network rules
        if self._network_lines:
            sections.append("\n".join(self._network_lines))

        # 4. Extra policy lines
        if self._extra_policy_lines:
            sections.append("\n".join(self._extra_policy_lines))

        policy_text = "\n\n".join(sections)

        # Build -D parameter list
        params_argv: list[str] = []
        for key, value in sorted(self._params.items()):
            params_argv.append(f"-D{key}={value}")

        return policy_text, params_argv

    def _render_writable_roots(self) -> str:
        """Render parameterized writable-root rules with exclusions."""
        if not self._writable_roots:
            return ""

        lines: list[str] = ["; --- Dynamic writable roots ---"]

        for index, (root_path, exclusions) in enumerate(self._writable_roots):
            param_key = f"WRITABLE_ROOT_{index}"
            self._params[param_key] = str(root_path)

            if not exclusions:
                # Simple case: no exclusions
                lines.append(f'(allow file-write* (subpath (param "{param_key}")))')
            else:
                # Complex case: require-all with require-not exclusions
                parts = [f'(subpath (param "{param_key}"))']
                for pattern in exclusions:
                    # Escape quotes in regex patterns for SBPL
                    escaped = pattern.replace('"', '\\"')
                    parts.append(f'(require-not (regex #"{escaped}"))')
                require_body = " ".join(parts)
                lines.append(f"(allow file-write* (require-all {require_body}))")

        return "\n".join(lines)

    def _render_readable_from_writable_roots(self) -> str:
        """Writable roots are implicitly readable (for restrict_file_read mode)."""
        if not self._writable_roots:
            return ""

        lines: list[str] = ["; --- Writable roots are implicitly readable ---"]
        for index, _ in enumerate(self._writable_roots):
            param_key = f"WRITABLE_ROOT_{index}"
            lines.append(f'(allow file-read* (subpath (param "{param_key}")))')
        return "\n".join(lines)

    def _render_extra_readable_paths(self) -> str:
        """Render extra readable paths from config."""
        seatbelt_opts = self._config.seatbelt
        if not seatbelt_opts.extra_readable_paths:
            return ""

        lines: list[str] = ["; --- Extra readable paths from config ---"]
        for index, extra_path in enumerate(seatbelt_opts.extra_readable_paths):
            resolved = str(Path(extra_path).resolve())
            param_key = f"EXTRA_READABLE_{index}"
            self._params[param_key] = resolved
            lines.append(f'(allow file-read* (subpath (param "{param_key}")))')
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Seatbelt backend
# ---------------------------------------------------------------------------

class SeatbeltBackend:
    """macOS Seatbelt sandbox backend using ``/usr/bin/sandbox-exec``.

    Each session gets a temporary directory and a dynamically generated Seatbelt
    policy that is delivered inline via ``-p`` with parameterized paths via ``-D``.

    Security properties:
    - Policy is inline (not a temp file) — cannot be tampered by child process
    - Paths are parameterized — prevents policy injection via special characters
    - Writable roots exclude .git, .codex, .claude — prevents sandbox escape
    - mach-lookup restricted to essential services — prevents Keychain access
    - Credential directories denied — ~/.ssh, ~/.aws, ~/.gnupg not readable
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

        # Write initial snapshot that sources the cwd marker
        snapshot_path.write_text(
            f"# Elephant Seatbelt sandbox snapshot for session {session_id}\n"
            f'if [ -f "{cwd_file}" ]; then\n'
            f'  cd "$(cat "{cwd_file}")" 2>/dev/null || true\n'
            f"fi\n",
            encoding="utf-8",
        )
        cwd_file.write_text(str(cwd), encoding="utf-8")

        handle = SessionHandle(
            session_id=session_id,
            backend_id=self.BACKEND_ID,
            sandbox_root=sandbox_root,
            cwd=cwd,
            snapshot_path=snapshot_path,
            cwd_file=cwd_file,
            # No policy file path in attachments — policy is inline now
            attachments=(),
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
        exempt_vars = tuple(self._config.allow_delta.get("env") or [])
        sanitized_env = self._security_guard.sanitize_env(
            base_env, extra_env=env, exempt_vars=exempt_vars,
        )
        sanitized_env["ELEPHANT_SANDBOX_SESSION"] = handle.session_id
        sanitized_env["ELEPHANT_SANDBOX"] = "seatbelt"

        # Build policy with SeatbeltPolicyBuilder
        policy_text, policy_params = self._build_policy(effective_cwd, handle.sandbox_root)

        # Build sandbox-exec argv with inline policy (-p) and -D params
        sandbox_argv = [
            _SANDBOX_EXEC_PATH,
            "-p", policy_text,
            *policy_params,
            "--",
            "/bin/sh", "-c", wrapped_command,
        ]

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

        # Detect sandbox violations from stderr AND stdout (commands often redirect stderr to stdout)
        combined_output = result.stderr + "\n" + result.stdout
        diagnostics.extend(self._detect_violations(combined_output, command))

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

    def _build_policy(self, cwd: Path, sandbox_root: Path) -> tuple[str, list[str]]:
        """Build the complete Seatbelt policy for a command execution.

        Returns (policy_text, ["-DKEY=VALUE", ...]).
        """
        builder = SeatbeltPolicyBuilder(self._config)

        # Writable root: workspace cwd with protected-path exclusions
        # Only add cwd as writable if workspace_access allows writes
        seatbelt_opts = self._config.seatbelt
        exclusions = list(seatbelt_opts.protected_paths)
        if self._config.workspace_access == "rw":
            builder.add_writable_root(cwd, exclusions=exclusions)

        # Extra writable roots from config
        for extra_root in seatbelt_opts.extra_writable_roots:
            builder.add_writable_root(Path(extra_root).resolve(), exclusions=exclusions)

        # Sandbox temp directory
        builder.add_sandbox_tmpdir(sandbox_root)

        # Credential deny rules
        if seatbelt_opts.deny_read_credentials:
            builder.add_credential_deny(Path.home())

        # Developer toolchain paths (auto-detected)
        if seatbelt_opts.restrict_file_read:
            builder.add_toolchain_paths(Path.home())

        # Network rules (basic)
        builder.add_network_rules()

        # Network proxy-routed mode (Phase 3)
        if getattr(seatbelt_opts, "network_proxy_mode", False):
            builder.add_network_proxy()

        # Deny-read glob patterns (Phase 3)
        deny_globs = getattr(seatbelt_opts, "deny_read_globs", ())
        if deny_globs:
            builder.add_deny_read_globs(deny_globs)

        # Deny-write paths from deny delta
        deny_write_paths = tuple(self._config.deny_delta.get("write") or [])
        if deny_write_paths:
            builder.add_deny_write_paths(deny_write_paths)

        return builder.render()

    @staticmethod
    def _detect_violations(stderr: str, command: str) -> list[str]:
        """Detect sandbox violations from stderr and produce structured diagnostics.

        Parses "Operation not permitted" patterns and maps them to known
        protection reasons for better agent/user feedback.
        """
        import re

        if "Operation not permitted" not in stderr and "permission denied" not in stderr.lower():
            return []

        diagnostics: list[str] = []

        # Known protection patterns and their reasons
        _VIOLATION_PATTERNS = (
            (r"\.git/hooks", "sandbox:denied:write .git/hooks (protected: git hook injection prevention)"),
            (r"\.claude/settings", "sandbox:denied:write .claude/settings (protected: config tampering prevention)"),
            (r"\.claude/skills", "sandbox:denied:write .claude/skills (protected: code injection prevention)"),
            (r"\.claude/commands", "sandbox:denied:write .claude/commands (protected: code injection prevention)"),
            (r"\.claude/agents", "sandbox:denied:write .claude/agents (protected: code injection prevention)"),
            (r"\.ssh", "sandbox:denied:read ~/.ssh (protected: credential protection)"),
            (r"\.aws", "sandbox:denied:read ~/.aws (protected: credential protection)"),
            (r"\.gnupg", "sandbox:denied:read ~/.gnupg (protected: credential protection)"),
            (r"\.kube", "sandbox:denied:read ~/.kube (protected: credential protection)"),
            (r"\.docker", "sandbox:denied:read ~/.docker (protected: credential protection)"),
        )

        combined_text = stderr + " " + command
        matched = False
        for pattern, reason in _VIOLATION_PATTERNS:
            if re.search(pattern, combined_text):
                diagnostics.append(reason)
                matched = True

        if not matched and "Operation not permitted" in stderr:
            # Generic violation — try to extract the path
            path_match = re.search(r"['\"]?(/[^\s'\"]+)['\"]?.*Operation not permitted", stderr)
            if path_match:
                diagnostics.append(f"sandbox:denied {path_match.group(1)} (Operation not permitted)")
            else:
                diagnostics.append("sandbox:denied (Operation not permitted — check sandbox policy)")

        # Network violations
        if any(indicator in stderr for indicator in (
            "Could not resolve host",
            "Connection refused",
            "connect to host",
            "Network is unreachable",
            "nodename nor servname",
        )):
            diagnostics.append("sandbox:denied:network (network isolated by sandbox policy)")

        return diagnostics
