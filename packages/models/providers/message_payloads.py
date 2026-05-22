"""Provider message payload helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import base64
from hashlib import sha256
import json
import mimetypes
from pathlib import Path

from packages.contracts.runtime import PromptMessage

_MAX_INLINE_IMAGE_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ImagePromptPart:
    mime_type: str
    data: str

    @property
    def data_url(self) -> str:
        return f"data:{self.mime_type};base64,{self.data}"


def openai_chat_messages_payload(
    messages: tuple[PromptMessage, ...],
    *,
    tool_name_map: Mapping[str, str],
    image_references_as_text: bool = False,
) -> list[dict[str, object]]:
    return [
        payload
        for message in messages
        if (
            payload := _openai_chat_message_payload(
                message,
                tool_name_map=tool_name_map,
                image_references_as_text=image_references_as_text,
            )
        )
    ]


def openai_responses_input_payload(
    messages: tuple[PromptMessage, ...],
    *,
    tool_name_map: Mapping[str, str],
    image_references_as_text: bool = False,
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
                        "call_id": _provider_call_id(str(message.tool_call_id)),
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
        content = _openai_responses_content(message, role=role, image_references_as_text=image_references_as_text)
        if content:
            payload.append(
                {
                    "role": "assistant" if role == "assistant" else "user",
                    "content": content,
                }
            )
    return payload


def _openai_chat_message_payload(
    message: PromptMessage,
    *,
    tool_name_map: Mapping[str, str],
    image_references_as_text: bool,
) -> dict[str, object]:
    role = str(message.role or "").strip().lower()
    if role not in {"system", "user", "assistant", "tool"}:
        return {}
    payload: dict[str, object] = {"role": role}
    if role == "tool":
        payload["content"] = str(message.content or "")
        if message.tool_call_id:
            payload["tool_call_id"] = _provider_call_id(str(message.tool_call_id))
        return payload
    if role == "user":
        if image_references_as_text:
            payload["content"] = str(message.content or "")
        else:
            content = _openai_chat_user_content(message)
            payload["content"] = content if content else str(message.content or "")
    else:
        payload["content"] = str(message.content or "")
    if role == "assistant" and message.tool_calls:
        payload["tool_calls"] = [
            _openai_chat_tool_call_payload(call, tool_name_map=tool_name_map)
            for call in message.tool_calls
            if isinstance(call, Mapping)
        ]
    return payload


def split_text_and_image_parts(content: str) -> tuple[str, tuple[ImagePromptPart, ...]]:
    """Extract local @image:/path references into base64 image parts."""

    text_lines: list[str] = []
    images: list[ImagePromptPart] = []
    for raw_line in str(content or "").splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("@image:"):
            image_part = _image_prompt_part(stripped.removeprefix("@image:").strip())
            if image_part is not None:
                images.append(image_part)
                continue
        text_lines.append(raw_line)
    return "\n".join(text_lines).strip(), tuple(images)


def prompt_message_has_image_parts(message: PromptMessage) -> bool:
    _text, images = split_text_and_image_parts(str(message.content or ""))
    return bool(images)


def _openai_chat_user_content(message: PromptMessage) -> list[dict[str, object]]:
    text, images = split_text_and_image_parts(str(message.content or ""))
    if not images:
        return []
    content: list[dict[str, object]] = []
    if text:
        content.append({"type": "text", "text": text})
    content.extend(
        {
            "type": "image_url",
            "image_url": {"url": image.data_url},
        }
        for image in images
    )
    return content


def _openai_responses_content(
    message: PromptMessage,
    *,
    role: str,
    image_references_as_text: bool,
) -> list[dict[str, object]]:
    raw_content = str(message.content or "")
    if role != "user":
        text = raw_content.strip()
        return [{"type": "output_text", "text": text}] if text else []
    if image_references_as_text:
        text = raw_content.strip()
        return [{"type": "input_text", "text": text}] if text else []
    text, images = split_text_and_image_parts(raw_content)
    content: list[dict[str, object]] = []
    if text:
        content.append({"type": "input_text", "text": text})
    content.extend(
        {
            "type": "input_image",
            "image_url": image.data_url,
            "detail": "auto",
        }
        for image in images
    )
    return content


def _image_prompt_part(raw_path: str) -> ImagePromptPart | None:
    if not raw_path:
        return None
    path = Path(raw_path).expanduser()
    try:
        path = path.resolve(strict=True)
        if not path.is_file() or path.stat().st_size > _MAX_INLINE_IMAGE_BYTES:
            return None
        mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
        if not mime_type.startswith("image/"):
            return None
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return None
    return ImagePromptPart(mime_type=mime_type, data=encoded)


def _openai_chat_tool_call_payload(
    call: Mapping[str, object],
    *,
    tool_name_map: Mapping[str, str],
) -> dict[str, object]:
    call_id = str(call.get("id") or call.get("call_id") or "").strip() or "call_context"
    call_id = _provider_call_id(call_id)
    name = _provider_tool_alias_for_message(str(call.get("name") or call.get("tool_name") or ""), tool_name_map=tool_name_map)
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
    call_id = _provider_call_id(call_id)
    name = _provider_tool_alias_for_message(str(call.get("name") or call.get("tool_name") or ""), tool_name_map=tool_name_map)
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


def _provider_call_id(call_id: str) -> str:
    normalized = str(call_id or "").strip() or "call_context"
    if len(normalized) <= 64:
        return normalized
    digest = sha256(normalized.encode("utf-8")).hexdigest()[:23]
    return f"{normalized[:40]}-{digest}"


def _tool_call_arguments(arguments: object) -> str:
    if isinstance(arguments, str):
        return arguments
    payload = arguments if isinstance(arguments, Mapping) else {}
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)
