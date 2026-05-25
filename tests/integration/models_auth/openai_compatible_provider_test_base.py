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
            payload={
                "type": "response.output_text.delta",
                "delta": "fallback-response-text",
            },
        )
        yield JSONHTTPStreamChunk(
            event="response.output_item.done",
            payload={
                "type": "response.output_item.done",
                "item": {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "fallback-response-text"}
                    ],
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
        raise AssertionError(
            "responses stream backfill should not fall back to post_json"
        )


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
        raise AssertionError(
            "responses done-event transport should not fall back to post_json"
        )


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
                    "usage": {
                        "input_tokens": 8,
                        "output_tokens": 5,
                        "total_tokens": 13,
                    },
                },
            },
        )

    def post_json(self, *, url: str, headers, payload):
        raise AssertionError(
            "responses reasoning stream transport should not fall back to post_json"
        )


class _ResponsesFragmentedReasoningStreamTransport:
    def post_json_stream(self, *, url: str, headers, payload):
        reasoning_deltas = (
            "先看",
            "\n",
            "release",
            "\n",
            "notes",
            "。",
            "\n",
            "Then",
            "\n",
            "verify",
        )
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
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 6,
                        "total_tokens": 16,
                    },
                },
            },
        )

    def post_json(self, *, url: str, headers, payload):
        raise AssertionError(
            "fragmented reasoning stream transport should not fall back to post_json"
        )


class _ResponsesWordFragmentReasoningStreamTransport:
    def post_json_stream(self, *, url: str, headers, payload):
        reasoning_deltas = (
            "The",
            "user",
            "asked",
            "about",
            "X",
            "un",
            "zhuo",
            "in",
            "Cheng",
            "du",
            ".",
        )
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
                    "usage": {
                        "input_tokens": 14,
                        "output_tokens": 7,
                        "total_tokens": 21,
                    },
                },
            },
        )

    def post_json(self, *, url: str, headers, payload):
        raise AssertionError(
            "word fragment reasoning stream transport should not fall back to post_json"
        )


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
                "usage": {
                    "prompt_tokens": 7,
                    "completion_tokens": 4,
                    "total_tokens": 11,
                },
            },
        )


class _ChatSplitTaggedReasoningStreamTransport:
    def __init__(self) -> None:
        self.stream_payloads: list[dict[str, object]] = []

    def post_json_stream(self, *, url: str, headers, payload):
        self.stream_payloads.append(dict(payload))
        chunks = (
            {"role": "assistant"},
            {"content": "<thi"},
            {"content": "nk>"},
            {
                "content": 'The user is asking me to reply with only two characters: "你好".'
            },
            {"content": "</think>"},
            {"content": "\n\n你好"},
            {},
        )
        for delta in chunks:
            yield JSONHTTPStreamChunk(
                event=None,
                payload={
                    "id": "chat-split-tagged-reasoning-stream",
                    "model": str(payload["model"]),
                    "choices": [{"delta": delta}],
                },
            )
        yield JSONHTTPStreamChunk(
            event=None,
            payload={
                "id": "chat-split-tagged-reasoning-stream",
                "model": str(payload["model"]),
                "choices": [{"delta": {}}],
                "usage": {
                    "prompt_tokens": 7,
                    "completion_tokens": 4,
                    "total_tokens": 11,
                },
            },
        )

    def post_json(self, *, url: str, headers, payload):
        raise AssertionError(
            "split tagged reasoning stream transport should not fall back to post_json"
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
                                                    "function": {
                                                        "name": tool_name,
                                                        "arguments": '{"query":',
                                                    },
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
                                                    "function": {
                                                        "arguments": '"native tools"}'
                                                    },
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
                                    {"delta": {}, "finish_reason": "tool_calls"}
                                ],
                                "usage": {
                                    "prompt_tokens": 7,
                                    "completion_tokens": 3,
                                    "total_tokens": 10,
                                },
                            },
                        )
                        for event in events:
                            self.wfile.write(
                                f"data: {json.dumps(event)}\n\n".encode("utf-8")
                            )
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
                                                    "arguments": json.dumps(
                                                        {"query": "native tools"}
                                                    ),
                                                },
                                            }
                                        ],
                                    }
                                }
                            ],
                            "usage": {
                                "prompt_tokens": 7,
                                "completion_tokens": 3,
                                "total_tokens": 10,
                            },
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
                                "choices": [
                                    {"delta": {"role": "assistant", "content": chunk}}
                                ],
                            }
                            self.wfile.write(
                                f"data: {json.dumps(event)}\n\n".encode("utf-8")
                            )
                            self.wfile.flush()
                        final_event = {
                            "id": "chatcmpl-stub",
                            "model": payload["model"],
                            "choices": [{"delta": {}, "finish_reason": "stop"}],
                            "usage": {
                                "prompt_tokens": 7,
                                "completion_tokens": 3,
                                "total_tokens": 10,
                            },
                        }
                        self.wfile.write(
                            f"data: {json.dumps(final_event)}\n\n".encode("utf-8")
                        )
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
                                            "usage": {
                                                "input_tokens": 6,
                                                "output_tokens": 3,
                                                "total_tokens": 9,
                                            },
                                        }
                                    },
                                ),
                            )
                        else:
                            content = f"live-response:{input_text}"
                            midpoint = max(1, len(content) // 2)
                            events = (
                                (
                                    "response.output_text.delta",
                                    {"delta": content[:midpoint]},
                                ),
                                (
                                    "response.output_text.delta",
                                    {"delta": content[midpoint:]},
                                ),
                                (
                                    "response.completed",
                                    {
                                        "response": {
                                            "id": "resp-stub",
                                            "model": payload["model"],
                                            "output_text": content,
                                            "usage": {
                                                "input_tokens": 6,
                                                "output_tokens": 3,
                                                "total_tokens": 9,
                                            },
                                        }
                                    },
                                ),
                            )
                        for event_name, event_payload in events:
                            self.wfile.write(f"event: {event_name}\n".encode("utf-8"))
                            self.wfile.write(
                                f"data: {json.dumps(event_payload)}\n\n".encode("utf-8")
                            )
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
                                    "arguments": json.dumps(
                                        {"query": "responses tools"}
                                    ),
                                }
                            ],
                            "usage": {
                                "input_tokens": 6,
                                "output_tokens": 3,
                                "total_tokens": 9,
                            },
                        }
                    else:
                        response = {
                            "id": "resp-stub",
                            "model": payload["model"],
                            "output_text": f"live-response:{self._responses_input_text(payload.get('input'))}",
                            "usage": {
                                "input_tokens": 6,
                                "output_tokens": 3,
                                "total_tokens": 9,
                            },
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


class OpenAICompatibleProviderTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.server = _ProviderStubServer().start()

    def tearDown(self) -> None:
        self.server.close()
