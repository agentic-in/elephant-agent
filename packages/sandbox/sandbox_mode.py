"""High-level sandbox mode abstraction.

Provides a declarative "Mode + allow/deny delta" system that maps
user-friendly configuration to low-level SeatbeltPolicyBuilder settings.

Mode hierarchy (tight → loose):
    readonly < safe < dev < open

Each mode defines sensible defaults for file-read, file-write, and network.
Users can apply allow/deny deltas on top of any mode.

Non-negotiable protected paths are always enforced regardless of mode or
user overrides (prevents sandbox escape vectors).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# SandboxMode enum
# ---------------------------------------------------------------------------


class SandboxMode(Enum):
    """High-level sandbox operating modes.

    Ordered from most restrictive to least restrictive:
    - readonly: no writes, no network, read system whitelist + cwd
    - safe: cwd writable, no network (default for most users)
    - dev: cwd writable, full network access
    - open: cwd writable, full read, full network (minimal restrictions)
    """

    READONLY = "readonly"
    SAFE = "safe"
    DEV = "dev"
    OPEN = "open"

    @classmethod
    def from_str(cls, value: str) -> "SandboxMode":
        """Parse a mode string, case-insensitive."""
        try:
            return cls(value.lower())
        except ValueError:
            valid = ", ".join(m.value for m in cls)
            raise ValueError(f"Invalid sandbox mode '{value}'. Valid modes: {valid}")

    @classmethod
    def is_new_mode(cls, value: str) -> bool:
        """Check if a mode string is a new-style mode (not legacy)."""
        try:
            cls(value.lower())
            return True
        except ValueError:
            return False


# ---------------------------------------------------------------------------
# Non-negotiable protected paths (cannot be overridden by allow)
# ---------------------------------------------------------------------------

# These regex patterns are always applied as write exclusions within
# writable roots. They protect against sandbox escape vectors.
PROTECTED_WRITE_PATTERNS: tuple[str, ...] = (
    # Git hook injection — sandbox escape vector
    r"(^|/)\.git/hooks(/.*)?$",
    # Configuration tampering
    r"(^|/)\.claude/settings[^/]*$",
    r"(^|/)\.claude/settings\.local[^/]*$",
    # Code injection via skills/commands/agents
    r"(^|/)\.claude/skills(/.*)?$",
    r"(^|/)\.claude/commands(/.*)?$",
    r"(^|/)\.claude/agents(/.*)?$",
)

# Credential directories that are always deny-read (non-negotiable)
PROTECTED_CREDENTIAL_DIRS: tuple[str, ...] = (
    ".ssh",
    ".aws",
    ".gnupg",
    ".kube",
    ".docker",
)

# Environment variable fragments that are always filtered
PROTECTED_ENV_FRAGMENTS: tuple[str, ...] = (
    "KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "CREDENTIAL",
    "PASSWD",
    "AUTH",
)


# ---------------------------------------------------------------------------
# Allow/Deny delta
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AllowDenyDelta:
    """User-specified overrides on top of a mode's defaults.

    Allow rules relax restrictions, deny rules tighten them.
    Priority: deny > allow > mode preset.
    Exception: non-negotiable protected paths cannot be overridden by allow.
    """

    # Network override
    allow_network: bool | None = None   # True = force open, False = force deny, None = use mode default
    deny_network: bool | None = None    # True = force deny regardless of mode

    # Additional readable paths (expand mode's read whitelist)
    allow_read: tuple[str, ...] = ()

    # Additional writable paths (expand beyond cwd)
    allow_write: tuple[str, ...] = ()

    # Environment variables to exempt from filtering
    allow_env: tuple[str, ...] = ()

    # Paths to deny reading (glob patterns, tighten beyond mode defaults)
    deny_read: tuple[str, ...] = ()

    # Paths to deny writing (restrict within otherwise-writable areas)
    deny_write: tuple[str, ...] = ()

    # Environment variables to force-filter
    deny_env: tuple[str, ...] = ()

    @classmethod
    def from_config(cls, section: dict[str, Any]) -> "AllowDenyDelta":
        """Parse allow/deny delta from config section.

        Expected format:
            allow:
              network: true
              read: ["~/.npmrc"]
              write: ["~/output"]
              env: ["NODE_AUTH_TOKEN"]
            deny:
              read: ["**/*.key"]
              write: ["/some/path"]
              env: ["SOME_VAR"]
        """
        allow_section = section.get("allow", {}) or {}
        deny_section = section.get("deny", {}) or {}

        # Parse network from allow/deny
        allow_network: bool | None = None
        deny_network: bool | None = None

        if "network" in allow_section:
            allow_network = bool(allow_section["network"])
        if "network" in deny_section:
            deny_network = bool(deny_section["network"])

        # Parse path lists
        allow_read = tuple(str(p) for p in (allow_section.get("read") or []))
        allow_write = tuple(str(p) for p in (allow_section.get("write") or []))
        allow_env = tuple(str(e) for e in (allow_section.get("env") or []))

        deny_read = tuple(str(p) for p in (deny_section.get("read") or []))
        deny_write = tuple(str(p) for p in (deny_section.get("write") or []))
        deny_env = tuple(str(e) for e in (deny_section.get("env") or []))

        return cls(
            allow_network=allow_network,
            deny_network=deny_network,
            allow_read=allow_read,
            allow_write=allow_write,
            allow_env=allow_env,
            deny_read=deny_read,
            deny_write=deny_write,
            deny_env=deny_env,
        )

    def to_config(self) -> dict[str, Any]:
        """Serialize to config dict format."""
        result: dict[str, Any] = {}

        allow: dict[str, Any] = {}
        if self.allow_network is not None:
            allow["network"] = self.allow_network
        if self.allow_read:
            allow["read"] = list(self.allow_read)
        if self.allow_write:
            allow["write"] = list(self.allow_write)
        if self.allow_env:
            allow["env"] = list(self.allow_env)

        deny: dict[str, Any] = {}
        if self.deny_network is not None:
            deny["network"] = self.deny_network
        if self.deny_read:
            deny["read"] = list(self.deny_read)
        if self.deny_write:
            deny["write"] = list(self.deny_write)
        if self.deny_env:
            deny["env"] = list(self.deny_env)

        if allow:
            result["allow"] = allow
        if deny:
            result["deny"] = deny
        return result


# ---------------------------------------------------------------------------
# Mode policy derivation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PolicySpec:
    """Derived policy specification from mode + delta.

    This is the intermediate representation that bridges the user-facing
    mode abstraction and the low-level SeatbeltPolicyBuilder.
    """

    # File write: paths that may be written to
    writable_roots: tuple[str, ...] = ()

    # File write: additional exclusion patterns (always includes PROTECTED_WRITE_PATTERNS)
    write_exclusions: tuple[str, ...] = ()

    # File read: whether to use platform whitelist (True) or allow-all (False)
    restrict_file_read: bool = True

    # File read: additional readable paths beyond system whitelist
    extra_readable_paths: tuple[str, ...] = ()

    # File read: glob patterns to deny
    deny_read_globs: tuple[str, ...] = ()

    # Network
    allow_network: bool = False
    allow_network_loopback: bool = True

    # Credential directories to deny read
    deny_read_credentials: bool = True

    # Environment variables to exempt from filtering
    exempt_env_vars: tuple[str, ...] = ()

    # Environment variables to force-filter (beyond default fragments)
    extra_deny_env: tuple[str, ...] = ()


def mode_to_policy(
    mode: SandboxMode,
    delta: AllowDenyDelta | None = None,
    *,
    cwd: Path | None = None,
) -> PolicySpec:
    """Derive a PolicySpec from a mode and optional allow/deny delta.

    This is the core function that bridges user-facing configuration
    to the technical policy specification.

    Parameters
    ----------
    mode:
        The base operating mode.
    delta:
        Optional allow/deny overrides.
    cwd:
        The workspace directory (used as writable root where applicable).

    Returns
    -------
    PolicySpec with all settings resolved.
    """
    delta = delta or AllowDenyDelta()
    cwd_str = str(cwd.resolve()) if cwd else "."

    # --- Base settings per mode ---
    if mode == SandboxMode.READONLY:
        writable_roots: list[str] = []
        restrict_file_read = True
        allow_network = False
        allow_network_loopback = False
    elif mode == SandboxMode.SAFE:
        writable_roots = [cwd_str]
        restrict_file_read = True
        allow_network = False
        allow_network_loopback = True
    elif mode == SandboxMode.DEV:
        writable_roots = [cwd_str]
        restrict_file_read = True
        allow_network = True
        allow_network_loopback = True
    elif mode == SandboxMode.OPEN:
        writable_roots = [cwd_str]
        restrict_file_read = False  # allow-all read
        allow_network = True
        allow_network_loopback = True
    else:
        # Fallback to safe
        writable_roots = [cwd_str]
        restrict_file_read = True
        allow_network = False
        allow_network_loopback = True

    # --- Apply allow delta ---

    # Network: allow overrides mode (but deny > allow)
    if delta.allow_network is True:
        allow_network = True
        allow_network_loopback = True

    # Additional writable paths
    extra_write: list[str] = []
    for path_str in delta.allow_write:
        resolved = str(Path(path_str).expanduser().resolve())
        extra_write.append(resolved)
    writable_roots.extend(extra_write)

    # Additional readable paths
    extra_readable: list[str] = list(delta.allow_read)

    # Exempt env vars
    exempt_env: list[str] = list(delta.allow_env)

    # --- Apply deny delta (deny > allow) ---

    # Network deny overrides everything
    if delta.deny_network is True:
        allow_network = False
        allow_network_loopback = False

    # Deny read globs
    deny_read_globs: list[str] = list(delta.deny_read)

    # Additional deny env
    extra_deny_env: list[str] = list(delta.deny_env)

    # --- Protected paths: always enforce (non-negotiable) ---
    write_exclusions = list(PROTECTED_WRITE_PATTERNS)

    return PolicySpec(
        writable_roots=tuple(writable_roots),
        write_exclusions=tuple(write_exclusions),
        restrict_file_read=restrict_file_read,
        extra_readable_paths=tuple(extra_readable),
        deny_read_globs=tuple(deny_read_globs),
        allow_network=allow_network,
        allow_network_loopback=allow_network_loopback,
        deny_read_credentials=True,  # always on
        exempt_env_vars=tuple(exempt_env),
        extra_deny_env=tuple(extra_deny_env),
    )
