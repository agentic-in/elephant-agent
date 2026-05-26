"""Cloud backend registry — maps provider names to backend factories.

Usage::

    from packages.sandbox.backends.cloud_registry import (
        get_cloud_backend,
        register_cloud_backend,
    )

    # Built-in providers are auto-registered at import time.
    backend = get_cloud_backend(config)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from packages.sandbox.config import CloudProfileOptions, SandboxConfig
    from packages.sandbox.types import EnvironmentBackend


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class CloudBackendFactory(Protocol):
    """Creates an ``EnvironmentBackend`` for a specific cloud provider."""

    def create(
        self,
        config: SandboxConfig,
        profile: CloudProfileOptions,
    ) -> EnvironmentBackend: ...


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_CLOUD_BACKENDS: dict[str, CloudBackendFactory] = {}


def register_cloud_backend(provider: str, factory: CloudBackendFactory) -> None:
    """Register a cloud backend factory under *provider* name."""
    _CLOUD_BACKENDS[provider] = factory


def get_cloud_backend(config: SandboxConfig) -> EnvironmentBackend:
    """Instantiate the cloud backend determined by the active profile.

    Uses ``config.effective_cloud()`` to resolve which profile is active,
    then dispatches to the registered factory for ``profile.provider``.
    """
    profile = config.effective_cloud()
    factory = _CLOUD_BACKENDS.get(profile.provider)
    if factory is None:
        available = ", ".join(sorted(_CLOUD_BACKENDS)) or "(none)"
        raise ValueError(
            f"Unknown cloud provider: {profile.provider!r}. "
            f"Available: {available}"
        )
    return factory.create(config, profile)


def registered_providers() -> tuple[str, ...]:
    """Return the names of all registered cloud providers."""
    return tuple(sorted(_CLOUD_BACKENDS))


# ---------------------------------------------------------------------------
# Built-in provider registration
# ---------------------------------------------------------------------------

def _register_builtins() -> None:
    from packages.sandbox.backends.tencent_cloud import TencentCloudFactory
    register_cloud_backend("tencent", TencentCloudFactory())


_register_builtins()
