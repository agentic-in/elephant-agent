"""Anthropic Messages provider adapter.

This module keeps Anthropic-specific request, response, and capability logic
isolated from the generic OpenAI-compatible path. The adapter speaks the native
Messages API shape and the capability bridge converts it into the shared model
provider runtime contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from packages.capabilities.runtime import CapabilityDescriptor, ModelProviderCapability
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
from packages.models.provider_runtime import ProviderRuntimeResolution, attach_session_header, provider_auth_headers
from packages.models.runtime import (
    CredentialSource,
    ModelAdapter,
    ModelAdapterDescriptor,
    ModelEmbeddingResult,
    ModelRequest,
    ModelTextResult,
    ModelUsage,
)
from packages.models.reasoning_parser import split_reasoning_and_content
from ._tool_names import provider_tool_name
from .identity_contract import build_provider_messages, build_provider_system_prompt
from .http import JSONHTTPTransport, UrllibJSONHTTPTransport


ANTHROPIC_API_VERSION = "2023-06-01"
ANTHROPIC_ENDPOINT_PATH = "/v1/messages"
ANTHROPIC_REQUEST_FAMILY = "messages"
THINKING_BUDGET = {"max": 64000, "xhigh": 32000, "high": 16000, "medium": 8000, "low": 4000}
ADAPTIVE_EFFORT_MAP = {
    "max": "max",
    "xhigh": "xhigh",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "minimal": "low",
}


def _is_reasoning_block_type(block_type: str) -> bool:
    normalized = block_type.strip().lower()
    return "reasoning" in normalized or "thinking" in normalized


@dataclass(frozen=True, slots=True)
class AnthropicContentBlock:
    type: str
    text: str
    block_id: str = ""
    name: str = ""
    input: Mapping[str, object] = field(default_factory=dict)
    tool_use_id: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)

    def as_mapping(self) -> dict[str, object]:
        if self.type == "tool_use":
            return {
                "type": "tool_use",
                "id": self.block_id,
                "name": self.name,
                "input": dict(self.input),
                "metadata": dict(self.metadata),
            }
        if self.type == "tool_result":
            return {
                "type": "tool_result",
                "tool_use_id": self.tool_use_id,
                "content": self.text,
                "metadata": dict(self.metadata),
            }
        return {
            "type": self.type,
            "text": self.text,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class AnthropicMessageTurn:
    role: str
    content: tuple[AnthropicContentBlock, ...]
    metadata: Mapping[str, str] = field(default_factory=dict)

    def as_mapping(self) -> dict[str, object]:
        return {
            "role": self.role,
            "content": [block.as_mapping() for block in self.content],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class AnthropicMessagesRequest:
    request_id: str
    provider_id: str
    transport_id: str
    request_family: str
    model_id: str
    base_url: str | None
    endpoint_path: str
    headers: Mapping[str, str]
    system: str
    messages: tuple[AnthropicMessageTurn, ...]
    max_tokens: int
    temperature: float | None = None
    stop_sequences: tuple[str, ...] = ()
    tools: tuple[Mapping[str, object], ...] = ()
    tool_name_map: Mapping[str, str] = field(default_factory=dict)
    thinking: Mapping[str, object] | None = None
    output_config: Mapping[str, object] | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def as_mapping(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self.model_id,
            "max_tokens": self.max_tokens,
            "messages": [
                {
                    "role": turn.role,
                    "content": [_anthropic_wire_content_block(block) for block in turn.content],
                }
                for turn in self.messages
            ],
        }
        if user_id := str(self.metadata.get("user_id") or "").strip():
            payload["metadata"] = {"user_id": user_id}
        if self.system:
            payload["system"] = self.system
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.stop_sequences:
            payload["stop_sequences"] = self.stop_sequences
        if self.tools:
            payload["tools"] = [dict(tool) for tool in self.tools]
        if self.thinking:
            payload["thinking"] = dict(self.thinking)
        if self.output_config:
            payload["output_config"] = dict(self.output_config)
        return payload


def _anthropic_wire_content_block(block: AnthropicContentBlock) -> dict[str, object]:
    if block.type == "tool_use":
        return {
            "type": "tool_use",
            "id": block.block_id,
            "name": block.name,
            "input": dict(block.input),
        }
    if block.type == "tool_result":
        return {
            "type": "tool_result",
            "tool_use_id": block.tool_use_id,
            "content": block.text,
        }
    return {
        "type": block.type,
        "text": block.text,
    }


@dataclass(frozen=True, slots=True)
class AnthropicMessagesResponse:
    response_id: str
    request_id: str
    provider_id: str
    transport_id: str
    model_id: str
    stop_reason: str | None
    content: tuple[AnthropicContentBlock, ...]
    reasoning: tuple[str, ...] = ()
    tool_calls: tuple[ExecutionToolCall, ...] = ()
    usage: ModelUsage = field(default_factory=ModelUsage)
    metadata: Mapping[str, str] = field(default_factory=dict)

    def text(self) -> str:
        return "".join(block.text for block in self.content)

    def as_mapping(self) -> dict[str, object]:
        return {
            "id": self.response_id,
            "type": "message",
            "role": "assistant",
            "content": [block.as_mapping() for block in self.content],
            "model": self.model_id,
            "stop_reason": self.stop_reason,
            "usage": {
                "input_tokens": self.usage.prompt_tokens,
                "output_tokens": self.usage.completion_tokens,
                "total_tokens": self.usage.total_tokens,
                "cache_read_input_tokens": self.usage.cached_prompt_tokens,
                "cache_creation_input_tokens": self.usage.cache_creation_prompt_tokens,
            },
            "metadata": dict(self.metadata),
        }


class AnthropicMessagesModelAdapter(ModelAdapter):
    """Native Anthropic Messages adapter."""

    def __init__(
        self,
        *,
        adapter_id: str,
        resolution: ProviderRuntimeResolution,
        credential_source: CredentialSource | None = None,
        http_transport: JSONHTTPTransport | None = None,
        max_tokens: int = 1024,
        temperature: float | None = None,
        anthropic_version: str = ANTHROPIC_API_VERSION,
        extra_headers: Mapping[str, str] | None = None,
    ) -> None:
        self.resolution = resolution
        self.credential_source = credential_source
        self.http_transport = http_transport or UrllibJSONHTTPTransport()
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.anthropic_version = anthropic_version
        self.extra_headers = dict(extra_headers or {})
        self.descriptor = ModelAdapterDescriptor(
            adapter_id=adapter_id,
            provider_id=resolution.provider_id,
            model_id=resolution.model_id,
            kind="messages",
            supported_tasks=("generate", "summarize"),
            metadata={
                "provider_id": resolution.provider_id,
                "transport_id": resolution.transport_id,
                "request_family": resolution.request_family,
                "endpoint_path": resolution.endpoint_path,
                "native_api": "anthropic_messages",
            },
        )

    def _credential_keys(self, credentials: Mapping[str, str]) -> str:
        if not credentials:
            return "no-credentials"
        return ",".join(sorted(credentials))

    def _resolve_credentials(self, credentials: Mapping[str, str] | None = None) -> Mapping[str, str]:
        if credentials is not None:
            return credentials
        if self.credential_source is None:
            return {}
        return self.credential_source.resolve(self.resolution.provider_id)

    def build_request(
        self,
        request: ModelRequest,
        credentials: Mapping[str, str] | None = None,
    ) -> AnthropicMessagesRequest:
        resolved_credentials = self._resolve_credentials(credentials)
        credential_keys = self._credential_keys(resolved_credentials)
        system = self._compose_system_prompt(request, credential_keys)
        headers = {
            **self.extra_headers,
            "content-type": "application/json",
            **provider_auth_headers(
                provider_id=self.resolution.provider_id,
                request_family=self.resolution.request_family,
                api_key=resolved_credentials.get("api_key"),
                anthropic_version=self.anthropic_version,
            ),
        }
        if beta := request.metadata.get("anthropic_beta"):
            headers["anthropic-beta"] = beta
        attach_session_header(headers, request.session_id)
        reasoning_effort = str(request.reasoning_effort or "").strip().lower()
        thinking, output_config, max_tokens, temperature = self._thinking_config_for(
            model_id=self.resolution.model_id,
            reasoning_effort=reasoning_effort,
            base_max_tokens=self._max_tokens_for(request),
        )
        tools, tool_name_map = self._anthropic_tools_from_request(request.tools)
        messages = self._anthropic_messages_from_request(request, tool_name_map=tool_name_map)
        return AnthropicMessagesRequest(
            request_id=request.request_id,
            provider_id=self.resolution.provider_id,
            transport_id=self.resolution.transport_id,
            request_family=self.resolution.request_family,
            model_id=self.resolution.model_id,
            base_url=self.resolution.base_url,
            endpoint_path=self.resolution.endpoint_path or ANTHROPIC_ENDPOINT_PATH,
            headers=headers,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            tools=tools,
            tool_name_map=tool_name_map,
            thinking=thinking,
            output_config=output_config,
            metadata={
                "bundle_id": request.context.get("bundle_id", ""),
                "profile_id": request.profile_id,
                "session_id": request.session_id,
                "task": request.task,
                "provider_id": self.resolution.provider_id,
                "transport_id": self.resolution.transport_id,
                "credential_keys": credential_keys,
            },
        )

    def parse_response(
        self,
        payload: Mapping[str, Any],
        request: AnthropicMessagesRequest,
    ) -> AnthropicMessagesResponse:
        blocks: list[AnthropicContentBlock] = []
        reasoning_blocks: list[str] = []
        tool_calls: list[ExecutionToolCall] = []
        for block in payload.get("content", []):
            if not isinstance(block, Mapping):
                continue
            block_type = str(block.get("type", "text"))
            if _is_reasoning_block_type(block_type):
                text = str(block.get("thinking") or block.get("text") or "").strip()
                if text:
                    reasoning_blocks.append(text)
                continue
            if block_type == "tool_use":
                wire_tool_name = str(block.get("name") or "").strip()
                tool_name = request.tool_name_map.get(wire_tool_name, wire_tool_name)
                arguments_payload = block.get("input", {})
                arguments = (
                    {str(key): value for key, value in arguments_payload.items()}
                    if isinstance(arguments_payload, Mapping)
                    else {}
                )
                if tool_name:
                    tool_calls.append(
                        ExecutionToolCall(
                            tool_name=tool_name,
                            arguments=arguments,
                            call_id=str(block.get("id") or "").strip(),
                        )
                    )
                continue
            combined = split_reasoning_and_content(str(block.get("text", "")), streaming=False)
            if combined.reasoning:
                reasoning_blocks.append(combined.reasoning)
            blocks.append(
                AnthropicContentBlock(
                    type=block_type,
                    text=combined.content,
                    metadata={
                        key: str(value)
                        for key, value in block.items()
                        if key not in {"type", "text"}
                    },
                )
            )
        usage_payload = payload.get("usage", {})
        usage = ModelUsage(
            prompt_tokens=int(usage_payload.get("input_tokens", 0)),
            completion_tokens=int(usage_payload.get("output_tokens", 0)),
            total_tokens=int(usage_payload.get("input_tokens", 0)) + int(usage_payload.get("output_tokens", 0)),
            cached_prompt_tokens=int(usage_payload.get("cache_read_input_tokens", 0) or 0),
            cache_creation_prompt_tokens=int(usage_payload.get("cache_creation_input_tokens", 0) or 0),
            cache_usage_reported=(
                "cache_read_input_tokens" in usage_payload
                or "cache_creation_input_tokens" in usage_payload
            ),
        )
        return AnthropicMessagesResponse(
            response_id=str(payload.get("id", f"{request.request_id}:anthropic")),
            request_id=request.request_id,
            provider_id=request.provider_id,
            transport_id=request.transport_id,
            model_id=str(payload.get("model", request.model_id)),
            stop_reason=payload.get("stop_reason"),
            content=tuple(blocks),
            reasoning=tuple(reasoning_blocks),
            tool_calls=tuple(tool_calls),
            usage=usage,
            metadata={
                "request_family": request.request_family,
                "endpoint_path": request.endpoint_path,
                "anthropic_version": self.anthropic_version,
            },
        )

    def generate(self, request: ModelRequest, credentials: Mapping[str, str]) -> ModelTextResult:
        native_request = self.build_request(request, credentials)
        if native_request.base_url is None:
            raise RuntimeError("anthropic provider execution requires a base_url")
        response_payload = self.http_transport.post_json(
            url=self._compose_url(native_request.base_url, native_request.endpoint_path),
            headers=native_request.headers,
            payload=native_request.as_mapping(),
        )
        response = self.parse_response(response_payload.payload, native_request)
        return ModelTextResult(
            result_id=response.response_id,
            request_id=request.request_id,
            adapter_id=self.descriptor.adapter_id,
            provider_id=self.resolution.provider_id,
            model_id=self.resolution.model_id,
            task=request.task,
            content=response.text(),
            reasoning="\n\n".join(response.reasoning),
            usage=response.usage,
            tool_calls=response.tool_calls,
            metadata={
                "request_family": native_request.request_family,
                "transport_id": native_request.transport_id,
                "endpoint_path": native_request.endpoint_path,
                "stop_reason": response.stop_reason or "unknown",
                "credential_keys": native_request.metadata.get("credential_keys", "unknown"),
                "anthropic_version": self.anthropic_version,
                "status_code": str(response_payload.status_code),
            },
        )

    def summarize(self, request: ModelRequest, credentials: Mapping[str, str]) -> ModelTextResult:
        summary_request = ModelRequest(
            request_id=request.request_id,
            profile_id=request.profile_id,
            session_id=request.session_id,
            provider_id=request.provider_id,
            model_id=request.model_id,
            prompt=request.prompt,
            context=dict(request.context),
            task="summarize",
            reasoning_effort=request.reasoning_effort,
            metadata=dict(request.metadata),
            messages=tuple(request.messages),
        )
        result = self.generate(summary_request, credentials)
        return ModelTextResult(
            result_id=result.result_id,
            request_id=result.request_id,
            adapter_id=result.adapter_id,
            provider_id=result.provider_id,
            model_id=result.model_id,
            task="summarize",
            content=result.content,
            usage=result.usage,
            failure_kind=result.failure_kind,
            metadata=dict(result.metadata),
        )

    def embed(self, request: ModelRequest, credentials: Mapping[str, str]) -> ModelEmbeddingResult:
        credential_keys = self._credential_keys(self._resolve_credentials(credentials))
        return ModelEmbeddingResult(
            result_id=f"{request.request_id}:embed",
            request_id=request.request_id,
            adapter_id=self.descriptor.adapter_id,
            provider_id=self.resolution.provider_id,
            model_id=self.resolution.model_id,
            task="embed",
            embeddings=(),
            failure_kind="unsupported",
            metadata={
                "request_family": self.resolution.request_family,
                "transport_id": self.resolution.transport_id,
                "credential_keys": credential_keys,
            },
        )

    def _compose_system_prompt(self, request: ModelRequest, credential_keys: str) -> str:
        del credential_keys
        return build_provider_system_prompt(request)

    def _compose_user_text(self, request: ModelRequest) -> str:
        context_bits: list[str] = []
        for key in ("work_item_ids", "evidence_refs", "artifact_ids", "mode"):
            value = request.context.get(key)
            if value:
                context_bits.append(f"{key}={value}")
        if request.metadata:
            context_bits.extend(f"{key}={value}" for key, value in sorted(request.metadata.items()))
        prompt = request.prompt.strip() or "acknowledged"
        if context_bits:
            return f"{prompt}\n\ncontext: {'; '.join(context_bits)}"
        return prompt

    def _anthropic_messages_from_request(
        self,
        request: ModelRequest,
        *,
        tool_name_map: Mapping[str, str],
    ) -> tuple[AnthropicMessageTurn, ...]:
        turns: list[AnthropicMessageTurn] = []
        for message in build_provider_messages(request):
            role = str(message.role or "").strip().lower()
            if role == "system":
                continue
            turn = self._anthropic_turn_from_message(message, tool_name_map=tool_name_map)
            if turn is None:
                continue
            if turns and turns[-1].role == turn.role:
                previous = turns[-1]
                turns[-1] = AnthropicMessageTurn(
                    role=previous.role,
                    content=previous.content + turn.content,
                    metadata=previous.metadata,
                )
            else:
                turns.append(turn)
        if not turns:
            turns.append(
                AnthropicMessageTurn(
                    role="user",
                    content=(AnthropicContentBlock(type="text", text="acknowledged"),),
                    metadata={"task": request.task},
                )
            )
        return tuple(turns)

    def _anthropic_turn_from_message(
        self,
        message: PromptMessage,
        *,
        tool_name_map: Mapping[str, str],
    ) -> AnthropicMessageTurn | None:
        role = str(message.role or "").strip().lower()
        if role == "tool":
            if not message.tool_call_id:
                return None
            return AnthropicMessageTurn(
                role="user",
                content=(
                    AnthropicContentBlock(
                        type="tool_result",
                        text=str(message.content or ""),
                        tool_use_id=message.tool_call_id,
                    ),
                ),
            )
        if role not in {"user", "assistant"}:
            return None
        blocks: list[AnthropicContentBlock] = []
        if message.content.strip():
            blocks.append(AnthropicContentBlock(type="text", text=message.content))
        if role == "assistant":
            for call in message.tool_calls:
                if not isinstance(call, Mapping):
                    continue
                blocks.append(self._anthropic_tool_use_block(call, tool_name_map=tool_name_map))
        if not blocks:
            return None
        return AnthropicMessageTurn(role=role, content=tuple(blocks))

    def _anthropic_tool_use_block(
        self,
        call: Mapping[str, object],
        *,
        tool_name_map: Mapping[str, str],
    ) -> AnthropicContentBlock:
        call_id = str(call.get("id") or call.get("call_id") or "").strip() or "toolu_context"
        name = self._provider_tool_name(str(call.get("name") or call.get("tool_name") or ""), tool_name_map=tool_name_map)
        arguments = call.get("arguments")
        return AnthropicContentBlock(
            type="tool_use",
            text="",
            block_id=call_id,
            name=name,
            input={str(key): value for key, value in arguments.items()} if isinstance(arguments, Mapping) else {},
        )

    def _provider_tool_name(self, tool_name: str, *, tool_name_map: Mapping[str, str]) -> str:
        normalized = str(tool_name or "").strip()
        if not normalized:
            return "tool_context"
        inverse = {original: alias for alias, original in tool_name_map.items()}
        return inverse.get(normalized, normalized)

    def _anthropic_tools_from_request(
        self,
        tools: tuple[Mapping[str, object], ...],
    ) -> tuple[tuple[Mapping[str, object], ...], dict[str, str]]:
        rendered: list[Mapping[str, object]] = []
        tool_name_map: dict[str, str] = {}
        used_aliases: set[str] = set()
        for tool in tools:
            if not isinstance(tool, Mapping):
                continue
            function = tool.get("function")
            if not isinstance(function, Mapping):
                continue
            name = str(function.get("name") or "").strip()
            if not name:
                continue
            alias = provider_tool_name(name, used_aliases)
            description = str(function.get("description") or "").strip()
            parameters = function.get("parameters")
            input_schema = dict(parameters) if isinstance(parameters, Mapping) else {"type": "object", "properties": {}}
            rendered.append(
                {
                    "name": alias,
                    "description": description,
                    "input_schema": input_schema,
                }
            )
            used_aliases.add(alias)
            tool_name_map[alias] = name
        return tuple(rendered), tool_name_map

    def _max_tokens_for(self, request: ModelRequest) -> int:
        token_budget = request.context.get("token_budget")
        if token_budget is not None:
            try:
                budget = int(token_budget)
            except (TypeError, ValueError):
                budget = self.max_tokens
            else:
                budget = max(32, min(self.max_tokens, budget))
            return budget
        return self.max_tokens

    def _compose_url(self, base_url: str, endpoint_path: str) -> str:
        return f"{base_url.rstrip('/')}/{endpoint_path.lstrip('/')}"

    def _thinking_config_for(
        self,
        *,
        model_id: str,
        reasoning_effort: str,
        base_max_tokens: int,
    ) -> tuple[Mapping[str, object] | None, Mapping[str, object] | None, int, float | None]:
        if not reasoning_effort or not self.resolution.supports_reasoning:
            return None, None, base_max_tokens, self.temperature
        effort = reasoning_effort.lower()
        if self._supports_adaptive_thinking(model_id):
            return (
                {"type": "adaptive"},
                {"effort": ADAPTIVE_EFFORT_MAP.get(effort, "medium")},
                base_max_tokens,
                self.temperature,
            )
        budget = THINKING_BUDGET.get(effort, THINKING_BUDGET["medium"])
        return (
            {"type": "enabled", "budget_tokens": budget},
            None,
            max(base_max_tokens, budget + 4096),
            1,
        )

    def _supports_adaptive_thinking(self, model_id: str) -> bool:
        normalized = model_id.lower()
        return any(v in normalized for v in ("4.6", "4-6", "4.7", "4-7"))


class AnthropicMessagesProviderCapability(ModelProviderCapability):
    """Shared runtime bridge for the native Anthropic adapter."""

    def __init__(
        self,
        *,
        adapter: AnthropicMessagesModelAdapter,
        credential_source: CredentialSource | None = None,
        capability_id: str = "model.anthropic.messages",
    ) -> None:
        self.adapter = adapter
        self.credential_source = credential_source or adapter.credential_source
        self.descriptor = CapabilityDescriptor(
            capability_id=capability_id,
            kind="model_provider",
            version="1.0.0",
            metadata={
                "provider_id": adapter.resolution.provider_id,
                "transport_id": adapter.resolution.transport_id,
                "request_family": adapter.resolution.request_family,
                "model_id": adapter.resolution.model_id,
                "adapter_id": adapter.descriptor.adapter_id,
                "native_api": "anthropic_messages",
            },
        )

    def _credentials(self) -> Mapping[str, str]:
        if self.credential_source is None:
            return {}
        return self.credential_source.resolve(self.adapter.resolution.provider_id)

    def generate(
        self,
        *,
        profile: PersonalModelRuntimeState,
        session: Episode,
        context: ContextBundle,
        prompt: str,
        model_role: str = "strong",
    ) -> ExecutionResult:
        request = ModelRequest(
            request_id=f"{session.episode_id}:anthropic",
            profile_id=profile.profile_id,
            session_id=session.episode_id,
            provider_id=self.adapter.resolution.provider_id,
            model_id=self.adapter.resolution.model_id,
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
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            messages=tuple(context.prompt_envelope.messages),
        )
        result = self.adapter.generate(request, self._credentials())
        return ExecutionResult(
            execution_id=result.result_id,
            episode_id=session.episode_id,
            outcome="ok" if result.failure_kind is None else "failed",
            summary=result.content,
            reasoning=result.reasoning,
            prompt_tokens=result.usage.prompt_tokens,
            completion_tokens=result.usage.completion_tokens,
            total_tokens=result.usage.total_tokens,
            cached_prompt_tokens=result.usage.cached_prompt_tokens,
            cache_creation_prompt_tokens=result.usage.cache_creation_prompt_tokens,
            cache_usage_reported=result.usage.cache_usage_reported,
            telemetry_event_ids=(request.request_id,),
            side_effects=(
                f"provider={result.provider_id}",
                f"transport={self.adapter.resolution.transport_id}",
                f"model_role={model_role}",
                f"credential_keys={result.metadata.get('credential_keys', 'unknown')}",
            ),
            tool_calls=result.tool_calls,
        )
