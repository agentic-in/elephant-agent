"""Gateway runtime capabilities."""


from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import tempfile
from typing import Any
from uuid import uuid4

from apps.provider_runtime import (
    load_provider_profile,
    provider_profile_from_payload,
)
from packages.auth import AuthProfile, EnvironmentSecretStore, PersistentAuthProfileStore, ProfileCredentialResolver
from packages.models import SurfaceModelProviderCapability
from packages.models.runtime_capability import provider_fallback_summary, provider_profile_summary
from packages.capabilities.runtime import (
    CapabilityDescriptor,
    ContextCapability,
    RecallCapability,
    ModelProviderCapability,
    TelemetrySinkCapability,
)
from packages.context import (
    ContextRuntime,
    apply_session_context_epoch,
)
from packages.context.epoch_store import EpochStore
from packages.context.compress import compress_epoch
from packages.contracts import Episode
from packages.contracts.runtime import (
    ContextBundle,
    ExecutionResult,
    StateFocusDecision,
    EvidenceRetrievalRequest,
    EvidenceRetrievalResult,
    RecallEvidence,
    RuntimeModelChoice,
    PersonalModelRuntimeState,
    GenerationModelProfile,
    SupportModelProfile,
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
    GatewayOutboundMessage,
    GatewayPolicyHint,
    GatewaySenderRef,
    InMemoryGatewayIdentityStore,
    InMemoryGatewaySessionStore,
)
from packages.kernel import KernelDependencies, KernelService, KernelSourceRequest, ReconciliationPipeline, StateReconciler
from packages.evidence import RecallRuntime
from packages.runtime_layout import elephant_file_path
from packages.skills import SkillPromptContextBuilder
from packages.state import (
    DEFAULT_ELEPHANT_IDENTITY_TEXT,
    LoadedProfile,
    ProfileLoader,
    build_prompt_contract,
    elephant_id_from_session,
    load_runtime_profile,
    profile_with_authored_elephant_identity,
)
from packages.security.runtime import SecurityPolicy
from packages.storage import RuntimeStorageRepository
from packages.tools import ToolRuntime
from .plugins import GatewayAdapterDescriptor, GatewayPluginRegistry

CHAT_BOT_ADAPTER_ID = "messaging.chat-bot"
WEBHOOK_ADAPTER_ID = "messaging.webhook"
TELEGRAM_ADAPTER_ID = "messaging.telegram"
FEISHU_ADAPTER_ID = "messaging.feishu"
DISCORD_ADAPTER_ID = "messaging.discord"

from .runtime_support import *  # noqa: F401,F403

class GatewayTelemetrySink(TelemetrySinkCapability):
    def __init__(self) -> None:
        self.descriptor = CapabilityDescriptor(
            capability_id="gateway.telemetry",
            kind="telemetry_sink",
            version="1.0.0",
            metadata={"description": "In-process telemetry sink for gateway shared-runtime turns."},
        )
        self._events: list[dict[str, Any]] = []

    @property
    def events(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._events)

    def emit(self, event: Mapping[str, Any]) -> None:
        self._events.append(dict(event))

class GatewayRecallCapability(RecallCapability):
    def __init__(self, runtime: RecallRuntime) -> None:
        self.descriptor = CapabilityDescriptor(
            capability_id="gateway.recall",
            kind="recall",
            version="1.0.0",
            metadata={"description": "Shared evidence recall adapter for gateway turns."},
        )
        self.runtime = runtime

    def retrieve_evidence(self, request: EvidenceRetrievalRequest) -> EvidenceRetrievalResult:
        return self.runtime.retrieve_evidence(request)



class GatewayContextCapability(ContextCapability):
    def __init__(
        self,
        profile: LoadedProfile,
        *,
        total_tokens: int = 3072,
        skill_prompt_context: SkillPromptContextBuilder | None = None,
        profile_loader: ProfileLoader | None = None,
        repository: RuntimeStorageRepository | None = None,
        epoch_store: EpochStore | None = None,
        install_root: Path | None = None,
    ) -> None:
        self.default_profile = profile
        self.profile_loader = profile_loader
        self.repository = repository
        self.epoch_store = epoch_store
        self.install_root = install_root
        self.total_tokens = total_tokens
        self._last_session_id: str | None = None
        # Prompt contract is rebuilt per-turn in `assemble` so that the session's
        # bound identity (elephant/state) flows into sections like "Who you are" and
        # "Your own voice". The default here is only a fallback for adapters
        # that don't carry a session-level personal_model_id yet.
        self.prompt_contract = build_prompt_contract(profile, prompt_mode="full")
        self.descriptor = CapabilityDescriptor(
            capability_id="gateway.context",
            kind="context",
            version="1.0.0",
            metadata={"description": "Prompt-contract-aware context adapter for gateway turns."},
        )
        self.runtime = ContextRuntime(
            instruction_refs=self.prompt_contract.instruction_refs,
            total_tokens=total_tokens,
        )
        self.skill_prompt_context = skill_prompt_context

    def _load_profile_for_session(self, session: Episode) -> LoadedProfile:
        """Resolve the runtime profile for this session's bound elephant.

        Reads identity + user + companion settings straight off the canonical
        State row (and its persisted canonical records) so the prompt reflects
        the bound elephant — not a startup-time stub.
        """
        if self.repository is None:
            return self._with_authored_identity(self.default_profile, session)
        try:
            elephant_id = elephant_id_from_session(session)
            loaded = load_runtime_profile(
                self.repository,
                personal_model_id=getattr(session, "personal_model_id", None),
                elephant_id=elephant_id or None,
                profile_loader=self.profile_loader,
            )
            return self._with_authored_identity(loaded, session)
        except Exception:
            return self._with_authored_identity(self.default_profile, session)

    def _with_authored_identity(self, loaded: LoadedProfile, session: Episode) -> LoadedProfile:
        elephant_id = elephant_id_from_session(session)
        if not elephant_id or self.install_root is None:
            return loaded
        return profile_with_authored_elephant_identity(
            loaded,
            elephant_file_path(elephant_id, install_root=self.install_root),
        )

    def assemble(
        self,
        session: Episode,
        work_items: tuple[object, ...],
        recall_items: tuple[RecallEvidence, ...],
        *,
        state_focus: StateFocusDecision | None = None,
    ) -> ContextBundle:
        loaded = self._load_profile_for_session(session)
        prompt_contract = build_prompt_contract(loaded, prompt_mode="full")
        runtime = ContextRuntime(
            instruction_refs=prompt_contract.instruction_refs,
            total_tokens=self.total_tokens,
        )
        if self.skill_prompt_context is not None:
            skill_lines = self.skill_prompt_context.stable_prefix_lines(session)
            if skill_lines:
                runtime = ContextRuntime(
                    instruction_refs=(*runtime.instruction_refs, *skill_lines),
                    total_tokens=runtime.total_tokens,
                )
        self._last_session_id = session.episode_id
        bundle = runtime.assemble(session, work_items, recall_items, state_focus=state_focus)
        bundle = replace(
            bundle,
            bundle_id=f"bundle:{session.episode_id}:{len(work_items)}:{len(recall_items)}",
            instruction_refs=runtime.instruction_refs,
        )
        epoch = (
            self.epoch_store.load(session.episode_id)
            if self.epoch_store is not None
            else None
        )
        return apply_session_context_epoch(bundle, epoch)

    def force_projection_compaction(
        self,
        *,
        reason: str = "provider-overflow",
        session_id: str | None = None,
    ):
        """Safety-net compaction for provider overflow retries.

        Uses the deterministic compactor (no LLM call) since this
        runs in the kernel hot path during error recovery.
        """
        resolved_session_id = session_id or self._last_session_id
        if self.epoch_store is None or not resolved_session_id:
            return None
        epoch = self.epoch_store.load(resolved_session_id)
        if epoch is None or not epoch.frozen:
            return None
        result = compress_epoch(
            epoch,
            context_limit=self.total_tokens,
            usage_tokens=self.total_tokens,
            reflect_compressor=None,
        )
        if result is None:
            return None
        updated, compress_result = result
        self.epoch_store.save(updated)
        return compress_result

    def flush_projection_cache(self) -> None:
        return None

class GatewayPreviewModelProvider(ModelProviderCapability):
    def __init__(self) -> None:
        self.descriptor = CapabilityDescriptor(
            capability_id="gateway.model.preview",
            kind="model_provider",
            version="1.0.0",
            metadata={"description": "Deterministic conversational fallback for gateway turns."},
        )

    def selection_state(self) -> RuntimeModelChoice:
        return RuntimeModelChoice(
            strong_model=GenerationModelProfile(
                profile_id="gateway-preview:strong",
                provider_id="gateway-preview",
                model_id="gateway-preview-strong",
            ),
            weak_model=SupportModelProfile(
                profile_id="gateway-preview:weak",
                provider_id="gateway-preview",
                model_id="gateway-preview-weak",
            ),
            state_focus_mode="skip",
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
        summary = "Gateway model provider is not configured; configure a model provider before chatting through IM."
        return ExecutionResult(
            execution_id=f"gateway.model:{session.episode_id}:{uuid4().hex}",
            episode_id=session.episode_id,
            outcome="ok",
            summary=summary,
            side_effects=("gateway-preview-provider", profile.mode, f"model_role={model_role}"),
        )

class GatewaySurfaceModelProvider(ModelProviderCapability):
    def __init__(
        self,
        *,
        repository: RuntimeStorageRepository,
        fallback: ModelProviderCapability,
        active_provider_profile: AuthProfile | None,
        runtime_environ: Mapping[str, str] | None = None,
        credential_resolver: CredentialResolver | None = None,
        tool_runtime: ToolRuntime | None = None,
        semantic_index_bundle: Any = None,
        embedding_service: Any = None,
        skill_runtime: Any = None,
        profile_loader: Any = None,
    ) -> None:
        if credential_resolver is None and runtime_environ is not None:
            credential_resolver = ProfileCredentialResolver(EnvironmentSecretStore(runtime_environ))
        profile_id = active_provider_profile.profile_id if active_provider_profile is not None else None
        provider_id = active_provider_profile.provider_id if active_provider_profile is not None else None
        self.surface = SurfaceModelProviderCapability(
            repository=repository,
            secret_key_path=repository.database_path.parent / "provider-secrets.key",
            fallback=fallback,
            credential_resolver=credential_resolver,
            active_provider_profile_id=profile_id,
            active_provider_id=provider_id,
            capability_id="gateway.model.runtime",
            surface_label="gateway",
            bootstrap_state_dir=repository.database_path.parent,
            tool_runtime=tool_runtime,
        )
        self.descriptor = self.surface.descriptor
        self.fallback = fallback

    def describe(self) -> Mapping[str, object]:
        return self.surface.describe()

    def selection_state(self) -> RuntimeModelChoice:
        return self.surface.selection_state()

    def turn_scoped_recall_blocks(
        self,
        *,
        profile: PersonalModelRuntimeState,
        session: Episode,
        context: ContextBundle,
        prompt: str,
    ) -> tuple[str, ...]:
        return self.surface.turn_scoped_recall_blocks(
            profile=profile,
            session=session,
            context=context,
            prompt=prompt,
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
            return self.surface.generate(
                profile=profile,
                session=session,
                context=context,
                prompt=prompt,
                model_role=model_role,
            )
        except LookupError:
            return self.fallback.generate(
                profile=profile,
                session=session,
                context=context,
                prompt=prompt,
                model_role=model_role,
            )
