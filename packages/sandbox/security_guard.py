"""Security guard for sandbox environment sanitization and path validation."""

from __future__ import annotations

import os
from pathlib import Path

_SAFE_PREFIXES = (
    "PATH",
    "HOME",
    "USER",
    "LANG",
    "LC_",
    "TERM",
    "TMP",
    "TEMP",
    "SHELL",
    "VIRTUAL_ENV",
    "CONDA",
)

_SECRET_FRAGMENTS = (
    "KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "CREDENTIAL",
    "PASSWD",
    "AUTH",
)

_SENSITIVE_SYSTEM_PREFIXES = (
    Path("/etc"),
    Path("/boot"),
    Path("/usr/lib/systemd"),
    Path("/private/etc"),
)

_SENSITIVE_EXACT_PATHS = (
    Path("/var/run/docker.sock"),
    Path("/run/docker.sock"),
)

_SENSITIVE_HOME_EXACT_NAMES = (
    ".bash_profile",
    ".bashrc",
    ".env",
    ".netrc",
    ".npmrc",
    ".pgpass",
    ".profile",
    ".pypirc",
    ".zprofile",
    ".zshrc",
)

_SENSITIVE_HOME_PREFIX_NAMES = (
    ".aws",
    ".azure",
    ".docker",
    ".gnupg",
    ".kube",
    ".ssh",
)


class SecurityGuard:
    """Sanitizes environments and validates paths for sandboxed execution."""

    def sanitize_env(
        self,
        base_env: dict[str, str],
        extra_env: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Build a sanitized environment dict.

        Starts from base_env, keeps only keys with safe prefixes, excludes
        keys containing secret fragments, then overlays extra_env, and
        finally adds sandbox-specific variables.
        """
        env: dict[str, str] = {}
        for key, value in base_env.items():
            if any(fragment in key.upper() for fragment in _SECRET_FRAGMENTS):
                continue
            if any(key.startswith(prefix) for prefix in _SAFE_PREFIXES):
                env[key] = value
        if extra_env:
            env.update(extra_env)
        env["ELEPHANT_SANDBOX"] = "1"
        return env

    def validate_sensitive_host_path(self, path: Path) -> str | None:
        """Return a reason string if *path* is sensitive, None otherwise.

        Does NOT block the workspace cwd itself — callers are expected to
        allow the workspace root explicitly.
        """
        resolved = path.expanduser().resolve(strict=False)
        home = Path.home().resolve()

        # System-level paths — check both the original (pre-symlink) path
        # and the resolved path, since macOS /var -> /private/var
        for exact in _SENSITIVE_EXACT_PATHS:
            if path == exact or resolved == exact or resolved == exact.resolve():
                return f"sensitive system path: {path}"

        for prefix in _SENSITIVE_SYSTEM_PREFIXES:
            if _path_is_relative_to(resolved, prefix):
                return f"sensitive system prefix: {path}"

        # Home-directory exact matches
        for name in _SENSITIVE_HOME_EXACT_NAMES:
            if resolved == home / name:
                return f"sensitive home file: {path}"

        # Home-directory prefix matches
        for name in _SENSITIVE_HOME_PREFIX_NAMES:
            if _path_is_relative_to(resolved, home / name):
                return f"sensitive credential directory: {path}"

        return None

    def validate_bind_mounts(
        self, mounts: list[tuple[Path, str]],
    ) -> list[tuple[Path, str, str]]:
        """Validate a list of bind mount specifications for container backends.

        Each mount is a ``(host_path, access_mode)`` tuple where
        *access_mode* is ``"ro"`` or ``"rw"``.

        Returns a list of ``(host_path, access_mode, reason)`` tuples for
        rejected mounts.  An empty list means all mounts are allowed.
        """
        rejected: list[tuple[Path, str, str]] = []
        for host_path, access_mode in mounts:
            reason = self.validate_sensitive_host_path(host_path)
            if reason:
                rejected.append((host_path, access_mode, reason))
            elif access_mode not in ("ro", "rw"):
                rejected.append(
                    (host_path, access_mode, f"invalid access mode: {access_mode}")
                )
        return rejected

    def validate_network_mode(self, mode: str) -> str | None:
        """Validate a Docker network mode string.

        Returns a reason string if the mode is disallowed, ``None`` if
        the mode is acceptable.

        By default only ``"none"`` and ``"bridge"`` are allowed.
        ``"host"`` is rejected because it defeats network isolation.
        """
        _ALLOWED_NETWORK_MODES = ("none", "bridge")
        if mode in _ALLOWED_NETWORK_MODES:
            return None
        if mode == "host":
            return "host network mode is not allowed: defeats network isolation"
        return f"unknown network mode: {mode}"


def _path_is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
