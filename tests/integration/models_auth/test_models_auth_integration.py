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


class ModelsAuthIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        from tempfile import TemporaryDirectory

        self.tempdir = TemporaryDirectory()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_secret_reference_resolution_returns_redacted_bundle(self) -> None:
        secret_store = InMemorySecretStore()
        reference = SecretReference(
            reference_id="secret-openai-token",
            provider_id="openai",
            secret_name="api_token",
            secret_key="api_key",
        )
        secret_store.put(reference.reference_id, "sk-test-123")
        resolver = ProfileCredentialResolver(secret_store)
        profile = AuthProfile(
            profile_id="auth-openai-default",
            provider_id="openai",
            secret_references=(reference,),
            priority=10,
        )

        bundle = resolver.resolve(profile)

        self.assertEqual(bundle.as_mapping(), {"api_key": "sk-test-123"})
        self.assertEqual(bundle.redacted_mapping(), {"api_key": "***"})
        self.assertNotIn("sk-test-123", repr(bundle))

    def test_preview_auth_provider_selects_provider_profile(self) -> None:
        secret_store = InMemorySecretStore()
        reference = SecretReference(
            reference_id="secret-anthropic-token",
            provider_id="anthropic",
            secret_name="api_token",
            secret_key="api_key",
        )
        secret_store.put(reference.reference_id, "anthropic-secret")
        profile = AuthProfile(
            profile_id="auth-anthropic-default",
            provider_id="anthropic",
            secret_references=(reference,),
            priority=1,
        )
        profile_store = InMemoryAuthProfileStore((profile,))
        capability = PreviewAuthProviderCapability(
            profile_store=profile_store,
            resolver=ProfileCredentialResolver(secret_store),
        )

        credentials = capability.resolve("anthropic")

        self.assertEqual(credentials, {"api_key": "anthropic-secret"})

    def test_model_registry_routes_provider_neutral_adapters(self) -> None:
        registry = InMemoryModelAdapterRegistry(
            (
                PromptEchoModelAdapter(
                    adapter_id="adapter.preview.echo",
                    provider_id="preview.echo",
                    model_id="echo-1",
                ),
                StaticTextModelAdapter(
                    adapter_id="adapter.preview.static",
                    provider_id="preview.static",
                    model_id="static-1",
                    response_template="[{provider_id}/{model_id}] {prompt} :: {credential_keys}",
                ),
            )
        )

        self.assertEqual(
            registry.select("preview.echo").descriptor.adapter_id,
            "adapter.preview.echo",
        )
        self.assertEqual(
            registry.select("preview.static").descriptor.adapter_id,
            "adapter.preview.static",
        )
        self.assertEqual(len(registry.list()), 2)

    def test_provider_runtime_lists_catalog_and_guided_setup(self) -> None:
        resolver = ProviderRuntimeResolver.default()

        catalog = resolver.list_catalog()
        provider_ids = {record.provider_id for record in catalog}
        openai_compatible = next(
            record for record in catalog if record.provider_id == "openai-compatible"
        )
        openrouter = next(
            record for record in catalog if record.provider_id == "openrouter"
        )
        anthropic = next(
            record for record in catalog if record.provider_id == "anthropic"
        )
        claude_code = next(
            record for record in catalog if record.provider_id == "claude-code"
        )
        copilot = next(record for record in catalog if record.provider_id == "copilot")
        openai_codex = next(
            record for record in catalog if record.provider_id == "openai-codex"
        )
        google = next(record for record in catalog if record.provider_id == "google")
        google_oauth = next(
            record for record in catalog if record.provider_id == "google-gemini-cli"
        )
        perplexity = next(
            record for record in catalog if record.provider_id == "perplexity"
        )
        volcengine = next(
            record for record in catalog if record.provider_id == "volcengine"
        )
        qianfan = next(
            record for record in catalog if record.provider_id == "baidu-qianfan"
        )
        tokenhub = next(
            record for record in catalog if record.provider_id == "tencent-tokenhub"
        )
        xiaomi = next(record for record in catalog if record.provider_id == "xiaomi")
        minimax = next(record for record in catalog if record.provider_id == "minimax")
        ollama = next(record for record in catalog if record.provider_id == "ollama")
        guide = resolver.build_setup_guide("openai-compatible")

        self.assertTrue(
            {
                "openai-compatible",
                "openai",
                "openai-codex",
                "openrouter",
                "anthropic",
                "claude-code",
                "copilot",
                "google",
                "google-gemini-cli",
                "groq",
                "deepseek",
                "xai",
                "cohere",
                "perplexity",
                "cerebras",
                "nvidia",
                "xiaomi",
                "mistral",
                "together",
                "huggingface",
                "siliconflow",
                "volcengine",
                "baidu-qianfan",
                "tencent-hunyuan",
                "tencent-tokenhub",
                "stepfun",
                "qwen-oauth",
                "zai",
                "alibaba",
                "moonshot",
                "moonshot-cn",
                "minimax",
                "minimax-cn",
                "modelscope",
                "opencode-zen",
                "opencode-go",
                "kilocode",
                "ollama",
                "vllm",
                "vllm-semantic-router",
            }.issubset(provider_ids)
        )
        self.assertEqual(openai_compatible.transport_id, "openai_chat_compatible")
        self.assertEqual(openai_compatible.capability_flags, ("chat", "embeddings"))
        self.assertEqual(
            openai_compatible.metadata["capability_truth_source"], "runtime_execution"
        )
        self.assertIn("base url", openai_compatible.onboarding_hint.lower())
        self.assertEqual(openrouter.transport_id, "openai_chat_compatible")
        self.assertEqual(openrouter.default_base_url, "https://openrouter.ai/api/v1")
        self.assertIn("aggregator", openrouter.metadata["surface"])
        self.assertIn("base_url", guide.required_config_keys)
        self.assertIn("model_id", guide.required_config_keys)
        self.assertEqual(guide.metadata["capability_truth_source"], "runtime_execution")
        self.assertIn(
            "Run a provider test or health flow", " ".join(guide.quickstart_steps)
        )
        self.assertEqual(anthropic.transport_id, "anthropic_messages")
        self.assertEqual(anthropic.auth_type, "oauth_external")
        self.assertEqual(anthropic.capability_flags, ("chat",))
        self.assertIn("streaming", anthropic.metadata["unsupported_capabilities"])
        self.assertEqual(claude_code.transport_id, "anthropic_messages")
        self.assertEqual(claude_code.auth_type, "oauth_external")
        self.assertEqual(
            claude_code.metadata["external_source"], "claude_code_credentials"
        )
        self.assertEqual(copilot.transport_id, "openai_responses")
        self.assertEqual(copilot.auth_type, "oauth_external")
        self.assertEqual(
            copilot.reasoning_efforts, ("minimal", "low", "medium", "high")
        )
        self.assertEqual(openai_codex.transport_id, "openai_responses")
        self.assertEqual(openai_codex.auth_type, "oauth_external")
        self.assertEqual(openai_codex.metadata["endpoint_path"], "/responses")
        self.assertEqual(google.transport_id, "openai_chat_compatible")
        self.assertEqual(google_oauth.auth_type, "oauth_external")
        self.assertEqual(google_oauth.default_base_url, "cloudcode-pa://google")
        self.assertEqual(perplexity.transport_id, "openai_responses")
        self.assertEqual(perplexity.default_base_url, "https://api.perplexity.ai/v1")
        self.assertEqual(volcengine.metadata["endpoint_path"], "/chat/completions")
        self.assertEqual(qianfan.metadata["endpoint_path"], "/chat/completions")
        self.assertEqual(
            tokenhub.default_base_url, "https://tokenhub.tencentmaas.com/v1"
        )
        self.assertEqual(
            tokenhub.env_var_names, ("TOKENHUB_API_KEY", "TENCENT_TOKENHUB_API_KEY")
        )
        self.assertEqual(xiaomi.default_model_id, "mimo-v2-pro")
        self.assertEqual(
            xiaomi.model_hints, ("mimo-v2-pro", "mimo-v2-omni", "mimo-v2-flash")
        )
        self.assertEqual(minimax.transport_id, "openai_chat_compatible")
        self.assertEqual(minimax.default_base_url, "https://api.minimaxi.com/v1")
        self.assertEqual(minimax.metadata["image_input_support"], "token_plan_mcp_only")
        self.assertEqual(ollama.transport_id, "openai_chat_compatible")

    def test_provider_runtime_resolves_transport_and_runtime_metadata(self) -> None:
        resolver = ProviderRuntimeResolver.default()

        resolution = resolver.resolve(
            "openai-compatible",
            model_id="gpt-4o-mini",
            base_url="https://example.invalid/v1",
        )

        self.assertEqual(resolution.transport_id, "openai_chat_compatible")
        self.assertEqual(resolution.request_family, "chat_completions")
        self.assertEqual(resolution.model_id, "gpt-4o-mini")
        self.assertEqual(resolution.base_url, "https://example.invalid/v1")
        self.assertTrue(resolution.supports_streaming)
        self.assertTrue(resolution.supports_embeddings)
        self.assertTrue(resolution.supports_tools)
        self.assertFalse(resolution.supports_reasoning)
        self.assertEqual(resolution.capability_flags, ("chat", "embeddings"))
        self.assertEqual(
            resolution.provider_metadata["capability_truth_source"], "runtime_execution"
        )
        self.assertNotIn(
            "tools", resolution.provider_metadata["unsupported_capabilities"]
        )

        minimax_resolution = resolver.resolve("minimax", model_id="MiniMax-M2.5")

        self.assertEqual(minimax_resolution.transport_id, "openai_chat_compatible")
        self.assertEqual(minimax_resolution.request_family, "chat_completions")
        self.assertEqual(minimax_resolution.base_url, "https://api.minimaxi.com/v1")

        copilot_claude = resolver.resolve("copilot", model_id="claude-sonnet-4.6")
        self.assertEqual(copilot_claude.transport_id, "anthropic_messages")
        self.assertFalse(copilot_claude.supports_reasoning)

        copilot_gpt5 = resolver.resolve("copilot", model_id="gpt-5.4")
        self.assertEqual(copilot_gpt5.transport_id, "openai_responses")
        self.assertTrue(copilot_gpt5.supports_reasoning)
        self.assertEqual(
            copilot_gpt5.reasoning_efforts, ("minimal", "low", "medium", "high")
        )

        openai_codex = resolver.resolve("openai-codex", model_id="gpt-5.4")
        self.assertEqual(openai_codex.transport_id, "openai_responses")
        self.assertEqual(openai_codex.endpoint_path, "/responses")
        self.assertEqual(openai_codex.provider_metadata["endpoint_path"], "/responses")

    def test_preview_model_capability_uses_resolved_credentials(self) -> None:
        secret_store = InMemorySecretStore()
        reference = SecretReference(
            reference_id="secret-openai-token",
            provider_id="openai",
            secret_name="api_token",
            secret_key="api_key",
        )
        secret_store.put(reference.reference_id, "sk-test-456")
        profile_store = InMemoryAuthProfileStore(
            (
                AuthProfile(
                    profile_id="auth-openai-default",
                    provider_id="openai",
                    secret_references=(reference,),
                    priority=10,
                ),
            )
        )
        auth_capability = PreviewAuthProviderCapability(
            profile_store=profile_store,
            resolver=ProfileCredentialResolver(secret_store),
        )
        model_capability = PreviewModelProviderCapability(
            adapter=PromptEchoModelAdapter(
                adapter_id="adapter.preview.echo",
                provider_id="openai",
                model_id="gpt-preview",
            ),
            credential_source=auth_capability,
        )

        profile = PersonalModelRuntimeState(
            profile_id="profile-companion",
            display_name="Elephant Agent",
            mode="companion",
            enabled_capabilities=("model.preview",),
        )
        session = Episode(
            episode_id="session-123",
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
            instruction_refs=("docs/agent/task-cards/ux-1-model-and-auth-adapters.md",),
            token_budget=1024,
        )

        result = model_capability.generate(
            profile=profile,
            session=session,
            context=context,
            prompt="Summarize the integration state without leaking secrets.",
        )

        self.assertEqual(result.outcome, "ok")
        self.assertIn("openai/gpt-preview", result.summary)
        self.assertIn("creds: api_key", result.summary)
        self.assertNotIn("sk-test-456", result.summary)

    def test_surface_runtime_includes_enabled_custom_mcp_tools_in_model_request(
        self,
    ) -> None:
        database_path = Path(self.tempdir.name) / "surface-runtime-mcp.sqlite3"
        repository = RuntimeStorageRepository(database_path)
        repository.bootstrap()
        tool_runtime = ToolRuntime()
        sync_custom_mcp_tools(
            tool_runtime,
            config_path=Path(self.tempdir.name) / "global-config.yaml",
            config={
                "mcp_servers": {
                    "filesystem": {
                        "label": "Filesystem",
                        "transport": "stdio",
                        "command": "npx",
                        "args": [
                            "-y",
                            "@modelcontextprotocol/server-filesystem",
                            "/tmp/demo",
                        ],
                        "tools": {
                            "read_file": {
                                "display_name": "Read File",
                                "description": "Read one file from the mounted elephant file area.",
                                "reads_state": True,
                                "schema": {
                                    "type": "object",
                                    "properties": {"path": {"type": "string"}},
                                    "required": ["path"],
                                },
                            },
                            "write_file": {
                                "display_name": "Write File",
                                "description": "Write one file in the mounted elephant file area.",
                                "writes_state": True,
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "path": {"type": "string"},
                                        "content": {"type": "string"},
                                    },
                                    "required": ["path", "content"],
                                },
                            },
                        },
                    }
                },
                "mcp_overrides": {
                    "filesystem:write_file": {"enabled": False},
                },
            },
            cwd=ROOT,
        )
        capability = SurfaceModelProviderCapability(
            repository=repository,
            fallback=mock.Mock(),
            secret_key_path=Path(self.tempdir.name) / "provider-secrets.key",
            tool_runtime=tool_runtime,
        )
        captured_requests: list[ModelRequest] = []

        class _CapturingAdapter:
            def generate(
                self, request: ModelRequest, credentials: dict[str, str]
            ) -> ModelTextResult:
                captured_requests.append(request)
                return ModelTextResult(
                    result_id="result-mcp-tools",
                    request_id=request.request_id,
                    adapter_id="adapter.capture",
                    provider_id=request.provider_id,
                    model_id=request.model_id,
                    task="generate",
                    content="captured",
                    usage=ModelUsage(),
                    metadata={
                        "transport_id": "openai_chat_completions",
                        "credential_keys": ",".join(sorted(credentials)),
                    },
                )

        profile = PersonalModelRuntimeState(
            profile_id="profile-companion",
            display_name="Elephant Agent",
            mode="companion",
            enabled_capabilities=("model.surface",),
        )
        session = Episode(
            episode_id="session-mcp-tools",
            state_id="state:test",
            personal_model_id=profile.profile_id,
            entry_surface="test",
            elephant_id="elephant-1",
            status="open",
            started_at=datetime(2026, 1, 1),
            updated_at=datetime(2026, 1, 1),
        )
        context = ContextBundle(
            bundle_id="bundle-mcp-tools",
            episode_id=session.episode_id,
            instruction_refs=("docs/agent/task-cards/ux-1-model-and-auth-adapters.md",),
            token_budget=1024,
        )
        credential_bundle = mock.Mock()
        credential_bundle.as_mapping.return_value = {"api_key": "sk-test-789"}
        active_profile = mock.Mock(
            provider_id="openai-compatible",
            default_model="openai/gpt-4o-mini",
            base_url="https://api.example.test/v1",
            metadata={},
            profile_id="provider-openai-compatible",
        )

        with (
            mock.patch.object(
                capability, "_profile_for_role", return_value=active_profile
            ),
            mock.patch.object(
                capability.credential_resolver,
                "resolve",
                return_value=credential_bundle,
            ),
            mock.patch(
                "packages.models.runtime_capability.build_model_adapter",
                return_value=_CapturingAdapter(),
            ),
        ):
            result = capability.generate(
                profile=profile,
                session=session,
                context=context,
                prompt="Use any enabled tools if needed.",
            )

        self.assertEqual(result.outcome, "ok")
        self.assertEqual(len(captured_requests), 1)
        request = captured_requests[0]
        self.assertEqual(
            [tool["function"]["name"] for tool in request.tools],
            ["mcp.filesystem.read_file"],
        )
        self.assertEqual(
            request.tools[0]["function"]["parameters"],
            {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        )

    def test_surface_runtime_adds_tool_fallback_prompt_without_native_tool_calling(
        self,
    ) -> None:
        database_path = (
            Path(self.tempdir.name) / "surface-runtime-fallback-tools.sqlite3"
        )
        repository = RuntimeStorageRepository(database_path)
        repository.bootstrap()
        tool_runtime = ToolRuntime()
        sync_custom_mcp_tools(
            tool_runtime,
            config_path=Path(self.tempdir.name) / "global-config.yaml",
            config={
                "mcp_servers": {
                    "filesystem": {
                        "label": "Filesystem",
                        "transport": "stdio",
                        "command": "npx",
                        "args": [
                            "-y",
                            "@modelcontextprotocol/server-filesystem",
                            "/tmp/demo",
                        ],
                        "tools": {
                            "read_file": {
                                "display_name": "Read File",
                                "description": "Read one file from the mounted elephant file area.",
                                "reads_state": True,
                                "schema": {
                                    "type": "object",
                                    "properties": {"path": {"type": "string"}},
                                    "required": ["path"],
                                },
                            },
                        },
                    }
                },
            },
            cwd=ROOT,
        )
        capability = SurfaceModelProviderCapability(
            repository=repository,
            fallback=mock.Mock(),
            secret_key_path=Path(self.tempdir.name) / "provider-secrets.key",
            tool_runtime=tool_runtime,
        )
        captured_requests: list[ModelRequest] = []

        class _CapturingAdapter:
            def generate(
                self, request: ModelRequest, credentials: dict[str, str]
            ) -> ModelTextResult:
                captured_requests.append(request)
                return ModelTextResult(
                    result_id="result-fallback-tools",
                    request_id=request.request_id,
                    adapter_id="adapter.capture",
                    provider_id=request.provider_id,
                    model_id=request.model_id,
                    task="generate",
                    content="captured",
                    usage=ModelUsage(),
                    metadata={
                        "transport_id": "legacy_chat",
                        "credential_keys": ",".join(sorted(credentials)),
                    },
                )

        profile = PersonalModelRuntimeState(
            profile_id="profile-companion",
            display_name="Elephant Agent",
            mode="companion",
            enabled_capabilities=("model.surface",),
        )
        session = Episode(
            episode_id="session-fallback-tools",
            state_id="state:test",
            personal_model_id=profile.profile_id,
            entry_surface="test",
            elephant_id="elephant-1",
            status="open",
            started_at=datetime(2026, 1, 1),
            updated_at=datetime(2026, 1, 1),
        )
        context = ContextBundle(
            bundle_id="bundle-fallback-tools",
            episode_id=session.episode_id,
            instruction_refs=("docs/agent/task-cards/ux-1-model-and-auth-adapters.md",),
            token_budget=1024,
            rendered_prompt="base context",
        )
        credential_bundle = mock.Mock()
        credential_bundle.as_mapping.return_value = {"api_key": "sk-test-789"}
        active_profile = mock.Mock(
            provider_id="openai-compatible",
            default_model="legacy-chat-model",
            base_url="https://api.example.test/v1",
            metadata={},
            profile_id="provider-openai-compatible",
        )
        legacy_resolution = mock.Mock(supports_tools=False)

        with (
            mock.patch.object(
                capability, "_profile_for_role", return_value=active_profile
            ),
            mock.patch.object(
                capability.runtime_resolver, "resolve", return_value=legacy_resolution
            ),
            mock.patch.object(
                capability.credential_resolver,
                "resolve",
                return_value=credential_bundle,
            ),
            mock.patch(
                "packages.models.runtime_capability.build_model_adapter",
                return_value=_CapturingAdapter(),
            ),
        ):
            result = capability.generate(
                profile=profile,
                session=session,
                context=context,
                prompt="Use tools if needed.",
            )

        self.assertEqual(result.outcome, "ok")
        self.assertEqual(len(captured_requests), 1)
        request = captured_requests[0]
        self.assertEqual(request.tools, ())
        self.assertIn(
            "Native provider tool calling is unavailable",
            request.context["frozen_prefix_prompt"],
        )
        self.assertIn(
            "mcp.filesystem.read_file", request.context["frozen_prefix_prompt"]
        )
        self.assertIn("base context", request.context["rendered_prompt"])
        self.assertIn("mcp.filesystem.read_file", request.context["rendered_prompt"])

    def test_model_request_can_be_constructed_for_preview_runtime(self) -> None:
        request = ModelRequest(
            request_id="request-1",
            profile_id="profile-companion",
            session_id="session-123",
            provider_id="preview.static",
            model_id="static-1",
            prompt="hello",
        )

        self.assertEqual(request.provider_id, "preview.static")
        self.assertEqual(request.task, "generate")

    def test_auth_profiles_persist_provider_metadata_and_secret_references(
        self,
    ) -> None:
        database_path = Path(self.tempdir.name) / "auth.sqlite3"
        repository = RuntimeStorageRepository(database_path)
        repository.bootstrap()
        store = PersistentAuthProfileStore(repository)
        catalog = ProviderCatalog.with_defaults()
        factory = ProviderProfileFactory(catalog)

        reference = SecretReference(
            reference_id="secret-openai-token",
            provider_id="openai",
            secret_name="api_token",
            secret_key="api_key",
        )
        profile = factory.from_provider_defaults(
            "openai",
            profile_id="auth-openai-default",
            secret_references=(reference,),
            priority=20,
            metadata={"env": "prod"},
        )
        store.register(profile)

        loaded = store.get("auth-openai-default")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.provider_id, "openai")
        self.assertEqual(loaded.transport_id, "openai_responses")
        self.assertEqual(loaded.base_url, "https://api.openai.com/v1")
        self.assertEqual(loaded.default_model, "gpt-4.1-mini")
        self.assertEqual(loaded.secret_references[0].secret_key, "api_key")
        self.assertEqual(loaded.metadata["env"], "prod")

        selected = store.select("openai")
        self.assertEqual(selected.profile_id, "auth-openai-default")
        self.assertEqual(catalog.get("openai").required_secret_keys, ("api_key",))

        auth_profiles_path = database_path.with_name("auth.auth-profiles.json")
        persisted = json.loads(auth_profiles_path.read_text(encoding="utf-8"))
        row = persisted["auth-openai-default"]
        self.assertEqual(
            (
                row["provider_id"],
                row["transport_id"],
                row["base_url"],
                row["default_model"],
            ),
            ("openai", "openai_responses", "https://api.openai.com/v1", "gpt-4.1-mini"),
        )
        self.assertNotIn("sk-test-123", database_path.read_text(errors="ignore"))

    def test_legacy_provider_auth_state_methods_stay_off_clean_storage(self) -> None:
        database_path = Path(self.tempdir.name) / "auth-state.sqlite3"
        repository = RuntimeStorageRepository(database_path)
        repository.bootstrap()

        repository.upsert_provider_auth_state(
            ProviderAuthState(
                provider_id="copilot",
                auth_type="api_key",
                status="authenticated",
                source="gh-cli",
                transport_id="openai_responses",
                provider_kind="aggregator",
                base_url="https://api.githubcopilot.com",
                default_model="gpt-5.4",
                runtime_enabled=True,
                summary="authenticated via gh-cli",
                metadata={"reasoning_efforts": "minimal,low,medium,high"},
                discovered_at=datetime(2026, 4, 13),
                updated_at=datetime(2026, 4, 13),
            )
        )

        loaded = repository.load_provider_auth_state("copilot")
        self.assertIsNone(loaded)
        listed = repository.list_provider_auth_states()
        self.assertEqual(listed, ())

        with sqlite3.connect(database_path) as connection:
            provider_auth_table = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'provider_auth_states'"
            ).fetchone()
            records_table = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'records'"
            ).fetchone()
            record = (
                None
                if records_table is None
                else connection.execute(
                    "SELECT schema_version, owner_scope FROM records WHERE record_id = ?",
                    ("provider-auth:copilot",),
                ).fetchone()
            )

        self.assertIsNone(provider_auth_table)
        self.assertIsNone(record)


if __name__ == "__main__":
    unittest.main()
