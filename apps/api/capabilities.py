"""API capability adapters and deterministic preview providers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import logging
from pathlib import Path
from threading import Lock
from typing import Any, Callable
from uuid import uuid4

from packages.capabilities.runtime import (
    CapabilityDescriptor,
    ContextCapability,
    DeliveryAdapterCapability,
    RecallCapability,
    ModelProviderCapability,
    TelemetrySinkCapability,
    ToolCapability,
)
from packages.context import (
    ContextRuntime,
    apply_session_context_epoch,
)
from packages.context.epoch_store import FileEpochStore
from packages.context.compress import compress_epoch
from packages.contracts import (
    ContextBundle,
    Episode,
    ExecutionResult,
)
from packages.contracts.runtime import (
    EvidenceRetrievalRequest,
    EvidenceRetrievalResult,
    RecallEvidence,
    StateFocusDecision,
    PersonalModelRuntimeState,
)
from packages.evidence import RecallRuntime
from packages.runtime_layout import elephant_file_path
from packages.state import (
    ProfileLoader,
    build_prompt_contract,
    elephant_id_from_session,
    load_runtime_profile,
    profile_with_authored_elephant_identity,
)
from packages.storage import RuntimeStorageRepository
from packages.skills import SkillPromptContextBuilder
from packages.tools import ToolRuntime


LOGGER = logging.getLogger(__name__)


def _agent_runtime_prefix_lines(
    repository: RuntimeStorageRepository | None,
    session: Episode,
) -> tuple[str, ...]:
    if repository is None:
        return ()
    try:
        state = repository.load_state(session.state_id)
    except Exception:
        return ()
    if state is None:
        return ()
    metadata = dict(getattr(state, "metadata", {}) or {})
    fields = {
        "role": str(metadata.get("role_title") or "").strip(),
        "runtime": str(metadata.get("runtime_id") or "").strip(),
        "engine": str(metadata.get("engine_id") or "").strip(),
        "provider": str(metadata.get("provider_id") or "").strip(),
        "model": str(metadata.get("provider_model") or "").strip(),
        "tools": str(metadata.get("tool_ids") or "").strip(),
        "skills": str(metadata.get("skill_ids") or "").strip(),
    }
    role_prompt = str(metadata.get("role_prompt") or metadata.get("instruction") or "").strip()
    if not any(fields.values()) and not role_prompt:
        return ()
    lines = [
        "# Agent Runtime Binding",
        "This episode is running as a configured Elephant agent. Keep this binding stable across the episode.",
    ]
    if fields["role"]:
        lines.append(f"- role: {fields['role']}")
    runtime_parts = [part for part in (fields["runtime"], fields["engine"], fields["provider"], fields["model"]) if part]
    if runtime_parts:
        lines.append("- engine: " + " / ".join(runtime_parts))
    if fields["tools"]:
        lines.append(f"- allowed tools: {fields['tools']}")
    if fields["skills"]:
        lines.append(f"- assigned skills: {fields['skills']}")
    if role_prompt:
        lines.extend(("- instruction:", role_prompt))
    return tuple(lines)


class APITelemetrySink(TelemetrySinkCapability):
    def __init__(self) -> None:
        self.descriptor = CapabilityDescriptor(
            capability_id="api.telemetry",
            kind="telemetry_sink",
            version="1.0.0",
            metadata={"description": "In-process telemetry sink for API wiring."},
        )
        self._events: list[dict[str, Any]] = []
        self._observers: list[Callable[[Mapping[str, Any]], None]] = []
        self._observer_lock = Lock()

    @property
    def events(self) -> tuple[dict[str, Any], ...]:
        with self._observer_lock:
            return tuple(self._events)

    def subscribe(self, observer: Callable[[Mapping[str, Any]], None]) -> Callable[[], None]:
        with self._observer_lock:
            self._observers.append(observer)

        def _unsubscribe() -> None:
            with self._observer_lock:
                if observer in self._observers:
                    self._observers.remove(observer)

        return _unsubscribe

    def emit(self, event: Mapping[str, Any]) -> None:
        record = dict(event)
        with self._observer_lock:
            self._events.append(record)
            observers = tuple(self._observers)
        for observer in observers:
            try:
                observer(record)
            except Exception:
                LOGGER.warning("API telemetry observer failed", exc_info=True)
                continue


class APIRecallCapability(RecallCapability):
    def __init__(self, runtime: RecallRuntime) -> None:
        self.descriptor = CapabilityDescriptor(
            capability_id="api.recall",
            kind="recall",
            version="1.0.0",
            metadata={"description": "Evidence recall adapter for API-backed kernel flows."},
        )
        self.runtime = runtime

    def retrieve_evidence(self, request: EvidenceRetrievalRequest) -> EvidenceRetrievalResult:
        return self.runtime.retrieve_evidence(request)


class APIContextCapability(ContextCapability):
    def __init__(
        self,
        runtime: ContextRuntime,
        *,
        skill_prompt_context: SkillPromptContextBuilder | None = None,
        repository: RuntimeStorageRepository | None = None,
        profile_loader: ProfileLoader | None = None,
        install_root: Path | None = None,
    ) -> None:
        self.descriptor = CapabilityDescriptor(
            capability_id="api.context",
            kind="context",
            version="1.0.0",
            metadata={"description": "Layered context adapter for API flows."},
        )
        self.runtime = runtime
        self.skill_prompt_context = skill_prompt_context
        self.repository = repository
        self.profile_loader = profile_loader
        self.install_root = install_root
        self._last_session_id: str | None = None

    def _runtime_for_session(self, session: Episode) -> ContextRuntime:
        if self.repository is None:
            return self.runtime
        try:
            elephant_id = elephant_id_from_session(session)
            loaded = load_runtime_profile(
                self.repository,
                personal_model_id=getattr(session, "personal_model_id", None),
                elephant_id=elephant_id or None,
                profile_loader=self.profile_loader,
            )
            if elephant_id and self.install_root is not None:
                loaded = profile_with_authored_elephant_identity(
                    loaded,
                    elephant_file_path(elephant_id, install_root=self.install_root),
                )
            prompt_contract = build_prompt_contract(loaded, prompt_mode="full")
            return ContextRuntime(
                instruction_refs=prompt_contract.instruction_refs,
                total_tokens=self.runtime.total_tokens,
            )
        except Exception:
            LOGGER.warning("failed to build API context capability runtime", exc_info=True)
            return self.runtime

    def assemble(
        self,
        session: Episode,
        work_items: tuple[object, ...],
        recall_items: tuple[RecallEvidence, ...],
        *,
        state_focus: StateFocusDecision | None = None,
    ) -> ContextBundle:
        self._last_session_id = session.episode_id
        runtime = self._runtime_for_session(session)
        extra_prefix_lines: tuple[str, ...] = ()
        if self.skill_prompt_context is not None:
            skill_lines = self.skill_prompt_context.stable_prefix_lines(session)
            extra_prefix_lines = (*extra_prefix_lines, *skill_lines)
        extra_prefix_lines = (*extra_prefix_lines, *_agent_runtime_prefix_lines(self.repository, session))
        if extra_prefix_lines:
            runtime = ContextRuntime(
                instruction_refs=(*runtime.instruction_refs, *extra_prefix_lines),
                total_tokens=self.runtime.total_tokens,
            )
        bundle = runtime.assemble(session, work_items, recall_items, state_focus=state_focus)
        bundle = replace(bundle, instruction_refs=runtime.instruction_refs)
        _epoch_store = FileEpochStore(self.repository.database_path.parent) if self.repository is not None else None
        epoch = _epoch_store.load(session.episode_id) if _epoch_store is not None else None
        return apply_session_context_epoch(bundle, epoch)

    def force_projection_compaction(
        self,
        *,
        reason: str = "provider-overflow",
        session_id: str | None = None,
    ):
        resolved_session_id = session_id or self._last_session_id
        if self.repository is None or not resolved_session_id:
            return None
        _epoch_store = FileEpochStore(self.repository.database_path.parent)
        epoch = _epoch_store.load(resolved_session_id)
        if epoch is None or not epoch.frozen:
            return None
        result = compress_epoch(
            epoch,
            context_limit=self.runtime.total_tokens,
            usage_tokens=self.runtime.total_tokens,
            reflect_compressor=None,
        )
        if result is not None:
            updated, _compress_result = result
            _epoch_store.save(updated)
            return _compress_result
        return None

    def flush_projection_cache(self) -> None:
        return None


class APIDeliveryCapability(DeliveryAdapterCapability):
    def __init__(self) -> None:
        self.descriptor = CapabilityDescriptor(
            capability_id="api.delivery",
            kind="delivery",
            version="1.0.0",
            metadata={"description": "Delivery adapter for API controlled execution."},
        )

    def deliver(self, session_id: str, payload: Mapping[str, Any]) -> ExecutionResult:
        summary = str(payload.get("summary", "delivered response"))
        return ExecutionResult(
            execution_id=f"delivery:{session_id}:{uuid4().hex}",
            episode_id=session_id,
            outcome="ok",
            summary=summary,
            side_effects=("delivery",),
        )


class APIModelProvider(ModelProviderCapability):
    def __init__(self) -> None:
        self.descriptor = CapabilityDescriptor(
            capability_id="api.model",
            kind="model_provider",
            version="1.0.0",
            metadata={"description": "Deterministic model adapter for API flows."},
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
        summary = prompt.strip() or "acknowledged"
        if context.rendered_prompt:
            summary = f"{summary} | context: {context.rendered_prompt.splitlines()[0]}"
        return ExecutionResult(
            execution_id=f"model:{session.episode_id}:{uuid4().hex}",
            episode_id=session.episode_id,
            outcome="ok",
            summary=summary,
            side_effects=(profile.mode, f"model_role={model_role}"),
        )


class APIToolExecution(ToolCapability):
    def __init__(self, runtime: ToolRuntime) -> None:
        self.descriptor = CapabilityDescriptor(
            capability_id="api.tools",
            kind="tool",
            version="1.0.0",
            metadata={"description": "API tool runtime."},
        )
        self.runtime = runtime

    def invoke(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        *,
        session_id: str,
    ) -> ExecutionResult:
        return self.runtime.invoke(tool_name, arguments, session_id=session_id)
