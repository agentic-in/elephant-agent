"""Provider metadata discovery and runtime state evaluation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable
from urllib import error, request
from urllib.parse import quote
import json

from packages.auth.runtime import AuthProfile, SecretValueResolution

from .model_metadata import resolve_provider_model_metadata
from .provider_catalog import provider_definition
from .provider_runtime import ProviderRuntimeResolver, provider_auth_headers

RequestJsonCallable = Callable[..., dict[str, Any]]

_MODEL_CONTEXT_KEYS = (
    "context_length",
    "context_window",
    "max_context_length",
    "max_position_embeddings",
    "max_model_len",
    "max_input_tokens",
    "max_sequence_length",
    "max_seq_len",
    "n_ctx",
    "n_ctx_train",
)

_MODEL_OUTPUT_KEYS = (
    "max_completion_tokens",
    "max_output_tokens",
    "max_tokens",
)

DEFAULT_CONTEXT_WINDOW_TOKENS = 128_000


@dataclass(frozen=True, slots=True)
class DiscoveredProviderModel:
    model_id: str
    label: str
    context_window_tokens: int | None = None
    max_output_tokens: int | None = None
    source: str = "endpoint"
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DiscoveredProviderState:
    provider_id: str
    display_name: str
    transport_display_name: str
    auth_type: str
    provider_kind: str
    runtime_enabled: bool
    status: str
    source: str
    profile_id: str | None = None
    base_url: str | None = None
    default_model: str | None = None
    reasoning_efforts: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderProbeContext:
    provider_id: str
    base_url: str
    api_key: str | None
    request_family: str
    metadata: Mapping[str, str]
    extra_headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderModelLookupContext:
    probe: ProviderProbeContext
    requester: RequestJsonCallable
    hinted_models: tuple[DiscoveredProviderModel, ...]
    model_id: str | None = None


@runtime_checkable
class ProviderMetadataProbe(Protocol):
    probe_id: str

    def list_models(self, context: ProviderModelLookupContext) -> tuple[DiscoveredProviderModel, ...] | None:
        """Return provider models or None when this probe does not apply."""

    def detect_context_window(self, context: ProviderModelLookupContext) -> int | None:
        """Return a detected context window or None when unavailable."""


class ProviderMetadataProbeRegistry:
    def __init__(self, probes: tuple[ProviderMetadataProbe, ...] = ()) -> None:
        self._probes: dict[str, ProviderMetadataProbe] = {}
        for probe in probes:
            self.register(probe)

    def register(self, probe: ProviderMetadataProbe) -> None:
        self._probes[str(probe.probe_id)] = probe

    def list(self) -> tuple[ProviderMetadataProbe, ...]:
        return tuple(self._probes.values())

    @classmethod
    def default(cls) -> "ProviderMetadataProbeRegistry":
        return cls((_OllamaProviderMetadataProbe(), _GenericProviderMetadataProbe()))


def _normalize_base_url(base_url: str | None) -> str:
    return str(base_url or "").strip().rstrip("/")


def _compose_provider_url(base_url: str, endpoint_path: str) -> str:
    trimmed_base = _normalize_base_url(base_url)
    trimmed_path = endpoint_path.lstrip("/")
    if trimmed_path.startswith("v1/") and trimmed_base.endswith("/v1"):
        trimmed_path = trimmed_path[3:]
    return f"{trimmed_base}/{trimmed_path}"


def _coerce_reasonable_int(value: Any, *, minimum: int = 1024, maximum: int = 10_000_000) -> int | None:
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, str):
            value = value.strip().replace(",", "")
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if minimum <= parsed <= maximum:
        return parsed
    return None


def _iter_nested_mappings(value: Any):
    if isinstance(value, Mapping):
        yield value
        for nested in value.values():
            yield from _iter_nested_mappings(nested)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_nested_mappings(item)


def _extract_nested_int(payload: Mapping[str, Any], keys: tuple[str, ...]) -> int | None:
    keyset = {key.casefold() for key in keys}
    for mapping in _iter_nested_mappings(payload):
        for key, value in mapping.items():
            if str(key).casefold() not in keyset:
                continue
            parsed = _coerce_reasonable_int(value)
            if parsed is not None:
                return parsed
    return None


def _context_window_from_payload(payload: Mapping[str, Any]) -> int | None:
    return _extract_nested_int(payload, _MODEL_CONTEXT_KEYS)


def _max_output_tokens_from_payload(payload: Mapping[str, Any]) -> int | None:
    return _extract_nested_int(payload, _MODEL_OUTPUT_KEYS)


def _provider_metadata(provider_id: str) -> Mapping[str, str]:
    definition = provider_definition(provider_id)
    if definition is None:
        return {}
    return {str(key): str(value) for key, value in dict(definition.metadata).items()}


def _provider_model_catalog_path(provider_id: str) -> str:
    configured = _provider_metadata(provider_id).get("model_catalog_path", "").strip()
    return configured or "/v1/models"


def _provider_model_detail_path(provider_id: str, model_id: str) -> str:
    metadata = _provider_metadata(provider_id)
    template = metadata.get("model_detail_path_template", "").strip()
    if template:
        return template.replace("{model_id}", quote(model_id, safe=""))
    catalog_path = _provider_model_catalog_path(provider_id)
    catalog_root = catalog_path.split("?", 1)[0].rstrip("/")
    if catalog_root.endswith("/models"):
        return f"{catalog_root}/{quote(model_id, safe='')}"
    return f"/v1/models/{quote(model_id, safe='')}"


def _provider_model_payload_list_keys(provider_id: str) -> tuple[str, ...]:
    configured = _provider_metadata(provider_id).get("model_payload_list_key", "").strip()
    keys = [configured] if configured else []
    keys.extend(["data", "models"])
    ordered: list[str] = []
    seen: set[str] = set()
    for key in keys:
        normalized = key.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return tuple(ordered)


def _provider_model_id_keys(provider_id: str) -> tuple[str, ...]:
    configured = _provider_metadata(provider_id).get("model_payload_id_key", "").strip()
    keys = [configured] if configured else []
    keys.extend(["id", "slug"])
    ordered: list[str] = []
    seen: set[str] = set()
    for key in keys:
        normalized = key.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return tuple(ordered)


def _provider_model_items(provider_id: str, payload: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    for list_key in _provider_model_payload_list_keys(provider_id):
        items = payload.get(list_key)
        if not isinstance(items, list):
            continue
        return tuple(item for item in items if isinstance(item, Mapping))
    return ()


def _provider_request_headers(
    *,
    provider_id: str,
    request_family: str,
    api_key: str | None,
    extra_headers: Mapping[str, str] | None = None,
    metadata: Mapping[str, str] | None = None,
) -> dict[str, str]:
    return {
        "Accept": "application/json",
        **dict(extra_headers or {}),
        **provider_auth_headers(
            provider_id=provider_id,
            request_family=request_family,
            api_key=api_key,
            metadata=metadata,
        ),
    }


def request_json(
    *,
    url: str,
    headers: Mapping[str, str],
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    http_request = request.Request(url, headers=dict(headers), method="GET")
    try:
        with request.urlopen(http_request, timeout=timeout_seconds) as response:
            raw_body = response.read().decode("utf-8")
            payload = json.loads(raw_body) if raw_body else {}
    except error.HTTPError as exc:  # pragma: no cover - exercised by integration tests
        detail = exc.read().decode("utf-8", errors="replace").strip()
        suffix = f" {detail[:200]}" if detail else ""
        raise RuntimeError(f"provider metadata request failed with status {exc.code}.{suffix}".strip()) from exc
    except error.URLError as exc:  # pragma: no cover - exercised by integration tests
        raise RuntimeError(f"provider metadata request failed for {url}: {exc.reason}") from exc
    if isinstance(payload, list):
        return {"data": payload}
    if not isinstance(payload, dict):
        raise RuntimeError("provider metadata response must be a JSON object")
    return {str(key): value for key, value in payload.items()}


def heuristic_context_window(model_id: str) -> int | None:
    normalized = model_id.casefold()
    heuristics = (
        ("gpt-5.4-nano", 400_000),
        ("gpt-5.4-mini", 400_000),
        ("gpt-5.4", 1_050_000),
        ("gpt-5.3-codex-spark", 128_000),
        ("gpt-5.1-chat", 128_000),
        ("gpt-5", 400_000),
        ("gpt-4.1", 1_047_576),
        ("gpt-4o", 128_000),
        ("claude", 200_000),
        ("gemini", 1_048_576),
        ("glm", 204_800),
        ("minimax", 204_800),
        ("mimo-v2-pro", 1_000_000),
        ("mimo-v2-omni", 256_000),
        ("mimo-v2-flash", 256_000),
        ("xiaomi", 256_000),
        ("qwen3-coder-plus", 1_000_000),
        ("qwen3-coder", 262_144),
        ("llama", 131_072),
        ("qwen", 131_072),
        ("deepseek", 128_000),
        ("kimi", 262_144),
    )
    for prefix, size in sorted(heuristics, key=lambda item: len(item[0]), reverse=True):
        if prefix in normalized:
            return size
    return DEFAULT_CONTEXT_WINDOW_TOKENS


def _hinted_models(
    provider_id: str, *, runtime_resolver: ProviderRuntimeResolver
) -> tuple[DiscoveredProviderModel, ...]:
    definition = provider_definition(provider_id)
    if definition is None:
        return ()
    models: list[DiscoveredProviderModel] = []
    seen: set[str] = set()
    for model_id in definition.model_hints:
        normalized = str(model_id).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        try:
            reasoning_efforts = runtime_resolver.resolve(
                provider_id,
                model_id=normalized,
                base_url=definition.default_base_url,
            ).reasoning_efforts
        except Exception:
            reasoning_efforts = ()
        models.append(
            DiscoveredProviderModel(
                model_id=normalized,
                label=normalized,
                context_window_tokens=heuristic_context_window(normalized),
                source="catalog-hint",
                metadata={"reasoning_efforts": ",".join(reasoning_efforts)},
            )
        )
    return tuple(models)


def _merge_discovered_models(
    primary: tuple[DiscoveredProviderModel, ...],
    fallback: tuple[DiscoveredProviderModel, ...],
) -> tuple[DiscoveredProviderModel, ...]:
    merged = list(primary)
    positions = {item.model_id: index for index, item in enumerate(merged)}
    for hinted in fallback:
        index = positions.get(hinted.model_id)
        if index is None:
            positions[hinted.model_id] = len(merged)
            merged.append(hinted)
            continue
        current = merged[index]
        current_reasoning = str(current.metadata.get("reasoning_efforts", "")).strip()
        hinted_reasoning = str(hinted.metadata.get("reasoning_efforts", "")).strip()
        if current.context_window_tokens is not None and current_reasoning:
            continue
        merged[index] = DiscoveredProviderModel(
            model_id=current.model_id,
            label=current.label or hinted.label,
            context_window_tokens=current.context_window_tokens or hinted.context_window_tokens,
            max_output_tokens=current.max_output_tokens or hinted.max_output_tokens,
            source=current.source,
            metadata={
                **dict(hinted.metadata),
                **dict(current.metadata),
                "reasoning_efforts": current_reasoning or hinted_reasoning,
            },
        )
    return tuple(merged)


def _ollama_server_root(base_url: str) -> str:
    server_url = _normalize_base_url(base_url)
    if server_url.endswith("/v1"):
        server_url = server_url[:-3]
    return server_url


def _context_window_from_ollama_show_payload(payload: Mapping[str, Any]) -> int | None:
    parameters = payload.get("parameters")
    if isinstance(parameters, str) and "num_ctx" in parameters:
        for line in parameters.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2 and parts[0] == "num_ctx":
                parsed = _coerce_reasonable_int(parts[-1])
                if parsed is not None:
                    return parsed
    model_info = payload.get("model_info")
    if isinstance(model_info, Mapping):
        for key, value in model_info.items():
            if "context_length" not in str(key).casefold():
                continue
            parsed = _coerce_reasonable_int(value)
            if parsed is not None:
                return parsed
    return _context_window_from_payload(payload)


class _GenericProviderMetadataProbe:
    probe_id = "generic"

    def list_models(self, context: ProviderModelLookupContext) -> tuple[DiscoveredProviderModel, ...] | None:
        payload = context.requester(
            url=_compose_provider_url(
                context.probe.base_url,
                _provider_model_catalog_path(context.probe.provider_id),
            ),
            headers=_provider_request_headers(
                provider_id=context.probe.provider_id,
                request_family=context.probe.request_family,
                api_key=context.probe.api_key,
                extra_headers=context.probe.extra_headers,
                metadata=context.probe.metadata,
            ),
        )
        data = _provider_model_items(context.probe.provider_id, payload)
        if not data:
            return context.hinted_models
        models: list[DiscoveredProviderModel] = []
        for item in data:
            model_id = ""
            for key in _provider_model_id_keys(context.probe.provider_id):
                candidate = str(item.get(key) or "").strip()
                if candidate:
                    model_id = candidate
                    break
            if not model_id:
                continue
            context_window_tokens = _context_window_from_payload(item)
            max_output_tokens = _max_output_tokens_from_payload(item)
            label = str(item.get("name") or item.get("label") or model_id)
            reasoning_efforts = ()
            capabilities = item.get("capabilities")
            if isinstance(capabilities, Mapping):
                supports_payload = capabilities.get("supports")
                if isinstance(supports_payload, Mapping):
                    raw_efforts = supports_payload.get("reasoning_effort")
                    if isinstance(raw_efforts, list):
                        reasoning_efforts = tuple(
                            str(value).strip().lower() for value in raw_efforts if str(value).strip()
                        )
            models.append(
                DiscoveredProviderModel(
                    model_id=model_id,
                    label=label,
                    context_window_tokens=context_window_tokens,
                    max_output_tokens=max_output_tokens,
                    metadata={
                        "owned_by": str(item.get("owned_by", "")),
                        "reasoning_efforts": ",".join(reasoning_efforts),
                    },
                )
            )
        if not models:
            return context.hinted_models
        return _merge_discovered_models(tuple(models), context.hinted_models)

    def detect_context_window(self, context: ProviderModelLookupContext) -> int | None:
        if not context.model_id:
            return None
        payload = context.requester(
            url=_compose_provider_url(
                context.probe.base_url,
                _provider_model_detail_path(context.probe.provider_id, context.model_id),
            ),
            headers=_provider_request_headers(
                provider_id=context.probe.provider_id,
                request_family=context.probe.request_family,
                api_key=context.probe.api_key,
                extra_headers=context.probe.extra_headers,
                metadata=context.probe.metadata,
            ),
        )
        detected = _context_window_from_payload(payload)
        if detected is not None:
            return detected
        metadata = resolve_provider_model_metadata(
            provider_id=context.probe.provider_id,
            model_id=context.model_id,
            base_url=context.probe.base_url,
            api_key=context.probe.api_key,
        )
        return (
            metadata.context_window_tokens
            if metadata is not None and metadata.context_window_tokens is not None
            else heuristic_context_window(context.model_id)
        )


class _OllamaProviderMetadataProbe:
    probe_id = "ollama"

    def list_models(self, context: ProviderModelLookupContext) -> tuple[DiscoveredProviderModel, ...] | None:
        return None

    def detect_context_window(self, context: ProviderModelLookupContext) -> int | None:
        if context.probe.provider_id.strip().lower() != "ollama" or not context.model_id:
            return None
        server_url = _ollama_server_root(context.probe.base_url)
        if not server_url:
            return None
        body = json.dumps({"name": context.model_id}).encode("utf-8")
        http_request = request.Request(
            f"{server_url}/api/show",
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=5.0) as response:
                raw_body = response.read().decode("utf-8")
                payload = json.loads(raw_body) if raw_body else {}
        except (
            error.HTTPError,
            error.URLError,
            json.JSONDecodeError,
        ):  # pragma: no cover
            return None
        if not isinstance(payload, Mapping):
            return None
        return _context_window_from_ollama_show_payload(payload)


class ProviderMetadataDiscoveryService:
    def __init__(
        self,
        *,
        runtime_resolver: ProviderRuntimeResolver | None = None,
        probe_registry: ProviderMetadataProbeRegistry | None = None,
        requester: RequestJsonCallable | None = None,
    ) -> None:
        self.runtime_resolver = runtime_resolver or ProviderRuntimeResolver.default()
        self.probe_registry = probe_registry or ProviderMetadataProbeRegistry.default()
        self.requester = requester or request_json

    def discover_models(
        self,
        *,
        provider_id: str,
        base_url: str | None,
        api_key: str | None,
        extra_headers: Mapping[str, str] | None = None,
        default_model_id: str | None = None,
    ) -> tuple[DiscoveredProviderModel, ...]:
        hinted_models = _hinted_models(provider_id, runtime_resolver=self.runtime_resolver)
        resolved_base_url = _normalize_base_url(base_url)
        if not resolved_base_url or not resolved_base_url.startswith(("http://", "https://")):
            return hinted_models
        resolution = self.runtime_resolver.resolve(
            provider_id,
            model_id=default_model_id or self._default_model_for(provider_id) or "model-id",
            base_url=resolved_base_url,
        )
        lookup_context = ProviderModelLookupContext(
            probe=ProviderProbeContext(
                provider_id=provider_id,
                base_url=resolved_base_url,
                api_key=api_key,
                request_family=resolution.request_family,
                metadata={str(key): str(value) for key, value in dict(resolution.provider_metadata).items()},
                extra_headers=dict(extra_headers or {}),
            ),
            requester=self.requester,
            hinted_models=hinted_models,
        )
        for probe in self.probe_registry.list():
            try:
                discovered = probe.list_models(lookup_context)
            except RuntimeError:
                continue
            if discovered is not None:
                return discovered
        return hinted_models

    def detect_context_window(
        self,
        *,
        provider_id: str,
        base_url: str | None,
        model_id: str,
        api_key: str | None,
        extra_headers: Mapping[str, str] | None = None,
        hinted_models: tuple[DiscoveredProviderModel, ...] | None = None,
    ) -> int | None:
        models = (
            hinted_models
            if hinted_models is not None
            else self.discover_models(
                provider_id=provider_id,
                base_url=base_url,
                api_key=api_key,
                extra_headers=extra_headers,
                default_model_id=model_id,
            )
        )
        normalized_provider_id = provider_id.strip().lower()
        for item in models:
            if (
                item.model_id == model_id
                and item.context_window_tokens is not None
                and not (normalized_provider_id == "ollama" and item.source == "catalog-hint")
            ):
                return item.context_window_tokens
        resolved_base_url = _normalize_base_url(base_url)
        if not resolved_base_url:
            return None
        if not resolved_base_url.startswith(("http://", "https://")):
            return heuristic_context_window(model_id)
        resolution = self.runtime_resolver.resolve(
            provider_id,
            model_id=model_id,
            base_url=resolved_base_url,
        )
        lookup_context = ProviderModelLookupContext(
            probe=ProviderProbeContext(
                provider_id=provider_id,
                base_url=resolved_base_url,
                api_key=api_key,
                request_family=resolution.request_family,
                metadata={str(key): str(value) for key, value in dict(resolution.provider_metadata).items()},
                extra_headers=dict(extra_headers or {}),
            ),
            requester=self.requester,
            hinted_models=models,
            model_id=model_id,
        )
        for probe in self.probe_registry.list():
            try:
                detected = probe.detect_context_window(lookup_context)
            except RuntimeError:
                detected = None
            if detected is not None:
                return detected
        metadata = resolve_provider_model_metadata(
            provider_id=provider_id,
            model_id=model_id,
            base_url=resolved_base_url,
            api_key=api_key,
        )
        return (
            metadata.context_window_tokens
            if metadata is not None and metadata.context_window_tokens is not None
            else heuristic_context_window(model_id)
        )

    def reasoning_efforts(
        self,
        *,
        provider_id: str,
        model_id: str,
        base_url: str | None,
        api_key: str | None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> tuple[str, ...]:
        resolved_base_url = _normalize_base_url(base_url)
        if resolved_base_url:
            try:
                models = self.discover_models(
                    provider_id=provider_id,
                    base_url=resolved_base_url,
                    api_key=api_key,
                    extra_headers=extra_headers,
                    default_model_id=model_id,
                )
            except Exception:
                models = ()
            for item in models:
                if item.model_id != model_id:
                    continue
                raw_efforts = str(item.metadata.get("reasoning_efforts", "")).strip()
                if raw_efforts:
                    return tuple(part for part in raw_efforts.split(",") if part)
        resolution = self.runtime_resolver.resolve(
            provider_id,
            model_id=model_id,
            base_url=base_url,
        )
        return resolution.reasoning_efforts

    def local_provider_reachable(
        self,
        *,
        provider_id: str,
        base_url: str | None,
        api_key: str | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> bool:
        try:
            return bool(
                self.discover_models(
                    provider_id=provider_id,
                    base_url=base_url,
                    api_key=api_key,
                    extra_headers=extra_headers,
                )
            )
        except Exception:
            return False

    def _default_model_for(self, provider_id: str) -> str | None:
        try:
            guide = self.runtime_resolver.build_setup_guide(provider_id)
        except LookupError:
            return None
        return guide.suggested_model_id


class ProviderStateEvaluator:
    def __init__(self, *, runtime_resolver: ProviderRuntimeResolver | None = None) -> None:
        self.runtime_resolver = runtime_resolver or ProviderRuntimeResolver.default()

    def evaluate(
        self,
        provider_id: str,
        *,
        selected_profile: AuthProfile | None,
        discovered_secret: SecretValueResolution | None,
        base_url: str | None,
        default_model: str | None,
        secret_status: str | None = None,
        secret_source: str | None = None,
        local_provider_reachable: bool = False,
        external_process_status: tuple[str, str] | None = None,
    ) -> DiscoveredProviderState:
        definition = provider_definition(provider_id)
        if definition is None:
            raise LookupError(f"unknown provider definition: {provider_id}")
        resolved_base_url = base_url
        if selected_profile is not None:
            if secret_status == "missing":
                status = "configured-missing-secret"
            else:
                status = "configured"
            source = secret_source if secret_status != "not-required" else "profile"
        elif discovered_secret is not None:
            status = "authenticated"
            source = discovered_secret.source
        elif definition.auth_type == "external_process" and external_process_status is not None:
            resolved_base_url = external_process_status[0]
            status = "authenticated"
            source = external_process_status[1]
        elif definition.provider_kind == "local" and local_provider_reachable:
            status = "available"
            source = "local-probe"
        elif not definition.runtime_enabled:
            status = "discovery-only"
            source = definition.metadata.get("runtime_status", "discovery-only")
        else:
            status = "requires-setup"
            source = "none"
        try:
            resolution = self.runtime_resolver.resolve(
                provider_id,
                model_id=default_model or definition.default_model_id,
                base_url=resolved_base_url,
            )
            transport_display_name = resolution.transport_display_name
            reasoning_efforts = resolution.reasoning_efforts
            transport_id = resolution.transport_id
        except Exception:
            transport_display_name = definition.transport_id
            reasoning_efforts = ()
            transport_id = definition.transport_id
        summary = f"{status} via {source}"
        return DiscoveredProviderState(
            provider_id=definition.provider_id,
            display_name=definition.display_name,
            transport_display_name=transport_display_name,
            auth_type=definition.auth_type,
            provider_kind=definition.provider_kind,
            runtime_enabled=definition.runtime_enabled,
            status=status,
            source=source,
            profile_id=selected_profile.profile_id if selected_profile is not None else None,
            base_url=resolved_base_url,
            default_model=default_model,
            reasoning_efforts=reasoning_efforts,
            metadata={
                "transport_id": transport_id,
                "summary": summary,
                "supports_custom_base_url": str(definition.supports_custom_base_url).lower(),
            },
        )


__all__ = [
    "DEFAULT_CONTEXT_WINDOW_TOKENS",
    "DiscoveredProviderModel",
    "DiscoveredProviderState",
    "ProviderMetadataDiscoveryService",
    "ProviderMetadataProbe",
    "ProviderMetadataProbeRegistry",
    "ProviderStateEvaluator",
    "heuristic_context_window",
    "request_json",
]
