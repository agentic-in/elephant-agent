from __future__ import annotations

from tests.integration.models_auth.openai_compatible_provider_test_base import (
    ModelRequest,
    OpenAICompatibleProviderAdapter,
    OpenAICompatibleProviderConfig,
    OpenAICompatibleProviderTestBase,
    PromptMessage,
    ProviderRuntimeResolver,
    _ResponsesDoneEventTransport,
    _ResponsesStreamBackfillTransport,
    _StaticCredentialSource,
)


class OpenAICompatibleProviderResponsesTests(OpenAICompatibleProviderTestBase):
    def test_responses_transport_parses_native_tool_calls(self) -> None:
        adapter = OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id="openai",
                base_url=self.server.openai_base_url,
                model_id="gpt-4.1-mini",
            ),
            runtime_resolver=ProviderRuntimeResolver.default(),
            credential_source=_StaticCredentialSource(
                {"openai": {"api_key": "sk-openai-123"}}
            ),
        )
        request = ModelRequest(
            request_id="request-responses-tools",
            profile_id="profile-companion",
            session_id="session-responses-tools",
            provider_id="openai",
            model_id="gpt-4.1-mini",
            prompt="Use tools through responses.",
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
        result = adapter.generate(request, {"api_key": "sk-openai-123"})

        self.assertEqual(plan.endpoint_path, "/v1/responses")
        self.assertEqual(plan.payload["input"][0]["role"], "user")
        self.assertEqual(
            plan.payload["input"][0]["content"][0]["text"],
            "Use tools through responses.",
        )
        self.assertEqual(plan.payload["tools"][0]["name"], "tool_web_search")
        self.assertFalse(plan.payload["store"])
        self.assertEqual(result.content, "")
        self.assertEqual(len(result.tool_calls), 1)
        self.assertEqual(result.tool_calls[0].tool_name, "tool.web.search")
        self.assertEqual(result.tool_calls[0].arguments, {"query": "responses tools"})

    def test_responses_transport_shortens_long_tool_call_ids_consistently(self) -> None:
        adapter = OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id="copilot",
                base_url=self.server.openai_base_url,
                model_id="gpt-5.4",
            ),
            runtime_resolver=ProviderRuntimeResolver.default(),
            credential_source=_StaticCredentialSource(
                {"copilot": {"api_key": "ghu-copilot"}}
            ),
        )
        long_call_id = "call-" + ("x" * 407)
        request = ModelRequest(
            request_id="request-responses-long-call-id",
            profile_id="profile-companion",
            session_id="session-responses-long-call-id",
            provider_id="copilot",
            model_id="gpt-5.4",
            prompt="Use the tool result.",
            messages=(
                PromptMessage(
                    role="assistant",
                    content="",
                    tool_calls=(
                        {
                            "id": long_call_id,
                            "name": "tool.web.search",
                            "arguments": {"query": "responses tools"},
                        },
                    ),
                ),
                PromptMessage(
                    role="tool",
                    content="tool result",
                    tool_call_id=long_call_id,
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
        function_call = next(
            item
            for item in plan.payload["input"]
            if item.get("type") == "function_call"
        )
        function_output = next(
            item
            for item in plan.payload["input"]
            if item.get("type") == "function_call_output"
        )

        self.assertEqual(plan.endpoint_path, "/v1/responses")
        self.assertEqual(function_call["call_id"], function_output["call_id"])
        self.assertLessEqual(len(function_call["call_id"]), 64)
        self.assertNotEqual(function_call["call_id"], long_call_id)
        self.assertTrue(str(function_call["call_id"]).startswith(long_call_id[:40]))

    def test_responses_transport_includes_reasoning_effort_when_supported(self) -> None:
        adapter = OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id="openai",
                base_url=self.server.openai_base_url,
                model_id="gpt-5.4",
            ),
            runtime_resolver=ProviderRuntimeResolver.default(),
            credential_source=_StaticCredentialSource(
                {"openai": {"api_key": "sk-openai-123"}}
            ),
        )
        request = ModelRequest(
            request_id="request-responses-reasoning",
            profile_id="profile-companion",
            session_id="session-responses-reasoning",
            provider_id="openai",
            model_id="gpt-5.4",
            prompt="Think carefully before answering.",
            reasoning_effort="high",
        )

        plan = adapter.plan_request(request)

        self.assertEqual(plan.transport_id, "openai_responses")
        self.assertEqual(plan.payload["reasoning"], {"effort": "high"})
        self.assertTrue(plan.payload["stream"])

    def test_codex_responses_omits_internal_metadata_from_request_payload(self) -> None:
        root_base_url = self.server.openai_base_url.removesuffix("/v1")
        adapter = OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id="openai-codex",
                base_url=root_base_url,
                model_id="gpt-5.4",
            ),
            runtime_resolver=ProviderRuntimeResolver.default(),
            credential_source=_StaticCredentialSource(
                {"openai-codex": {"api_key": "sk-codex-123"}}
            ),
        )
        request = ModelRequest(
            request_id="request-codex-no-metadata",
            profile_id="profile-companion",
            session_id="session-codex-no-metadata",
            provider_id="openai-codex",
            model_id="gpt-5.4",
            prompt="Explain the current runtime status.",
            metadata={"trace_id": "trace-codex-123"},
        )

        plan = adapter.plan_request(request)
        result = adapter.generate(request, {"api_key": "sk-codex-123"})

        self.assertEqual(plan.transport_id, "openai_responses")
        self.assertEqual(plan.endpoint_path, "/responses")
        self.assertNotIn("metadata", plan.payload)
        self.assertEqual(self.server.requests[-1]["path"], "/responses")
        self.assertNotIn("metadata", self.server.requests[-1]["payload"])
        self.assertEqual(
            result.content, "live-response:Explain the current runtime status."
        )

    def test_codex_responses_backfills_completed_response_from_stream_items(
        self,
    ) -> None:
        transport = _ResponsesStreamBackfillTransport()
        adapter = OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id="openai-codex",
                base_url="https://chatgpt.com/backend-api/codex",
                model_id="gpt-5.4",
            ),
            runtime_resolver=ProviderRuntimeResolver.default(),
            credential_source=_StaticCredentialSource(
                {"openai-codex": {"api_key": "sk-codex-123"}}
            ),
            http_transport=transport,
        )
        request = ModelRequest(
            request_id="request-codex-stream-fallback",
            profile_id="profile-companion",
            session_id="session-codex-stream-fallback",
            provider_id="openai-codex",
            model_id="gpt-5.4",
            prompt="Doctor check",
        )

        result = adapter.generate(request, {"api_key": "sk-codex-123"})

        self.assertEqual(adapter.plan_request(request).endpoint_path, "/responses")
        self.assertEqual(result.content, "fallback-response-text")
        self.assertEqual(len(transport.stream_payloads), 1)
        self.assertEqual(len(transport.post_payloads), 0)
        self.assertTrue(bool(transport.stream_payloads[0]["stream"]))
        self.assertEqual(result.metadata["stream"], "true")

    def test_codex_responses_does_not_duplicate_output_text_done_content(self) -> None:
        streamed: list[str] = []
        transport = _ResponsesDoneEventTransport()
        adapter = OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id="openai-codex",
                base_url="https://chatgpt.com/backend-api/codex",
                model_id="gpt-5.4",
            ),
            runtime_resolver=ProviderRuntimeResolver.default(),
            credential_source=_StaticCredentialSource(
                {"openai-codex": {"api_key": "sk-codex-123"}}
            ),
            http_transport=transport,
            stream_observer=streamed.append,
        )
        request = ModelRequest(
            request_id="request-codex-stream-done",
            profile_id="profile-companion",
            session_id="session-codex-stream-done",
            provider_id="openai-codex",
            model_id="gpt-5.4",
            prompt="Say hello once.",
        )

        result = adapter.generate(request, {"api_key": "sk-codex-123"})

        self.assertEqual(result.content, "hello from codex")
        self.assertEqual(streamed, ["hello from codex"])
        self.assertEqual(result.metadata["stream"], "true")

    def test_copilot_sanitizes_tool_schema_for_strict_function_contracts(self) -> None:
        adapter = OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id="copilot",
                base_url=self.server.openai_base_url,
                model_id="gpt-5.4",
            ),
            runtime_resolver=ProviderRuntimeResolver.default(),
            credential_source=_StaticCredentialSource(
                {"copilot": {"api_key": "ghu-test"}}
            ),
        )
        request = ModelRequest(
            request_id="request-copilot-tools",
            profile_id="profile-companion",
            session_id="session-copilot-tools",
            provider_id="copilot",
            model_id="gpt-5.4",
            prompt="Ask a clarification question with choices.",
            tools=(
                {
                    "type": "function",
                    "function": {
                        "name": "tool.clarify",
                        "description": "Ask for clarification.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "question": {"type": "string"},
                                "choices": {"type": ["array", "string"]},
                            },
                            "required": ["question"],
                        },
                    },
                },
            ),
        )

        plan = adapter.plan_request(request)

        self.assertEqual(plan.payload["tools"][0]["name"], "tool_clarify")
        self.assertEqual(
            plan.payload["tools"][0]["parameters"]["properties"]["choices"]["type"],
            "string",
        )

    def test_responses_strict_schema_adds_array_items_for_tool_properties(self) -> None:
        adapter = OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id="openai-codex",
                base_url=self.server.openai_base_url,
                model_id="gpt-5.4",
            ),
            runtime_resolver=ProviderRuntimeResolver.default(),
            credential_source=_StaticCredentialSource(
                {"openai-codex": {"api_key": "sk-codex-123"}}
            ),
        )
        request = ModelRequest(
            request_id="request-codex-tools",
            profile_id="profile-companion",
            session_id="session-codex-tools",
            provider_id="openai-codex",
            model_id="gpt-5.4",
            prompt="Track tool activity.",
            tools=(
                {
                    "type": "function",
                    "function": {
                        "name": "tool.todo.manage",
                        "description": "Manage an execution todo board.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "action": {"type": "string"},
                                "notes": {"type": "string"},
                            },
                            "required": ["action"],
                        },
                    },
                },
            ),
        )

        plan = adapter.plan_request(request)

        self.assertEqual(
            plan.payload["tools"][0]["parameters"]["properties"]["notes"]["type"],
            "string",
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
