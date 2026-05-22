"""vLLM Semantic Router as an OpenAI-chat-compatible provider edge."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from packages.models.providers.http import ProviderHTTPError
from packages.models.providers.openai_compatible import (
    OpenAICompatibleProviderAdapter,
    OpenAICompatibleProviderConfig,
)
from packages.models.runtime import ModelRequest, ModelTextResult

# Auth profile metadata keys (packages.auth.runtime.AuthProfile.metadata)
VSR_ROUTING_POLICY_KEY = "vsr_routing_policy"
VSR_FALLBACK_BASE_URL_KEY = "vsr_fallback_base_url"
VSR_FALLBACK_MODEL_ID_KEY = "vsr_fallback_model_id"

# Optional request hint; gateways or router plugins may consume it.
VSR_ROUTING_POLICY_HEADER = "x-vsr-routing-policy"

# Prefixes copied onto ModelTextResult.metadata for observability (lowercased keys).
_VSR_RESPONSE_HEADER_PREFIXES = (
    "x-vsr-",
    "x-selected-model",
)


def validate_vsr_semantic_router_profile_metadata(metadata: Mapping[str, str]) -> None:
    """Ensure fallback knobs are self-consistent."""
    url = str(metadata.get(VSR_FALLBACK_BASE_URL_KEY, "")).strip()
    model = str(metadata.get(VSR_FALLBACK_MODEL_ID_KEY, "")).strip()
    if bool(url) ^ bool(model):
        raise ValueError(
            "vLLM Semantic Router profile metadata requires "
            f"both '{VSR_FALLBACK_BASE_URL_KEY}' and '{VSR_FALLBACK_MODEL_ID_KEY}', or neither."
        )


def _vsr_observable_response_headers(headers: Mapping[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw_key, raw_value in headers.items():
        key = str(raw_key).lower().strip()
        if not key:
            continue
        if any(key.startswith(prefix) for prefix in _VSR_RESPONSE_HEADER_PREFIXES):
            out[f"vsr_response_header:{key}"] = str(raw_value).strip()
    return out


def _fallback_eligible_exc(exc: BaseException) -> bool:
    if isinstance(exc, (ConnectionError, OSError, TimeoutError)):
        return True
    if isinstance(exc, ProviderHTTPError):
        return exc.status_code in {502, 503, 504}
    return False


class VllmSemanticRouterProviderAdapter(OpenAICompatibleProviderAdapter):
    """Routes chat completions through a Semantic Router ingress with optional direct fallback."""

    def __init__(
        self,
        *,
        router_metadata: Mapping[str, str],
        **kwargs: Any,
    ) -> None:
        validate_vsr_semantic_router_profile_metadata(router_metadata)
        super().__init__(**kwargs)
        self._router_metadata = dict(router_metadata)

    def _build_headers(
        self,
        resolution,
        credentials: Mapping[str, str],
        *,
        session_id: str,
    ) -> dict[str, str]:
        headers = super()._build_headers(resolution, credentials, session_id=session_id)
        policy = str(self._router_metadata.get(VSR_ROUTING_POLICY_KEY, "")).strip()
        if policy:
            headers[VSR_ROUTING_POLICY_HEADER] = policy
        return headers

    def generate(
        self,
        request: ModelRequest,
        credentials: Mapping[str, str],
    ) -> ModelTextResult:
        try:
            plan = self.plan_request(request, credentials)
            if not bool(plan.payload.get("stream")):
                response = self.http_transport.post_json(
                    url=plan.url,
                    headers=plan.headers,
                    payload=plan.payload,
                )
                vsr_meta = _vsr_observable_response_headers(response.headers)
                result = self._text_result_from_payload(
                    request=request,
                    plan=plan,
                    payload=response.payload,
                    status_code=response.status_code,
                )
                if not vsr_meta:
                    return result
                return replace(result, metadata={**dict(result.metadata), **vsr_meta})
            return super().generate(request, credentials)
        except (ConnectionError, ProviderHTTPError, OSError, TimeoutError) as exc:
            if self._should_attempt_fallback(exc):
                return self._invoke_fallback(request, credentials, cause=exc)
            raise

    def _should_attempt_fallback(self, exc: BaseException) -> bool:
        if not _fallback_eligible_exc(exc):
            return False
        url = str(self._router_metadata.get(VSR_FALLBACK_BASE_URL_KEY, "")).strip()
        model = str(self._router_metadata.get(VSR_FALLBACK_MODEL_ID_KEY, "")).strip()
        return bool(url and model)

    def _invoke_fallback(
        self,
        request: ModelRequest,
        credentials: Mapping[str, str],
        *,
        cause: BaseException,
    ) -> ModelTextResult:
        fb_url = str(self._router_metadata[VSR_FALLBACK_BASE_URL_KEY]).strip()
        fb_model = str(self._router_metadata[VSR_FALLBACK_MODEL_ID_KEY]).strip()
        fallback_config = OpenAICompatibleProviderConfig(
            provider_id="openai-compatible",
            base_url=fb_url,
            model_id=fb_model,
            extra_headers=self.config.extra_headers,
            auth_header_name=self.config.auth_header_name,
        )
        inner = OpenAICompatibleProviderAdapter(
            config=fallback_config,
            runtime_resolver=self.runtime_resolver,
            credential_source=None,
            http_transport=self.http_transport,
            adapter_id=f"{self.descriptor.adapter_id}:vsr-fallback",
            stream_observer=self.stream_observer,
        )
        fb_request = ModelRequest(
            request_id=request.request_id,
            profile_id=request.profile_id,
            session_id=request.session_id,
            provider_id="openai-compatible",
            model_id=fb_model,
            prompt=request.prompt,
            context=dict(request.context),
            task=request.task,
            reasoning_effort=request.reasoning_effort,
            metadata=dict(request.metadata),
            tools=tuple(request.tools),
            messages=tuple(request.messages),
        )
        result = inner.generate(fb_request, credentials)
        diag_status = ""
        if isinstance(cause, ProviderHTTPError):
            diag_status = str(cause.status_code)
        elif isinstance(cause, TimeoutError):
            diag_status = "timeout"
        extra_meta = {
            "vsr_fallback": "true",
            "vsr_fallback_error": type(cause).__name__,
            "vsr_fallback_http_status": diag_status,
        }
        return replace(result, metadata={**dict(result.metadata), **extra_meta})
