"""Core CLI runtime implementation composed from smaller mixin surfaces."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import os
from pathlib import Path
import threading
from typing import Any

from apps.provider_runtime import capture_runtime_secret_env, load_provider_profile
from packages.models import SurfaceModelProviderCapability
from packages.contracts.layers import Episode
from packages.contracts.runtime import (
    ContextBundle,
    EventEnvelope,
    ExecutionResult,
    ExperienceRecord,
    StateFocusDecision,
    RecallEvidence,
    PlanDraft,
    PromptMessage,
    PersonalModelGrowthState,
    PersonalModelRuntimeState,
)
from packages.cron import CronRuntime
from packages.evidence import RecallRuntime, SemanticSummaryIndexer, build_semantic_index_bundle
from packages.gateway_core import FileGatewayIdentityStore, GatewayOutboundQueue, default_outbound_queue_path
from packages.gateway_core.outbound_delivery import GatewayMessageDeliverySurface
from packages.growth import GrowthUpdate
from packages.kernel import KernelDependencies, KernelOutcome
from packages.runtime_config import configured_external_skill_dirs, global_config_path_for_state_dir, load_global_config
from packages.runtime_layout import (
    default_authored_skills_dir,
    default_builtin_skills_dir,
    default_cron_dir,
    default_installed_skills_dir,
    default_pairing_dir,
    default_skill_search_cache_dir,
    default_workspaces_dir,
    infer_install_root_from_state_dir,
)
from packages.security import SecurityPolicy
from packages.skills import SkillHub, SkillPromptContextBuilder, SkillSearchHub, SkillRuntime, default_skill_hub_sources, sync_builtin_skill_shelf
from packages.state import ProfileLoader
from packages.storage import RuntimeStorageRepository
from packages.tools import BuiltinToolDependencies, InMemorySessionTodoStore, ToolRuntime
from packages.tools.adapters import StructuredClarifySurface
from packages.tools.browser_backend import create_playwright_browser_backend
from packages.tools.surfaces import BrowserToolBackend, ClarifySurface
from packages.understanding import PersonalModelUnderstandingSurface

from .runtime_cognition import (
    _CliContextCapability,
    _DurableRecallCapability,
    _PreviewDeliveryCapability,
    _PreviewModelProviderCapability,
)
from .runtime_extensions import (
    _PreviewTelemetrySink,
    build_skill_runtime,
    build_tool_runtime,
    load_extension_manifest,
    load_json_file,
    sanitize_extension_manifest_payload,
)
from .runtime_extensions_surface import CliRuntimeExtensionsMixin
from .runtime_profile import CliRuntimeProfileMixin
from .runtime_provider import CliRuntimeProviderMixin
from .runtime_records import CliRuntimeRecordsMixin
from .runtime_snapshot import (
    append_outcome_experience as _append_runtime_outcome_experience,
    append_outcome_growth as _append_runtime_outcome_growth,
    append_outcome_recall_event as _append_runtime_outcome_recall_event,
    load_snapshot as _load_runtime_snapshot,
    write_snapshot as _write_runtime_snapshot,
)
from .runtime_support import *  # noqa: F401,F403
from .runtime_support import _default_elephant_identity_file_text, _seed_elephant_identity_text
from .runtime_turns import (
    build_kernel_dependencies as _build_runtime_kernel_dependencies,
    create_elephant_session as _create_runtime_elephant_session,
    explain_next_step as _explain_runtime_next_step,
    generate_opening_reply as _generate_runtime_opening_reply,
    inspect_wake_continuity as _inspect_runtime_wake_continuity,
    open_next_episode as _open_runtime_next_episode,
    run_turn as _run_runtime_turn,
    start_episode as _start_runtime_session,
)

@dataclass(frozen=True, slots=True)
class CliRuntime(CliRuntimeProfileMixin, CliRuntimeProviderMixin, CliRuntimeExtensionsMixin, CliRuntimeRecordsMixin):
    paths: CliPaths
    repository: RuntimeStorageRepository
    profile_loader: ProfileLoader
    snapshot_path: Path
    recall_runtime: RecallRuntime
    cron_runtime: CronRuntime
    model_provider: SurfaceModelProviderCapability
    tool_runtime: ToolRuntime
    skill_runtime: SkillRuntime
    skill_hub: SkillHub
    skill_search_hub: SkillSearchHub
    security_policy: SecurityPolicy
    semantic_index_bundle: Any = None
    skill_prompt_context: SkillPromptContextBuilder | None = None
    todo_store: InMemorySessionTodoStore = field(default_factory=InMemorySessionTodoStore)
    browser_backend: BrowserToolBackend | None = None
    clarify_surface: ClarifySurface | None = None
    message_delivery_surface: Any = None
    sub_agent_active: bool = field(default=False, repr=False, compare=False)
    active_provider_id: str | None = None
    growth_updates: dict[str, GrowthUpdate] = field(default_factory=dict, repr=False, compare=False)
    kernel_event_observer: Any = field(default=None, repr=False, compare=False)

    @classmethod
    def create(
        cls,
        *,
        state_dir: Path,
        warm_embedding: bool = True,
    ) -> "CliRuntime":
        home_dir = infer_install_root_from_state_dir(state_dir)
        skills_dir = home_dir / "skills"
        paths = CliPaths(
            home_dir=home_dir,
            state_dir=state_dir,
            skills_dir=skills_dir,
            builtin_skills_dir=default_builtin_skills_dir(install_root=home_dir),
            installed_skills_dir=default_installed_skills_dir(install_root=home_dir),
            authored_skills_dir=default_authored_skills_dir(install_root=home_dir),
            skill_search_cache_dir=default_skill_search_cache_dir(install_root=home_dir),
            cron_dir=default_cron_dir(install_root=home_dir),
            workspaces_dir=default_workspaces_dir(install_root=home_dir),
            pairing_dir=default_pairing_dir(install_root=home_dir),
        )
        repository = RuntimeStorageRepository(paths.database_path)
        repository.bootstrap()
        sync_builtin_skill_shelf(destination_root=paths.builtin_skills_dir)
        profile_loader = ProfileLoader(home_dir)
        global_config_path = global_config_path_for_state_dir(state_dir)
        # Ensure config.yaml is always written so the file is visible
        from packages.runtime_config import read_global_config_text
        if not global_config_path.exists():
            from packages.runtime_config import write_global_config, default_global_config
            write_global_config(
                global_config_path,
                default_global_config(state_dir=state_dir),
            )
        global_config = load_global_config(
            global_config_path,
            state_dir=state_dir,
        )
        from packages.observability import setup_from_config
        setup_from_config(global_config, state_dir=str(state_dir))
        active_provider_profile = load_provider_profile(state_dir, config_path=global_config_path)
        active_provider_profile_id = None
        active_provider_id = None
        if active_provider_profile is not None:
            repository.upsert_auth_profile(active_provider_profile)
            active_provider_profile_id = active_provider_profile.profile_id
            active_provider_id = active_provider_profile.provider_id
            capture_runtime_secret_env(paths.state_dir, active_provider_profile)
        # Load extension manifest from config.yaml
        from packages.runtime_config import load_extensions_from_config
        config_extensions = load_extensions_from_config(global_config)
        extension_manifest = load_extension_manifest(config_extensions, profile_dir=home_dir)
        cron_runtime = CronRuntime(paths.cron_jobs_path, output_dir=paths.cron_output_dir, lock_path=paths.cron_lock_path)
        skill_hub = SkillHub(
            sources=default_skill_hub_sources(
                external_dirs=configured_external_skill_dirs(global_config),
                install_root=home_dir,
            )
        )
        skill_search_hub = SkillSearchHub(cache_root=paths.skill_search_cache_dir)
        security_policy = SecurityPolicy.default()
        todo_store = InMemorySessionTodoStore()

        # --- Parallel initialization of heavy I/O operations ---
        # browser_backend and semantic_index_bundle are the two slowest
        # components (500ms-4.5s each). Run them in parallel threads to
        # halve the total boot time.
        browser_holder: dict[str, object] = {}
        semantic_holder: dict[str, object] = {}

        def _init_browser():
            browser_holder["backend"], browser_holder["reason"] = create_playwright_browser_backend()

        def _init_semantic():
            semantic_holder["bundle"] = build_semantic_index_bundle(
                repository=repository,
                state_dir=paths.state_dir,
            )

        browser_thread = threading.Thread(target=_init_browser, name="elephant-init-browser", daemon=True)
        semantic_thread = threading.Thread(target=_init_semantic, name="elephant-init-semantic", daemon=True)
        browser_thread.start()
        semantic_thread.start()

        # Wait for semantic bundle (needed for recall_runtime + tool dependencies)
        semantic_thread.join()
        semantic_index_bundle = semantic_holder.get("bundle")

        recall_runtime = RecallRuntime.from_repository(
            repository,
            semantic_index_bundle=semantic_index_bundle,
        )
        _embedding_service = recall_runtime.evidence_retriever.embedding_service
        semantic_summary_indexer = (
            SemanticSummaryIndexer(
                semantic_index=semantic_index_bundle.service,
                embedding_service=_embedding_service,
                repository=repository,
            )
            if _embedding_service is not None and semantic_index_bundle is not None
            else None
        )
        message_delivery = GatewayMessageDeliverySurface(
            outbound_queue=GatewayOutboundQueue(path=default_outbound_queue_path(state_dir)),
            identity_store=FileGatewayIdentityStore(state_dir / "gateway-identities.json"),
        )
        clarify_surface = StructuredClarifySurface(surface_label="cli")

        def _elephant_file_root_for_session(session_id: str | None) -> Path:
            if session_id:
                session = repository.load_episode_state(session_id)
                if session is not None and session.elephant_id:
                    elephant_files = paths.elephant_file_path(session.elephant_id)
                    elephant_files.mkdir(parents=True, exist_ok=True)
                    return elephant_files
            return Path.cwd()

        # Wait for browser backend (needed by tool_runtime)
        browser_thread.join()
        browser_backend = browser_holder.get("backend")

        tool_runtime = build_tool_runtime(
            extension_manifest,
            repository=repository,
            dependencies=BuiltinToolDependencies(
                cwd=Path.cwd(),
                cwd_resolver=_elephant_file_root_for_session,
                cron_runtime=cron_runtime,
                message_delivery=message_delivery,
                personal_model_understanding=PersonalModelUnderstandingSurface(
                    repository=repository,
                    semantic_summary_indexer=semantic_summary_indexer,
                    semantic_searcher=semantic_index_bundle.searcher if semantic_index_bundle is not None else None,
                    embedding_service=_embedding_service,
                ),
                todo_store=todo_store,
                learning_result_surface=None,
                browser_backend=browser_backend,
                clarify_surface=clarify_surface,
            ),
            snapshot_path=paths.snapshot_path,
            security_policy=security_policy,
        )
        # Kick the sentence-transformer steady as early as possible — right
        # after the embedding service is constructed. `steady_async` is
        # idempotent + daemon-threaded (see
        # packages/embeddings/runtime.py:810), so calling it here just
        # guarantees the 4.5 s cold load is in flight well before any
        # session surface prep or the shell composer's first paint.
        if warm_embedding and _embedding_service is not None:
            steady_async = getattr(_embedding_service, "steady_async", None)
            if callable(steady_async):
                try:
                    steady_async()
                except Exception:
                    # Best-effort: an unavailable runtime is not an error.
                    pass
        skill_runtime = build_skill_runtime(
            extension_manifest,
            repository=repository,
            profile_loader=profile_loader,
            scan_on_init_dirs=(paths.authored_skills_dir,) if getattr(paths, "authored_skills_dir", None) else (),
        )
        runtime = cls(
            paths=paths,
            repository=repository,
            profile_loader=profile_loader,
            snapshot_path=paths.snapshot_path,
            recall_runtime=recall_runtime,
            cron_runtime=cron_runtime,
            model_provider=SurfaceModelProviderCapability(
                repository=repository,
                fallback=_PreviewModelProviderCapability(),
                secret_key_path=paths.secret_key_path,
                tool_runtime=tool_runtime,
                capability_id="cli.model.runtime",
                surface_label="cli",
                active_provider_profile_id=active_provider_profile_id,
                active_provider_id=active_provider_id,
                bootstrap_state_dir=paths.state_dir,
            ),
            tool_runtime=tool_runtime,
            skill_runtime=skill_runtime,
            skill_hub=skill_hub,
            skill_search_hub=skill_search_hub,
            security_policy=security_policy,
            semantic_index_bundle=semantic_index_bundle,
            skill_prompt_context=SkillPromptContextBuilder(
                repository=repository,
                profile_loader=profile_loader,
                skill_runtime=skill_runtime,
                install_root=home_dir,
                surface_kind="cli",
            ),
            todo_store=todo_store,
            browser_backend=browser_backend,
            clarify_surface=clarify_surface,
            message_delivery_surface=message_delivery,
            sub_agent_active=os.environ.get("ELEPHANT_SUB_AGENT_CHILD") == "1",
            active_provider_id=active_provider_id,
        )
        runtime._apply_extension_manifest(extension_manifest)
        return runtime

    def start(
        self,
        *,
        profile_id: str | None = None,
        display_name: str | None = None,
        mode: str | None = None,
        session_id: str | None = None,
    ) -> Episode:
        return _start_runtime_session(
            self,
            profile_id=profile_id,
            display_name=display_name,
            mode=mode,
            session_id=session_id,
        )

    def create_elephant(
        self,
        *,
        elephant_id: str,
        profile_id: str | None = None,
        display_name: str | None = None,
        mode: str | None = None,
        session_id: str | None = None,
    ) -> Episode:
        return _create_runtime_elephant_session(
            self,
            elephant_id=elephant_id,
            profile_id=profile_id,
            display_name=display_name,
            mode=mode,
            session_id=session_id,
            seed_elephant_identity_text=_seed_elephant_identity_text,
            seed_elephant_identity_file_text=_default_elephant_identity_file_text,
        )

    def open_next_episode(
        self,
        episode_id: str,
        *,
        next_episode_id: str | None = None,
        reason: str = "wake_boundary",
        summary: str = "",
    ):
        return _open_runtime_next_episode(
            self,
            episode_id,
            next_episode_id=next_episode_id,
            reason=reason,
            summary=summary,
        )

    def explain_next_step(
        self,
        *,
        session_id: str,
        prompt: str,
        state_query: str | None = None,
        tool_name: str | None = None,
        tool_arguments: Mapping[str, Any] | None = None,
        delivery_payload: Mapping[str, Any] | None = None,
        event_payload: Mapping[str, str] | None = None,
    ) -> KernelOutcome:
        return _explain_runtime_next_step(
            self,
            session_id=session_id,
            prompt=prompt,
            state_query=state_query,
            tool_name=tool_name,
            tool_arguments=tool_arguments,
            delivery_payload=delivery_payload,
            event_payload=event_payload,
        )

    def compact_session_context(
        self,
        session_id: str,
        *,
        reason: str = "gateway-hygiene",
        force: bool = False,
    ):
        session = self._load_session(session_id)
        capability = _CliContextCapability(
            profile_loader=self.profile_loader,
            repository=self.repository,
            prompt_mode="full",
            snapshot_path=self.snapshot_path,
            total_tokens=self.active_provider_context_window(),
            tool_runtime=self.tool_runtime,
            skill_runtime=self.skill_runtime,
            skill_prompt_context=self.skill_prompt_context,
            install_root=self.paths.home_dir,
            workspaces_dir=self.paths.workspaces_dir,
            summary_model_provider=self.model_provider,
            embedding_service=self.recall_runtime.retriever.evidence_retriever.embedding_service,
        )
        return capability.compact_session_projection(
            session_id=session.episode_id,
            reason=reason,
            force=force,
        )

    def generate_opening_reply(
        self,
        *,
        session_id: str,
        prompt: str,
        opening_label: str,
    ) -> KernelOutcome | None:
        return _generate_runtime_opening_reply(
            self,
            session_id=session_id,
            prompt=prompt,
            opening_label=opening_label,
        )

    def _run_turn(
        self,
        *,
        session_id: str,
        prompt: str,
        state_query: str | None = None,
        tool_name: str | None = None,
        tool_arguments: Mapping[str, Any] | None = None,
        delivery_payload: Mapping[str, Any] | None = None,
        event_type: str = "turn.received",
        source: str = "cli",
        event_payload: Mapping[str, str] | None = None,
        record_input_event: bool = True,
        record_outcome_event: bool = True,
        capture_experience: bool = True,
        apply_growth: bool = True,
    ) -> KernelOutcome:
        return _run_runtime_turn(
            self,
            session_id=session_id,
            prompt=prompt,
            state_query=state_query,
            tool_name=tool_name,
            tool_arguments=tool_arguments,
            delivery_payload=delivery_payload,
            event_type=event_type,
            source=source,
            event_payload=event_payload,
            record_input_event=record_input_event,
            record_outcome_event=record_outcome_event,
            capture_experience=capture_experience,
            apply_growth=apply_growth,
        )

    def inspect_wake_continuity(self, episode_id: str) -> WakeProgressionResult:
        return _inspect_runtime_wake_continuity(
            self,
            episode_id,
            result_cls=WakeProgressionResult,
        )

    def _build_kernel_dependencies(self, session: Episode, profile: PersonalModelRuntimeState) -> KernelDependencies:
        return _build_runtime_kernel_dependencies(
            self,
            session,
            profile,
            recall_capability_cls=_DurableRecallCapability,
            context_capability_cls=_CliContextCapability,
            telemetry_cls=_PreviewTelemetrySink,
            delivery_capability_cls=_PreviewDeliveryCapability,
        )

    def set_kernel_event_observer(self, observer) -> None:
        object.__setattr__(self, "kernel_event_observer", observer)

    def _load_snapshot(self) -> dict[str, Any] | None:
        return _load_runtime_snapshot(self)

    def _append_outcome_recall_event(self, outcome: KernelOutcome) -> None:
        _append_runtime_outcome_recall_event(self, outcome)

    def _append_outcome_experience(self, outcome: KernelOutcome) -> ExperienceRecord | None:
        return _append_runtime_outcome_experience(self, outcome)

    def _append_outcome_growth(
        self,
        outcome: KernelOutcome,
        *,
        experience: ExperienceRecord | None,
    ) -> PersonalModelGrowthState:
        return _append_runtime_outcome_growth(
            self,
            outcome,
            experience=experience,
        )

    def _write_snapshot(
        self,
        *,
        profile: PersonalModelRuntimeState,
        session: Episode,
        work_items: tuple[object, ...],
        recall_items: tuple[RecallEvidence, ...],
        plan: PlanDraft | None,
        execution: ExecutionResult | None,
        delivery: ExecutionResult | None,
        stages: tuple[Any, ...],
        event: EventEnvelope | None,
        elephant_identity_text: str | None,
        state_focus: StateFocusDecision | None,
        context: ContextBundle | None = None,
        turn_messages: tuple[PromptMessage, ...] = (),
    ) -> None:
        _write_runtime_snapshot(
            self,
            profile=profile,
            session=session,
            work_items=work_items,
            recall_items=recall_items,
            plan=plan,
            execution=execution,
            delivery=delivery,
            stages=stages,
            event=event,
            elephant_identity_text=elephant_identity_text,
            state_focus=state_focus,
            context=context,
            turn_messages=turn_messages,
        )
