"""Package-owned model-provider orchestration for product surfaces."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
import logging
import os
import re
from pathlib import Path
import shutil
from typing import Any

from packages.auth import (
    AuthProfile,
    EncryptedRepositorySecretStore,
    LocalEncryptedSecretCipher,
    ProfileCredentialResolver,
    ProviderAuthState,
    SecretReference,
    SecretValueResolution,
)
from packages.capabilities.runtime import CapabilityDescriptor, ModelProviderCapability
from packages.contracts import Episode
from packages.contracts.runtime import (
    ContextBundle,
    ExecutionResult,
    GenerationModelProfile,
    RuntimeModelChoice,
    PersonalModelRuntimeState,
    PromptMessage,
    SupportModelProfile,
)
from packages.embeddings import OPENAI_COMPATIBLE_EMBED_PROFILE_ID, OPENAI_COMPATIBLE_EMBED_PROVIDER_ID
from packages.models.bootstrap import (
    EmbeddingBootstrapState,
    resolve_embedding_bootstrap_state,
    trigger_embedding_bootstrap,
)
from packages.models.discovery import (
    DiscoveredProviderModel,
    DiscoveredProviderState,
    ProviderMetadataDiscoveryService,
    ProviderStateEvaluator,
    heuristic_context_window,
    request_json,
)
from packages.models.provider_catalog import default_provider_definitions, provider_definition
from packages.models.prompt_sections import context_with_fallback_tool_prompt
from packages.models.provider_runtime import ProviderRuntimeResolver
from packages.models.providers import build_model_adapter
from packages.models.runtime_describe import embedding_bootstrap_summary_fields, invalid_provider_resolution_summary
from packages.storage import RuntimeStorageRepository
from packages.tools import ToolDefinition, ToolRuntime, build_tool_fallback_prompt

from .ephemeral_injection import TurnScopedPrefixCache, ephemeral_blocks_as_user_suffix, recall_block_contents, strip_recall_blocks
from .runtime import ModelRequest

LOGGER = logging.getLogger(__name__)

RequestJsonCallable = Callable[..., dict[str, Any]]

# Signature every per-turn context block builder must satisfy.
# Returns a support block (str) or "" to no-op. Runs once per kernel turn
# (result is cached by `TurnScopedPrefixCache` across all `generate()` calls
# that share the same user message). Must not mutate `messages`.
EphemeralPrefixBuilder = Callable[
    [PersonalModelRuntimeState, Episode, ContextBundle, str, str],
    str,
]

_RECALL_CONTEXT_MARKER = "Current-turn recall support:"
_MAX_SESSION_RECALL_BYTES = 60 * 1024
_MIN_RECALL_QUERY_CHARS = 4
_MIN_RECALL_QUERY_WORDS = 2
_RECALL_WORD_RE = re.compile(r"[A-Za-z0-9_./:-]+")
_RECALL_CJK_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")


def _hot_recall_query_allowed(query: str) -> bool:
    normalized = " ".join(str(query or "").split()).strip()
    if len(normalized) < _MIN_RECALL_QUERY_CHARS:
        return False
    words = _RECALL_WORD_RE.findall(normalized)
    cjk_chars = _RECALL_CJK_RE.findall(normalized)
    if len(words) < _MIN_RECALL_QUERY_WORDS and len(cjk_chars) < _MIN_RECALL_QUERY_CHARS:
        return False
    return True


def _recall_message_contents(message: PromptMessage) -> tuple[str, ...]:
    content = str(message.content or "").strip()
    if not content:
        return ()
    if str(message.metadata.get("elephant_context") or "").strip() == "recall":
        return (content,)
    if content.startswith(_RECALL_CONTEXT_MARKER):
        return (content,)
    return recall_block_contents(content)


def _surfaced_recall_stats(messages: tuple[PromptMessage, ...]) -> tuple[int, frozenset[str]]:
    contents = tuple(content for message in messages for content in _recall_message_contents(message))
    return sum(len(content.encode("utf-8")) for content in contents), frozenset(contents)


def _normalize_base_url(base_url: str | None) -> str:
    return str(base_url or "").strip().rstrip("/")


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


def generation_model_profile_from_auth_profile(profile: AuthProfile) -> GenerationModelProfile:
    if not str(profile.default_model or "").strip():
        raise ValueError(f"auth profile '{profile.profile_id}' is missing a generation model id")
    return GenerationModelProfile(
        profile_id=profile.profile_id,
        provider_id=profile.provider_id,
        model_id=str(profile.default_model),
        base_url=profile.base_url,
        transport_id=profile.transport_id,
        reasoning_effort=str(profile.metadata.get("reasoning_effort", "")).strip() or None,
        metadata=dict(profile.metadata),
    )


def support_model_profile_from_auth_profile(profile: AuthProfile) -> SupportModelProfile:
    if not str(profile.default_model or "").strip():
        raise ValueError(f"auth profile '{profile.profile_id}' is missing a support model id")
    return SupportModelProfile(
        profile_id=profile.profile_id,
        provider_id=profile.provider_id,
        model_id=str(profile.default_model),
        base_url=profile.base_url,
        transport_id=profile.transport_id,
        reasoning_effort=str(profile.metadata.get("reasoning_effort", "")).strip() or None,
        metadata=dict(profile.metadata),
    )


def runtime_selection_from_auth_profile(profile: AuthProfile) -> RuntimeModelChoice:
    return RuntimeModelChoice(
        strong_model=generation_model_profile_from_auth_profile(profile),
        weak_model=support_model_profile_from_auth_profile(profile),
        state_focus_mode="skip",
    )


def provider_profile_summary(profile: AuthProfile) -> dict[str, Any]:
    context_window_tokens = _coerce_reasonable_int(profile.metadata.get("context_window_tokens"))
    return {
        "profile_id": profile.profile_id,
        "provider_id": profile.provider_id,
        "transport_id": profile.transport_id,
        "base_url": profile.base_url,
        "default_model": profile.default_model,
        "auth_method": profile.auth_method,
        "provider_kind": profile.provider_kind,
        "extra_headers": dict(profile.extra_headers),
        "secret_reference_ids": tuple(reference.reference_id for reference in profile.secret_references),
        "context_window_tokens": context_window_tokens,
        "context_window_mode": str(profile.metadata.get("context_window_mode", "auto")),
        "reasoning_effort": str(profile.metadata.get("reasoning_effort", "")).strip() or None,
        "source": "configured",
    }


def provider_fallback_summary() -> dict[str, Any]:
    return {
        "profile_id": "",
        "provider_id": "preview",
        "transport_id": "preview",
        "base_url": None,
        "default_model": None,
        "auth_method": "preview",
        "provider_kind": "preview",
        "extra_headers": {},
        "secret_reference_ids": (),
        "context_window_tokens": None,
        "context_window_mode": "unset",
        "reasoning_effort": None,
        "source": "preview-fallback",
    }


class SurfaceModelProviderCapability(ModelProviderCapability):
    def __init__(
        self,
        *,
        repository: RuntimeStorageRepository,
        fallback: ModelProviderCapability,
        secret_key_path: Path,
        credential_resolver: ProfileCredentialResolver | None = None,
        tool_runtime: ToolRuntime | None = None,
        active_provider_profile_id: str | None = None,
        active_provider_id: str | None = None,
        capability_id: str = "surface.model.runtime",
        surface_label: str = "surface",
        bootstrap_state_dir: Path | None = None,
        ephemeral_prefix_builders: "tuple[EphemeralPrefixBuilder, ...]" = (),
    ) -> None:
        self.repository = repository
        self.fallback = fallback
        self.secret_cipher = LocalEncryptedSecretCipher.from_path(secret_key_path)
        self.credential_resolver = credential_resolver or ProfileCredentialResolver(
            EncryptedRepositorySecretStore(
                repository,
                cipher=self.secret_cipher,
            )
        )
        self.tool_runtime = tool_runtime
        self.active_provider_profile_id = active_provider_profile_id
        self.active_provider_id = active_provider_id
        # Per-turn context block builders. Each is a callable
        # `(profile, session, context, prompt, query) -> str` that returns a
        # current-turn support section or "" to opt
        # out. Builders run ONCE per kernel turn — the rendered blocks are
        # cached by `_ephemeral_prefix_cache` keyed on
        # (episode_id, last_user_message_content). Tool-loop follow-ups and
        # overflow retries inside the same user turn reuse the cached
        # result and never re-trigger memory providers with a stale query.
        # See `packages/models/ephemeral_injection.py`.
        self.ephemeral_prefix_builders: tuple[EphemeralPrefixBuilder, ...] = tuple(
            ephemeral_prefix_builders
        )
        self._ephemeral_prefix_cache = TurnScopedPrefixCache()
        self.state_focus_mode = "skip"
        self.bootstrap_state_dir = bootstrap_state_dir or repository.database_path.parent
        self.runtime_resolver = ProviderRuntimeResolver.default()
        self.metadata_discovery = ProviderMetadataDiscoveryService(
            runtime_resolver=self.runtime_resolver,
            requester=lambda **kwargs: request_json(**kwargs),
        )
        self.state_evaluator = ProviderStateEvaluator(runtime_resolver=self.runtime_resolver)
        self._stream_observer = None
        self.descriptor = CapabilityDescriptor(
            capability_id=capability_id,
            kind="model_provider",
            version="1.0.0",
            metadata={
                "description": f"{surface_label} model provider runtime wired to persisted provider profiles.",
            },
        )
        if self.active_provider_profile_id is not None or self.active_provider_id is not None:
            self.ensure_embedding_bootstrap_state()

    def set_active_profile(
        self,
        *,
        provider_profile_id: str | None,
        provider_id: str | None,
    ) -> None:
        self.active_provider_profile_id = provider_profile_id
        self.active_provider_id = provider_id
        self.ensure_embedding_bootstrap_state()

    def _load_profile(self, profile_id: str | None) -> AuthProfile | None:
        if profile_id is None:
            return None
        return self.repository.load_auth_profile(profile_id)

    def active_profile(self) -> AuthProfile | None:
        if self.active_provider_profile_id is not None:
            profile = self._load_profile(self.active_provider_profile_id)
            if profile is not None:
                return profile
        if self.active_provider_id is not None:
            try:
                return self.repository.select_auth_profile(self.active_provider_id)
            except LookupError:
                return None
        return None

    def _profile_for_role(self, model_role: str) -> AuthProfile:
        normalized_role = model_role.strip().lower()
        if normalized_role in {"strong", "weak"}:
            profile = self.active_profile()
            if profile is None:
                raise LookupError("no active provider profile is configured")
            return profile
        raise ValueError(f"unsupported model_role: {model_role}")

    def selection_state(self) -> RuntimeModelChoice:
        try:
            active_profile = self._profile_for_role("strong")
        except LookupError:
            return self.fallback.selection_state()
        return runtime_selection_from_auth_profile(active_profile)

    def turn_scoped_recall_blocks(
        self,
        *,
        profile: PersonalModelRuntimeState,
        session: Episode,
        context: ContextBundle,
        prompt: str,
    ) -> tuple[str, ...]:
        """Return current-turn recall blocks for the active user message suffix."""

        query = strip_recall_blocks(prompt).strip()
        if not self.ephemeral_prefix_builders or not _hot_recall_query_allowed(query):
            return ()
        surfaced_bytes, surfaced_contents = _surfaced_recall_stats(tuple(context.prompt_envelope.messages))
        if surfaced_bytes >= _MAX_SESSION_RECALL_BYTES:
            return ()
        blocks = self._ephemeral_prefix_cache.resolve(
            builders=self.ephemeral_prefix_builders,
            profile=profile,
            session=session,
            context=context,
            prompt=prompt,
            query=query,
        )
        suffix = ephemeral_blocks_as_user_suffix(blocks=blocks)
        if not suffix or suffix in surfaced_contents:
            return ()
        if surfaced_bytes + len(suffix.encode("utf-8")) > _MAX_SESSION_RECALL_BYTES:
            return ()
        return (suffix,)

    def resolve_credentials(self, provider_profile: AuthProfile) -> Mapping[str, str]:
        return self.credential_resolver.resolve(provider_profile).as_mapping()

    def resolve_discovered_credentials(self, provider_id: str) -> Mapping[str, str]:
        resolution = self._discovered_secret_resolution(provider_id)
        if resolution is None:
            return {}
        return {"api_key": resolution.value}

    def has_stored_secret(self, reference_id: str) -> bool:
        return self.repository.has_auth_secret_value(reference_id)

    def store_secret_value(self, reference: SecretReference, value: str) -> None:
        encrypted = self.secret_cipher.encrypt(
            reference_id=reference.reference_id,
            value=value,
        )
        self.repository.upsert_auth_secret_value(encrypted)

    def set_stream_observer(self, observer) -> None:
        self._stream_observer = observer

    def _stream_observer_for_request(
        self,
        *,
        request: ModelRequest,
        model_role: str,
    ):
        observer = self._stream_observer
        if not callable(observer):
            return None
        metadata = {
            "session_id": request.session_id,
            "request_id": request.request_id,
            "provider_id": request.provider_id,
            "model_id": request.model_id,
            "model_role": model_role,
        }

        def scoped_stream_observer(delta: str) -> None:
            try:
                observer(delta, **metadata)
            except TypeError:
                observer(delta)

        return scoped_stream_observer

    def _resolved_extra_headers_for(
        self,
        *,
        provider_id: str,
        active_profile: AuthProfile | None = None,
    ) -> Mapping[str, str]:
        if active_profile is not None and active_profile.provider_id == provider_id:
            if active_profile.extra_headers:
                return dict(active_profile.extra_headers)
        definition = provider_definition(provider_id)
        if definition is None:
            return {}
        return dict(definition.extra_headers)

    def _resolved_metadata_base_url(
        self,
        *,
        provider_id: str,
        base_url: str | None,
        active_profile: AuthProfile | None = None,
    ) -> str | None:
        normalized = _normalize_base_url(base_url)
        if normalized:
            return normalized
        if active_profile is not None and active_profile.provider_id == provider_id:
            normalized = _normalize_base_url(active_profile.base_url)
            if normalized:
                return normalized
        try:
            configured_profile = self.repository.select_auth_profile(provider_id)
        except LookupError:
            configured_profile = None
        if configured_profile is not None and configured_profile != active_profile:
            normalized = _normalize_base_url(configured_profile.base_url)
            if normalized:
                return normalized
        definition = provider_definition(provider_id)
        if definition is None:
            return None
        return _provider_base_url_from_env(provider_id, definition.base_url_env_var) or definition.default_base_url

    def _resolved_metadata_api_key(
        self,
        *,
        provider_id: str,
        explicit_api_key: str | None,
        active_profile: AuthProfile | None = None,
    ) -> str | None:
        if explicit_api_key:
            return explicit_api_key
        if active_profile is not None and active_profile.provider_id == provider_id:
            try:
                bundle = self.credential_resolver.resolve(active_profile)
            except LookupError:
                bundle = None
            if bundle is not None:
                resolved = str(bundle.values.get("api_key", "")).strip()
                if resolved:
                    return resolved
        try:
            configured_profile = self.repository.select_auth_profile(provider_id)
        except LookupError:
            configured_profile = None
        if configured_profile is not None and configured_profile != active_profile:
            try:
                bundle = self.credential_resolver.resolve(configured_profile)
            except LookupError:
                bundle = None
            if bundle is not None:
                resolved = str(bundle.values.get("api_key", "")).strip()
                if resolved:
                    return resolved
        discovered = self._discovered_secret_resolution(provider_id)
        if discovered is not None:
            resolved = str(discovered.value).strip()
            if resolved:
                return resolved
        return None

    def _hinted_models(self, provider_id: str) -> tuple[DiscoveredProviderModel, ...]:
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
                reasoning_efforts = self.runtime_resolver.resolve(
                    provider_id,
                    model_id=normalized,
                    base_url=definition.default_base_url,
                ).reasoning_efforts
            except Exception:
                LOGGER.warning(
                    "failed to resolve discovered model reasoning efforts",
                    extra={"provider_id": provider_id, "model_id": normalized},
                    exc_info=True,
                )
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
        self,
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

    def _profile_secret_status(self, profile: AuthProfile) -> tuple[str, str]:
        if not profile.secret_references:
            return ("not-required", "not-required")
        try:
            bundle = self.credential_resolver.resolve(profile)
        except LookupError:
            return ("missing", "missing")
        sources = tuple(dict.fromkeys(bundle.value_sources.values()))
        source_summary = ", ".join(source for source in sources if source) or "encrypted-local-store"
        return ("stored", source_summary)

    def _local_embedding_default_active(self) -> bool:
        profile = self.repository.load_auth_profile(OPENAI_COMPATIBLE_EMBED_PROFILE_ID)
        if profile is None or profile.provider_id != OPENAI_COMPATIBLE_EMBED_PROVIDER_ID:
            return True
        return str(profile.metadata.get("embedding_active") or "").strip().lower() != "true"

    def _embedding_bootstrap_state_focus_mode(self) -> str:
        if not self._local_embedding_default_active():
            return "skip"
        if self.active_provider_profile_id is None and self.active_provider_id is None:
            return "skip"
        return "embedded"

    def ensure_embedding_bootstrap_state(
        self,
        *,
        source: str | None = None,
        force_download: bool = False,
    ) -> EmbeddingBootstrapState:
        self.state_focus_mode = self._embedding_bootstrap_state_focus_mode()
        return trigger_embedding_bootstrap(
            self.bootstrap_state_dir,
            state_focus_mode=self.state_focus_mode,
            source=source,
            force_download=force_download,
        )

    def _embedding_bootstrap_state(self) -> EmbeddingBootstrapState:
        self.state_focus_mode = self._embedding_bootstrap_state_focus_mode()
        return resolve_embedding_bootstrap_state(
            self.bootstrap_state_dir,
            state_focus_mode=self.state_focus_mode,
        )

    def describe(self) -> Mapping[str, object]:
        embedding_bootstrap = self._embedding_bootstrap_state()
        profile = self.active_profile()
        if profile is None:
            summary = provider_fallback_summary()
            summary["model_id"] = summary.get("default_model")
            summary.update(embedding_bootstrap_summary_fields(embedding_bootstrap))
            return summary
        summary = provider_profile_summary(profile)
        try:
            resolution = self.runtime_resolver.resolve(
                profile.provider_id,
                model_id=profile.default_model,
                base_url=profile.base_url,
            )
        except LookupError as error:
            summary.update(invalid_provider_resolution_summary(profile, error))
            summary.update(embedding_bootstrap_summary_fields(embedding_bootstrap))
            return summary
        summary.update(
            {
                "display_name": resolution.display_name,
                "transport_display_name": resolution.transport_display_name,
                "supports_streaming": resolution.supports_streaming,
                "supports_reasoning": resolution.supports_reasoning,
                "reasoning_efforts": resolution.reasoning_efforts,
                "auth_type": str(resolution.provider_metadata.get("auth_type", profile.auth_method)),
                "secret_status": self._profile_secret_status(profile)[0],
                "secret_source": self._profile_secret_status(profile)[1],
                "model_id": profile.default_model,
                **embedding_bootstrap_summary_fields(embedding_bootstrap),
            }
        )
        return summary

    def discover_models(
        self,
        *,
        provider_id: str,
        base_url: str | None,
        api_key: str | None = None,
    ) -> tuple[DiscoveredProviderModel, ...]:
        active_profile = self.active_profile()
        resolved_base_url = self._resolved_metadata_base_url(
            provider_id=provider_id,
            base_url=base_url,
            active_profile=active_profile,
        )
        resolved_api_key = self._resolved_metadata_api_key(
            provider_id=provider_id,
            explicit_api_key=api_key,
            active_profile=active_profile,
        )
        return self.metadata_discovery.discover_models(
            provider_id=provider_id,
            base_url=resolved_base_url,
            api_key=resolved_api_key,
            extra_headers=self._resolved_extra_headers_for(
                provider_id=provider_id,
                active_profile=active_profile,
            ),
            default_model_id=self._default_model_for(provider_id),
        )

    def detect_context_window(
        self,
        *,
        provider_id: str,
        base_url: str | None,
        model_id: str,
        api_key: str | None = None,
    ) -> int | None:
        active_profile = self.active_profile()
        resolved_base_url = self._resolved_metadata_base_url(
            provider_id=provider_id,
            base_url=base_url,
            active_profile=active_profile,
        )
        resolved_api_key = self._resolved_metadata_api_key(
            provider_id=provider_id,
            explicit_api_key=api_key,
            active_profile=active_profile,
        )
        resolved_extra_headers = self._resolved_extra_headers_for(
            provider_id=provider_id,
            active_profile=active_profile,
        )
        models = self.discover_models(
            provider_id=provider_id,
            base_url=base_url,
            api_key=api_key,
        )
        return self.metadata_discovery.detect_context_window(
            provider_id=provider_id,
            base_url=resolved_base_url,
            model_id=model_id,
            api_key=resolved_api_key,
            extra_headers=resolved_extra_headers,
            hinted_models=models,
        )

    def reasoning_efforts(
        self,
        *,
        provider_id: str,
        model_id: str,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> tuple[str, ...]:
        active_profile = self.active_profile()
        resolved_base_url = self._resolved_metadata_base_url(
            provider_id=provider_id,
            base_url=base_url,
            active_profile=active_profile,
        )
        resolved_api_key = self._resolved_metadata_api_key(
            provider_id=provider_id,
            explicit_api_key=api_key,
            active_profile=active_profile,
        )
        return self.metadata_discovery.reasoning_efforts(
            provider_id=provider_id,
            model_id=model_id,
            base_url=resolved_base_url,
            api_key=resolved_api_key,
            extra_headers=self._resolved_extra_headers_for(
                provider_id=provider_id,
                active_profile=active_profile,
            ),
        )

    def discover_provider_states(self) -> tuple[DiscoveredProviderState, ...]:
        states: list[DiscoveredProviderState] = []
        for definition in default_provider_definitions(include_discovery_only=True):
            state = self._discover_provider_state(definition.provider_id)
            self.repository.upsert_provider_auth_state(
                ProviderAuthState(
                    provider_id=state.provider_id,
                    auth_type=state.auth_type,
                    status=state.status,
                    source=state.source,
                    profile_id=state.profile_id,
                    transport_id=state.metadata.get("transport_id") or None,
                    provider_kind=state.provider_kind,
                    base_url=state.base_url,
                    default_model=state.default_model,
                    runtime_enabled=state.runtime_enabled,
                    summary=state.metadata.get("summary", ""),
                    metadata=dict(state.metadata),
                    discovered_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
            states.append(state)
        return tuple(states)

    def discovered_provider_state(self, provider_id: str) -> DiscoveredProviderState:
        return self._discover_provider_state(provider_id)

    def _discover_provider_state(self, provider_id: str) -> DiscoveredProviderState:
        definition = provider_definition(provider_id)
        if definition is None:
            raise LookupError(f"unknown provider definition: {provider_id}")
        try:
            profile = self.repository.select_auth_profile(provider_id)
        except LookupError:
            profile = None
        active_profile = self.active_profile()
        selected_profile = profile if profile is not None else (
            active_profile if active_profile and active_profile.provider_id == provider_id else None
        )
        base_url = (
            (selected_profile.base_url if selected_profile is not None else None)
            or _provider_base_url_from_env(definition.provider_id, definition.base_url_env_var)
            or definition.default_base_url
        )
        default_model = (
            (selected_profile.default_model if selected_profile is not None else None)
            or definition.default_model_id
        )
        secret_status = None
        secret_source = None
        if selected_profile is not None:
            secret_status, secret_source = self._profile_secret_status(selected_profile)
        discovered_secret = None if selected_profile is not None else self._discovered_secret_resolution(provider_id)
        external_process_status = _copilot_acp_status() if provider_id == "copilot-acp" else None
        local_provider_reachable = (
            definition.provider_kind == "local"
            and self._local_provider_reachable(provider_id, base_url)
        )
        return self.state_evaluator.evaluate(
            provider_id,
            selected_profile=selected_profile,
            discovered_secret=discovered_secret,
            base_url=base_url,
            default_model=default_model,
            secret_status=secret_status,
            secret_source=secret_source,
            local_provider_reachable=local_provider_reachable,
            external_process_status=external_process_status,
        )

    def _discovered_secret_resolution(self, provider_id: str) -> SecretValueResolution | None:
        definition = provider_definition(provider_id)
        if definition is None or not definition.required_secret_keys:
            return None
        reference_metadata: dict[str, str] = {}
        if definition.env_var_names:
            reference_metadata["env_var"] = definition.env_var_names[0]
        synthetic_reference = SecretReference(
            reference_id=f"discovery:{provider_id}:api_key",
            provider_id=provider_id,
            secret_name="api_token",
            secret_key="api_key",
            source="discovery",
            metadata=reference_metadata,
        )
        try:
            return self.credential_resolver.secret_store.resolve(synthetic_reference)
        except LookupError:
            return None

    def _local_provider_reachable(self, provider_id: str, base_url: str | None) -> bool:
        active_profile = self.active_profile()
        resolved_base_url = self._resolved_metadata_base_url(
            provider_id=provider_id,
            base_url=base_url,
            active_profile=active_profile,
        )
        resolved_api_key = self._resolved_metadata_api_key(
            provider_id=provider_id,
            explicit_api_key=None,
            active_profile=active_profile,
        )
        return self.metadata_discovery.local_provider_reachable(
            provider_id=provider_id,
            base_url=resolved_base_url,
            api_key=resolved_api_key,
            extra_headers=self._resolved_extra_headers_for(
                provider_id=provider_id,
                active_profile=active_profile,
            ),
        )

    def _default_model_for(self, provider_id: str) -> str | None:
        try:
            guide = self.runtime_resolver.build_setup_guide(provider_id)
        except LookupError:
            return None
        return guide.suggested_model_id

    def _model_visible_tools(self) -> tuple[ToolDefinition, ...]:
        if self.tool_runtime is None:
            return ()
        return self.tool_runtime.list_tools(
            audience="model",
            enabled_only=True,
            available_only=True,
        )

    def _fallback_tool_prompt(self, tools: tuple[ToolDefinition, ...]) -> str:
        prompt = build_tool_fallback_prompt(tools)
        if not prompt:
            return ""
        return (
            "## available runtime tools\n"
            "Native provider tool calling is unavailable on this transport. "
            "Use the governed built-in tool surface through fallback markup when tool work is necessary.\n"
            f"{prompt}"
        )

    def generate(
        self,
        *,
        profile: PersonalModelRuntimeState,
        session: Episode,
        context: ContextBundle,
        prompt: str,
        model_role: str = "strong",
    ) -> ExecutionResult:
        try:
            active_profile = self._profile_for_role(model_role)
        except LookupError:
            return self.fallback.generate(
                profile=profile,
                session=session,
                context=context,
                prompt=prompt,
                model_role=model_role,
            )
        resolution = self.runtime_resolver.resolve(
            active_profile.provider_id,
            model_id=active_profile.default_model or None,
            base_url=active_profile.base_url,
        )
        visible_tools = self._model_visible_tools()
        if visible_tools and not resolution.supports_tools:
            context = context_with_fallback_tool_prompt(
                context,
                self._fallback_tool_prompt(visible_tools),
            )
        request_tools = (
            tuple(tool.model_function_schema() for tool in visible_tools)
            if resolution.supports_tools
            else ()
        )
        api_messages = tuple(context.prompt_envelope.messages)
        request = ModelRequest(
            request_id=f"{session.episode_id}:model:{model_role}",
            profile_id=profile.profile_id,
            session_id=session.episode_id,
            provider_id=active_profile.provider_id,
            model_id=active_profile.default_model or "",
            prompt=prompt,
            context={
                "bundle_id": context.bundle_id,
                "token_budget": str(context.token_budget),
                "instruction_refs": ",".join(context.instruction_refs),
                "work_item_ids": ",".join(context.work_item_ids),
                "evidence_refs": ",".join(context.evidence_refs),
                "artifact_ids": ",".join(context.artifact_ids),
                "frozen_prefix_prompt": context.prompt_envelope.frozen_prefix,
                "session_snapshot_prompt": context.prompt_envelope.session_snapshot,
                "rendered_prompt": context.rendered_prompt or "",
            },
            reasoning_effort=str(active_profile.metadata.get("reasoning_effort", "")).strip() or None,
            metadata={
                "profile_mode": profile.mode,
                "session_status": session.status,
                "provider_profile_id": active_profile.profile_id,
            },
            tools=request_tools,
            messages=api_messages,
        )

        credentials = self.credential_resolver.resolve(active_profile).as_mapping()
        adapter = build_model_adapter(
            active_profile,
            runtime_resolver=self.runtime_resolver,
            credentials=credentials,
            adapter_id=f"adapter.models.{active_profile.provider_id}.surface",
            stream_observer=self._stream_observer_for_request(request=request, model_role=model_role),
        )
        if adapter is None:
            return self.fallback.generate(
                profile=profile,
                session=session,
                context=context,
                prompt=prompt,
            )
        result = adapter.generate(request, credentials)
        return ExecutionResult(
            execution_id=result.result_id,
            episode_id=session.episode_id,
            outcome="ok" if result.failure_kind is None else "failed",
            summary=result.content,
            reasoning=result.reasoning,
            prompt_tokens=result.usage.prompt_tokens,
            completion_tokens=result.usage.completion_tokens,
            total_tokens=result.usage.total_tokens,
            cached_prompt_tokens=result.usage.cached_prompt_tokens,
            cache_creation_prompt_tokens=result.usage.cache_creation_prompt_tokens,
            cache_usage_reported=result.usage.cache_usage_reported,
            telemetry_event_ids=(request.request_id,),
            side_effects=(
                f"provider={result.provider_id}",
                f"model={result.model_id}",
                f"model_role={model_role}",
                f"transport={result.metadata.get('transport_id', 'unknown')}",
                f"credential_keys={result.metadata.get('credential_keys', 'unknown')}",
            ),
            tool_calls=result.tool_calls,
        )

__all__ = [
    "SurfaceModelProviderCapability",
    "runtime_selection_from_auth_profile",
    "provider_fallback_summary",
    "provider_profile_summary",
    "generation_model_profile_from_auth_profile",
    "support_model_profile_from_auth_profile",
]
