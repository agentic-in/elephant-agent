"""Provider methods for the API runtime app."""


from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass, replace
from pathlib import Path
import json
from typing import Any, Mapping
from uuid import uuid4

from apps.provider_runtime import provider_profile_from_payload
from packages.embeddings import (
    ELEPHANT_EMBED_DEFAULT_DIMENSIONS,
    ELEPHANT_EMBED_MODEL_ID,
    ELEPHANT_EMBED_PROVIDER_ID,
    ELEPHANT_EMBED_PROVIDER_KIND,
    OPENAI_COMPATIBLE_EMBED_DEFAULT_SECRET_ENV_VAR,
    OPENAI_COMPATIBLE_EMBED_PROFILE_ID,
    OPENAI_COMPATIBLE_EMBED_PROVIDER_ID,
    OPENAI_COMPATIBLE_EMBED_SECRET_REFERENCE_ID,
    default_local_embedding_provider_config,
)
from packages.models import SurfaceModelProviderCapability
from packages.auth import AuthProfile, PersistentAuthProfileStore, SecretReference
from packages.context import ContextRuntime
from packages.contracts import (
    ContextBundle,
    Episode,
    EventEnvelope,
    ExecutionResult,
)
from packages.contracts.runtime import PersonalModelRuntimeState, RecallEvidence
from packages.kernel import KernelDependencies, KernelOutcome, KernelService, KernelSourceRequest, ReconciliationPipeline, StateReconciler
from packages.evidence.recall_runtime import RecallRuntime
from packages.operator.runtime import (
    RecallEvidenceOperatorDetail,
    RecallEvidenceSearchHit,
    ProcedureOperatorDetail,
    build_recall_evidence_operator_surface,
    build_procedure_operator_surface,
    build_profile_operator_surface,
)
from packages.storage import RuntimeStorageRepository
from packages.runtime_config import global_config_path_for_state_dir, save_provider_to_config
from packages.tools import BuiltinToolDependencies, build_tool_runtime
from packages.tools.adapters import DeliveryMessageSurfaceAdapter, StructuredClarifySurface
from packages.tools.browser_backend import create_playwright_browser_backend

from .capabilities import (
    APIContextCapability,
    APIDeliveryCapability,
    APIRecallCapability,
    APIModelProvider,
    APITelemetrySink,
    APIToolExecution,
)
from .state_runtime import APIContinuityInspection, APIStateService

from .api_runtime_support import (
    APIAppConfig,
    APIResponse,
    APIEpisodeCreationResult,
    APIEpisodeInspection,
    APIEpisodeTransitionResult,
    APILoopRecord,
    APILoopResult,
    _coerce_str_tuple,
    _json_bytes,
    _jsonable,
    _now,
    _optional_bool,
    _optional_datetime,
    _optional_str,
    _read_json_bytes,
    _split_path,
)

_EMBEDDING_API_KEY_ENV_VAR = OPENAI_COMPATIBLE_EMBED_DEFAULT_SECRET_ENV_VAR
_EMBEDDING_API_KEY_REFERENCE_ID = OPENAI_COMPATIBLE_EMBED_SECRET_REFERENCE_ID


def _persist_default_provider(self, provider_profile: Mapping[str, Any]) -> None:
    """Write provider profile to config.yaml."""
    state_dir = self.repository.database_path.parent
    config_path = global_config_path_for_state_dir(self.repository.database_path.parent)
    save_provider_to_config(
        config_path,
        state_dir=state_dir,
        provider_payload=provider_profile,
    )


def list_providers(self) -> dict[str, Any]:
    providers = []
    for record in self.model_provider.runtime_resolver.list_catalog():
        provider = record.as_mapping()
        try:
            discovered_state = asdict(self.model_provider.discovered_provider_state(record.provider_id))
            provider["discovered_state"] = discovered_state
            provider["status"] = discovered_state.get("status")
            provider["source"] = discovered_state.get("source")
        except Exception:
            pass
        providers.append(provider)
    return {
        "active_provider": self.model_provider.describe(),
        "providers": providers,
    }

def setup_provider(self, provider_id: str) -> dict[str, Any]:
    guide = self.model_provider.runtime_resolver.build_setup_guide(provider_id)
    return {
        "active_provider": self.model_provider.describe(),
        "guide": guide.as_mapping(),
    }

def discover_provider_models(self, payload: Mapping[str, Any]) -> dict[str, Any]:
    provider_id = str(payload.get("providerId") or payload.get("provider_id") or "").strip()
    if not provider_id:
        raise ValueError("providerId is required")
    base_url = str(payload.get("baseUrl") or payload.get("base_url") or "").strip() or None
    api_key = str(payload.get("apiKey") or payload.get("api_key") or "").strip() or None
    models = self.model_provider.discover_models(
        provider_id=provider_id,
        base_url=base_url,
        api_key=api_key,
    )
    return {
        "active_provider": self.model_provider.describe(),
        "providerId": provider_id,
        "baseUrl": base_url,
        "models": [asdict(model) for model in models],
    }

def _metadata_context_window_tokens(metadata: Mapping[str, str]) -> int | None:
    raw_value = metadata.get("context_window_tokens")
    if raw_value is None:
        return None
    try:
        parsed = int(str(raw_value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _profile_payload_with_metadata(payload: Mapping[str, Any], profile: AuthProfile) -> dict[str, Any]:
    next_payload = dict(payload)
    next_payload["metadata"] = {
        **{str(key): str(value) for key, value in dict(payload.get("metadata", {})).items()},
        **{str(key): str(value) for key, value in dict(profile.metadata).items()},
    }
    return next_payload


def _provider_profile_with_auto_context(self, profile: AuthProfile) -> AuthProfile:
    metadata = {str(key): str(value) for key, value in dict(profile.metadata).items()}
    context_window_mode = str(metadata.get("context_window_mode") or "auto").strip().lower() or "auto"
    metadata["context_window_mode"] = context_window_mode
    if context_window_mode == "manual" or _metadata_context_window_tokens(metadata) is not None:
        return replace(profile, metadata=metadata)
    model_id = str(profile.default_model or "").strip()
    if not model_id:
        return replace(profile, metadata=metadata)
    try:
        detected = self.model_provider.detect_context_window(
            provider_id=profile.provider_id,
            base_url=profile.base_url,
            model_id=model_id,
        )
    except Exception:
        detected = None
    if detected is not None:
        metadata["context_window_tokens"] = str(detected)
    return replace(profile, metadata=metadata)


def set_default_provider(self, provider_profile: Mapping[str, Any]) -> dict[str, Any]:
    active_profile = _provider_profile_with_auto_context(self, provider_profile_from_payload(provider_profile))
    enriched_provider_profile = _profile_payload_with_metadata(provider_profile, active_profile)
    _persist_default_provider(self, enriched_provider_profile)
    self.auth_store.register(active_profile)
    self.model_provider.set_active_profile(
        provider_profile_id=active_profile.profile_id,
        provider_id=active_profile.provider_id,
    )
    return {
        "provider_profile": active_profile,
        "active_provider": self.model_provider.describe(),
    }

def _provider_probe(
    self,
    *,
    prompt: str,
) -> ExecutionResult:
    active_profile = self.model_provider.active_profile()
    profile = PersonalModelRuntimeState(
        profile_id=f"provider-test:{active_profile.provider_id if active_profile is not None else 'preview'}",
        display_name=active_profile.provider_id if active_profile is not None else "Provider Test",
        mode="default",
    )
    session = Episode(
        episode_id=f"episode:provider-test:{uuid4().hex[:8]}",
        state_id="state:provider-test",
        personal_model_id=profile.profile_id,
        entry_surface="api",
        elephant_id="provider-test",
        status="open",
        started_at=_now(),
        updated_at=_now(),
    )
    context = ContextBundle(
        bundle_id=f"bundle:provider-test:{uuid4().hex[:8]}",
        episode_id=session.episode_id,
        instruction_refs=("apps/api",),
        work_item_ids=(),
        evidence_refs=(),
        artifact_ids=(),
        token_budget=512,
        rendered_prompt="provider test",
    )
    return self.model_provider.generate(
        profile=profile,
        session=session,
        context=context,
        prompt=prompt,
    )

def test_provider(self, *, prompt: str = "Summarize the current provider configuration.") -> dict[str, Any]:
    active_provider = self.model_provider.describe()
    try:
        result = self._provider_probe(prompt=prompt)
    except Exception as error:  # pragma: no cover - defensive surface guard
        return {
            "active_provider": active_provider,
            "status": "not-ready",
            "error": str(error),
        }
    return {
        "active_provider": active_provider,
        "status": "ok",
        "result": result,
    }

def doctor_provider(self) -> dict[str, Any]:
    active_provider = self.model_provider.describe()
    bootstrap_check = {
        "check": "embedding_bootstrap",
        "status": str(active_provider.get("embedding_bootstrap_status") or "unknown"),
        "summary": str(active_provider.get("embedding_bootstrap_summary") or ""),
    }
    if active_provider["source"] != "configured":
        return {
            "status": "preview",
            "active_provider": active_provider,
            "checks": (
                {"check": "provider_profile", "status": "missing"},
                {"check": "credentials", "status": "preview"},
                bootstrap_check,
            ),
            "probe_summary": "",
        }
    try:
        probe = self._provider_probe(prompt="Doctor check")
    except Exception as error:  # pragma: no cover - defensive surface guard
        return {
            "status": "not-ready",
            "active_provider": active_provider,
            "checks": (
                {"check": "provider_profile", "status": "configured"},
                {"check": "credentials", "status": "missing", "summary": str(error)},
                bootstrap_check,
            ),
            "probe_summary": "",
        }
    return {
        "status": "ready",
        "active_provider": active_provider,
        "checks": (
            {"check": "provider_profile", "status": "configured"},
            {"check": "credentials", "status": "available"},
            bootstrap_check,
            {"check": "runtime", "status": "ok", "summary": probe.summary},
        ),
        "probe_summary": probe.summary,
    }


def _embedding_provider_profile(self) -> AuthProfile | None:
    profile = self.repository.load_auth_profile(OPENAI_COMPATIBLE_EMBED_PROFILE_ID)
    if profile is None or profile.provider_id != OPENAI_COMPATIBLE_EMBED_PROVIDER_ID:
        return None
    return profile


def _active_embedding_provider_profile(self) -> AuthProfile | None:
    profile = self._embedding_provider_profile()
    if profile is None:
        return None
    if str(profile.metadata.get("embedding_active") or "").strip().lower() != "true":
        return None
    return profile


def _embedding_secret_reference(env_var: str | None = None) -> SecretReference:
    resolved_env_var = str(env_var or "").strip() or _EMBEDDING_API_KEY_ENV_VAR
    return SecretReference(
        reference_id=_EMBEDDING_API_KEY_REFERENCE_ID,
        provider_id=OPENAI_COMPATIBLE_EMBED_PROVIDER_ID,
        secret_name="api_token",
        secret_key="api_key",
        metadata={
            "storage": "local-vault",
            "scope": "embedding-provider",
            "env_var": resolved_env_var,
        },
    )


def _embedding_auth_profile(
    self,
    *,
    base_url: str,
    model_id: str,
    dimensions: int,
    reference: SecretReference,
    active: bool,
    configured_from: str,
) -> AuthProfile:
    existing = self._embedding_provider_profile()
    metadata = dict(existing.metadata) if existing is not None else {}
    metadata.update(
        {
            "embedding_active": "true" if active else "false",
            "dimensions": str(dimensions),
            "configured_from": configured_from,
        }
    )
    secret_env_var = str(reference.metadata.get("env_var") or "").strip()
    if secret_env_var:
        metadata["secret_env_var"] = secret_env_var
    return AuthProfile(
        profile_id=OPENAI_COMPATIBLE_EMBED_PROFILE_ID,
        provider_id=OPENAI_COMPATIBLE_EMBED_PROVIDER_ID,
        transport_id="openai-compatible",
        base_url=base_url,
        default_model=model_id,
        auth_method="api_key",
        provider_kind="embedding",
        secret_references=(reference,),
        metadata=metadata,
    )


def _embedding_dimensions(profile: AuthProfile) -> int:
    try:
        return int(str(profile.metadata.get("dimensions") or "0").replace(",", ""))
    except (TypeError, ValueError):
        return 0


def _stored_embedding_api_key(self, reference_id: str) -> str | None:
    stored = self.repository.load_auth_secret_value(reference_id)
    if stored is None:
        return None
    resolved = str(self.model_provider.secret_cipher.decrypt(stored) or "").strip()
    return resolved or None


def _stored_api_key_for_active_provider(self, provider_id: str) -> str | None:
    active_profile = self.model_provider.active_profile()
    if active_profile is None or active_profile.provider_id != provider_id:
        return None
    reference = next((item for item in active_profile.secret_references if item.secret_key == "api_key"), None)
    if reference is None or not self.repository.has_auth_secret_value(reference.reference_id):
        return None
    credentials = self.model_provider.resolve_credentials(active_profile)
    resolved = str(credentials.get("api_key", "")).strip()
    return resolved or None


def embedding_provider_summary(self) -> dict[str, Any]:
    active_provider = dict(self.model_provider.describe())
    profile = self._active_embedding_provider_profile()
    if profile is not None:
        reference = next((item for item in profile.secret_references if item.secret_key == "api_key"), None)
        reference_id = reference.reference_id if reference is not None else ""
        has_secret = bool(reference_id) and self.repository.has_auth_secret_value(reference_id)
        return {
            "source": "configured",
            "profile_id": profile.profile_id,
            "config_id": profile.profile_id,
            "provider_id": profile.provider_id,
            "provider_kind": profile.provider_kind,
            "model_id": profile.default_model or "",
            "dimensions": _embedding_dimensions(profile),
            "base_url": profile.base_url or "",
            "status": "active",
            "secret_status": "stored" if has_secret else "missing",
            "secret_reference_id": reference_id,
            "embedding_bootstrap_status": "external",
            "embedding_bootstrap_summary": "OpenAI-compatible embeddings do not use the local bootstrap worker.",
        }
    local_default = default_local_embedding_provider_config()
    return {
        "source": "local-default",
        "profile_id": "",
        "config_id": "local-default",
        "provider_id": local_default.get("provider_id") or ELEPHANT_EMBED_PROVIDER_ID,
        "provider_kind": local_default.get("provider_kind") or ELEPHANT_EMBED_PROVIDER_KIND,
        "model_id": local_default.get("model_id") or ELEPHANT_EMBED_MODEL_ID,
        "dimensions": local_default.get("dimensions") or ELEPHANT_EMBED_DEFAULT_DIMENSIONS,
        "base_url": "",
        "status": "active",
        "secret_status": "not-required",
        "secret_reference_id": "",
        "embedding_bootstrap_status": active_provider.get("embedding_bootstrap_status") or "unknown",
        "embedding_bootstrap_summary": active_provider.get("embedding_bootstrap_summary") or "",
    }


def set_local_embedding_provider(self) -> dict[str, Any]:
    profile = self._embedding_provider_profile()
    if profile is not None and str(profile.metadata.get("embedding_active") or "").strip().lower() == "true":
        self.repository.upsert_auth_profile(
            replace(
                profile,
                metadata={
                    **dict(profile.metadata),
                    "embedding_active": "false",
                    "configured_from": "api",
                },
            )
        )
    self.model_provider.ensure_embedding_bootstrap_state()
    return self.embedding_provider_summary()


def set_openai_compatible_embedding_provider(
    self,
    *,
    base_url: str,
    model_id: str,
    dimensions: int,
    api_key: str | None = None,
    secret_env_var: str | None = None,
) -> dict[str, Any]:
    resolved_base_url = str(base_url).strip()
    resolved_model_id = str(model_id).strip()
    if not resolved_base_url:
        raise ValueError("embedding base_url must not be empty")
    if not resolved_model_id:
        raise ValueError("embedding model must not be empty")
    if dimensions <= 0:
        raise ValueError("embedding dimensions must be positive")

    reference = _embedding_secret_reference(secret_env_var)
    persisted_api_key = (
        str(api_key or "").strip()
        or self._stored_embedding_api_key(reference.reference_id)
        or self._stored_api_key_for_active_provider("openai-compatible")
    )
    if not persisted_api_key:
        raise ValueError(
            "OpenAI-compatible embeddings require an API key; paste one here or configure an active OpenAI-compatible provider first."
        )

    profile = _embedding_auth_profile(
        self,
        base_url=resolved_base_url,
        model_id=resolved_model_id,
        dimensions=dimensions,
        reference=reference,
        active=True,
        configured_from="api",
    )
    self.repository.upsert_auth_profile(profile)
    self.model_provider.store_secret_value(reference, persisted_api_key)
    return self.embedding_provider_summary()


def set_embedding_provider(self, payload: Mapping[str, Any]) -> dict[str, Any]:
    source = str(payload.get("source") or payload.get("provider") or "").strip().lower()
    if source in {"", "local", "elephant-embed", "local-default"}:
        return {"embedding_provider": self.set_local_embedding_provider()}
    if source not in {"openai-compatible", "external", "provider"}:
        raise ValueError("embedding provider source must be elephant-embed or openai-compatible")
    dimensions_raw = payload.get("dimensions")
    try:
        dimensions = int(str(dimensions_raw or "").replace(",", ""))
    except ValueError as error:
        raise ValueError("embedding dimensions must be a positive integer") from error
    return {
        "embedding_provider": self.set_openai_compatible_embedding_provider(
            base_url=str(payload.get("baseUrl") or payload.get("base_url") or ""),
            model_id=str(payload.get("modelId") or payload.get("model_id") or ""),
            dimensions=dimensions,
            api_key=str(payload.get("apiKey") or payload.get("api_key") or "").strip() or None,
            secret_env_var=str(payload.get("secretEnvVar") or payload.get("secret_env_var") or "").strip() or None,
        )
    }


def list_provider_keys(self) -> dict[str, Any]:
    keys: list[dict[str, Any]] = []
    profiles = sorted(
        self.repository.list_auth_profiles(),
        key=lambda profile: (profile.provider_id, profile.profile_id),
    )
    for profile in profiles:
        for reference in profile.secret_references:
            has_value = self.repository.has_auth_secret_value(reference.reference_id)
            keys.append(
                {
                    "referenceId": reference.reference_id,
                    "profileId": profile.profile_id,
                    "providerId": reference.provider_id,
                    "secretName": reference.secret_name,
                    "secretKey": reference.secret_key,
                    "source": reference.source,
                    "metadata": dict(reference.metadata),
                    "createdAt": None,
                    "hasValue": has_value,
                    "valueUpdatedAt": None,
                    "redactedValue": "***" if has_value else "",
                }
            )
    return {"keys": keys}


def upsert_provider_key(self, reference_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    value = str(payload.get("value") or "")
    if not value.strip():
        raise ValueError("value is required")
    reference = _load_secret_reference(self, reference_id)
    self.model_provider.store_secret_value(reference, value)
    return {"status": "ok", "referenceId": reference_id, "hasValue": True}


def create_provider_key(self, payload: Mapping[str, Any]) -> dict[str, Any]:
    profile_id = str(payload.get("profileId") or payload.get("profile_id") or "").strip()
    provider_id = str(payload.get("providerId") or payload.get("provider_id") or "").strip()
    secret_key = str(payload.get("secretKey") or payload.get("secret_key") or "api_key").strip()
    secret_name = str(payload.get("secretName") or payload.get("secret_name") or "api_token").strip()
    reference_id = str(payload.get("referenceId") or payload.get("reference_id") or f"secret:{profile_id}:{secret_key}").strip()
    if not profile_id or not provider_id or not reference_id:
        raise ValueError("profileId, providerId, and referenceId are required")
    profile = self.repository.load_auth_profile(profile_id)
    if profile is None:
        raise KeyError(profile_id)
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    reference = SecretReference(
        reference_id=reference_id,
        provider_id=provider_id,
        secret_name=secret_name,
        secret_key=secret_key,
        metadata={str(key): str(value) for key, value in dict(metadata).items()},
    )
    next_refs = tuple(ref for ref in profile.secret_references if ref.reference_id != reference_id) + (reference,)
    self.repository.upsert_auth_profile(replace(profile, secret_references=next_refs))
    raw_value = payload.get("value")
    if isinstance(raw_value, str) and raw_value.strip():
        self.model_provider.store_secret_value(reference, raw_value)
    return {"status": "ok", "referenceId": reference_id, "hasValue": bool(raw_value)}


def delete_provider_key(self, reference_id: str) -> dict[str, Any]:
    self.repository.delete_auth_secret_value(reference_id)
    return {"status": "ok", "referenceId": reference_id, "hasValue": False}


def _load_secret_reference(self, reference_id: str) -> SecretReference:
    for profile in self.repository.list_auth_profiles():
        for reference in profile.secret_references:
            if reference.reference_id == reference_id:
                return reference
    raise KeyError(reference_id)
