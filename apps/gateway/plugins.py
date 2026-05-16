"""Pluggable adapter and service registry for gateway messaging surfaces."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


AdapterFactory = Callable[[Any], object]
ServiceFactory = Callable[..., object]


@dataclass(frozen=True, slots=True)
class GatewayServicePluginRegistration:
    key: str
    factory: ServiceFactory
    enabled_by_default: bool = False


@runtime_checkable
class GatewayPlatformPlugin(Protocol):
    key: str

    def adapter_descriptor(self) -> "GatewayAdapterDescriptor":
        """Return the adapter descriptor for this platform."""

    def build_adapter(self, app: Any) -> object:
        """Build the messaging adapter for this platform."""

    def service_registrations(self) -> tuple[GatewayServicePluginRegistration, ...]:
        """Return managed service registrations owned by this platform."""


@dataclass(frozen=True, slots=True)
class GatewayAdapterDescriptor:
    key: str
    adapter_id: str
    surface: str
    default_account_id: str
    operator_action: str
    identity_mapping: str | None = None
    preferred_transport: str | None = None
    implemented_transports: tuple[str, ...] = ()
    supported_updates: tuple[str, ...] = ()
    supported_events: tuple[str, ...] = ()
    delivery_defaults: Mapping[str, str] = field(default_factory=dict)
    delivery_api: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def summary_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "adapter_id": self.adapter_id,
            "surface": self.surface,
            "default_account_id": self.default_account_id,
            "operator_action": self.operator_action,
        }
        if self.identity_mapping is not None:
            payload["identity_mapping"] = self.identity_mapping
        if self.preferred_transport is not None:
            payload["preferred_transport"] = self.preferred_transport
        if self.implemented_transports:
            payload["implemented_transports"] = self.implemented_transports
        if self.supported_updates:
            payload["supported_updates"] = self.supported_updates
        if self.supported_events:
            payload["supported_events"] = self.supported_events
        if self.delivery_defaults:
            payload["delivery_defaults"] = dict(self.delivery_defaults)
        if self.delivery_api is not None:
            payload["delivery_api"] = self.delivery_api
        payload.update(dict(self.metadata))
        return payload


@dataclass(frozen=True, slots=True)
class _GatewayAdapterRegistration:
    descriptor: GatewayAdapterDescriptor
    factory: AdapterFactory


@dataclass(frozen=True, slots=True)
class _GatewayServiceRegistration:
    key: str
    factory: ServiceFactory
    enabled_by_default: bool = False


@runtime_checkable
class GatewayHttpService(Protocol):
    service_key: str
    app: Any

    @property
    def http_paths(self) -> tuple[str, ...]:
        """Return the HTTP paths owned by this service."""

    def describe(self) -> Mapping[str, object]:
        """Return setup and health information for this service."""

    def handle_http_event(
        self,
        payload: Mapping[str, object],
        *,
        path: str,
    ) -> tuple[str, Mapping[str, object]]:
        """Handle one JSON HTTP event and return an HTTP status plus payload."""


@dataclass(frozen=True, slots=True)
class GatewayManagedRuntime:
    service_key: str
    runtime_id: str
    target: str
    label: str
    pid_path: Path
    log_path: Path
    record_path: Path


@runtime_checkable
class GatewayManagedService(Protocol):
    service_key: str
    app: Any

    def describe(self) -> Mapping[str, object]:
        """Return setup and health information for this service."""

    def configured_runtime_target(self) -> str:
        """Resolve the active runtime target from configuration."""

    def managed_runtime(
        self,
        *,
        args: Any,
        target: str,
    ) -> GatewayManagedRuntime:
        """Describe one detached runtime target for this service."""

    def build_detached_runtime_command(
        self,
        *,
        args: Any,
        target: str,
    ) -> tuple[str, ...]:
        """Build the detached launcher command for one runtime target."""

    def prepare_managed_runtime(self, *, action: str, target: str) -> None:
        """Perform preflight checks before a managed runtime action."""

    def managed_runtime_log_hint(self, *, target: str) -> str:
        """Return a command hint that helps operators inspect runtime logs."""


@dataclass(slots=True)
class GatewayPluginRegistry:
    _adapters: dict[str, _GatewayAdapterRegistration] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _services: dict[str, _GatewayServiceRegistration] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _platforms: dict[str, GatewayPlatformPlugin] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def register_adapter(
        self,
        descriptor: GatewayAdapterDescriptor,
        *,
        factory: AdapterFactory,
    ) -> None:
        self._adapters[descriptor.key] = _GatewayAdapterRegistration(
            descriptor=descriptor,
            factory=factory,
        )

    def register_service(
        self,
        key: str,
        *,
        factory: ServiceFactory,
        enabled_by_default: bool = False,
    ) -> None:
        self._services[key] = _GatewayServiceRegistration(
            key=key,
            factory=factory,
            enabled_by_default=enabled_by_default,
        )

    def register_platform(self, platform: GatewayPlatformPlugin) -> None:
        descriptor = platform.adapter_descriptor()
        self._platforms[platform.key] = platform
        self.register_adapter(descriptor, factory=platform.build_adapter)
        for service in platform.service_registrations():
            self.register_service(
                service.key,
                factory=service.factory,
                enabled_by_default=service.enabled_by_default,
            )

    def adapter_keys(self) -> tuple[str, ...]:
        return tuple(self._adapters.keys())

    def service_keys(self) -> tuple[str, ...]:
        return tuple(self._services.keys())

    def platform_keys(self) -> tuple[str, ...]:
        return tuple(self._platforms.keys())

    def adapter_descriptor(self, key: str) -> GatewayAdapterDescriptor:
        try:
            return self._adapters[key].descriptor
        except KeyError as exc:
            raise LookupError(f"unknown gateway adapter plugin: {key}") from exc

    def create_adapter(self, key: str, app: Any) -> object:
        try:
            registration = self._adapters[key]
        except KeyError as exc:
            raise LookupError(f"unknown gateway adapter plugin: {key}") from exc
        return registration.factory(app)

    def create_service(self, key: str, *, app: Any, **kwargs: object) -> object:
        try:
            registration = self._services[key]
        except KeyError as exc:
            raise LookupError(f"unknown gateway service plugin: {key}") from exc
        return registration.factory(app=app, **kwargs)

    def adapter_id_map(self) -> dict[str, str]:
        return {
            key: registration.descriptor.adapter_id
            for key, registration in self._adapters.items()
        }

    def adapter_setup_payload(self) -> dict[str, dict[str, object]]:
        return {
            key: registration.descriptor.summary_payload()
            for key, registration in self._adapters.items()
        }

    def configured_service_keys(
        self,
        manifest: Mapping[str, object] | None = None,
    ) -> tuple[str, ...]:
        if not self._services:
            return ()
        if manifest is None:
            return self.service_keys()
        gateway_payload = _mapping(manifest.get("gateway")) or {}
        adapters_payload = _mapping(gateway_payload.get("adapters")) or {}
        resolved: list[str] = []
        for key in self._services:
            adapter_payload = _mapping(adapters_payload.get(key))
            if adapter_payload is not None and adapter_payload.get("enabled") is False:
                continue
            resolved.append(key)
        return tuple(resolved)


def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def default_gateway_runtime_path(
    state_dir: Path,
    *,
    service_key: str,
    target: str,
    suffix: str,
) -> Path:
    normalized_target = str(target).strip().lower().replace("_", "-") or "configured"
    return state_dir / f"{service_key}-{normalized_target}.{suffix}"


@runtime_checkable
class DaemonService(Protocol):
    """Protocol for services that can run as async tasks inside the unified daemon."""

    service_key: str
    app: Any

    def has_credentials(self) -> bool:
        """Return True if at least one account can be resolved with current environment.

        This is a preflight check: it should NOT start any task or allocate resources.
        Return False if no accounts have sufficient credentials to start.
        """

    async def start_daemon_task(self, *, loop: Any) -> Any | None:
        """Start this service as an asyncio Task inside the daemon event loop.

        Returns the created Task, or None if the service has no long-running task
        (e.g. webhook-only services that are handled by the HTTP server).
        """

    async def stop_daemon_task(self) -> None:
        """Gracefully stop this service's daemon task."""


__all__ = [
    "AdapterFactory",
    "DaemonService",
    "GatewayAdapterDescriptor",
    "GatewayHttpService",
    "GatewayManagedRuntime",
    "GatewayManagedService",
    "GatewayPlatformPlugin",
    "GatewayPluginRegistry",
    "GatewayServicePluginRegistration",
    "ServiceFactory",
    "default_gateway_runtime_path",
]
