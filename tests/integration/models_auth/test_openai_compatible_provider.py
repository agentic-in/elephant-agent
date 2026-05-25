from __future__ import annotations

import unittest

from tests.integration.models_auth.openai_compatible_provider_test_base import (
    ModelRequest,
    OpenAICompatibleProviderAdapter,
    OpenAICompatibleProviderConfig,
    OpenAICompatibleProviderTestBase,
    PromptMessage,
    ProviderRuntimeResolver,
    _StaticCredentialSource,
)


class OpenAICompatibleProviderTests(OpenAICompatibleProviderTestBase):
    def test_plans_chat_requests_with_custom_base_url_and_headers(self) -> None:
        adapter = OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id="openai-compatible",
                base_url=self.server.openai_base_url,
                model_id="openai/gpt-4o-mini",
                extra_headers={"x-tenant": "elephant"},
            ),
            runtime_resolver=ProviderRuntimeResolver.default(),
            credential_source=_StaticCredentialSource(
                {"openai-compatible": {"api_key": "sk-test-123"}}
            ),
        )
        request = ModelRequest(
            request_id="request-1",
            profile_id="profile-companion",
            session_id="session-1",
            provider_id="openai-compatible",
            model_id="openai/gpt-4o-mini",
            prompt="Summarize the provider runtime.",
            metadata={"trace_id": "trace-123"},
        )

        plan = adapter.plan_request(request)
        result = adapter.generate(request, {"api_key": "sk-test-123"})

        self.assertEqual(plan.url, self.server.openai_base_url + "/chat/completions")
        self.assertEqual(plan.request_family, "chat_completions")
        self.assertEqual(plan.transport_id, "openai_chat_compatible")
        self.assertEqual(plan.headers["Authorization"], "Bearer sk-test-123")
        self.assertEqual(plan.headers["x-tenant"], "elephant")
        self.assertEqual(plan.headers["x-session-id"], "session-1")
        self.assertEqual(plan.payload["model"], "openai/gpt-4o-mini")
        self.assertEqual(plan.payload["messages"][0]["role"], "system")
        self.assertIn(
            "#### Understanding System", plan.payload["messages"][0]["content"]
        )
        self.assertIn(
            "You are the active Elephant Agent identity",
            plan.payload["messages"][0]["content"],
        )
        self.assertIn("#### Episode Continuity", plan.payload["messages"][0]["content"])
        self.assertIn(
            "Stay truthful and bounded", plan.payload["messages"][0]["content"]
        )
        self.assertIn("#### Session Work", plan.payload["messages"][0]["content"])
        self.assertIn(
            "#### Understanding tools", plan.payload["messages"][0]["content"]
        )
        self.assertEqual(plan.payload["messages"][1]["role"], "user")
        self.assertEqual(plan.payload["messages"][1]["content"], request.prompt)
        self.assertNotIn("metadata", plan.payload)
        self.assertEqual(result.task, "generate")
        self.assertEqual(result.content, "live-chat:Summarize the provider runtime.")
        self.assertEqual(result.usage.cached_prompt_tokens, 4)
        self.assertTrue(result.usage.cache_usage_reported)
        self.assertNotIn("sk-test-123", result.content)
        self.assertEqual(self.server.requests[0]["path"], "/v1/chat/completions")
        self.assertEqual(
            self.server.requests[0]["headers"]["Authorization"], "Bearer sk-test-123"
        )
        request_headers = {
            str(key).lower(): str(value)
            for key, value in dict(self.server.requests[0]["headers"]).items()
        }
        self.assertEqual(request_headers["x-session-id"], "session-1")
        self.assertNotIn("metadata", self.server.requests[0]["payload"])
        self.assertFalse(plan.payload["stream"])

    def test_session_header_does_not_override_explicit_extra_header(self) -> None:
        adapter = OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id="openai-compatible",
                base_url=self.server.openai_base_url,
                model_id="openai/gpt-4o-mini",
                extra_headers={"X-Session-Id": "configured-session"},
            ),
            runtime_resolver=ProviderRuntimeResolver.default(),
        )
        request = ModelRequest(
            request_id="request-explicit-session-header",
            profile_id="profile-companion",
            session_id="runtime-session",
            provider_id="openai-compatible",
            model_id="openai/gpt-4o-mini",
            prompt="Respect explicit headers.",
        )

        plan = adapter.plan_request(request)

        self.assertEqual(plan.headers["X-Session-Id"], "configured-session")
        self.assertNotIn("x-session-id", plan.headers)

    def test_usage_accepts_openai_compatible_cache_token_aliases(self) -> None:
        adapter = OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id="openai-compatible",
                base_url=self.server.openai_base_url,
                model_id="openai/gpt-4o-mini",
            ),
            runtime_resolver=ProviderRuntimeResolver.default(),
        )

        usage = adapter._usage_from_payload(
            {
                "usage": {
                    "input_tokens": 12,
                    "output_tokens": 4,
                    "total_tokens": 16,
                    "cache_read_input_tokens": 6,
                    "cache_write_input_tokens": 2,
                }
            }
        )

        self.assertEqual(usage.prompt_tokens, 12)
        self.assertEqual(usage.completion_tokens, 4)
        self.assertEqual(usage.cached_prompt_tokens, 6)
        self.assertEqual(usage.cache_creation_prompt_tokens, 2)
        self.assertTrue(usage.cache_usage_reported)

    def test_chat_requests_accept_base_url_without_v1_suffix(self) -> None:
        root_base_url = self.server.openai_base_url.removesuffix("/v1")
        adapter = OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id="openai-compatible",
                base_url=root_base_url,
                model_id="openai/gpt-4o-mini",
            ),
            runtime_resolver=ProviderRuntimeResolver.default(),
            credential_source=_StaticCredentialSource(
                {"openai-compatible": {"api_key": "sk-test-123"}}
            ),
        )
        request = ModelRequest(
            request_id="request-root-base",
            profile_id="profile-her",
            session_id="session-root-base",
            provider_id="openai-compatible",
            model_id="openai/gpt-4o-mini",
            prompt="Use the root endpoint.",
        )

        plan = adapter.plan_request(request)
        result = adapter.generate(request, {"api_key": "sk-test-123"})

        self.assertEqual(plan.url, root_base_url + "/v1/chat/completions")
        self.assertEqual(self.server.requests[-1]["path"], "/v1/chat/completions")
        self.assertEqual(result.content, "live-chat:Use the root endpoint.")

    def test_rendered_prompt_is_forwarded_without_provider_guardrail_prepended(
        self,
    ) -> None:
        adapter = OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id="openai-compatible",
                base_url=self.server.openai_base_url,
                model_id="openai/gpt-4o-mini",
            ),
            runtime_resolver=ProviderRuntimeResolver.default(),
            credential_source=_StaticCredentialSource(
                {"openai-compatible": {"api_key": "sk-test-123"}}
            ),
        )
        request = ModelRequest(
            request_id="request-identity",
            profile_id="profile-companion",
            session_id="session-identity",
            provider_id="openai-compatible",
            model_id="openai/gpt-4o-mini",
            prompt="Who are you?",
            context={
                "frozen_prefix_prompt": (
                    "## EpisodeFrozenContext\n"
                    "### System Layer Contract\n"
                    "You are Aeon, the active elephant identity."
                ),
                "session_snapshot_prompt": (
                    "## StateSnapshot\n" "- active current work: keep the State exact"
                ),
                "rendered_prompt": "legacy rendered prompt should not be used when structured sections exist",
            },
        )

        plan = adapter.plan_request(request)

        self.assertEqual(plan.payload["messages"][0]["role"], "system")
        self.assertEqual(
            plan.payload["messages"][0]["content"],
            f"{request.context['frozen_prefix_prompt']}\n\n"
            f"{request.context['session_snapshot_prompt']}",
        )
        self.assertIn("You are Aeon", plan.payload["messages"][0]["content"])
        self.assertNotIn("## LoopContext", plan.payload["messages"][0]["content"])
        self.assertNotIn(
            "OpenAI-compatible provider adapter", plan.payload["messages"][0]["content"]
        )
        self.assertNotIn("credential_keys=", plan.payload["messages"][0]["content"])
        self.assertEqual(
            sum(
                1 for message in plan.payload["messages"] if message["role"] == "system"
            ),
            1,
        )
        self.assertEqual(
            plan.payload["messages"][1]["content"],
            "Who are you?",
        )

    def test_chat_request_flattens_all_system_context_into_one_system_message(
        self,
    ) -> None:
        adapter = OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id="openai-compatible",
                base_url=self.server.openai_base_url,
                model_id="openai/gpt-4o-mini",
            ),
            runtime_resolver=ProviderRuntimeResolver.default(),
        )
        request = ModelRequest(
            request_id="request-single-system",
            profile_id="profile-companion",
            session_id="session-single-system",
            provider_id="openai-compatible",
            model_id="openai/gpt-4o-mini",
            prompt="What should I do next?",
            context={
                "frozen_prefix_prompt": "## EpisodeFrozenContext\n- keep answers exact",
                "session_snapshot_prompt": "## StateSnapshot\n- active current work: simplify prompt assembly",
            },
            messages=(
                PromptMessage(
                    role="system",
                    content="## SessionHistorySummary\n- prior system summary",
                ),
                PromptMessage(role="assistant", content="Earlier reply."),
            ),
        )

        plan = adapter.plan_request(request)

        self.assertEqual(
            [message["role"] for message in plan.payload["messages"]],
            ["system", "assistant", "user"],
        )
        self.assertIn("## EpisodeFrozenContext", plan.payload["messages"][0]["content"])
        self.assertIn("## StateSnapshot", plan.payload["messages"][0]["content"])
        self.assertNotIn("## LoopContext", plan.payload["messages"][0]["content"])
        self.assertNotIn(
            "## WorkspaceAttachments", plan.payload["messages"][0]["content"]
        )
        self.assertIn(
            "## SessionHistorySummary", plan.payload["messages"][0]["content"]
        )
        self.assertEqual(plan.payload["messages"][1]["content"], "Earlier reply.")
        self.assertEqual(
            plan.payload["messages"][2]["content"], "What should I do next?"
        )

    def test_chat_request_preserves_history_and_tool_result_roles(self) -> None:
        adapter = OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id="openai-compatible",
                base_url=self.server.openai_base_url,
                model_id="openai/gpt-4o-mini",
            ),
            runtime_resolver=ProviderRuntimeResolver.default(),
        )
        request = ModelRequest(
            request_id="request-role-history",
            profile_id="profile-companion",
            session_id="session-role-history",
            provider_id="openai-compatible",
            model_id="openai/gpt-4o-mini",
            prompt="Use that result.",
            messages=(
                PromptMessage(role="user", content="Search the docs."),
                PromptMessage(
                    role="assistant",
                    content="",
                    tool_calls=(
                        {
                            "id": "call-1",
                            "name": "tool.web.search",
                            "arguments": {"query": "elephant docs"},
                        },
                    ),
                ),
                PromptMessage(
                    role="tool",
                    content="docs result",
                    tool_call_id="call-1",
                    tool_name="tool.web.search",
                ),
            ),
            tools=(
                {
                    "type": "function",
                    "function": {
                        "name": "tool.web.search",
                        "description": "Search the web.",
                        "parameters": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                        },
                    },
                },
            ),
        )

        plan = adapter.plan_request(request)

        self.assertEqual(
            [message["role"] for message in plan.payload["messages"][-4:]],
            ["user", "assistant", "tool", "user"],
        )
        self.assertEqual(
            plan.payload["messages"][-3]["tool_calls"][0]["function"]["name"],
            "tool_web_search",
        )
        self.assertEqual(plan.payload["messages"][-2]["tool_call_id"], "call-1")
        self.assertEqual(plan.payload["messages"][-1]["content"], "Use that result.")

    def test_embed_requests_use_the_shared_compatible_transport(self) -> None:
        adapter = OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id="openai-compatible",
                base_url=self.server.openai_base_url,
                model_id="text-embedding-3-small",
            ),
            runtime_resolver=ProviderRuntimeResolver.default(),
            credential_source=_StaticCredentialSource(
                {"openai-compatible": {"api_key": "sk-embed-456"}}
            ),
        )
        request = ModelRequest(
            request_id="request-embed",
            profile_id="profile-companion",
            session_id="session-2",
            provider_id="openai-compatible",
            model_id="text-embedding-3-small",
            prompt="Long-term memory retrieval",
            task="embed",
            context={"input": "Long-term memory retrieval"},
        )

        plan = adapter.plan_request(request)
        result = adapter.embed(request, {"api_key": "sk-embed-456"})

        self.assertEqual(plan.endpoint_path, "/v1/embeddings")
        self.assertEqual(plan.url, self.server.openai_base_url + "/embeddings")
        self.assertEqual(plan.payload["input"], "Long-term memory retrieval")
        self.assertEqual(plan.credential_keys, ("api_key",))
        self.assertEqual(result.task, "embed")
        self.assertEqual(result.metadata["endpoint_path"], "/v1/embeddings")
        self.assertEqual(result.metadata["request_family"], "embeddings")
        self.assertEqual(result.embeddings[0], (0.1, 0.2, 0.3, 0.4))

    def test_generate_streams_chat_completions_when_observer_is_present(self) -> None:
        streamed: list[str] = []
        adapter = OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id="openai-compatible",
                base_url=self.server.openai_base_url,
                model_id="openai/gpt-4o-mini",
            ),
            runtime_resolver=ProviderRuntimeResolver.default(),
            credential_source=_StaticCredentialSource(
                {"openai-compatible": {"api_key": "sk-stream-789"}}
            ),
            stream_observer=streamed.append,
        )
        request = ModelRequest(
            request_id="request-stream",
            profile_id="profile-companion",
            session_id="session-stream",
            provider_id="openai-compatible",
            model_id="openai/gpt-4o-mini",
            prompt="Stream the live reply.",
        )

        plan = adapter.plan_request(request)
        result = adapter.generate(request, {"api_key": "sk-stream-789"})

        self.assertTrue(plan.payload["stream"])
        self.assertEqual(result.content, "live-chat:Stream the live reply.")
        self.assertEqual("".join(streamed), result.content)
        self.assertEqual(result.metadata["stream"], "true")

    def test_generate_streams_and_parses_native_tool_calls(self) -> None:
        streamed: list[str] = []
        adapter = OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id="openai-compatible",
                base_url=self.server.openai_base_url,
                model_id="openai/gpt-4o-mini",
            ),
            runtime_resolver=ProviderRuntimeResolver.default(),
            credential_source=_StaticCredentialSource(
                {"openai-compatible": {"api_key": "sk-tools-123"}}
            ),
            stream_observer=streamed.append,
        )
        request = ModelRequest(
            request_id="request-tools",
            profile_id="profile-companion",
            session_id="session-tools",
            provider_id="openai-compatible",
            model_id="openai/gpt-4o-mini",
            prompt="Use tools to continue researching.",
            tools=(
                {
                    "type": "function",
                    "function": {
                        "name": "tool.web.search",
                        "description": "Search the web.",
                        "parameters": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                            "required": ["query"],
                        },
                    },
                },
            ),
        )

        plan = adapter.plan_request(request)
        result = adapter.generate(request, {"api_key": "sk-tools-123"})

        self.assertTrue(plan.payload["stream"])
        self.assertEqual(plan.payload["stream_options"], {"include_usage": True})
        self.assertEqual(
            plan.payload["tools"][0]["function"]["name"], "tool_web_search"
        )
        self.assertEqual(result.content, "")
        self.assertEqual(len(result.tool_calls), 1)
        self.assertEqual(result.tool_calls[0].tool_name, "tool.web.search")
        self.assertEqual(result.tool_calls[0].arguments, {"query": "native tools"})
        self.assertEqual(streamed, [])
        self.assertEqual(result.metadata["stream"], "true")


if __name__ == "__main__":
    unittest.main()
