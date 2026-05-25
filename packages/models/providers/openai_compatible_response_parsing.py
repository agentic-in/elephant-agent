"""Response parsing helpers for OpenAI-compatible provider adapters."""

from __future__ import annotations

import json
from typing import Any, Mapping

from packages.contracts.runtime import ExecutionToolCall

from ..reasoning_parser import combine_reasoning_text, split_reasoning_and_content
from ..runtime import ModelUsage
from .openai_usage import openai_compatible_usage_from_payload


class OpenAICompatibleResponseParsingMixin:
    """Parse OpenAI-compatible text, reasoning, tool, and embedding payloads."""

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
                    parts.append(
                        value.strip()
                        if effective_hint or key != "text"
                        else split_reasoning_and_content(value, streaming=False).reasoning
                    )
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
