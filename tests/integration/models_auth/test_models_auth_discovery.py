from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime
import json
import os
import sqlite3
import sys
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.models import DiscoveredProviderModel, SurfaceModelProviderCapability
from packages.auth import (
    AuthProfile,
    InMemoryAuthProfileStore,
    InMemorySecretStore,
    PersistentAuthProfileStore,
    PreviewAuthProviderCapability,
    ProfileCredentialResolver,
    ProviderCatalog,
    ProviderAuthState,
    ProviderProfileFactory,
    ProviderProfileInput,
    profile_from_input,
    SecretReference,
)
from packages.contracts import ContextBundle
from packages.contracts.layers import Episode
from packages.contracts.runtime import PersonalModelRuntimeState
from packages.models import (
    InMemoryModelAdapterRegistry,
    ProviderRuntimeResolver,
    ModelRequest,
    ModelTextResult,
    ModelUsage,
    PreviewModelProviderCapability,
    PromptEchoModelAdapter,
    StaticTextModelAdapter,
)
from packages.storage import RuntimeStorageRepository
from packages.tools import ToolRuntime, sync_custom_mcp_tools


class _ProviderCatalogStubServer:
    def __init__(self, *, path: str, payload: object) -> None:
        self.path = path
        self.payload = payload
        self.requests: list[str] = []
        self.last_headers: dict[str, str] = {}
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def start(self) -> "_ProviderCatalogStubServer":
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
                outer.requests.append(self.path)
                outer.last_headers = {
                    str(key): str(value) for key, value in self.headers.items()
                }
                if self.path != outer.path:
                    self.send_response(404)
                    self.end_headers()
                    return
                encoded = json.dumps(outer.payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format: str, *args: object) -> None:
                return

        return Handler


class _OllamaShowStubServer:
    def __init__(self, *, payload: object) -> None:
        self.payload = payload
        self.requests: list[str] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    def start(self) -> "_OllamaShowStubServer":
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
                outer.requests.append(f"GET {self.path}")
                self.send_response(404)
                self.end_headers()

            def do_POST(self) -> None:  # noqa: N802
                outer.requests.append(f"POST {self.path}")
                if self.path != "/api/show":
                    self.send_response(404)
                    self.end_headers()
                    return
                encoded = json.dumps(outer.payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format: str, *args: object) -> None:
                return

        return Handler


class ModelsAuthDiscoveryIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        from tempfile import TemporaryDirectory

        self.tempdir = TemporaryDirectory()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_surface_runtime_discovers_external_provider_credentials(self) -> None:
        database_path = Path(self.tempdir.name) / "provider-discovery.sqlite3"
        repository = RuntimeStorageRepository(database_path)
        repository.bootstrap()
        capability = SurfaceModelProviderCapability(
            repository=repository,
            fallback=mock.Mock(),
            secret_key_path=Path(self.tempdir.name) / "provider-secrets.key",
        )

        with mock.patch.dict(
            os.environ, {"COPILOT_GITHUB_TOKEN": "ghu-test"}, clear=False
        ):
            state = capability.discovered_provider_state("copilot")

        self.assertEqual(state.status, "authenticated")
        self.assertEqual(state.source, "env:COPILOT_GITHUB_TOKEN")
        self.assertEqual(state.transport_display_name, "OpenAI Responses")
        self.assertEqual(state.reasoning_efforts, ("minimal", "low", "medium", "high"))

    def test_surface_runtime_discovers_copilot_skips_classic_pat_env(self) -> None:
        database_path = (
            Path(self.tempdir.name) / "provider-discovery-copilot-pat.sqlite3"
        )
        repository = RuntimeStorageRepository(database_path)
        repository.bootstrap()
        capability = SurfaceModelProviderCapability(
            repository=repository,
            fallback=mock.Mock(),
            secret_key_path=Path(self.tempdir.name) / "provider-secrets.key",
        )

        with mock.patch.dict(
            os.environ,
            {"COPILOT_GITHUB_TOKEN": "ghp_classic_pat", "GH_TOKEN": "gho_oauth_token"},
            clear=False,
        ):
            state = capability.discovered_provider_state("copilot")

        self.assertEqual(state.status, "authenticated")
        self.assertEqual(state.source, "env:GH_TOKEN")

    def test_api_provider_list_surfaces_codex_and_copilot_discovery(self) -> None:
        from types import SimpleNamespace

        from apps.api.api_runtime_provider_methods import list_providers

        database_path = Path(self.tempdir.name) / "provider-api-list.sqlite3"
        repository = RuntimeStorageRepository(database_path)
        repository.bootstrap()
        capability = SurfaceModelProviderCapability(
            repository=repository,
            fallback=mock.Mock(),
            secret_key_path=Path(self.tempdir.name) / "provider-secrets.key",
        )
        codex_home = Path(self.tempdir.name) / ".codex"
        codex_home.mkdir(parents=True, exist_ok=True)
        (codex_home / "auth.json").write_text(
            json.dumps(
                {
                    "tokens": {
                        "access_token": "codex-api-token",
                        "refresh_token": "codex-refresh-token",
                    }
                }
            ),
            encoding="utf-8",
        )

        with (
            mock.patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}, clear=True),
            mock.patch(
                "packages.auth.discovery.subprocess.run",
                return_value=mock.Mock(stdout="gho-copilot-token\n"),
            ),
        ):
            payload = list_providers(SimpleNamespace(model_provider=capability))

        providers = {str(row["provider_id"]): row for row in payload["providers"]}
        self.assertEqual(providers["openai-codex"]["status"], "authenticated")
        self.assertIn("codex-cli", providers["openai-codex"]["source"])
        self.assertEqual(providers["copilot"]["status"], "authenticated")
        self.assertEqual(providers["copilot"]["source"], "gh auth token")

    def test_surface_runtime_discovers_models_with_saved_non_active_provider_key(
        self,
    ) -> None:
        database_path = Path(self.tempdir.name) / "provider-saved-key-discovery.sqlite3"
        repository = RuntimeStorageRepository(database_path)
        repository.bootstrap()
        capability = SurfaceModelProviderCapability(
            repository=repository,
            fallback=mock.Mock(),
            secret_key_path=Path(self.tempdir.name) / "provider-secrets.key",
        )
        reference = SecretReference(
            reference_id="secret-provider-openai-compatible-api-key",
            provider_id="openai-compatible",
            secret_name="api_token",
            secret_key="api_key",
        )
        repository.upsert_auth_profile(
            AuthProfile(
                profile_id="provider-openai-compatible",
                provider_id="openai-compatible",
                default_model="model-a",
                base_url="https://provider.example.test/v1",
                secret_references=(reference,),
            )
        )
        capability.store_secret_value(reference, "sk-saved-provider")

        def _fake_request_json(*, url: str, headers, timeout_seconds: float = 10.0):
            del timeout_seconds
            self.assertEqual(url, "https://provider.example.test/v1/models")
            self.assertEqual(
                dict(headers).get("Authorization"), "Bearer sk-saved-provider"
            )
            return {"data": [{"id": "model-a"}, {"id": "model-b"}]}

        with mock.patch(
            "packages.models.runtime_capability.request_json",
            side_effect=_fake_request_json,
        ):
            models = capability.discover_models(
                provider_id="openai-compatible", base_url=None
            )

        self.assertEqual(
            [model.model_id for model in models[:2]], ["model-a", "model-b"]
        )

    def test_surface_runtime_discovers_copilot_models_from_provider_specific_catalog_path(
        self,
    ) -> None:
        database_path = Path(self.tempdir.name) / "provider-copilot-models.sqlite3"
        repository = RuntimeStorageRepository(database_path)
        repository.bootstrap()
        capability = SurfaceModelProviderCapability(
            repository=repository,
            fallback=mock.Mock(),
            secret_key_path=Path(self.tempdir.name) / "provider-secrets.key",
        )
        server = _ProviderCatalogStubServer(
            path="/models",
            payload=[
                {
                    "id": "claude-opus-4.6",
                    "capabilities": {"type": "chat"},
                },
                {
                    "id": "gpt-5.4",
                    "context_window": 128000,
                    "max_output_tokens": 16384,
                    "capabilities": {
                        "type": "chat",
                        "supports": {
                            "reasoning_effort": ["minimal", "low", "medium", "high"]
                        },
                    },
                },
            ],
        ).start()
        self.addCleanup(server.close)

        with mock.patch.dict(
            os.environ, {"COPILOT_GITHUB_TOKEN": "ghu-test"}, clear=False
        ):
            models = capability.discover_models(
                provider_id="copilot", base_url=server.base_url
            )

        self.assertEqual(server.requests, ["/models"])
        self.assertEqual(server.last_headers.get("Authorization"), "Bearer ghu-test")
        self.assertEqual(server.last_headers.get("Openai-Intent"), "conversation-edits")
        self.assertEqual(
            [model.model_id for model in models[:2]], ["claude-opus-4.6", "gpt-5.4"]
        )

    def test_surface_runtime_detects_copilot_claude_context_with_bearer_auth(
        self,
    ) -> None:
        database_path = (
            Path(self.tempdir.name) / "provider-copilot-claude-context.sqlite3"
        )
        repository = RuntimeStorageRepository(database_path)
        repository.bootstrap()
        capability = SurfaceModelProviderCapability(
            repository=repository,
            fallback=mock.Mock(),
            secret_key_path=Path(self.tempdir.name) / "provider-secrets.key",
        )
        requests: list[tuple[str, dict[str, str]]] = []

        def _fake_request_json(*, url: str, headers, timeout_seconds: float = 10.0):
            del timeout_seconds
            normalized_headers = {
                str(key): str(value) for key, value in dict(headers).items()
            }
            requests.append((url, normalized_headers))
            if url.endswith("/models/claude-sonnet-4.6"):
                return {
                    "id": "claude-sonnet-4.6",
                    "context_window": 200000,
                    "max_output_tokens": 8192,
                }
            raise AssertionError(f"unexpected url {url}")

        with (
            mock.patch.dict(
                os.environ, {"COPILOT_GITHUB_TOKEN": "ghu-test"}, clear=False
            ),
            mock.patch.object(
                capability,
                "discover_models",
                return_value=(
                    DiscoveredProviderModel(
                        model_id="claude-sonnet-4.6",
                        label="claude-sonnet-4.6",
                        context_window_tokens=None,
                    ),
                ),
            ),
            mock.patch(
                "packages.models.runtime_capability.request_json",
                side_effect=_fake_request_json,
            ),
        ):
            context_window = capability.detect_context_window(
                provider_id="copilot",
                base_url="https://api.githubcopilot.com",
                model_id="claude-sonnet-4.6",
            )

        self.assertEqual(context_window, 200000)
        self.assertEqual(
            [url for url, _ in requests],
            [
                "https://api.githubcopilot.com/models/claude-sonnet-4.6",
            ],
        )
        detail_headers = requests[-1][1]
        self.assertEqual(detail_headers.get("Authorization"), "Bearer ghu-test")
        self.assertEqual(detail_headers.get("anthropic-version"), "2023-06-01")
        self.assertEqual(detail_headers.get("Openai-Intent"), "conversation-edits")

    def test_surface_runtime_falls_back_to_curated_codex_models_when_live_probe_fails(
        self,
    ) -> None:
        database_path = Path(self.tempdir.name) / "provider-codex-models.sqlite3"
        repository = RuntimeStorageRepository(database_path)
        repository.bootstrap()
        capability = SurfaceModelProviderCapability(
            repository=repository,
            fallback=mock.Mock(),
            secret_key_path=Path(self.tempdir.name) / "provider-secrets.key",
        )

        with mock.patch(
            "packages.models.runtime_capability.request_json",
            side_effect=RuntimeError("boom"),
        ):
            models = capability.discover_models(
                provider_id="openai-codex",
                base_url="https://chatgpt.com/backend-api/codex",
            )

        self.assertGreaterEqual(len(models), 4)
        self.assertEqual(
            [model.model_id for model in models[:4]],
            ["gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex", "gpt-5.3-codex-spark"],
        )
        self.assertTrue(all(model.source == "catalog-hint" for model in models))
        gpt5 = next(model for model in models if model.model_id == "gpt-5.4")
        gpt5_mini = next(model for model in models if model.model_id == "gpt-5.4-mini")
        spark = next(
            model for model in models if model.model_id == "gpt-5.3-codex-spark"
        )
        self.assertEqual(gpt5.context_window_tokens, 1_050_000)
        self.assertEqual(gpt5_mini.context_window_tokens, 400_000)
        self.assertEqual(spark.context_window_tokens, 128_000)
        self.assertEqual(gpt5.metadata["reasoning_efforts"], "minimal,low,medium,high")

    def test_surface_runtime_uses_model_specific_context_hints_when_live_probe_fails(
        self,
    ) -> None:
        database_path = Path(self.tempdir.name) / "provider-context-hints.sqlite3"
        repository = RuntimeStorageRepository(database_path)
        repository.bootstrap()
        capability = SurfaceModelProviderCapability(
            repository=repository,
            fallback=mock.Mock(),
            secret_key_path=Path(self.tempdir.name) / "provider-secrets.key",
        )

        with mock.patch(
            "packages.models.runtime_capability.request_json",
            side_effect=RuntimeError("boom"),
        ):
            minimax_models = capability.discover_models(
                provider_id="minimax",
                base_url="https://api.minimaxi.com/v1",
            )
            qwen_models = capability.discover_models(
                provider_id="qwen-oauth",
                base_url="https://portal.qwen.ai/v1",
            )
            xiaomi_models = capability.discover_models(
                provider_id="xiaomi",
                base_url="https://api.xiaomimimo.com/v1",
            )

        minimax = next(
            model for model in minimax_models if model.model_id == "MiniMax-M2.7"
        )
        qwen = next(
            model for model in qwen_models if model.model_id == "qwen3-coder-plus"
        )
        mimo_pro = next(
            model for model in xiaomi_models if model.model_id == "mimo-v2-pro"
        )
        mimo_omni = next(
            model for model in xiaomi_models if model.model_id == "mimo-v2-omni"
        )
        self.assertEqual(minimax.context_window_tokens, 204_800)
        self.assertEqual(qwen.context_window_tokens, 1_000_000)
        self.assertEqual(mimo_pro.context_window_tokens, 1_000_000)
        self.assertEqual(mimo_omni.context_window_tokens, 256_000)

    def test_surface_runtime_detects_ollama_runtime_context_from_show_api(self) -> None:
        database_path = Path(self.tempdir.name) / "provider-ollama-context.sqlite3"
        repository = RuntimeStorageRepository(database_path)
        repository.bootstrap()
        capability = SurfaceModelProviderCapability(
            repository=repository,
            fallback=mock.Mock(),
            secret_key_path=Path(self.tempdir.name) / "provider-secrets.key",
        )
        server = _OllamaShowStubServer(
            payload={
                "parameters": "temperature 0.7\nnum_ctx 32768",
                "model_info": {"llama.context_length": 131072},
            },
        ).start()
        self.addCleanup(server.close)

        context_window = capability.detect_context_window(
            provider_id="ollama",
            base_url=server.base_url,
            model_id="llama3.2",
        )

        self.assertEqual(context_window, 32_768)
        self.assertEqual(server.requests, ["GET /v1/models", "POST /api/show"])

    def test_surface_runtime_uses_models_dev_fallback_after_endpoint_metadata_miss(
        self,
    ) -> None:
        database_path = Path(self.tempdir.name) / "provider-models-dev-context.sqlite3"
        repository = RuntimeStorageRepository(database_path)
        repository.bootstrap()
        capability = SurfaceModelProviderCapability(
            repository=repository,
            fallback=mock.Mock(),
            secret_key_path=Path(self.tempdir.name) / "provider-secrets.key",
        )

        with (
            mock.patch(
                "packages.models.runtime_capability.request_json",
                side_effect=RuntimeError("boom"),
            ),
            mock.patch(
                "packages.models.model_metadata.fetch_models_dev_registry",
                return_value={
                    "alibaba": {
                        "models": {
                            "qwen3-coder-plus": {
                                "limit": {
                                    "context": 1_000_000,
                                    "output": 65_536,
                                }
                            }
                        }
                    }
                },
            ),
        ):
            context_window = capability.detect_context_window(
                provider_id="openai-compatible",
                base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                model_id="qwen3-coder-plus",
            )

        self.assertEqual(context_window, 1_000_000)

    def test_surface_runtime_does_not_invent_placeholder_models_for_openai_compatible(
        self,
    ) -> None:
        database_path = (
            Path(self.tempdir.name) / "provider-openai-compatible-models.sqlite3"
        )
        repository = RuntimeStorageRepository(database_path)
        repository.bootstrap()
        capability = SurfaceModelProviderCapability(
            repository=repository,
            fallback=mock.Mock(),
            secret_key_path=Path(self.tempdir.name) / "provider-secrets.key",
        )

        with mock.patch(
            "packages.models.runtime_capability.request_json",
            side_effect=RuntimeError("boom"),
        ):
            models = capability.discover_models(
                provider_id="openai-compatible",
                base_url="https://api.example.test/v1",
            )

        self.assertEqual(models, ())

    def test_surface_runtime_discovers_claude_code_from_local_credentials(self) -> None:
        database_path = Path(self.tempdir.name) / "provider-claude-code.sqlite3"
        repository = RuntimeStorageRepository(database_path)
        repository.bootstrap()
        capability = SurfaceModelProviderCapability(
            repository=repository,
            fallback=mock.Mock(),
            secret_key_path=Path(self.tempdir.name) / "provider-secrets.key",
        )
        claude_home = Path(self.tempdir.name) / ".claude"
        claude_home.mkdir(parents=True, exist_ok=True)
        (claude_home / ".credentials.json").write_text(
            json.dumps(
                {
                    "claudeAiOauth": {
                        "accessToken": "sk-ant-oat-claude-code-token",
                        "refreshToken": "refresh-token",
                        "expiresAt": "2999-01-01T00:00:00+00:00",
                    }
                }
            ),
            encoding="utf-8",
        )

        with mock.patch("pathlib.Path.home", return_value=Path(self.tempdir.name)):
            state = capability.discovered_provider_state("claude-code")

        self.assertEqual(state.status, "authenticated")
        self.assertIn("claude-code-oauth", state.source)

    def test_surface_runtime_discovers_copilot_acp_process(self) -> None:
        database_path = Path(self.tempdir.name) / "provider-copilot-acp.sqlite3"
        repository = RuntimeStorageRepository(database_path)
        repository.bootstrap()
        capability = SurfaceModelProviderCapability(
            repository=repository,
            fallback=mock.Mock(),
            secret_key_path=Path(self.tempdir.name) / "provider-secrets.key",
        )
        fake_bin = Path(self.tempdir.name) / "copilot"
        fake_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_bin.chmod(0o755)

        with mock.patch.dict(
            os.environ,
            {"PATH": f"{self.tempdir.name}:{os.environ.get('PATH', '')}"},
            clear=False,
        ):
            state = capability.discovered_provider_state("copilot-acp")

        self.assertEqual(state.status, "authenticated")
        self.assertTrue(state.source.startswith("command:"))
        self.assertEqual(state.base_url, "acp://copilot")

    def test_auth_profile_factory_supports_compatible_endpoint_inputs(self) -> None:
        profile_input = ProviderProfileInput(
            profile_id="auth-custom",
            provider_id="custom-compatible",
            secret_references=(),
            priority=3,
            metadata={"source": "manual"},
        )

        profile = profile_from_input(
            profile_input,
            base_url="https://example.invalid/v1",
            default_model="mistral-small",
            transport_id="openai-compatible",
            auth_method="bearer",
            provider_kind="custom",
            extra_headers={"x-tenant": "elephant"},
        )

        self.assertEqual(profile.provider_id, "custom-compatible")
        self.assertEqual(profile.transport_id, "openai-compatible")
        self.assertEqual(profile.base_url, "https://example.invalid/v1")
        self.assertEqual(profile.default_model, "mistral-small")
        self.assertEqual(profile.auth_method, "bearer")
        self.assertEqual(profile.provider_kind, "custom")
        self.assertEqual(profile.extra_headers["x-tenant"], "elephant")


if __name__ == "__main__":
    unittest.main()
