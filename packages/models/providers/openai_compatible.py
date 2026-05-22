"""Generic OpenAI-compatible provider adapter.

This module provides one reusable path for endpoints that speak the common
OpenAI-compatible request shape. The adapter stays provider-neutral at the
kernel boundary while still exposing the transport, credential, and endpoint
metadata needed by product surfaces and integration tests.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from packages.contracts.runtime import ExecutionToolCall, PromptMessage

from ..provider_runtime import ProviderRuntimeResolution, ProviderRuntimeResolver, attach_session_header
from ..runtime import CredentialSource, ModelAdapterDescriptor, ModelEmbeddingResult, ModelRequest, ModelTextResult, ModelUsage
from ._tool_names import provider_tool_name
from .identity_contract import build_provider_messages, build_provider_system_prompt
from .http import JSONHTTPTransport, UrllibJSONHTTPTransport
from .message_payloads import openai_chat_messages_payload, openai_responses_input_payload, prompt_message_has_image_parts
from .openai_usage import openai_compatible_usage_from_payload
from ..reasoning_parser import combine_reasoning_text, normalize_reasoning_text, split_reasoning_and_content, stitch_text_fragments

_SCHEMA_TYPE_PREFERENCE = ("string", "object", "array", "integer", "number", "boolean")


@dataclass(frozen=True, slots=True)
class OpenAICompatibleProviderConfig:
    provider_id: str = "openai-compatible"
    base_url: str = ""
    model_id: str = ""
    extra_headers: Mapping[str, str] = field(default_factory=dict)
    auth_header_name: str = "Authorization"
    auth_scheme: str = "Bearer"

    def __post_init__(self) -> None:
        if not self.base_url:
            raise ValueError("base_url is required for an OpenAI-compatible provider")
        if not self.model_id:
            raise ValueError("model_id is required for an OpenAI-compatible provider")


@dataclass(frozen=True, slots=True)
class OpenAICompatibleRequestPlan:
    request_id: str
    provider_id: str
    model_id: str
    base_url: str
    endpoint_path: str
    url: str
    request_family: str
    transport_id: str
    headers: Mapping[str, str] = field(default_factory=dict)
    payload: Mapping[str, Any] = field(default_factory=dict)
    tool_name_map: Mapping[str, str] = field(default_factory=dict)
    credential_keys: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)


class OpenAICompatibleProviderAdapter:
    """Plan and execute requests for OpenAI-compatible and OpenAI transports."""

    def __init__(
        self,
        *,
        config: OpenAICompatibleProviderConfig,
        runtime_resolver: ProviderRuntimeResolver | None = None,
        credential_source: CredentialSource | None = None,
        http_transport: JSONHTTPTransport | None = None,
        adapter_id: str = "adapter.models.openai-compatible",
        stream_observer: Callable[[str], None] | None = None,
    ) -> None:
        self.config = config
        self.runtime_resolver = runtime_resolver or ProviderRuntimeResolver.default()
        self.credential_source = credential_source
        self.http_transport = http_transport or UrllibJSONHTTPTransport()
        self.stream_observer = stream_observer
        self.descriptor = ModelAdapterDescriptor(
            adapter_id=adapter_id,
            provider_id=config.provider_id,
            model_id=config.model_id,
            kind="chat",
            supported_tasks=("generate", "summarize", "embed"),
            metadata={
                "provider_id": config.provider_id,
                "transport_id": "openai_chat_compatible",
                "base_url": config.base_url,
            },
        )

    def plan_request(
        self,
        request: ModelRequest,
        credentials: Mapping[str, str] | None = None,
    ) -> OpenAICompatibleRequestPlan:
        provider_id = self._resolve_provider_id(request)
        resolution = self.runtime_resolver.resolve(
            provider_id,
            model_id=request.model_id or self.config.model_id,
            base_url=self.config.base_url,
        )
        resolved_credentials = self._resolve_credentials(provider_id, credentials)
        if request.task == "embed" and not resolution.supports_embeddings:
            raise ValueError(f"transport {resolution.transport_id} does not support embeddings")
        endpoint_path = self._endpoint_path_for_task(request.task, resolution.endpoint_path)
        url = self._compose_url(self.config.base_url, endpoint_path)
        headers = self._build_headers(resolution, resolved_credentials, session_id=request.session_id)
        payload, tool_name_map = self._build_payload(request, request.task, resolution)
        return OpenAICompatibleRequestPlan(
            request_id=request.request_id,
            provider_id=provider_id,
            model_id=resolution.model_id,
            base_url=self.config.base_url,
            endpoint_path=endpoint_path,
            url=url,
            request_family=resolution.request_family if request.task != "embed" else "embeddings",
            transport_id=resolution.transport_id,
            headers=headers,
            payload=payload,
            tool_name_map=tool_name_map,
            credential_keys=tuple(sorted(resolved_credentials)),
            metadata={
                "supports_streaming": str(resolution.supports_streaming).lower(),
                "supports_embeddings": str(resolution.supports_embeddings).lower(),
                "supports_tools": str(resolution.supports_tools).lower(),
                "supports_reasoning": str(resolution.supports_reasoning).lower(),
            },
        )

    def generate(
        self,
        request: ModelRequest,
        credentials: Mapping[str, str],
    ) -> ModelTextResult:
        plan = self.plan_request(request, credentials)
        if bool(plan.payload.get("stream")):
            return self._generate_streaming(request, plan)
        response = self.http_transport.post_json(url=plan.url, headers=plan.headers, payload=plan.payload)
        return self._text_result_from_payload(
            request=request,
            plan=plan,
            payload=response.payload,
            status_code=response.status_code,
        )

    def _generate_streaming(
        self,
        request: ModelRequest,
        plan: OpenAICompatibleRequestPlan,
    ) -> ModelTextResult:
        transport = getattr(self.http_transport, "post_json_stream", None)
        if transport is None:
            fallback_response = self.http_transport.post_json(url=plan.url, headers=plan.headers, payload=plan.payload)
            return self._text_result_from_payload(
                request=request,
                plan=plan,
                payload=fallback_response.payload,
                status_code=fallback_response.status_code,
                stream_used=False,
            )
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        collected_output: list[Mapping[str, Any]] = []
        usage = ModelUsage()
        result_id = f"{request.request_id}:generate"
        result_model = plan.model_id
        final_payload: Mapping[str, Any] | None = None
        chat_stream_tool_calls: dict[int, dict[str, Any]] = {}
        for chunk in transport(url=plan.url, headers=plan.headers, payload=plan.payload):
            payload = chunk.payload
            event_name = chunk.event
            if plan.request_family == "responses":
                response_payload = self._responses_stream_response_payload(
                    payload,
                    collected_output=collected_output,
                    text_parts=text_parts,
                )
                if response_payload:
                    final_payload = response_payload
                result_id = str(response_payload.get("id", payload.get("id", result_id)))
                result_model = str(response_payload.get("model", payload.get("model", result_model)))
                if "output_item.done" in str(event_name or payload.get("type") or ""):
                    item = payload.get("item")
                    if isinstance(item, Mapping):
                        collected_output.append({str(key): value for key, value in item.items()})
                delta = self._extract_stream_text_delta(
                    payload,
                    request_family=plan.request_family,
                    event=event_name,
                )
                reasoning_delta = self._extract_stream_reasoning_delta(
                    payload,
                    request_family=plan.request_family,
                    event=event_name,
                )
                chunk_usage = self._usage_from_payload(response_payload)
            else:
                result_id = str(payload.get("id", result_id))
                result_model = str(payload.get("model", result_model))
                delta = self._extract_stream_text_delta(payload, request_family=plan.request_family)
                reasoning_delta = self._extract_stream_reasoning_delta(
                    payload,
                    request_family=plan.request_family,
                )
                self._merge_chat_stream_tool_calls(payload, chat_stream_tool_calls)
                chunk_usage = self._usage_from_payload(payload)
            if reasoning_delta:
                reasoning_parts.append(reasoning_delta)
                self._emit_stream_delta(reasoning_delta, reasoning=True)
            if delta:
                text_parts.append(delta)
                self._emit_stream_delta(delta, reasoning=False)
            if any((chunk_usage.prompt_tokens, chunk_usage.completion_tokens, chunk_usage.total_tokens)):
                usage = chunk_usage
        if plan.request_family == "responses":
            payload = (
                final_payload
                if final_payload is not None
                else self._responses_stream_response_payload(
                    {},
                    collected_output=collected_output,
                    text_parts=text_parts,
                )
            )
            tool_calls = self._extract_tool_calls(
                payload,
                request_family=plan.request_family,
                tool_name_map=plan.tool_name_map,
            )
            try:
                content, reasoning = self._extract_text_and_reasoning(
                    payload,
                    request_family=plan.request_family,
                    allow_empty=bool(tool_calls),
                )
            except RuntimeError:
                content, reasoning = "", ""
            if reasoning:
                reasoning = normalize_reasoning_text(reasoning)
            else:
                reasoning = stitch_text_fragments(*reasoning_parts).strip()
            if not content and not tool_calls and not reasoning:
                raise RuntimeError("responses transport returned no streamed assistant text")
            return ModelTextResult(
                result_id=result_id,
                request_id=request.request_id,
                adapter_id=self.descriptor.adapter_id,
                provider_id=plan.provider_id,
                model_id=result_model,
                task="generate",
                content=content,
                reasoning=reasoning,
                usage=usage,
                metadata={
                    "endpoint_path": plan.endpoint_path,
                    "url": plan.url,
                    "credential_keys": ",".join(plan.credential_keys) or "no-credentials",
                    "transport_id": plan.transport_id,
                    "request_family": plan.request_family,
                    "status_code": "200",
                    "stream": "true",
                },
                tool_calls=tool_calls,
            )
        content = "".join(text_parts)
        reasoning = stitch_text_fragments(*reasoning_parts).strip()
        tool_calls = self._chat_stream_tool_calls(
            chat_stream_tool_calls,
            tool_name_map=plan.tool_name_map,
        )
        if not content and not tool_calls and not reasoning:
            raise RuntimeError("chat-completions transport returned no streamed assistant text")
        return ModelTextResult(
            result_id=result_id,
            request_id=request.request_id,
            adapter_id=self.descriptor.adapter_id,
            provider_id=plan.provider_id,
            model_id=result_model,
            task="generate",
            content=content,
            reasoning=reasoning,
            usage=usage,
            metadata={
                "endpoint_path": plan.endpoint_path,
                "url": plan.url,
                "credential_keys": ",".join(plan.credential_keys) or "no-credentials",
                "transport_id": plan.transport_id,
                "request_family": plan.request_family,
                "status_code": "200",
                "stream": "true",
            },
            tool_calls=tool_calls,
        )

    def _text_result_from_payload(
        self,
        *,
        request: ModelRequest,
        plan: OpenAICompatibleRequestPlan,
        payload: Mapping[str, Any],
        status_code: int | str,
        stream_used: bool = False,
    ) -> ModelTextResult:
        tool_calls = self._extract_tool_calls(
            payload,
            request_family=plan.request_family,
            tool_name_map=plan.tool_name_map,
        )
        content, reasoning = self._extract_text_and_reasoning(
            payload,
            request_family=plan.request_family,
            allow_empty=bool(tool_calls),
        )
        usage = self._usage_from_payload(payload)
        return ModelTextResult(
            result_id=str(payload.get("id", f"{request.request_id}:generate")),
            request_id=request.request_id,
            adapter_id=self.descriptor.adapter_id,
            provider_id=plan.provider_id,
            model_id=str(payload.get("model", plan.model_id)),
            task="generate",
            content=content,
            reasoning=reasoning,
            usage=usage,
            metadata={
                "endpoint_path": plan.endpoint_path,
                "url": plan.url,
                "credential_keys": ",".join(plan.credential_keys) or "no-credentials",
                "transport_id": plan.transport_id,
                "request_family": plan.request_family,
                "status_code": str(status_code),
                "stream": "true" if stream_used else "false",
            },
            tool_calls=tool_calls,
        )

    def summarize(
        self,
        request: ModelRequest,
        credentials: Mapping[str, str],
    ) -> ModelTextResult:
        result = self.generate(
            ModelRequest(
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
            ),
            credentials,
        )
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

    def embed(
        self,
        request: ModelRequest,
        credentials: Mapping[str, str],
    ) -> ModelEmbeddingResult:
        plan = self.plan_request(request, credentials)
        response = self.http_transport.post_json(url=plan.url, headers=plan.headers, payload=plan.payload)
        embeddings = self._extract_embeddings(response.payload)
        return ModelEmbeddingResult(
            result_id=str(response.payload.get("id", f"{request.request_id}:embed")),
            request_id=request.request_id,
            adapter_id=self.descriptor.adapter_id,
            provider_id=plan.provider_id,
            model_id=str(response.payload.get("model", plan.model_id)),
            task="embed",
            embeddings=embeddings,
            metadata={
                "endpoint_path": plan.endpoint_path,
                "url": plan.url,
                "credential_keys": ",".join(plan.credential_keys) or "no-credentials",
                "transport_id": plan.transport_id,
                "request_family": plan.request_family,
                "status_code": str(response.status_code),
            },
        )

    def _resolve_provider_id(self, request: ModelRequest) -> str:
        provider_id = request.provider_id or self.config.provider_id
        if provider_id != self.config.provider_id:
            raise ValueError(
                f"request provider_id {provider_id!r} does not match adapter provider_id "
                f"{self.config.provider_id!r}"
            )
        return provider_id

    def _resolve_credentials(
        self,
        provider_id: str,
        explicit_credentials: Mapping[str, str] | None,
    ) -> Mapping[str, str]:
        if explicit_credentials is not None:
            return dict(explicit_credentials)
        if self.credential_source is None:
            return {}
        return dict(self.credential_source.resolve(provider_id))

    def _build_headers(
        self,
        resolution: ProviderRuntimeResolution,
        credentials: Mapping[str, str],
        *,
        session_id: str,
    ) -> dict[str, str]:
        headers = dict(self.config.extra_headers)
        headers["Content-Type"] = "application/json"
        api_key = credentials.get("api_key")
        if api_key:
            headers[resolution.auth_header_name] = f"{self.config.auth_scheme} {api_key}"
        attach_session_header(headers, session_id)
        return headers

    def _build_payload(
        self,
        request: ModelRequest,
        task: str,
        resolution: ProviderRuntimeResolution,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        if task == "embed":
            input_text = request.context.get("input") or request.context.get("text") or request.prompt
            return (
                {
                    "model": resolution.model_id,
                    "input": input_text,
                    "encoding_format": "float",
                },
                {},
            )
        provider_messages = build_provider_messages(request)
        image_references_as_text = self._request_has_image_parts(provider_messages) and not self._supports_image_input(resolution)
        if image_references_as_text and resolution.provider_id in {"minimax", "minimax-cn"}:
            provider_messages = self._with_minimax_mcp_image_hint(provider_messages)
        if resolution.request_family == "responses":
            should_stream = bool(resolution.supports_streaming)
            response_tools, tool_name_map = (
                self._normalized_tool_definitions(
                    request.tools,
                    request_family="responses",
                    strict_schema=self._requires_strict_tool_schema(resolution),
                )
                if request.tools and resolution.supports_tools
                else ((), {})
            )
            payload: dict[str, Any] = {
                "model": resolution.model_id,
                "input": openai_responses_input_payload(
                    provider_messages,
                    tool_name_map=tool_name_map,
                    image_references_as_text=image_references_as_text,
                ),
                "store": False,
                "stream": should_stream,
            }
            payload["instructions"] = build_provider_system_prompt(request)
            if request.reasoning_effort and resolution.supports_reasoning:
                payload["reasoning"] = {"effort": request.reasoning_effort}
            if response_tools:
                payload["tools"] = response_tools
                if payload["tools"]:
                    payload["tool_choice"] = "auto"
                    payload["parallel_tool_calls"] = True
            return payload, tool_name_map
        should_stream = bool(self.stream_observer and resolution.supports_streaming)
        tool_name_map: dict[str, str] = {}
        chat_tools: tuple[Mapping[str, object], ...] = ()
        if request.tools and resolution.supports_tools:
            chat_tools, tool_name_map = self._normalized_tool_definitions(
                request.tools,
                request_family="chat_completions",
                strict_schema=self._requires_strict_tool_schema(resolution),
            )
        messages = openai_chat_messages_payload(
            provider_messages,
            tool_name_map=tool_name_map,
            image_references_as_text=image_references_as_text,
        )
        payload = {
            "model": resolution.model_id,
            "messages": messages,
            "stream": should_stream,
        }
        if (
            request.reasoning_effort
            and resolution.supports_reasoning
            and resolution.provider_id == "copilot"
        ):
            payload["reasoning_effort"] = request.reasoning_effort
        if chat_tools:
            payload["tools"] = chat_tools
            if payload["tools"]:
                payload["tool_choice"] = "auto"
                payload["parallel_tool_calls"] = True
        if payload["stream"]:
            payload["stream_options"] = {"include_usage": True}
        return payload, tool_name_map

    def _responses_tool_definition(self, payload: Mapping[str, object]) -> dict[str, object]:
        if not isinstance(payload, Mapping):
            return {}
        function_payload = payload.get("function")
        if isinstance(function_payload, Mapping):
            normalized: dict[str, object] = {
                "type": str(payload.get("type") or "function"),
                "name": str(function_payload.get("name") or ""),
                "description": str(function_payload.get("description") or ""),
                "parameters": dict(function_payload.get("parameters") or {}),
                "strict": bool(function_payload.get("strict", payload.get("strict", False))),
            }
            return normalized
        return {str(key): value for key, value in payload.items()}

    def _chat_tool_definition(self, payload: Mapping[str, object]) -> dict[str, object]:
        if not isinstance(payload, Mapping):
            return {}
        function_payload = payload.get("function")
        if isinstance(function_payload, Mapping):
            return {
                **{str(key): value for key, value in payload.items()},
                "type": str(payload.get("type") or "function"),
                "function": {str(key): value for key, value in function_payload.items()},
            }
        name = str(payload.get("name") or "").strip()
        if not name:
            return {}
        normalized: dict[str, object] = {
            "type": str(payload.get("type") or "function"),
            "function": {
                "name": name,
                "description": str(payload.get("description") or ""),
                "parameters": dict(payload.get("parameters") or {}),
            },
        }
        strict = payload.get("strict")
        if strict is not None:
            normalized["function"]["strict"] = strict
        return normalized

    def _normalized_tool_definitions(
        self,
        tools: tuple[Mapping[str, object], ...],
        *,
        request_family: str,
        strict_schema: bool,
    ) -> tuple[list[dict[str, object]], dict[str, str]]:
        normalized_tools: list[dict[str, object]] = []
        tool_name_map: dict[str, str] = {}
        used_aliases: set[str] = set()
        for item in tools:
            normalized = (
                self._responses_tool_definition(item)
                if request_family == "responses"
                else self._chat_tool_definition(item)
            )
            if not normalized:
                continue
            normalized = self._sanitize_tool_definition(normalized, request_family=request_family, strict_schema=strict_schema)
            if not normalized:
                continue
            if request_family == "responses":
                raw_name = str(normalized.get("name") or "").strip()
                if not raw_name:
                    continue
                alias = self._provider_tool_name(raw_name, used_aliases)
                normalized["name"] = alias
            else:
                function_payload = normalized.get("function")
                if not isinstance(function_payload, Mapping):
                    continue
                raw_name = str(function_payload.get("name") or "").strip()
                if not raw_name:
                    continue
                alias = self._provider_tool_name(raw_name, used_aliases)
                normalized["function"] = {
                    **{str(key): value for key, value in function_payload.items()},
                    "name": alias,
                }
            normalized_tools.append(normalized)
            used_aliases.add(alias)
            tool_name_map[alias] = raw_name
        return normalized_tools, tool_name_map

    def _requires_strict_tool_schema(self, resolution: ProviderRuntimeResolution) -> bool:
        return resolution.request_family == "responses" or resolution.provider_id in {"copilot", "openai", "openai-codex"}

    def _supports_image_input(self, resolution: ProviderRuntimeResolution) -> bool:
        return resolution.provider_id not in {"minimax", "minimax-cn"}

    def _request_has_image_parts(self, messages: tuple[Any, ...]) -> bool:
        return any(prompt_message_has_image_parts(message) for message in messages)

    def _with_minimax_mcp_image_hint(self, messages: tuple[PromptMessage, ...]) -> tuple[PromptMessage, ...]:
        hint = (
            "MiniMax text API cannot receive image bytes directly. "
            "When the user provides @image:/path references, keep the local path and, "
            "if an MCP image tool such as understand_image is available, call it with "
            "image_url set to that path and prompt set to the user's question before answering."
        )
        updated_messages: list[PromptMessage] = []
        inserted = False
        for message in messages:
            if not inserted and str(message.role or "").strip().lower() == "system":
                updated_messages.append(
                    PromptMessage(
                        role=message.role,
                        content=f"{message.content}\n\n{hint}",
                        name=message.name,
                        tool_call_id=message.tool_call_id,
                        tool_name=message.tool_name,
                        tool_calls=message.tool_calls,
                        metadata=message.metadata,
                    )
                )
                inserted = True
            else:
                updated_messages.append(message)
        if inserted:
            return tuple(updated_messages)
        return (PromptMessage(role="system", content=hint), *messages)

    def _sanitize_tool_definition(
        self,
        payload: Mapping[str, object],
        *,
        request_family: str,
        strict_schema: bool,
    ) -> dict[str, object]:
        normalized = {str(key): value for key, value in payload.items()}
        if request_family == "responses":
            parameters = normalized.get("parameters")
            normalized["parameters"] = self._sanitize_json_schema(parameters, strict=strict_schema)
            return normalized
        function_payload = normalized.get("function")
        if not isinstance(function_payload, Mapping):
            return normalized
        function_mapping = {str(key): value for key, value in function_payload.items()}
        function_mapping["parameters"] = self._sanitize_json_schema(
            function_mapping.get("parameters"),
            strict=strict_schema,
        )
        normalized["function"] = function_mapping
        return normalized

    def _sanitize_json_schema(self, payload: object, *, strict: bool) -> dict[str, object]:
        if not isinstance(payload, Mapping):
            return {"type": "object", "properties": {}}
        schema = {str(key): value for key, value in payload.items()}
        resolved_type = self._schema_type(schema.get("type"), strict=strict)
        normalized: dict[str, object] = {}
        if resolved_type:
            normalized["type"] = resolved_type
        description = schema.get("description")
        if isinstance(description, str) and description.strip():
            normalized["description"] = description.strip()
        enum = schema.get("enum")
        if isinstance(enum, (list, tuple)):
            normalized_enum = [str(item) if resolved_type == "string" else item for item in enum]
            if normalized_enum:
                normalized["enum"] = normalized_enum
        if resolved_type == "object" or ("properties" in schema and resolved_type != "array"):
            properties = schema.get("properties")
            if isinstance(properties, Mapping):
                normalized_properties: dict[str, object] = {}
                for key, value in properties.items():
                    if not isinstance(value, Mapping):
                        continue
                    normalized_properties[str(key)] = self._sanitize_json_schema(value, strict=strict)
                normalized["properties"] = normalized_properties
                required = schema.get("required")
                if isinstance(required, (list, tuple)) and normalized_properties:
                    normalized["required"] = [
                        str(item)
                        for item in required
                        if str(item).strip() and str(item) in normalized_properties
                    ]
        if resolved_type == "array":
            items = schema.get("items")
            if isinstance(items, Mapping):
                normalized["items"] = self._sanitize_json_schema(items, strict=strict)
            elif strict:
                normalized["items"] = {"type": "string"}
        if resolved_type in {"integer", "number"}:
            minimum = schema.get("minimum")
            maximum = schema.get("maximum")
            if isinstance(minimum, (int, float)):
                normalized["minimum"] = minimum
            if isinstance(maximum, (int, float)):
                normalized["maximum"] = maximum
        if "type" not in normalized:
            normalized["type"] = "object"
            normalized.setdefault("properties", {})
        if normalized.get("type") == "object":
            normalized.setdefault("properties", {})
        return normalized

    def _schema_type(self, raw_type: object, *, strict: bool) -> str | None:
        if isinstance(raw_type, str):
            return raw_type
        if isinstance(raw_type, (list, tuple)):
            candidates = [str(item).strip() for item in raw_type if str(item).strip()]
            if not candidates:
                return None
            if strict:
                for preferred in _SCHEMA_TYPE_PREFERENCE:
                    if preferred in candidates:
                        return preferred
            return candidates[0]
        return None

    def _provider_tool_name(self, tool_name: str, used_aliases: set[str]) -> str:
        return provider_tool_name(tool_name, used_aliases)

    def _endpoint_path_for_task(self, task: str, default_endpoint_path: str) -> str:
        if task == "embed":
            return "/v1/embeddings"
        return default_endpoint_path

    def _compose_url(self, base_url: str, endpoint_path: str) -> str:
        trimmed_base = base_url.rstrip("/")
        trimmed_path = endpoint_path.lstrip("/")
        if trimmed_path.startswith("v1/") and trimmed_base.endswith("/v1"):
            trimmed_path = trimmed_path[3:]
        return f"{trimmed_base}/{trimmed_path}"

    def _extract_text_content(
        self,
        payload: Mapping[str, Any],
        *,
        request_family: str,
        allow_empty: bool = False,
    ) -> str:
        if request_family == "responses":
            direct_text = payload.get("output_text")
            if isinstance(direct_text, str) and direct_text.strip():
                return direct_text
            output = payload.get("output", ())
            texts: list[str] = []
            if isinstance(output, list):
                for item in output:
                    if not isinstance(item, dict):
                        continue
                    content = item.get("content", ())
                    if isinstance(content, list):
                        for block in content:
                            if not isinstance(block, dict):
                                continue
                            if block.get("type") in {"output_text", "text"}:
                                text = block.get("text")
                                if isinstance(text, str):
                                    texts.append(text)
                    elif isinstance(item.get("text"), str):
                        texts.append(str(item["text"]))
            if texts:
                return "".join(texts)
            if allow_empty:
                return ""
            raise RuntimeError("responses transport returned no assistant text")
        choices = payload.get("choices", ())
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                message = choice.get("message", {})
                if not isinstance(message, dict):
                    continue
                content = message.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    texts = [
                        str(block.get("text", ""))
                        for block in content
                        if isinstance(block, dict) and block.get("text")
                    ]
                    if texts:
                        return "".join(texts)
        if allow_empty:
            return ""
        raise RuntimeError("chat-completions transport returned no assistant text")

    def _extract_text_and_reasoning(
        self,
        payload: Mapping[str, Any],
        *,
        request_family: str,
        allow_empty: bool = False,
    ) -> tuple[str, str]:
        content = self._extract_text_content(
            payload,
            request_family=request_family,
            allow_empty=allow_empty,
        )
        reasoning = self._extract_reasoning_content(payload, request_family=request_family)
        combined = split_reasoning_and_content(content, streaming=False, reasoning=reasoning)
        return combined.content, combined.reasoning

    def _extract_reasoning_content(
        self,
        payload: Mapping[str, Any],
        *,
        request_family: str,
    ) -> str:
        parts: list[str] = []
        if request_family == "responses":
            for key in ("reasoning", "thinking", "reasoning_content", "thinking_content"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    parts.append(value)
                else:
                    parts.append(self._reasoning_text_from_node(value, hinted_reasoning=True))
            output = payload.get("output")
            if isinstance(output, list):
                parts.append(self._reasoning_text_from_node(output, hinted_reasoning=False))
            output_text = payload.get("output_text")
            if isinstance(output_text, str) and output_text.strip():
                parts.append(split_reasoning_and_content(output_text, streaming=False).reasoning)
            return combine_reasoning_text(*parts)
        choices = payload.get("choices", ())
        if not isinstance(choices, list):
            return ""
        for choice in choices:
            if not isinstance(choice, Mapping):
                continue
            message = choice.get("message")
            if not isinstance(message, Mapping):
                continue
            for key in ("reasoning", "reasoning_content", "thinking", "thinking_content"):
                value = message.get(key)
                if isinstance(value, str) and value.strip():
                    parts.append(value)
                else:
                    parts.append(self._reasoning_text_from_node(value, hinted_reasoning=True))
            content = message.get("content")
            if isinstance(content, str):
                parts.append(split_reasoning_and_content(content, streaming=False).reasoning)
            elif isinstance(content, (list, tuple, Mapping)):
                parts.append(self._reasoning_text_from_node(content, hinted_reasoning=False))
        return combine_reasoning_text(*parts)

    def _reasoning_text_from_node(self, payload: object, *, hinted_reasoning: bool) -> str:
        if isinstance(payload, str):
            if hinted_reasoning:
                return payload.strip()
            return split_reasoning_and_content(payload, streaming=False).reasoning
        if isinstance(payload, Mapping):
            node_type = str(payload.get("type") or "").strip().lower()
            effective_hint = hinted_reasoning or self._is_reasoning_type(node_type)
            parts: list[str] = []
            for key in ("text", "output_text", "reasoning", "reasoning_content", "thinking", "thinking_content"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip() if effective_hint or key != "text" else split_reasoning_and_content(value, streaming=False).reasoning)
                elif isinstance(value, (list, tuple, Mapping)):
                    parts.append(self._reasoning_text_from_node(value, hinted_reasoning=effective_hint or key != "text"))
            content = payload.get("content")
            if isinstance(content, (list, tuple, Mapping, str)):
                parts.append(self._reasoning_text_from_node(content, hinted_reasoning=effective_hint))
            return combine_reasoning_text(*parts)
        if isinstance(payload, (list, tuple)):
            return combine_reasoning_text(
                *(self._reasoning_text_from_node(item, hinted_reasoning=hinted_reasoning) for item in payload)
            )
        return ""

    def _is_reasoning_type(self, value: object) -> bool:
        normalized = str(value or "").strip().lower()
        return bool(normalized) and ("reasoning" in normalized or "thinking" in normalized)

    def _extract_tool_calls(
        self,
        payload: Mapping[str, Any],
        *,
        request_family: str,
        tool_name_map: Mapping[str, str] | None = None,
    ) -> tuple[ExecutionToolCall, ...]:
        if request_family != "chat_completions":
            if request_family != "responses":
                return ()
            output = payload.get("output", ())
            if not isinstance(output, list):
                return ()
            calls: list[ExecutionToolCall] = []
            for item in output:
                if not isinstance(item, Mapping):
                    continue
                call = self._tool_call_from_payload(item, tool_name_map=tool_name_map)
                if call is not None:
                    calls.append(call)
                    continue
                content = item.get("content")
                if isinstance(content, list):
                    for block in content:
                        call = self._tool_call_from_payload(block, tool_name_map=tool_name_map)
                        if call is not None:
                            calls.append(call)
            return tuple(calls)
        choices = payload.get("choices", ())
        if not isinstance(choices, list):
            return ()
        calls: list[ExecutionToolCall] = []
        for choice in choices:
            if not isinstance(choice, Mapping):
                continue
            message = choice.get("message")
            if not isinstance(message, Mapping):
                continue
            tool_calls = message.get("tool_calls")
            if isinstance(tool_calls, list):
                for item in tool_calls:
                    call = self._tool_call_from_payload(item, tool_name_map=tool_name_map)
                    if call is not None:
                        calls.append(call)
            function_call = message.get("function_call")
            if isinstance(function_call, Mapping):
                call = self._tool_call_from_payload({"function": function_call}, tool_name_map=tool_name_map)
                if call is not None:
                    calls.append(call)
        return tuple(calls)

    def _merge_chat_stream_tool_calls(
        self,
        payload: Mapping[str, Any],
        collected: dict[int, dict[str, Any]],
    ) -> None:
        choices = payload.get("choices", ())
        if not isinstance(choices, list):
            return
        for choice in choices:
            if not isinstance(choice, Mapping):
                continue
            delta = choice.get("delta")
            if not isinstance(delta, Mapping):
                continue
            tool_calls = delta.get("tool_calls")
            if isinstance(tool_calls, list):
                for fallback_index, item in enumerate(tool_calls):
                    if not isinstance(item, Mapping):
                        continue
                    index = self._stream_tool_call_index(item.get("index"), fallback=fallback_index)
                    current = collected.setdefault(index, {"function": {"name": "", "arguments": ""}})
                    self._merge_stream_tool_call_item(current, item)
            function_call = delta.get("function_call")
            if isinstance(function_call, Mapping):
                current = collected.setdefault(0, {"function": {"name": "", "arguments": ""}})
                self._merge_stream_tool_call_item(current, {"function": function_call})

    def _stream_tool_call_index(self, raw_index: object, *, fallback: int) -> int:
        try:
            return int(raw_index)
        except (TypeError, ValueError):
            return fallback

    def _merge_stream_tool_call_item(self, current: dict[str, Any], item: Mapping[str, object]) -> None:
        item_id = item.get("id")
        if isinstance(item_id, str) and item_id.strip():
            current["id"] = item_id
        item_type = item.get("type")
        if isinstance(item_type, str) and item_type.strip():
            current["type"] = item_type
        function = item.get("function")
        if not isinstance(function, Mapping):
            return
        current_function = current.setdefault("function", {"name": "", "arguments": ""})
        if not isinstance(current_function, dict):
            current_function = {"name": "", "arguments": ""}
            current["function"] = current_function
        name = function.get("name")
        if isinstance(name, str) and name:
            existing_name = str(current_function.get("name") or "")
            current_function["name"] = name if not existing_name or existing_name == name else f"{existing_name}{name}"
        arguments = function.get("arguments")
        if isinstance(arguments, str) and arguments:
            current_function["arguments"] = f"{current_function.get('arguments') or ''}{arguments}"

    def _chat_stream_tool_calls(
        self,
        collected: Mapping[int, Mapping[str, Any]],
        *,
        tool_name_map: Mapping[str, str] | None = None,
    ) -> tuple[ExecutionToolCall, ...]:
        calls: list[ExecutionToolCall] = []
        for index in sorted(collected):
            call = self._tool_call_from_payload(collected[index], tool_name_map=tool_name_map)
            if call is not None:
                calls.append(call)
        return tuple(calls)

    def _tool_call_from_payload(
        self,
        payload: object,
        *,
        tool_name_map: Mapping[str, str] | None = None,
    ) -> ExecutionToolCall | None:
        if not isinstance(payload, Mapping):
            return None
        function = payload.get("function")
        if isinstance(function, Mapping):
            name = str(function.get("name") or "").strip()
            arguments = self._tool_arguments_from_payload(function.get("arguments"))
        else:
            payload_type = str(payload.get("type") or "").strip()
            if payload_type and payload_type not in {"function_call", "tool_call", "function"} and "tool" not in payload_type:
                return None
            name = str(payload.get("name") or payload.get("tool_name") or "").strip()
            arguments = self._tool_arguments_from_payload(payload.get("arguments") or payload.get("input"))
        if tool_name_map is not None:
            name = str(tool_name_map.get(name, name)).strip()
        if not name:
            return None
        return ExecutionToolCall(
            tool_name=name,
            arguments=arguments,
            call_id=str(payload.get("id") or payload.get("call_id") or "").strip(),
        )

    def _tool_arguments_from_payload(self, payload: object) -> dict[str, object]:
        if isinstance(payload, Mapping):
            return {str(key): value for key, value in payload.items()}
        if isinstance(payload, str):
            text = payload.strip()
            if not text:
                return {}
            try:
                decoded = json.loads(text)
            except json.JSONDecodeError:
                return {}
            if isinstance(decoded, Mapping):
                return {str(key): value for key, value in decoded.items()}
        return {}

    def _extract_stream_text_delta(
        self,
        payload: Mapping[str, Any],
        *,
        request_family: str,
        event: str | None = None,
    ) -> str:
        if request_family == "responses":
            event_name = str(event or payload.get("type") or "").strip()
            if "output_text.delta" in event_name:
                delta = payload.get("delta")
                return str(delta) if isinstance(delta, str) else ""
            return ""
        if request_family != "chat_completions":
            return ""
        choices = payload.get("choices", ())
        if not isinstance(choices, list):
            return ""
        fragments: list[str] = []
        for choice in choices:
            if not isinstance(choice, Mapping):
                continue
            delta = choice.get("delta")
            if not isinstance(delta, Mapping):
                continue
            content = delta.get("content")
            if isinstance(content, str):
                fragments.append(content)
                continue
            if isinstance(content, list):
                fragments.extend(
                    str(block.get("text", ""))
                    for block in content
                    if isinstance(block, Mapping) and block.get("text") and not self._is_reasoning_type(block.get("type"))
                )
        return "".join(fragments)

    def _extract_stream_reasoning_delta(
        self,
        payload: Mapping[str, Any],
        *,
        request_family: str,
        event: str | None = None,
    ) -> str:
        if request_family == "responses":
            event_name = str(event or payload.get("type") or "").strip().lower()
            if not self._is_reasoning_type(event_name):
                return ""
            direct = payload.get("delta") or payload.get("text") or payload.get("output_text")
            if isinstance(direct, str) and direct != "":
                return direct
            return self._reasoning_text_from_node(payload, hinted_reasoning=True)
        if request_family != "chat_completions":
            return ""
        choices = payload.get("choices", ())
        if not isinstance(choices, list):
            return ""
        parts: list[str] = []
        for choice in choices:
            if not isinstance(choice, Mapping):
                continue
            delta = choice.get("delta")
            if not isinstance(delta, Mapping):
                continue
            for key in ("reasoning", "reasoning_content", "thinking", "thinking_content"):
                value = delta.get(key)
                if isinstance(value, str) and value.strip():
                    parts.append(value)
                else:
                    parts.append(self._reasoning_text_from_node(value, hinted_reasoning=True))
            content = delta.get("content")
            if isinstance(content, (list, tuple, Mapping)):
                parts.append(self._reasoning_text_from_node(content, hinted_reasoning=False))
        return combine_reasoning_text(*parts)

    def _emit_stream_delta(self, delta: str, *, reasoning: bool) -> None:
        if self.stream_observer is None or not delta:
            return
        self.stream_observer(self._stream_reasoning_marker(delta) if reasoning else delta)

    def _stream_reasoning_marker(self, delta: str) -> str:
        return f"<think>{delta}</think>"

    def _responses_stream_response_payload(
        self,
        payload: Mapping[str, Any],
        *,
        collected_output: list[Mapping[str, Any]],
        text_parts: list[str],
    ) -> Mapping[str, Any]:
        response_payload = payload.get("response")
        if isinstance(response_payload, Mapping):
            synthesized: dict[str, Any] = {str(key): value for key, value in response_payload.items()}
        else:
            synthesized = {}
        response_id = payload.get("id")
        if isinstance(response_id, str):
            synthesized["id"] = response_id
        response_model = payload.get("model")
        if isinstance(response_model, str):
            synthesized["model"] = response_model
        existing_output = synthesized.get("output")
        if collected_output and not (isinstance(existing_output, list) and existing_output):
            synthesized["output"] = list(collected_output)
        existing_output_text = synthesized.get("output_text")
        if text_parts and not (isinstance(existing_output_text, str) and existing_output_text.strip()):
            synthesized["output_text"] = "".join(text_parts)
        usage_payload = payload.get("usage")
        if isinstance(usage_payload, Mapping):
            synthesized["usage"] = dict(usage_payload)
        return synthesized

    def _extract_embeddings(self, payload: Mapping[str, Any]) -> tuple[tuple[float, ...], ...]:
        data = payload.get("data", ())
        if not isinstance(data, list):
            raise RuntimeError("embedding response did not include a data list")
        embeddings: list[tuple[float, ...]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            vector = item.get("embedding", ())
            if isinstance(vector, list):
                embeddings.append(tuple(float(value) for value in vector))
        if not embeddings:
            raise RuntimeError("embedding response did not include vectors")
        return tuple(embeddings)

    def _usage_from_payload(self, payload: Mapping[str, Any]) -> ModelUsage:
        return openai_compatible_usage_from_payload(payload)
