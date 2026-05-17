from __future__ import annotations

from datetime import datetime
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.auth import (
    AuthProfile,
    InMemoryAuthProfileStore,
    InMemorySecretStore,
    PreviewAuthProviderCapability,
    ProfileCredentialResolver,
    SecretReference,
)
from packages.contracts import ContextBundle, PromptMessage
from packages.contracts.layers import Episode
from packages.contracts.runtime import PersonalModelRuntimeState
from packages.models.provider_catalog import provider_definition
from packages.models.providers import (
    AnthropicMessagesModelAdapter,
    AnthropicMessagesProviderCapability,
    build_model_adapter,
)
from packages.models.provider_runtime import ProviderRuntimeResolver
from packages.models.runtime import ModelRequest


class _AnthropicStubServer:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._server.state = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def start(self) -> "_AnthropicStubServer":
        self._thread.start()
        return self

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                server_state = self.server.state  # type: ignore[attr-defined]
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                payload = json.loads(body.decode("utf-8"))
                server_state.requests.append(
                    {
                        "path": self.path,
                        "headers": dict(self.headers.items()),
                        "payload": payload,
                    }
                )
                if payload.get("tools"):
                    response = {
                        "id": "msg-stub",
                        "model": payload["model"],
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "toolu-stub",
                                "name": "tool.web.search",
                                "input": {"query": "anthropic tools"},
                            }
                        ],
                        "stop_reason": "tool_use",
                        "usage": {
                            "input_tokens": 9,
                            "output_tokens": 4,
                            "cache_read_input_tokens": 3,
                            "cache_creation_input_tokens": 2,
                        },
                    }
                else:
                    response = {
                        "id": "msg-stub",
                        "model": payload["model"],
                        "content": [
                            {
                                "type": "text",
                                "text": f"live-anthropic:{payload['messages'][0]['content'][0]['text'].splitlines()[0]}",
                            }
                        ],
                        "stop_reason": "end_turn",
                        "usage": {
                            "input_tokens": 9,
                            "output_tokens": 4,
                            "cache_read_input_tokens": 3,
                            "cache_creation_input_tokens": 2,
                        },
                    }
                encoded = json.dumps(response).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format: str, *args: object) -> None:
                return

        return Handler


class AnthropicProviderAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.secret_store = InMemorySecretStore()
        self.reference = SecretReference(
            reference_id="secret-anthropic-token",
            provider_id="anthropic",
            secret_name="api_token",
            secret_key="api_key",
        )
        self.secret_store.put(self.reference.reference_id, "anthropic-secret")
        self.profile_store = InMemoryAuthProfileStore(
            (
                AuthProfile(
                    profile_id="auth-anthropic-default",
                    provider_id="anthropic",
                    secret_references=(self.reference,),
                    priority=10,
                ),
            )
        )
        self.auth_capability = PreviewAuthProviderCapability(
            profile_store=self.profile_store,
            resolver=ProfileCredentialResolver(self.secret_store),
        )
        self.server = _AnthropicStubServer().start()
        self.resolution = ProviderRuntimeResolver.default().resolve(
            "anthropic",
            base_url=self.server.base_url,
        )
        self.adapter = AnthropicMessagesModelAdapter(
            adapter_id="adapter.anthropic.messages",
            resolution=self.resolution,
            credential_source=self.auth_capability,
        )
        self.capability = AnthropicMessagesProviderCapability(
            adapter=self.adapter,
            credential_source=self.auth_capability,
        )

    def tearDown(self) -> None:
        self.server.close()

    def _request(self) -> ModelRequest:
        return ModelRequest(
            request_id="request-1",
            profile_id="profile-companion",
            session_id="session-1",
            provider_id="anthropic",
            model_id=self.resolution.model_id,
            prompt="Explain the provider boundary without leaking secrets.",
            context={
                "bundle_id": "bundle-1",
                "token_budget": "512",
                "instruction_refs": "docs/agent/task-cards/prv-3-anthropic-provider-adapter.md",
                "work_item_ids": "work-1",
                "evidence_refs": "evidence-1",
                "frozen_prefix_prompt": "## EpisodeFrozenContext\n- Keep the response structured.",
                "session_snapshot_prompt": "## StateSnapshot\n- active current work: explain the provider boundary",
                "rendered_prompt": "legacy rendered prompt should not be used when structured sections exist",
            },
            metadata={
                "profile_mode": "companion",
                "session_status": "active",
            },
        )

    def test_native_request_uses_anthropic_messages_shape(self) -> None:
        request = self.adapter.build_request(self._request())

        self.assertFalse(self.resolution.supports_streaming)
        self.assertTrue(self.resolution.supports_tools)
        self.assertTrue(self.resolution.supports_reasoning)
        self.assertEqual(self.resolution.reasoning_efforts, ("low", "medium", "high"))
        self.assertEqual(self.resolution.capability_flags, ("chat",))
        self.assertEqual(request.endpoint_path, "/v1/messages")
        self.assertEqual(request.request_family, "messages")
        self.assertEqual(request.headers["x-api-key"], "anthropic-secret")
        self.assertEqual(request.headers["anthropic-version"], "2023-06-01")
        self.assertEqual(request.headers["x-session-id"], "session-1")
        self.assertEqual(request.messages[0].role, "user")
        self.assertEqual(
            request.messages[0].content[0].text,
            "Explain the provider boundary without leaking secrets.",
        )
        self.assertEqual(
            request.system,
            "## EpisodeFrozenContext\n- Keep the response structured.\n\n"
            "## StateSnapshot\n- active current work: explain the provider boundary",
        )
        self.assertNotIn("Anthropic Messages native adapter", request.system)
        self.assertNotIn("credential_keys=", request.system)
        self.assertNotIn("provider_id=anthropic", request.system)
        self.assertEqual(request.metadata["credential_keys"], "api_key")
        self.assertEqual(request.tools, ())
        wire_payload = request.as_mapping()
        self.assertNotIn("metadata", wire_payload)
        self.assertNotIn("metadata", wire_payload["messages"][0])
        self.assertNotIn("metadata", wire_payload["messages"][0]["content"][0])

    def test_native_request_preserves_history_and_tool_result_blocks(self) -> None:
        request = self._request()
        request = ModelRequest(
            request_id=request.request_id,
            profile_id=request.profile_id,
            session_id=request.session_id,
            provider_id=request.provider_id,
            model_id=request.model_id,
            prompt="Use that result.",
            context=dict(request.context),
            messages=(
                PromptMessage(role="user", content="Search the docs."),
                PromptMessage(
                    role="assistant",
                    content="",
                    tool_calls=(
                        {"id": "toolu-1", "name": "tool.web.search", "arguments": {"query": "elephant docs"}},
                    ),
                ),
                PromptMessage(
                    role="tool",
                    content="docs result",
                    tool_call_id="toolu-1",
                    tool_name="tool.web.search",
                ),
            ),
            tools=(
                {
                    "type": "function",
                    "function": {
                        "name": "tool.web.search",
                        "description": "Search the web.",
                        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
                    },
                },
            ),
        )

        planned = self.adapter.build_request(request)
        payload = planned.as_mapping()

        self.assertEqual([message["role"] for message in payload["messages"][-3:]], ["user", "assistant", "user"])
        self.assertEqual(payload["messages"][-2]["content"][0]["type"], "tool_use")
        self.assertEqual(payload["messages"][-2]["content"][0]["name"], "tool_web_search")
        self.assertEqual(payload["messages"][-1]["content"][0]["type"], "tool_result")
        self.assertEqual(payload["messages"][-1]["content"][0]["tool_use_id"], "toolu-1")
        self.assertEqual(payload["messages"][-1]["content"][1]["text"], "Use that result.")

    def test_native_request_uses_bearer_headers_for_anthropic_oauth_tokens(self) -> None:
        request = self.adapter.build_request(self._request(), {"api_key": "sk-ant-oat-test-token"})

        self.assertEqual(request.headers["Authorization"], "Bearer sk-ant-oat-test-token")
        self.assertIn("oauth-2025-04-20", request.headers["anthropic-beta"])
        self.assertEqual(request.headers["x-app"], "cli")
        self.assertNotIn("x-api-key", request.headers)

    def test_reasoning_effort_maps_to_thinking_payload(self) -> None:
        request = self.adapter.build_request(
            ModelRequest(
                request_id="request-thinking",
                profile_id="profile-companion",
                session_id="session-1",
                provider_id="anthropic",
                model_id=self.resolution.model_id,
                prompt="Think carefully before answering.",
                reasoning_effort="high",
            )
        )

        self.assertEqual(request.thinking, {"type": "enabled", "budget_tokens": 16000})
        self.assertIsNone(request.output_config)
        self.assertEqual(request.temperature, 1)
        self.assertGreaterEqual(request.max_tokens, 20096)

    def test_copilot_claude_uses_bearer_auth_and_default_headers(self) -> None:
        copilot_definition = provider_definition("copilot")
        self.assertIsNotNone(copilot_definition)
        assert copilot_definition is not None
        profile = AuthProfile(
            profile_id="auth-copilot-claude",
            provider_id="copilot",
            base_url=self.server.base_url,
            default_model="claude-sonnet-4.6",
            extra_headers=dict(copilot_definition.extra_headers),
        )
        adapter = build_model_adapter(
            profile,
            runtime_resolver=ProviderRuntimeResolver.default(),
            credentials={"api_key": "ghu-copilot"},
            adapter_id="adapter.copilot.messages",
        )

        self.assertIsInstance(adapter, AnthropicMessagesModelAdapter)
        request = ModelRequest(
            request_id="request-copilot-claude",
            profile_id="profile-companion",
            session_id="session-copilot-claude",
            provider_id="copilot",
            model_id="claude-sonnet-4.6",
            prompt="Explain the provider boundary without leaking secrets.",
        )

        native_request = adapter.build_request(request)

        self.assertEqual(native_request.headers["Authorization"], "Bearer ghu-copilot")
        self.assertEqual(native_request.headers["anthropic-version"], "2023-06-01")
        self.assertEqual(native_request.headers["Openai-Intent"], "conversation-edits")
        self.assertEqual(native_request.headers["x-initiator"], "agent")
        self.assertNotIn("x-api-key", native_request.headers)

        adapter.generate(request, {"api_key": "ghu-copilot"})

        request_headers = {str(key).lower(): str(value) for key, value in dict(self.server.requests[-1]["headers"]).items()}
        self.assertEqual(request_headers["authorization"], "Bearer ghu-copilot")
        self.assertEqual(request_headers["anthropic-version"], "2023-06-01")
        self.assertEqual(request_headers["openai-intent"], "conversation-edits")
        self.assertEqual(request_headers["x-initiator"], "agent")
        self.assertEqual(request_headers["x-session-id"], "session-copilot-claude")
        self.assertNotIn("x-api-key", request_headers)

    def test_session_header_does_not_override_explicit_extra_header(self) -> None:
        adapter = AnthropicMessagesModelAdapter(
            resolution=self.resolution,
            credential_source=self.auth_capability,
            adapter_id="adapter.anthropic.explicit-session-header",
            extra_headers={"X-Session-Id": "configured-session"},
        )

        request = adapter.build_request(self._request())

        self.assertEqual(request.headers["X-Session-Id"], "configured-session")
        self.assertNotIn("x-session-id", request.headers)

    def test_generate_returns_native_result_without_leaking_secret_material(self) -> None:
        result = self.adapter.generate(self._request(), self.auth_capability.resolve("anthropic"))

        self.assertEqual(result.task, "generate")
        self.assertEqual(result.content, "live-anthropic:Explain the provider boundary without leaking secrets.")
        self.assertNotIn("anthropic-secret", result.content)
        self.assertEqual(result.metadata["transport_id"], "anthropic_messages")
        self.assertEqual(result.metadata["credential_keys"], "api_key")
        self.assertEqual(result.usage.cached_prompt_tokens, 3)
        self.assertEqual(result.usage.cache_creation_prompt_tokens, 2)
        self.assertTrue(result.usage.cache_usage_reported)
        self.assertEqual(self.server.requests[0]["path"], "/v1/messages")
        request_headers = {str(key).lower(): str(value) for key, value in dict(self.server.requests[0]["headers"]).items()}
        self.assertEqual(request_headers["x-api-key"], "anthropic-secret")
        self.assertEqual(request_headers["x-session-id"], "session-1")

    def test_generate_parses_native_tool_use_blocks(self) -> None:
        request = ModelRequest(
            request_id="request-tools",
            profile_id="profile-companion",
            session_id="session-tools",
            provider_id="anthropic",
            model_id=self.resolution.model_id,
            prompt="Use tools to keep researching.",
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

        native_request = self.adapter.build_request(request, self.auth_capability.resolve("anthropic"))

        self.assertEqual(native_request.tools[0]["name"], "tool_web_search")
        self.assertEqual(native_request.tool_name_map["tool_web_search"], "tool.web.search")

        result = self.adapter.generate(request, self.auth_capability.resolve("anthropic"))

        self.assertEqual(result.content, "")
        self.assertEqual(len(result.tool_calls), 1)
        self.assertEqual(result.tool_calls[0].tool_name, "tool.web.search")
        self.assertEqual(result.tool_calls[0].arguments, {"query": "anthropic tools"})
        self.assertEqual(self.server.requests[-1]["payload"]["tools"][0]["name"], "tool_web_search")

    def test_capability_bridge_uses_shared_runtime_contract(self) -> None:
        profile = PersonalModelRuntimeState(
            profile_id="profile-companion",
            display_name="Elephant Agent",
            mode="companion",
            enabled_capabilities=("model.anthropic.messages",),
        )
        session = Episode(
            episode_id="session-1",
            state_id="state:test",
            personal_model_id=profile.profile_id,
            entry_surface="test",
            elephant_id="elephant-1",
            status="open",
            started_at=datetime(2026, 1, 1),
            updated_at=datetime(2026, 1, 1),
        )
        context = ContextBundle(
            bundle_id="bundle-1",
            episode_id=session.episode_id,
            instruction_refs=("docs/agent/task-cards/prv-3-anthropic-provider-adapter.md",),
            work_item_ids=("work-1",),
            evidence_refs=("evidence-1",),
            token_budget=512,
            rendered_prompt="## system\nKeep the response structured.",
        )

        result = self.capability.generate(
            profile=profile,
            session=session,
            context=context,
            prompt="Explain the provider boundary without leaking secrets.",
        )

        self.assertEqual(result.session_id, session.episode_id)
        self.assertEqual(result.outcome, "ok")
        self.assertEqual(result.summary, "live-anthropic:Explain the provider boundary without leaking secrets.")
        self.assertEqual(result.cached_prompt_tokens, 3)
        self.assertEqual(result.cache_creation_prompt_tokens, 2)
        self.assertTrue(result.cache_usage_reported)
        self.assertIn("transport=anthropic_messages", result.side_effects)
        self.assertIn("credential_keys=api_key", result.side_effects)
        self.assertNotIn("anthropic-secret", result.summary)

    def test_embed_is_explicitly_unsupported(self) -> None:
        result = self.adapter.embed(self._request(), self.auth_capability.resolve("anthropic"))

        self.assertEqual(result.failure_kind, "unsupported")
        self.assertEqual(result.metadata["transport_id"], "anthropic_messages")


if __name__ == "__main__":
    unittest.main()
