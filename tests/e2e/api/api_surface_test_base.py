from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import unittest
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api import create_app

EMBEDDING_BOOTSTRAP_STATUSES = {"ready", "pending", "downloading", "failed"}


class _ProviderStubServer:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._server.state = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def openai_base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    @property
    def anthropic_base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

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
                    response = {
                        "id": "chatcmpl-stub",
                        "model": payload["model"],
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": f"live-chat:{payload['messages'][-1]['content']}",
                                }
                            }
                        ],
                        "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
                    }
                elif self.path == "/v1/responses":
                    content = f"live-response:{Handler._responses_input_text(payload.get('input'))}"
                    if payload.get("stream"):
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
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream")
                        self.send_header("Cache-Control", "no-cache")
                        self.end_headers()
                        for event_name, event_payload in events:
                            self.wfile.write(f"event: {event_name}\n".encode("utf-8"))
                            self.wfile.write(f"data: {json.dumps(event_payload)}\n\n".encode("utf-8"))
                            self.wfile.flush()
                        self.wfile.write(b"data: [DONE]\n\n")
                        self.wfile.flush()
                        return
                    response = {
                        "id": "resp-stub",
                        "model": payload["model"],
                        "output_text": content,
                        "usage": {"input_tokens": 6, "output_tokens": 3, "total_tokens": 9},
                    }
                elif self.path == "/v1/messages":
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
                        "usage": {"input_tokens": 8, "output_tokens": 4},
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

            def do_GET(self) -> None:  # noqa: N802
                server_state = self.server.state  # type: ignore[attr-defined]
                server_state.requests.append(
                    {
                        "path": self.path,
                        "headers": dict(self.headers.items()),
                        "payload": None,
                    }
                )
                if self.path == "/v1/models":
                    response = {
                        "data": [
                            {"id": "openai/gpt-4o-mini", "owned_by": "stub", "context_window": 128000},
                            {"id": "openai/gpt-4.1-mini", "owned_by": "stub"},
                        ]
                    }
                    encoded = json.dumps(response).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(encoded)))
                    self.end_headers()
                    self.wfile.write(encoded)
                    return
                self.send_response(404)
                self.end_headers()

        return Handler



class APISurfaceTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.stub = _ProviderStubServer().start()
        self._previous_openrouter_secret = os.environ.get("ELEPHANT_OPENROUTER_API_KEY")
        self._previous_openai_secret = os.environ.get("ELEPHANT_OPENAI_API_KEY")
        self._previous_anthropic_secret = os.environ.get("ELEPHANT_ANTHROPIC_API_KEY")
        os.environ["ELEPHANT_OPENROUTER_API_KEY"] = "sk-api-test-123"
        os.environ["ELEPHANT_OPENAI_API_KEY"] = "sk-openai-test-456"
        os.environ["ELEPHANT_ANTHROPIC_API_KEY"] = "sk-anthropic-test-789"
        self.app = create_app(
            database_path=Path(self.tempdir.name) / "api.sqlite3",
            install_root=Path(self.tempdir.name),
        )

    def tearDown(self) -> None:
        if self._previous_openrouter_secret is None:
            os.environ.pop("ELEPHANT_OPENROUTER_API_KEY", None)
        else:
            os.environ["ELEPHANT_OPENROUTER_API_KEY"] = self._previous_openrouter_secret
        if self._previous_openai_secret is None:
            os.environ.pop("ELEPHANT_OPENAI_API_KEY", None)
        else:
            os.environ["ELEPHANT_OPENAI_API_KEY"] = self._previous_openai_secret
        if self._previous_anthropic_secret is None:
            os.environ.pop("ELEPHANT_ANTHROPIC_API_KEY", None)
        else:
            os.environ["ELEPHANT_ANTHROPIC_API_KEY"] = self._previous_anthropic_secret
        self.stub.close()
        self.tempdir.cleanup()

    def _provider_profile(
        self,
        *,
        profile_id: str = "provider-openrouter",
        provider_id: str = "openai-compatible",
        base_url: str | None = None,
        default_model: str | None = "openai/gpt-4o-mini",
        reference_id: str = "secret-openrouter-token",
        env_var: str = "ELEPHANT_OPENROUTER_API_KEY",
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "profile_id": profile_id,
            "provider_id": provider_id,
            "secret_references": [
                {
                    "reference_id": reference_id,
                    "provider_id": provider_id,
                    "secret_name": "api_token",
                    "secret_key": "api_key",
                    "metadata": {"env_var": env_var},
                }
            ],
        }
        if base_url is not None:
            payload["base_url"] = base_url
        if default_model is not None:
            payload["default_model"] = default_model
        if extra_headers:
            payload["extra_headers"] = extra_headers
        return payload

    def _dashboard_section(self, section: str) -> dict[str, Any]:
        response = self.app.dispatch("GET", f"/v1/internal/dashboard/{section}")
        self.assertEqual(response.status_code, 200)
        return response.payload["dashboard"]

    def _dashboard_sections(self, *sections: str) -> dict[str, Any]:
        top_level_keys = {
            "overview": ("overview", "herd", "states", "personal_models", "runtime", "learning"),
            "personal-models": ("personal_models",),
            "herd": ("herd", "states"),
            "runtime": ("herd", "states", "runtime"),
            "reflect": ("learning",),
            "chat": ("overview", "herd", "states", "personal_models", "runtime"),
            "evidence": ("evidence", "semantic_index_health"),
            "providers": ("providers",),
        }
        operation_keys = {
            "providers": ("models",),
            "skills": ("skills", "skill_affinities", "settings"),
            "tools": ("tools", "mcp", "settings"),
            "gateway": ("gateway",),
            "cron": ("cron",),
            "settings": ("settings",),
            "usage": ("usage",),
            "logs": ("logs",),
            "usage-logs": ("usage", "logs"),
        }
        merged = self._dashboard_section(sections[0])
        for section in sections[1:]:
            payload = self._dashboard_section(section)
            for key in top_level_keys.get(section, ()):
                merged[key] = payload[key]
            merged_operations = dict(merged.get("operations", {}))
            for operation_key in operation_keys.get(section, ()):
                merged_operations[operation_key] = payload["operations"][operation_key]
            merged["operations"] = merged_operations
        return merged

    @staticmethod
    def _body(payload: dict[str, object]) -> bytes:
        return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

