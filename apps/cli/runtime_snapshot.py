from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from urllib.parse import quote
from uuid import uuid4

from .snapshot_io import load_snapshot_payload, write_snapshot_payload
from .runtime_prompt_messages import session_history_messages
from packages.context import (
    ContextRuntime,
    FrozenSkillIndexEntry,
    SessionContextEpoch,
    SkillDisclosureRecord,
    next_session_context_epoch,
    restore_session_context_epoch,
    session_context_epoch_payload,
)
from packages.contracts import Episode
from packages.contracts.runtime import (
    ContextBundle,
    EventEnvelope,
    ExecutionResult,
    ExperienceRecord,
    StateFocusCandidateScore,
    StateFocusDecision,
    StateFocusReason,
    RecallEvidence,
    PlanDraft,
    PromptMessage,
    PersonalModelGrowthState,
    PersonalModelRuntimeState,
    ProcedureRecord,
)
from packages.experience import capture_turn_experience
from packages.growth import GrowthTurnSignals, apply_turn_growth
from packages.kernel import KernelOutcome
from packages.kernel.generation_context import build_context_for_generation
from packages.state import (
    build_prompt_contract,
    elephant_id_from_session,
    load_runtime_profile,
    profile_with_authored_elephant_identity,
)

if TYPE_CHECKING:
    from apps.cli.runtime import CliRuntime

from .runtime_growth_metrics import active_personal_model_facts_for_growth, personal_model_growth_metrics
from .runtime_support import _resolved_session_skills


def load_snapshot(runtime: CliRuntime) -> dict[str, Any] | None:
    return load_snapshot_payload(runtime.snapshot_path)


def load_snapshot_state_focus(runtime: CliRuntime, *, session_id: str | None = None) -> StateFocusDecision | None:
    snapshot = load_snapshot(runtime)
    return restore_snapshot_state_focus(snapshot, session_id=session_id)


def restore_snapshot_state_focus(
    snapshot: Mapping[str, Any] | None,
    *,
    session_id: str | None = None,
) -> StateFocusDecision | None:
    if not snapshot:
        return None
    if session_id is not None:
        session = snapshot.get("session")
        resolved_snapshot_session_id = (
            str(session.get("episode_id") or session.get("session_id") or "").strip()
            if isinstance(session, Mapping)
            else ""
        )
        if resolved_snapshot_session_id != session_id:
            return None
    payload = snapshot.get("state_focus")
    if not isinstance(payload, Mapping):
        return None
    reasons = tuple(_restore_state_focus_reason(reason) for reason in payload.get("reasons", ()) if isinstance(reason, Mapping))
    candidate_scores = tuple(
        _restore_state_focus_candidate_score(score)
        for score in payload.get("candidate_scores", ())
        if isinstance(score, Mapping)
    )
    return StateFocusDecision(
        focus_family=str(payload.get("focus_family") or "").strip(),
        confidence=float(payload.get("confidence") or 0.0),
        focus_work_item_ids=_as_str_tuple(payload.get("focus_work_item_ids")),
        provisional_work_item_seed=_optional_str(payload.get("provisional_work_item_seed")),
        continuity_signal=str(payload.get("continuity_signal") or "none"),
        focus_scope=str(payload.get("focus_scope") or "episode"),
        context_budget=str(payload.get("context_budget") or "standard"),
        embedding_available=bool(payload.get("embedding_available", False)),
        degradation_mode=str(payload.get("degradation_mode") or "none"),
        needs_focus_model_assist=bool(payload.get("needs_focus_model_assist", False)),
        focus_assist_outcome=str(payload.get("focus_assist_outcome") or "not-requested"),
        selection_path=str(payload.get("selection_path") or "direct"),
        reasons=reasons,
        candidate_scores=candidate_scores,
        audit_trace=_as_str_tuple(payload.get("audit_trace")),
    )


def load_snapshot_session_context_epoch(
    runtime: CliRuntime,
    *,
    session_id: str | None = None,
) -> SessionContextEpoch | None:
    return restore_snapshot_session_context_epoch(load_snapshot(runtime), session_id=session_id)


def restore_snapshot_session_context_epoch(
    snapshot: Mapping[str, Any] | None,
    *,
    session_id: str | None = None,
) -> SessionContextEpoch | None:
    return restore_session_context_epoch(snapshot, session_id=session_id)


def write_snapshot_session_context_epoch(runtime: CliRuntime, epoch: SessionContextEpoch) -> None:
    payload = load_snapshot(runtime) or {}
    payload["session_context_epoch"] = _session_context_epoch_payload(epoch)
    write_snapshot_payload(runtime.snapshot_path, payload)


def append_outcome_recall_event(runtime: CliRuntime, outcome: KernelOutcome) -> None:
    session = runtime._load_session(outcome.route_session_id)
    tags = ("continuity", "assistant", *_step_action_tags(outcome))
    content = "\n".join(
        part
        for part in (
            outcome.state.summary.strip(),
            outcome.execution.summary.strip(),
        )
        if part
    ).strip()
    if not content:
        return
    event = EventEnvelope(
        event_id=f"event:{uuid4().hex}",
        event_type="continuity",
        episode_id=session.episode_id,
        source="cli",
        payload={
            "content": content,
            "summary": content.splitlines()[0],
            "signal_kind": "continuity",
            "work_item_ids": "",
            "tags": ",".join(tags),
            "source_event_id": outcome.event.event_id,
        },
    )
    runtime.recall_runtime.append_event(event)


def append_outcome_experience(runtime: CliRuntime, outcome: KernelOutcome) -> ExperienceRecord | None:
    execution = outcome.execution
    if execution is None:
        return None
    session = runtime._load_session(outcome.route_session_id)
    profile = runtime._load_profile(session.personal_model_id).state
    active_skills = _resolved_session_skills(
        repository=runtime.repository,
        profile_loader=runtime.profile_loader,
        skill_runtime=runtime.skill_runtime,
        session=session,
    )
    extra_tags: list[str] = [f"outcome:{execution.outcome}"]
    record = capture_turn_experience(
        session_id=session.episode_id,
        profile_id=session.personal_model_id,
        elephant_id=session.elephant_id,
        summary=outcome.state.summary.strip() or execution.summary,
        source_event_id=outcome.event.event_id,
        run_id=None,
        work_item_id=None,
        tool_call_count=outcome.tool_call_count,
        model_turn_count=outcome.model_turn_count,
        related_skill_ids=tuple(skill.skill_id for skill in active_skills),
        produced_artifact_ids=execution.produced_artifact_ids,
        tags=tuple(extra_tags),
    )
    return record


def append_outcome_growth(
    runtime: CliRuntime,
    outcome: KernelOutcome,
    *,
    experience: ExperienceRecord | None,
) -> PersonalModelGrowthState:
    session = runtime._load_session(outcome.route_session_id)
    profile_id = session.personal_model_id
    current = runtime.repository.load_personal_model_growth(profile_id)
    if _growth_state_predates_profile_sessions(runtime, profile_id=profile_id, state=current):
        current = None
    procedures = ()  # Procedural evidence removed; growth tracks without procedures.
    update = apply_turn_growth(
        current,
        _build_growth_turn_signals(
            current=current,
            outcome=outcome,
            experience=experience,
            procedures=procedures,
            runtime=runtime,
            session=session,
        ),
    )
    runtime.repository.upsert_personal_model_growth(update.after.state)
    runtime.growth_updates[session.episode_id] = update
    return update.after.state


def _growth_state_predates_profile_sessions(
    runtime: CliRuntime,
    *,
    profile_id: str,
    state: PersonalModelGrowthState | None,
) -> bool:
    if state is None:
        return False
    growth_timestamp = state.updated_at or state.created_at or state.last_dialogue_at or state.first_dialogue_at
    if growth_timestamp is None:
        return False
    episodes = runtime.repository.list_episodes()
    started_at_values = [
        episode.started_at
        for episode in episodes
        if episode.personal_model_id == profile_id
    ]
    if not started_at_values:
        return False
    first_started_at = min(started_at_values)
    if first_started_at.tzinfo is None:
        first_started_at = first_started_at.replace(tzinfo=timezone.utc)
    if growth_timestamp.tzinfo is None:
        growth_timestamp = growth_timestamp.replace(tzinfo=timezone.utc)
    return growth_timestamp < first_started_at


def _build_growth_turn_signals(
    *,
    current: PersonalModelGrowthState | None,
    outcome: KernelOutcome,
    experience: ExperienceRecord | None,
    procedures: tuple[ProcedureRecord, ...],
    runtime: CliRuntime,
    session: Episode,
) -> GrowthTurnSignals:
    promoted_delta, promoted_ids = _promoted_procedure_delta(current, procedures)
    pm_metrics = personal_model_growth_metrics(
        facts=active_personal_model_facts_for_growth(runtime, personal_model_id=session.personal_model_id),
        since=current.last_dialogue_at if current is not None else None,
    )
    return GrowthTurnSignals(
        session_id=session.episode_id,
        profile_id=session.personal_model_id,
        total_tokens=outcome.execution.total_tokens,
        captured_experiences=1 if experience is not None else 0,
        promoted_experiences=promoted_delta,
        continuity_bonus=bool(session.interruption_state),
        occurred_at=session.updated_at,
        work_item_id=None,
        work_item_status=None,
        work_item_priority=None,
        progression_action="",
        resume_signal="continue" if any(step.action == "resume" and step.status == "completed" for step in outcome.steps) else "none",
        continuity_mode="background" if session.interruption_state else "foreground",
        execution_outcome=outcome.execution.outcome,
        experience_status=experience.status if experience is not None else None,
        active_work_item_present=bool(outcome.state.summary.strip()),
        plan_step_count=0,
        work_item_dependency_count=0,
        recall_count=len(outcome.recall_items),
        context_work_item_count=len(outcome.context.work_item_ids),
        tool_call_count=outcome.tool_call_count,
        model_turn_count=outcome.model_turn_count,
        blocked_work_item_count=0,
        work_item_evidence_refs=(),
        replay_evidence_refs=(),
        skill_ids=experience.related_skill_ids if experience is not None else (),
        artifact_ids=outcome.execution.produced_artifact_ids,
        promoted_procedure_ids=promoted_ids,
        personal_model_fact_count=pm_metrics.fact_count,
        personal_model_lens_counts=pm_metrics.lens_counts,
        personal_model_topic_count=pm_metrics.topic_count,
        personal_model_new_fact_count=pm_metrics.new_fact_count,
        personal_model_updated_fact_count=pm_metrics.updated_fact_count,
        personal_model_supported_fact_count=pm_metrics.supported_fact_count,
        personal_model_evidence_ref_count=pm_metrics.evidence_ref_count,
        personal_model_high_confidence_fact_count=pm_metrics.high_confidence_fact_count,
        personal_model_rich_fact_count=pm_metrics.rich_fact_count,
        personal_model_average_confidence=pm_metrics.average_confidence,
        elapsed_since_last_turn_seconds=_growth_elapsed_seconds(current, occurred_at=session.updated_at),
    )


def _promoted_procedure_delta(
    current: PersonalModelGrowthState | None,
    procedures: tuple[ProcedureRecord, ...],
) -> tuple[int, tuple[str, ...]]:
    if not procedures:
        return 0, ()
    promoted = tuple(
        procedure.procedure_id
        for procedure in procedures
        if procedure.status in {"active", "promoted", "verified"}
    )
    already_recorded = current.promoted_experiences if current is not None else 0
    delta = max(0, len(promoted) - already_recorded)
    if delta == 0:
        return 0, ()
    return delta, promoted[-delta:]


def _step_action_tags(outcome: KernelOutcome) -> tuple[str, ...]:
    tags: list[str] = []
    for step in outcome.steps:
        if step.status != "completed":
            continue
        tag = f"step:{step.action}"
        if tag not in tags:
            tags.append(tag)
        if len(tags) >= 3:
            break
    return tuple(tags)


def _growth_elapsed_seconds(
    current: PersonalModelGrowthState | None,
    *,
    occurred_at: datetime,
) -> int | None:
    if current is None or current.last_dialogue_at is None:
        return None
    elapsed = occurred_at - current.last_dialogue_at
    return max(0, int(elapsed.total_seconds()))


def write_snapshot(
    runtime: CliRuntime,
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
    existing = load_snapshot(runtime) or {}
    session_context_epoch = _next_session_context_epoch(
        runtime,
        restore_snapshot_session_context_epoch(existing),
        profile=profile,
        session=session,
        work_items=work_items,
        event=event,
        execution=execution,
        delivery=delivery,
        state_focus=state_focus,
        context=context,
        turn_messages=turn_messages,
    )
    payload = {
        "profile": _profile_payload(profile, elephant_identity_text=elephant_identity_text),
        "session": _session_payload(session),
        "work_items": [_work_item_payload(work_item) for work_item in work_items],
        "recall_items": [_recall_item_payload(evidence) for evidence in recall_items],
        "plan": _plan_payload(plan),
        "execution": _execution_payload(execution),
        "delivery": _execution_payload(delivery),
        "stages": [_stage_payload(stage) for stage in stages],
        "event": _event_payload(event),
        "state_focus": _state_focus_payload(state_focus),
        "session_context_epoch": _session_context_epoch_payload(session_context_epoch),
        "telemetry": existing.get("telemetry", ()),
    }
    write_snapshot_payload(runtime.snapshot_path, payload)


def _next_session_context_epoch(
    runtime: CliRuntime,
    existing: SessionContextEpoch | None,
    *,
    profile: PersonalModelRuntimeState,
    session: Episode,
    work_items: tuple[object, ...],
    event: EventEnvelope | None,
    execution: ExecutionResult | None,
    delivery: ExecutionResult | None,
    state_focus: StateFocusDecision | None,
    context: ContextBundle | None,
    turn_messages: tuple[PromptMessage, ...] = (),
) -> SessionContextEpoch:
    disclosures = _skill_disclosure_records(runtime, context=context)
    frozen_skill_index = _frozen_session_skill_index(runtime, profile=profile, session=session)
    can_refresh_episode_open = existing is not None and existing.frozen and event is None and execution is None and not existing.history_messages
    if context is None and (existing is None or not existing.frozen or can_refresh_episode_open):
        context = _episode_open_frozen_context(runtime, profile=profile, session=session, frozen_skill_index=frozen_skill_index)
    is_user_turn = event is not None and _snapshot_event_is_user_turn(event.event_type, event.source)
    fallback_history = session_history_messages(
        event=event,
        execution=execution,
        delivery=delivery,
        is_user_turn=is_user_turn,
    )
    return next_session_context_epoch(
        existing,
        session=session,
        event=event,
        execution=execution,
        context=context,
        turn_messages=turn_messages,
        thread_focus=_derive_session_epoch_focus(runtime, session=session, work_items=work_items),
        frozen_skill_index=frozen_skill_index,
        frozen_tool_count=_frozen_session_tool_count(runtime),
        frozen_tool_ids=_frozen_session_tool_ids(runtime),
        skill_disclosures=disclosures,
        fallback_history_messages=fallback_history,
        now=_utc_now(),
    )


def _episode_open_frozen_context(
    runtime: CliRuntime,
    *,
    profile: PersonalModelRuntimeState,
    session: Episode,
    frozen_skill_index: tuple[FrozenSkillIndexEntry, ...],
) -> ContextBundle | None:
    try:
        resolved_elephant_id = elephant_id_from_session(session)
        loaded = load_runtime_profile(
            runtime.repository,
            personal_model_id=profile.profile_id,
            elephant_id=resolved_elephant_id or None,
            profile_loader=runtime.profile_loader,
        )
        if resolved_elephant_id:
            loaded = profile_with_authored_elephant_identity(
                loaded,
                runtime.paths.elephant_file_path(resolved_elephant_id),
            )
        prompt_contract = build_prompt_contract(loaded, prompt_mode="full")
        stable_prefix_lines = tuple(prompt_contract.stable_prefix_refs or prompt_contract.instruction_refs)
        skill_lines = _frozen_skill_shelf_prompt_lines(frozen_skill_index)
        runtime_path_lines = _episode_open_runtime_path_lines(runtime, session=session)
        runtime_context = ContextRuntime(
            instruction_refs=stable_prefix_lines + skill_lines + runtime_path_lines,
            total_tokens=max(1024, int(getattr(runtime, "active_provider_context_window", lambda: 0)() or 0)),
        )
        assembled = runtime_context.assemble_detailed(
            session,
            (),
            (),
            recent_loop_context=(),
            state_focus=None,
            profile_snapshot_refs=prompt_contract.profile_snapshot_refs,
            artifacts=(),
        )
        base = replace(
            assembled.bundle,
            bundle_id=f"bundle:{session.episode_id}:episode-open",
            instruction_refs=prompt_contract.instruction_refs + skill_lines + runtime_path_lines,
        )
        request = SimpleNamespace(
            tool_name=None,
            personal_model_id=session.personal_model_id,
            episode_id=session.episode_id,
        )
        dependencies = SimpleNamespace(storage=runtime.repository, context=SimpleNamespace())
        return build_context_for_generation(
            dependencies=dependencies,
            request=request,
            profile=profile,
            session=session,
            state_focus=None,
            work_items=(),
            recall_items=(),
            context=base,
            decision=None,
            plan=None,
            continuity=None,
        )
    except Exception:
        return None


def _frozen_skill_shelf_prompt_lines(frozen_skill_index: tuple[FrozenSkillIndexEntry, ...]) -> tuple[str, ...]:
    if not frozen_skill_index:
        return ()
    lines = [
        "### Available skill shelf",
        "- This Episode exposes only skills linked by active `world.skills.affinity.*` Personal Model facts.",
        "- Full skill bodies are not injected; use skill tools/search for long-tail skills.",
    ]
    for entry in frozen_skill_index[:12]:
        label = entry.display_name or entry.skill_id
        reason = entry.reason or entry.source_topic or "PM skill affinity"
        command = f" /{entry.slash_command}" if entry.slash_command else ""
        lines.append(f"- {label} (`{entry.skill_id}`{command}): {reason}")
    return tuple(lines)


def _episode_open_runtime_path_lines(runtime: CliRuntime, *, session: Episode) -> tuple[str, ...]:
    lines = ["### Runtime paths"]
    try:
        lines.append(
            f"startup_cwd={Path.cwd().resolve()} "
            "(the directory where this session launched; use as working directory when the user asks to explore 'here' or 'current project')"
        )
    except Exception:
        pass
    workspaces_dir = getattr(getattr(runtime, "paths", None), "workspaces_dir", None)
    elephant_id = str(getattr(session, "elephant_id", "") or "").strip()
    if workspaces_dir is not None and elephant_id:
        elephant_ws = workspaces_dir.expanduser().resolve() / quote(elephant_id, safe="")
        lines.append(
            f"elephant_workspace={elephant_ws} "
            "(default scratch directory for file output when the user does not specify a path)"
        )
    return tuple(lines) if len(lines) > 1 else ()


def _snapshot_event_is_user_turn(event_type: str | None, source: str | None) -> bool:
    if str(source or "").strip() == "cli.startup":
        return False
    normalized_event_type = str(event_type or "").strip().lower()
    if not normalized_event_type:
        return True
    return normalized_event_type == "turn.received"


def _derive_session_epoch_focus(
    runtime: CliRuntime,
    *,
    session: Episode,
    work_items: tuple[object, ...],
) -> str:
    del work_items
    # Episode-open frozen context must not infer the current turn's focus. It can
    # only carry the previous wake/resume summary captured before this Episode.
    continuity = runtime.inspect_continuity(session_id=session.episode_id)
    normalized = str(getattr(continuity, "wake_summary", "") or "").strip()
    if normalized and not _focus_summary_is_planner_fallback(normalized):
        return normalized
    return "No prior Episode summary was available when this Episode froze."


def _focus_summary_is_planner_fallback(text: str) -> bool:
    normalized = text.strip().lower()
    return (
        normalized in {"idle", "defer_or_schedule"}
        or "no durable state focus is available" in normalized
        or "no actionable current work was available" in normalized
        or "planner should defer" in normalized
    )


def _frozen_session_skill_count(
    runtime: CliRuntime,
    *,
    profile: PersonalModelRuntimeState,
    session: Episode,
) -> int:
    return len(_frozen_session_skill_index(runtime, profile=profile, session=session))


def _frozen_session_skill_index(
    runtime: CliRuntime,
    *,
    profile: PersonalModelRuntimeState,
    session: Episode,
) -> tuple[FrozenSkillIndexEntry, ...]:
    del profile
    affinity = _skill_affinity_rows(runtime, personal_model_id=session.personal_model_id)
    if not affinity:
        return ()
    skills = _resolved_session_skills(
        repository=runtime.repository,
        profile_loader=runtime.profile_loader,
        skill_runtime=runtime.skill_runtime,
        session=session,
        prompt_visible_only=True,
    )
    skills_by_key: dict[str, object] = {}
    for skill in skills:
        skills_by_key[str(skill.skill_id)] = skill
        skills_by_key[_skill_index_id(str(skill.skill_id))] = skill
    out: list[FrozenSkillIndexEntry] = []
    seen: set[str] = set()
    for score, topic, metadata, text in affinity:
        skill_id = str(metadata.get("skill_id") or "").strip()
        index_id = str(metadata.get("index_id") or "").strip() or topic.rsplit(".", 1)[-1]
        skill = skills_by_key.get(skill_id) or skills_by_key.get(index_id)
        if skill is None:
            continue
        resolved_skill_id = str(getattr(skill, "skill_id", "") or "")
        if not resolved_skill_id or resolved_skill_id in seen:
            continue
        seen.add(resolved_skill_id)
        reason = str(metadata.get("reason") or metadata.get("behavioral_effect") or text).strip()
        out.append(
            FrozenSkillIndexEntry(
                skill_id=resolved_skill_id,
                display_name=str(getattr(skill, "display_name", "") or ""),
                category=str(getattr(skill, "metadata", {}).get("category") or "").strip(),
                source_id=str(getattr(skill, "metadata", {}).get("source_id") or "").strip(),
                storage_tier=str(getattr(skill, "metadata", {}).get("storage_tier") or "").strip(),
                slash_command=str(getattr(skill, "metadata", {}).get("slash_command") or "").strip(),
                index_id=index_id,
                source_topic=topic,
                reason=reason[:180],
            )
        )
    return tuple(out[:12])


def _skill_index_id(skill_id: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in skill_id.strip().lower())
    return "_".join(part for part in cleaned.split("_") if part)


def _skill_affinity_rows(runtime: CliRuntime, *, personal_model_id: str) -> tuple[tuple[float, str, dict[str, str], str], ...]:
    list_facts = getattr(runtime.repository, "list_personal_model_facts", None)
    if not callable(list_facts):
        return ()
    try:
        facts = tuple(list_facts(personal_model_id=personal_model_id, status="active"))
    except Exception:
        return ()
    rows: list[tuple[float, str, dict[str, str], str]] = []
    for fact in facts:
        metadata = {str(key): str(value) for key, value in dict(getattr(fact, "metadata", {}) or {}).items()}
        topic = str(metadata.get("topic") or "").strip()
        if not (topic.startswith("world.skills.affinity.") or topic.startswith("skills.affinity.")):
            continue
        if metadata.get("projection_policy") not in {"", "skill_shelf_candidate"}:
            continue
        try:
            confidence = float(metadata.get("confidence") or getattr(fact, "confidence", 0.0) or 0.0)
        except ValueError:
            confidence = float(getattr(fact, "confidence", 0.0) or 0.0)
        try:
            usage = min(10.0, float(metadata.get("usage_count") or 0.0))
        except ValueError:
            usage = 0.0
        score = confidence + (usage * 0.01)
        rows.append((score, topic, metadata, str(getattr(fact, "text", "") or "")))
    rows.sort(key=lambda item: (-item[0], item[1]))
    return tuple(rows)


def _frozen_session_skill_ids(
    runtime: CliRuntime,
    *,
    profile: PersonalModelRuntimeState,
    session: Episode,
) -> tuple[str, ...]:
    return tuple(
        entry.skill_id
        for entry in _frozen_session_skill_index(runtime, profile=profile, session=session)
    )


def _frozen_session_tool_count(runtime: CliRuntime) -> int:
    return len(_frozen_session_tool_ids(runtime))


def _frozen_session_tool_ids(runtime: CliRuntime) -> tuple[str, ...]:
    if runtime.tool_runtime is None:
        return ()
    return tuple(
        tool.tool_id
        for tool in runtime.tool_runtime.list_tools(
            audience="model",
            enabled_only=True,
            available_only=True,
        )
    )


def _skill_disclosure_records(
    runtime: CliRuntime,
    *,
    context: ContextBundle | None,
) -> tuple[SkillDisclosureRecord, ...]:
    if context is None or runtime.skill_runtime is None:
        return ()
    disclosed_skill_ids = tuple(
        artifact_id.split(":", 1)[1]
        for artifact_id in context.artifact_ids
        if artifact_id.startswith("skill:") and ":" in artifact_id
    )
    if not disclosed_skill_ids:
        return ()
    records: list[SkillDisclosureRecord] = []
    for skill_id in dict.fromkeys(disclosed_skill_ids):
        definition = runtime.skill_runtime.describe(skill_id)
        display_name = (
            definition.display_name.strip()
            if definition is not None and definition.display_name.strip()
            else skill_id
        )
        records.append(
            SkillDisclosureRecord(
                skill_id=skill_id,
                display_name=display_name,
                reason=_skill_disclosure_reason(skill_id=skill_id, display_name=display_name),
            )
        )
    return tuple(records)


def _skill_disclosure_reason(*, skill_id: str, display_name: str) -> str:
    return (
        f"{display_name} ({skill_id}) was disclosed because the runtime recorded an explicit skill overlay."
    )


def _profile_payload(profile: PersonalModelRuntimeState, *, elephant_identity_text: str | None) -> dict[str, Any]:
    return {
        "profile_id": profile.profile_id,
        "display_name": profile.display_name,
        "mode": profile.mode,
        "elephant_path": profile.elephant_path,
        "preferences": list(profile.preferences),
        "enabled_capabilities": list(profile.enabled_capabilities),
        "elephant_identity_text": elephant_identity_text,
    }


def _session_payload(session: Episode) -> dict[str, Any]:
    return {
        "episode_id": session.episode_id,
        "personal_model_id": session.personal_model_id,
        "elephant_id": session.elephant_id,
        "status": session.status,
        "started_at": _iso(session.started_at),
        "updated_at": _iso(session.updated_at),
        "parent_episode_id": session.parent_episode_id,
        "interruption_state": session.interruption_state,
    }


def _work_item_payload(work_item: object) -> dict[str, Any]:
    return {
        "work_item_id": getattr(work_item, "work_item_id", ""),
        "session_id": getattr(work_item, "session_id", ""),
        "title": getattr(work_item, "title", ""),
        "status": getattr(work_item, "status", ""),
        "priority": getattr(work_item, "priority", ""),
    }


def _recall_item_payload(evidence: RecallEvidence) -> dict[str, Any]:
    return {
        "evidence_ref": evidence.evidence_id,
        "episode_id": evidence.episode_id,
        "kind": evidence.kind,
        "content": evidence.content,
        "source_id": evidence.source_id,
        "source_kind": evidence.source_kind,
        "work_item_ids": list(evidence.work_item_ids),
        "tags": list(evidence.tags),
        "created_at": _iso(evidence.created_at) if evidence.created_at is not None else None,
    }


def _plan_payload(plan: PlanDraft | None) -> dict[str, Any] | None:
    if plan is None:
        return None
    return {
        "plan_id": plan.plan_id,
        "work_item_id": plan.work_item_id,
        "session_id": plan.session_id,
        "steps": [
            {
                "step_id": step.step_id,
                "title": step.title,
                "rationale": step.rationale,
                "dependency_refs": list(step.dependency_refs),
            }
            for step in plan.steps
        ],
        "rationale": plan.rationale,
    }


def _execution_payload(execution: ExecutionResult | None) -> dict[str, Any] | None:
    if execution is None:
        return None
    return {
        "execution_id": execution.execution_id,
        "episode_id": execution.episode_id,
        "outcome": execution.outcome,
        "summary": execution.summary,
        "prompt_tokens": execution.prompt_tokens,
        "completion_tokens": execution.completion_tokens,
        "total_tokens": execution.total_tokens,
        "produced_artifact_ids": list(execution.produced_artifact_ids),
        "telemetry_event_ids": list(execution.telemetry_event_ids),
        "side_effects": list(execution.side_effects),
    }


def _state_focus_payload(state_focus: StateFocusDecision | None) -> dict[str, Any] | None:
    if state_focus is None:
        return None
    return {
        "focus_family": state_focus.focus_family,
        "confidence": state_focus.confidence,
        "focus_work_item_ids": list(state_focus.focus_work_item_ids),
        "provisional_work_item_seed": state_focus.provisional_work_item_seed,
        "continuity_signal": state_focus.continuity_signal,
        "focus_scope": state_focus.focus_scope,
        "context_budget": state_focus.context_budget,
        "embedding_available": state_focus.embedding_available,
        "degradation_mode": state_focus.degradation_mode,
        "needs_focus_model_assist": state_focus.needs_focus_model_assist,
        "focus_assist_outcome": state_focus.focus_assist_outcome,
        "selection_path": state_focus.selection_path,
        "reasons": [_state_focus_reason_payload(reason) for reason in state_focus.reasons],
        "candidate_scores": [_state_focus_candidate_score_payload(score) for score in state_focus.candidate_scores],
        "audit_trace": list(state_focus.audit_trace),
    }


def _session_context_epoch_payload(epoch: SessionContextEpoch) -> dict[str, Any]:
    return session_context_epoch_payload(epoch)


def _state_focus_reason_payload(reason: StateFocusReason) -> dict[str, Any]:
    return {
        "code": reason.code,
        "detail": reason.detail,
        "weight": reason.weight,
    }


def _state_focus_candidate_score_payload(score: StateFocusCandidateScore) -> dict[str, Any]:
    return {
        "candidate_id": score.candidate_id,
        "kind": score.kind,
        "label": score.label,
        "total_score": score.total_score,
        "heuristics_score": score.heuristics_score,
        "embedding_score": score.embedding_score,
        "reasons": [_state_focus_reason_payload(reason) for reason in score.reasons],
        "metadata": dict(score.metadata),
    }


def _stage_payload(stage: Any) -> Any:
    return {
        "stage": stage.stage,
        "detail": stage.detail,
        "recorded_at": _iso(stage.recorded_at),
    }


def _restore_state_focus_reason(payload: Mapping[str, Any]) -> StateFocusReason:
    return StateFocusReason(
        code=str(payload.get("code") or "").strip(),
        detail=str(payload.get("detail") or "").strip(),
        weight=float(payload.get("weight") or 0.0),
    )


def _restore_state_focus_candidate_score(payload: Mapping[str, Any]) -> StateFocusCandidateScore:
    return StateFocusCandidateScore(
        candidate_id=str(payload.get("candidate_id") or "").strip(),
        kind=str(payload.get("kind") or "").strip(),
        label=str(payload.get("label") or "").strip(),
        total_score=float(payload.get("total_score") or 0.0),
        heuristics_score=float(payload.get("heuristics_score") or 0.0),
        embedding_score=float(payload.get("embedding_score") or 0.0),
        reasons=tuple(
            _restore_state_focus_reason(reason)
            for reason in payload.get("reasons", ())
            if isinstance(reason, Mapping)
        ),
        metadata={
            str(key): str(value)
            for key, value in dict(payload.get("metadata") or {}).items()
        },
    )


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    return tuple(str(item) for item in value if str(item))


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _event_payload(event: EventEnvelope | None) -> dict[str, Any] | None:
    if event is None:
        return None
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "episode_id": event.episode_id,
        "source": event.source,
        "payload": dict(event.payload),
    }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
