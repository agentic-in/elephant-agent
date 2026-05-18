from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from packages.contracts.layers import Episode
from packages.contracts.runtime import EventEnvelope, ExecutionResult, PersonalModelRuntimeState, PromptMessage
from packages.kernel import (
    KernelDependencies,
    KernelOutcome,
    KernelStageRecord,
    KernelService,
    KernelSourceRequest,
    ReconciliationPipeline,
    StateReconciler,
)
from packages.context.compress import split_for_compress, _deterministic_summary
from packages.kernel.context_compaction import projection_compaction_detail
from packages.kernel.episode_state_machine import open_next_episode as _open_next_episode
from packages.storage.repository_support import DEFAULT_PERSONAL_MODEL_ID
from packages.state import (
    ensure_elephant_identity_file,
    is_companion_mode,
)

if TYPE_CHECKING:
    from apps.cli.runtime import CliRuntime


_USAGE_AFTER_TURN_COMPACTION_RATIO = 0.85


@dataclass(frozen=True, slots=True)
class _RequesterScopedToolCapability:
    tool_runtime: Any
    requester: str
    descriptor: Any

    def invoke(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        *,
        session_id: str,
    ) -> ExecutionResult:
        return self.tool_runtime.invoke(
            tool_name,
            arguments,
            session_id=session_id,
            requester=self.requester,
        )


def start_episode(
    runtime: CliRuntime,
    *,
    profile_id: str | None = None,
    display_name: str | None = None,
    mode: str | None = None,
    session_id: str | None = None,
) -> Episode:
    loaded = runtime.profile_loader.load(
        profile_id=profile_id,
        display_name=display_name,
        mode=mode,
    )
    profile_state = replace(loaded.state, preferences=loaded.state.preferences)
    now = datetime.now(timezone.utc)
    session = Episode(
        episode_id=session_id or uuid4().hex,
        state_id=f"state:{profile_state.profile_id}:default",
        personal_model_id=profile_state.profile_id,
        entry_surface="cli",
        elephant_id="",
        status="open",
        started_at=now,
        updated_at=now,
    )
    runtime.repository.upsert_personal_model_runtime_state(profile_state, updated_at=now)
    runtime.repository.upsert_episode(session)
    current_profile = runtime._load_profile(profile_state.profile_id)
    runtime._write_snapshot(
        profile=profile_state,
        session=session,
        work_items=(),
        recall_items=(),
        plan=None,
        execution=None,
        delivery=None,
        stages=(),
        event=None,
        elephant_identity_text=current_profile.elephant_identity_text,
        state_focus=None,
    )
    return session


def create_elephant_session(
    runtime: CliRuntime,
    *,
    elephant_id: str,
    profile_id: str | None = None,
    display_name: str | None = None,
    mode: str | None = None,
    session_id: str | None = None,
    seed_elephant_identity_text,
    seed_elephant_identity_file_text,
) -> Episode:
    resolved_elephant_id = elephant_id.strip()
    if not resolved_elephant_id:
        raise ValueError("elephant name is required")
    if runtime.latest_session_for_elephant(resolved_elephant_id) is not None:
        raise ValueError(f"elephant already exists: {resolved_elephant_id}")
    runtime.paths.elephant_file_path(resolved_elephant_id).mkdir(parents=True, exist_ok=True)
    source_profile = runtime._load_profile(profile_id or runtime.current_profile().state.profile_id)
    personal_model_id = runtime.repository.ensure_default_personal_model(
        personal_model_id=DEFAULT_PERSONAL_MODEL_ID,
    ).personal_model_id
    if display_name is None:
        elephant_display_name = resolved_elephant_id.replace("-", " ").title()
    else:
        elephant_display_name = display_name.strip()
    elephant_mode = mode or source_profile.state.mode
    elephant_companion = source_profile.companion if is_companion_mode(elephant_mode) else None
    elephant_identity_text = seed_elephant_identity_text(
        source_profile,
        display_name=elephant_display_name,
        mode=elephant_mode,
        companion=elephant_companion,
    )
    elephant_file_root = runtime.paths.elephant_file_path(resolved_elephant_id)
    ensure_elephant_identity_file(
        elephant_file_root,
        seed_elephant_identity_file_text(
            source_profile,
            elephant_id=resolved_elephant_id,
            display_name=elephant_display_name,
            mode=elephant_mode,
            companion=elephant_companion,
        ),
    )
    profile_state = replace(
        source_profile.state,
        profile_id=personal_model_id,
        preferences=source_profile.state.preferences,
    )
    now = datetime.now(timezone.utc)
    session = Episode(
        episode_id=session_id or uuid4().hex,
        state_id=f"state:{resolved_elephant_id}",
        personal_model_id=profile_state.profile_id,
        entry_surface="cli",
        elephant_id=resolved_elephant_id,
        status="open",
        started_at=now,
        updated_at=now,
    )
    runtime.repository.upsert_personal_model_runtime_state(profile_state, updated_at=now)
    runtime.repository.upsert_episode(session)
    elephant_state = runtime.ensure_elephant_state(
        session,
        elephant_identity_text=elephant_identity_text,
        elephant_display_name=elephant_display_name,
        elephant_mode=elephant_mode,
        elephant_companion=elephant_companion,
    )
    runtime.repository.switch_state(elephant_state.state_id)
    runtime._write_snapshot(
        profile=profile_state,
        session=session,
        work_items=(),
        recall_items=(),
        plan=None,
        execution=None,
        delivery=None,
        stages=(),
        event=None,
        elephant_identity_text=elephant_identity_text,
        state_focus=None,
    )
    return session


def open_next_episode(
    runtime: CliRuntime,
    episode_id: str,
    *,
    next_episode_id: str | None = None,
    reason: str = "wake_boundary",
    summary: str = "",
):
    now = datetime.now(timezone.utc)
    transition = _open_next_episode(
        runtime.repository,
        episode_id,
        reason=reason,
        summary=summary,
        current=now,
        episode_id=next_episode_id,
        semantic_summary_indexer=getattr(runtime, "_semantic_summary_indexer", None),
    )
    runtime._ensure_learning_worker_if_needed()
    session = transition.episode
    profile = runtime._load_profile(session.personal_model_id)
    runtime._write_snapshot(
        profile=profile.state,
        session=session,
        work_items=(),
        recall_items=(),
        plan=None,
        execution=None,
        delivery=None,
        stages=(),
        event=None,
        elephant_identity_text=profile.elephant_identity_text,
        state_focus=None,
    )
    return transition


def explain_next_step(
    runtime: CliRuntime,
    *,
    session_id: str,
    prompt: str,
    state_query: str | None = None,
    tool_name: str | None = None,
    tool_arguments: Mapping[str, Any] | None = None,
    delivery_payload: Mapping[str, Any] | None = None,
    event_payload: Mapping[str, str] | None = None,
) -> KernelOutcome:
    return runtime._run_turn(
        session_id=session_id,
        prompt=prompt,
        state_query=state_query,
        tool_name=tool_name,
        tool_arguments=tool_arguments,
        delivery_payload=delivery_payload,
        event_payload=event_payload,
    )


def generate_opening_reply(
    runtime: CliRuntime,
    *,
    session_id: str,
    prompt: str,
    opening_label: str,
) -> KernelOutcome | None:
    if runtime.model_provider.active_profile() is None:
        return None
    return runtime._run_turn(
        session_id=session_id,
        prompt=prompt,
        event_type="turn.internal",
        source="cli.startup",
        event_payload={
            "message": f"startup opening ({opening_label})",
            "summary": f"startup opening ({opening_label})",
            "content": "",
            "allow_embeddings": "false",
        },
        record_input_event=False,
        record_outcome_event=False,
        capture_experience=False,
        apply_growth=False,
    )


def run_turn(
    runtime: CliRuntime,
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
    session = runtime._load_session(session_id)
    loaded_profile = runtime._load_profile(session.personal_model_id)
    profile = loaded_profile.state
    episode = runtime.repository.load_episode(session.episode_id)
    route_state = runtime.repository.load_state(episode.state_id) if episode is not None else None
    dependencies = runtime._build_kernel_dependencies(session, profile)
    service = KernelService(dependencies=dependencies)
    payload = {
        "message": prompt,
        "content": prompt,
        "summary": prompt,
        "state_query": state_query or "",
        "tool_name": tool_name or "",
    }
    if event_payload is not None:
        payload.update(dict(event_payload))
    event = EventEnvelope(
        event_id=f"event:{uuid4().hex}",
        event_type=event_type,
        episode_id=session.episode_id,
        source=source,
        payload=payload,
    )
    outcome = service.run(
        KernelSourceRequest(
            route_id=session.episode_id,
            prompt=prompt,
            surface=source,
            source_event_type=event_type,
            source_payload=payload,
            source_event_id=event.event_id,
            route_profile_id=session.personal_model_id,
            route_status=session.status,
            route_interruption_state=session.interruption_state,
            route_started_at=session.started_at,
            personal_model_id=route_state.personal_model_id if route_state is not None else session.personal_model_id,
            state_id=route_state.state_id if route_state is not None else None,
            episode_id=session.episode_id,
            state_query=state_query,
            tool_name=tool_name,
            tool_arguments=dict(tool_arguments or {}),
            delivery_payload=dict(delivery_payload or {}),
        )
    )
    performed_turn_reconciliation = record_input_event or record_outcome_event
    refreshed_session = runtime._load_session(session.episode_id)
    persisted_profile = runtime._load_profile(refreshed_session.personal_model_id)
    decision_summary = _decision_summary_from_outcome(outcome)
    observed_event = replace(event, payload=_payload_with_turn_reasoning(event.payload, outcome, decision_summary=decision_summary))
    if performed_turn_reconciliation:
        turn_observation = ReconciliationPipeline().observe_turn(
            inbound_event=observed_event,
            execution=outcome.execution,
            decision_summary=decision_summary,
            include_input_event=record_input_event,
            include_outcome_event=record_outcome_event,
            source=source,
            profile_id=refreshed_session.personal_model_id,
            elephant_id=refreshed_session.elephant_id,
            turn_messages=outcome.turn_messages,
        )
        StateReconciler().reconcile_turn(
            repository=runtime.repository,
            recall_runtime=runtime.recall_runtime,
            observation=turn_observation,
        )
    experience = runtime._append_outcome_experience(outcome) if capture_experience else None
    if apply_growth:
        runtime._append_outcome_growth(outcome, experience=experience)
    snapshot_work_items: tuple[object, ...] = ()
    snapshot_recall_items = (
        runtime.inspect_recall_evidence(refreshed_session.episode_id)
        if performed_turn_reconciliation
        else outcome.recall_items
    )
    runtime._write_snapshot(
        profile=persisted_profile.state,
        session=refreshed_session,
        work_items=snapshot_work_items,
        recall_items=snapshot_recall_items,
        plan=None,
        execution=outcome.execution,
        delivery=outcome.delivery,
        stages=outcome.stages,
        event=outcome.event,
        elephant_identity_text=persisted_profile.elephant_identity_text,
        state_focus=None,
        context=outcome.context,
        turn_messages=outcome.turn_messages,
    )
    _queue_projection_embedding_backfill(
        runtime,
        messages=outcome.turn_messages,
        thread_focus=_projection_thread_focus(snapshot_work_items),
    )
    outcome = _compact_snapshot_after_high_usage(runtime, outcome)
    return outcome


def _render_messages_text(messages: tuple[PromptMessage, ...], *, limit: int = 0) -> str:
    """Render prompt messages into concise text for compress evidence.

    Only includes user queries and assistant final responses.
    Tool calls are summarized as "[N tool calls]", tool results are omitted.
    limit=0 means no truncation (best effort — pass everything).
    """
    lines: list[str] = []
    total = 0
    pending_tool_names: list[str] = []
    for msg in messages:
        role = msg.role or "unknown"
        content = msg.content.strip()
        if role == "tool":
            # Skip tool results entirely — they're noise for summary
            continue
        if role == "assistant" and msg.tool_calls and not content:
            # Collect tool call names but don't render the empty assistant message
            for c in msg.tool_calls:
                name = str(c.get("function", {}).get("name") or c.get("name") or "tool")
                pending_tool_names.append(name)
            continue
        # Flush pending tool calls as a compact line
        if pending_tool_names:
            tool_line = f"[used {len(pending_tool_names)} tools: {', '.join(dict.fromkeys(pending_tool_names))}]"
            total += len(tool_line)
            if limit and total > limit:
                lines.append("... (truncated)")
                break
            lines.append(tool_line)
            pending_tool_names = []
        if not content:
            continue
        if role == "assistant" and msg.tool_calls:
            # Assistant with both tool_calls and content — just show content
            call_summary = f"[+{len(msg.tool_calls)} tool calls]"
            line = f"assistant {call_summary}: {content[:300]}"
        elif role == "user":
            line = f"user: {content}"
        elif role == "assistant":
            line = f"assistant: {content}"
        else:
            continue
        total += len(line)
        if limit and total > limit:
            lines.append("... (truncated)")
            break
        lines.append(line)
    # Flush any remaining pending tools
    if pending_tool_names:
        tool_line = f"[used {len(pending_tool_names)} tools: {', '.join(dict.fromkeys(pending_tool_names))}]"
        lines.append(tool_line)
    return "\n".join(lines)


def _reflect_compress_summary(
    runtime: CliRuntime,
    outcome: KernelOutcome,
    *,
    frozen_epoch: Any,
    to_summarize: tuple[PromptMessage, ...],
    tail: tuple[PromptMessage, ...],
    context_limit: int,
    log: Any,
) -> tuple[str, str]:
    fallback_note = "llm_failed_using_heuristic"
    previous_sub_agent_active = bool(getattr(runtime, "sub_agent_active", False))
    delegation_armed = False
    if previous_sub_agent_active:
        # Internal context compaction is allowed to run reflect delegation even
        # inside a sub-agent runtime; temporarily drop the guard only for this call.
        object.__setattr__(runtime, "sub_agent_active", False)
        delegation_armed = True
    try:
        from apps.reflect.runner import run_reflect_agent
        from packages.contracts.runtime import LearningJob

        token_budget = max(400, int(context_limit * 0.08))
        compress_metadata = {
            "compressed_messages": _render_messages_text(to_summarize, limit=0),
            "previous_summary": frozen_epoch.compacted_history_summary,
            "token_budget": str(token_budget),
            "tail_hint": _render_messages_text(tail, limit=1500),
            # Must use comma-separated string rather than list, because _mapping_text will
            # turn list into "['compress']" via str(value), causing feature parsing to fail
            "features": "compress",
        }
        session = runtime._load_session(outcome.route_session_id)
        now = datetime.now(timezone.utc)
        # Transient job instance, used only to pass metadata/episode/state to run_reflect_agent
        job = LearningJob(
            job_id=f"sync-compress:{uuid4().hex[:12]}",
            job_type="context_compaction",
            trigger="context_compaction",
            status="running",
            personal_model_id=session.personal_model_id,
            state_id=session.state_id,
            episode_id=outcome.route_session_id,
            loop_id=None,
            summary="synchronous context compression",
            progress_stage="agent_running",
            progress_detail="synchronous compress",
            attempt_count=1,
            max_attempts=1,
            available_at=now,
            created_at=now,
            started_at=now,
            finished_at=None,
            worker_id="context-compress-sync",
            last_error="",
            metadata=compress_metadata,
        )
        result = run_reflect_agent(runtime, job, explicit_features=("compress",), persist_result=False)
        return result.summary.strip(), fallback_note
    except Exception as exc:
        log.warning("context compress agent failed: %s", exc, exc_info=True)
        return "", fallback_note
    finally:
        if delegation_armed:
            object.__setattr__(runtime, "sub_agent_active", previous_sub_agent_active)



def _compact_snapshot_after_high_usage(runtime: CliRuntime, outcome: KernelOutcome) -> KernelOutcome:
    """Trigger synchronous reflect-based context compression when usage is high."""
    import logging
    log = logging.getLogger(__name__)

    usage_tokens = _execution_context_usage_tokens(outcome.execution)
    context_limit = _context_limit_tokens(runtime, outcome)
    if usage_tokens <= 0 or context_limit <= 0:
        log.debug("compress skipped: usage=%s limit=%s", usage_tokens, context_limit)
        return outcome
    trigger_tokens = max(1, int(context_limit * _USAGE_AFTER_TURN_COMPACTION_RATIO))
    if usage_tokens < trigger_tokens:
        log.debug("compress skipped: usage %s < trigger %s (limit=%s ratio=%s)",
                  usage_tokens, trigger_tokens, context_limit, _USAGE_AFTER_TURN_COMPACTION_RATIO)
        return outcome

    log.info("compress triggered: usage=%s trigger=%s limit=%s session=%s",
             usage_tokens, trigger_tokens, context_limit, outcome.route_session_id)

    # Load the frozen epoch to get history messages
    from apps.cli.runtime_snapshot import restore_snapshot_session_context_epoch
    from apps.cli.snapshot_io import load_snapshot_payload
    snapshot_path = getattr(runtime, "snapshot_path", None)
    if snapshot_path is None:
        log.warning("compress skipped: snapshot_path is None")
        _emit_compress_skip_stage(runtime, outcome, "snapshot_path_missing", usage_tokens)
        return outcome
    snapshot = load_snapshot_payload(snapshot_path) if snapshot_path.exists() else None
    frozen_epoch = restore_snapshot_session_context_epoch(snapshot, session_id=outcome.route_session_id) if snapshot else None
    if frozen_epoch is None:
        log.warning("compress skipped: frozen_epoch is None (snapshot=%s)", snapshot is not None)
        _emit_compress_skip_stage(runtime, outcome, "epoch_missing", usage_tokens)
        return outcome
    if not frozen_epoch.frozen:
        log.warning("compress skipped: epoch not frozen yet")
        _emit_compress_skip_stage(runtime, outcome, "epoch_not_frozen", usage_tokens)
        return outcome

    # Key design: when a single turn contains many tool calls/thinking (e.g. 19 tools at once),
    # even the first turn can overflow context. history_messages may be small in count,
    # but a single tool result can be very large and must be compressed. So we no longer require >= 4 messages.
    # We only require at least 1 history message, otherwise there is nothing to compress.
    history_count = len(frozen_epoch.history_messages)
    if history_count == 0:
        log.warning("compress skipped: history_messages is empty")
        _emit_compress_skip_stage(runtime, outcome, "history_empty", usage_tokens)
        return outcome

    # split_for_compress protects the recent tail while moving older or oversized
    # completed context into a reference summary. A single-turn overflow can
    # still compress tool messages, or a huge user message when there is no
    # richer tail to preserve.
    to_summarize, tail = split_for_compress(
        frozen_epoch.history_messages,
        protected_tail_turns=2,
    )
    if not to_summarize:
        # Degraded retry: only protect the tail messages of the last 1 user turn
        to_summarize, tail = split_for_compress(
            frozen_epoch.history_messages,
            protected_tail_turns=1,
        )
    if not to_summarize:
        log.warning("compress skipped: nothing to summarize (msgs=%d)",
                    history_count)
        _emit_compress_skip_stage(runtime, outcome, f"nothing_to_summarize_{history_count}", usage_tokens)
        return outcome

    # Emit a "compressing" stage so the TUI shows progress.
    _emit_post_snapshot_kernel_stage(
        runtime,
        outcome,
        KernelStageRecord(
            stage="context-compact",
            detail=(
                f"reason=usage "
                f"messages={len(frozen_epoch.history_messages)}->{len(tail)} "
                f"compressing={len(to_summarize)}"
            ),
            recorded_at=datetime.now(timezone.utc),
        ),
    )

    summary, fallback_note = _reflect_compress_summary(
        runtime,
        outcome,
        frozen_epoch=frozen_epoch,
        to_summarize=to_summarize,
        tail=tail,
        context_limit=context_limit,
        log=log,
    )

    # Fallback: if LLM compress fails or returns an empty summary, history must still be force-truncated;
    # otherwise the next turn will repeat the same overflow + skip loop. compress is blocking for UX,
    # so guaranteeing the next turn can run is the priority. Here we use a minimal heuristic reference summary.
    if not summary:
        log.warning(
            "context compress fallback: hard-truncating history without LLM summary "
            "(history=%d to_summarize=%d tail=%d)",
            history_count, len(to_summarize), len(tail),
        )
        summary = _deterministic_summary(to_summarize, history_count=history_count)
        _emit_post_snapshot_kernel_stage(
            runtime,
            outcome,
            KernelStageRecord(
                stage="context-compact",
                detail=(
                    f"reason=fallback tokens={usage_tokens}->? "
                    f"messages={history_count}->{len(tail)} "
                    f"compacted_messages={len(to_summarize)} tail={len(tail)} "
                    f"note={fallback_note}"
                ),
                recorded_at=datetime.now(timezone.utc),
            ),
        )

    # Update the epoch: summary replaces Episode resume in frozen_prefix,
    # optionally refresh PM facts, keep only tail messages.
    from packages.context.session_projection import compact_session_context_epoch
    updated_epoch, compaction_result = compact_session_context_epoch(
        frozen_epoch,
        total_tokens=context_limit,
        reason="usage",
        force=True,
        summary_text=summary,
        tail_messages=tail,
    )

    # Refresh Episode resume in frozen_prefix with the new summary
    from packages.kernel.generation_context import (
        _strip_prompt_sections,
        _append_prompt_section,
    )
    updated_prefix = _strip_prompt_sections(updated_epoch.frozen_prefix, "Episode resume")
    updated_prefix = _append_prompt_section(
        updated_prefix,
        "Episode resume",
        (f"Reference summary: {summary}",),
    )
    from dataclasses import replace as _dc_replace
    updated_epoch = _dc_replace(updated_epoch, frozen_prefix=updated_prefix)

    # Write the compacted epoch back to snapshot.
    # IMPORTANT: The compress sub-agent runs in a child episode that shares the
    # same snapshot_path. Its _write_snapshot overwrites the "session" key with
    # the child episode, causing restore_session_context_epoch to fail on
    # session_id mismatch on the next parent turn. We must atomically restore
    # both session_context_epoch AND the session key to the parent episode.
    from apps.cli.runtime_snapshot import _session_context_epoch_payload
    from apps.cli.snapshot_io import load_snapshot_payload, write_snapshot_payload
    _snap = load_snapshot_payload(runtime.snapshot_path) or {}
    _snap["session_context_epoch"] = _session_context_epoch_payload(updated_epoch)
    # Restore session key — only episode_id matters for epoch session matching.
    _existing_session = _snap.get("session")
    if not isinstance(_existing_session, dict) or _existing_session.get("episode_id") != outcome.route_session_id:
        _snap["session"] = {"episode_id": outcome.route_session_id}
    write_snapshot_payload(runtime.snapshot_path, _snap)

    # Persist summary to episode so dashboard can display it
    try:
        with runtime.repository.connection() as connection:
            connection.execute(
                "UPDATE episodes SET exit_summary = ? WHERE episode_id = ?",
                (summary, outcome.route_session_id),
            )
            connection.commit()
    except Exception:
        pass

    detail = projection_compaction_detail(compaction_result)
    record = KernelStageRecord(
        stage="context-compact",
        detail=detail,
        recorded_at=datetime.now(timezone.utc),
    )
    _emit_post_snapshot_kernel_stage(runtime, outcome, record)
    log.info(
        "compress completed: %d->%d messages, summary_len=%d, session=%s",
        history_count, len(tail), len(summary), outcome.route_session_id,
    )
    return replace(outcome, stages=(*outcome.stages, record))


def _execution_context_usage_tokens(execution: ExecutionResult) -> int:
    return max(
        _safe_token_count(getattr(execution, "prompt_tokens", 0)),
        _safe_token_count(getattr(execution, "total_tokens", 0)),
    )


def _context_limit_tokens(runtime: CliRuntime, outcome: KernelOutcome) -> int:
    context_limit = _safe_token_count(getattr(outcome.context, "token_budget", 0))
    if context_limit > 0:
        return context_limit
    try:
        return _safe_token_count(runtime.active_provider_context_window())
    except Exception:
        return 0


def _safe_token_count(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _emit_post_snapshot_kernel_stage(runtime: CliRuntime, outcome: KernelOutcome, record: KernelStageRecord) -> None:
    observer = getattr(runtime, "kernel_event_observer", None)
    if not callable(observer):
        return
    try:
        observer(
            {
                "event_id": f"telemetry:{outcome.route_session_id}:context-compact:{uuid4().hex}",
                "event_type": "kernel.stage",
                "session_id": outcome.route_session_id,
                "source": "kernel",
                "payload": {
                    "stage": record.stage,
                    "detail": record.detail,
                    "recorded_at": record.recorded_at.isoformat(),
                    "event_id": outcome.event.event_id,
                },
            }
        )
    except Exception:
        return


def _emit_compress_skip_stage(
    runtime: CliRuntime,
    outcome: KernelOutcome,
    reason: str,
    usage_tokens: int,
) -> None:
    """Emit a diagnostic stage when compress was triggered but bailed early.

    This makes the failure visible in TUI logs and reflect history rather
    than silently returning. The detail string MUST include 'tokens=X->X'
    (with '->' arrow) so that _format_compaction_notice in turn_metrics.py
    parses it as a token segment; otherwise the TUI only renders the bare
    word 'usage' which is useless for diagnostics.
    """
    _emit_post_snapshot_kernel_stage(
        runtime,
        outcome,
        KernelStageRecord(
            stage="context-compact",
            detail=(
                f"reason=skip:{reason} "
                f"tokens={usage_tokens}->{usage_tokens} "
                f"messages=0->0"
            ),
            recorded_at=datetime.now(timezone.utc),
        ),
    )


def _queue_projection_embedding_backfill(
    runtime: CliRuntime,
    *,
    messages: tuple[PromptMessage, ...],
    thread_focus: str,
) -> None:
    """Embedding backfill hook, currently a no-op.

    Embedding-based semantic anchoring has been removed from the context
    compression path.
    """
    return


def _projection_thread_focus(work_items: tuple[Any, ...]) -> str:
    active_work_item = next(
        (
            work_item
            for work_item in work_items
            if str(getattr(work_item, "status", "") or "").strip() == "active"
            and str(getattr(work_item, "title", "") or "").strip()
        ),
        None,
    )
    if active_work_item is None:
        active_work_item = next((work_item for work_item in work_items if str(getattr(work_item, "title", "") or "").strip()), None)
    return str(getattr(active_work_item, "title", "") or "").strip() if active_work_item is not None else ""


def inspect_wake_continuity(runtime: CliRuntime, episode_id: str, *, result_cls):
    session = runtime._load_session(episode_id)
    profile = runtime._load_profile(session.personal_model_id)
    recovery = runtime._planning_recall_evidence_recovery(session)
    state = runtime.current_elephant_state()
    state_focus = ""
    if state is not None:
        state_focus = state.summary.strip()
    wake_summary = state_focus if state_focus else "No active elephant focus is available."
    plan = None
    rationale_event = _wake_rationale_event(
        episode_id=session.episode_id,
        wake_summary=wake_summary,
        recovery=recovery,
    )
    wake_observation = ReconciliationPipeline().observe_wake(
        session_id=session.episode_id,
        durable_events=(rationale_event,),
        decision_summary=wake_summary,
    )
    reconciliation = StateReconciler().reconcile_wake(
        repository=runtime.repository,
        recall_runtime=runtime.recall_runtime,
        observation=wake_observation,
        inspect_only=True,
    )
    return result_cls(
        profile=profile.state,
        session=session,
        wake_action="continue" if state_focus else "idle",
        wake_summary=wake_summary,
        state_focus=state_focus,
        applied=False,
        plan=plan,
        reconciliation=reconciliation,
        retrieval=recovery.retrieval,
        resume_packet=recovery.resume_packet,
    )


def _wake_rationale_event(
    *,
    episode_id: str,
    wake_summary: str,
    recovery,
) -> EventEnvelope:
    scope_summary = ", ".join(recovery.scope_episode_ids) or episode_id
    content = (
        f"Wake recovery searched scope {scope_summary}. "
        f"Reason: {recovery.scope_reason}. "
        f"Next step: {wake_summary}"
    )
    return EventEnvelope(
        event_id=f"event:{uuid4().hex}",
        event_type="wake.recovery.rationale",
        episode_id=episode_id,
        source="cli.wake",
        payload={
            "content": content,
            "summary": "wake recovery scope selected for elephant continuity",
            "signal_kind": "semantic",
            "tags": "continuity,recovery,wake,scope-aware,resume-packet",
            "scope_episode_ids": ",".join(recovery.scope_episode_ids),
            "scope_reason": recovery.scope_reason,
            "query": recovery.query,
            "resume_packet_summary": recovery.resume_packet.summary if getattr(recovery, "resume_packet", None) is not None else "",
            "resume_packet_evidence_ids": ",".join(
                recovery.resume_packet.evidence_ids if getattr(recovery, "resume_packet", None) is not None else ()
            ),
        },
    )


def _compact_runtime_text(text: str, *, limit: int = 220) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3].rstrip()}..."


def _payload_with_turn_reasoning(
    payload: Mapping[str, str],
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


def _decision_summary_from_outcome(outcome: KernelOutcome) -> str:
    if outcome.state.summary.strip():
        return outcome.state.summary.strip()
    return outcome.execution.summary.strip()


def build_kernel_dependencies(
    runtime: CliRuntime,
    session: Episode,
    profile: PersonalModelRuntimeState,
    *,
    recall_capability_cls,
    context_capability_cls,
    telemetry_cls,
    delivery_capability_cls,
) -> KernelDependencies:
    recall = recall_capability_cls(recall_runtime=runtime.recall_runtime, repository=runtime.repository)
    model_tools = _RequesterScopedToolCapability(
        tool_runtime=runtime.tool_runtime,
        requester="model",
        descriptor=runtime.tool_runtime.descriptor,
    )
    embedding_service = runtime.recall_runtime.evidence_retriever.embedding_service
    semantic_summary_indexer = None
    if runtime.semantic_index_bundle is not None and embedding_service is not None:
        from packages.evidence import SemanticSummaryIndexer

        semantic_summary_indexer = SemanticSummaryIndexer(
            semantic_index=runtime.semantic_index_bundle.service,
            embedding_service=embedding_service,
            repository=runtime.repository,
        )
    return KernelDependencies(
        storage=runtime.repository,
        context=context_capability_cls(
            profile_loader=runtime.profile_loader,
            repository=runtime.repository,
            prompt_mode="full",
            snapshot_path=runtime.snapshot_path,
            total_tokens=runtime.active_provider_context_window(),
            tool_runtime=runtime.tool_runtime,
            skill_runtime=runtime.skill_runtime,
            skill_prompt_context=runtime.skill_prompt_context,
            workspaces_dir=runtime.paths.workspaces_dir,
            startup_cwd=Path.cwd(),
            summary_model_provider=runtime.model_provider,
            embedding_service=embedding_service,
        ),
        recall=recall,
        model_provider=runtime.model_provider,
        telemetry=telemetry_cls(runtime.snapshot_path, observer=runtime.kernel_event_observer),
        tools=model_tools,
        delivery=delivery_capability_cls(),
        embedding_service=embedding_service,
        security_policy=runtime.security_policy,
        skill_runtime=runtime.skill_runtime,
        semantic_summary_indexer=semantic_summary_indexer,
    )
