"""Transport-aware provider catalog and runtime resolution primitives.

This module owns the shared seam between provider manifests, transport
definitions, catalog metadata, and runtime resolution. Provider-specific
network adapters can build on top of these structures without changing the
kernel or duplicating setup UX data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import MutableMapping, Mapping, Protocol, runtime_checkable

from .auth_headers import build_provider_auth_headers
from .provider_catalog import (
    default_provider_definitions,
    reasoning_efforts_for,
    resolve_transport_id,
    supports_reasoning,
)


@dataclass(frozen=True, slots=True)
class ProviderTransportDefinition:
    transport_id: str
    display_name: str
    request_family: str
    endpoint_path: str
    auth_header_name: str = "Authorization"
    supports_streaming: bool = True
    supports_embeddings: bool = False
    supports_tools: bool = True
    supports_reasoning: bool = False
    supports_custom_base_url: bool = True
    metadata: Mapping[str, str] = field(default_factory=dict)

    def as_catalog_metadata(self) -> dict[str, str]:
        return {
            "transport_id": self.transport_id,
            "transport_display_name": self.display_name,
            "request_family": self.request_family,
            "endpoint_path": self.endpoint_path,
            "auth_header_name": self.auth_header_name,
            "supports_streaming": str(self.supports_streaming).lower(),
            "supports_embeddings": str(self.supports_embeddings).lower(),
            "supports_tools": str(self.supports_tools).lower(),
            "supports_reasoning": str(self.supports_reasoning).lower(),
            "supports_custom_base_url": str(self.supports_custom_base_url).lower(),
            **dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class ProviderManifest:
    provider_id: str
    display_name: str
    transport_id: str
    catalog_summary: str
    onboarding_hint: str
    default_base_url: str | None = None
    default_model_id: str | None = None
    endpoint_path_override: str | None = None
    required_secret_keys: tuple[str, ...] = ("api_key",)
    required_config_keys: tuple[str, ...] = ()
    capability_flags: tuple[str, ...] = ()
    model_hints: tuple[str, ...] = ()
    supports_custom_base_url: bool = True
    listing_priority: int = 100
    docs_url: str | None = None
    provider_kind: str = "first_party"
    auth_method: str = "api_key"
    auth_type: str = "api_key"
    env_var_names: tuple[str, ...] = ()
    base_url_env_var: str | None = None
    extra_headers: Mapping[str, str] = field(default_factory=dict)
    runtime_enabled: bool = True
    metadata: Mapping[str, str] = field(default_factory=dict)

    def setup_fields(self) -> tuple[str, ...]:
        fields = list(self.required_config_keys)
        if self.supports_custom_base_url and "base_url" not in fields:
            fields.insert(0, "base_url")
        if self.default_model_id is not None and "model_id" not in fields:
            fields.append("model_id")
        return tuple(fields)

    def as_catalog_metadata(self) -> dict[str, str]:
        return {
            "provider_id": self.provider_id,
            "provider_display_name": self.display_name,
            "transport_id": self.transport_id,
            "catalog_summary": self.catalog_summary,
            "onboarding_hint": self.onboarding_hint,
            "default_base_url": self.default_base_url or "",
            "default_model_id": self.default_model_id or "",
            "endpoint_path_override": self.endpoint_path_override or "",
            "required_secret_keys": ",".join(self.required_secret_keys),
            "required_config_keys": ",".join(self.required_config_keys),
            "capability_flags": ",".join(self.capability_flags),
            "model_hints": ",".join(self.model_hints),
            "supports_custom_base_url": str(self.supports_custom_base_url).lower(),
            "listing_priority": str(self.listing_priority),
            **dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class ProviderCatalogRecord:
    provider_id: str
    display_name: str
    transport_id: str
    transport_display_name: str
    catalog_summary: str
    onboarding_hint: str
    default_base_url: str | None
    default_model_id: str | None
    required_secret_keys: tuple[str, ...]
    required_config_keys: tuple[str, ...]
    capability_flags: tuple[str, ...]
    model_hints: tuple[str, ...]
    supports_custom_base_url: bool
    listing_priority: int
    provider_kind: str = "first_party"
    auth_method: str = "api_key"
    auth_type: str = "api_key"
    env_var_names: tuple[str, ...] = ()
    base_url_env_var: str | None = None
    reasoning_efforts: tuple[str, ...] = ()
    docs_url: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def as_mapping(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "transport_id": self.transport_id,
            "transport_display_name": self.transport_display_name,
            "catalog_summary": self.catalog_summary,
            "onboarding_hint": self.onboarding_hint,
            "default_base_url": self.default_base_url,
            "default_model_id": self.default_model_id,
            "required_secret_keys": self.required_secret_keys,
            "required_config_keys": self.required_config_keys,
            "capability_flags": self.capability_flags,
            "model_hints": self.model_hints,
            "supports_custom_base_url": self.supports_custom_base_url,
            "listing_priority": self.listing_priority,
            "provider_kind": self.provider_kind,
            "auth_method": self.auth_method,
            "auth_type": self.auth_type,
            "env_var_names": self.env_var_names,
            "base_url_env_var": self.base_url_env_var,
            "reasoning_efforts": self.reasoning_efforts,
            "docs_url": self.docs_url,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class ProviderSetupGuide:
    provider_id: str
    display_name: str
    transport_id: str
    transport_display_name: str
    required_secret_keys: tuple[str, ...]
    required_config_keys: tuple[str, ...]
    provider_kind: str
    auth_method: str
    auth_type: str
    quickstart_steps: tuple[str, ...]
    verification_steps: tuple[str, ...]
    suggested_base_url: str | None
    suggested_model_id: str | None
    onboarding_hint: str
    env_var_names: tuple[str, ...] = ()
    base_url_env_var: str | None = None
    reasoning_efforts: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def as_mapping(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "transport_id": self.transport_id,
            "transport_display_name": self.transport_display_name,
            "required_secret_keys": self.required_secret_keys,
            "required_config_keys": self.required_config_keys,
            "provider_kind": self.provider_kind,
            "auth_method": self.auth_method,
            "auth_type": self.auth_type,
            "quickstart_steps": self.quickstart_steps,
            "verification_steps": self.verification_steps,
            "suggested_base_url": self.suggested_base_url,
            "suggested_model_id": self.suggested_model_id,
            "env_var_names": self.env_var_names,
            "base_url_env_var": self.base_url_env_var,
            "reasoning_efforts": self.reasoning_efforts,
            "onboarding_hint": self.onboarding_hint,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class ProviderRuntimeResolution:
    provider_id: str
    display_name: str
    transport_id: str
    transport_display_name: str
    request_family: str
    model_id: str
    base_url: str | None
    endpoint_path: str
    auth_header_name: str
    supports_streaming: bool
    supports_embeddings: bool
    supports_tools: bool
    supports_reasoning: bool
    capability_flags: tuple[str, ...]
    reasoning_efforts: tuple[str, ...] = ()
    provider_metadata: Mapping[str, str] = field(default_factory=dict)
    transport_metadata: Mapping[str, str] = field(default_factory=dict)

    def as_mapping(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "transport_id": self.transport_id,
            "transport_display_name": self.transport_display_name,
            "request_family": self.request_family,
            "model_id": self.model_id,
            "base_url": self.base_url,
            "endpoint_path": self.endpoint_path,
            "auth_header_name": self.auth_header_name,
            "supports_streaming": self.supports_streaming,
            "supports_embeddings": self.supports_embeddings,
            "supports_tools": self.supports_tools,
            "supports_reasoning": self.supports_reasoning,
            "reasoning_efforts": self.reasoning_efforts,
            "capability_flags": self.capability_flags,
            "provider_metadata": dict(self.provider_metadata),
            "transport_metadata": dict(self.transport_metadata),
        }


SESSION_ID_HEADER = "x-session-id"


def attach_session_header(headers: MutableMapping[str, str], session_id: str) -> MutableMapping[str, str]:
    normalized = session_id.strip()
    if not normalized:
        return headers
    if any(key.lower() == SESSION_ID_HEADER for key in headers):
        return headers
    headers[SESSION_ID_HEADER] = normalized
    return headers


def provider_auth_headers(
    *,
    provider_id: str,
    request_family: str,
    api_key: str | None,
    anthropic_version: str = "2023-06-01",
    metadata: Mapping[str, str] | None = None,
) -> dict[str, str]:
    return build_provider_auth_headers(
        provider_id=provider_id,
        request_family=request_family,
        api_key=api_key,
        anthropic_version=anthropic_version,
        metadata=metadata,
    )


@runtime_checkable
class ProviderTransportRegistry(Protocol):
    def register(self, transport: ProviderTransportDefinition) -> None:
        """Register a transport definition."""

    def get(self, transport_id: str) -> ProviderTransportDefinition | None:
        """Return a transport definition by id."""

    def list(self) -> tuple[ProviderTransportDefinition, ...]:
        """Return all registered transport definitions."""


@runtime_checkable
class ProviderManifestRegistry(Protocol):
    def register(self, manifest: ProviderManifest) -> None:
        """Register a provider manifest."""

    def get(self, provider_id: str) -> ProviderManifest | None:
        """Return a provider manifest by id."""

    def list(self) -> tuple[ProviderManifest, ...]:
        """Return all registered provider manifests."""


class InMemoryProviderTransportRegistry:
    def __init__(self, transports: tuple[ProviderTransportDefinition, ...] = ()) -> None:
        self._transports: dict[str, ProviderTransportDefinition] = {}
        for transport in transports:
            self.register(transport)

    def register(self, transport: ProviderTransportDefinition) -> None:
        self._transports[transport.transport_id] = transport

    def get(self, transport_id: str) -> ProviderTransportDefinition | None:
        return self._transports.get(transport_id)

    def list(self) -> tuple[ProviderTransportDefinition, ...]:
        return tuple(self._transports.values())

    @classmethod
    def default(cls) -> "InMemoryProviderTransportRegistry":
        return cls(
            (
                ProviderTransportDefinition(
                    transport_id="openai_chat_compatible",
                    display_name="OpenAI Chat-Compatible",
                    request_family="chat_completions",
                    endpoint_path="/v1/chat/completions",
                    supports_streaming=True,
                    supports_embeddings=True,
                    supports_tools=True,
                    supports_reasoning=False,
                    supports_custom_base_url=True,
                    metadata={
                        "setup_style": "custom_endpoint",
                        "request_shape": "chat-completions",
                        "execution_surface": "streaming_chat_completions",
                    },
                ),
                ProviderTransportDefinition(
                    transport_id="openai_responses",
                    display_name="OpenAI Responses",
                    request_family="responses",
                    endpoint_path="/v1/responses",
                    supports_streaming=True,
                    supports_embeddings=False,
                    supports_tools=True,
                    supports_reasoning=False,
                    supports_custom_base_url=False,
                    metadata={
                        "setup_style": "first_party",
                        "request_shape": "responses",
                        "execution_surface": "streaming_text_responses",
                    },
                ),
                ProviderTransportDefinition(
                    transport_id="anthropic_messages",
                    display_name="Anthropic Messages",
                    request_family="messages",
                    endpoint_path="/v1/messages",
                    supports_streaming=False,
                    supports_embeddings=False,
                    supports_tools=True,
                    supports_reasoning=False,
                    supports_custom_base_url=False,
                    metadata={
                        "setup_style": "first_party",
                        "request_shape": "messages",
                        "execution_surface": "non_streaming_text_messages",
                    },
                ),
            )
        )


class InMemoryProviderManifestRegistry:
    def __init__(self, manifests: tuple[ProviderManifest, ...] = ()) -> None:
        self._manifests: dict[str, ProviderManifest] = {}
        for manifest in manifests:
            self.register(manifest)

    def register(self, manifest: ProviderManifest) -> None:
        self._manifests[manifest.provider_id] = manifest

    def get(self, provider_id: str) -> ProviderManifest | None:
        return self._manifests.get(provider_id)

    def list(self) -> tuple[ProviderManifest, ...]:
        return tuple(
            sorted(
                self._manifests.values(),
                key=lambda manifest: (manifest.listing_priority, manifest.provider_id),
            )
        )

    @classmethod
    def default(cls) -> "InMemoryProviderManifestRegistry":
        return cls(tuple(_manifest_from_definition(definition) for definition in default_provider_definitions()))


class ProviderRuntimeResolver:
    def __init__(
        self,
        *,
        transport_registry: ProviderTransportRegistry | None = None,
        manifest_registry: ProviderManifestRegistry | None = None,
    ) -> None:
        self.transport_registry = transport_registry or InMemoryProviderTransportRegistry.default()
        self.manifest_registry = manifest_registry or InMemoryProviderManifestRegistry.default()

    @classmethod
    def default(cls) -> "ProviderRuntimeResolver":
        return cls()

    def list_catalog(self) -> tuple[ProviderCatalogRecord, ...]:
        records: list[ProviderCatalogRecord] = []
        for manifest in self.manifest_registry.list():
            records.append(self._catalog_record(manifest))
        return tuple(records)

    def build_setup_guide(self, provider_id: str) -> ProviderSetupGuide:
        manifest = self._manifest_for(provider_id)
        suggested_model_id = manifest.default_model_id
        transport_id = resolve_transport_id(
            provider_id=manifest.provider_id,
            default_transport_id=manifest.transport_id,
            model_id=suggested_model_id,
        )
        transport = self._transport_for_transport_id(transport_id)
        steps = [f"Create or select an auth profile for {manifest.display_name}."]
        if manifest.required_secret_keys:
            if manifest.auth_type == "oauth_external":
                steps.append(
                    "Reuse a local OAuth session if Elephant Agent can discover one, or store an override token in the encrypted local vault."
                )
            elif manifest.auth_type == "oauth_device_code":
                steps.append(
                    "Authenticate through the provider's device-code flow or attach a reusable agent key in the encrypted local vault."
                )
            elif manifest.auth_type == "external_process":
                steps.append(
                    "Install and authenticate the provider-side local helper so Elephant Agent can reuse that runtime process."
                )
            else:
                steps.append(
                    "Store the required provider secret(s) in Elephant Agent' encrypted local vault: "
                    f"{', '.join(manifest.required_secret_keys)}."
                )
        elif manifest.provider_kind == "local":
            steps.append("Confirm the local endpoint is running before the first health check.")
        if transport.supports_custom_base_url:
            steps.append("Set the endpoint base URL for your compatible API.")
        if suggested_model_id is not None:
            steps.append(f"Choose or override the default model id ({suggested_model_id}).")
        steps.append("Run a provider test or health flow before first use.")
        effective_reasoning_efforts = reasoning_efforts_for(
            provider_id=manifest.provider_id,
            model_id=suggested_model_id,
        )
        resolved_endpoint_path = manifest.endpoint_path_override or transport.endpoint_path
        return ProviderSetupGuide(
            provider_id=manifest.provider_id,
            display_name=manifest.display_name,
            transport_id=transport.transport_id,
            transport_display_name=transport.display_name,
            required_secret_keys=manifest.required_secret_keys,
            required_config_keys=manifest.setup_fields(),
            provider_kind=manifest.provider_kind,
            auth_method=manifest.auth_method,
            auth_type=manifest.auth_type,
            quickstart_steps=tuple(steps),
            verification_steps=(
                "Check the provider listing entry.",
                "Run a connectivity test or health command.",
                "Set the provider as default if the check succeeds.",
            ),
            suggested_base_url=manifest.default_base_url,
            suggested_model_id=suggested_model_id,
            env_var_names=manifest.env_var_names,
            base_url_env_var=manifest.base_url_env_var,
            reasoning_efforts=effective_reasoning_efforts,
            onboarding_hint=manifest.onboarding_hint,
            metadata=self._runtime_truth_metadata(
                manifest,
                transport,
                model_id=suggested_model_id,
                reasoning_efforts=effective_reasoning_efforts,
                endpoint_path=resolved_endpoint_path,
            ),
        )

    def resolve(
        self,
        provider_id: str,
        *,
        model_id: str | None = None,
        base_url: str | None = None,
    ) -> ProviderRuntimeResolution:
        manifest = self._manifest_for(provider_id)
        resolved_model_id = model_id or manifest.default_model_id
        if resolved_model_id is None:
            raise ValueError(f"provider manifest is missing a default model id: {provider_id}")
        resolved_transport_id = resolve_transport_id(
            provider_id=manifest.provider_id,
            default_transport_id=manifest.transport_id,
            model_id=resolved_model_id,
        )
        transport = self._transport_for_transport_id(resolved_transport_id)
        resolved_base_url = base_url if base_url is not None else manifest.default_base_url
        resolved_endpoint_path = manifest.endpoint_path_override or transport.endpoint_path
        effective_reasoning_efforts = reasoning_efforts_for(
            provider_id=manifest.provider_id,
            model_id=resolved_model_id,
        )
        return ProviderRuntimeResolution(
            provider_id=manifest.provider_id,
            display_name=manifest.display_name,
            transport_id=transport.transport_id,
            transport_display_name=transport.display_name,
            request_family=transport.request_family,
            model_id=resolved_model_id,
            base_url=resolved_base_url,
            endpoint_path=resolved_endpoint_path,
            auth_header_name=transport.auth_header_name,
            supports_streaming=transport.supports_streaming,
            supports_embeddings=transport.supports_embeddings,
            supports_tools=transport.supports_tools,
            supports_reasoning=supports_reasoning(
                provider_id=manifest.provider_id,
                model_id=resolved_model_id,
            ),
            reasoning_efforts=effective_reasoning_efforts,
            capability_flags=manifest.capability_flags,
            provider_metadata=self._runtime_truth_metadata(
                manifest,
                transport,
                model_id=resolved_model_id,
                reasoning_efforts=effective_reasoning_efforts,
                endpoint_path=resolved_endpoint_path,
            ),
            transport_metadata=self._runtime_truth_metadata(
                manifest,
                transport,
                model_id=resolved_model_id,
                reasoning_efforts=effective_reasoning_efforts,
                endpoint_path=resolved_endpoint_path,
            ),
        )

    def _manifest_for(self, provider_id: str) -> ProviderManifest:
        manifest = self.manifest_registry.get(provider_id)
        if manifest is None:
            raise LookupError(f"no provider manifest registered for provider: {provider_id}")
        return manifest

    def _transport_for_manifest(self, manifest: ProviderManifest) -> ProviderTransportDefinition:
        transport = self.transport_registry.get(manifest.transport_id)
        if transport is None:
            raise LookupError(f"no transport registered for manifest transport id: {manifest.transport_id}")
        return transport

    def _transport_for_transport_id(self, transport_id: str) -> ProviderTransportDefinition:
        transport = self.transport_registry.get(transport_id)
        if transport is None:
            raise LookupError(f"no transport registered for transport id: {transport_id}")
        return transport

    def _catalog_record(
        self,
        manifest: ProviderManifest,
    ) -> ProviderCatalogRecord:
        transport_id = resolve_transport_id(
            provider_id=manifest.provider_id,
            default_transport_id=manifest.transport_id,
            model_id=manifest.default_model_id,
        )
        transport = self._transport_for_transport_id(transport_id)
        effective_reasoning_efforts = reasoning_efforts_for(
            provider_id=manifest.provider_id,
            model_id=manifest.default_model_id,
        )
        resolved_endpoint_path = manifest.endpoint_path_override or transport.endpoint_path
        return ProviderCatalogRecord(
            provider_id=manifest.provider_id,
            display_name=manifest.display_name,
            transport_id=transport.transport_id,
            transport_display_name=transport.display_name,
            catalog_summary=manifest.catalog_summary,
            onboarding_hint=manifest.onboarding_hint,
            default_base_url=manifest.default_base_url,
            default_model_id=manifest.default_model_id,
            required_secret_keys=manifest.required_secret_keys,
            required_config_keys=manifest.setup_fields(),
            capability_flags=manifest.capability_flags,
            model_hints=manifest.model_hints,
            supports_custom_base_url=transport.supports_custom_base_url,
            listing_priority=manifest.listing_priority,
            provider_kind=manifest.provider_kind,
            auth_method=manifest.auth_method,
            auth_type=manifest.auth_type,
            env_var_names=manifest.env_var_names,
            base_url_env_var=manifest.base_url_env_var,
            reasoning_efforts=effective_reasoning_efforts,
            docs_url=manifest.docs_url,
            metadata=self._runtime_truth_metadata(
                manifest,
                transport,
                model_id=manifest.default_model_id,
                reasoning_efforts=effective_reasoning_efforts,
                endpoint_path=resolved_endpoint_path,
            ),
        )

    def _runtime_truth_metadata(
        self,
        manifest: ProviderManifest,
        transport: ProviderTransportDefinition,
        *,
        model_id: str | None,
        reasoning_efforts: tuple[str, ...],
        endpoint_path: str | None = None,
    ) -> dict[str, str]:
        return {
            **dict(manifest.metadata),
            **dict(transport.metadata),
            "auth_method": manifest.auth_method,
            "auth_type": manifest.auth_type,
            "provider_kind": manifest.provider_kind,
            "env_var_names": ",".join(manifest.env_var_names),
            "base_url_env_var": manifest.base_url_env_var or "",
            "runtime_enabled": str(manifest.runtime_enabled).lower(),
            "resolved_model_id": str(model_id or ""),
            "endpoint_path": str(endpoint_path or transport.endpoint_path),
            "reasoning_efforts": ",".join(reasoning_efforts),
            "supports_reasoning": str(bool(reasoning_efforts)).lower(),
            "capability_truth_source": "runtime_execution",
        }


def _manifest_from_definition(definition) -> ProviderManifest:
    return ProviderManifest(
        provider_id=definition.provider_id,
        display_name=definition.display_name,
        transport_id=definition.transport_id,
        catalog_summary=definition.catalog_summary,
        onboarding_hint=definition.onboarding_hint,
        default_base_url=definition.default_base_url,
        default_model_id=definition.default_model_id,
        endpoint_path_override=definition.endpoint_path_override,
        required_secret_keys=definition.required_secret_keys,
        required_config_keys=definition.required_config_keys,
        capability_flags=definition.capability_flags,
        model_hints=definition.model_hints,
        supports_custom_base_url=definition.supports_custom_base_url,
        listing_priority=definition.listing_priority,
        docs_url=definition.docs_url,
        provider_kind=definition.provider_kind,
        auth_method=definition.auth_method,
        auth_type=definition.auth_type,
        env_var_names=definition.env_var_names,
        base_url_env_var=definition.base_url_env_var,
        extra_headers=definition.extra_headers,
        runtime_enabled=definition.runtime_enabled,
        metadata=definition.metadata,
    )
