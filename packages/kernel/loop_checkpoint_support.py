"""Durable run helpers for resumable long-horizon kernel execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Iterable
from uuid import uuid4

from packages.contracts.runtime import (
    ExecutionResult,
    LoopState,
    LoopStep,
    PendingToolCall,
    WaitCondition,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _compact(value: str, *, limit: int = 320) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _format_arguments(arguments: Mapping[str, object]) -> str:
    if not arguments:
        return "<none>"
    return ", ".join(f"{key}={value}" for key, value in sorted(arguments.items()))


def _checkpoint_content_preview(step: LoopStep) -> str:
    if step.kind == "tool":
        return "tool-result-pruned: " + _compact(step.content, limit=160)
    if step.kind == "context_prompt":
        return "provider-system-prompt-pruned: " + _compact(step.content, limit=180)
    return _compact(step.content, limit=220)


def _checkpoint_step_id(run_id: str, step_index: int) -> str:
    return f"loop-step:{run_id}:{step_index}"


@dataclass(frozen=True, slots=True)
class LoopCheckpointBudget:
    max_model_turns: int = 100
    max_wall_time_seconds: int = 8 * 60 * 60
    tool_result_preview_chars: int = 1_500
    tool_result_turn_budget_chars: int = 200_000
    tool_result_persist_threshold_chars: int = 100_000


@dataclass(frozen=True, slots=True)
class LoopCheckpointService:
    budget: LoopCheckpointBudget = LoopCheckpointBudget()

    def start_loop(
        self,
        *,
        episode_id: str | None = None,
        session_id: str | None = None,
        source_event_id: str,
        prompt: str,
        now: datetime | None = None,
    ) -> LoopState:
        resolved_episode_id = str(episode_id or session_id or "").strip()
        if not resolved_episode_id:
            raise ValueError("episode_id is required")
        current = now or _utc_now()
        return LoopState(
            run_id=f"loop:{resolved_episode_id}:{uuid4().hex[:10]}",
            episode_id=resolved_episode_id,
            source_event_id=source_event_id,
            prompt=prompt.strip(),
            status="active",
            phase="model",
            step_count=0,
            model_turn_count=0,
            tool_call_count=0,
            max_model_turns=self.budget.max_model_turns,
            max_wall_time_seconds=self.budget.max_wall_time_seconds,
            created_at=current,
            updated_at=current,
            heartbeat_at=current,
        )

    def resume_loop(
        self,
        run: LoopState,
        *,
        now: datetime | None = None,
    ) -> LoopState:
        current = now or _utc_now()
        return replace(
            run,
            status="active",
            phase="resume",
            updated_at=current,
            heartbeat_at=current,
            waiting_reason=None,
        )

    def complete(
        self,
        run: LoopState,
        *,
        summary: str,
        now: datetime | None = None,
    ) -> LoopState:
        current = now or _utc_now()
        return replace(
            run,
            status="completed",
            phase="done",
            updated_at=current,
            heartbeat_at=current,
            waiting_reason=None,
            continuation_prompt=None,
            last_summary=_compact(summary, limit=800),
        )

    def fail(
        self,
        run: LoopState,
        *,
        summary: str,
        reason: str = "failed",
        now: datetime | None = None,
    ) -> LoopState:
        current = now or _utc_now()
        return replace(
            run,
            status="failed",
            phase="done",
            updated_at=current,
            heartbeat_at=current,
            waiting_reason=reason,
            continuation_prompt=None,
            last_summary=_compact(summary, limit=800),
        )

    def park(
        self,
        run: LoopState,
        *,
        wait_condition: WaitCondition,
        last_summary: str,
        continuation_prompt: str | None = None,
        now: datetime | None = None,
    ) -> LoopState:
        """Transition the Loop into a structured wait.

        ``wait_condition`` is authoritative — it tells the supervisor /
        resume path which wake-up mechanism owns this Loop (timer,
        tool_callback, network, approval, external_poll, event, or
        budget_exhausted). ``continuation_prompt`` is a human-readable
        projection retained only for operator logs and the prompt-hint
        renderer in apps/cli; the resume path rebuilds prompts from
        LoopState.pending_tool_calls + partial_assistant +
        EpisodeContinuityPacket instead.
        """
        current = now or _utc_now()
        legacy_reason = wait_condition.payload.get("legacy_reason") or wait_condition.kind
        auto_prompt = continuation_prompt or self.build_continuation_prompt(run, recent_steps=())
        return replace(
            run,
            status="pending",
            phase="waiting",
            updated_at=current,
            heartbeat_at=current,
            waiting_reason=legacy_reason,
            continuation_prompt=auto_prompt,
            last_summary=_compact(last_summary, limit=800),
            wait_condition=wait_condition,
        )

    def touch_heartbeat(
        self,
        run: LoopState,
        *,
        now: datetime | None = None,
    ) -> LoopState:
        """Update the liveness marker without changing other fields.

        Callers bump the heartbeat at every model turn, tool call, and
        supervisor tick so a stale heartbeat is a reliable crash signal.
        """
        current = now or _utc_now()
        return replace(run, heartbeat_at=current, updated_at=current)

    def register_pending_tool(
        self,
        run: LoopState,
        *,
        call_id: str,
        tool_name: str,
        arguments,
        step_id: str,
        idempotency_key: str | None = None,
        handle_id: str | None = None,
        status: str = "dispatched",
        now: datetime | None = None,
    ) -> LoopState:
        """Record a tool call that has left the kernel.

        Resume drains ``pending_tool_calls`` to decide whether to replay
        (``dispatched``), poll (``running``), or inject-only (``done_unread``).
        Clearing happens via ``clear_pending_tool`` once the corresponding
        Step is durably persisted.
        """
        current = now or _utc_now()
        entry = PendingToolCall(
            call_id=call_id,
            tool_name=tool_name,
            arguments=dict(arguments or {}),
            started_at=current,
            step_id=step_id,
            handle_id=handle_id,
            status=status,
            idempotency_key=idempotency_key,
        )
        pending = tuple(call for call in run.pending_tool_calls if call.call_id != call_id)
        return replace(
            run,
            pending_tool_calls=(*pending, entry),
            updated_at=current,
            heartbeat_at=current,
        )

    def clear_pending_tool(
        self,
        run: LoopState,
        *,
        call_id: str,
        now: datetime | None = None,
    ) -> LoopState:
        current = now or _utc_now()
        pending = tuple(call for call in run.pending_tool_calls if call.call_id != call_id)
        if len(pending) == len(run.pending_tool_calls):
            return run
        return replace(run, pending_tool_calls=pending, updated_at=current, heartbeat_at=current)

    def mark_partial_assistant(
        self,
        run: LoopState,
        partial: str | None,
        *,
        now: datetime | None = None,
    ) -> LoopState:
        """Store the assistant text that was emitted before an SSE disconnect.

        Resume re-injects this as the prefix of the next assistant turn so
        the provider does not redo work we already saw.
        """
        current = now or _utc_now()
        normalized = None
        if partial is not None:
            stripped = partial.strip()
            normalized = stripped if stripped else None
        return replace(run, partial_assistant=normalized, updated_at=current, heartbeat_at=current)

    def record_model_turn(
        self,
        run: LoopState,
        *,
        summary: str,
        response_text: str | None = None,
        now: datetime | None = None,
    ) -> tuple[LoopState, LoopStep]:
        current = now or _utc_now()
        updated = replace(
            run,
            phase="model",
            step_count=run.step_count + 1,
            model_turn_count=run.model_turn_count + 1,
            updated_at=current,
            heartbeat_at=current,
            last_summary=_compact(summary, limit=800),
        )
        step = LoopStep(
            step_id=_checkpoint_step_id(run.run_id, updated.step_count),
            run_id=run.run_id,
            episode_id=run.episode_id,
            step_index=updated.step_count,
            kind="model",
            title=f"model turn {updated.model_turn_count}",
            content=_compact(response_text or summary, limit=6_000),
            created_at=current,
            outcome="ok",
        )
        return updated, step

    def record_context_prompt(
        self,
        run: LoopState,
        *,
        system_prompt: str | None = None,
        rendered_prompt: str | None = None,
        now: datetime | None = None,
    ) -> tuple[LoopState, LoopStep]:
        current = now or _utc_now()
        prompt_text = system_prompt if system_prompt is not None else (rendered_prompt or "")
        updated = replace(
            run,
            phase="context",
            step_count=run.step_count + 1,
            updated_at=current,
            heartbeat_at=current,
        )
        step = LoopStep(
            step_id=_checkpoint_step_id(run.run_id, updated.step_count),
            run_id=run.run_id,
            episode_id=run.episode_id,
            step_index=updated.step_count,
            kind="context_prompt",
            title="provider system prompt",
            content=prompt_text,
            created_at=current,
            outcome="ok",
        )
        return updated, step

    def record_tool_step(
        self,
        run: LoopState,
        *,
        tool_name: str,
        arguments: Mapping[str, object],
        result: ExecutionResult,
        now: datetime | None = None,
    ) -> tuple[LoopState, LoopStep]:
        current = now or _utc_now()
        updated = replace(
            run,
            phase="tool",
            step_count=run.step_count + 1,
            tool_call_count=run.tool_call_count + 1,
            updated_at=current,
            heartbeat_at=current,
            last_summary=_compact(result.summary, limit=800),
        )
        content = "\n".join(
            (
                f"arguments: {_format_arguments(arguments)}",
                f"outcome: {result.outcome}",
                f"summary: {_compact(result.summary, limit=900)}",
            )
        )
        step = LoopStep(
            step_id=_checkpoint_step_id(run.run_id, updated.step_count),
            run_id=run.run_id,
            episode_id=run.episode_id,
            step_index=updated.step_count,
            kind="tool",
            title=tool_name,
            content=content,
            created_at=current,
            outcome=result.outcome,
            tool_name=tool_name,
        )
        return updated, step

    def should_resume(self, prompt: str) -> bool:
        normalized = " ".join(prompt.casefold().split())
        if not normalized:
            return False
        explicit_phrases = (
            "continue",
            "resume",
            "keep going",
            "go on",
            "carry on",
            "pick up where you left off",
            "keep working",
            "continue that",
            "resume that",
            "finish this",
            "finish it",
            "keep digging",
        )
        return any(
            normalized == phrase
            or normalized.startswith(f"{phrase} ")
            or normalized.endswith(f" {phrase}")
            for phrase in explicit_phrases
        )

    def resume_prompt_for_request(self, run: LoopState, prompt: str) -> str:
        base = run.continuation_prompt or self.build_continuation_prompt(run, recent_steps=())
        normalized = " ".join(prompt.casefold().split())
        if normalized in {"continue", "resume", "keep going", "go on", "carry on", "finish this", "finish it"}:
            return base
        return f"{base}\n\nLatest user nudge:\n{prompt.strip()}"

    def build_continuation_prompt(
        self,
        run: LoopState,
        *,
        recent_steps: Iterable[LoopStep],
        observations: Iterable[str] = (),
    ) -> str:
        sections = [
            "Continue the same Elephant Agent loop checkpoint from its durable checkpoint.",
            f"Original user request:\n{run.prompt}",
        ]
        step_lines = []
        for step in recent_steps:
            step_lines.append(f"- {step.kind} | {step.title} | {_checkpoint_content_preview(step)}")
        if step_lines:
            sections.append("Recent durable checkpoints:\n" + "\n".join(step_lines))
        observation_lines = [item.strip() for item in observations if item.strip()]
        if observation_lines:
            sections.append("Latest tool observations:\n" + "\n\n".join(observation_lines))
        sections.append(
            "Continue from the latest checkpoint instead of restarting from scratch. "
            "If more tool work is required, call more tools directly when native tool calling is available; "
            "otherwise emit more <tool_call> markup. "
            "When the work is done, answer directly as Elephant Agent without raw tool markup."
        )
        return "\n\n".join(sections)

    def interruption_state(self, run: LoopState) -> str | None:
        if run.status != "pending":
            return None
        reason = run.waiting_reason or "checkpointed"
        return f"loop-checkpoint:{run.run_id}:{reason}"
