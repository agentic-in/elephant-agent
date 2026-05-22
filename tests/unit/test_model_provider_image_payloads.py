from __future__ import annotations

import base64
from pathlib import Path
import unittest

from packages.contracts.runtime import PromptMessage
from packages.models.runtime import ModelRequest
from packages.models.providers.anthropic import AnthropicContentBlock, AnthropicMessageTurn, AnthropicMessagesRequest
from packages.models.providers.message_payloads import (
    openai_chat_messages_payload,
    openai_responses_input_payload,
    split_text_and_image_parts,
)
from packages.models.providers.openai_compatible import OpenAICompatibleProviderAdapter, OpenAICompatibleProviderConfig


class ModelProviderImagePayloadTests(unittest.TestCase):
    def test_openai_chat_payload_converts_image_reference_to_data_url(self) -> None:
        path = self._write_image("clip.png", b"png-bytes")
        payload = openai_chat_messages_payload(
            (PromptMessage(role="user", content=f"what is this?\n\n@image:{path}"),),
            tool_name_map={},
        )

        content = payload[0]["content"]
        self.assertIsInstance(content, list)
        self.assertEqual(content[0], {"type": "text", "text": "what is this?"})
        self.assertEqual(content[1]["type"], "image_url")
        self.assertEqual(content[1]["image_url"]["url"], self._data_url("image/png", b"png-bytes"))

    def test_openai_responses_payload_uses_input_image_parts(self) -> None:
        path = self._write_image("photo.jpg", b"jpeg-bytes")
        payload = openai_responses_input_payload(
            (PromptMessage(role="user", content=f"describe\n@image:{path}"),),
            tool_name_map={},
        )

        content = payload[0]["content"]
        self.assertEqual(content[0], {"type": "input_text", "text": "describe"})
        self.assertEqual(content[1]["type"], "input_image")
        self.assertEqual(content[1]["detail"], "auto")
        self.assertEqual(content[1]["image_url"], self._data_url("image/jpeg", b"jpeg-bytes"))

    def test_missing_image_reference_stays_in_text(self) -> None:
        text, images = split_text_and_image_parts("@image:/tmp/does-not-exist.png")

        self.assertEqual(text, "@image:/tmp/does-not-exist.png")
        self.assertEqual(images, ())

    def test_anthropic_request_can_render_image_content_block(self) -> None:
        encoded = base64.b64encode(b"png-bytes").decode("ascii")
        request = AnthropicMessagesRequest(
            request_id="r1",
            provider_id="anthropic",
            transport_id="anthropic_messages",
            request_family="anthropic_messages",
            model_id="claude-vision",
            base_url="https://api.anthropic.com/v1",
            endpoint_path="/v1/messages",
            headers={},
            system="",
            messages=(
                AnthropicMessageTurn(
                    role="user",
                    content=(
                        AnthropicContentBlock(type="text", text="look"),
                        AnthropicContentBlock(
                            type="image",
                            text="",
                            source={"type": "base64", "media_type": "image/png", "data": encoded},
                        ),
                    ),
                ),
            ),
            max_tokens=1024,
        )

        content = request.as_mapping()["messages"][0]["content"]
        self.assertEqual(content[0], {"type": "text", "text": "look"})
        self.assertEqual(
            content[1],
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": encoded}},
        )

    def test_minimax_openai_default_uses_bearer_chat_completions(self) -> None:
        adapter = OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id="minimax",
                base_url="https://api.minimaxi.com/v1",
                model_id="MiniMax-M2.7",
            )
        )
        plan = adapter.plan_request(
            ModelRequest(
                request_id="r1",
                profile_id="p1",
                session_id="s1",
                provider_id="minimax",
                model_id="MiniMax-M2.7",
                prompt="hello",
            ),
            credentials={"api_key": "mini-key"},
        )

        self.assertEqual(plan.transport_id, "openai_chat_compatible")
        self.assertEqual(plan.request_family, "chat_completions")
        self.assertEqual(plan.url, "https://api.minimaxi.com/v1/chat/completions")
        self.assertEqual(plan.headers["Authorization"], "Bearer mini-key")
        self.assertNotIn("x-api-key", {key.lower(): value for key, value in plan.headers.items()})

    def test_minimax_openai_keeps_image_paths_for_mcp_image_tools(self) -> None:
        path = self._write_image("clip.png", b"png-bytes")
        adapter = OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id="minimax",
                base_url="https://api.minimaxi.com/v1",
                model_id="MiniMax-M2.7",
            )
        )

        plan = adapter.plan_request(
            ModelRequest(
                request_id="r1",
                profile_id="p1",
                session_id="s1",
                provider_id="minimax",
                model_id="MiniMax-M2.7",
                prompt=f"describe\n@image:{path}",
                tools=(
                    {
                        "type": "function",
                        "function": {
                            "name": "mcp__MiniMax__understand_image",
                            "description": "Understand images",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    },
                ),
            ),
            credentials={"api_key": "mini-key"},
        )

        messages = plan.payload["messages"]
        self.assertIn("understand_image", messages[0]["content"])
        self.assertEqual(messages[1]["role"], "user")
        self.assertIsInstance(messages[1]["content"], str)
        self.assertIn(f"@image:{path}", messages[1]["content"])
        self.assertNotIn("data:image", str(plan.payload))

    def _write_image(self, name: str, data: bytes) -> Path:
        path = Path(self.id().replace(".", "_")).with_suffix("")
        path.mkdir(exist_ok=True)
        target = path / name
        target.write_bytes(data)
        self.addCleanup(lambda: path.rmdir())
        self.addCleanup(lambda: target.unlink(missing_ok=True))
        return target.resolve()

    @staticmethod
    def _data_url(mime_type: str, data: bytes) -> str:
        return f"data:{mime_type};base64,{base64.b64encode(data).decode('ascii')}"


if __name__ == "__main__":
    unittest.main()
