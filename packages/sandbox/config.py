"""Sandbox configuration types."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

SandboxMode = Literal["off", "all", "non-main"]
SandboxBackend = Literal["local", "docker", "ssh", "seatbelt", "cloud"]
SandboxScope = Literal["session", "agent", "shared"]
WorkspaceAccess = Literal["none", "ro", "rw"]


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

    mode: SandboxMode = "off"
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

    @property
    def is_active(self) -> bool:
        return self.mode != "off"

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
        seatbelt_options = SeatbeltSandboxOptions(
            allow_network=bool(seatbelt_raw.get("allow_network", False)),
            allow_network_loopback=bool(seatbelt_raw.get("allow_network_loopback", True)),
            allow_writable_tmp=bool(seatbelt_raw.get("allow_writable_tmp", True)),
        ) if isinstance(seatbelt_raw, Mapping) else SeatbeltSandboxOptions()

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

        return cls(
            mode=str(section.get("mode", "off")),
            backend=str(section.get("backend", "local")),
            scope=str(section.get("scope", "session")),
            workspace_access=str(section.get("workspace_access", "none")),
            resource_limits=resource_limits,
            docker=docker_options,
            ssh=ssh_options,
            seatbelt=seatbelt_options,
            cloud=cloud_options,
            clouds=clouds,
            cloud_profile=cloud_profile,
        )

    def to_config_section(self) -> dict[str, Any]:
        """Serialize to a dict suitable for the ``sandbox:`` YAML section."""
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
