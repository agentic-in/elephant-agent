"""Integration tests for the vLLM Semantic Router provider adapter."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.auth.runtime import AuthProfile
from packages.models.provider_runtime import ProviderRuntimeResolver
from packages.models.providers.openai_compatible import OpenAICompatibleProviderConfig
from packages.models.providers.registry import InMemoryModelAdapterBuilderRegistry, ModelAdapterBuildContext
from packages.models.providers.vllm_semantic_router import (
    VSR_FALLBACK_BASE_URL_KEY,
    VSR_FALLBACK_MODEL_ID_KEY,
    VSR_ROUTING_POLICY_HEADER,
    VSR_ROUTING_POLICY_KEY,
    VllmSemanticRouterProviderAdapter,
)
from packages.models.runtime import CredentialSource, ModelRequest


class _StaticCredentialSource:
    def resolve(self, provider_id: str) -> dict[str, str]:
        return {}


class _VsrRouterStubServer:
    def __init__(self, *, status_code: int = 200) -> None:
        self.status_code = status_code
        self.requests: list[dict[str, object]] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._server.state = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    def start(self) -> "_VsrRouterStubServer":
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
                if self.path != "/v1/chat/completions":
                    self.send_response(404)
                    self.end_headers()
                    return
                if server_state.status_code != 200:
                    self.send_response(server_state.status_code)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    return
                user_content = payload["messages"][-1]["content"]
                response = {
                    "id": "chatcmpl-vsr-stub",
                    "model": payload["model"],
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": f"live-vsr:{user_content}",
                            }
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 5,
                        "completion_tokens": 4,
                        "total_tokens": 9,
                    },
                }
                encoded = json.dumps(response).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("x-vsr-selected-decision", "default-route")
                self.send_header("x-vsr-selected-model", "deepseek-chat")
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format: str, *args: object) -> None:
                return

        return Handler


class _DirectFallbackStubServer:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._server.state = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    def start(self) -> "_DirectFallbackStubServer":
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
                if self.path != "/v1/chat/completions":
                    self.send_response(404)
                    self.end_headers()
                    return
                user_content = payload["messages"][-1]["content"]
                response = {
                    "id": "chatcmpl-fallback-stub",
                    "model": payload["model"],
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": f"live-fallback:{user_content}",
                            }
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 4,
                        "completion_tokens": 3,
                        "total_tokens": 7,
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


class VllmSemanticRouterProviderIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router_server = _VsrRouterStubServer().start()
        self.resolver = ProviderRuntimeResolver.default()

    def tearDown(self) -> None:
        self.router_server.close()

    def _adapter(
        self,
        *,
        router_metadata: dict[str, str] | None = None,
    ) -> VllmSemanticRouterProviderAdapter:
        return VllmSemanticRouterProviderAdapter(
            router_metadata=router_metadata or {},
            config=OpenAICompatibleProviderConfig(
                provider_id="vllm-semantic-router",
                base_url=self.router_server.base_url,
                model_id="deepseek-chat",
            ),
            runtime_resolver=self.resolver,
            credential_source=_StaticCredentialSource(),
            adapter_id="integration.vsr",
        )

    def _request(self, *, prompt: str = "Route through semantic router.") -> ModelRequest:
        return ModelRequest(
            request_id="request-vsr-1",
            profile_id="profile-companion",
            session_id="session-vsr-1",
            provider_id="vllm-semantic-router",
            model_id="deepseek-chat",
            prompt=prompt,
            task="generate",
        )

    def test_integration_routes_chat_and_records_vsr_metadata(self) -> None:
        adapter = self._adapter()
        request = self._request()

        plan = adapter.plan_request(request, {})
        result = adapter.generate(request, {})

        self.assertEqual(plan.url, self.router_server.base_url + "/chat/completions")
        self.assertEqual(plan.request_family, "chat_completions")
        self.assertEqual(plan.transport_id, "openai_chat_compatible")
        self.assertIn("live-vsr:Route through semantic router.", result.content)
        self.assertEqual(
            result.metadata.get("vsr_response_header:x-vsr-selected-decision"),
            "default-route",
        )
        self.assertEqual(
            result.metadata.get("vsr_response_header:x-vsr-selected-model"),
            "deepseek-chat",
        )
        self.assertEqual(self.router_server.requests[0]["path"], "/v1/chat/completions")
        self.assertEqual(
            self.router_server.requests[0]["payload"]["model"],
            "deepseek-chat",
        )

    def test_integration_sends_routing_policy_header(self) -> None:
        adapter = self._adapter(router_metadata={VSR_ROUTING_POLICY_KEY: "latency_first"})
        request = self._request(prompt="Policy hint.")

        plan = adapter.plan_request(request, {})
        adapter.generate(request, {})

        self.assertEqual(plan.headers.get(VSR_ROUTING_POLICY_HEADER), "latency_first")
        request_headers = {
            str(key).lower(): str(value)
            for key, value in dict(self.router_server.requests[0]["headers"]).items()
        }
        self.assertEqual(request_headers.get("x-vsr-routing-policy"), "latency_first")

    def test_build_model_adapter_registry_selects_vsr_builder(self) -> None:
        profile = AuthProfile(
            profile_id="auth-vsr-default",
            provider_id="vllm-semantic-router",
            base_url=self.router_server.base_url,
            default_model="deepseek-chat",
            metadata={},
        )
        resolution = self.resolver.resolve(
            "vllm-semantic-router",
            model_id="deepseek-chat",
            base_url=self.router_server.base_url,
        )
        context = ModelAdapterBuildContext(
            profile=profile,
            resolution=resolution,
            runtime_resolver=self.resolver,
            credential_source=_StaticCredentialSource(),
            credentials={},
            adapter_id="integration.registry",
        )
        builder = InMemoryModelAdapterBuilderRegistry.default().select(context)
        self.assertEqual(builder.builder_id, "vllm-semantic-router")

    def test_integration_fallback_on_router_503(self) -> None:
        failing_router = _VsrRouterStubServer(status_code=503).start()
        fallback_server = _DirectFallbackStubServer().start()
        self.addCleanup(failing_router.close)
        self.addCleanup(fallback_server.close)
        adapter = VllmSemanticRouterProviderAdapter(
            router_metadata={
                VSR_FALLBACK_BASE_URL_KEY: fallback_server.base_url,
                VSR_FALLBACK_MODEL_ID_KEY: "direct-model",
            },
            config=OpenAICompatibleProviderConfig(
                provider_id="vllm-semantic-router",
                base_url=failing_router.base_url,
                model_id="deepseek-chat",
            ),
            runtime_resolver=self.resolver,
            credential_source=_StaticCredentialSource(),
            adapter_id="integration.vsr.fallback",
        )
        request = self._request(prompt="Fallback path.")

        result = adapter.generate(request, {})

        self.assertIn("live-fallback:Fallback path.", result.content)
        self.assertEqual(result.metadata.get("vsr_fallback"), "true")
        self.assertEqual(result.metadata.get("vsr_fallback_http_status"), "503")
        self.assertEqual(failing_router.requests[0]["path"], "/v1/chat/completions")
        self.assertEqual(fallback_server.requests[0]["path"], "/v1/chat/completions")
        self.assertEqual(fallback_server.requests[0]["payload"]["model"], "direct-model")


if __name__ == "__main__":
    unittest.main()
