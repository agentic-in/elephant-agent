"""Provider-aware model metadata fallback resolution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import ipaddress
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any
from urllib import error, request
from urllib.parse import urlparse

from packages.runtime_layout import default_cli_state_dir


MODELS_DEV_URL = "https://models.dev/api.json"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
_MODELS_DEV_CACHE_TTL_SECONDS = 3600
_OPENROUTER_CACHE_TTL_SECONDS = 3600
_ENDPOINT_CACHE_TTL_SECONDS = 300

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})
_CONTAINER_LOCAL_SUFFIXES = (".docker.internal", ".containers.internal", ".lima.internal")

_CONTEXT_KEYS = (
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
_OUTPUT_KEYS = (
    "max_completion_tokens",
    "max_output_tokens",
    "max_tokens",
)

_PROVIDER_TO_MODELS_DEV: dict[str, str] = {
    "alibaba": "alibaba",
    "anthropic": "anthropic",
    "baidu-qianfan": "baidu",
    "cerebras": "cerebras",
    "claude-code": "anthropic",
    "cohere": "cohere",
    "copilot": "github-copilot",
    "deepseek": "deepseek",
    "fireworks": "fireworks-ai",
    "google": "google",
    "groq": "groq",
    "huggingface": "huggingface",
    "kilocode": "kilo",
    "minimax": "minimax",
    "minimax-cn": "minimax-cn",
    "modelscope": "modelscope",
    "mistral": "mistral",
    "moonshot": "kimi-for-coding",
    "moonshot-cn": "kimi-for-coding",
    "nvidia": "nvidia",
    "openai": "openai",
    "openai-codex": "openai",
    "opencode-go": "opencode-go",
    "opencode-zen": "opencode",
    "openrouter": "openrouter",
    "requesty": "requesty",
    "perplexity": "perplexity",
    "qwen-oauth": "alibaba",
    "siliconflow": "siliconflow",
    "stepfun": "stepfun",
    "tencent-hunyuan": "tencent",
    "tencent-tokenhub": "tencent",
    "together": "togetherai",
    "volcengine": "volcengine",
    "xai": "xai",
    "xiaomi": "xiaomi",
    "zai": "zai",
}

_URL_TO_PROVIDER: dict[str, str] = {
    "api-inference.modelscope.cn": "modelscope",
    "api.anthropic.com": "anthropic",
    "api.cerebras.ai": "cerebras",
    "api.cohere.ai": "cohere",
    "api.deepseek.com": "deepseek",
    "api.githubcopilot.com": "copilot",
    "api.groq.com": "groq",
    "api.hunyuan.cloud.tencent.com": "tencent-hunyuan",
    "api.minimax": "minimax",
    "api.mistral.ai": "mistral",
    "api.moonshot.ai": "moonshot",
    "api.moonshot.cn": "moonshot-cn",
    "api.openai.com": "openai",
    "api.perplexity.ai": "perplexity",
    "api.siliconflow.cn": "siliconflow",
    "api.siliconflow.com": "siliconflow",
    "api.stepfun.ai": "stepfun",
    "api.stepfun.com": "stepfun",
    "api.together.ai": "together",
    "api.x.ai": "xai",
    "api.xiaomimimo.com": "xiaomi",
    "api.z.ai": "zai",
    "ark.cn-beijing.volces.com": "volcengine",
    "chatgpt.com": "openai-codex",
    "dashscope-intl.aliyuncs.com": "alibaba",
    "dashscope.aliyuncs.com": "alibaba",
    "generativelanguage.googleapis.com": "google",
    "integrate.api.nvidia.com": "nvidia",
    "models.github.ai": "copilot",
    "openrouter.ai": "openrouter",
    "router.requesty.ai": "requesty",
    "opencode.ai": "opencode-go",
    "portal.qwen.ai": "qwen-oauth",
    "qianfan.baidubce.com": "baidu-qianfan",
    "tokenhub-intl.tencentcloudmaas.com": "tencent-tokenhub",
    "tokenhub-intl.tencentmaas.cn": "tencent-tokenhub",
    "tokenhub-intl.tencentmaas.com": "tencent-tokenhub",
    "tokenhub.tencentmaas.cn": "tencent-tokenhub",
    "tokenhub.tencentmaas.com": "tencent-tokenhub",
    "xiaomimimo.com": "xiaomi",
}

_models_dev_cache: dict[str, Any] = {}
_models_dev_cache_time = 0.0
_openrouter_cache: dict[str, "ResolvedModelMetadata"] = {}
_openrouter_cache_time = 0.0
_endpoint_metadata_cache: dict[str, dict[str, "ResolvedModelMetadata"]] = {}
_endpoint_metadata_cache_time: dict[str, float] = {}


@dataclass(frozen=True, slots=True)
class ResolvedModelMetadata:
    context_window_tokens: int | None = None
    max_output_tokens: int | None = None
    source: str = "unknown"


def resolve_provider_model_metadata(
    *,
    provider_id: str,
    model_id: str,
    base_url: str | None = None,
    api_key: str | None = None,
) -> ResolvedModelMetadata | None:
    """Resolve metadata for one selected model from local, registry, or routed catalogs."""

    normalized_model = str(model_id or "").strip()
    if not normalized_model:
        return None

    normalized_base_url = _normalize_base_url(base_url)
    cached_context = get_cached_context_length(normalized_model, normalized_base_url)
    if cached_context is not None:
        return ResolvedModelMetadata(
            context_window_tokens=cached_context,
            source="context-length-cache",
        )

    if normalized_base_url and is_local_endpoint(normalized_base_url):
        local = query_local_endpoint_metadata(
            model_id=normalized_model,
            base_url=normalized_base_url,
            api_key=api_key,
        )
        if local is not None and local.context_window_tokens is not None:
            save_context_length(normalized_model, normalized_base_url, local.context_window_tokens)
            return local

    effective_provider = _effective_provider_id(provider_id=provider_id, base_url=normalized_base_url)
    models_dev = lookup_models_dev_metadata(effective_provider, normalized_model)
    if models_dev is not None and models_dev.context_window_tokens is not None:
        return models_dev

    openrouter = lookup_openrouter_metadata(normalized_model)
    if openrouter is not None and openrouter.context_window_tokens is not None:
        return openrouter

    return None


def lookup_models_dev_metadata(provider_id: str, model_id: str) -> ResolvedModelMetadata | None:
    models_dev_provider = _PROVIDER_TO_MODELS_DEV.get(provider_id.strip().lower())
    if not models_dev_provider:
        return None
    data = fetch_models_dev_registry()
    provider_data = data.get(models_dev_provider)
    if not isinstance(provider_data, Mapping):
        return None
    models = provider_data.get("models")
    if not isinstance(models, Mapping):
        return None
    entry = _find_model_entry(models, model_id)
    if entry is None and "/" in model_id:
        entry = _find_model_entry(models, model_id.rsplit("/", 1)[1])
    if entry is None:
        return None
    limit = entry.get("limit")
    context = _coerce_reasonable_int(limit.get("context") if isinstance(limit, Mapping) else None)
    output = _coerce_reasonable_int(limit.get("output") if isinstance(limit, Mapping) else None)
    if context is None:
        context = _extract_nested_int(entry, _CONTEXT_KEYS)
    if output is None:
        output = _extract_nested_int(entry, _OUTPUT_KEYS)
    if context is None and output is None:
        return None
    return ResolvedModelMetadata(
        context_window_tokens=context,
        max_output_tokens=output,
        source=f"models.dev:{models_dev_provider}",
    )


def lookup_openrouter_metadata(model_id: str) -> ResolvedModelMetadata | None:
    metadata = fetch_openrouter_model_metadata()
    return _find_metadata_entry(metadata, model_id)


def get_cached_context_length(model_id: str, base_url: str | None) -> int | None:
    normalized_model = str(model_id or "").strip()
    normalized_base_url = _normalize_base_url(base_url)
    if not normalized_model or not normalized_base_url:
        return None
    return _load_context_length_cache().get(_context_length_cache_key(normalized_model, normalized_base_url))


def save_context_length(model_id: str, base_url: str | None, context_window_tokens: int) -> None:
    normalized_model = str(model_id or "").strip()
    normalized_base_url = _normalize_base_url(base_url)
    parsed = _coerce_reasonable_int(context_window_tokens)
    if not normalized_model or not normalized_base_url or parsed is None:
        return
    cache = _load_context_length_cache()
    key = _context_length_cache_key(normalized_model, normalized_base_url)
    if cache.get(key) == parsed:
        return
    cache[key] = parsed
    _save_context_length_cache(cache)


def query_local_endpoint_metadata(
    *,
    model_id: str,
    base_url: str,
    api_key: str | None = None,
) -> ResolvedModelMetadata | None:
    normalized = _normalize_base_url(base_url)
    server_root = normalized[:-3] if normalized.endswith("/v1") else normalized

    lm_studio = _request_json_object(f"{server_root}/api/v1/models", timeout_seconds=2.0)
    if lm_studio:
        for model in _model_items(lm_studio):
            candidate_id = str(model.get("key") or model.get("id") or "").strip()
            if not _model_id_matches(candidate_id, model_id):
                continue
            loaded_instances = model.get("loaded_instances")
            if isinstance(loaded_instances, list):
                for instance in loaded_instances:
                    if not isinstance(instance, Mapping):
                        continue
                    config = instance.get("config")
                    if not isinstance(config, Mapping):
                        continue
                    context = _coerce_reasonable_int(config.get("context_length"))
                    if context is not None:
                        return ResolvedModelMetadata(context_window_tokens=context, source="local:lm-studio")
            context = _extract_nested_int(model, _CONTEXT_KEYS)
            output = _extract_nested_int(model, _OUTPUT_KEYS)
            if context is not None or output is not None:
                return ResolvedModelMetadata(context, output, "local:lm-studio")

    detail = _request_json_object(
        f"{server_root}/v1/models/{model_id}",
        headers=_bearer_headers(api_key),
        timeout_seconds=2.0,
    )
    if detail:
        context = _extract_nested_int(detail, _CONTEXT_KEYS)
        output = _extract_nested_int(detail, _OUTPUT_KEYS)
        if context is not None or output is not None:
            return ResolvedModelMetadata(context, output, "local:model-detail")

    listed = fetch_endpoint_model_metadata(base_url=normalized, api_key=api_key)
    entry = _find_metadata_entry(listed, model_id)
    if entry is not None:
        return entry

    props = _request_json_object(f"{server_root}/v1/props", headers=_bearer_headers(api_key), timeout_seconds=2.0)
    if not props:
        props = _request_json_object(f"{server_root}/props", headers=_bearer_headers(api_key), timeout_seconds=2.0)
    if props:
        context = _extract_nested_int(props, _CONTEXT_KEYS)
        if context is not None:
            return ResolvedModelMetadata(context_window_tokens=context, source="local:llamacpp")

    return None


def fetch_models_dev_registry(*, force_refresh: bool = False) -> Mapping[str, Any]:
    global _models_dev_cache, _models_dev_cache_time
    if (
        not force_refresh
        and _models_dev_cache
        and (time.time() - _models_dev_cache_time) < _MODELS_DEV_CACHE_TTL_SECONDS
    ):
        return _models_dev_cache

    try:
        payload = _request_json_object(MODELS_DEV_URL, timeout_seconds=10.0)
        if payload:
            _models_dev_cache = dict(payload)
            _models_dev_cache_time = time.time()
            _save_models_dev_disk_cache(_models_dev_cache)
            return _models_dev_cache
    except RuntimeError:
        pass

    if not _models_dev_cache:
        _models_dev_cache = _load_models_dev_disk_cache()
        if _models_dev_cache:
            _models_dev_cache_time = time.time() - _MODELS_DEV_CACHE_TTL_SECONDS + 300
    return _models_dev_cache


def fetch_openrouter_model_metadata(*, force_refresh: bool = False) -> Mapping[str, ResolvedModelMetadata]:
    global _openrouter_cache, _openrouter_cache_time
    if (
        not force_refresh
        and _openrouter_cache
        and (time.time() - _openrouter_cache_time) < _OPENROUTER_CACHE_TTL_SECONDS
    ):
        return _openrouter_cache

    try:
        payload = _request_json_object(OPENROUTER_MODELS_URL, timeout_seconds=10.0)
    except RuntimeError:
        return _openrouter_cache
    cache: dict[str, ResolvedModelMetadata] = {}
    for model in _model_items(payload):
        model_id = str(model.get("id") or "").strip()
        if not model_id:
            continue
        top_provider = model.get("top_provider")
        output = None
        if isinstance(top_provider, Mapping):
            output = _coerce_reasonable_int(top_provider.get("max_completion_tokens"))
        entry = ResolvedModelMetadata(
            context_window_tokens=_extract_nested_int(model, _CONTEXT_KEYS),
            max_output_tokens=output or _extract_nested_int(model, _OUTPUT_KEYS),
            source="openrouter",
        )
        _add_metadata_aliases(cache, model_id, entry)
        canonical_slug = str(model.get("canonical_slug") or "").strip()
        if canonical_slug:
            _add_metadata_aliases(cache, canonical_slug, entry)
    _openrouter_cache = cache
    _openrouter_cache_time = time.time()
    return _openrouter_cache


def fetch_endpoint_model_metadata(
    *,
    base_url: str,
    api_key: str | None = None,
    force_refresh: bool = False,
) -> Mapping[str, ResolvedModelMetadata]:
    normalized = _normalize_base_url(base_url)
    if not normalized:
        return {}
    if not force_refresh:
        cached = _endpoint_metadata_cache.get(normalized)
        cached_at = _endpoint_metadata_cache_time.get(normalized, 0)
        if cached is not None and (time.time() - cached_at) < _ENDPOINT_CACHE_TTL_SECONDS:
            return cached

    candidates = [normalized]
    alternate = normalized[:-3].rstrip("/") if normalized.endswith("/v1") else f"{normalized}/v1"
    if alternate and alternate not in candidates:
        candidates.append(alternate)

    for candidate in candidates:
        payload = _request_json_object(
            f"{candidate.rstrip('/')}/models",
            headers=_bearer_headers(api_key),
            timeout_seconds=5.0,
        )
        if not payload:
            continue
        cache: dict[str, ResolvedModelMetadata] = {}
        for model in _model_items(payload):
            model_id = str(model.get("id") or model.get("key") or "").strip()
            if not model_id:
                continue
            entry = ResolvedModelMetadata(
                context_window_tokens=_extract_nested_int(model, _CONTEXT_KEYS),
                max_output_tokens=_extract_nested_int(model, _OUTPUT_KEYS),
                source="endpoint:/models",
            )
            _add_metadata_aliases(cache, model_id, entry)
        if cache:
            _endpoint_metadata_cache[normalized] = cache
            _endpoint_metadata_cache_time[normalized] = time.time()
            return cache

    _endpoint_metadata_cache[normalized] = {}
    _endpoint_metadata_cache_time[normalized] = time.time()
    return {}


def is_local_endpoint(base_url: str | None) -> bool:
    normalized = _normalize_base_url(base_url)
    if not normalized:
        return False
    try:
        parsed = urlparse(normalized if "://" in normalized else f"http://{normalized}")
    except ValueError:
        return False
    host = parsed.hostname or ""
    if host in _LOCAL_HOSTS or any(host.endswith(suffix) for suffix in _CONTAINER_LOCAL_SUFFIXES):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_link_local


def infer_provider_from_url(base_url: str | None) -> str | None:
    normalized = _normalize_base_url(base_url)
    if not normalized:
        return None
    parsed = urlparse(normalized if "://" in normalized else f"https://{normalized}")
    host = parsed.netloc.lower() or parsed.path.lower()
    for url_part, provider_id in _URL_TO_PROVIDER.items():
        if url_part in host:
            return provider_id
    return None


def _effective_provider_id(*, provider_id: str, base_url: str | None) -> str:
    normalized_provider = provider_id.strip().lower()
    if normalized_provider in {"", "openai-compatible"}:
        return infer_provider_from_url(base_url) or normalized_provider
    return normalized_provider


def _request_json_object(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout_seconds: float = 10.0,
) -> Mapping[str, Any] | None:
    http_request = request.Request(url, headers=dict(headers or {}), method="GET")
    try:
        with request.urlopen(http_request, timeout=timeout_seconds) as response:
            raw_body = response.read().decode("utf-8")
    except (error.HTTPError, error.URLError, TimeoutError) as exc:
        return None
    try:
        payload = json.loads(raw_body) if raw_body else {}
    except json.JSONDecodeError:
        return None
    if isinstance(payload, list):
        return {"data": payload}
    if not isinstance(payload, Mapping):
        return None
    return payload


def _model_items(payload: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    for key in ("data", "models"):
        value = payload.get(key)
        if isinstance(value, list):
            return tuple(item for item in value if isinstance(item, Mapping))
    return ()


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


def _find_model_entry(models: Mapping[str, Any], model_id: str) -> Mapping[str, Any] | None:
    entry = models.get(model_id)
    if isinstance(entry, Mapping):
        return entry
    model_lower = model_id.casefold()
    for candidate_id, candidate in models.items():
        if str(candidate_id).casefold() == model_lower and isinstance(candidate, Mapping):
            return candidate
    return None


def _find_metadata_entry(
    metadata: Mapping[str, ResolvedModelMetadata],
    model_id: str,
) -> ResolvedModelMetadata | None:
    entry = metadata.get(model_id)
    if entry is not None:
        return entry
    if "/" not in model_id:
        for candidate_id, candidate in metadata.items():
            if candidate_id.rsplit("/", 1)[-1] == model_id:
                return candidate
    model_lower = model_id.casefold()
    for candidate_id, candidate in metadata.items():
        if candidate_id.casefold() == model_lower:
            return candidate
    return None


def _add_metadata_aliases(
    cache: dict[str, ResolvedModelMetadata],
    model_id: str,
    entry: ResolvedModelMetadata,
) -> None:
    cache[model_id] = entry
    if "/" in model_id:
        cache.setdefault(model_id.rsplit("/", 1)[1], entry)


def _model_id_matches(candidate_id: str, lookup_model: str) -> bool:
    if candidate_id == lookup_model:
        return True
    return "/" in candidate_id and candidate_id.rsplit("/", 1)[1] == lookup_model


def _bearer_headers(api_key: str | None) -> dict[str, str]:
    resolved = str(api_key or "").strip()
    return {"Authorization": f"Bearer {resolved}"} if resolved else {}


def _normalize_base_url(base_url: str | None) -> str:
    return str(base_url or "").strip().rstrip("/")


def _models_dev_disk_cache_path() -> Path:
    override = os.environ.get("ELEPHANT_MODELS_DEV_CACHE_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    return default_cli_state_dir() / "models-dev-cache.json"


def _context_length_cache_path() -> Path:
    override = os.environ.get("ELEPHANT_CONTEXT_LENGTH_CACHE_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    return default_cli_state_dir() / "context-length-cache.json"


def _context_length_cache_key(model_id: str, base_url: str) -> str:
    return f"{model_id}@{base_url}"


def _load_context_length_cache() -> dict[str, int]:
    path = _context_length_cache_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    raw_cache = payload.get("context_lengths") if isinstance(payload, Mapping) else None
    if not isinstance(raw_cache, Mapping):
        return {}
    cache: dict[str, int] = {}
    for key, value in raw_cache.items():
        parsed = _coerce_reasonable_int(value)
        if parsed is not None:
            cache[str(key)] = parsed
    return cache


def _save_context_length_cache(cache: Mapping[str, int]) -> None:
    path = _context_length_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            json.dump({"context_lengths": dict(cache)}, handle, separators=(",", ":"))
            temp_name = handle.name
        Path(temp_name).replace(path)
    except OSError:
        return


def _load_models_dev_disk_cache() -> dict[str, Any]:
    path = _models_dev_disk_cache_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _save_models_dev_disk_cache(payload: Mapping[str, Any]) -> None:
    path = _models_dev_disk_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            json.dump(dict(payload), handle, separators=(",", ":"))
            temp_name = handle.name
        Path(temp_name).replace(path)
    except OSError:
        return


__all__ = [
    "ResolvedModelMetadata",
    "fetch_endpoint_model_metadata",
    "fetch_models_dev_registry",
    "fetch_openrouter_model_metadata",
    "get_cached_context_length",
    "infer_provider_from_url",
    "is_local_endpoint",
    "lookup_models_dev_metadata",
    "lookup_openrouter_metadata",
    "query_local_endpoint_metadata",
    "resolve_provider_model_metadata",
    "save_context_length",
]
