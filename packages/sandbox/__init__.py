"""Elephant Agent sandbox execution package.

Provides sandboxed command execution with resource limits, environment
sanitization, and pluggable backends for isolated tool execution.
"""

from __future__ import annotations

from .backends.cloud_registry import get_cloud_backend, register_cloud_backend, registered_providers
from .backends.docker import DockerBackend
from .backends.local import LocalBackend
from .backends.seatbelt import SeatbeltBackend
from .backends.sdk import SDKBackend, SDKProvider
from .backends.ssh import SSHBackend
from .backends.tencent_cloud import TencentCloudBackend, TencentCloudFactory, TencentCloudSandboxProvider
from .code_launcher import CodeExecutionLauncher, LocalCodeLauncher, SandboxCodeLauncher
from .config import CloudProfileOptions, CloudSandboxOptions, DockerSandboxOptions, ResourceLimits, SandboxConfig, SeatbeltSandboxOptions, SshSandboxOptions
from .environment import SandboxEnvironment
from .executor import SandboxToolExecutor
from .path_mapper import SandboxPathMapper
from .process_manager import SandboxManagedProcess, SandboxProcessManager
from .resource_governor import ResourceGovernor
from .sandbox_mode import AllowDenyDelta, PolicySpec, SandboxMode, mode_to_policy, PROTECTED_WRITE_PATTERNS
from .scope_manager import SandboxScopeManager, SessionInfo
from .security_guard import SecurityGuard
from .types import EnvironmentBackend, SandboxOutput, SessionHandle

__all__ = [
    "AllowDenyDelta",
    "CodeExecutionLauncher",
    "CloudProfileOptions",
    "CloudSandboxOptions",
    "DockerBackend",
    "DockerSandboxOptions",
    "EnvironmentBackend",
    "get_cloud_backend",
    "LocalBackend",
    "LocalCodeLauncher",
    "mode_to_policy",
    "PolicySpec",
    "PROTECTED_WRITE_PATTERNS",
    "register_cloud_backend",
    "registered_providers",
    "ResourceGovernor",
    "ResourceLimits",
    "SDKBackend",
    "SandboxCodeLauncher",
    "SandboxConfig",
    "SandboxEnvironment",
    "SandboxManagedProcess",
    "SandboxMode",
    "SandboxOutput",
    "SandboxPathMapper",
    "SandboxProcessManager",
    "SandboxScopeManager",
    "SDKProvider",
    "SeatbeltBackend",
    "SeatbeltSandboxOptions",
    "SecurityGuard",
    "SessionHandle",
    "SessionInfo",
    "SSHBackend",
    "SshSandboxOptions",
    "SandboxToolExecutor",
    "TencentCloudBackend",
    "TencentCloudFactory",
    "TencentCloudSandboxProvider",
]
