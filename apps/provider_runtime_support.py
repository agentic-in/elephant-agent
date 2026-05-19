"""Shared provider runtime wiring for product surfaces.

This module keeps surface-level provider profile parsing, encrypted local
credential lookup, endpoint model discovery, and runtime capability selection
in one place so CLI, API, and gateway do not each keep private copies of the
same rules.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any
from urllib import error, request
from urllib.parse import quote

from packages.auth import (
    AuthProfile,
    LocalEncryptedSecretCipher,
    PersistentAuthProfileStore,
    ProviderCatalog,
    ProviderProfileFactory,
    ProviderProfileInput,
    SecretValueResolution,
    SecretReference,
    SecretStore,
    profile_from_input,
)
from packages.models.discovery import DiscoveredProviderModel, DiscoveredProviderState
from packages.models.provider_catalog import provider_definition
from packages.models.provider_runtime import provider_auth_headers
from packages.storage import RuntimeStorageRepository

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


def _provider_request_headers(
    *,
    provider_id: str,
    request_family: str,
    api_key: str | None,
    extra_headers: Mapping[str, str] | None = None,
) -> dict[str, str]:
    return {
        "Accept": "application/json",
        **dict(extra_headers or {}),
        **provider_auth_headers(
            provider_id=provider_id,
            request_family=request_family,
            api_key=api_key,
        ),
    }


def _request_json(
    *,
    url: str,
    headers: Mapping[str, str],
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    from packages.models import request_json as _models_request_json

    return _models_request_json(
        url=url,
        headers=headers,
        timeout_seconds=timeout_seconds,
    )


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


def _query_ollama_context_window(*, model_id: str, base_url: str, timeout_seconds: float = 5.0) -> int | None:
    server_url = _ollama_server_root(base_url)
    if not server_url:
        return None
    body = json.dumps({"name": model_id}).encode("utf-8")
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
        with request.urlopen(http_request, timeout=timeout_seconds) as response:
            raw_body = response.read().decode("utf-8")
            payload = json.loads(raw_body) if raw_body else {}
    except (
        error.HTTPError,
        error.URLError,
        json.JSONDecodeError,
    ):  # pragma: no cover - covered by caller fallback
        return None
    if not isinstance(payload, Mapping):
        return None
    return _context_window_from_ollama_show_payload(payload)


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


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return {str(key): value for key, value in payload.items()}


def _jwt_claims(token: str) -> Mapping[str, Any]:
    parts = str(token or "").split(".")
    if len(parts) < 2:
        return {}
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(decoded.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): value for key, value in payload.items()}


def _jwt_token_is_expiring(token: str, *, skew_seconds: int = 0) -> bool:
    claims = _jwt_claims(token)
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        return False
    return float(exp) <= (datetime.now(timezone.utc).timestamp() + max(0, int(skew_seconds)))


def _timestamp_string_is_expiring(value: Any, *, skew_seconds: int = 0) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        expires_at = datetime.fromisoformat(text)
    except ValueError:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at.timestamp() <= (datetime.now(timezone.utc).timestamp() + max(0, int(skew_seconds)))


def _codex_auth_path() -> Path:
    codex_home = os.environ.get("CODEX_HOME", "").strip()
    if not codex_home:
        codex_home = str(Path.home() / ".codex")
    return Path(codex_home).expanduser() / "auth.json"


def _read_codex_cli_resolution() -> SecretValueResolution | None:
    auth_path = _codex_auth_path()
    if not auth_path.is_file():
        return None
    payload = _read_json_object(auth_path)
    if payload is None:
        return None
    tokens = payload.get("tokens")
    if not isinstance(tokens, Mapping):
        return None
    access_token = str(tokens.get("access_token", "") or "").strip()
    refresh_token = str(tokens.get("refresh_token", "") or "").strip()
    if not access_token or not refresh_token or _jwt_token_is_expiring(access_token):
        return None
    return SecretValueResolution(value=access_token, source=f"codex-cli:{auth_path}")


def _qwen_auth_path() -> Path:
    return Path.home() / ".qwen" / "oauth_creds.json"


def _claude_code_credentials_path() -> Path:
    return Path.home() / ".claude" / ".credentials.json"


def _read_qwen_oauth_resolution() -> SecretValueResolution | None:
    auth_path = _qwen_auth_path()
    if not auth_path.is_file():
        return None
    payload = _read_json_object(auth_path)
    if payload is None:
        return None
    access_token = str(payload.get("access_token", "") or "").strip()
    if not access_token:
        return None
    try:
        expiry_ms = int(payload.get("expiry_date"))
    except (TypeError, ValueError):
        expiry_ms = 0
    if expiry_ms and expiry_ms <= int(datetime.now(timezone.utc).timestamp() * 1000):
        return None
    return SecretValueResolution(value=access_token, source=f"qwen-cli:{auth_path}")


def _read_google_gemini_oauth_resolution() -> SecretValueResolution | None:
    return None


def _read_anthropic_token_from_payload(
    path: Path, payload: Mapping[str, Any], *, source: str
) -> SecretValueResolution | None:
    claude_code_oauth = payload.get("claudeAiOauth")
    if isinstance(claude_code_oauth, Mapping):
        payload = {str(key): value for key, value in claude_code_oauth.items()}
    access_token = str(payload.get("accessToken") or payload.get("access_token") or payload.get("token") or "").strip()
    if not access_token:
        return None
    expires_at = payload.get("expiresAt") or payload.get("expires_at")
    if _timestamp_string_is_expiring(expires_at):
        return None
    return SecretValueResolution(value=access_token, source=f"{source}:{path}")


def _read_anthropic_oauth_resolution() -> SecretValueResolution | None:
    for env_name in ("ANTHROPIC_TOKEN",):
        value = os.environ.get(env_name)
        if value:
            return SecretValueResolution(value=value, source=f"env:{env_name}")
    return None


def _read_claude_code_oauth_resolution() -> SecretValueResolution | None:
    path = _claude_code_credentials_path()
    if path.is_file():
        payload = _read_json_object(path)
        if payload is not None:
            resolution = _read_anthropic_token_from_payload(path, payload, source="claude-code-oauth")
            if resolution is not None:
                return resolution
    value = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    if value:
        return SecretValueResolution(value=value, source="env:CLAUDE_CODE_OAUTH_TOKEN")
    return None


def _read_copilot_resolution() -> SecretValueResolution | None:
    for env_name in ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
        value = str(os.environ.get(env_name) or "").strip()
        if value and not value.startswith("ghp_"):
            return SecretValueResolution(value=value, source=f"env:{env_name}")
    clean_env = {key: value for key, value in os.environ.items() if key not in {"GH_TOKEN", "GITHUB_TOKEN"}}
    try:
        completed = subprocess.run(
            ["gh", "auth", "token"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
            env=clean_env,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    token = completed.stdout.strip()
    if not token or token.startswith("ghp_"):
        return None
    return SecretValueResolution(value=token, source="gh auth token")


def _copilot_acp_status() -> tuple[str, str] | None:
    base_url = os.environ.get("COPILOT_ACP_BASE_URL", "").strip()
    if base_url.startswith("acp+tcp://"):
        return (base_url, "env:COPILOT_ACP_BASE_URL")
    command = (
        os.environ.get("ELEPHANT_COPILOT_ACP_COMMAND", "").strip()
        or os.environ.get("COPILOT_CLI_PATH", "").strip()
        or "copilot"
    )
    resolved = shutil.which(command) if command else None
    if resolved:
        return ("acp://copilot", f"command:{resolved}")
    return None


def _base_url_aliases(provider_id: str) -> tuple[str, ...]:
    del provider_id
    return ()


def _provider_base_url_from_env(provider_id: str, primary_env_var: str | None) -> str | None:
    candidates = []
    if primary_env_var:
        candidates.append(primary_env_var)
    candidates.extend(_base_url_aliases(provider_id))
    for env_name in candidates:
        value = os.environ.get(env_name, "").strip()
        if value:
            return value
    return None


def provider_profile_from_payload(payload: Mapping[str, Any]) -> AuthProfile:
    if "profile_id" not in payload or "provider_id" not in payload:
        raise ValueError("provider_profile must include profile_id and provider_id")
    secret_references = tuple(secret_reference_from_payload(item) for item in payload.get("secret_references", ()))
    profile_input = ProviderProfileInput(
        profile_id=str(payload["profile_id"]),
        provider_id=str(payload["provider_id"]),
        secret_references=secret_references,
        priority=int(payload.get("priority", 0)),
        session_pin=str(payload["session_pin"]) if payload.get("session_pin") is not None else None,
        cooldown_until=None,
        metadata={str(key): str(value) for key, value in dict(payload.get("metadata", {})).items()},
    )
    provider_id = profile_input.provider_id
    base_url = payload.get("base_url")
    default_model = payload.get("default_model")
    transport_id = payload.get("transport_id")
    auth_method = payload.get("auth_method")
    provider_kind = payload.get("provider_kind")
    extra_headers = payload.get("extra_headers")
    catalog = ProviderCatalog.with_defaults()
    provider_defaults = catalog.get(provider_id)
    if provider_id == "openai-compatible" and (base_url is None or default_model is None):
        raise ValueError("openai-compatible provider profiles require base_url and default_model")
    if any(
        value is not None
        for value in (
            base_url,
            default_model,
            transport_id,
            auth_method,
            provider_kind,
            extra_headers,
        )
    ):
        default_profile = None
        if provider_defaults is not None:
            default_profile = ProviderProfileFactory(catalog).from_provider_defaults(
                provider_id,
                profile_id=profile_input.profile_id,
                secret_references=profile_input.secret_references,
                priority=profile_input.priority,
                session_pin=profile_input.session_pin,
                cooldown_until=profile_input.cooldown_until,
                metadata=profile_input.metadata,
            )
        return profile_from_input(
            profile_input,
            base_url=(
                str(base_url)
                if base_url is not None
                else (default_profile.base_url if default_profile is not None else "")
            ),
            default_model=(
                str(default_model)
                if default_model is not None
                else (default_profile.default_model if default_profile is not None else "")
            ),
            transport_id=(
                str(transport_id)
                if transport_id is not None
                else (default_profile.transport_id if default_profile is not None else "openai-compatible")
            ),
            auth_method=(
                str(auth_method)
                if auth_method is not None
                else (default_profile.auth_method if default_profile is not None else "api_key")
            ),
            provider_kind=(
                str(provider_kind)
                if provider_kind is not None
                else (default_profile.provider_kind if default_profile is not None else "custom")
            ),
            extra_headers=(
                {
                    **(dict(default_profile.extra_headers) if default_profile is not None else {}),
                    **{str(key): str(value) for key, value in dict(extra_headers or {}).items()},
                }
            ),
        )
    factory = ProviderProfileFactory(catalog)
    return factory.from_provider_defaults(
        provider_id,
        profile_id=profile_input.profile_id,
        secret_references=profile_input.secret_references,
        priority=profile_input.priority,
        session_pin=profile_input.session_pin,
        cooldown_until=profile_input.cooldown_until,
        metadata=profile_input.metadata,
    )


def secret_reference_from_payload(payload: Mapping[str, Any]) -> SecretReference:
    return SecretReference(
        reference_id=str(payload["reference_id"]),
        provider_id=str(payload["provider_id"]),
        secret_name=str(payload["secret_name"]),
        secret_key=str(payload["secret_key"]),
        source=str(payload.get("source", "elephant")),
        metadata={str(key): str(value) for key, value in dict(payload.get("metadata", {})).items()},
    )


def load_provider_profile(state_dir: Path, *, config_path: Path | None = None) -> AuthProfile | None:
    """Load the active provider profile from config.yaml (models.provider)."""
    if config_path is not None:
        from packages.runtime_config import (
            load_global_config,
            load_provider_from_config,
        )

        try:
            config = load_global_config(config_path, state_dir=state_dir)
            provider_payload = load_provider_from_config(config)
            if isinstance(provider_payload, dict):
                return provider_profile_from_payload(provider_payload)
        except (OSError, ValueError, KeyError):
            pass
    return None


RUNTIME_LOCAL_SECRET_ENV_FILE = "runtime-local-secrets.json"


def runtime_local_secret_env_path(state_dir: Path) -> Path:
    return state_dir / RUNTIME_LOCAL_SECRET_ENV_FILE


def load_runtime_local_secret_env(state_dir: Path | None) -> dict[str, str]:
    if state_dir is None:
        return {}
    path = runtime_local_secret_env_path(state_dir)
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a JSON object")
    resolved: dict[str, str] = {}
    for key, value in payload.items():
        text = str(value).strip()
        if text:
            resolved[str(key)] = text
    return resolved


def persist_runtime_local_secret_env(
    state_dir: Path | None,
    updates: Mapping[str, str],
) -> Path | None:
    if state_dir is None:
        return None
    filtered = {str(key): str(value).strip() for key, value in updates.items() if str(value).strip()}
    if not filtered:
        return None
    state_dir.mkdir(parents=True, exist_ok=True)
    path = runtime_local_secret_env_path(state_dir)
    payload = load_runtime_local_secret_env(state_dir)
    payload.update(filtered)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def capture_runtime_secret_env(
    state_dir: Path | None,
    profile: AuthProfile | None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path | None:
    if profile is None:
        return None
    source = os.environ if environ is None else environ
    updates: dict[str, str] = {}
    for reference in profile.secret_references:
        for env_var in reference.env_var_candidates():
            value = str(source.get(env_var) or "").strip()
            if value:
                updates[env_var] = value
    return persist_runtime_local_secret_env(state_dir, updates)


def build_runtime_secret_environ(
    state_dir: Path | None,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    resolved = load_runtime_local_secret_env(state_dir)
    source = os.environ if environ is None else environ
    resolved.update({str(key): str(value) for key, value in source.items()})
    return resolved


def _normalize_env_name(candidate: str) -> str:
    return candidate.strip().replace("-", "_").replace(".", "_").upper()


class EnvironmentSecretStore(SecretStore):
    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self.environ = environ

    def resolve(self, reference: SecretReference) -> SecretValueResolution:
        env = self.environ or os.environ
        candidates: list[str] = list(reference.env_var_candidates())
        seen = set(candidates)
        for candidate in (
            reference.secret_name,
            reference.secret_key,
            reference.reference_id,
        ):
            normalized = _normalize_env_name(candidate)
            if normalized and normalized not in seen:
                seen.add(normalized)
                candidates.append(normalized)
        for candidate in candidates:
            value = env.get(candidate)
            if value is not None:
                return SecretValueResolution(value=value, source=f"env:{candidate}")
        raise LookupError(f"missing environment secret for reference: {reference.reference_id}")

    def read(self, reference: SecretReference) -> str:
        return self.resolve(reference).value


class EncryptedRepositorySecretStore(SecretStore):
    def __init__(
        self,
        repository: RuntimeStorageRepository,
        *,
        cipher: LocalEncryptedSecretCipher,
    ) -> None:
        self.repository = repository
        self.cipher = cipher

    def resolve(self, reference: SecretReference) -> SecretValueResolution:
        stored = self.repository.load_auth_secret_value(reference.reference_id)
        if stored is not None:
            return SecretValueResolution(
                value=self.cipher.decrypt(stored),
                source="encrypted-local-store",
            )
        for env_name in reference.env_var_candidates():
            value = os.environ.get(env_name)
            if value is not None:
                if reference.provider_id.strip().lower() == "copilot" and value.strip().startswith("ghp_"):
                    continue
                return SecretValueResolution(value=value, source=f"env:{env_name}")
        external = self._external_resolution(reference)
        if external is not None:
            return external
        raise LookupError(f"missing stored secret for reference: {reference.reference_id}")

    def read(self, reference: SecretReference) -> str:
        return self.resolve(reference).value

    def _external_resolution(self, reference: SecretReference) -> SecretValueResolution | None:
        provider_id = reference.provider_id.strip().lower()
        if provider_id == "anthropic":
            return _read_anthropic_oauth_resolution()
        if provider_id == "claude-code":
            return _read_claude_code_oauth_resolution()
        if provider_id == "openai-codex":
            return _read_codex_cli_resolution()
        if provider_id == "google-gemini-cli":
            return _read_google_gemini_oauth_resolution()
        if provider_id == "qwen-oauth":
            return _read_qwen_oauth_resolution()
        if provider_id == "copilot":
            return _read_copilot_resolution()
        return None


from packages.auth import (
    EncryptedRepositorySecretStore as _PackageEncryptedRepositorySecretStore,
    EnvironmentSecretStore as _PackageEnvironmentSecretStore,
)
from packages.models.bootstrap import (
    EmbeddingBootstrapState as _PackageEmbeddingBootstrapState,
    load_embedding_bootstrap_state as _package_load_embedding_bootstrap_state,
    persist_embedding_bootstrap_state as _package_persist_embedding_bootstrap_state,
    resolve_embedding_bootstrap_state as _package_resolve_embedding_bootstrap_state,
    run_embedding_bootstrap_worker as _package_run_embedding_bootstrap_worker,
    trigger_embedding_bootstrap as _package_trigger_embedding_bootstrap,
)

EmbeddingBootstrapState = _PackageEmbeddingBootstrapState
EnvironmentSecretStore = _PackageEnvironmentSecretStore
EncryptedRepositorySecretStore = _PackageEncryptedRepositorySecretStore
load_embedding_bootstrap_state = _package_load_embedding_bootstrap_state
persist_embedding_bootstrap_state = _package_persist_embedding_bootstrap_state
resolve_embedding_bootstrap_state = _package_resolve_embedding_bootstrap_state
run_embedding_bootstrap_worker = _package_run_embedding_bootstrap_worker
trigger_embedding_bootstrap = _package_trigger_embedding_bootstrap


def register_provider_profile(
    repository: RuntimeStorageRepository,
    payload: Mapping[str, Any],
) -> AuthProfile:
    profile = provider_profile_from_payload(payload)
    PersistentAuthProfileStore(repository).register(profile)
    return profile


_APP_PROVIDER_RUNTIME_COMPAT_EXPORTS = {
    "DiscoveredProviderModel",
    "DiscoveredProviderState",
    "EmbeddingBootstrapState",
    "EncryptedRepositorySecretStore",
    "EnvironmentSecretStore",
    "load_embedding_bootstrap_state",
    "persist_embedding_bootstrap_state",
    "resolve_embedding_bootstrap_state",
    "run_embedding_bootstrap_worker",
    "trigger_embedding_bootstrap",
    "generation_model_profile_from_auth_profile",
    "support_model_profile_from_auth_profile",
    "provider_profile_summary",
    "provider_fallback_summary",
}

__all__ = [name for name in globals() if not name.startswith("_") and name not in _APP_PROVIDER_RUNTIME_COMPAT_EXPORTS]
