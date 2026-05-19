"""Provider message payload helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping

from packages.contracts.runtime import PromptMessage


def openai_chat_messages_payload(
    messages: tuple[PromptMessage, ...],
    *,
    tool_name_map: Mapping[str, str],
) -> list[dict[str, object]]:
    return [
        payload
        for message in messages
        if (payload := _openai_chat_message_payload(message, tool_name_map=tool_name_map))
    ]


def openai_responses_input_payload(
    messages: tuple[PromptMessage, ...],
    *,
    tool_name_map: Mapping[str, str],
) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for message in messages:
        role = str(message.role or "").strip().lower()
        if role == "system":
            continue
        if role == "tool":
            if message.tool_call_id:
                payload.append(
                    {
                        "type": "function_call_output",
                        "call_id": message.tool_call_id,
                        "output": str(message.content or ""),
                    }
                )
            continue
        if role == "assistant" and message.tool_calls:
            for call in message.tool_calls:
                if isinstance(call, Mapping):
                    payload.append(_openai_responses_function_call_payload(call, tool_name_map=tool_name_map))
            if not str(message.content or "").strip():
                continue
        payload.append(
            {
                "role": "assistant" if role == "assistant" else "user",
                "content": [
                    {
                        "type": "output_text" if role == "assistant" else "input_text",
                        "text": str(message.content or ""),
                    }
                ],
            }
        )
    return payload


def _openai_chat_message_payload(
    message: PromptMessage,
    *,
    tool_name_map: Mapping[str, str],
) -> dict[str, object]:
    role = str(message.role or "").strip().lower()
    if role not in {"system", "user", "assistant", "tool"}:
        return {}
    payload: dict[str, object] = {"role": role}
    if role == "tool":
        payload["content"] = str(message.content or "")
        if message.tool_call_id:
            tool_call_id = str(message.tool_call_id)
            payload["tool_call_id"] = tool_call_id[:64] if len(tool_call_id) > 64 else tool_call_id
        return payload
    payload["content"] = str(message.content or "")
    if role == "assistant" and message.tool_calls:
        payload["tool_calls"] = [
            _openai_chat_tool_call_payload(call, tool_name_map=tool_name_map)
            for call in message.tool_calls
            if isinstance(call, Mapping)
        ]
    return payload


def _openai_chat_tool_call_payload(
    call: Mapping[str, object],
    *,
    tool_name_map: Mapping[str, str],
) -> dict[str, object]:
    call_id = str(call.get("id") or call.get("call_id") or "").strip() or "call_context"
    if len(call_id) > 64:
        call_id = call_id[:64]
    name = _provider_tool_alias_for_message(
        str(call.get("name") or call.get("tool_name") or ""),
        tool_name_map=tool_name_map,
    )
    arguments = _tool_call_arguments(call.get("arguments"))
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": arguments,
        },
    }


def _openai_responses_function_call_payload(
    call: Mapping[str, object],
    *,
    tool_name_map: Mapping[str, str],
) -> dict[str, object]:
    call_id = str(call.get("id") or call.get("call_id") or "").strip() or "call_context"
    if len(call_id) > 64:
        call_id = call_id[:64]
    name = _provider_tool_alias_for_message(
        str(call.get("name") or call.get("tool_name") or ""),
        tool_name_map=tool_name_map,
    )
    return {
        "type": "function_call",
        "call_id": call_id,
        "name": name,
        "arguments": _tool_call_arguments(call.get("arguments")),
    }


def _provider_tool_alias_for_message(tool_name: str, *, tool_name_map: Mapping[str, str]) -> str:
    normalized = str(tool_name or "").strip()
    if not normalized:
        return "tool_context"
    inverse = {original: alias for alias, original in tool_name_map.items()}
    return inverse.get(normalized, normalized)


def _tool_call_arguments(arguments: object) -> str:
    if isinstance(arguments, str):
        return arguments
    payload = arguments if isinstance(arguments, Mapping) else {}
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)
