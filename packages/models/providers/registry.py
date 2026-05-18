"""Registry-backed model-adapter builders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, runtime_checkable

from packages.auth.runtime import AuthProfile
from packages.models.provider_runtime import ProviderRuntimeResolution, ProviderRuntimeResolver
from packages.models.runtime import CredentialSource, ModelAdapter

from .anthropic import AnthropicMessagesModelAdapter
from .openai_compatible import OpenAICompatibleProviderAdapter, OpenAICompatibleProviderConfig
from .vllm_semantic_router import VllmSemanticRouterProviderAdapter


@dataclass(frozen=True, slots=True)
class ModelAdapterBuildContext:
    profile: AuthProfile
    resolution: ProviderRuntimeResolution
    runtime_resolver: ProviderRuntimeResolver
    credential_source: CredentialSource
    credentials: Mapping[str, str]
    adapter_id: str
    stream_observer: object | None = None


@runtime_checkable
class ModelAdapterBuilder(Protocol):
    builder_id: str

    def supports(self, context: ModelAdapterBuildContext) -> bool:
        """Return whether this builder supports the context."""

    def build(self, context: ModelAdapterBuildContext) -> ModelAdapter:
        """Build an adapter for the context."""


class InMemoryModelAdapterBuilderRegistry:
    def __init__(self, builders: tuple[ModelAdapterBuilder, ...] = ()) -> None:
        self._builders: dict[str, ModelAdapterBuilder] = {}
        for builder in builders:
            self.register(builder)

    def register(self, builder: ModelAdapterBuilder) -> None:
        self._builders[str(builder.builder_id)] = builder

    def get(self, builder_id: str) -> ModelAdapterBuilder | None:
        return self._builders.get(builder_id)

    def list(self) -> tuple[ModelAdapterBuilder, ...]:
        return tuple(self._builders.values())

    def select(self, context: ModelAdapterBuildContext) -> ModelAdapterBuilder:
        configured = str(context.resolution.transport_metadata.get("adapter_builder") or "").strip()
        if configured:
            builder = self.get(configured)
            if builder is None:
                raise LookupError(f"no model-adapter builder registered for id: {configured}")
            return builder
        for builder in self._builders.values():
            if builder.supports(context):
                return builder
        raise LookupError(
            "no model-adapter builder registered for "
            f"provider={context.profile.provider_id} request_family={context.resolution.request_family}"
        )

    @classmethod
    def default(cls) -> "InMemoryModelAdapterBuilderRegistry":
        return cls(
            (
                _VllmSemanticRouterModelAdapterBuilder(),
                _OpenAICompatibleModelAdapterBuilder(),
                _AnthropicMessagesModelAdapterBuilder(),
            )
        )


class _VllmSemanticRouterModelAdapterBuilder:
    builder_id = "vllm-semantic-router"

    def supports(self, context: ModelAdapterBuildContext) -> bool:
        return context.profile.provider_id == "vllm-semantic-router"

    def build(self, context: ModelAdapterBuildContext) -> ModelAdapter:
        return VllmSemanticRouterProviderAdapter(
            router_metadata=context.profile.metadata,
            config=OpenAICompatibleProviderConfig(
                provider_id=context.profile.provider_id,
                base_url=context.profile.base_url or "",
                model_id=context.profile.default_model or "",
                extra_headers=context.profile.extra_headers,
                auth_header_name=context.resolution.auth_header_name,
            ),
            runtime_resolver=context.runtime_resolver,
            credential_source=context.credential_source,
            adapter_id=context.adapter_id,
            stream_observer=context.stream_observer,
        )


class _OpenAICompatibleModelAdapterBuilder:
    builder_id = "openai-compatible"

    def supports(self, context: ModelAdapterBuildContext) -> bool:
        return context.resolution.request_family in {"chat_completions", "responses"}

    def build(self, context: ModelAdapterBuildContext) -> ModelAdapter:
        return OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id=context.profile.provider_id,
                base_url=context.profile.base_url or "",
                model_id=context.profile.default_model or "",
                extra_headers=context.profile.extra_headers,
                auth_header_name=context.resolution.auth_header_name,
            ),
            runtime_resolver=context.runtime_resolver,
            credential_source=context.credential_source,
            adapter_id=context.adapter_id,
            stream_observer=context.stream_observer,
        )


class _AnthropicMessagesModelAdapterBuilder:
    builder_id = "anthropic-messages"

    def supports(self, context: ModelAdapterBuildContext) -> bool:
        return context.resolution.request_family == "messages"

    def build(self, context: ModelAdapterBuildContext) -> ModelAdapter:
        return AnthropicMessagesModelAdapter(
            adapter_id=context.adapter_id,
            resolution=context.resolution,
            credential_source=context.credential_source,
            extra_headers=context.profile.extra_headers,
        )


_DEFAULT_MODEL_ADAPTER_BUILDER_REGISTRY: InMemoryModelAdapterBuilderRegistry | None = None


def default_model_adapter_builder_registry() -> InMemoryModelAdapterBuilderRegistry:
    global _DEFAULT_MODEL_ADAPTER_BUILDER_REGISTRY
    if _DEFAULT_MODEL_ADAPTER_BUILDER_REGISTRY is None:
        _DEFAULT_MODEL_ADAPTER_BUILDER_REGISTRY = InMemoryModelAdapterBuilderRegistry.default()
    return _DEFAULT_MODEL_ADAPTER_BUILDER_REGISTRY


__all__ = [
    "InMemoryModelAdapterBuilderRegistry",
    "ModelAdapterBuildContext",
    "ModelAdapterBuilder",
    "default_model_adapter_builder_registry",
]
