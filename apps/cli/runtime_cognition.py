"""Context assembly, recall retrieval, and preview capabilities for the CLI runtime."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from .snapshot_io import load_snapshot_payload
from packages.capabilities.runtime import CapabilityDescriptor
from packages.context import (
    ContextAssemblyResult,
    ContextProjectionCompactionResult,
    ContextRuntime,
    apply_session_context_epoch,
    compact_session_context_epoch,
)
from packages.contracts.layers import Episode
from packages.contracts.runtime import (
    ContextBundle,
    EvidenceRetrievalRequest,
    ExecutionResult,
    StateFocusDecision,
    RecallEvidence,
    RuntimeModelChoice,
    PlanDraft,
    PersonalModelRuntimeState,
    EpisodeContinuityState,
    GenerationModelProfile,
    SupportModelProfile,
)
from packages.evidence import RecallRuntime
from packages.runtime_layout import elephant_file_path
from packages.state.rendered_views import RenderedRelationshipView
from packages.skills import SkillHub, SkillRuntime
from packages.state import (
    LoadedProfile,
    ProfileLoader,
    PromptMode,
    build_prompt_contract,
    elephant_id_from_session,
    load_runtime_profile,
    profile_with_authored_elephant_identity,
)
from packages.storage import RuntimeStorageRepository
from packages.tools import ToolRuntime

from .runtime_snapshot import (
    SessionContextEpoch,
    restore_snapshot_session_context_epoch,
    write_snapshot_session_context_epoch,
)
from packages.skills import SkillPromptContextBuilder
from .runtime_support import _restore_datetime, _utc_now


def _recall_query_seed(repository: RuntimeStorageRepository) -> str:
    state = repository.current_state()
    parts = tuple(
        part.strip()
        for part in (
            state.summary if state is not None else "",
            state.summary if state is not None else "",
        )
        if part and part.strip()
    )
    if not parts:
        return "resume continuity next step"
    return "resume continuity next step " + " | ".join(parts[:3])


def _recall_query_with_relationship(
    repository: RuntimeStorageRepository,
    *,
    relationship: RenderedRelationshipView | None,
) -> str:
    base = _recall_query_seed(repository)
    if relationship is None or not relationship.continuity_notes:
        return base
    note_seed = " | ".join(note for note in relationship.continuity_notes[:2] if note)
    if not note_seed:
        return base
    return f"{base} | relationship continuity {note_seed}"


def _recall_scope_session_ids(
    repository: RuntimeStorageRepository,
    session: Episode,
) -> tuple[str, ...]:
    lineage = repository.episode_lineage(session.episode_id)
    if not lineage:
        return (session.episode_id,)
    return tuple(dict.fromkeys(state.episode_id for state in lineage))


def _recall_scope_reason(
    *,
    session: Episode,
    relationship: RenderedRelationshipView | None,
    scope_session_ids: tuple[str, ...],
) -> str:
    reasons: list[str] = []
    if len(scope_session_ids) > 1:
        reasons.append("resume recovery spans the current session lineage")
    else:
        reasons.append("no parent lineage was available, so recovery stays in the active session")
    state = getattr(session, "elephant_id", None)
    if state:
        reasons.append("elephant continuity stays ahead of generic recall")
    if relationship is not None and relationship.continuity_notes:
        reasons.append("relationship continuity notes add continuity-sensitive recall cues")
    if session.interruption_state:
        reasons.append(f"session interruption state is {session.interruption_state}")
    return "; ".join(reasons)


def _list_scope_recall_evidence(
    repository: RuntimeStorageRepository,
    *,
    scope_session_ids: tuple[str, ...],
) -> tuple[RecallEvidence, ...]:
    scope_set = set(scope_session_ids)
    if not scope_set:
        return ()
    records: list[RecallEvidence] = []
    for step in repository.list_steps():
        if step.episode_id not in scope_set:
            continue
        content = "\n".join(part for part in (step.summary.strip(), step.outcome.strip()) if part) or step.action
        records.append(
            RecallEvidence(
                evidence_id=f"step:{step.step_id}",
                episode_id=step.episode_id,
                kind=step.action,
                content=content,
                source_id=step.step_id,
                source_kind="step",
                step_id=step.step_id,
                loop_id=step.loop_id,
                created_at=step.created_at,
                metadata=dict(step.metadata),
            )
        )
    records.sort(
        key=lambda record: (
            record.created_at if record.created_at is not None else datetime.min.replace(tzinfo=timezone.utc),
            record.evidence_id,
        )
    )
    return tuple(records)


def _load_snapshot_record(snapshot_path: Path | None) -> dict[str, Any] | None:
    if snapshot_path is None or not snapshot_path.exists():
        return None
    return load_snapshot_payload(snapshot_path)


def _recent_loop_context(snapshot_path: Path | None, *, session_id: str) -> tuple[str, ...]:
    snapshot = _load_snapshot_record(snapshot_path)
    if not snapshot:
        return ()
    session = snapshot.get("session")
    resolved_snapshot_session_id = (
        str(session.get("episode_id") or session.get("session_id") or "").strip()
        if isinstance(session, Mapping)
        else ""
    )
    if resolved_snapshot_session_id != session_id:
        return ()

    turns: list[str] = []
    event = snapshot.get("event")
    include_turn = _snapshot_event_is_user_turn(event)
    if include_turn and isinstance(event, Mapping):
        payload = event.get("payload")
        if isinstance(payload, Mapping):
            message = str(payload.get("message") or payload.get("content") or payload.get("summary") or "").strip()
            if message:
                turns.append(f"user: {message}")

    execution = snapshot.get("execution")
    if include_turn and isinstance(execution, Mapping):
        summary = str(execution.get("summary") or "").strip()
        if summary:
            turns.append(f"elephant: {summary}")

    delivery = snapshot.get("delivery")
    if include_turn and isinstance(delivery, Mapping):
        summary = str(delivery.get("summary") or "").strip()
        if summary:
            turns.append(f"delivery: {summary}")

    return tuple(turns[:4])


def _snapshot_event_is_user_turn(event: object) -> bool:
    if not isinstance(event, Mapping):
        return False
    source = str(event.get("source") or "").strip()
    if source == "cli.startup":
        return False
    event_type = str(event.get("event_type") or "").strip().lower()
    if not event_type:
        return True
    return event_type == "turn.received"


@dataclass(frozen=True, slots=True)
class _DurableRecallCapability:
    recall_runtime: RecallRuntime
    repository: RuntimeStorageRepository
    descriptor: CapabilityDescriptor = CapabilityDescriptor(
        capability_id="cli.recall.runtime",
        kind="recall",
        version="1.0.0",
        metadata={"description": "Repo-backed evidence recall adapter for CLI kernel flows."},
    )

    def retrieve_evidence(self, request: EvidenceRetrievalRequest):
        return self.recall_runtime.retrieve_evidence(request)


@dataclass(frozen=True, slots=True)
class _PreviewRecallCapability:
    session: Episode
    snapshot_path: Path
    descriptor: Any = None

    def search(
        self,
        session_id: str,
        query: str,
        *,
        work_item_ids: tuple[str, ...] = (),
        scope_episode_ids: tuple[str, ...] = (),
        scope_reason: str = "",
    ) -> tuple[RecallEvidence, ...]:
        snapshot = self._load_snapshot()
        if snapshot is not None:
            recall_items = snapshot.get("recall_items", ())
            if recall_items:
                return tuple(RecallEvidence(**self._restore_recall_item(item)) for item in recall_items)
        now = _utc_now()
        return (
            RecallEvidence(
                evidence_id=f"recall:{session_id}:profile",
                episode_id=session_id,
                kind="semantic",
                content=f"Profile continuity is bound to {self.session.personal_model_id}.",
                source_kind="preview",
                work_item_ids=work_item_ids,
                tags=("profile", "continuity"),
                created_at=now,
            ),
            RecallEvidence(
                evidence_id=f"recall:{session_id}:query",
                episode_id=session_id,
                kind="episodic",
                content=f"Most recent query: {query}",
                source_kind="preview",
                work_item_ids=work_item_ids,
                tags=("query", "scope-aware") if scope_episode_ids or scope_reason else ("query",),
                created_at=now,
            ),
        )

    def _load_snapshot(self) -> dict[str, Any] | None:
        return load_snapshot_payload(self.snapshot_path)

    def _restore_recall_item(self, item: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(item)
        created_at = payload.get("created_at")
        if created_at is not None:
            payload["created_at"] = _restore_datetime(str(created_at))
        for field_name in ("work_item_ids", "tags"):
            value = payload.get(field_name)
            if value is not None:
                payload[field_name] = tuple(value)
        return payload


@dataclass(frozen=True, slots=True)
class _CliContextCapability:
    profile_loader: ProfileLoader
    repository: RuntimeStorageRepository
    prompt_mode: PromptMode = "full"
    snapshot_path: Path | None = None
    total_tokens: int = 4096
    tool_runtime: ToolRuntime | None = None
    skill_runtime: SkillRuntime | None = None
    skill_hub: SkillHub | None = None
    skill_prompt_context: SkillPromptContextBuilder | None = None
    install_root: Path | None = None
    workspaces_dir: Path | None = None
    startup_cwd: Path | None = None
    summary_model_provider: Any | None = None
    embedding_service: Any | None = None
    last_projection_compaction: ContextProjectionCompactionResult | None = field(default=None, init=False, repr=False, compare=False)
    descriptor: CapabilityDescriptor = CapabilityDescriptor(
        capability_id="cli.context.runtime",
        kind="context_assembler",
        version="1.0.0",
        metadata={"description": "CLI context runtime with Elephant Agent identity and durable profile instructions."},
    )

    def _load_profile(self, profile_id: str, *, elephant_id: str | None = None) -> LoadedProfile:
        """Resolve the runtime profile for this CLI turn.

        Identity (display_name, elephant_identity_text, user_profile_text,
        companion settings) is read from the canonical State row + its
        persisted canonical records. Operator extension configuration
        (skill / tool overrides) is merged in from ``profile.json`` via
        the profile loader.
        """
        loaded = load_runtime_profile(
            self.repository,
            personal_model_id=profile_id,
            elephant_id=elephant_id,
            profile_loader=self.profile_loader,
        )
        if elephant_id and self.install_root is not None:
            return profile_with_authored_elephant_identity(
                loaded,
                elephant_file_path(elephant_id, install_root=self.install_root),
            )
        return loaded

    def assemble(
        self,
        session: Episode,
        work_items: tuple[object, ...],
        recall_items: tuple[RecallEvidence, ...],
        *,
        state_focus: StateFocusDecision | None = None,
    ) -> ContextBundle:
        return self.assemble_detailed(session, work_items, recall_items, state_focus=state_focus).bundle

    def assemble_detailed(
        self,
        session: Episode,
        work_items: tuple[object, ...],
        recall_items: tuple[RecallEvidence, ...],
        *,
        state_focus: StateFocusDecision | None = None,
        decision: object | None = None,
        plan: PlanDraft | None = None,
        continuity: EpisodeContinuityState | None = None,
        bundle_id: str | None = None,
    ) -> ContextAssemblyResult:
        loaded = self._load_profile(session.personal_model_id, elephant_id=session.elephant_id)
        resolved_elephant_id = elephant_id_from_session(session)
        if resolved_elephant_id and resolved_elephant_id != session.elephant_id:
            loaded = self._load_profile(session.personal_model_id, elephant_id=resolved_elephant_id)
        return self._assemble_result(
            session=session,
            work_items=work_items,
            recall_items=recall_items,
            loaded=loaded,
            state_focus=state_focus,
            artifacts=self._capability_artifacts(
                session,
                loaded,
                work_items=work_items,
                recall_items=recall_items,
                decision=decision,
                plan=plan,
                continuity=continuity,
            ),
            bundle_id=bundle_id,
        )

    def augment_for_generation(
        self,
        *,
        session: Episode,
        work_items: tuple[object, ...],
        recall_items: tuple[RecallEvidence, ...],
        context: ContextBundle,
        state_focus: StateFocusDecision | None,
        decision: object | None,
        plan: PlanDraft | None,
        continuity: EpisodeContinuityState,
    ) -> ContextBundle:
        return self.assemble_detailed(
            session,
            work_items,
            recall_items,
            state_focus=state_focus,
            decision=decision,
            plan=plan,
            continuity=continuity,
            bundle_id=context.bundle_id,
        ).bundle

    def _assemble_result(
        self,
        *,
        session: Episode,
        work_items: tuple[object, ...],
        recall_items: tuple[RecallEvidence, ...],
        loaded: LoadedProfile,
        state_focus: StateFocusDecision | None,
        artifacts: tuple[str, ...],
        bundle_id: str | None = None,
    ) -> ContextAssemblyResult:
        prompt_contract = build_prompt_contract(loaded, prompt_mode=self.prompt_mode)
        stable_prefix_lines = tuple(prompt_contract.stable_prefix_refs or prompt_contract.instruction_refs)
        capability_prefix_lines = self._capability_stable_prefix_lines(session=session, loaded=loaded)
        runtime = ContextRuntime(
            instruction_refs=stable_prefix_lines + capability_prefix_lines,
            total_tokens=max(1024, self.total_tokens),
        )
        assembled = runtime.assemble_detailed(
            session,
            work_items,
            recall_items,
            recent_loop_context=(),
            state_focus=state_focus,
            profile_snapshot_refs=prompt_contract.profile_snapshot_refs,
            artifacts=artifacts,
        )
        bundle_envelope = assembled.bundle.prompt_envelope
        bundle = replace(
            assembled.bundle,
            bundle_id=bundle_id or f"bundle:{session.episode_id}:{len(work_items)}:{len(recall_items)}",
            instruction_refs=prompt_contract.instruction_refs + capability_prefix_lines,
            prompt_envelope=bundle_envelope,
        )
        frozen_epoch = restore_snapshot_session_context_epoch(
            _load_snapshot_record(self.snapshot_path),
            session_id=session.episode_id,
        )
        object.__setattr__(self, "last_projection_compaction", None)
        if frozen_epoch is not None and frozen_epoch.frozen:
            bundle = apply_session_context_epoch(bundle, frozen_epoch)
        return replace(assembled, bundle=bundle)

    def compact_session_projection(
        self,
        *,
        session_id: str | None = None,
        reason: str = "manual",
        force: bool = False,
    ) -> ContextProjectionCompactionResult | None:
        frozen_epoch = restore_snapshot_session_context_epoch(
            _load_snapshot_record(self.snapshot_path),
            session_id=session_id,
        )
        if frozen_epoch is None or not frozen_epoch.frozen:
            return None
        _updated_epoch, result = self._compact_frozen_epoch_if_needed(frozen_epoch, force=force, reason=reason)
        object.__setattr__(self, "last_projection_compaction", result)
        return result

    def force_projection_compaction(
        self,
        *,
        reason: str = "provider-overflow",
        session_id: str | None = None,
    ) -> ContextProjectionCompactionResult | None:
        return self.compact_session_projection(session_id=session_id, reason=reason, force=True)

    def flush_projection_cache(self) -> None:
        object.__setattr__(self, "last_projection_compaction", None)

    def _compact_frozen_epoch_if_needed(
        self,
        frozen_epoch: SessionContextEpoch,
        *,
        force: bool = False,
        reason: str = "manual",
    ) -> tuple[SessionContextEpoch, ContextProjectionCompactionResult]:
        """Compact the frozen epoch with the deterministic fallback path."""
        updated_epoch, result = compact_session_context_epoch(
            frozen_epoch,
            total_tokens=self.total_tokens,
            reason=reason,
            force=force,
        )
        if updated_epoch != frozen_epoch:
            self._write_compacted_epoch(updated_epoch)
        return updated_epoch, result

    def _write_compacted_epoch(self, epoch: SessionContextEpoch) -> None:
        if self.snapshot_path is None:
            return
        runtime_proxy = type("_SnapshotRuntimeProxy", (), {"snapshot_path": self.snapshot_path})()
        write_snapshot_session_context_epoch(runtime_proxy, epoch)

    def _capability_stable_prefix_lines(
        self,
        *,
        session: Episode,
        loaded: LoadedProfile,
    ) -> tuple[str, ...]:
        lines: list[str] = []
        _pm_state, pm_facts = self._resolve_pm_state_and_facts(session)
        skill_prompt_context = self.skill_prompt_context
        if skill_prompt_context is None and self.skill_runtime is not None:
            skill_prompt_context = SkillPromptContextBuilder(
                repository=self.repository,
                profile_loader=self.profile_loader,
                skill_runtime=self.skill_runtime,
                install_root=self.install_root,
                surface_kind="cli",
            )
        if skill_prompt_context is not None:
            lines.extend(skill_prompt_context.stable_prefix_lines(session))
        pending_count = self._pending_proposal_count_from_facts(pm_facts)
        if pending_count > 0:
            lines.append("")
            lines.append(f"### Pending Personal Model proposals ({pending_count})")
            lines.append("Review them in the dashboard before treating them as durable understanding.")
        if path_artifact := self._runtime_path_artifact(session):
            lines.append("")
            lines.append("### Runtime paths")
            lines.append(path_artifact)
        return tuple(lines)

    def _capability_artifacts(
        self,
        session: Episode,
        loaded: LoadedProfile,
        *,
        work_items: tuple[object, ...] = (),
        recall_items: tuple[RecallEvidence, ...] = (),
        decision: object | None = None,
        plan: PlanDraft | None = None,
        continuity: EpisodeContinuityState | None = None,
    ) -> tuple[str, ...]:
        artifacts = list(
            self._generation_artifacts(
                work_items=work_items,
                recall_items=recall_items,
                decision=decision,
                plan=plan,
                continuity=continuity,
            )
        )
        active_run = self.repository.load_latest_open_loop_checkpoint(session.episode_id)
        if active_run is not None:
            artifacts.append(
                "active-loop-checkpoint: there is unfinished long-horizon work in flight; "
                f"run={active_run.run_id}; status={active_run.status}; "
                f"objective={_compact_runtime_text(active_run.prompt, limit=180)}; "
                f"checkpoint={_compact_runtime_text(active_run.last_summary or active_run.waiting_reason or '<empty>', limit=220)}"
            )
            recent_steps = self.repository.list_loop_checkpoint_steps(active_run.run_id, limit=4)
            if recent_steps:
                step_lines = "; ".join(
                    f"{step.kind} {step.title}: {_compact_runtime_text(step.content, limit=120)}"
                    for step in recent_steps
                )
                artifacts.append(f"active-loop-checkpoint-steps: {step_lines}")
        return tuple(artifacts)

    def _runtime_path_artifact(self, session: Episode) -> str:
        lines: list[str] = []
        if self.startup_cwd is not None:
            lines.append(f"startup_cwd={self.startup_cwd.expanduser().resolve()} (the directory where this session launched; use as working directory when the user asks to explore 'here' or 'current project')")
        if self.workspaces_dir is not None and session.elephant_id:
            elephant_ws = self.workspaces_dir.expanduser().resolve() / quote(session.elephant_id.strip(), safe='')
            lines.append(f"elephant_workspace={elephant_ws} (default scratch directory for file output when the user does not specify a path)")
        if not lines:
            return ""
        return "runtime-paths: " + "; ".join(lines)

    def _resolve_pm_state_and_facts(self, session: Episode) -> tuple[Any, tuple[Any, ...]]:
        """Resolve PM state and facts once for PM-related prompt sections."""
        state = None
        elephant_id = str(session.elephant_id or "").strip()
        if elephant_id:
            for candidate in self.repository.list_states(status="active"):
                if candidate.elephant_id == elephant_id:
                    state = candidate
                    break
        if state is None:
            state = self.repository.current_state()
        if state is None:
            active_states = self.repository.list_states(status="active")
            profile_states = [c for c in active_states if str(c.metadata.get("profile_id") or "").strip() == session.personal_model_id]
            if len(profile_states) == 1: state = profile_states[0]
            elif len(active_states) == 1: state = active_states[0]
        if state is None:
            return (None, ())
        list_facts = getattr(self.repository, "list_personal_model_facts", None)
        if not callable(list_facts):
            return (state, ())
        try:
            facts = tuple(list_facts(personal_model_id=state.personal_model_id, status="active"))
        except Exception:
            facts = ()
        return (state, facts)

    def _recently_learned_from_facts(self, facts: tuple[Any, ...]) -> tuple[str, ...]:
        """Find PM facts committed in last 24h for UX visibility."""
        try:
            from datetime import timedelta, datetime, timezone
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            recent: list[str] = []
            for fact in facts:
                metadata = dict(getattr(fact, "metadata", {}) or {})
                committed_at = getattr(fact, "committed_at", None)
                promoted_at = committed_at.isoformat() if committed_at is not None else ""
                if not promoted_at:
                    continue
                try:
                    if datetime.fromisoformat(promoted_at.replace("Z", "+00:00")) < cutoff: continue
                except (ValueError, TypeError): continue
                effect = str(metadata.get("behavioral_effect") or getattr(fact, "text", "") or "").strip()
                if effect and effect not in recent: recent.append(_compact_runtime_text(effect, limit=120))
            return tuple(recent[:4])
        except Exception:
            return ()

    def _pending_proposal_count_from_facts(self, facts: tuple[Any, ...]) -> int:
        """Facts are durable claims; pending proposals live in the question ledger."""
        return 0

    def _personal_model_behavior_contract_from_facts(self, facts: tuple[Any, ...], *, limit: int = 8) -> str:
        grouped: dict[str, list[str]] = {}
        for fact in facts:
            metadata = dict(getattr(fact, "metadata", {}) or {})
            if str(getattr(fact, "status", "") or "active") != "active":
                continue
            effect = str(metadata.get("behavioral_effect") or getattr(fact, "text", "") or "").strip()
            if not effect: continue
            family = str(metadata.get("facet") or getattr(fact, "lens", "") or "general").strip()
            grouped.setdefault(family, [])
            compact = _compact_runtime_text(effect, limit=160)
            if compact not in grouped[family]: grouped[family].append(compact)
        if not grouped:
            return ""
        lines: list[str] = []
        total = 0
        family_labels = {"style": "Style", "core": "Identity", "relationship": "Relationship", "procedural": "Workflow", "personal_knowledge": "Knowledge"}
        for family in ("style", "core", "relationship", "procedural", "personal_knowledge"):
            effects = grouped.pop(family, [])
            if not effects: continue
            label = family_labels.get(family, family.replace("_", " ").title())
            for effect in effects:
                if total >= limit: break
                lines.append(f"- {label}: {effect}")
                total += 1
        for family, effects in grouped.items():
            label = family.replace("_", " ").title()
            for effect in effects:
                if total >= limit: break
                lines.append(f"- {label}: {effect}")
                total += 1
        return "\n".join(lines) if lines else ""

    def _generation_artifacts(
        self,
        *,
        work_items: tuple[object, ...],
        recall_items: tuple[RecallEvidence, ...],
        decision: object | None,
        plan: PlanDraft | None,
        continuity: EpisodeContinuityState | None,
    ) -> tuple[str, ...]:
        artifacts = [
            artifact
            for artifact in (
                _continuity_artifact(continuity),
            )
            if artifact.strip()
        ]
        if plan is not None and plan.steps:
            step = plan.steps[0]
            artifacts.append(
                "runtime-plan-step: "
                f"{step.title}; rationale={_compact_runtime_text(step.rationale, limit=160)}"
                )
        return tuple(artifacts)

def _continuity_artifact(continuity: EpisodeContinuityState | None) -> str:
    if continuity is None or not continuity.requires_recovery:
        return ""
    return f"runtime-continuity: {_compact_runtime_text(continuity.summary, limit=160)}"


def _looks_like_profile_dump_evidence(text: str) -> bool:
    normalized = " ".join(str(text or "").casefold().replace("_", " ").split())
    if not normalized:
        return False
    markers = (
        "preferred name:",
        "current work:",
        "current city:",
        "mbti:",
        "personal hobbies:",
        "hobbies:",
        "boundaries:",
        "care context:",
        "age:",
        "birth date:",
        "gender:",
        "relationship mode:",
    )
    if sum(1 for marker in markers if marker in normalized) >= 2:
        return True
    return any(normalized.startswith(marker) for marker in markers)


def _recall_summary_artifact(recall_items: tuple[RecallEvidence, ...], *, limit: int = 3) -> str:
    """Short human-shaped summary of which recall evidence was surfaced this turn.

    The old rendering leaked ``evidence_ref[kind; work_items=a,b; tags=c,d]``
    into the attachments slice. evidence_ref and work_item refs have no
    tool for the model to dereference; they were pure prompt
    pollution. We now emit one line per preview using the evidence
    content directly — no fallback literal like "no previews available"
    which is worse than silence.
    """
    if not recall_items:
        return ""
    preview_texts: list[str] = []
    preview_count = min(len(recall_items), max(1, limit))
    for evidence in recall_items[:preview_count]:
        content = str(getattr(evidence, "content", "") or "")
        if _looks_like_profile_dump_evidence(content):
            continue
        snippet = _compact_runtime_text(content, limit=80)
        if snippet:
            preview_texts.append(snippet)
    if not preview_texts:
        # Nothing worth showing — omit the whole line instead of echoing
        # "0 surfaced" / "no previews".
        return ""
    remainder = len(recall_items) - len(preview_texts)
    suffix = f" (+{remainder} more)" if remainder > 0 else ""
    previews = " · ".join(preview_texts)
    return f"Recently surfaced notes: {previews}{suffix}"


def _compact_runtime_text(value: str, *, limit: int) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 1)].rstrip() + "…"


@dataclass(frozen=True, slots=True)
class _PreviewModelProviderCapability:
    descriptor: Any = None

    def selection_state(self) -> RuntimeModelChoice:
        return RuntimeModelChoice(
            strong_model=GenerationModelProfile(
                profile_id="preview:strong",
                provider_id="preview",
                model_id="preview-strong",
            ),
            weak_model=SupportModelProfile(
                profile_id="preview:weak",
                provider_id="preview",
                model_id="preview-weak",
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
        summary = (
            f"Next step for {profile.display_name} in {session.episode_id}: "
            f"continue from elephant continuity and {len(context.evidence_refs)} recall evidence item(s) "
            f"with the {model_role} model path."
        )
        return ExecutionResult(
            execution_id=f"exec:{session.episode_id}:{uuid4().hex[:8]}",
            episode_id=session.episode_id,
            outcome="ok",
            summary=summary,
            prompt_tokens=len(prompt.split()),
            completion_tokens=len(summary.split()),
            total_tokens=len(prompt.split()) + len(summary.split()),
            side_effects=(f"model_role={model_role}",),
        )

class _PreviewToolCapability:
    descriptor: Any = None

    def invoke(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        *,
        session_id: str,
    ) -> ExecutionResult:
        summary = f"invoked {tool_name} with {dict(arguments)}"
        return ExecutionResult(
            execution_id=f"tool:{session_id}:{tool_name}",
            episode_id=session_id,
            outcome="ok",
            summary=summary,
            side_effects=(tool_name,),
        )


@dataclass(frozen=True, slots=True)
class _PreviewDeliveryCapability:
    descriptor: Any = None

    def deliver(
        self,
        session_id: str,
        payload: Mapping[str, Any],
    ) -> ExecutionResult:
        return ExecutionResult(
            execution_id=f"delivery:{session_id}:{uuid4().hex[:8]}",
            episode_id=session_id,
            outcome="ok",
            summary=f"delivered {payload.get('event_id', 'event')}",
        )
