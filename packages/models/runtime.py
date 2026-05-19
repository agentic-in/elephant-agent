"""Provider-neutral model adapter contracts and preview baselines."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Mapping, Protocol, runtime_checkable

from packages.capabilities.runtime import CapabilityDescriptor
from packages.contracts import Episode
from packages.contracts.runtime import (
    ContextBundle,
    ExecutionResult,
    ExecutionToolCall,
    RuntimeModelChoice,
    PromptMessage,
    PersonalModelRuntimeState,
    GenerationModelProfile,
    SupportModelProfile,
)


@dataclass(frozen=True, slots=True)
class ModelAdapterDescriptor:
    adapter_id: str
    provider_id: str
    model_id: str
    kind: str = "chat"
    supported_tasks: tuple[str, ...] = ("generate", "summarize", "embed")
    fallback_model_ids: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModelRequest:
    request_id: str
    profile_id: str
    session_id: str
    provider_id: str
    model_id: str
    prompt: str
    context: Mapping[str, str] = field(default_factory=dict)
    task: str = "generate"
    reasoning_effort: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)
    tools: tuple[Mapping[str, object], ...] = ()
    messages: tuple[PromptMessage, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_prompt_tokens: int = 0
    cache_creation_prompt_tokens: int = 0
    cache_usage_reported: bool = False


@dataclass(frozen=True, slots=True)
class ModelTextResult:
    result_id: str
    request_id: str
    adapter_id: str
    provider_id: str
    model_id: str
    task: str
    content: str
    reasoning: str = ""
    usage: ModelUsage = field(default_factory=ModelUsage)
    failure_kind: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)
    tool_calls: tuple[ExecutionToolCall, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelEmbeddingResult:
    result_id: str
    request_id: str
    adapter_id: str
    provider_id: str
    model_id: str
    task: str
    embeddings: tuple[tuple[float, ...], ...]
    failure_kind: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)


@runtime_checkable
class CredentialSource(Protocol):
    def resolve(self, provider_id: str) -> Mapping[str, str]:
        """Return resolved credentials for a provider."""


@runtime_checkable
class ModelAdapter(Protocol):
    descriptor: ModelAdapterDescriptor

    def generate(self, request: ModelRequest, credentials: Mapping[str, str]) -> ModelTextResult:
        """Generate model text for the request."""

    def summarize(self, request: ModelRequest, credentials: Mapping[str, str]) -> ModelTextResult:
        """Return a text summary for the request."""

    def embed(self, request: ModelRequest, credentials: Mapping[str, str]) -> ModelEmbeddingResult:
        """Return embeddings for the request payload."""


@runtime_checkable
class ModelAdapterRegistry(Protocol):
    def register(self, adapter: ModelAdapter) -> None:
        """Register an adapter."""

    def get(self, adapter_id: str) -> ModelAdapter | None:
        """Return an adapter by id."""

    def select(self, provider_id: str, model_id: str | None = None) -> ModelAdapter:
        """Return the best matching adapter for a provider/model pair."""

    def list(self) -> tuple[ModelAdapter, ...]:
        """Return all registered adapters."""


class InMemoryModelAdapterRegistry:
    def __init__(self, adapters: tuple[ModelAdapter, ...] = ()) -> None:
        self._adapters: dict[str, ModelAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: ModelAdapter) -> None:
        self._adapters[adapter.descriptor.adapter_id] = adapter

    def get(self, adapter_id: str) -> ModelAdapter | None:
        return self._adapters.get(adapter_id)

    def select(self, provider_id: str, model_id: str | None = None) -> ModelAdapter:
        for adapter in self._adapters.values():
            descriptor = adapter.descriptor
            if descriptor.provider_id != provider_id:
                continue
            if model_id is None or descriptor.model_id == model_id:
                return adapter
            if model_id in descriptor.fallback_model_ids:
                return adapter
        for adapter in self._adapters.values():
            if adapter.descriptor.provider_id == provider_id:
                return adapter
        raise LookupError(f"no model adapter registered for provider: {provider_id}")

    def list(self) -> tuple[ModelAdapter, ...]:
        return tuple(self._adapters.values())


class PromptEchoModelAdapter:
    """Baseline adapter that makes preview runtime behavior inspectable."""

    def __init__(self, *, adapter_id: str, provider_id: str, model_id: str) -> None:
        self.descriptor = ModelAdapterDescriptor(
            adapter_id=adapter_id,
            provider_id=provider_id,
            model_id=model_id,
            kind="chat",
            supported_tasks=("generate", "summarize", "embed"),
        )

    def _summarize_credential_keys(self, credentials: Mapping[str, str]) -> str:
        if not credentials:
            return "no-credentials"
        return ",".join(sorted(credentials))

    def generate(self, request: ModelRequest, credentials: Mapping[str, str]) -> ModelTextResult:
        context_bits = ", ".join(f"{key}={value}" for key, value in sorted(request.context.items()))
        credential_keys = self._summarize_credential_keys(credentials)
        content = (
            f"[{self.descriptor.provider_id}/{self.descriptor.model_id}] "
            f"{request.prompt}"
            + (f" | context: {context_bits}" if context_bits else "")
            + f" | creds: {credential_keys}"
        )
        usage = ModelUsage(
            prompt_tokens=len(request.prompt.split()),
            completion_tokens=len(content.split()),
            total_tokens=len(request.prompt.split()) + len(content.split()),
        )
        return ModelTextResult(
            result_id=f"{request.request_id}:generate",
            request_id=request.request_id,
            adapter_id=self.descriptor.adapter_id,
            provider_id=self.descriptor.provider_id,
            model_id=self.descriptor.model_id,
            task="generate",
            content=content,
            usage=usage,
            metadata={"credential_keys": credential_keys},
        )

    def summarize(self, request: ModelRequest, credentials: Mapping[str, str]) -> ModelTextResult:
        credential_keys = self._summarize_credential_keys(credentials)
        content = f"summary({self.descriptor.model_id}): {request.prompt[:96]}"
        usage = ModelUsage(
            prompt_tokens=len(request.prompt.split()),
            completion_tokens=len(content.split()),
            total_tokens=len(request.prompt.split()) + len(content.split()),
        )
        return ModelTextResult(
            result_id=f"{request.request_id}:summarize",
            request_id=request.request_id,
            adapter_id=self.descriptor.adapter_id,
            provider_id=self.descriptor.provider_id,
            model_id=self.descriptor.model_id,
            task="summarize",
            content=content,
            usage=usage,
            metadata={"credential_keys": credential_keys},
        )

    def embed(self, request: ModelRequest, credentials: Mapping[str, str]) -> ModelEmbeddingResult:
        content = request.prompt if request.prompt else request.context.get("text", "")
        credential_keys = self._summarize_credential_keys(credentials)
        embeddings = (self._stable_embedding(content),)
        return ModelEmbeddingResult(
            result_id=f"{request.request_id}:embed",
            request_id=request.request_id,
            adapter_id=self.descriptor.adapter_id,
            provider_id=self.descriptor.provider_id,
            model_id=self.descriptor.model_id,
            task="embed",
            embeddings=embeddings,
            metadata={"credential_keys": credential_keys},
        )

    def _stable_embedding(self, text: str) -> tuple[float, ...]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        vector = []
        for offset in range(0, 16, 4):
            chunk = digest[offset : offset + 4]
            value = int.from_bytes(chunk, "big") / 0xFFFFFFFF
            vector.append(round(value, 6))
        return tuple(vector)


class StaticTextModelAdapter:
    """Baseline adapter that returns a fixed or templated response."""

    def __init__(
        self,
        *,
        adapter_id: str,
        provider_id: str,
        model_id: str,
        response_template: str,
    ) -> None:
        self.response_template = response_template
        self.descriptor = ModelAdapterDescriptor(
            adapter_id=adapter_id,
            provider_id=provider_id,
            model_id=model_id,
            kind="chat",
            supported_tasks=("generate", "summarize", "embed"),
        )

    def _render(self, request: ModelRequest, credentials: Mapping[str, str]) -> str:
        return self.response_template.format(
            prompt=request.prompt,
            provider_id=self.descriptor.provider_id,
            model_id=self.descriptor.model_id,
            session_id=request.session_id,
            profile_id=request.profile_id,
            credential_keys=",".join(sorted(credentials)) or "no-credentials",
        )

    def generate(self, request: ModelRequest, credentials: Mapping[str, str]) -> ModelTextResult:
        content = self._render(request, credentials)
        return ModelTextResult(
            result_id=f"{request.request_id}:generate",
            request_id=request.request_id,
            adapter_id=self.descriptor.adapter_id,
            provider_id=self.descriptor.provider_id,
            model_id=self.descriptor.model_id,
            task="generate",
            content=content,
            usage=ModelUsage(
                prompt_tokens=len(request.prompt.split()),
                completion_tokens=len(content.split()),
                total_tokens=len(request.prompt.split()) + len(content.split()),
            ),
        )

    def summarize(self, request: ModelRequest, credentials: Mapping[str, str]) -> ModelTextResult:
        content = f"summary[{self.descriptor.model_id}]: {self._render(request, credentials)}"
        return ModelTextResult(
            result_id=f"{request.request_id}:summarize",
            request_id=request.request_id,
            adapter_id=self.descriptor.adapter_id,
            provider_id=self.descriptor.provider_id,
            model_id=self.descriptor.model_id,
            task="summarize",
            content=content,
            usage=ModelUsage(
                prompt_tokens=len(request.prompt.split()),
                completion_tokens=len(content.split()),
                total_tokens=len(request.prompt.split()) + len(content.split()),
            ),
        )

    def embed(self, request: ModelRequest, credentials: Mapping[str, str]) -> ModelEmbeddingResult:
        text = self._render(request, credentials)
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        embeddings = (
            tuple(round(int.from_bytes(digest[index : index + 4], "big") / 0xFFFFFFFF, 6) for index in range(0, 16, 4)),
        )
        return ModelEmbeddingResult(
            result_id=f"{request.request_id}:embed",
            request_id=request.request_id,
            adapter_id=self.descriptor.adapter_id,
            provider_id=self.descriptor.provider_id,
            model_id=self.descriptor.model_id,
            task="embed",
            embeddings=embeddings,
        )


class PreviewModelProviderCapability:
    """Bridge a provider-neutral adapter into the kernel capability contract."""

    def __init__(
        self,
        *,
        adapter: ModelAdapter,
        weak_adapter: ModelAdapter | None = None,
        provider_id: str | None = None,
        credential_source: CredentialSource | None = None,
        capability_id: str = "model.preview",
        state_focus_mode: str = "skip",
    ) -> None:
        self.adapter = adapter
        self.weak_adapter = weak_adapter or adapter
        self.credential_source = credential_source
        self.provider_id = provider_id or adapter.descriptor.provider_id
        self.state_focus_mode = state_focus_mode
        self.descriptor = CapabilityDescriptor(
            capability_id=capability_id,
            kind="model_provider",
            version="1.0.0",
            metadata={
                "provider_id": self.provider_id,
                "strong_adapter_id": adapter.descriptor.adapter_id,
                "strong_model_id": adapter.descriptor.model_id,
                "weak_adapter_id": self.weak_adapter.descriptor.adapter_id,
                "weak_model_id": self.weak_adapter.descriptor.model_id,
                "state_focus_mode": self.state_focus_mode,
            },
        )

    def _credentials(self) -> Mapping[str, str]:
        if self.credential_source is None:
            return {}
        return self.credential_source.resolve(self.provider_id)

    def _adapter_for_role(self, model_role: str) -> ModelAdapter:
        normalized_role = model_role.strip().lower()
        if normalized_role == "strong":
            return self.adapter
        if normalized_role == "weak":
            return self.weak_adapter
        raise ValueError(f"unsupported model_role: {model_role}")

    def selection_state(self) -> RuntimeModelChoice:
        return RuntimeModelChoice(
            strong_model=GenerationModelProfile(
                profile_id=f"{self.provider_id}:strong",
                provider_id=self.provider_id,
                model_id=self.adapter.descriptor.model_id,
                metadata={"adapter_id": self.adapter.descriptor.adapter_id},
            ),
            weak_model=SupportModelProfile(
                profile_id=f"{self.provider_id}:weak",
                provider_id=self.provider_id,
                model_id=self.weak_adapter.descriptor.model_id,
                metadata={"adapter_id": self.weak_adapter.descriptor.adapter_id},
            ),
            state_focus_mode=self.state_focus_mode,
        )

    def generate(
        self,
        *,
        profile: PersonalModelRuntimeState,
        session: Episode,
        context: ContextBundle,
        prompt: str,
        model_role: str = "strong",
    ) -> ExecutionResult:
        selected_adapter = self._adapter_for_role(model_role)
        request = ModelRequest(
            request_id=f"{session.episode_id}:model:{model_role}",
            profile_id=profile.profile_id,
            session_id=session.episode_id,
            provider_id=self.provider_id,
            model_id=selected_adapter.descriptor.model_id,
            prompt=prompt,
            context={
                "bundle_id": context.bundle_id,
                "token_budget": str(context.token_budget),
                "instruction_refs": ",".join(context.instruction_refs),
                "work_item_ids": ",".join(context.work_item_ids),
                "evidence_refs": ",".join(context.evidence_refs),
                "artifact_ids": ",".join(context.artifact_ids),
                "frozen_prefix_prompt": context.prompt_envelope.frozen_prefix,
                "session_snapshot_prompt": context.prompt_envelope.session_snapshot,
                "rendered_prompt": context.rendered_prompt or "",
            },
            metadata={
                "profile_mode": profile.mode,
                "session_status": session.status,
                "model_role": model_role,
            },
            messages=tuple(context.prompt_envelope.messages),
        )
        result = selected_adapter.generate(request, self._credentials())
        outcome = "ok" if result.failure_kind is None else "failed"
        return ExecutionResult(
            execution_id=result.result_id,
            episode_id=session.episode_id,
            outcome=outcome,
            summary=result.content,
            reasoning=result.reasoning,
            prompt_tokens=result.usage.prompt_tokens,
            completion_tokens=result.usage.completion_tokens,
            total_tokens=result.usage.total_tokens,
            telemetry_event_ids=(request.request_id,),
            side_effects=(
                f"provider={result.provider_id}",
                f"model={result.model_id}",
                f"model_role={model_role}",
                f"credential_keys={result.metadata.get('credential_keys', 'unknown')}",
            ),
            tool_calls=result.tool_calls,
        )
