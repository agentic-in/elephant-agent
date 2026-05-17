"""Gateway runtime adapter registration and app factory."""


from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any
from uuid import uuid4

from apps.provider_runtime import (
    load_provider_profile,
    provider_profile_from_payload,
)
from apps.runtime_layout import default_cli_state_dir
from packages.cron import CronRuntime
from packages.runtime_config import configured_external_skill_dirs, global_config_path_for_state_dir, load_extensions_from_config, load_global_config
from packages.runtime_layout import default_cron_dir, elephant_file_path, infer_install_root_from_state_dir
from packages.auth import (
    AuthProfile,
    EncryptedRepositorySecretStore,
    EnvironmentSecretStore,
    LocalEncryptedSecretCipher,
    PersistentAuthProfileStore,
    ProfileCredentialResolver,
    SecretReference,
    SecretStore,
    SecretValueResolution,
)
from packages.capabilities.runtime import (
    CapabilityDescriptor,
    ContextCapability,
    RecallCapability,
    ModelProviderCapability,
    TelemetrySinkCapability,
)
from packages.context import ContextRuntime
from packages.context.epoch_store import FileEpochStore
from packages.contracts.runtime import (
    ContextBundle,
    EventEnvelope,
    ExecutionResult,
    RecallEvidence,
    PersonalModelRuntimeState,
)
from packages.gateway_core import (
    DEFAULT_GATEWAY_ACCOUNT_ID,
    FileGatewayIdentityStore,
    FileGatewaySessionStore,
    GatewayAccountRef,
    GatewayAttachmentRef,
    GatewayConversationRef,
    GatewayCoreDependencies,
    GatewayCoreService,
    GatewayExchange,
    GatewayIdentityRecord,
    GatewayInboundMessage,
    GatewayMessageDeliverySurface,
    GatewayOutboundMessage,
    GatewayOutboundQueue,
    GatewayPolicyHint,
    GatewaySenderRef,
    InMemoryGatewayIdentityStore,
    InMemoryGatewaySessionStore,
    default_outbound_queue_path,
)
from packages.kernel import KernelDependencies, KernelService, KernelSourceRequest, ReconciliationPipeline, StateReconciler
from packages.evidence import RecallRuntime, SemanticSummaryIndexer, build_semantic_index_bundle
from packages.skills import (
    RuntimeSkillManagementSurface,
    SkillHub,
    SkillPromptContextBuilder,
    SkillSearchHub,
    build_surface_skill_runtime,
    default_skill_hub_sources,
    load_skill_extension_manifest,
    sync_builtin_skill_shelf,
)
from packages.state import DEFAULT_ELEPHANT_IDENTITY_TEXT, LoadedProfile, ProfileLoader, build_prompt_contract
from packages.security.runtime import SecurityPolicy
from packages.storage import RuntimeStorageRepository
from packages.tools import (
    BuiltinToolDependencies,
    RequesterScopedToolCapability,
    ToolRequester,
    ToolRuntimeContext,
    build_tool_runtime,
    sync_custom_mcp_tools,
)
from packages.tools.adapters import StructuredClarifySurface
from packages.understanding import PersonalModelUnderstandingSurface
from packages.tools.browser_backend import create_playwright_browser_backend
from .platforms import BUILTIN_GATEWAY_PLATFORMS
from .plugins import GatewayPluginRegistry
from .runtime_adapters import ChatBotMessagingAdapter, WebhookMessagingAdapter
from .runtime_app import GatewayApp
from .runtime_capabilities import (
    GatewayContextCapability,
    GatewayRecallCapability,
    GatewayPreviewModelProvider,
    GatewaySurfaceModelProvider,
    GatewayTelemetrySink,
)
from .runtime_support import *  # noqa: F401,F403

def register_builtin_gateway_adapters(registry: GatewayPluginRegistry) -> GatewayPluginRegistry:
    for platform in BUILTIN_GATEWAY_PLATFORMS:
        registry.register_platform(platform)
    return registry

def _builtin_gateway_plugin_registry() -> GatewayPluginRegistry:
    registry = GatewayPluginRegistry()
    return register_builtin_gateway_adapters(registry)


class _GatewayFallbackSecretStore:
    def __init__(self, stores: tuple[SecretStore, ...]) -> None:
        self.stores = stores

    def resolve(self, reference: SecretReference) -> SecretValueResolution:
        errors: list[str] = []
        for store in self.stores:
            try:
                return store.resolve(reference)
            except LookupError as exc:
                errors.append(str(exc))
        detail = "; ".join(errors) or reference.reference_id
        raise LookupError(f"missing gateway provider secret for {reference.reference_id}: {detail}")

    def read(self, reference: SecretReference) -> str:
        return self.resolve(reference).value


def _candidate_cli_state_dirs(
    resolved_state_dir: Path | None,
    resolved_control_state_dir: Path | None = None,
) -> tuple[Path, ...]:
    candidates: list[Path] = []
    if resolved_control_state_dir is not None:
        candidates.append(resolved_control_state_dir)
    if resolved_state_dir is not None:
        candidates.append(resolved_state_dir)
    candidates.append(default_cli_state_dir())
    unique: list[Path] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return tuple(unique)


def _gateway_provider_credential_resolver(
    *,
    runtime_repository: RuntimeStorageRepository,
    resolved_state_dir: Path | None,
    resolved_control_state_dir: Path | None = None,
    runtime_environ: Mapping[str, str] | None = None,
) -> ProfileCredentialResolver:
    stores: list[SecretStore] = [
        EncryptedRepositorySecretStore(
            runtime_repository,
            cipher=LocalEncryptedSecretCipher.from_path(
                runtime_repository.database_path.parent / "provider-secrets.key"
            ),
            environ=runtime_environ,
        )
    ]
    for state_dir in _candidate_cli_state_dirs(resolved_state_dir, resolved_control_state_dir):
        database_path = state_dir / "elephant.sqlite3"
        secret_key_path = state_dir / "provider-secrets.key"
        if not database_path.exists() or not secret_key_path.exists():
            continue
        if database_path == runtime_repository.database_path:
            continue
        stores.append(
            EncryptedRepositorySecretStore(
                RuntimeStorageRepository(database_path),
                cipher=LocalEncryptedSecretCipher.from_path(secret_key_path),
                environ=runtime_environ,
            )
        )
    if runtime_environ is not None:
        stores.append(EnvironmentSecretStore(runtime_environ))
    return ProfileCredentialResolver(_GatewayFallbackSecretStore(tuple(stores)))

def build_gateway_app(
    *,
    profile_id: str = "you",
    provider_profile: Mapping[str, Any] | None = None,
    state_dir: str | Path | None = None,
    control_state_dir: str | Path | None = None,
    runtime_environ: Mapping[str, str] | None = None,
    plugin_registry: GatewayPluginRegistry | None = None,
) -> tuple[GatewayApp, ChatBotMessagingAdapter, WebhookMessagingAdapter]:
    registry = plugin_registry or _builtin_gateway_plugin_registry()
    ephemeral_home: Path | None = None
    if state_dir is None:
        ephemeral_home = Path(tempfile.mkdtemp(prefix="elephant-gateway-home-"))
    resolved_state_dir = Path(state_dir) if state_dir is not None else None

    if resolved_state_dir is not None:
        from packages.runtime_config import load_global_config, global_config_path_for_state_dir
        _gw_cfg = load_global_config(global_config_path_for_state_dir(resolved_state_dir), state_dir=resolved_state_dir)
        from packages.observability import setup_from_config
        setup_from_config(_gw_cfg, state_dir=str(resolved_state_dir))

    # The extension-manifest loader surfaces skill / tool overrides (profile.json
    # on disk). Identity does NOT flow through it — it flows from the DB.
    if resolved_state_dir is not None:
        bundle_root = infer_install_root_from_state_dir(resolved_state_dir)
    else:
        bundle_root = ephemeral_home
    profile_loader: ProfileLoader = ProfileLoader(bundle_root)
    loaded_profile: LoadedProfile = profile_loader.load()
    # Normalize profile_id: single-user mode keeps the canonical
    # DEFAULT_PERSONAL_MODEL_ID ("you") regardless of caller arg.
    profile_id = loaded_profile.state.profile_id

    if resolved_state_dir is None:
        identity_store = InMemoryGatewayIdentityStore()
        session_store = InMemoryGatewaySessionStore()
    else:
        identity_store = FileGatewayIdentityStore(
            resolved_state_dir / "gateway-identities.json"
        )
        session_store = FileGatewaySessionStore(
            resolved_state_dir / "gateway-sessions.json"
        )

    telemetry = GatewayTelemetrySink()
    core = GatewayCoreService(
        GatewayCoreDependencies(
            identity_store=identity_store,
            session_store=session_store,
            security_policy=SecurityPolicy.default(),
            default_profile_id=profile_id,
            telemetry_sink=telemetry,
        )
    )
    runtime_repository = RuntimeStorageRepository(_runtime_database_path(resolved_state_dir))
    try:
        runtime_repository.bootstrap()
    except RuntimeError as exc:
        # Fail fast with a crisp, diagnosable message. Most common cause: a
        # stale gateway process from before a schema migration is still
        # running against a DB that newer code already migrated forward.
        message = (
            f"Gateway storage bootstrap failed: {exc}. "
            f"Database: {runtime_repository.database_path}. "
            f"This usually means an older gateway process is still running "
            f"against a database that has since been migrated — stop all "
            f"`apps.gateway` / `apps.launcher gateway` processes and retry."
        )
        print(message, file=sys.stderr, flush=True)
        raise SystemExit(message) from exc
    runtime_repository.upsert_personal_model_runtime_state(loaded_profile.state)
    auth_store = PersistentAuthProfileStore(runtime_repository)
    runtime_state_dir = runtime_repository.database_path.parent
    install_root = (
        ephemeral_home
        if ephemeral_home is not None
        else infer_install_root_from_state_dir(runtime_state_dir)
    )
    profile_loader = profile_loader or ProfileLoader(install_root)
    sync_builtin_skill_shelf(destination_root=install_root / "skills" / "builtin")
    resolved_control_state_dir = Path(control_state_dir) if control_state_dir is not None else None
    runtime_config_state_dir = resolved_control_state_dir or resolved_state_dir or runtime_state_dir
    runtime_global_config_path = global_config_path_for_state_dir(runtime_config_state_dir)
    runtime_global_config = load_global_config(
        runtime_global_config_path,
        state_dir=runtime_config_state_dir,
    )
    loaded_profile = replace(
        loaded_profile,
        manifest=_merge_runtime_manifest_from_global_config(
            loaded_profile.manifest,
            runtime_global_config,
        ),
    )

    active_provider_profile: AuthProfile | None = None
    if provider_profile is None:
        active_provider_profile = load_provider_profile(
            runtime_config_state_dir,
            config_path=runtime_global_config_path,
        )
    elif isinstance(provider_profile, AuthProfile):
        active_provider_profile = provider_profile
    elif provider_profile is not None:
        active_provider_profile = provider_profile_from_payload(provider_profile)
    if active_provider_profile is not None:
        auth_store.register(active_provider_profile)

    semantic_index_bundle = build_semantic_index_bundle(
        repository=runtime_repository,
        state_dir=runtime_state_dir,
    )
    recall_runtime = RecallRuntime.from_repository(
        runtime_repository,
        semantic_index_bundle=semantic_index_bundle,
    )
    cron_dir = default_cron_dir(install_root=install_root)
    cron_runtime = CronRuntime(
        cron_dir / "jobs.json",
        output_dir=cron_dir / "output",
        lock_path=cron_dir / "cron.lock",
    )
    skill_manifest = load_skill_extension_manifest(
        loaded_profile.manifest,
        profile_dir=install_root,
    )
    _gateway_embedding_service = recall_runtime.evidence_retriever.embedding_service
    semantic_summary_indexer = (
        SemanticSummaryIndexer(
            semantic_index=semantic_index_bundle.service,
            embedding_service=_gateway_embedding_service,
            repository=runtime_repository,
        )
        if _gateway_embedding_service is not None
        else None
    )
    skill_runtime = build_surface_skill_runtime(
        skill_manifest,
        repository=runtime_repository,
        profile_loader=profile_loader,
        surface_kind="gateway",
    )
    skill_hub = SkillHub(
        sources=default_skill_hub_sources(
            external_dirs=configured_external_skill_dirs(runtime_global_config),
            install_root=install_root,
        )
    )
    skill_search_hub = SkillSearchHub(cache_root=install_root / "skills" / "search-cache")
    skill_prompt_context = SkillPromptContextBuilder(
        repository=runtime_repository,
        profile_loader=profile_loader,
        skill_runtime=skill_runtime,
        install_root=install_root,
        surface_kind="gateway",
    )
    def _resolve_elephant_state(elephant_id: str):
        resolved_elephant_id = elephant_id.strip()
        if resolved_elephant_id:
            state = runtime_repository.load_state(f"state:{resolved_elephant_id}")
            if state is not None:
                return state
            for candidate in runtime_repository.list_states():
                if candidate.elephant_id == resolved_elephant_id or candidate.state_anchor in {
                    resolved_elephant_id,
                    f"elephant:{resolved_elephant_id}",
                }:
                    return candidate
        return runtime_repository.current_state()

    def _elephant_file_root_for_session(session_id: str | None) -> Path:
        if session_id:
            session = runtime_repository.load_episode_state(session_id)
            if session is not None and session.elephant_id:
                elephant_files = elephant_file_path(session.elephant_id, install_root=install_root)
                elephant_files.mkdir(parents=True, exist_ok=True)
                return elephant_files
        return Path.cwd()

    def _tool_context_for_session(session_id: str, requester: ToolRequester | None) -> ToolRuntimeContext:
        episode = runtime_repository.load_episode_state(session_id)
        if episode is None:
            raise KeyError(session_id)
        elephant_id = str(episode.elephant_id or "").strip()
        state = _resolve_elephant_state(elephant_id)
        cwd = _elephant_file_root_for_session(session_id)
        return ToolRuntimeContext(
            cwd=cwd,
            allowed_roots=(Path.home(), Path(tempfile.gettempdir())),
            env={},
            surface_id=f"gateway:{session_id}",
            surface_kind="gateway",
            requester=requester,
            personal_model_id=(episode.personal_model_id if state is None else state.personal_model_id),
            state_id="" if state is None else state.state_id,
            elephant_id=elephant_id,
            episode_id=episode.episode_id,
        )

    browser_backend, _browser_reason = create_playwright_browser_backend()
    outbound_queue = GatewayOutboundQueue(
        path=default_outbound_queue_path(resolved_state_dir or ephemeral_home),
    )
    tool_runtime = build_tool_runtime(
        enabled_overrides=_enabled_overrides(loaded_profile.manifest, "tool_overrides"),
        manifest_paths=_load_manifest_paths(loaded_profile.manifest, "tool_manifests", profile_dir=install_root),
        dependencies=BuiltinToolDependencies(
            cwd=Path.cwd(),
            cwd_resolver=_elephant_file_root_for_session,
            cron_runtime=cron_runtime,
            message_delivery=GatewayMessageDeliverySurface(
                outbound_queue=outbound_queue,
                identity_store=identity_store,
            ),
            personal_model_understanding=PersonalModelUnderstandingSurface(
                repository=runtime_repository,
                semantic_summary_indexer=semantic_summary_indexer,
                semantic_searcher=semantic_index_bundle.searcher,
                embedding_service=_gateway_embedding_service,
            ),
            skill_management=RuntimeSkillManagementSurface(
                skill_runtime=skill_runtime,
                skill_hub=skill_hub,
                profile_loader=profile_loader,
                profile_dir=install_root,
                skill_search_hub=skill_search_hub,
                installed_skills_dir=install_root / "skills" / "installed",
                authored_skills_dir=install_root / "skills" / "authored",
            ),
            browser_backend=browser_backend,
            clarify_surface=StructuredClarifySurface(
                surface_label="gateway",
                extra_metadata={"transport": "im"},
            ),
        ),
        context_resolver=_tool_context_for_session,
    )
    sync_custom_mcp_tools(
        tool_runtime,
        config_path=runtime_global_config_path,
        config=runtime_global_config,
        cwd=Path.cwd(),
    )
    preview_model_provider = GatewayPreviewModelProvider()
    model_provider = GatewaySurfaceModelProvider(
        repository=runtime_repository,
        fallback=preview_model_provider,
        active_provider_profile=active_provider_profile,
        runtime_environ=runtime_environ,
        credential_resolver=_gateway_provider_credential_resolver(
            runtime_repository=runtime_repository,
            resolved_state_dir=resolved_state_dir,
            resolved_control_state_dir=resolved_control_state_dir,
            runtime_environ=runtime_environ,
        ),
        tool_runtime=tool_runtime,
        semantic_index_bundle=semantic_index_bundle,
        embedding_service=_gateway_embedding_service,
        skill_runtime=skill_runtime,
        profile_loader=profile_loader,
    )
    provider_runtime = dict(model_provider.describe())
    epoch_store = FileEpochStore(runtime_state_dir)
    kernel = KernelService(
        dependencies=KernelDependencies(
            storage=runtime_repository,
            context=GatewayContextCapability(
                loaded_profile,
                skill_prompt_context=skill_prompt_context,
                profile_loader=profile_loader,
                repository=runtime_repository,
                epoch_store=epoch_store,
                install_root=install_root,
            ),
            recall=GatewayRecallCapability(recall_runtime),
            model_provider=model_provider,
            telemetry=telemetry,
            tools=RequesterScopedToolCapability(tool_runtime, "model"),
            embedding_service=recall_runtime.evidence_retriever.embedding_service,
            security_policy=SecurityPolicy.default(),
            skill_runtime=skill_runtime,
            semantic_summary_indexer=semantic_summary_indexer,
        )
    )

    app = GatewayApp(
        core=core,
        profile_id=profile_id,
        provider_runtime=provider_runtime,
        repository=runtime_repository,
        auth_store=auth_store,
        recall_runtime=recall_runtime,
        kernel=kernel,
        telemetry=telemetry,
        model_provider=model_provider,
        tool_runtime=tool_runtime,
        skill_runtime=skill_runtime,
        plugin_registry=registry,
        state_dir=str(resolved_state_dir) if resolved_state_dir is not None else None,
        epoch_store=epoch_store,
        loaded_profile=loaded_profile,
        provider_profile=active_provider_profile,
    )
    # Spawn background learning worker so enqueued jobs get processed
    if resolved_state_dir is not None:
        try:
            from apps.learning_worker_runtime import ensure_learning_worker_running
            ensure_learning_worker_running(
                state_dir=resolved_state_dir,
            )
        except Exception:
            pass
    chat_adapter = registry.create_adapter("chat_bot", app)
    webhook_adapter = registry.create_adapter("webhook", app)
    if not isinstance(chat_adapter, ChatBotMessagingAdapter):
        raise TypeError("gateway adapter plugin 'chat_bot' must build ChatBotMessagingAdapter")
    if not isinstance(webhook_adapter, WebhookMessagingAdapter):
        raise TypeError("gateway adapter plugin 'webhook' must build WebhookMessagingAdapter")
    return (
        app,
        chat_adapter,
        webhook_adapter,
    )


def _enabled_overrides(manifest: Mapping[str, Any], section: str) -> dict[str, bool]:
    payload = manifest.get(section, {})
    if not isinstance(payload, Mapping):
        return {}
    overrides: dict[str, bool] = {}
    for item_id, record in payload.items():
        if isinstance(record, Mapping) and "enabled" in record:
            overrides[str(item_id)] = _metadata_bool(record.get("enabled"), default=True)
        elif isinstance(record, bool):
            overrides[str(item_id)] = record
    return overrides


def _merge_runtime_manifest_from_global_config(
    manifest: Mapping[str, Any],
    global_config: Mapping[str, Any],
) -> dict[str, Any]:
    merged = dict(manifest)
    gateway_payload = global_config.get("gateway")
    if isinstance(gateway_payload, Mapping):
        merged["gateway"] = _deep_merge_mapping(
            _mapping_payload(merged.get("gateway")),
            gateway_payload,
        )
    extensions = load_extensions_from_config(global_config)
    if extensions:
        merged.update(extensions)
    return merged


def _mapping_payload(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _deep_merge_mapping(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        current = merged.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[str(key)] = _deep_merge_mapping(current, value)
        else:
            merged[str(key)] = value
    return merged


def _load_manifest_paths(
    manifest: Mapping[str, Any],
    section: str,
    *,
    profile_dir: Path,
) -> tuple[Path, ...]:
    payload = manifest.get(section, ())
    if not isinstance(payload, list):
        return ()
    paths: list[Path] = []
    for item in payload:
        raw = str(item).strip()
        if not raw:
            continue
        path = Path(raw)
        if not path.is_absolute():
            path = profile_dir / path
        paths.append(path)
    return tuple(paths)


def _metadata_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"true", "yes", "1", "on"}:
        return True
    if normalized in {"false", "no", "0", "off"}:
        return False
    return default
