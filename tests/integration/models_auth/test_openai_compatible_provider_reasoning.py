from __future__ import annotations

from tests.integration.models_auth.openai_compatible_provider_test_base import (
    ModelRequest,
    OpenAICompatibleProviderAdapter,
    OpenAICompatibleProviderConfig,
    OpenAICompatibleProviderTestBase,
    ProviderRuntimeResolver,
    _ChatSplitTaggedReasoningStreamTransport,
    _ChatTaggedReasoningTransport,
    _ResponsesFragmentedReasoningStreamTransport,
    _ResponsesReasoningStreamTransport,
    _ResponsesWordFragmentReasoningStreamTransport,
    _StaticCredentialSource,
    split_reasoning_and_content,
)


class OpenAICompatibleProviderReasoningTests(OpenAICompatibleProviderTestBase):
    def test_chat_stream_reasoning_tags_split_across_content_deltas_are_not_visible(
        self,
    ) -> None:
        streamed: list[str] = []
        transport = _ChatSplitTaggedReasoningStreamTransport()
        adapter = OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id="minimax",
                base_url="https://api.minimaxi.com/v1",
                model_id="MiniMax-M2.7",
            ),
            runtime_resolver=ProviderRuntimeResolver.default(),
            credential_source=_StaticCredentialSource(
                {"minimax": {"api_key": "sk-minimax-123"}}
            ),
            http_transport=transport,
            stream_observer=streamed.append,
        )
        request = ModelRequest(
            request_id="request-chat-split-tagged-reasoning-stream",
            profile_id="profile-companion",
            session_id="session-chat-split-tagged-reasoning-stream",
            provider_id="minimax",
            model_id="MiniMax-M2.7",
            prompt="你好。请只回复两个字：你好",
        )

        result = adapter.generate(request, {"api_key": "sk-minimax-123"})

        self.assertEqual(
            result.reasoning,
            'The user is asking me to reply with only two characters: "你好".',
        )
        self.assertEqual(result.content, "\n\n你好")
        self.assertNotIn("The user is asking", result.content)
        self.assertEqual(
            streamed,
            [
                '<think>The user is asking me to reply with only two characters: "你好".</think>',
                "\n\n你好",
            ],
        )
        self.assertTrue(bool(transport.stream_payloads[0]["stream"]))

    def test_responses_stream_reasoning_is_split_from_final_answer(self) -> None:
        streamed: list[str] = []
        transport = _ResponsesReasoningStreamTransport()
        adapter = OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id="openai",
                base_url="https://api.openai.example/v1",
                model_id="gpt-5.4",
            ),
            runtime_resolver=ProviderRuntimeResolver.default(),
            credential_source=_StaticCredentialSource(
                {"openai": {"api_key": "sk-openai-123"}}
            ),
            http_transport=transport,
            stream_observer=streamed.append,
        )
        request = ModelRequest(
            request_id="request-responses-stream-reasoning",
            profile_id="profile-companion",
            session_id="session-responses-stream-reasoning",
            provider_id="openai",
            model_id="gpt-5.4",
            prompt="Think carefully before answering.",
            reasoning_effort="high",
        )

        result = adapter.generate(request, {"api_key": "sk-openai-123"})

        self.assertEqual(result.reasoning, "Inspect the latest release state first.")
        self.assertEqual(result.content, "The release note draft is ready.")
        self.assertEqual(
            streamed,
            [
                "<think>Inspect the latest release state first.</think>",
                "The release note draft is ready.",
            ],
        )
        self.assertTrue(bool(transport.stream_payloads[0]["stream"]))

    def test_responses_stream_reasoning_collapses_fragmented_newlines_without_breaking_mixed_language_text(
        self,
    ) -> None:
        streamed: list[str] = []
        adapter = OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id="openai",
                base_url="https://api.openai.example/v1",
                model_id="gpt-5.4",
            ),
            runtime_resolver=ProviderRuntimeResolver.default(),
            credential_source=_StaticCredentialSource(
                {"openai": {"api_key": "sk-openai-123"}}
            ),
            http_transport=_ResponsesFragmentedReasoningStreamTransport(),
            stream_observer=streamed.append,
        )
        request = ModelRequest(
            request_id="request-responses-fragmented-reasoning",
            profile_id="profile-companion",
            session_id="session-responses-fragmented-reasoning",
            provider_id="openai",
            model_id="gpt-5.4",
            prompt="Think carefully before answering.",
            reasoning_effort="high",
        )

        result = adapter.generate(request, {"api_key": "sk-openai-123"})

        self.assertEqual(result.reasoning, "先看release notes。 Then verify")
        self.assertEqual(result.content, "结论已经确认。")
        streamed_combined = split_reasoning_and_content(
            "".join(streamed), streaming=True
        )
        self.assertEqual(streamed_combined.reasoning, "先看release notes。 Then verify")
        self.assertEqual(streamed_combined.content, "结论已经确认。")

    def test_responses_stream_reasoning_prioritizes_spaces_and_uses_completed_reasoning_when_available(
        self,
    ) -> None:
        streamed: list[str] = []
        adapter = OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id="openai",
                base_url="https://api.openai.example/v1",
                model_id="gpt-5.4",
            ),
            runtime_resolver=ProviderRuntimeResolver.default(),
            credential_source=_StaticCredentialSource(
                {"openai": {"api_key": "sk-openai-123"}}
            ),
            http_transport=_ResponsesWordFragmentReasoningStreamTransport(),
            stream_observer=streamed.append,
        )
        request = ModelRequest(
            request_id="request-responses-word-fragment-reasoning",
            profile_id="profile-companion",
            session_id="session-responses-word-fragment-reasoning",
            provider_id="openai",
            model_id="gpt-5.4",
            prompt="Think carefully before answering.",
            reasoning_effort="high",
        )

        result = adapter.generate(request, {"api_key": "sk-openai-123"})

        self.assertEqual(result.reasoning, "The user asked about Xunzhuo in Chengdu.")
        self.assertEqual(result.content, "I can answer naturally now.")
        streamed_combined = split_reasoning_and_content(
            "".join(streamed), streaming=True
        )
        self.assertEqual(
            streamed_combined.reasoning, "The user asked about X un zhuo in Cheng du."
        )
        self.assertEqual(streamed_combined.content, "I can answer naturally now.")

    def test_chat_transport_strips_tagged_reasoning_from_final_content(self) -> None:
        adapter = OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id="openai-compatible",
                base_url="https://api.openai.example/v1",
                model_id="openai/gpt-4o-mini",
            ),
            runtime_resolver=ProviderRuntimeResolver.default(),
            credential_source=_StaticCredentialSource(
                {"openai-compatible": {"api_key": "sk-openai-123"}}
            ),
            http_transport=_ChatTaggedReasoningTransport(),
        )
        request = ModelRequest(
            request_id="request-chat-tagged-reasoning",
            profile_id="profile-companion",
            session_id="session-chat-tagged-reasoning",
            provider_id="openai-compatible",
            model_id="openai/gpt-4o-mini",
            prompt="Give the latest update.",
        )

        result = adapter.generate(request, {"api_key": "sk-openai-123"})

        self.assertEqual(result.reasoning, "Inspect the latest release state first.")
        self.assertEqual(result.content, "The release note draft is ready.")


if __name__ == "__main__":
    import unittest

    unittest.main()
