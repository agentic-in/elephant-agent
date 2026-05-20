from __future__ import annotations

import concurrent.futures
import sys
from uuid import uuid4

from .context_compaction import (
    append_episode_continuity_packet,
    compact_context_after_usage,
    compaction_step_metadata,
    episode_continuity_packet,
    flush_projection_cache,
    latest_compacted_projection,
    projection_compaction_detail,
    retry_context_after_provider_overflow,
    stage_context_projection,
    stage_context_usage,
)
from .execution_support import execute_kernel_turn
from .generation_context import build_context_for_generation
from .lifecycle_support import (
    close_loop_lifecycle,
    close_episode_lifecycle,
    KernelStepRecorder,
    open_loop_lifecycle,
    open_episode_lifecycle,
    resolve_runtime_identity,
)
from .runtime_support import *  # noqa: F401,F403
_SUPPORT_UTC_NOW = _utc_now


def _clock_now() -> datetime:
    runtime_module = sys.modules.get("packages.kernel.runtime")
    runtime_now = getattr(runtime_module, "_utc_now", None) if runtime_module is not None else None
    if callable(runtime_now):
        return runtime_now()
    return _SUPPORT_UTC_NOW()


_STATE_SUMMARY_LIMIT = 480


def _compact_state_projection_text(value: object, *, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip(" ,;|") + "..."


def _primary_learning_trigger(
    *,
    execution: "ExecutionResult",
    steps: tuple["Step", ...],
) -> str:
    """Classify the learning-job trigger for the just-finished Loop.

    Per system-layer-model docs:755-762 reflection is a lightweight
    post-Episode triage. We distinguish three kernel-visible triggers:

    * ``checkpoint`` — Loop parked at a WaitCondition (outcome=paused)
      or emitted a checkpoint Step. Learning-worker runs the lighter
      triage path.
    * ``episode_close`` — normal terminal outcome.
    * ``episode_failed`` — Loop failed; worker may downgrade triage to
      a no-op depending on signal.
    """
    outcome = str(getattr(execution, "outcome", "") or "").strip()
    if outcome == "paused":
        return "checkpoint"
    checkpoint_seen = any(
        step.action == "checkpoint" and step.status == "completed" for step in steps
    )
    if checkpoint_seen:
        return "checkpoint"
    if outcome == "failed":
        return "episode_failed"
    return "episode_close"


def _request_uses_learning_agent_context(request: "KernelSourceRequest") -> bool:
    payload = getattr(request, "source_payload", {})
    if not isinstance(payload, dict):
        try:
            payload = dict(payload or {})
        except (TypeError, ValueError):
            payload = {}
    context_mode = str(payload.get("context_mode") or "").strip().lower()
    surface = str(getattr(request, "surface", "") or "").strip().lower()
    return context_mode == "learning_agent" or surface.startswith("learning.")


def _suppress_primary_learning_for_request(request: "KernelSourceRequest") -> bool:
    source_event_type = str(getattr(request, "source_event_type", "") or "").strip().lower()
    return _request_uses_learning_agent_context(request) or source_event_type == "turn.internal"


def _prompt_for_request_execution(
    request: "KernelSourceRequest",
    *,
    clock,
    is_first_turn_of_episode: bool,
    previous_updated_at,
) -> str:
    if _request_uses_learning_agent_context(request):
        return request.prompt
    prompt = request.prompt
    # Time injection: first turn of episode, idle > 1h, or temporal keywords
    if _should_inject_time(prompt, is_first_turn=is_first_turn_of_episode,
                           session_updated_at=previous_updated_at, now=clock.local_datetime):
        prompt = f"{prompt.rstrip()}\n\n{_time_annotation(clock)}"
    # Execution strategy hints (multi-source, compare, artifact)
    prompt = _apply_execution_guidance(prompt)
    return prompt


def _episode_lineage_ids(storage, session: Episode) -> tuple[str, ...]:
    ids: list[str] = []
    seen: set[str] = set()
    current = session
    while current is not None and current.episode_id not in seen:
        ids.append(current.episode_id)
        seen.add(current.episode_id)
        parent_id = str(getattr(current, "parent_episode_id", "") or "").strip()
        if not parent_id:
            break
        load_episode_state = getattr(storage, "load_episode_state", None)
        if not callable(load_episode_state):
            break
        current = load_episode_state(parent_id)
    return tuple(ids)


@dataclass(frozen=True, slots=True)
class KernelService:
    dependencies: KernelDependencies

    def _enqueue_episode_learning_job(
        self,
        *,
        outcome_state: State,
        episode: Episode,
        trigger: str,
        summary: str,
        metadata: Mapping[str, str] | None = None,
    ):
        enqueue = getattr(self.dependencies.storage, "enqueue_learning_job", None)
        if not callable(enqueue):
            return None
        loops = self.dependencies.storage.list_loops(episode_id=episode.episode_id)
        loop = loops[-1] if loops else None
        return enqueue(
            job_type="episode_boundary_learning",
            trigger=trigger,
            personal_model_id=outcome_state.personal_model_id,
            state_id=outcome_state.state_id,
            episode_id=episode.episode_id,
            loop_id=loop.loop_id if loop is not None else None,
            summary=summary,
            metadata=metadata,
        )

    def run(self, request: KernelSourceRequest) -> KernelOutcome:
        stages: list[KernelStageRecord] = []
        current = _clock_now()
        identity = resolve_runtime_identity(self.dependencies.storage, request, current=current)
        episode_lifecycle = open_episode_lifecycle(
            self.dependencies.storage,
            request,
            identity,
            current=current,
        )
        loop_lifecycle = open_loop_lifecycle(
            self.dependencies.storage,
            request,
            identity,
            episode_lifecycle.episode,
            current=current,
        )
        request = replace(
            request,
            owner_scope=request.owner_scope or "state",
            personal_model_id=identity.personal_model.personal_model_id,
            state_id=identity.state.state_id,
            episode_id=episode_lifecycle.episode.episode_id,
            loop_id=loop_lifecycle.loop.loop_id,
        )
        source_id = request.source_id
        event = request.to_event()
        step_recorder = KernelStepRecorder(
            self.dependencies.storage,
            loop_lifecycle.loop,
            semantic_summary_indexer=getattr(self.dependencies, "semantic_summary_indexer", None),
        )
        step_recorder.record(
            phase="observation",
            action="record_input",
            status="completed",
            current=current,
            summary="source input recorded",
            outcome="ok",
            payload_refs=(source_id, event.event_id),
            metadata={
                "event_type": request.source_event_type,
                "user_query": request.prompt,
                "route_id": request.route_id,
                "source": request.surface,
            },
        )

        def stage(name: str, detail: str) -> None:
            record = KernelStageRecord(stage=name, detail=detail, recorded_at=_clock_now())
            stages.append(record)
            self.dependencies.telemetry.emit(
                {
                    "event_id": f"telemetry:{event.episode_id}:{record.stage}:{record.recorded_at.isoformat()}",
                    "event_type": "kernel.stage",
                    "episode_id": event.episode_id,
                    "source": "kernel",
                    "payload": {
                        "stage": record.stage,
                        "detail": record.detail,
                        "recorded_at": record.recorded_at.isoformat(),
                        "event_id": event.event_id,
                    },
                }
            )

        stage(
            "ingest",
            " ".join(
                (
                    f"source={source_id}",
                    f"event={event.event_id}",
                    f"personal_model={identity.personal_model.personal_model_id}",
                    f"state={identity.state.state_id}",
                    f"episode={episode_lifecycle.episode.episode_id}",
                    f"loop={loop_lifecycle.loop.loop_id}",
                )
            ),
        )
        profile = self._route_profile(request, state=identity.state)
        session, previous_updated_at = self._route_session(request, profile=profile, current=current)
        stage(
            "resolve",
            " ".join(
                (
                    f"profile={profile.profile_id}",
                    f"route={session.episode_id}",
                    f"route_status={session.status}",
                )
            ),
        )
        stage(
            "identity-user",
            " ".join(
                (
                    f"identity={identity.state.elephant_id or identity.state.state_anchor}",
                    "user=<surface-owned>",
                )
            ),
        )
        clock = _build_clock(None, now=current)
        recall_selection = self._retrieve_recall_evidence(
            session,
            request,
            state=identity.state,
        )
        recall_items = recall_selection.recall_items
        stage(
            "recover",
            " ".join(
                (
                    f"recall_items={len(recall_items)}",
                    f"scope={','.join(recall_selection.scope_episode_ids)}",
                    f"vector_cache={recall_selection.vector_cache_status or 'n/a'}",
                )
            ),
        )

        context = self.dependencies.context.assemble(session, (), recall_items, state_focus=None)
        step_recorder.record(
            phase="reasoning",
            action="assemble_context",
            status="completed",
            current=_clock_now(),
            summary=f"context bundle {context.bundle_id}",
            outcome="ok",
            payload_refs=(context.bundle_id,),
        )
        projection_compaction = latest_compacted_projection(self.dependencies.context)
        if projection_compaction is not None:
            stage("context-compact", projection_compaction_detail(projection_compaction))
            flush_projection_cache(self.dependencies.context)
        stage(
            "context",
            f"bundle={context.bundle_id} budget={context.token_budget} recovery_scope_reason={recall_selection.scope_reason}",
        )

        context = self._context_for_generation(
            request=request,
            profile=profile,
            session=session,
            state_focus=None,
            work_items=(),
            recall_items=recall_items,
            context=context,
            decision=None,
            plan=None,
            continuity=None,
        )
        stage_context_projection(stage, context)
        prompt_for_execution = _prompt_for_request_execution(
            request,
            clock=clock,
            is_first_turn_of_episode=episode_lifecycle.is_new_episode,
            previous_updated_at=previous_updated_at,
        )
        try:
            execution, run, turn_messages = execute_kernel_turn(
                self,
                request,
                profile,
                session,
                context,
                prompt_for_execution=prompt_for_execution,
                loop_checkpoint=None,
                stage=stage,
                step_recorder=step_recorder,
            )
        except RuntimeError as error:
            retry_compaction = retry_context_after_provider_overflow(
                error=error,
                dependencies=self.dependencies,
                request=request,
                profile=profile,
                session=session,
                state_focus=None,
                work_items=(),
                recall_items=recall_items,
                decision=None,
                plan=None,
                continuity=None,
                stage=stage,
                context_for_generation=self._context_for_generation,
                recovery_scope_reason=recall_selection.scope_reason,
                source_step_ids=tuple(step.step_id for step in step_recorder.steps),
            )
            if retry_compaction is None:
                raise
            context = retry_compaction.context
            step_recorder.record(
                phase="reasoning",
                action="compact_context",
                status="completed",
                current=_clock_now(),
                summary=projection_compaction_detail(retry_compaction.result),
                outcome=str(getattr(retry_compaction.result, "reason", "") or "provider-overflow"),
                payload_refs=(*retry_compaction.packet.source_refs, retry_compaction.packet.packet_id),
                metadata=compaction_step_metadata(
                    packet=retry_compaction.packet,
                    result=retry_compaction.result,
                    source_step_ids=tuple(step.step_id for step in step_recorder.steps),
                ),
            )
            stage_context_projection(stage, context, source="generation-compacted-retry")
            execution, run, turn_messages = execute_kernel_turn(
                self,
                request,
                profile,
                session,
                context,
                prompt_for_execution=prompt_for_execution,
                loop_checkpoint=None,
                stage=stage,
                step_recorder=step_recorder,
            )
        # compact_context_after_usage is now a no-op — compression is handled
        # by the CLI layer via synchronous reflect compress after each turn.
        stage("execute", f"execution={execution.execution_id} outcome={execution.outcome}")
        step_recorder.record(
            phase="reasoning",
            action="reflect",
            status="completed",
            current=_clock_now(),
            summary="canonical state projection refreshed",
            outcome="ok",
            payload_refs=(execution.execution_id,),
        )

        persisted_at = _clock_now()
        projected_state = self._refresh_state_projection(
            identity.state,
            request=request,
            execution=execution,
            current=_clock_now(),
        )
        self.dependencies.storage.upsert_state(projected_state, updated_at=_clock_now())
        stage("persist", f"state={projected_state.state_id}")
        step_recorder.record(
            phase="acting",
            action="write_state",
            status="completed",
            current=_clock_now(),
            summary="runtime state persisted",
            outcome="ok",
            payload_refs=(projected_state.state_id,),
        )

        if episode_lifecycle.idle_closed_episodes:
            stage(
                "gateway_idle_learning",
                f"queued {len(episode_lifecycle.idle_closed_episodes)} idle-closed episode(s)",
            )

        delivery = self._deliver(request, profile, session, execution)
        stage("emit", "telemetry and delivery hooks dispatched")
        step_recorder.record(
            phase="acting",
            action="emit_response",
            status="completed" if execution.outcome != "failed" else "failed",
            current=_clock_now(),
            summary=execution.summary,
            outcome=execution.outcome,
            payload_refs=(execution.execution_id,),
            metadata={
                "execution_id": execution.execution_id,
                "final_response": execution.summary,
                "prompt_tokens": str(execution.prompt_tokens),
                "completion_tokens": str(execution.completion_tokens),
                "total_tokens": str(execution.total_tokens),
            },
        )
        loop = close_loop_lifecycle(
            self.dependencies.storage,
            loop_lifecycle,
            summary=execution.summary,
            outcome=execution.outcome,
            current=_clock_now(),
        )
        episode = close_episode_lifecycle(
            self.dependencies.storage,
            episode_lifecycle,
            summary=execution.summary,
            current=_clock_now(),
            semantic_summary_indexer=getattr(self.dependencies, "semantic_summary_indexer", None),
        )
        if episode.status == "closed":
            refreshed_state = self.dependencies.storage.load_state(projected_state.state_id)
            if refreshed_state is not None:
                projected_state = refreshed_state
        stage("episode", f"episode={episode.episode_id} status={episode.status}")

        # Reflection is moved off the foreground path per system-layer-model
        # docs:755-762. The runtime only enqueues a learning job; the
        # independent learning-worker process drains it. The primary
        # trigger is episode_close; a parked loop (outcome=paused) or a
        # checkpoint Step gets trigger=checkpoint so the worker knows to
        # treat it as lightweight triage rather than a full episode-boundary
        # reflection. Only enqueue when the episode actually closed — open
        # episodes (multi-turn sessions) defer learning until explicit close.
        primary_job = None
        if episode.status != "closed":
            stage("episode_learning", f"deferred episode={episode.episode_id} status={episode.status}")
        elif _suppress_primary_learning_for_request(request):
            stage("episode_learning", f"suppressed internal turn episode={episode.episode_id}")
        else:
            primary_trigger = _primary_learning_trigger(execution=execution, steps=step_recorder.steps)
            primary_job = self._enqueue_episode_learning_job(
                outcome_state=projected_state,
                episode=episode,
                trigger=primary_trigger,
                summary=episode.exit_summary or execution.summary,
                metadata={
                    "execution_id": execution.execution_id,
                    "execution_outcome": execution.outcome,
                    "loop_id": loop.loop_id,
                    "source": "kernel",
                },
            )
            if primary_job is not None:
                stage(
                    "episode_learning",
                    f"episode={episode.episode_id} job={primary_job.job_id} trigger={primary_trigger}",
                )

        outcome = KernelOutcome(
            event=event,
            source_id=source_id,
            personal_model=identity.personal_model,
            state=projected_state,
            episode=episode,
            loop=loop,
            steps=step_recorder.steps,
            recall_items=recall_items,
            context=context,
            execution=execution,
            delivery=delivery,
            stages=tuple(stages),
            turn_messages=turn_messages,
        )
        self._emit_telemetry(outcome)
        return outcome

    def _route_profile(self, request: KernelSourceRequest, *, state: State) -> PersonalModelRuntimeState:
        existing_session = self._load_route_session(request.route_id)
        profile_id = (
            request.route_profile_id
            or str(request.source_payload.get("profile_id", "")).strip()
            or (existing_session.personal_model_id if existing_session is not None else "")
            or state.elephant_id
            or state.state_id
        )
        existing_profile = self._load_route_profile(profile_id)
        display_name = (
            str(request.source_payload.get("profile_display_name", "")).strip()
            or (existing_profile.display_name if existing_profile is not None else "")
            or state.elephant_name
            or "Elephant Agent"
        )
        mode = (
            str(request.source_payload.get("profile_mode", "")).strip()
            or (existing_profile.mode if existing_profile is not None else "")
            or "companion"
        )
        return PersonalModelRuntimeState(
            profile_id=profile_id,
            display_name=display_name,
            mode=mode,
        )

    def _load_route_session(self, route_id: str) -> "Episode | None":
        load_episode = getattr(self.dependencies.storage, "load_episode", None)
        if not callable(load_episode):
            return None
        return load_episode(route_id)

    def _load_route_profile(self, profile_id: str) -> PersonalModelRuntimeState | None:
        load_profile = getattr(self.dependencies.storage, "load_personal_model_runtime_state", None)
        if not callable(load_profile):
            return None
        return load_profile(profile_id)

    def _route_session(
        self,
        request: KernelSourceRequest,
        *,
        profile: PersonalModelRuntimeState,
        current: datetime,
    ) -> "Episode":
        existing_session = self._load_route_session(request.route_id)
        started_at = request.route_started_at or (
            existing_session.started_at if existing_session is not None else current
        )
        # Preserve previous updated_at as the "last activity" marker for idle detection.
        # The new session object gets updated_at=current, but previous_updated_at
        # tells us when the user was last active before this turn.
        previous_updated_at = existing_session.updated_at if existing_session is not None else current
        return Episode(
            episode_id=request.route_id,
            state_id=existing_session.state_id if existing_session is not None else (request.state_id or "state:default"),
            personal_model_id=profile.profile_id,
            entry_surface=existing_session.entry_surface if existing_session is not None else request.surface,
            elephant_id=(existing_session.elephant_id if existing_session is not None else "") or "",
            status=(
                request.route_status
                or str(request.source_payload.get("route_status", "")).strip()
                or (existing_session.status if existing_session is not None else "")
                or "open"
            ),
            started_at=started_at,
            updated_at=current,
            ended_at=existing_session.ended_at if existing_session is not None else None,
            exit_summary=existing_session.exit_summary if existing_session is not None else "",
            parent_episode_id=existing_session.parent_episode_id if existing_session is not None else None,
            interruption_state=(
                request.route_interruption_state
                or str(request.source_payload.get("interruption_state", "")).strip()
                or (existing_session.interruption_state if existing_session is not None else None)
                or None
            ),
            metadata=existing_session.metadata if existing_session is not None else {},
        ), previous_updated_at

    def _retrieve_recall_evidence(
        self,
        session: Episode,
        request: KernelSourceRequest,
        *,
        state: State,
    ) -> _RecallSelection:
        del state
        query = request.state_query or request.prompt or str(request.event.payload.get("message", "")).strip()
        if not query.strip():
            return _RecallSelection(
                recall_items=(),
                query="",
                work_item_ids=(),
                scope_episode_ids=(session.episode_id,),
                scope_reason="no durable recovery query was available",
            )
        work_item_ids: tuple[str, ...] = ()
        scope_episode_ids = _episode_lineage_ids(self.dependencies.storage, session)
        scope_reason = "recovery follows the active episode lineage while allowing elephant and personal-model continuity recall"
        requested_scopes = ["episode"]
        if session.elephant_id:
            requested_scopes.append("elephant")
        if session.personal_model_id:
            requested_scopes.append("personal_model")
        retrieval = self.dependencies.recall.retrieve_evidence(
            EvidenceRetrievalRequest(
                episode_id=session.episode_id,
                personal_model_id=session.personal_model_id,
                elephant_id=session.elephant_id,
                lineage_episode_ids=scope_episode_ids,
                work_item_ids=work_item_ids,
                query=query,
                scopes=tuple(requested_scopes),
                latency_mode="fast",
                limit=5,
                scope_reason=scope_reason,
                relationship_hints=(),
                max_compression="episode_summary",
                replay_mode="off",
                allow_embeddings=str(request.event.payload.get("allow_embeddings", "true")).strip().lower() != "false",
            )
        )
        return _RecallSelection(
            recall_items=tuple(candidate.evidence for candidate in retrieval.candidates),
            query=query,
            work_item_ids=work_item_ids,
            scope_episode_ids=retrieval.scope_episode_ids,
            scope_reason=retrieval.scope_reason,
            vector_cache_status=str(
                getattr(retrieval.recall_reasons, "vector_cache_status", "") or ""
            ),
        )

    def _context_for_generation(
        self,
        *,
        request: KernelSourceRequest,
        profile: PersonalModelRuntimeState,
        session: Episode,
        state_focus: StateFocusDecision | None,
        work_items: tuple[object, ...],
        recall_items: tuple[RecallEvidence, ...],
        context: ContextBundle,
        decision: object | None,
        plan: PlanDraft | None,
        continuity: object | None,
    ) -> ContextBundle:
        return build_context_for_generation(
            dependencies=self.dependencies,
            request=request,
            profile=profile,
            session=session,
            state_focus=state_focus,
            work_items=work_items,
            recall_items=recall_items,
            context=context,
            decision=decision,
            plan=plan,
            continuity=continuity,
        )

    def _deliver(
        self,
        request: KernelSourceRequest,
        profile: PersonalModelRuntimeState,
        session: Episode,
        execution: ExecutionResult,
    ) -> ExecutionResult | None:
        if self.dependencies.delivery is None:
            return None
        payload = {
            "event_id": request.event.event_id,
            "profile_id": profile.profile_id,
            "session_id": session.episode_id,
            "outcome": execution.outcome,
            "summary": execution.summary,
        }
        payload.update(dict(request.delivery_payload))
        return self.dependencies.delivery.deliver(session.episode_id, payload)

    def _persist_loop_checkpoint(
        self,
        run: LoopState,
        *,
        step: LoopStep | None = None,
    ) -> None:
        upsert_run = getattr(self.dependencies.storage, "upsert_loop_checkpoint", None)
        if callable(upsert_run):
            upsert_run(run)
        append_step = getattr(self.dependencies.storage, "append_loop_checkpoint_step", None)
        if step is not None and callable(append_step):
            append_step(step)

    def _list_recent_loop_checkpoint_steps(self, run_id: str, *, limit: int) -> tuple[LoopStep, ...]:
        list_steps = getattr(self.dependencies.storage, "list_loop_checkpoint_steps", None)
        if not callable(list_steps):
            return ()
        return tuple(list_steps(run_id, limit=limit))

    def _emit_telemetry(self, outcome: KernelOutcome) -> None:
        planned_steps = sum(1 for step in outcome.steps if step.status == "planned")
        completed_steps = sum(1 for step in outcome.steps if step.status == "completed")
        failed_steps = sum(1 for step in outcome.steps if step.status == "failed")
        cancelled_steps = sum(1 for step in outcome.steps if step.status == "cancelled")
        self.dependencies.telemetry.emit(
            {
                "event_id": f"telemetry:{outcome.route_session_id}:outcome:{uuid4().hex}",
                "event_type": "kernel.outcome",
                "session_id": outcome.route_session_id,
                "source": "kernel",
                "payload": {
                    "event_id": outcome.event.event_id,
                    "source_id": outcome.source_id,
                    "personal_model_id": outcome.personal_model.personal_model_id,
                    "state_id": outcome.state.state_id,
                    "episode_id": outcome.episode.episode_id,
                    "loop_id": outcome.loop.loop_id,
                    "step_ids": outcome.step_ids,
                    "context_bundle_id": outcome.context.bundle_id,
                    "context_token_budget": outcome.context.token_budget,
                    "execution_id": outcome.execution.execution_id,
                    "execution_outcome": outcome.execution.outcome,
                    "execution_prompt_tokens": outcome.execution.prompt_tokens,
                    "execution_completion_tokens": outcome.execution.completion_tokens,
                    "execution_total_tokens": outcome.execution.total_tokens,
                    "delivery_execution_id": outcome.delivery.execution_id if outcome.delivery is not None else "",
                    "state_summary": outcome.state.summary,
                    "step_count": len(outcome.steps),
                    "planned_step_count": planned_steps,
                    "completed_step_count": completed_steps,
                    "failed_step_count": failed_steps,
                    "cancelled_step_count": cancelled_steps,
                    "tool_call_count": outcome.tool_call_count,
                    "model_turn_count": outcome.model_turn_count,
                    "recall_count": len(outcome.recall_items),
                    "turn_message_count": len(outcome.turn_messages),
                    "produced_artifact_ids": outcome.execution.produced_artifact_ids,
                    "context_artifact_ids": outcome.context.artifact_ids,
                },
            }
        )

    def _refresh_state_projection(
        self,
        state: State,
        *,
        request: KernelSourceRequest,
        execution: ExecutionResult,
        current: datetime,
    ) -> State:
        # Internal / startup turns must NEVER rewrite the Elephant context note
        # with transient prompt text. Those prompts are engineered
        # instructions like "Open the wake surface proactively before
        # the user sends a new message..." — clearly not durable context.
        # We detect them by surface prefix and return state unchanged.
        surface = (request.surface or "").strip().lower()
        source_event_type = (request.source_event_type or "").strip().lower()
        is_internal_turn = (
            surface.startswith("cli.startup")
            or surface.endswith(".startup")
            or source_event_type == "turn.internal"
        )
        if is_internal_turn:
            return replace(state, updated_at=current)

        explicit_context = request.state_query.strip() if request.state_query is not None else ""
        summary_source = execution.summary.strip() or explicit_context or state.summary.strip()
        summary = _compact_state_projection_text(
            summary_source,
            limit=_STATE_SUMMARY_LIMIT,
        )

        return replace(
            state,
            summary=summary,
            updated_at=current,
        )
