"""Sandbox configuration types."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

# Legacy mode values (backward compat)
LegacySandboxMode = Literal["off", "all", "non-main"]
# New mode values introduced in sandbox-ux
NewSandboxMode = Literal["readonly", "safe", "dev", "open"]
# Combined type for the mode field
SandboxModeStr = Literal["off", "all", "non-main", "readonly", "safe", "dev", "open"]

SandboxBackend = Literal["local", "docker", "ssh", "seatbelt", "cloud"]
SandboxScope = Literal["session", "agent", "shared"]
WorkspaceAccess = Literal["none", "ro", "rw"]

# New mode values that trigger the new code path
_NEW_MODE_VALUES = frozenset({"readonly", "safe", "dev", "open"})



@dataclass(frozen=True, slots=True)
class DockerSandboxOptions:
    """Docker-specific sandbox options."""

    image: str = "elephant-sandbox"


@dataclass(frozen=True, slots=True)
class SshSandboxOptions:
    """SSH-specific sandbox options."""

    host: str = ""
    port: int = 22
    user: str = ""
    identity_file: str = ""


@dataclass(frozen=True, slots=True)
class SeatbeltSandboxOptions:
    """macOS Seatbelt-specific sandbox options."""

    allow_network: bool = False
    allow_network_loopback: bool = True
    allow_writable_tmp: bool = True

    # Protected metadata patterns — regex patterns for deny-write within
    # writable roots.  Only .git/hooks is blocked (not the entire .git dir)
    # so that git commit/checkout works normally.
    protected_paths: tuple[str, ...] = (
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

    # Phase 1: Block reads to credential directories (~/.ssh, ~/.aws, etc.)
    deny_read_credentials: bool = True

    # Phase 1: Mach service whitelist — only these services are allowed.
    # Prevents Keychain access via com.apple.security.keychain.
    mach_services: tuple[str, ...] = (
        "com.apple.system.opendirectoryd.libinfo",
        "com.apple.PowerManagement.control",
        "com.apple.cfprefsd.daemon",
        "com.apple.cfprefsd.agent",
    )

    # Phase 1: Additional writable roots beyond the workspace cwd.
    extra_writable_roots: tuple[str, ...] = ()

    # Phase 2: Replace (allow file-read*) with precise system path whitelist.
    # When False, falls back to blanket file-read (legacy/escape hatch).
    restrict_file_read: bool = True

    # Phase 2: Additional paths to include in the read whitelist.
    extra_readable_paths: tuple[str, ...] = ()

    # Phase 3: Enable proxy-routed network (extract ports from env vars).
    network_proxy_mode: bool = False

    # Phase 3: Additional Unix socket paths to allow in proxy mode.
    extra_unix_sockets: tuple[str, ...] = ()

    # Phase 3: Glob patterns to deny-read (converted to Seatbelt regex).
    deny_read_globs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CloudProfileOptions:
    """A single cloud sandbox profile.

    ``provider`` determines which cloud backend implementation to use
    (``"tencent"``, ``"e2b"``, ``"aws"``, …).  The ``extra`` dict holds
    provider-specific fields that don't fit the common schema.
    """

    provider: str = "tencent"
    template: str = ""
    browser_template: str = ""
    domain: str = "ap-guangzhou.tencentags.com"
    api_key: str = ""
    timeout: int = 3600
    allow_internet: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


# Backward-compat alias — existing code that references ``CloudSandboxOptions``
# continues to work, but new code should prefer ``CloudProfileOptions``.
CloudSandboxOptions = CloudProfileOptions


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    """Resource constraints applied to sandboxed executions."""

    max_wall_seconds: int = 120
    max_memory_mb: int = 512
    max_processes: int = 256
    max_file_size_mb: int = 50
    max_stdout_bytes: int = 50_000
    max_stderr_bytes: int = 10_000


def _parse_cloud_profile(raw: Mapping[str, Any]) -> CloudProfileOptions:
    """Parse a cloud profile mapping into ``CloudProfileOptions``."""
    extra_raw = raw.get("extra", {})
    extra = dict(extra_raw) if isinstance(extra_raw, Mapping) else {}
    # Strip keys that are already top-level fields
    _TOP_LEVEL_KEYS = frozenset({
        "provider", "template", "browser_template", "domain", "api_key", "timeout", "allow_internet", "extra",
    })
    for key in list(raw.keys()):
        if key not in _TOP_LEVEL_KEYS:
            extra[key] = raw[key]
    return CloudProfileOptions(
        provider=str(raw.get("provider", "tencent")),
        template=str(raw.get("template", "")),
        browser_template=str(raw.get("browser_template", "")),
        domain=str(raw.get("domain", "ap-guangzhou.tencentags.com")),
        api_key=str(raw.get("api_key", "")),
        timeout=int(raw.get("timeout", 3600)),
        allow_internet=bool(raw.get("allow_internet", True)),
        extra=extra,
    )


@dataclass(frozen=True, slots=True)
class SandboxConfig:
    """Top-level sandbox configuration."""

    mode: SandboxModeStr = "off"
    backend: SandboxBackend = "local"
    scope: SandboxScope = "session"
    workspace_access: WorkspaceAccess = "none"
    resource_limits: ResourceLimits = field(default_factory=ResourceLimits)
    docker: DockerSandboxOptions = field(default_factory=DockerSandboxOptions)
    ssh: SshSandboxOptions = field(default_factory=SshSandboxOptions)
    seatbelt: SeatbeltSandboxOptions = field(default_factory=SeatbeltSandboxOptions)
    cloud: CloudProfileOptions = field(default_factory=CloudProfileOptions)
    clouds: dict[str, CloudProfileOptions] = field(default_factory=dict)
    cloud_profile: str = ""

    # --- New-style fields (Phase 1: sandbox-ux) ---
    # These are populated when mode is one of: readonly, safe, dev, open
    allow_delta: dict[str, Any] = field(default_factory=dict)
    deny_delta: dict[str, Any] = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        return self.mode != "off"

    @property
    def is_new_mode(self) -> bool:
        """True if using the new mode abstraction (readonly/safe/dev/open)."""
        return self.mode in _NEW_MODE_VALUES

    def effective_cloud(self) -> CloudProfileOptions:
        """Resolve the active cloud profile.

        If ``cloud_profile`` names an entry in ``clouds``, use that.
        Otherwise fall back to the single ``cloud`` field (backward compat).
        """
        if self.cloud_profile and self.cloud_profile in self.clouds:
            return self.clouds[self.cloud_profile]
        return self.cloud

    @classmethod
    def from_config_section(cls, section: Mapping[str, Any]) -> SandboxConfig:
        """Build a ``SandboxConfig`` from the ``sandbox:`` YAML section.

        Unknown keys are silently ignored so that forward-compatible config
        files do not break older agents.
        """
        rl_raw = section.get("resource_limits", {})
        resource_limits = ResourceLimits(
            max_wall_seconds=int(rl_raw.get("max_wall_seconds", 120)),
            max_memory_mb=int(rl_raw.get("max_memory_mb", 512)),
            max_processes=int(rl_raw.get("max_processes", 256)),
            max_file_size_mb=int(rl_raw.get("max_file_size_mb", 50)),
        ) if isinstance(rl_raw, Mapping) else ResourceLimits()

        docker_raw = section.get("docker", {})
        docker_options = DockerSandboxOptions(
            image=str(docker_raw.get("image", "elephant-sandbox")),
        ) if isinstance(docker_raw, Mapping) else DockerSandboxOptions()

        ssh_raw = section.get("ssh", {})
        ssh_options = SshSandboxOptions(
            host=str(ssh_raw.get("host", "")),
            port=int(ssh_raw.get("port", 22)),
            user=str(ssh_raw.get("user", "")),
            identity_file=str(ssh_raw.get("identity_file", "")),
        ) if isinstance(ssh_raw, Mapping) else SshSandboxOptions()

        seatbelt_raw = section.get("seatbelt", {})
        if isinstance(seatbelt_raw, Mapping):
            # Defaults must be specified inline because slots=True prevents
            # class-level attribute access to tuple defaults.
            _DEFAULT_PROTECTED = (
                r"(^|/)\.git/hooks(/.*)?$",
                r"(^|/)\.claude/settings[^/]*$",
                r"(^|/)\.claude/settings\.local[^/]*$",
                r"(^|/)\.claude/skills(/.*)?$",
                r"(^|/)\.claude/commands(/.*)?$",
                r"(^|/)\.claude/agents(/.*)?$",
            )
            _DEFAULT_MACH = (
                "com.apple.system.opendirectoryd.libinfo",
                "com.apple.PowerManagement.control",
                "com.apple.cfprefsd.daemon",
                "com.apple.cfprefsd.agent",
            )
            protected_raw = seatbelt_raw.get("protected_paths")
            protected_paths = (
                tuple(str(p) for p in protected_raw)
                if isinstance(protected_raw, (list, tuple))
                else _DEFAULT_PROTECTED
            )
            mach_raw = seatbelt_raw.get("mach_services")
            mach_services = (
                tuple(str(s) for s in mach_raw)
                if isinstance(mach_raw, (list, tuple))
                else _DEFAULT_MACH
            )
            extra_writable_raw = seatbelt_raw.get("extra_writable_roots")
            extra_writable_roots = (
                tuple(str(p) for p in extra_writable_raw)
                if isinstance(extra_writable_raw, (list, tuple))
                else ()
            )
            extra_readable_raw = seatbelt_raw.get("extra_readable_paths")
            extra_readable_paths = (
                tuple(str(p) for p in extra_readable_raw)
                if isinstance(extra_readable_raw, (list, tuple))
                else ()
            )
            seatbelt_options = SeatbeltSandboxOptions(
                allow_network=bool(seatbelt_raw.get("allow_network", False)),
                allow_network_loopback=bool(seatbelt_raw.get("allow_network_loopback", True)),
                allow_writable_tmp=bool(seatbelt_raw.get("allow_writable_tmp", True)),
                protected_paths=protected_paths,
                deny_read_credentials=bool(seatbelt_raw.get("deny_read_credentials", True)),
                mach_services=mach_services,
                extra_writable_roots=extra_writable_roots,
                restrict_file_read=bool(seatbelt_raw.get("restrict_file_read", True)),
                extra_readable_paths=extra_readable_paths,
            )
        else:
            seatbelt_options = SeatbeltSandboxOptions()

        # Single cloud profile (backward compat)
        cloud_raw = section.get("cloud", {})
        cloud_options = (
            _parse_cloud_profile(cloud_raw)
            if isinstance(cloud_raw, Mapping) else CloudProfileOptions()
        )

        # Multi-profile clouds dict
        clouds_raw = section.get("clouds", {})
        clouds: dict[str, CloudProfileOptions] = {}
        if isinstance(clouds_raw, Mapping):
            for name, cfg in clouds_raw.items():
                if isinstance(cfg, Mapping):
                    clouds[str(name)] = _parse_cloud_profile(cfg)

        cloud_profile = str(section.get("cloud_profile", ""))

        # --- New-style allow/deny delta (sandbox-ux) ---
        mode_str = str(section.get("mode", "off"))
        allow_raw = section.get("allow", {})
        deny_raw = section.get("deny", {})
        allow_delta = dict(allow_raw) if isinstance(allow_raw, Mapping) else {}
        deny_delta = dict(deny_raw) if isinstance(deny_raw, Mapping) else {}

        # If using new mode (readonly/safe/dev/open), auto-configure backend
        # and workspace_access based on mode semantics.
        resolved_backend = str(section.get("backend", "local"))
        resolved_workspace_access = str(section.get("workspace_access", "none"))

        if mode_str in _NEW_MODE_VALUES:
            # New mode always uses seatbelt on macOS
            if resolved_backend == "local":
                resolved_backend = "seatbelt"
            # Set workspace_access based on mode
            if mode_str == "readonly":
                resolved_workspace_access = "ro"
            else:
                resolved_workspace_access = "rw"

            # --- Use sandbox_mode.mode_to_policy() for authoritative derivation ---
            from .sandbox_mode import SandboxMode, AllowDenyDelta, mode_to_policy

            mode_enum = SandboxMode.from_str(mode_str)
            delta = AllowDenyDelta.from_config({"allow": allow_delta, "deny": deny_delta})
            spec = mode_to_policy(mode_enum, delta)

            # Build the seatbelt options from the derived PolicySpec
            seatbelt_options = SeatbeltSandboxOptions(
                allow_network=spec.allow_network,
                allow_network_loopback=spec.allow_network_loopback,
                allow_writable_tmp=True,
                protected_paths=seatbelt_options.protected_paths,
                deny_read_credentials=spec.deny_read_credentials,
                mach_services=seatbelt_options.mach_services,
                extra_writable_roots=tuple(spec.extra_readable_paths),  # allow.write paths
                restrict_file_read=spec.restrict_file_read,
                extra_readable_paths=tuple(spec.extra_readable_paths),
                deny_read_globs=spec.deny_read_globs,
            )
            # Override extra_writable_roots with the actual write paths from delta
            if delta.allow_write:
                seatbelt_options = SeatbeltSandboxOptions(
                    allow_network=seatbelt_options.allow_network,
                    allow_network_loopback=seatbelt_options.allow_network_loopback,
                    allow_writable_tmp=seatbelt_options.allow_writable_tmp,
                    protected_paths=seatbelt_options.protected_paths,
                    deny_read_credentials=seatbelt_options.deny_read_credentials,
                    mach_services=seatbelt_options.mach_services,
                    extra_writable_roots=tuple(str(p) for p in delta.allow_write),
                    restrict_file_read=seatbelt_options.restrict_file_read,
                    extra_readable_paths=seatbelt_options.extra_readable_paths,
                    deny_read_globs=seatbelt_options.deny_read_globs,
                )

        return cls(
            mode=mode_str,
            backend=resolved_backend,
            scope=str(section.get("scope", "session")),
            workspace_access=resolved_workspace_access,
            resource_limits=resource_limits,
            docker=docker_options,
            ssh=ssh_options,
            seatbelt=seatbelt_options,
            cloud=cloud_options,
            clouds=clouds,
            cloud_profile=cloud_profile,
            allow_delta=allow_delta,
            deny_delta=deny_delta,
        )

    def to_config_section(self) -> dict[str, Any]:
        """Serialize to a dict suitable for the ``sandbox:`` YAML section.

        For new-style modes (readonly/safe/dev/open), produces a compact format
        with just mode + allow/deny. For legacy modes, produces the full format.
        """
        if self.is_new_mode:
            # New compact format
            result: dict[str, Any] = {"mode": self.mode}
            if self.allow_delta:
                result["allow"] = dict(self.allow_delta)
            if self.deny_delta:
                result["deny"] = dict(self.deny_delta)
            # Include resource_limits if non-default
            rl = self.resource_limits
            if rl.max_wall_seconds != 120 or rl.max_memory_mb != 512:
                result["resource_limits"] = {
                    "max_wall_seconds": rl.max_wall_seconds,
                    "max_memory_mb": rl.max_memory_mb,
                    "max_processes": rl.max_processes,
                    "max_file_size_mb": rl.max_file_size_mb,
                }
            return result

        # Legacy full format
        result: dict[str, Any] = {
            "mode": self.mode,
            "backend": self.backend,
            "scope": self.scope,
            "workspace_access": self.workspace_access,
            "resource_limits": {
                "max_wall_seconds": self.resource_limits.max_wall_seconds,
                "max_memory_mb": self.resource_limits.max_memory_mb,
                "max_processes": self.resource_limits.max_processes,
                "max_file_size_mb": self.resource_limits.max_file_size_mb,
            },
            "docker": {
                "image": self.docker.image,
            },
            "ssh": {
                "host": self.ssh.host,
                "port": self.ssh.port,
                "user": self.ssh.user,
                "identity_file": self.ssh.identity_file,
            },
            "seatbelt": {
                "allow_network": self.seatbelt.allow_network,
                "allow_network_loopback": self.seatbelt.allow_network_loopback,
                "allow_writable_tmp": self.seatbelt.allow_writable_tmp,
                "protected_paths": list(self.seatbelt.protected_paths),
                "deny_read_credentials": self.seatbelt.deny_read_credentials,
                "mach_services": list(self.seatbelt.mach_services),
                "extra_writable_roots": list(self.seatbelt.extra_writable_roots),
                "restrict_file_read": self.seatbelt.restrict_file_read,
                "extra_readable_paths": list(self.seatbelt.extra_readable_paths),
            },
            "cloud": _profile_to_dict(self.cloud),
        }
        if self.clouds:
            result["clouds"] = {
                name: _profile_to_dict(profile)
                for name, profile in self.clouds.items()
            }
        if self.cloud_profile:
            result["cloud_profile"] = self.cloud_profile
        return result


def _profile_to_dict(profile: CloudProfileOptions) -> dict[str, Any]:
    """Serialize a ``CloudProfileOptions`` to a plain dict."""
    d: dict[str, Any] = {
        "provider": profile.provider,
        "template": profile.template,
        "browser_template": profile.browser_template,
        "domain": profile.domain,
        "api_key": profile.api_key,
        "timeout": profile.timeout,
        "allow_internet": profile.allow_internet,
    }
    if profile.extra:
        d["extra"] = dict(profile.extra)
    return d
