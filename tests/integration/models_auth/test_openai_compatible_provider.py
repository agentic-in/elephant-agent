from __future__ import annotations

import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import ssl
import subprocess
import threading
import sys
from types import SimpleNamespace
import unittest
from unittest import mock
from urllib import error

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.models.provider_runtime import ProviderRuntimeResolver
from packages.models.reasoning_parser import split_reasoning_and_content
from packages.models.providers.http import (
    DEFAULT_PROVIDER_HTTP_TIMEOUT_SECONDS,
    DEFAULT_PROVIDER_STREAM_HEARTBEAT_SECONDS,
    JSONHTTPStreamChunk,
    UrllibJSONHTTPTransport,
)
from packages.models.providers.openai_compatible import (
    OpenAICompatibleProviderAdapter,
    OpenAICompatibleProviderConfig,
)
from packages.models.runtime import ModelRequest
from packages.contracts import PromptMessage


class _StaticCredentialSource:
    def __init__(self, credentials: dict[str, dict[str, str]]) -> None:
        self._credentials = credentials

    def resolve(self, provider_id: str) -> dict[str, str]:
        return dict(self._credentials[provider_id])


class _ResponsesStreamBackfillTransport:
    def __init__(self) -> None:
        self.stream_payloads: list[dict[str, object]] = []
        self.post_payloads: list[dict[str, object]] = []

    def post_json_stream(self, *, url: str, headers, payload):
        self.stream_payloads.append(dict(payload))
        yield JSONHTTPStreamChunk(
            event="response.output_text.delta",
            payload={"type": "response.output_text.delta", "delta": "fallback-response-text"},
        )
        yield JSONHTTPStreamChunk(
            event="response.output_item.done",
            payload={
                "type": "response.output_item.done",
                "item": {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "fallback-response-text"}],
                    "role": "assistant",
                    "status": "completed",
                },
            },
        )
        yield JSONHTTPStreamChunk(
            event="response.completed",
            payload={
                "type": "response.completed",
                "response": {
                    "id": "resp-fallback",
                    "model": str(payload["model"]),
                    "output": [],
                    "usage": {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8},
                },
            },
        )

    def post_json(self, *, url: str, headers, payload):
        self.post_payloads.append(dict(payload))
        raise AssertionError("responses stream backfill should not fall back to post_json")


class _ResponsesDoneEventTransport:
    def __init__(self) -> None:
        self.stream_payloads: list[dict[str, object]] = []

    def post_json_stream(self, *, url: str, headers, payload):
        self.stream_payloads.append(dict(payload))
        yield JSONHTTPStreamChunk(
            event="response.output_text.delta",
            payload={"type": "response.output_text.delta", "delta": "hello from codex"},
        )
        yield JSONHTTPStreamChunk(
            event="response.output_text.done",
            payload={"type": "response.output_text.done", "text": "hello from codex"},
        )
        yield JSONHTTPStreamChunk(
            event="response.completed",
            payload={
                "type": "response.completed",
                "response": {
                    "id": "resp-done",
                    "model": str(payload["model"]),
                    "output": [],
                    "usage": {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8},
                },
            },
        )

    def post_json(self, *, url: str, headers, payload):
        raise AssertionError("responses done-event transport should not fall back to post_json")


class _ResponsesReasoningStreamTransport:
    def __init__(self) -> None:
        self.stream_payloads: list[dict[str, object]] = []

    def post_json_stream(self, *, url: str, headers, payload):
        self.stream_payloads.append(dict(payload))
        yield JSONHTTPStreamChunk(
            event="response.reasoning.delta",
            payload={
                "type": "response.reasoning.delta",
                "delta": "Inspect the latest release state first.",
            },
        )
        yield JSONHTTPStreamChunk(
            event="response.output_text.delta",
            payload={
                "type": "response.output_text.delta",
                "delta": "The release note draft is ready.",
            },
        )
        yield JSONHTTPStreamChunk(
            event="response.completed",
            payload={
                "type": "response.completed",
                "response": {
                    "id": "resp-reasoning-stream",
                    "model": str(payload["model"]),
                    "output_text": "The release note draft is ready.",
                    "reasoning": "Inspect the latest release state first.",
                    "usage": {"input_tokens": 8, "output_tokens": 5, "total_tokens": 13},
                },
            },
        )

    def post_json(self, *, url: str, headers, payload):
        raise AssertionError("responses reasoning stream transport should not fall back to post_json")


class _ResponsesFragmentedReasoningStreamTransport:
    def post_json_stream(self, *, url: str, headers, payload):
        reasoning_deltas = ("先看", "\n", "release", "\n", "notes", "。", "\n", "Then", "\n", "verify")
        for delta in reasoning_deltas:
            yield JSONHTTPStreamChunk(
                event="response.reasoning.delta",
                payload={
                    "type": "response.reasoning.delta",
                    "delta": delta,
                },
            )
        yield JSONHTTPStreamChunk(
            event="response.output_text.delta",
            payload={
                "type": "response.output_text.delta",
                "delta": "结论已经确认。",
            },
        )
        yield JSONHTTPStreamChunk(
            event="response.completed",
            payload={
                "type": "response.completed",
                "response": {
                    "id": "resp-fragmented-reasoning-stream",
                    "model": str(payload["model"]),
                    "output_text": "结论已经确认。",
                    "reasoning": "先看\nrelease\nnotes。\nThen\nverify",
                    "usage": {"input_tokens": 10, "output_tokens": 6, "total_tokens": 16},
                },
            },
        )

    def post_json(self, *, url: str, headers, payload):
        raise AssertionError("fragmented reasoning stream transport should not fall back to post_json")


class _ResponsesWordFragmentReasoningStreamTransport:
    def post_json_stream(self, *, url: str, headers, payload):
        reasoning_deltas = ("The", "user", "asked", "about", "X", "un", "zhuo", "in", "Cheng", "du", ".")
        for delta in reasoning_deltas:
            yield JSONHTTPStreamChunk(
                event="response.reasoning.delta",
                payload={
                    "type": "response.reasoning.delta",
                    "delta": delta,
                },
            )
        yield JSONHTTPStreamChunk(
            event="response.output_text.delta",
            payload={
                "type": "response.output_text.delta",
                "delta": "I can answer naturally now.",
            },
        )
        yield JSONHTTPStreamChunk(
            event="response.completed",
            payload={
                "type": "response.completed",
                "response": {
                    "id": "resp-word-fragment-reasoning-stream",
                    "model": str(payload["model"]),
                    "output_text": "I can answer naturally now.",
                    "reasoning": "The user asked about Xunzhuo in Chengdu.",
                    "usage": {"input_tokens": 14, "output_tokens": 7, "total_tokens": 21},
                },
            },
        )

    def post_json(self, *, url: str, headers, payload):
        raise AssertionError("word fragment reasoning stream transport should not fall back to post_json")


class _ChatTaggedReasoningTransport:
    def post_json(self, *, url: str, headers, payload):
        return SimpleNamespace(
            status_code=200,
            payload={
                "id": "chat-tagged-reasoning",
                "model": str(payload["model"]),
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "<think>Inspect the latest release state first.</think>The release note draft is ready.",
                        }
                    }
                ],
                "usage": {"prompt_tokens": 7, "completion_tokens": 4, "total_tokens": 11},
            },
        )


class _ProviderStubServer:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._server.state = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def openai_base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    def start(self) -> "_ProviderStubServer":
        self._thread.start()
        return self

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        class Handler(BaseHTTPRequestHandler):
            @staticmethod
            def _responses_input_text(value) -> str:
                if isinstance(value, str):
                    return value
                if isinstance(value, list):
                    texts: list[str] = []
                    for item in value:
                        if not isinstance(item, dict):
                            continue
                        content = item.get("content", ())
                        if isinstance(content, list):
                            for block in content:
                                if not isinstance(block, dict):
                                    continue
                                text = block.get("text")
                                if isinstance(text, str):
                                    texts.append(text)
                    return "".join(texts)
                return ""

            def do_GET(self) -> None:  # noqa: N802
                if self.path != "/v1/models":
                    self.send_response(404)
                    self.end_headers()
                    return
                response = {
                    "object": "list",
                    "data": [
                        {
                            "id": "openai/gpt-4o-mini",
                            "context_window": 128000,
                            "max_output_tokens": 16384,
                        }
                    ],
                }
                encoded = json.dumps(response).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

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
                if self.path == "/v1/chat/completions":
                    if payload.get("tools") and payload.get("stream"):
                        tool_name = str(payload["tools"][0]["function"]["name"])
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream")
                        self.send_header("Cache-Control", "no-cache")
                        self.end_headers()
                        events = (
                            {
                                "id": "chatcmpl-stub",
                                "model": payload["model"],
                                "choices": [
                                    {
                                        "delta": {
                                            "role": "assistant",
                                            "tool_calls": [
                                                {
                                                    "index": 0,
                                                    "id": "call-stub",
                                                    "type": "function",
                                                    "function": {"name": tool_name, "arguments": "{\"query\":"},
                                                }
                                            ],
                                        }
                                    }
                                ],
                            },
                            {
                                "id": "chatcmpl-stub",
                                "model": payload["model"],
                                "choices": [
                                    {
                                        "delta": {
                                            "tool_calls": [
                                                {
                                                    "index": 0,
                                                    "function": {"arguments": "\"native tools\"}"},
                                                }
                                            ],
                                        }
                                    }
                                ],
                            },
                            {
                                "id": "chatcmpl-stub",
                                "model": payload["model"],
                                "choices": [{"delta": {}, "finish_reason": "tool_calls"}],
                                "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
                            },
                        )
                        for event in events:
                            self.wfile.write(f"data: {json.dumps(event)}\n\n".encode("utf-8"))
                            self.wfile.flush()
                        self.wfile.write(b"data: [DONE]\n\n")
                        self.wfile.flush()
                        return
                    if payload.get("tools"):
                        tool_name = str(payload["tools"][0]["function"]["name"])
                        response = {
                            "id": "chatcmpl-stub",
                            "model": payload["model"],
                            "choices": [
                                {
                                    "message": {
                                        "role": "assistant",
                                        "content": "",
                                        "tool_calls": [
                                            {
                                                "id": "call-stub",
                                                "type": "function",
                                                "function": {
                                                    "name": tool_name,
                                                    "arguments": json.dumps({"query": "native tools"}),
                                                },
                                            }
                                        ],
                                    }
                                }
                            ],
                            "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
                        }
                        encoded = json.dumps(response).encode("utf-8")
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(encoded)))
                        self.end_headers()
                        self.wfile.write(encoded)
                        return
                    content = f"live-chat:{payload['messages'][-1]['content']}"
                    if payload.get("stream"):
                        midpoint = max(1, len(content) // 2)
                        chunks = (content[:midpoint], content[midpoint:])
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream")
                        self.send_header("Cache-Control", "no-cache")
                        self.end_headers()
                        for chunk in chunks:
                            if not chunk:
                                continue
                            event = {
                                "id": "chatcmpl-stub",
                                "model": payload["model"],
                                "choices": [{"delta": {"role": "assistant", "content": chunk}}],
                            }
                            self.wfile.write(f"data: {json.dumps(event)}\n\n".encode("utf-8"))
                            self.wfile.flush()
                        final_event = {
                            "id": "chatcmpl-stub",
                            "model": payload["model"],
                            "choices": [{"delta": {}, "finish_reason": "stop"}],
                            "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
                        }
                        self.wfile.write(f"data: {json.dumps(final_event)}\n\n".encode("utf-8"))
                        self.wfile.write(b"data: [DONE]\n\n")
                        self.wfile.flush()
                        return
                    response = {
                        "id": "chatcmpl-stub",
                        "model": payload["model"],
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": content,
                                }
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 7,
                            "completion_tokens": 3,
                            "total_tokens": 10,
                            "prompt_tokens_details": {"cached_tokens": 4},
                        },
                    }
                elif self.path == "/v1/embeddings":
                    response = {
                        "id": "embed-stub",
                        "model": payload["model"],
                        "data": [{"index": 0, "embedding": [0.1, 0.2, 0.3, 0.4]}],
                        "usage": {"prompt_tokens": 3, "total_tokens": 3},
                    }
                elif self.path in {"/v1/responses", "/responses"}:
                    if payload.get("stream"):
                        input_text = self._responses_input_text(payload.get("input"))
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream")
                        self.send_header("Cache-Control", "no-cache")
                        self.end_headers()
                        if payload.get("tools"):
                            function_call = {
                                "type": "function_call",
                                "name": str(payload["tools"][0]["name"]),
                                "arguments": json.dumps({"query": "responses tools"}),
                            }
                            events = (
                                ("response.output_item.done", {"item": function_call}),
                                (
                                    "response.completed",
                                    {
                                        "response": {
                                            "id": "resp-stub",
                                            "model": payload["model"],
                                            "output": [function_call],
                                            "usage": {"input_tokens": 6, "output_tokens": 3, "total_tokens": 9},
                                        }
                                    },
                                ),
                            )
                        else:
                            content = f"live-response:{input_text}"
                            midpoint = max(1, len(content) // 2)
                            events = (
                                ("response.output_text.delta", {"delta": content[:midpoint]}),
                                ("response.output_text.delta", {"delta": content[midpoint:]}),
                                (
                                    "response.completed",
                                    {
                                        "response": {
                                            "id": "resp-stub",
                                            "model": payload["model"],
                                            "output_text": content,
                                            "usage": {"input_tokens": 6, "output_tokens": 3, "total_tokens": 9},
                                        }
                                    },
                                ),
                            )
                        for event_name, event_payload in events:
                            self.wfile.write(f"event: {event_name}\n".encode("utf-8"))
                            self.wfile.write(f"data: {json.dumps(event_payload)}\n\n".encode("utf-8"))
                            self.wfile.flush()
                        self.wfile.write(b"data: [DONE]\n\n")
                        self.wfile.flush()
                        return
                    if payload.get("tools"):
                        tool_name = str(payload["tools"][0]["name"])
                        response = {
                            "id": "resp-stub",
                            "model": payload["model"],
                            "output": [
                                {
                                    "type": "function_call",
                                    "name": tool_name,
                                    "arguments": json.dumps({"query": "responses tools"}),
                                }
                            ],
                            "usage": {"input_tokens": 6, "output_tokens": 3, "total_tokens": 9},
                        }
                    else:
                        response = {
                            "id": "resp-stub",
                            "model": payload["model"],
                            "output_text": f"live-response:{self._responses_input_text(payload.get('input'))}",
                            "usage": {"input_tokens": 6, "output_tokens": 3, "total_tokens": 9},
                        }
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                encoded = json.dumps(response).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format: str, *args: object) -> None:
                return

        return Handler


class OpenAICompatibleProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = _ProviderStubServer().start()

    def tearDown(self) -> None:
        self.server.close()

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
        self.assertIn("### System Layer Contract", plan.payload["messages"][0]["content"])
        self.assertIn("You are the active elephant identity", plan.payload["messages"][0]["content"])
        self.assertIn("### Episode Continuity", plan.payload["messages"][0]["content"])
        self.assertIn("Stay truthful and bounded", plan.payload["messages"][0]["content"])
        self.assertIn("### Loop Execution Board", plan.payload["messages"][0]["content"])
        self.assertIn("### Understanding tools", plan.payload["messages"][0]["content"])
        self.assertEqual(plan.payload["messages"][1]["role"], "user")
        self.assertEqual(plan.payload["messages"][1]["content"], request.prompt)
        self.assertNotIn("metadata", plan.payload)
        self.assertEqual(result.task, "generate")
        self.assertEqual(result.content, "live-chat:Summarize the provider runtime.")
        self.assertEqual(result.usage.cached_prompt_tokens, 4)
        self.assertTrue(result.usage.cache_usage_reported)
        self.assertNotIn("sk-test-123", result.content)
        self.assertEqual(self.server.requests[0]["path"], "/v1/chat/completions")
        self.assertEqual(self.server.requests[0]["headers"]["Authorization"], "Bearer sk-test-123")
        request_headers = {str(key).lower(): str(value) for key, value in dict(self.server.requests[0]["headers"]).items()}
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

    def test_rendered_prompt_is_forwarded_without_provider_guardrail_prepended(self) -> None:
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
                    "## StateSnapshot\n"
                    "- active current work: keep the State exact"
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
        self.assertNotIn("OpenAI-compatible provider adapter", plan.payload["messages"][0]["content"])
        self.assertNotIn("credential_keys=", plan.payload["messages"][0]["content"])
        self.assertEqual(sum(1 for message in plan.payload["messages"] if message["role"] == "system"), 1)
        self.assertEqual(
            plan.payload["messages"][1]["content"],
            "Who are you?",
        )

    def test_chat_request_flattens_all_system_context_into_one_system_message(self) -> None:
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

        self.assertEqual([message["role"] for message in plan.payload["messages"]], ["system", "assistant", "user"])
        self.assertIn("## EpisodeFrozenContext", plan.payload["messages"][0]["content"])
        self.assertIn("## StateSnapshot", plan.payload["messages"][0]["content"])
        self.assertNotIn("## LoopContext", plan.payload["messages"][0]["content"])
        self.assertNotIn("## WorkspaceAttachments", plan.payload["messages"][0]["content"])
        self.assertIn("## SessionHistorySummary", plan.payload["messages"][0]["content"])
        self.assertEqual(plan.payload["messages"][1]["content"], "Earlier reply.")
        self.assertEqual(plan.payload["messages"][2]["content"], "What should I do next?")

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
                        {"id": "call-1", "name": "tool.web.search", "arguments": {"query": "elephant docs"}},
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
                        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
                    },
                },
            ),
        )

        plan = adapter.plan_request(request)

        self.assertEqual([message["role"] for message in plan.payload["messages"][-4:]], ["user", "assistant", "tool", "user"])
        self.assertEqual(plan.payload["messages"][-3]["tool_calls"][0]["function"]["name"], "tool_web_search")
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
        self.assertEqual(plan.payload["tools"][0]["function"]["name"], "tool_web_search")
        self.assertEqual(result.content, "")
        self.assertEqual(len(result.tool_calls), 1)
        self.assertEqual(result.tool_calls[0].tool_name, "tool.web.search")
        self.assertEqual(result.tool_calls[0].arguments, {"query": "native tools"})
        self.assertEqual(streamed, [])
        self.assertEqual(result.metadata["stream"], "true")

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
            credential_source=_StaticCredentialSource({"openai": {"api_key": "sk-openai-123"}}),
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

    def test_responses_stream_reasoning_collapses_fragmented_newlines_without_breaking_mixed_language_text(self) -> None:
        streamed: list[str] = []
        adapter = OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id="openai",
                base_url="https://api.openai.example/v1",
                model_id="gpt-5.4",
            ),
            runtime_resolver=ProviderRuntimeResolver.default(),
            credential_source=_StaticCredentialSource({"openai": {"api_key": "sk-openai-123"}}),
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
        streamed_combined = split_reasoning_and_content("".join(streamed), streaming=True)
        self.assertEqual(streamed_combined.reasoning, "先看release notes。 Then verify")
        self.assertEqual(streamed_combined.content, "结论已经确认。")

    def test_responses_stream_reasoning_prioritizes_spaces_and_uses_completed_reasoning_when_available(self) -> None:
        streamed: list[str] = []
        adapter = OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id="openai",
                base_url="https://api.openai.example/v1",
                model_id="gpt-5.4",
            ),
            runtime_resolver=ProviderRuntimeResolver.default(),
            credential_source=_StaticCredentialSource({"openai": {"api_key": "sk-openai-123"}}),
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
        streamed_combined = split_reasoning_and_content("".join(streamed), streaming=True)
        self.assertEqual(streamed_combined.reasoning, "The user asked about X un zhuo in Cheng du.")
        self.assertEqual(streamed_combined.content, "I can answer naturally now.")

    def test_chat_transport_strips_tagged_reasoning_from_final_content(self) -> None:
        adapter = OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id="openai-compatible",
                base_url="https://api.openai.example/v1",
                model_id="openai/gpt-4o-mini",
            ),
            runtime_resolver=ProviderRuntimeResolver.default(),
            credential_source=_StaticCredentialSource({"openai-compatible": {"api_key": "sk-openai-123"}}),
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

    def test_responses_transport_parses_native_tool_calls(self) -> None:
        adapter = OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id="openai",
                base_url=self.server.openai_base_url,
                model_id="gpt-4.1-mini",
            ),
            runtime_resolver=ProviderRuntimeResolver.default(),
            credential_source=_StaticCredentialSource({"openai": {"api_key": "sk-openai-123"}}),
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
        self.assertEqual(plan.payload["input"][0]["content"][0]["text"], "Use tools through responses.")
        self.assertEqual(plan.payload["tools"][0]["name"], "tool_web_search")
        self.assertFalse(plan.payload["store"])
        self.assertEqual(result.content, "")
        self.assertEqual(len(result.tool_calls), 1)
        self.assertEqual(result.tool_calls[0].tool_name, "tool.web.search")
        self.assertEqual(result.tool_calls[0].arguments, {"query": "responses tools"})

    def test_responses_transport_includes_reasoning_effort_when_supported(self) -> None:
        adapter = OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id="openai",
                base_url=self.server.openai_base_url,
                model_id="gpt-5.4",
            ),
            runtime_resolver=ProviderRuntimeResolver.default(),
            credential_source=_StaticCredentialSource({"openai": {"api_key": "sk-openai-123"}}),
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
            credential_source=_StaticCredentialSource({"openai-codex": {"api_key": "sk-codex-123"}}),
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
        self.assertEqual(result.content, "live-response:Explain the current runtime status.")

    def test_codex_responses_backfills_completed_response_from_stream_items(self) -> None:
        transport = _ResponsesStreamBackfillTransport()
        adapter = OpenAICompatibleProviderAdapter(
            config=OpenAICompatibleProviderConfig(
                provider_id="openai-codex",
                base_url="https://chatgpt.com/backend-api/codex",
                model_id="gpt-5.4",
            ),
            runtime_resolver=ProviderRuntimeResolver.default(),
            credential_source=_StaticCredentialSource({"openai-codex": {"api_key": "sk-codex-123"}}),
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
            credential_source=_StaticCredentialSource({"openai-codex": {"api_key": "sk-codex-123"}}),
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
            credential_source=_StaticCredentialSource({"copilot": {"api_key": "ghu-test"}}),
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
            credential_source=_StaticCredentialSource({"openai-codex": {"api_key": "sk-codex-123"}}),
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


class UrllibJSONHTTPTransportFallbackTests(unittest.TestCase):
    def test_default_timeouts_bound_stalled_model_responses(self) -> None:
        transport = UrllibJSONHTTPTransport()

        self.assertEqual(transport.timeout_seconds, DEFAULT_PROVIDER_HTTP_TIMEOUT_SECONDS)
        self.assertEqual(transport.timeout_seconds, 120.0)
        self.assertEqual(transport.stream_timeout_seconds, DEFAULT_PROVIDER_STREAM_HEARTBEAT_SECONDS)
        self.assertEqual(transport.stream_timeout_seconds, 30.0)

    def test_html_http_errors_are_summarized_with_codex_reauth_hint(self) -> None:
        transport = UrllibJSONHTTPTransport()
        exc = error.HTTPError(
            url="https://chatgpt.com/backend-api/codex/v1/responses",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=io.BytesIO(
                b"<html><head><title>Forbidden</title></head><body><h1>Forbidden</h1><p>Access denied.</p></body></html>"
            ),
        )

        message = transport._error_message(exc, url="https://chatgpt.com/backend-api/codex/v1/responses")
        exc.close()

        self.assertIn("provider request failed with status 403.", message)
        self.assertIn("HTML error page instead of JSON", message)
        self.assertIn("wrong Codex backend path", message)
        self.assertIn("/responses", message)
        self.assertNotIn("<html>", message)

    def test_retries_with_curl_on_tls_version_mismatch(self) -> None:
        transport = UrllibJSONHTTPTransport()
        completed = subprocess.CompletedProcess(
            args=["curl"],
            returncode=0,
            stdout=b'{"id":"chatcmpl-fallback","choices":[{"message":{"content":"ok"}}]}\n__ELEPHANT_STATUS__:200',
            stderr=b"",
        )
        with (
            mock.patch(
                "packages.models.providers.http.request.urlopen",
                side_effect=error.URLError(ssl.SSLError("WRONG_VERSION_NUMBER")),
            ),
            mock.patch("packages.models.providers.http.shutil.which", return_value="/usr/bin/curl"),
            mock.patch("packages.models.providers.http.subprocess.run", return_value=completed) as run,
        ):
            response = transport.post_json(
                url="https://example.test/v1/chat/completions",
                headers={"Authorization": "Bearer sk-test"},
                payload={"model": "demo", "messages": [{"role": "user", "content": "hello"}]},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.payload["id"], "chatcmpl-fallback")
        self.assertEqual(response.payload["choices"][0]["message"]["content"], "ok")
        command = run.call_args.args[0]
        self.assertIn("--write-out", command)
        self.assertIn("--max-time", command)
        self.assertEqual(command[command.index("--max-time") + 1], "120")
        self.assertIn("https://example.test/v1/chat/completions", command)

    def test_retries_with_curl_on_tls_unexpected_eof(self) -> None:
        transport = UrllibJSONHTTPTransport()

        self.assertTrue(
            transport._should_retry_with_curl(
                error.URLError(ssl.SSLError("UNEXPECTED_EOF_WHILE_READING"))
            )
        )

    def test_stream_retries_with_curl_on_tls_unexpected_eof(self) -> None:
        transport = UrllibJSONHTTPTransport()
        completed = subprocess.CompletedProcess(
            args=["curl"],
            returncode=0,
            stdout=(
                b'event: response.output_text.delta\n'
                b'data: {"delta":"hello"}\n\n'
                b'event: response.completed\n'
                b'data: {"response":{"id":"resp-fallback","output_text":"hello"}}\n\n'
                b'data: [DONE]\n\n'
                b'__ELEPHANT_STATUS__:200'
            ),
            stderr=b"",
        )
        with (
            mock.patch(
                "packages.models.providers.http.request.urlopen",
                side_effect=error.URLError(ssl.SSLError("UNEXPECTED_EOF_WHILE_READING")),
            ),
            mock.patch("packages.models.providers.http.shutil.which", return_value="/usr/bin/curl"),
            mock.patch("packages.models.providers.http.subprocess.run", return_value=completed) as run,
        ):
            chunks = tuple(
                transport.post_json_stream(
                    url="https://api.githubcopilot.com/v1/responses",
                    headers={"Authorization": "Bearer ghu-test"},
                    payload={"model": "gpt-5.4", "input": [], "stream": True},
                )
            )

        self.assertEqual([chunk.event for chunk in chunks], ["response.output_text.delta", "response.completed"])
        self.assertEqual(chunks[0].payload["delta"], "hello")
        command = run.call_args.args[0]
        self.assertIn("--write-out", command)
        self.assertIn("--max-time", command)
        self.assertEqual(command[command.index("--max-time") + 1], "30")
        self.assertIn("https://api.githubcopilot.com/v1/responses", command)


if __name__ == "__main__":
    unittest.main()
