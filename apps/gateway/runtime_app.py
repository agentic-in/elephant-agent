"""Gateway runtime application."""


from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
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
    next_session_context_epoch,
)
from packages.context.epoch_store import EpochStore, FileEpochStore
from packages.context.compress import compress_epoch
from packages.contracts.runtime import (
    ContextBundle,
    EventEnvelope,
    ExecutionResult,
    RecallEvidence,
    PersonalModelRuntimeState,
    PromptMessage,
)
from packages.contracts import Episode
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
    GatewayRouteState,
    GatewaySenderRef,
    InMemoryGatewayIdentityStore,
    InMemoryGatewaySessionStore,
)
from packages.kernel import KernelDependencies, KernelOutcome, KernelService, KernelSourceRequest, ReconciliationPipeline, StateReconciler
from packages.kernel.context_compaction import (
    flush_projection_cache,
)
from packages.evidence.recall_runtime import RecallRuntime
from packages.state import (
    DEFAULT_ELEPHANT_IDENTITY_TEXT,
    LoadedProfile,
    ProfileLoader,
    build_prompt_contract,
)
from packages.state.persistence import resolve_runtime_state
from packages.security.runtime import SecurityPolicy
from packages.skills import SkillRuntime
from packages.storage import RuntimeStorageRepository
from packages.tools import ToolRuntime
from .plugins import GatewayAdapterDescriptor, GatewayPluginRegistry


def _episode_status_from_route(status: str) -> str:
    normalized = str(status or "").strip()
    if normalized in ("paused", "interrupted"):
        return "paused"
    if normalized == "closed":
        return "closed"
    return "open"

CHAT_BOT_ADAPTER_ID = "messaging.chat-bot"
WEBHOOK_ADAPTER_ID = "messaging.webhook"
TELEGRAM_ADAPTER_ID = "messaging.telegram"
FEISHU_ADAPTER_ID = "messaging.feishu"
DISCORD_ADAPTER_ID = "messaging.discord"

from .runtime_support import *  # noqa: F401,F403
from .runtime_capabilities import GatewayContextCapability, GatewayRecallCapability, GatewayPreviewModelProvider, GatewaySurfaceModelProvider, GatewayTelemetrySink

def _aware_gateway_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _ack_pending_gateway_proactive_questions(
    repository,
    *,
    personal_model_id: str,
    episode_id: str,
    responded_at: datetime,
) -> None:
    list_open = getattr(repository, "list_open_questions", None)
    mark = getattr(repository, "mark_open_question", None)
    if not callable(list_open) or not callable(mark):
        return
    current = _aware_gateway_utc(responded_at)
    try:
        questions = list_open(
            personal_model_id=personal_model_id,
            status="asked",
            limit=128,
        )
    except Exception:
        return
    for question in questions:
        asked_at = getattr(question, "last_asked_at", None)
        if isinstance(asked_at, datetime) and _aware_gateway_utc(asked_at) > current:
            continue
        mark(
            question_id=question.question_id,
            status="answered",
            surface="gateway_user_response",
            now=current,
            user_response_episode_id=episode_id,
        )


@dataclass(frozen=True, slots=True)
class GatewayApp:
    core: GatewayCoreService
    profile_id: str
    provider_runtime: Mapping[str, object]
    repository: RuntimeStorageRepository
    auth_store: PersistentAuthProfileStore
    recall_runtime: RecallRuntime
    kernel: KernelService
    telemetry: GatewayTelemetrySink
    model_provider: GatewaySurfaceModelProvider
    tool_runtime: ToolRuntime | None = None
    skill_runtime: SkillRuntime | None = None
    plugin_registry: GatewayPluginRegistry | None = None
    state_dir: str | None = None
    epoch_store: EpochStore | None = None
    loaded_profile: LoadedProfile | None = None
    provider_profile: AuthProfile | None = None

    def handle_message(
        self,
        inbound: GatewayInboundMessage,
        *,
        reply_body: str | None = None,
        reply_to_message_id: str | None = None,
        attachment_refs: tuple[GatewayAttachmentRef, ...] = (),
        metadata: Mapping[str, object] | None = None,
        target_trusted: bool | None = None,
        consent_given: bool | None = None,
        is_external: bool | None = None,
    ) -> GatewayExchange:
        """Process one inbound turn through the shared synchronous gateway runtime.

        This method intentionally does **not** provide same-conversation queueing or
        FIFO guarantees by itself. Adapters must apply any required inbound
        serialization before calling into ``GatewayApp`` (for example via
        ``packages.gateway_core.InboundSequencer``) so the runtime boundary stays
        explicit and reusable across transports.
        """
        route = self.core.route_inbound(
            inbound,
        )
        if route.identity.state_id is None:
            return self._reject_unbound_route(
                route,
                reply_to_message_id=reply_to_message_id,
                attachment_refs=attachment_refs,
                metadata=metadata,
                target_trusted=target_trusted,
                consent_given=consent_given,
                is_external=is_external,
        )
        session = self._ensure_runtime_session(route)
        event = self._event_for_inbound(inbound, episode_id=session.episode_id)
        outcome = self.kernel.run(
            KernelSourceRequest(
                route_id=session.episode_id,
                prompt=inbound.body,
                surface=event.source,
                source_event_type=event.event_type,
                source_payload=dict(event.payload),
                source_event_id=event.event_id,
                route_status=_episode_status_from_route(session.status),
                route_interruption_state=session.interruption_state,
                route_started_at=session.started_at,
                state_id=route.identity.state_id,
                personal_model_id=session.personal_model_id,
                episode_id=session.episode_id,
                episode_policy="gateway_pinned",
            )
        )
        self._reconcile_turn(outcome)
        _ack_pending_gateway_proactive_questions(
            self.repository,
            personal_model_id=session.personal_model_id,
            episode_id=session.episode_id,
            responded_at=route.inbound.received_at or datetime.now(timezone.utc),
        )
        self._record_context_epoch(session, outcome)
        self._run_context_hygiene(session.episode_id, event_id=event.event_id, outcome=outcome)
        refreshed_session = self.repository.load_episode_state(session.episode_id) or session
        refreshed_route = self._route_state_from_runtime_session(
            refreshed_session,
            fallback=route.session,
        )
        self.core.dependencies.session_store.save(refreshed_route)
        route = replace(route, session=refreshed_route)
        route = self.core.record_turn_outcome(
            route,
            state_id=outcome.state.state_id,
            elephant_id=outcome.state.elephant_id or route.identity.elephant_id,
            episode_id=outcome.episode.episode_id,
        )
        provider_summary = self.model_provider.describe()
        delivery = self.core.deliver(
            route,
            body=reply_body or outcome.execution.summary,
            reply_to_message_id=reply_to_message_id
            or inbound.reply_to_message_id
            or inbound.event_id,
            attachment_refs=attachment_refs,
            metadata={
                **dict(metadata or {}),
                "runtime_surface": "gateway.shared-runtime",
                "context_bundle_id": outcome.context.bundle_id,
                "execution_id": outcome.execution.execution_id,
                "provider_id": str(provider_summary.get("provider_id") or "preview"),
            },
            target_trusted=target_trusted,
            consent_given=consent_given,
            is_external=is_external,
        )
        return GatewayExchange(route=route, delivery=delivery)

    def run_idle_proactive_turn(
        self,
        *,
        record: GatewayIdentityRecord,
        route_session: GatewayRouteState,
        now: datetime | None = None,
    ) -> KernelOutcome:
        """Run an idle proactive IM turn through the normal gateway kernel path."""
        del now
        session = self._ensure_runtime_session_for_identity(record, route_session)
        prompt = _idle_proactive_prompt()
        event_id = f"gateway-idle-proactive:{uuid4().hex}"
        outcome = self.kernel.run(
            KernelSourceRequest(
                route_id=session.episode_id,
                prompt=prompt,
                surface=f"gateway:{record.key.adapter_id}",
                source_event_type="turn.internal",
                source_payload={
                    "message": "idle proactive curiosity turn",
                    "summary": "idle proactive curiosity turn",
                    "content": prompt,
                    "adapter_id": record.key.adapter_id,
                    "account_id": record.key.account_id,
                    "conversation_id": record.key.conversation_id,
                    "state_id": record.state_id or "",
                    "elephant_id": record.elephant_id or "",
                    "allow_embeddings": "false",
                },
                source_event_id=event_id,
                route_status=_episode_status_from_route(session.status),
                route_interruption_state=session.interruption_state,
                route_started_at=session.started_at,
                state_id=record.state_id,
                personal_model_id=session.personal_model_id,
                episode_id=session.episode_id,
                episode_policy="gateway_pinned",
            )
        )
        refreshed_session = self.repository.load_episode_state(session.episode_id) or session
        refreshed_route = self._route_state_from_runtime_session(
            refreshed_session,
            fallback=route_session,
        )
        refreshed_route = replace(refreshed_route, updated_at=route_session.updated_at)
        self.core.dependencies.session_store.save(refreshed_route)
        return outcome

    def _reject_unbound_route(
        self,
        route,
        *,
        reply_to_message_id: str | None = None,
        attachment_refs: tuple[GatewayAttachmentRef, ...] = (),
        metadata: Mapping[str, object] | None = None,
        target_trusted: bool | None = None,
        consent_given: bool | None = None,
        is_external: bool | None = None,
    ) -> GatewayExchange:
        guidance = (
            "This conversation is not bound to an Elephant Agent elephant yet.\n"
            "Use `/elephant list` to see available herd, then `/elephant create <name>` "
            "to bind this conversation before sending plain text."
        )
        delivery = self.core.deliver(
            route,
            body=guidance,
            reply_to_message_id=reply_to_message_id
            or route.inbound.reply_to_message_id
            or route.inbound.event_id,
            attachment_refs=attachment_refs,
            metadata={
                **dict(metadata or {}),
                "runtime_surface": "gateway.elephant-binding-required",
            },
            target_trusted=target_trusted,
            consent_given=consent_given,
            is_external=is_external,
        )
        return GatewayExchange(route=route, delivery=delivery)

    def record_idle_proactive_delivery(
        self,
        *,
        record: GatewayIdentityRecord,
        route_session: GatewayRouteState,
        body: str,
    ) -> None:
        session = self._ensure_runtime_session_for_identity(record, route_session)
        existing = self.epoch_store.load(session.episode_id) if self.epoch_store is not None else None
        text = body.strip()
        if existing is None or not existing.frozen or not text:
            return
        epoch = replace(
            existing,
            history_messages=(
                *existing.history_messages,
                PromptMessage(
                    role="assistant",
                    content=text,
                    metadata={
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "source": "gateway:idle-proactive",
                        "projection_surface": "im",
                    },
                ),
            ),
        )
        self.epoch_store.save(epoch)

    def _record_context_epoch(self, session: Episode, outcome: KernelOutcome) -> None:
        existing = self.epoch_store.load(session.episode_id) if self.epoch_store is not None else None
        epoch = next_session_context_epoch(
            existing,
            session=session,
            event=outcome.event,
            execution=outcome.execution,
            context=outcome.context,
            turn_messages=outcome.turn_messages,
            thread_focus=outcome.state.summary,
        )
        if epoch != existing and self.epoch_store is not None:
            self.epoch_store.save(epoch)

    def _run_context_hygiene(self, session_id: str, *, event_id: str, outcome: KernelOutcome | None = None) -> None:
        execution = outcome.execution if outcome is not None else None
        usage_tokens = max(int(getattr(execution, "prompt_tokens", 0) or 0), int(getattr(execution, "total_tokens", 0) or 0))
        context_limit = int(getattr(outcome.context, "token_budget", 0) or 0) if outcome is not None else 0
        if self.epoch_store is None:
            return
        epoch = self.epoch_store.load(session_id)
        if epoch is None:
            return
        result = compress_epoch(
            epoch,
            context_limit=context_limit,
            usage_tokens=usage_tokens,
            reflect_compressor=self._llm_compress,
            session_id=session_id,
        )
        if result is None:
            return
        updated, compress_result = result
        self.epoch_store.save(updated)
        # Persist to episode for dashboard visibility
        try:
            with self.repository.connection() as connection:
                connection.execute("UPDATE episodes SET exit_summary = ? WHERE episode_id = ?", (compress_result.summary, session_id))
                connection.commit()
        except Exception:
            pass
        self.telemetry.emit({
            "event_id": f"telemetry:{session_id}:context-compact:{uuid4().hex}",
            "event_type": "kernel.stage",
            "session_id": session_id,
            "source": "gateway",
            "payload": {"stage": "context-compact", "detail": f"method={compress_result.method} messages={compress_result.before_messages}->{compress_result.after_messages}", "recorded_at": datetime.now(timezone.utc).isoformat(), "event_id": event_id},
        })
        flush_projection_cache(self.kernel.dependencies.context)

    def _llm_compress(
        self,
        to_summarize: tuple[PromptMessage, ...],
        tail: tuple[PromptMessage, ...],
        *,
        session_id: str,
        context_limit: int,
    ) -> str:
        """LLM-based context compression via direct model adapter call."""
        from packages.models import build_model_adapter, ModelRequest

        # Build concise conversation text — skip tool results, summarize tool calls
        lines: list[str] = []
        pending_tools: list[str] = []
        for msg in to_summarize:
            role = msg.role or "system"
            content = (msg.content or "").strip()
            if role == "tool":
                continue  # Skip tool results
            if role == "assistant" and msg.tool_calls and not content:
                for call in (msg.tool_calls or ()):
                    pending_tools.append(call.get("name") or call.get("tool_name") or "tool")
                continue
            if pending_tools:
                lines.append(f"[used {len(pending_tools)} tools: {', '.join(dict.fromkeys(pending_tools))}]")
                pending_tools = []
            if content:
                if role == "user":
                    lines.append(f"user: {content[:500]}")
                elif role == "assistant":
                    lines.append(f"assistant: {content[:400]}")
        if pending_tools:
            lines.append(f"[used {len(pending_tools)} tools: {', '.join(dict.fromkeys(pending_tools))}]")

        conversation_text = "\n".join(lines)
        token_budget = max(200, context_limit // 8)

        system_prompt = (
            "You are a context compression assistant. Produce a concise reference summary "
            "of the conversation below. Preserve: (a) key topics and decisions, "
            "(b) user-stated facts or preferences, (c) current task state for handoff. "
            f"Stay within ~{token_budget} tokens. Output the summary only, no commentary."
        )

        try:
            active_profile = self.model_provider.active_profile()
            if active_profile is None:
                return ""
            resolution = self.model_provider.surface.runtime_resolver.resolve(
                active_profile.provider_id,
                model_id=active_profile.default_model or None,
                base_url=active_profile.base_url,
            )
            credentials = self.model_provider.surface.credential_resolver.resolve(active_profile).as_mapping()
            adapter = build_model_adapter(
                resolution,
                credentials=credentials,
            )
            request = ModelRequest(
                request_id=f"compress:{session_id}:{uuid4().hex[:8]}",
                profile_id="compress",
                session_id=session_id,
                provider_id=active_profile.provider_id,
                model_id=active_profile.default_model or "",
                prompt=f"Summarize this conversation:\n\n{conversation_text}",
                messages=(
                    PromptMessage(role="system", content=system_prompt),
                    PromptMessage(role="user", content=f"Summarize this conversation:\n\n{conversation_text}"),
                ),
                tools=(),
                metadata={"source": "gateway-compress"},
            )
            result = adapter.execute(request)
            return (result.summary or "").strip()
        except Exception:
            return ""

    def _reconcile_turn(self, outcome: KernelOutcome) -> None:
        decision_summary = _decision_summary_from_outcome(outcome)
        observed_event = replace(
            outcome.event,
            payload=_payload_with_turn_reasoning(
                outcome.event.payload,
                outcome,
                decision_summary=decision_summary,
            ),
        )
        observation = ReconciliationPipeline().observe_turn(
            inbound_event=observed_event,
            execution=outcome.execution,
            decision_summary=decision_summary,
            include_input_event=True,
            include_outcome_event=True,
            source=observed_event.source,
            profile_id=outcome.personal_model.personal_model_id,
            elephant_id=outcome.state.elephant_id,
            turn_messages=outcome.turn_messages,
        )
        StateReconciler().reconcile_turn(
            repository=self.repository,
            recall_runtime=self.recall_runtime,
            observation=observation,
        )

    def provider_summary(self) -> Mapping[str, object]:
        return dict(self.model_provider.describe())

    def setup_summary(self) -> Mapping[str, object]:
        if self.plugin_registry is not None:
            registry = self.plugin_registry
        else:
            from .runtime_factory import register_builtin_gateway_adapters

            registry = register_builtin_gateway_adapters(GatewayPluginRegistry())
        return {
            "profile_id": self.profile_id,
            "state_dir": self.state_dir,
            "adapters": registry.adapter_id_map(),
            "adapter_setup": registry.adapter_setup_payload(),
            "provider": dict(self.model_provider.describe()),
        }

    def identity_records(self) -> tuple[GatewayIdentityRecord, ...]:
        return self.core.dependencies.identity_store.list_records()

    def session_records(self) -> tuple[GatewayRouteState, ...]:
        return self.core.dependencies.session_store.list_records()

    def recall_evidence_records(self, session_id: str | None = None) -> tuple[RecallEvidence, ...]:
        return self.recall_runtime.store.list(episode_id=session_id)

    def interrupt_episode(
        self,
        episode_id: str,
        *,
        interruption_state: str,
        interrupted_at: datetime | None = None,
    ) -> GatewayRouteState:
        session = self.core.dependencies.session_store.lookup(episode_id)
        if session is None:
            raise KeyError(episode_id)
        updated = replace(
            session,
            status="interrupted",
            interruption_state=interruption_state,
            updated_at=interrupted_at or _utc_now(),
        )
        self.core.dependencies.session_store.save(updated)
        existing_runtime = self.repository.load_episode_state(episode_id)
        if existing_runtime is not None:
            self.repository.upsert_episode_state(
                replace(
                    existing_runtime,
                    status=_episode_status_from_route(updated.status),
                    updated_at=updated.updated_at,
                    interruption_state=updated.interruption_state,
                )
            )
        else:
            self.repository.upsert_episode_state(self._runtime_session_from_route(updated))
        return updated

    def _ensure_runtime_session(self, route) -> Episode:
        """Ensure runtime session with correct personal_model_id from state.
        
        When we have a state_id (identity/companion), load it directly to extract
        the correct personal_model_id (which links the identity back to its user).
        This ensures that if the gateway route was created with an identity,
        we use the authoritative state.personal_model_id, not a potentially stale
        or incorrect session.profile_id value.
        
        This fixes the IM mode system prompt injection bug where Zoey (the identity)
        was being shown as the user's name because personal_model_id was incorrectly
        set to the state_id instead of the user's personal_model_id.
        """
        session = route.session
        identity = route.identity
        runtime_episode_id = identity.episode_id or session.session_id
        
        # When we have a state_id (bound identity/elephant), load the State directly
        # to get the authoritative personal_model_id (which links the identity to its user).
        # This ensures personal_model_id is never confused with state_id or elephant_id.
        resolved_state = None
        if identity.state_id:
            resolved_state = self.repository.load_state(identity.state_id)
        
        # Fallback to resolve_runtime_state if direct load didn't work
        if resolved_state is None:
            resolved_state = resolve_runtime_state(
                self.repository,
                state_id=identity.state_id,
                episode_id=runtime_episode_id,
                personal_model_id=(session.profile_id if session.profile_id != self.profile_id else None),
                elephant_id=identity.elephant_id,
                required=False,
            )
        
        existing = self.repository.load_episode_state(runtime_episode_id)
        idle_gap_seconds = max(0.0, (session.updated_at - existing.updated_at).total_seconds()) if existing is not None else 0.0
        if idle_gap_seconds > 1800:
            self._clear_idle_context_epoch(
                runtime_episode_id,
                personal_model_id=(existing.personal_model_id if existing is not None else session.profile_id),
                state_id=identity.state_id,
            )
        resolved_personal_model_id = (
            resolved_state.personal_model_id
            if resolved_state is not None and resolved_state.personal_model_id
            else None
        )
        resolved_elephant_id = (
            resolved_state.elephant_id
            if resolved_state is not None and resolved_state.elephant_id
            else identity.elephant_id
        )
        resolved = Episode(
            episode_id=runtime_episode_id,
            state_id=identity.state_id or "unresolved",
            personal_model_id=resolved_personal_model_id
            or (existing.personal_model_id if existing is not None and existing.personal_model_id else None)
            or session.profile_id,
            entry_surface="gateway",
            elephant_id=resolved_elephant_id
            or (existing.elephant_id if existing is not None and existing.elephant_id else "")
            or "",
            status=_episode_status_from_route(session.status),
            started_at=existing.started_at if existing is not None else session.started_at,
            updated_at=session.updated_at,
            parent_episode_id=existing.parent_episode_id if existing is not None else None,
            interruption_state=session.interruption_state,
        )
        self.repository.upsert_episode_state(resolved)
        return resolved

    def _clear_idle_context_epoch(
        self,
        episode_id: str,
        *,
        personal_model_id: str | None,
        state_id: str | None,
    ) -> None:
        if self.epoch_store is None:
            return
        epoch = self.epoch_store.load(episode_id)
        if epoch is None or not epoch.frozen or (not epoch.history_messages and not epoch.compacted_history_summary):
            return
        self.epoch_store.save(
            replace(epoch, history_messages=(), compacted_history_summary=""),
        )

    def _runtime_session_from_route(self, session: GatewayRouteState) -> Episode:
        return Episode(
            episode_id=session.session_id,
            state_id="unresolved",
            personal_model_id=session.profile_id,
            entry_surface="gateway",
            elephant_id="",
            status=_episode_status_from_route(session.status),
            started_at=session.started_at,
            updated_at=session.updated_at,
            interruption_state=session.interruption_state,
        )

    def _ensure_runtime_session_for_identity(
        self,
        record: GatewayIdentityRecord,
        route_session: GatewayRouteState,
    ) -> Episode:
        runtime_episode_id = record.episode_id or route_session.session_id
        existing = self.repository.load_episode_state(runtime_episode_id)
        resolved_state = self.repository.load_state(record.state_id) if record.state_id else None
        session = Episode(
            episode_id=runtime_episode_id,
            state_id=record.state_id or "unresolved",
            personal_model_id=(
                getattr(resolved_state, "personal_model_id", None)
                or (existing.personal_model_id if existing is not None else None)
                or route_session.profile_id
            ),
            entry_surface="gateway",
            elephant_id=(
                getattr(resolved_state, "elephant_id", None)
                or record.elephant_id
                or (existing.elephant_id if existing is not None else None)
                or ""
            ),
            status=_episode_status_from_route(route_session.status),
            started_at=existing.started_at if existing is not None else route_session.started_at,
            updated_at=route_session.updated_at,
            parent_episode_id=existing.parent_episode_id if existing is not None else None,
            interruption_state=route_session.interruption_state,
        )
        self.repository.upsert_episode_state(session)
        return session

    def _route_state_from_runtime_session(
        self,
        session: Episode,
        *,
        fallback: GatewayRouteState,
    ) -> GatewayRouteState:
        return GatewayRouteState(
            session_id=session.episode_id,
            profile_id=session.personal_model_id or fallback.profile_id,
            status=session.status,
            started_at=session.started_at,
            updated_at=session.updated_at,
            interruption_state=session.interruption_state,
        )

    def _event_for_inbound(
        self,
        inbound: GatewayInboundMessage,
        *,
        episode_id: str,
    ) -> EventEnvelope:
        payload = {
            "message": inbound.body,
            "content": inbound.body,
            "summary": inbound.body,
            "adapter_id": inbound.adapter_id,
            "account_id": inbound.account_id,
            "delivery_surface": inbound.account.surface or "",
            "conversation_id": inbound.conversation_id,
            "parent_conversation_id": inbound.parent_conversation_id or "",
            "thread_id": inbound.thread_id or "",
            "chat_type": inbound.chat_type or "",
            "external_user_id": inbound.external_user_id,
            "display_name": inbound.display_name or "",
            "attachments": ",".join(inbound.attachments),
            **_string_payload(inbound.metadata),
        }
        return EventEnvelope(
            event_id=f"gateway:{inbound.event_id}",
            event_type="turn.received",
            episode_id=episode_id,
            source=f"gateway:{inbound.adapter_id}",
            payload=payload,
        )


def _idle_proactive_prompt() -> str:
    return "\n".join(
        (
            "[SYSTEM: This turn is running as an idle proactive IM check-in.]",
            "Use the same Elephant Agent identity, voice, tools, and Personal Model context that you use in this IM chat.",
            "Before asking anything, call tool.personal_model.questions with action=list and status=open to inspect the current question queue.",
            "If you choose to ask one, call tool.personal_model.questions with action=ask for that exact question_id before your final response.",
            "Only send a final question after action=ask succeeds; if you do not mark a question asked through the tool, respond with exactly [SILENT].",
            "You may create/update/dismiss/delete questions with tool.personal_model.questions when the current queue is stale, duplicated, or misaligned with the Personal Model.",
            "If there is no useful, respectful question to ask now, respond with exactly [SILENT]; do not explain why no question fit.",
            "Do not mention cron, automation, system prompts, question banks, candidate ids, lenses, tool calls, suitability evaluations, or internal reasoning.",
            "Do not use a fixed opener like 'I have a small question' or '有个小问题'. Phrase it naturally for this user.",
            "Ask only one question. Keep it concise. Follow the user's language and style preferences.",
        )
    ).strip()


def _compact_runtime_text(text: str, *, limit: int = 220) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3].rstrip()}..."


def _decision_summary_from_outcome(outcome: KernelOutcome) -> str:
    if outcome.state.summary.strip():
        return outcome.state.summary.strip()
    return outcome.execution.summary.strip()


def _payload_with_turn_reasoning(
    payload: Mapping[str, object],
    outcome: KernelOutcome,
    *,
    decision_summary: str,
) -> dict[str, str]:
    enriched = {str(key): str(value) for key, value in dict(payload).items()}
    reasoning_trace = outcome.execution.reasoning.strip()
    summary = decision_summary.strip()
    if reasoning_trace:
        enriched.setdefault("reasoning_trace", reasoning_trace)
        enriched.setdefault("raw_reasoning_trace", reasoning_trace)
        enriched.setdefault("reasoning_summary", _compact_runtime_text(reasoning_trace))
        enriched.setdefault("reasoning_provenance", "provider.raw_trace")
        return enriched
    if summary:
        enriched.setdefault("reasoning_summary", summary)
        enriched.setdefault("reasoning_provenance", "runtime.decision_summary")
    return enriched
