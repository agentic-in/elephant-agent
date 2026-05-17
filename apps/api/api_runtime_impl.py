"""Programmatic API runtime implementation assembled from smaller method modules."""


from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
import json
from typing import Any, Mapping
from uuid import uuid4

from apps.provider_runtime import load_provider_profile
from packages.runtime_config import global_config_path_for_state_dir
from packages.models import SurfaceModelProviderCapability
from packages.auth import AuthProfile, PersistentAuthProfileStore
from packages.context import ContextRuntime
from packages.cron import CronRuntime
from packages.contracts import (
    ContextBundle,
    EventEnvelope,
    ExecutionResult,
)
from packages.contracts.runtime import PersonalModelRuntimeState, RecallEvidence
from packages.kernel import KernelDependencies, KernelOutcome, KernelService, KernelSourceRequest, ReconciliationPipeline, StateReconciler
from packages.evidence import RecallRuntime, SemanticSummaryIndexer, build_semantic_index_bundle
from packages.operator.runtime import (
    RecallEvidenceOperatorDetail,
    RecallEvidenceSearchHit,
    ProcedureOperatorDetail,
    build_recall_evidence_operator_surface,
    build_procedure_operator_surface,
    build_profile_operator_surface,
)
from packages.runtime_config import configured_external_skill_dirs, load_global_config
from packages.runtime_layout import default_cron_dir, infer_install_root_from_state_dir
from packages.state import ProfileLoader, build_prompt_contract
from packages.storage import RuntimeStorageRepository
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
from packages.tools import (
    BuiltinToolDependencies,
    RequesterScopedToolCapability,
    ToolRequester,
    ToolRuntimeContext,
    build_tool_runtime,
    sync_custom_mcp_tools,
)
from packages.tools.adapters import DeliveryMessageSurfaceAdapter, StructuredClarifySurface
from packages.understanding import PersonalModelUnderstandingSurface
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
    APIEpisodeLifecycleResult,
    APIEpisodeTransitionResult,
    APILoopRecord,
    APILoopResult,
)
from . import api_runtime_provider_methods as _provider_methods
from . import api_runtime_surface_methods as _surface_methods
from . import api_runtime_recall_methods as _recall_methods
from . import api_runtime_http_methods as _http_methods
from . import api_runtime_console as _console_methods
from . import api_runtime_cron_ops as _cron_methods
from . import api_runtime_internal_methods as _internal_methods


def _enabled_overrides(state_dir: Path, section: str) -> dict[str, bool]:
    """Load skill/extension override settings from config.yaml."""
    from packages.runtime_config import load_global_config, load_extensions_from_config, global_config_path_for_state_dir
    manifest = {}
    try:
        config_path = global_config_path_for_state_dir(state_dir)
        config = load_global_config(config_path, state_dir=state_dir)
        extensions = load_extensions_from_config(config)
        if extensions:
            manifest = extensions
    except (OSError, ValueError):
        pass
    payload = manifest.get(section) if isinstance(manifest, Mapping) else None
    if not isinstance(payload, Mapping):
        return {}
    overrides: dict[str, bool] = {}
    for item_id, record in payload.items():
        if isinstance(record, Mapping) and isinstance(record.get("enabled"), bool):
            overrides[str(item_id)] = bool(record["enabled"])
    return overrides


class ElephantAPIApp:
    def __init__(self, config: APIAppConfig) -> None:
        self.config = config
        self.repository = RuntimeStorageRepository(config.database_path)
        self.repository.bootstrap()
        runtime_state_dir = self.repository.database_path.parent
        _obs_cfg = load_global_config(global_config_path_for_state_dir(runtime_state_dir), state_dir=runtime_state_dir)
        from packages.observability import setup_from_config
        setup_from_config(_obs_cfg, state_dir=str(runtime_state_dir))
        install_root = config.install_root or infer_install_root_from_state_dir(runtime_state_dir)
        sync_builtin_skill_shelf(destination_root=install_root / "skills" / "builtin")
        self.profile_loader = ProfileLoader(install_root)
        active_provider_profile = load_provider_profile(runtime_state_dir, config_path=global_config_path_for_state_dir(runtime_state_dir))
        active_provider_profile_id = None
        active_provider_id = None
        if active_provider_profile is not None:
            self.repository.upsert_auth_profile(active_provider_profile)
            active_provider_profile_id = active_provider_profile.profile_id
            active_provider_id = active_provider_profile.provider_id
        self.auth_store = PersistentAuthProfileStore(self.repository)
        self.semantic_index_bundle = build_semantic_index_bundle(
            repository=self.repository,
            state_dir=runtime_state_dir,
        )
        self.recall_runtime = RecallRuntime.from_repository(
            self.repository,
            semantic_index_bundle=self.semantic_index_bundle,
        )
        cron_dir = default_cron_dir(install_root=install_root)
        self.cron_runtime = CronRuntime(
            cron_dir / "jobs.json",
            output_dir=cron_dir / "output",
            lock_path=cron_dir / "cron.lock",
        )
        loaded_profile = self.profile_loader.load()
        prompt_contract = build_prompt_contract(loaded_profile, prompt_mode="full")
        context_instruction_refs = prompt_contract.instruction_refs or config.instruction_refs
        self.context_runtime = ContextRuntime(instruction_refs=context_instruction_refs, total_tokens=config.total_tokens)
        self.personal_state = APIStateService(
            repository=self.repository,
            recall_runtime=self.recall_runtime,
        )
        self.telemetry = APITelemetrySink()
        self.preview_model_provider = APIModelProvider()
        self.delivery = APIDeliveryCapability()
        self.recall = APIRecallCapability(self.recall_runtime)
        browser_backend, _ = create_playwright_browser_backend()
        runtime_global_config_path = global_config_path_for_state_dir(runtime_state_dir)
        runtime_global_config = load_global_config(
            runtime_global_config_path,
            state_dir=runtime_state_dir,
        )
        skill_manifest = load_skill_extension_manifest(
            self.profile_loader.load().manifest,
            profile_dir=install_root,
        )
        _api_embedding_service = self.recall_runtime.evidence_retriever.embedding_service
        self.semantic_summary_indexer = (
            SemanticSummaryIndexer(
                semantic_index=self.semantic_index_bundle.service,
                embedding_service=_api_embedding_service,
                repository=self.repository,
            )
            if _api_embedding_service is not None
            else None
        )
        self.skill_runtime = build_surface_skill_runtime(
            skill_manifest,
            repository=self.repository,
            profile_loader=self.profile_loader,
            surface_kind="api",
        )
        self.skill_hub = SkillHub(
            sources=default_skill_hub_sources(
                external_dirs=configured_external_skill_dirs(runtime_global_config),
                install_root=install_root,
            )
        )
        self.skill_search_hub = SkillSearchHub()
        skill_prompt_context = SkillPromptContextBuilder(
            repository=self.repository,
            profile_loader=self.profile_loader,
            skill_runtime=self.skill_runtime,
            install_root=install_root,
            surface_kind="api",
        )
        self.context = APIContextCapability(
            self.context_runtime,
            skill_prompt_context=skill_prompt_context,
            repository=self.repository,
            profile_loader=self.profile_loader,
            install_root=install_root,
        )
        def _resolve_elephant_state(elephant_id: str):
            resolved_elephant_id = elephant_id.strip()
            if resolved_elephant_id:
                state = self.repository.load_state(f"state:{resolved_elephant_id}")
                if state is not None:
                    return state
                for candidate in self.repository.list_states():
                    if candidate.elephant_id == resolved_elephant_id:
                        return candidate
            return self.repository.current_state()

        def _tool_context_for_session(session_id: str, requester: ToolRequester | None) -> ToolRuntimeContext:
            episode = self.repository.load_episode_state(session_id)
            if episode is None:
                raise KeyError(session_id)
            elephant_id = str(episode.elephant_id or "").strip()
            state = _resolve_elephant_state(elephant_id)
            return ToolRuntimeContext(
                cwd=Path.cwd(),
                allowed_roots=(Path.home(), Path("/tmp")),
                env={},
                surface_id=f"api:{session_id}",
                surface_kind="api",
                requester=requester,
                personal_model_id=(episode.personal_model_id if state is None else state.personal_model_id),
                state_id="" if state is None else state.state_id,
                elephant_id=elephant_id,
                episode_id=episode.episode_id,
            )
        self.tool_runtime = build_tool_runtime(
            enabled_overrides=_enabled_overrides(runtime_state_dir, "tool_overrides"),
            dependencies=BuiltinToolDependencies(
                cwd=Path.cwd(),
                cron_runtime=self.cron_runtime,
                personal_model_understanding=PersonalModelUnderstandingSurface(
                    repository=self.repository,
                    semantic_summary_indexer=self.semantic_summary_indexer,
                    semantic_searcher=self.semantic_index_bundle.searcher,
                    embedding_service=_api_embedding_service,
                ),
                skill_management=RuntimeSkillManagementSurface(
                    skill_runtime=self.skill_runtime,
                    skill_hub=self.skill_hub,
                    profile_loader=self.profile_loader,
                    profile_dir=install_root,
                    skill_search_hub=self.skill_search_hub,
                    installed_skills_dir=install_root / "skills" / "installed",
                    authored_skills_dir=install_root / "skills" / "authored",
                ),
                browser_backend=browser_backend,
                message_delivery=DeliveryMessageSurfaceAdapter(
                    self.delivery,
                    surface_label="api",
                    default_target="api",
                ),
                clarify_surface=StructuredClarifySurface(
                    surface_label="api",
                    extra_metadata={"transport": "http"},
                ),
            ),
            context_resolver=_tool_context_for_session,
        )
        sync_custom_mcp_tools(
            self.tool_runtime,
            config_path=runtime_global_config_path,
            config=runtime_global_config,
            cwd=Path.cwd(),
        )
        self.tools = APIToolExecution(self.tool_runtime)
        self.model_provider = SurfaceModelProviderCapability(
            repository=self.repository,
            fallback=self.preview_model_provider,
            secret_key_path=self.repository.database_path.parent / "provider-secrets.key",
            tool_runtime=self.tool_runtime,
            capability_id="api.model.runtime",
            surface_label="api",
            active_provider_profile_id=active_provider_profile_id,
            active_provider_id=active_provider_id,
            bootstrap_state_dir=self.repository.database_path.parent,
        )
        self.kernel = KernelService(
            dependencies=KernelDependencies(
                storage=self.repository,
                context=self.context,
                recall=self.recall,
                model_provider=self.model_provider,
                telemetry=self.telemetry,
                tools=RequesterScopedToolCapability(self.tool_runtime, "model"),
                delivery=self.delivery,
                embedding_service=self.recall_runtime.evidence_retriever.embedding_service,
                skill_runtime=self.skill_runtime,
                semantic_summary_indexer=self.semantic_summary_indexer,
            )
        )
        self._loops: dict[str, list[APILoopRecord]] = {}

ElephantAPIApp.list_providers = _provider_methods.list_providers
ElephantAPIApp.setup_provider = _provider_methods.setup_provider
ElephantAPIApp.discover_provider_models = _provider_methods.discover_provider_models
ElephantAPIApp.set_default_provider = _provider_methods.set_default_provider
ElephantAPIApp._provider_probe = _provider_methods._provider_probe
ElephantAPIApp.test_provider = _provider_methods.test_provider
ElephantAPIApp.doctor_provider = _provider_methods.doctor_provider
ElephantAPIApp.embedding_provider_summary = _provider_methods.embedding_provider_summary
ElephantAPIApp.set_local_embedding_provider = _provider_methods.set_local_embedding_provider
ElephantAPIApp.set_openai_compatible_embedding_provider = _provider_methods.set_openai_compatible_embedding_provider
ElephantAPIApp.set_embedding_provider = _provider_methods.set_embedding_provider
ElephantAPIApp._embedding_provider_profile = _provider_methods._embedding_provider_profile
ElephantAPIApp._active_embedding_provider_profile = _provider_methods._active_embedding_provider_profile
ElephantAPIApp._stored_embedding_api_key = _provider_methods._stored_embedding_api_key
ElephantAPIApp._stored_api_key_for_active_provider = _provider_methods._stored_api_key_for_active_provider
ElephantAPIApp.list_provider_keys = _provider_methods.list_provider_keys
ElephantAPIApp.create_provider_key = _provider_methods.create_provider_key
ElephantAPIApp.upsert_provider_key = _provider_methods.upsert_provider_key
ElephantAPIApp.delete_provider_key = _provider_methods.delete_provider_key
ElephantAPIApp.create_episode = _surface_methods.create_episode
ElephantAPIApp.interrupt_episode = _surface_methods.interrupt_episode
ElephantAPIApp.open_next_episode = _surface_methods.open_next_episode
ElephantAPIApp.list_recall_evidence = _surface_methods.list_recall_evidence
ElephantAPIApp.inspect_identity = _surface_methods.inspect_identity
ElephantAPIApp.update_identity_state = _surface_methods.update_identity_state
ElephantAPIApp.inspect_user = _surface_methods.inspect_user
ElephantAPIApp.update_user_state = _surface_methods.update_user_state
ElephantAPIApp.inspect_relationship = _surface_methods.inspect_relationship
ElephantAPIApp.update_relationship_state = _surface_methods.update_relationship_state
ElephantAPIApp.inspect_continuity = _surface_methods.inspect_continuity
ElephantAPIApp.inspect_context_frame = _surface_methods.inspect_context_frame
ElephantAPIApp.inspect_recall_evidence_surface = _surface_methods.inspect_recall_evidence_surface
ElephantAPIApp.search_recall_evidence_surface = _surface_methods.search_recall_evidence_surface
ElephantAPIApp.inspect_episode = _surface_methods.inspect_episode
ElephantAPIApp.inspect_internal_dashboard = _internal_methods.inspect_internal_dashboard
ElephantAPIApp.delete_diary_entry = _internal_methods.delete_diary_entry
ElephantAPIApp.trigger_diary_write = _internal_methods.trigger_diary_write
ElephantAPIApp.trigger_reflect_job = _internal_methods.trigger_reflect_job
ElephantAPIApp.patch_operator_settings = _console_methods.patch_operator_settings
ElephantAPIApp.patch_operator_global_config = _console_methods.patch_operator_global_config
ElephantAPIApp.create_operator_mcp_tool = _console_methods.create_operator_mcp_tool
ElephantAPIApp.update_operator_mcp_tool = _console_methods.update_operator_mcp_tool
ElephantAPIApp.delete_operator_mcp_tool = _console_methods.delete_operator_mcp_tool
ElephantAPIApp.sync_operator_mcp_server = _console_methods.sync_operator_mcp_server
ElephantAPIApp.delete_operator_mcp_server = _console_methods.delete_operator_mcp_server
ElephantAPIApp.set_operator_mcp_tool_enabled = _console_methods.set_operator_mcp_tool_enabled
ElephantAPIApp.discover_operator_mcp_server = _console_methods.discover_operator_mcp_server
ElephantAPIApp.set_console_item_enabled = _console_methods.set_console_item_enabled
ElephantAPIApp.gateway_action = _console_methods.gateway_action
ElephantAPIApp.inspect_recall_evidence = _recall_methods.inspect_recall_evidence
ElephantAPIApp.run_loop = _http_methods.run_loop
ElephantAPIApp.dispatch = _http_methods.dispatch
ElephantAPIApp._dispatch_providers = _http_methods._dispatch_providers
ElephantAPIApp._dispatch_internal = _http_methods._dispatch_internal
ElephantAPIApp._dispatch_operator = _http_methods._dispatch_operator
ElephantAPIApp._dispatch_episodes = _http_methods._dispatch_episodes
ElephantAPIApp._dispatch_states = _http_methods._dispatch_states
ElephantAPIApp.run_cron_job_now = _http_methods.run_cron_job_now
ElephantAPIApp.run_proactive_ask_now = _cron_methods.run_proactive_ask_now
ElephantAPIApp.__call__ = _http_methods.__call__

def create_app(
    *,
    database_path: str | Path,
    install_root: str | Path | None = None,
    instruction_refs: tuple[str, ...] = ("apps/api",),
    total_tokens: int = 2048,
) -> ElephantAPIApp:
    return ElephantAPIApp(
        APIAppConfig(
            database_path=Path(database_path),
            install_root=Path(install_root) if install_root is not None else None,
            instruction_refs=instruction_refs,
            total_tokens=total_tokens,
        )
    )

__all__ = [
    "APIAppConfig",
    "APIResponse",
    "APIEpisodeCreationResult",
    "APIEpisodeInspection",
    "APIEpisodeLifecycleResult",
    "APIEpisodeTransitionResult",
    "APILoopRecord",
    "APILoopResult",
    "ElephantAPIApp",
    "create_app",
]
