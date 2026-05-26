"""Model and tool execution helpers for the kernel runtime."""

from __future__ import annotations

import concurrent.futures
from collections.abc import Mapping
from dataclasses import replace
from datetime import timedelta
import json
import logging as _diag_logging
from uuid import uuid4

_diag_logging.getLogger(__name__).info("🔍 execution_support module loaded (diagnostic patch v2)")

from packages.context import queue_projection_history_embedding_backfill

from .loop_checkpoint_support import LoopCheckpointService
from .context_compaction import stage_context_usage
from .lifecycle_support import (
    KernelStepRecorder,
    assistant_turn_messages,
    context_with_turn_messages,
    initial_turn_messages,
)
from .runtime_support import (
    _MAX_PARALLEL_TOOL_WORKERS,
    _TextToolCall,
    _budget_tool_result_summary,
    _clean_execution_summary,
    _deduplicate_tool_calls,
    _enforce_observation_budget,
    _execute_direct_tool_loop,
    _format_tool_arguments,
    _model_turn_summary,
    _parse_execution_tool_calls,
    _provider_system_prompt_for_recording,
    _role_preserved_tool_interaction_messages,
    _should_parallelize_tool_batch,
    _tool_result_budget_config,
    _utc_now,
    _with_execution_usage,
    LoopState,
    ContextBundle,
    ExecutionResult,
    KernelSourceRequest,
    PersonalModelRuntimeState,
    PromptMessage,
    Episode,
    WaitCondition,
)


def execute_kernel_turn(
    service,
    request: KernelSourceRequest,
    profile: PersonalModelRuntimeState,
    session: Episode,
    context: ContextBundle,
    *,
    prompt_for_execution: str,
    loop_checkpoint: LoopState | None,
    stage: object | None = None,
    step_recorder: KernelStepRecorder | None = None,
) -> tuple[ExecutionResult, LoopState | None, tuple[PromptMessage, ...]]:
    turn_messages = initial_turn_messages(prompt_for_execution)
    if request.tool_name is not None:
        _record_effective_user_query_step(
            step_recorder,
            raw_prompt=request.prompt,
            effective_prompt=turn_messages[0].content if turn_messages else prompt_for_execution,
            source_event_id=request.event.event_id,
        )
        if service.dependencies.tools is None:
            raise RuntimeError("tool execution requested but no tool capability was configured")
        _record_step(
            step_recorder,
            action="call_tool",
            status="planned",
            summary=f"tool {request.tool_name}",
            payload_refs=(request.event.event_id,),
            metadata={
                "tool_name": request.tool_name,
                "tool_arguments": dict(request.tool_arguments),
                "turn_event_id": request.event.event_id,
            },
        )
        execution, checkpoint = _execute_direct_tool_loop(
            request=request,
            session=session,
            tool_capability=service.dependencies.tools,
            persist_loop_checkpoint=service._persist_loop_checkpoint,
        )
        _record_step(
            step_recorder,
            action="call_tool",
            status="failed" if execution.outcome == "failed" else "completed",
            summary=execution.summary,
            outcome=execution.outcome,
            payload_refs=(execution.execution_id,),
            metadata=_tool_execution_step_metadata(
                tool_name=request.tool_name,
                execution=execution,
                tool_arguments=request.tool_arguments,
            ),
        )
        return execution, checkpoint, (*turn_messages, *assistant_turn_messages(_clean_execution_summary(execution)))

    model_prompt = turn_messages[0].content if len(turn_messages) == 1 and turn_messages[0].role == "user" else prompt_for_execution
    _record_effective_user_query_step(
        step_recorder,
        raw_prompt=request.prompt,
        effective_prompt=model_prompt,
        source_event_id=request.event.event_id,
        recall_count=0,
        recall_bytes=0,
    )
    response = _generate_with_steps(
        service,
        profile,
        session,
        context,
        model_prompt,
        step_recorder=step_recorder,
        planned_summary="initial model call",
    )
    if service.dependencies.tools is None:
        stage_context_usage(stage, response.prompt_tokens, response.completion_tokens, response.total_tokens)
        cleaned = _clean_execution_summary(response)
        return cleaned, None, (*turn_messages, *assistant_turn_messages(cleaned))
    return _execute_model_tool_loop(
        service,
        request=request,
        profile=profile,
        session=session,
        context=context,
        initial=response,
        loop_checkpoint=loop_checkpoint,
        turn_messages=turn_messages,
        stage=stage,
        step_recorder=step_recorder,
    )


def _request_uses_learning_agent_context(request: KernelSourceRequest) -> bool:
    payload = getattr(request, "source_payload", {})
    if not isinstance(payload, dict):
        try:
            payload = dict(payload or {})
        except (TypeError, ValueError):
            payload = {}
    context_mode = str(payload.get("context_mode") or "").strip().lower()
    surface = str(getattr(request, "surface", "") or "").strip().lower()
    return context_mode == "learning_agent" or surface.startswith("learning.")


def _record_effective_user_query_step(
    recorder: KernelStepRecorder | None,
    *,
    raw_prompt: str,
    effective_prompt: str,
    source_event_id: str,
    recall_count: int = 0,
    recall_bytes: int = 0,
) -> None:
    raw = str(raw_prompt or "").strip()
    effective = str(effective_prompt or "").strip()
    if not effective:
        return
    _record_step(
        recorder,
        action="effective_user_query",
        status="completed",
        summary="model user query assembled",
        outcome="ok",
        payload_refs=(source_event_id,) if source_event_id else (),
        metadata={
            "effective_user_query": effective,
            "raw_user_query": raw,
            "recall_count": max(0, int(recall_count)),
            "recall_bytes": max(0, int(recall_bytes)),
        },
    )


def _generate_with_steps(
    service,
    profile: PersonalModelRuntimeState,
    session: Episode,
    context: ContextBundle,
    prompt: str,
    *,
    step_recorder: KernelStepRecorder | None,
    planned_summary: str,
) -> ExecutionResult:
    _record_step(
        step_recorder,
        action="call_model",
        status="planned",
        summary=planned_summary,
        payload_refs=(context.bundle_id,),
        metadata={
            "context_bundle_id": context.bundle_id,
            "token_budget": context.token_budget,
            "system_prompt": _provider_system_prompt_for_recording(context),
            "model_prompt": prompt,
        },
    )
    try:
        response = service.dependencies.model_provider.generate(
            profile=profile,
            session=session,
            context=context,
            prompt=prompt,
        )
    except Exception as error:
        _record_step(
            step_recorder,
            action="call_model",
            status="failed",
            summary=str(error),
            outcome="failed",
            payload_refs=(context.bundle_id,),
            metadata={"context_bundle_id": context.bundle_id, "error": str(error)},
        )
        raise
    _record_step(
        step_recorder,
        action="call_model",
        status="failed" if response.outcome == "failed" else "completed",
        summary=response.summary,
        outcome=response.outcome,
        payload_refs=(response.execution_id,),
        metadata={
            "execution_id": response.execution_id,
            "assistant_response": response.summary,
            "assistant_reasoning": response.reasoning,
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "total_tokens": response.total_tokens,
            "cached_prompt_tokens": response.cached_prompt_tokens,
            "cache_creation_prompt_tokens": response.cache_creation_prompt_tokens,
        },
    )
    return response


def _record_step(
    recorder: KernelStepRecorder | None,
    *,
    action: str,
    status: str,
    summary: str = "",
    outcome: str = "",
    payload_refs: tuple[str, ...] = (),
    metadata: Mapping[str, object] | None = None,
) -> None:
    if recorder is None:
        return
    recorder.record(
        phase="acting",
        action=action,
        status=status,
        current=_utc_now(),
        summary=summary,
        outcome=outcome,
        payload_refs=payload_refs,
        metadata=_step_metadata(metadata or {}),
    )


def _step_metadata(metadata: Mapping[str, object]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        text = _metadata_text(value)
        if text:
            normalized[str(key)] = text
    return normalized


def _metadata_text(value: object) -> str:
    if isinstance(value, str):
        return value[:12_000]
    if isinstance(value, (int, float, bool)):
        return str(value)
    try:
        return json.dumps(value, separators=(",", ":"), sort_keys=True, default=str)[:12_000]
    except (TypeError, ValueError):
        return str(value)[:12_000]


def _tool_execution_step_metadata(
    *,
    tool_name: str,
    execution: ExecutionResult,
    tool_arguments: Mapping[str, object] | None = None,
    tool_call_id: str = "",
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "tool_name": tool_name,
        "execution_id": execution.execution_id,
        "tool_result": execution.summary,
    }
    if tool_arguments is not None:
        metadata["tool_arguments"] = dict(tool_arguments)
    if tool_call_id:
        metadata["tool_call_id"] = tool_call_id
    if execution.telemetry_event_ids:
        metadata["telemetry_event_ids"] = execution.telemetry_event_ids
    if execution.trace_metadata:
        metadata.update(dict(execution.trace_metadata))
    return metadata


def _execute_model_tool_loop(
    service,
    *,
    request: KernelSourceRequest,
    profile: PersonalModelRuntimeState,
    session: Episode,
    context: ContextBundle,
    initial: ExecutionResult,
    loop_checkpoint: LoopState | None,
    turn_messages: tuple[PromptMessage, ...],
    stage: object | None = None,
    step_recorder: KernelStepRecorder | None = None,
) -> tuple[ExecutionResult, LoopState | None, tuple[PromptMessage, ...]]:
    response = initial
    prompt_tokens_total = response.prompt_tokens
    completion_tokens_total = response.completion_tokens
    total_tokens_total = response.total_tokens
    cached_prompt_tokens_total = response.cached_prompt_tokens
    cache_creation_prompt_tokens_total = response.cache_creation_prompt_tokens
    cache_usage_reported = response.cache_usage_reported
    stage_context_usage(stage, prompt_tokens_total, completion_tokens_total, total_tokens_total)
    collected_turn_messages = list(turn_messages)
    loop_traces: list[str] = []
    loop_service = LoopCheckpointService()
    budget = loop_service.budget
    current_loop = loop_checkpoint
    starting_model_turn_count = current_loop.model_turn_count if current_loop is not None else 0
    context_recorded = False
    deadline = _utc_now() + timedelta(
        seconds=(current_loop.max_wall_time_seconds if current_loop is not None else budget.max_wall_time_seconds)
    )
    while True:
        parsed = _parse_execution_tool_calls(response)
        deduped_calls = _deduplicate_tool_calls(parsed.calls)
        parsed_for_turn = replace(parsed, calls=deduped_calls)
        if current_loop is None:
            current_loop = loop_service.start_loop(
                episode_id=session.episode_id,
                source_event_id=request.event.event_id,
                prompt=request.prompt,
            )
            service._persist_loop_checkpoint(current_loop)
        provider_system_prompt = _provider_system_prompt_for_recording(context)
        if current_loop is not None and not context_recorded and provider_system_prompt:
            current_loop, context_step = loop_service.record_context_prompt(current_loop, system_prompt=provider_system_prompt)
            service._persist_loop_checkpoint(current_loop, step=context_step)
            context_recorded = True
        if current_loop is not None:
            cleaned_summary = _model_turn_summary(response, parsed=parsed_for_turn)
            current_loop, model_step = loop_service.record_model_turn(
                current_loop,
                summary=cleaned_summary,
                response_text=_clean_execution_summary(response).summary,
            )
            service._persist_loop_checkpoint(current_loop, step=model_step)
        if not deduped_calls:
            return _finalize_model_loop_response(
                service,
                current_loop,
                loop_service,
                response,
                loop_traces=tuple(loop_traces),
                collected_turn_messages=collected_turn_messages,
                prompt_tokens_total=prompt_tokens_total,
                completion_tokens_total=completion_tokens_total,
                total_tokens_total=total_tokens_total,
                cached_prompt_tokens_total=cached_prompt_tokens_total,
                cache_creation_prompt_tokens_total=cache_creation_prompt_tokens_total,
                cache_usage_reported=cache_usage_reported,
            )

        observations = _invoke_tools_for_loop(
            service,
            deduped_calls,
            session=session,
            budget=budget,
            current_loop=current_loop,
            loop_service=loop_service,
            step_recorder=step_recorder,
            loop_traces=loop_traces,
        )
        tool_turn_messages = _role_preserved_tool_interaction_messages(
            assistant_summary=parsed.cleaned_text or response.summary,
            calls=deduped_calls,
            observations=tuple(observations),
        )
        collected_turn_messages.extend(tool_turn_messages)
        learning_agent_context = _request_uses_learning_agent_context(request)
        if not learning_agent_context:
            _queue_projection_embedding_backfill(
                service,
                tool_turn_messages,
                thread_focus=request.state_query or request.prompt,
            )

        if current_loop is not None and (
            (current_loop.model_turn_count - starting_model_turn_count) >= current_loop.max_model_turns
            or _utc_now() >= deadline
        ):
            return _park_model_tool_loop(
                service,
                current_loop,
                loop_service,
                parsed.cleaned_text or response.summary,
                observations,
                session=session,
                loop_traces=tuple(loop_traces),
                step_recorder=step_recorder,
                collected_turn_messages=collected_turn_messages,
                prompt_tokens_total=prompt_tokens_total,
                completion_tokens_total=completion_tokens_total,
                total_tokens_total=total_tokens_total,
                cached_prompt_tokens_total=cached_prompt_tokens_total,
                cache_creation_prompt_tokens_total=cache_creation_prompt_tokens_total,
                cache_usage_reported=cache_usage_reported,
                starting_model_turn_count=starting_model_turn_count,
            )

        loop_context = context_with_turn_messages(context, tuple(collected_turn_messages))
        response = _generate_with_steps(
            service,
            profile,
            session,
            loop_context,
            "Continue the same Elephant Agent turn using the role-preserved tool result messages above.",
            step_recorder=step_recorder,
            planned_summary="continue model call after tool observations",
        )
        prompt_tokens_total += response.prompt_tokens
        completion_tokens_total += response.completion_tokens
        total_tokens_total += response.total_tokens
        cached_prompt_tokens_total += response.cached_prompt_tokens
        cache_creation_prompt_tokens_total += response.cache_creation_prompt_tokens
        cache_usage_reported = cache_usage_reported or response.cache_usage_reported
        stage_context_usage(stage, prompt_tokens_total, completion_tokens_total, total_tokens_total)


def _finalize_model_loop_response(
    service,
    current_loop: LoopState | None,
    loop_service: LoopCheckpointService,
    response: ExecutionResult,
    *,
    loop_traces: tuple[str, ...],
    collected_turn_messages: list[PromptMessage],
    prompt_tokens_total: int,
    completion_tokens_total: int,
    total_tokens_total: int,
    cached_prompt_tokens_total: int,
    cache_creation_prompt_tokens_total: int,
    cache_usage_reported: bool,
) -> tuple[ExecutionResult, LoopState | None, tuple[PromptMessage, ...]]:
    cleaned = _with_execution_usage(
        _clean_execution_summary(response),
        prompt_tokens=prompt_tokens_total,
        completion_tokens=completion_tokens_total,
        total_tokens=total_tokens_total,
        cached_prompt_tokens=cached_prompt_tokens_total,
        cache_creation_prompt_tokens=cache_creation_prompt_tokens_total,
        cache_usage_reported=cache_usage_reported,
    )
    finalized = cleaned if not loop_traces else replace(
        cleaned,
        side_effects=tuple(dict.fromkeys((*cleaned.side_effects, *loop_traces))),
    )
    if current_loop is not None:
        current_loop = loop_service.complete(current_loop, summary=finalized.summary)
        service._persist_loop_checkpoint(current_loop)
    collected_turn_messages.extend(assistant_turn_messages(finalized))
    return finalized, current_loop, tuple(collected_turn_messages)


def _invoke_tools_for_loop(
    service,
    calls: tuple[_TextToolCall, ...],
    *,
    session: Episode,
    budget,
    current_loop: LoopState | None,
    loop_service: LoopCheckpointService,
    step_recorder: KernelStepRecorder | None,
    loop_traces: list[str],
) -> list[str]:
    tool_budget_config = _tool_result_budget_config(
        preview_chars=budget.tool_result_preview_chars,
        turn_budget_chars=budget.tool_result_turn_budget_chars,
        persist_threshold_chars=budget.tool_result_persist_threshold_chars,
    )
    for call in calls:
        _record_step(
            step_recorder,
            action="call_tool",
            status="planned",
            summary=f"tool {call.tool_name}",
            payload_refs=(call.call_id,) if call.call_id else (),
            metadata={
                "tool_name": call.tool_name,
                "tool_call_id": call.call_id,
                "tool_arguments": call.arguments,
            },
        )
    observations: list[str] = []
    for call, result in _invoke_tool_batch(service, calls, session=session):
        loop_traces.append(call.tool_name)
        _record_step(
            step_recorder,
            action="call_tool",
            status="failed" if result.outcome == "failed" else "completed",
            summary=result.summary,
            outcome=result.outcome,
            payload_refs=(result.execution_id,),
            metadata=_tool_execution_step_metadata(
                tool_name=call.tool_name,
                execution=result,
                tool_arguments=call.arguments,
                tool_call_id=call.call_id,
            ),
        )
        if current_loop is not None:
            current_loop, tool_step = loop_service.record_tool_step(
                current_loop,
                tool_name=call.tool_name,
                arguments=call.arguments,
                result=result,
            )
            service._persist_loop_checkpoint(current_loop, step=tool_step)
        summary = _budget_tool_result_summary(
            result.summary,
            tool_name=call.tool_name,
            tool_use_id=result.execution_id,
            config=tool_budget_config,
        )
        observations.append(
            "\n".join(
                (
                    f"tool: {call.tool_name}",
                    f"arguments: {_format_tool_arguments(call.arguments)}",
                    f"outcome: {result.outcome}",
                    f"summary: {summary}",
                )
            )
        )
    return list(_enforce_observation_budget(observations, config=tool_budget_config))


def _park_model_tool_loop(
    service,
    current_loop: LoopState,
    loop_service: LoopCheckpointService,
    last_summary: str,
    observations: list[str],
    *,
    session: Episode,
    loop_traces: tuple[str, ...],
    step_recorder: KernelStepRecorder | None,
    collected_turn_messages: list[PromptMessage],
    prompt_tokens_total: int,
    completion_tokens_total: int,
    total_tokens_total: int,
    cached_prompt_tokens_total: int,
    cache_creation_prompt_tokens_total: int,
    cache_usage_reported: bool,
    starting_model_turn_count: int,
) -> tuple[ExecutionResult, LoopState | None, tuple[PromptMessage, ...]]:
    reason = (
        "model-turn-budget"
        if (current_loop.model_turn_count - starting_model_turn_count) >= current_loop.max_model_turns
        else "wall-time-budget"
    )
    recent_steps = service._list_recent_loop_checkpoint_steps(current_loop.run_id, limit=6)
    continuation_prompt = loop_service.build_continuation_prompt(
        current_loop,
        recent_steps=recent_steps,
        observations=tuple(observations),
    )
    wait_condition = WaitCondition(
        kind="budget_exhausted",
        payload={"budget": reason, "legacy_reason": reason},
        created_at=_utc_now(),
        auto_wake=False,
    )
    parked = loop_service.park(
        current_loop,
        wait_condition=wait_condition,
        last_summary=last_summary,
        continuation_prompt=continuation_prompt,
    )
    service._persist_loop_checkpoint(parked)
    message = (
        "I kept working through this request and parked it at a durable checkpoint "
        f"after {parked.model_turn_count} model rounds and {parked.tool_call_count} tool calls. "
        "Ask me to continue and I will resume from the saved loop checkpoint."
    )
    paused = ExecutionResult(
        execution_id=f"loop:{parked.run_id}:pending",
        episode_id=session.episode_id,
        outcome="paused",
        summary=message,
        prompt_tokens=prompt_tokens_total,
        completion_tokens=completion_tokens_total,
        total_tokens=total_tokens_total,
        cached_prompt_tokens=cached_prompt_tokens_total,
        cache_creation_prompt_tokens=cache_creation_prompt_tokens_total,
        cache_usage_reported=cache_usage_reported,
        side_effects=tuple(dict.fromkeys(loop_traces)),
    )
    _record_step(
        step_recorder,
        action="checkpoint",
        status="completed",
        summary=continuation_prompt,
        outcome=reason,
        payload_refs=(parked.run_id,),
    )
    _record_step(
        step_recorder,
        action="pause",
        status="completed",
        summary=message,
        outcome="paused",
        payload_refs=(parked.run_id, paused.execution_id),
    )
    collected_turn_messages.extend(assistant_turn_messages(paused))
    return paused, parked, tuple(collected_turn_messages)


def _invoke_tool_batch(
    service,
    calls: tuple[_TextToolCall, ...],
    *,
    session: Episode,
) -> list[tuple[_TextToolCall, ExecutionResult]]:
    if not _should_parallelize_tool_batch(calls):
        return [(call, _invoke_tool_call(service, call, session=session)) for call in calls]

    max_workers = min(len(calls), _MAX_PARALLEL_TOOL_WORKERS)
    ordered_results: list[tuple[_TextToolCall, ExecutionResult] | None] = [None] * len(calls)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_invoke_tool_call, service, call, session=session): index
            for index, call in enumerate(calls)
        }
        for future in concurrent.futures.as_completed(futures):
            index = futures[future]
            ordered_results[index] = (calls[index], future.result())
    return [result for result in ordered_results if result is not None]


def _invoke_tool_call(
    service,
    call: _TextToolCall,
    *,
    session: Episode,
) -> ExecutionResult:
    import logging as _logging
    _logging.getLogger(__name__).info(
        "📞 _invoke_tool_call: tool=%s session=%s",
        call.tool_name, session.episode_id[:8] if session.episode_id else "?",
    )
    try:
        assert service.dependencies.tools is not None
        return service.dependencies.tools.invoke(call.tool_name, dict(call.arguments), session_id=session.episode_id)
    except Exception as error:
        return ExecutionResult(
            execution_id=f"tool:{session.episode_id}:{uuid4().hex[:8]}",
            episode_id=session.episode_id,
            outcome="failed",
            summary=str(error),
            side_effects=(call.tool_name,),
        )


def _queue_projection_embedding_backfill(
    service,
    messages: tuple[PromptMessage, ...],
    *,
    thread_focus: str,
) -> None:
    if service.dependencies.embedding_service is None or not messages:
        return
    queue_projection_history_embedding_backfill(
        service.dependencies.embedding_service,
        messages=messages,
        thread_focus=thread_focus,
        include_query=False,
    )
