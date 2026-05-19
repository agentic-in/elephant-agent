"""Role-preserved prompt message helpers for CLI snapshot state."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from packages.contracts.runtime import EventEnvelope, ExecutionResult, PromptMessage


def session_history_messages(
    *,
    event: EventEnvelope | None,
    execution: ExecutionResult | None,
    delivery: ExecutionResult | None,
    is_user_turn: bool,
) -> tuple[PromptMessage, ...]:
    if event is None or execution is None or not is_user_turn:
        return ()
    messages: list[PromptMessage] = []
    message = (
        str(event.payload.get("message") or event.payload.get("content") or event.payload.get("summary") or "").strip()
        if isinstance(event.payload, Mapping)
        else ""
    )
    if message:
        messages.append(PromptMessage(role="user", content=message))
    summary = execution.summary.strip()
    if summary:
        messages.append(PromptMessage(role="assistant", content=summary))
    if delivery is not None and delivery.summary.strip():
        messages.append(
            PromptMessage(
                role="assistant",
                content=delivery.summary.strip(),
                metadata={"source": "delivery"},
            )
        )
    return tuple(messages)


def prompt_message_payload(message: PromptMessage) -> dict[str, Any]:
    return {
        "role": message.role,
        "content": message.content,
        "name": message.name,
        "tool_call_id": message.tool_call_id,
        "tool_name": message.tool_name,
        "tool_calls": [dict(call) for call in message.tool_calls if isinstance(call, Mapping)],
        "metadata": dict(message.metadata),
    }


def prompt_messages_tuple(value: Any) -> tuple[PromptMessage, ...]:
    messages: list[PromptMessage] = []
    if isinstance(value, (list, tuple)):
        for item in value:
            if not isinstance(item, Mapping):
                continue
            role = str(item.get("role") or "").strip().lower()
            content = str(item.get("content") or "")
            if role not in {"system", "user", "assistant", "tool"}:
                continue
            tool_calls_payload = item.get("tool_calls")
            tool_calls = (
                tuple(
                    {str(key): value for key, value in call.items()}
                    for call in tool_calls_payload
                    if isinstance(call, Mapping)
                )
                if isinstance(tool_calls_payload, (list, tuple))
                else ()
            )
            metadata_payload = item.get("metadata")
            messages.append(
                PromptMessage(
                    role=role,
                    content=content,
                    name=str(item.get("name") or "").strip(),
                    tool_call_id=str(item.get("tool_call_id") or "").strip(),
                    tool_name=str(item.get("tool_name") or "").strip(),
                    tool_calls=tool_calls,
                    metadata=(
                        {str(key): str(value) for key, value in metadata_payload.items()}
                        if isinstance(metadata_payload, Mapping)
                        else {}
                    ),
                )
            )
    return tuple(messages)
