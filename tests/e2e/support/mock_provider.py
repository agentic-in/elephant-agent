from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from typing import Any


class MockOpenAICompatibleProvider:
    """Small OpenAI-compatible provider used by installed-command e2e tests."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.last_payload: dict[str, Any] | None = None
        self.last_path: str | None = None
        self.fail_chat = False
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    def start(self) -> "MockOpenAICompatibleProvider":
        self._thread.start()
        return self

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                outer.requests.append({"method": "GET", "path": self.path, "payload": None})
                if self.path != "/v1/models":
                    self.send_response(404)
                    self.end_headers()
                    return
                self._send_json(
                    {
                        "object": "list",
                        "data": [
                            {
                                "id": "openai/gpt-4o-mini",
                                "owned_by": "e2e-stub",
                                "context_window": 128000,
                                "max_output_tokens": 16384,
                            },
                            {
                                "id": "openai/gpt-4.1-mini",
                                "owned_by": "e2e-stub",
                                "context_window": 1047576,
                                "max_output_tokens": 32768,
                            },
                        ],
                    }
                )

            def do_POST(self) -> None:  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                payload = json.loads(body.decode("utf-8"))
                outer.last_payload = payload
                outer.last_path = self.path
                outer.requests.append({"method": "POST", "path": self.path, "payload": payload})

                if self.path != "/v1/chat/completions":
                    self.send_response(404)
                    self.end_headers()
                    return
                if outer.fail_chat:
                    self._send_json(
                        {"error": {"message": "stub provider is unavailable", "type": "server_error"}},
                        status=503,
                    )
                    return

                prompt_text = str(payload["messages"][-1]["content"])
                if "ELEPHANT_DASHBOARD_OK" in prompt_text:
                    content = "ELEPHANT_DASHBOARD_OK"
                elif "ELEPHANT_INSTALLED_OK" in prompt_text:
                    content = "ELEPHANT_INSTALLED_OK"
                elif "ELEPHANT_SMOKE_OK" in prompt_text:
                    content = "ELEPHANT_SMOKE_OK"
                else:
                    content = f"live-chat:{prompt_text}"

                if payload.get("stream"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    midpoint = max(1, len(content) // 2)
                    for chunk in (content[:midpoint], content[midpoint:]):
                        event = {
                            "id": "chatcmpl-e2e-stub",
                            "model": payload["model"],
                            "choices": [{"delta": {"role": "assistant", "content": chunk}}],
                        }
                        self.wfile.write(f"data: {json.dumps(event)}\n\n".encode("utf-8"))
                        self.wfile.flush()
                    final_event = {
                        "id": "chatcmpl-e2e-stub",
                        "model": payload["model"],
                        "choices": [{"delta": {}, "finish_reason": "stop"}],
                        "usage": {
                            "prompt_tokens": 7,
                            "completion_tokens": 3,
                            "total_tokens": 10,
                            "prompt_tokens_details": {"cached_tokens": 2},
                        },
                    }
                    self.wfile.write(f"data: {json.dumps(final_event)}\n\n".encode("utf-8"))
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                    return

                self._send_json(
                    {
                        "id": "chatcmpl-e2e-stub",
                        "model": payload["model"],
                        "choices": [{"message": {"role": "assistant", "content": content}}],
                        "usage": {
                            "prompt_tokens": 7,
                            "completion_tokens": 3,
                            "total_tokens": 10,
                            "prompt_tokens_details": {"cached_tokens": 2},
                        },
                    }
                )

            def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
                encoded = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        return Handler

