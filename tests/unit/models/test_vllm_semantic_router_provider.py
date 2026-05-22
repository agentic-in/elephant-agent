from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.auth.runtime import AuthProfile
from packages.models.provider_catalog import provider_definition
from packages.models.provider_runtime import ProviderRuntimeResolver
from packages.models.providers.http import JSONHTTPResponse, ProviderHTTPError
from packages.models.providers.openai_compatible import OpenAICompatibleProviderConfig
from packages.models.providers.registry import InMemoryModelAdapterBuilderRegistry, ModelAdapterBuildContext
from packages.models.providers.vllm_semantic_router import (
    VSR_FALLBACK_BASE_URL_KEY,
    VSR_FALLBACK_MODEL_ID_KEY,
    VSR_ROUTING_POLICY_HEADER,
    VSR_ROUTING_POLICY_KEY,
    validate_vsr_semantic_router_profile_metadata,
    VllmSemanticRouterProviderAdapter,
)
from packages.models.runtime import CredentialSource, ModelRequest


class _EmptyCreds(CredentialSource):
    def resolve(self, provider_id: str):
        return {}


class _SeqTransport:
    def __init__(self, outcomes: list[JSONHTTPResponse | BaseException]) -> None:
        self._outcomes = list(outcomes)
        self.urls: list[str] = []

    def post_json(self, *, url: str, headers: dict, payload: dict) -> JSONHTTPResponse:
        self.urls.append(url)
        if not self._outcomes:
            raise AssertionError("no scripted outcomes left")
        item = self._outcomes.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class VllmSemanticRouterProviderTests(unittest.TestCase):
    def test_catalog_registers_semantic_router_provider(self) -> None:
        definition = provider_definition("vllm-semantic-router")
        self.assertIsNotNone(definition)
        assert definition is not None
        self.assertEqual(definition.metadata.get("adapter_builder"), "vllm-semantic-router")

    def test_validate_metadata_rejects_partial_fallback(self) -> None:
        with self.assertRaises(ValueError):
            validate_vsr_semantic_router_profile_metadata({VSR_FALLBACK_BASE_URL_KEY: "http://x/v1"})
        with self.assertRaises(ValueError):
            validate_vsr_semantic_router_profile_metadata({VSR_FALLBACK_MODEL_ID_KEY: "m"})
        validate_vsr_semantic_router_profile_metadata({})

    def test_adapter_builder_is_selected_for_manifest(self) -> None:
        resolver = ProviderRuntimeResolver.default()
        resolution = resolver.resolve(
            "vllm-semantic-router",
            model_id="MoM",
            base_url="http://router.example/v1",
        )
        profile = AuthProfile(
            profile_id="t-profile",
            provider_id="vllm-semantic-router",
            base_url="http://router.example/v1",
            default_model="MoM",
            metadata={},
        )
        ctx = ModelAdapterBuildContext(
            profile=profile,
            resolution=resolution,
            runtime_resolver=resolver,
            credential_source=_EmptyCreds(),
            credentials={},
            adapter_id="unit.test",
        )
        reg = InMemoryModelAdapterBuilderRegistry.default()
        builder = reg.select(ctx)
        self.assertEqual(builder.builder_id, "vllm-semantic-router")

    def test_routing_policy_header_on_plan(self) -> None:
        resolver = ProviderRuntimeResolver.default()
        transport = _SeqTransport([])
        adapter = VllmSemanticRouterProviderAdapter(
            router_metadata={VSR_ROUTING_POLICY_KEY: "latency_first"},
            config=OpenAICompatibleProviderConfig(
                provider_id="vllm-semantic-router",
                base_url="http://router.example/v1",
                model_id="MoM",
            ),
            runtime_resolver=resolver,
            credential_source=_EmptyCreds(),
            http_transport=transport,
            adapter_id="unit.test",
        )
        request = ModelRequest(
            request_id="r1",
            profile_id="t-profile",
            session_id="",
            provider_id="vllm-semantic-router",
            model_id="MoM",
            prompt="hi",
            task="generate",
        )
        plan = adapter.plan_request(request, {})
        self.assertEqual(plan.headers.get(VSR_ROUTING_POLICY_HEADER), "latency_first")

    def test_non_stream_merges_vsr_response_headers(self) -> None:
        resolver = ProviderRuntimeResolver.default()
        payload = {
            "id": "chatcmpl-1",
            "model": "routed-model",
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        }
        transport = _SeqTransport(
            [
                JSONHTTPResponse(
                    status_code=200,
                    headers={
                        "x-vsr-selected-decision": "code_decision",
                        "x-selected-model": "backend-1",
                        "content-type": "application/json",
                    },
                    payload=payload,
                )
            ]
        )
        adapter = VllmSemanticRouterProviderAdapter(
            router_metadata={},
            config=OpenAICompatibleProviderConfig(
                provider_id="vllm-semantic-router",
                base_url="http://router.example/v1",
                model_id="MoM",
            ),
            runtime_resolver=resolver,
            credential_source=_EmptyCreds(),
            http_transport=transport,
            adapter_id="unit.test",
        )
        request = ModelRequest(
            request_id="r1",
            profile_id="t-profile",
            session_id="",
            provider_id="vllm-semantic-router",
            model_id="MoM",
            prompt="hi",
            task="generate",
        )
        result = adapter.generate(request, {})
        self.assertEqual(result.content, "ok")
        self.assertEqual(result.metadata.get("vsr_response_header:x-vsr-selected-decision"), "code_decision")
        self.assertEqual(result.metadata.get("vsr_response_header:x-selected-model"), "backend-1")

    def test_fallback_on_router_503(self) -> None:
        resolver = ProviderRuntimeResolver.default()
        ok_payload = {
            "id": "chatcmpl-fb",
            "model": "direct",
            "choices": [{"message": {"role": "assistant", "content": "fallback-body"}}],
        }
        transport = _SeqTransport(
            [
                ProviderHTTPError("upstream unavailable", status_code=503, url="http://router.example/v1/chat/completions"),
                JSONHTTPResponse(status_code=200, headers={}, payload=ok_payload),
            ]
        )
        adapter = VllmSemanticRouterProviderAdapter(
            router_metadata={
                VSR_FALLBACK_BASE_URL_KEY: "http://direct.example/v1",
                VSR_FALLBACK_MODEL_ID_KEY: "direct",
            },
            config=OpenAICompatibleProviderConfig(
                provider_id="vllm-semantic-router",
                base_url="http://router.example/v1",
                model_id="MoM",
            ),
            runtime_resolver=resolver,
            credential_source=_EmptyCreds(),
            http_transport=transport,
            adapter_id="unit.test",
        )
        request = ModelRequest(
            request_id="r1",
            profile_id="t-profile",
            session_id="",
            provider_id="vllm-semantic-router",
            model_id="MoM",
            prompt="hi",
            task="generate",
        )
        result = adapter.generate(request, {})
        self.assertEqual(result.content, "fallback-body")
        self.assertEqual(result.metadata.get("vsr_fallback"), "true")
        self.assertEqual(result.metadata.get("vsr_fallback_http_status"), "503")
        self.assertIn("http://router.example/v1/chat/completions", transport.urls[0])
        self.assertIn("http://direct.example/v1/chat/completions", transport.urls[1])
