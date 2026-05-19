"""Resume support for parked long-horizon loops.

Phase 1 implements the three idempotency locks that a wake-up path
needs before it can safely feed a resumed Loop back into the kernel:

1. **Pending tool calls** — Each tool call registered via
   :meth:`LoopCheckpointService.register_pending_tool` carries a status
   (``dispatched`` / ``running`` / ``done_unread``). The resume path
   inspects each pending entry. If a completed ``Step`` already exists
   for that tool call, the replay is skipped (the tool result is
   already durable). Otherwise the entry is queued for replay with
   its stored idempotency key.
2. **Partial assistant** — If the Loop parked while mid-stream SSE was
   interrupted (see ``ProviderSSEIncompleteError``), the accumulated
   text lives in ``LoopState.partial_assistant``. Resume consumes it
   once and clears the field so a subsequent crash does not re-emit
   the same prefix twice.
3. **Context bundle** — Phase 1 simply records the bundle id the
   checkpoint was last associated with so the caller can invalidate
   caches; full Phase 3 work will lift the typed EpisodeContinuityPacket
   into the rebuild path.

The concrete runtime behaviour (actually calling a provider again,
actually reassembling a ContextBundle) lands in commits 6 (supervisor)
and Phase 3 (continuity packet). This module provides the pure logic
the supervisor can import without bringing the whole kernel service in.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Iterable, Sequence

from packages.contracts.layers import Step
from packages.contracts.runtime import LoopState, PendingToolCall


@dataclass(frozen=True, slots=True)
class PendingToolReplayPlan:
    """How to treat one entry in ``LoopState.pending_tool_calls`` on resume.

    ``skip`` — a completed Step already exists for this call_id; the
    tool ran to completion before the crash so replay would double-run
    the side-effect.

    ``inject`` — the result is durable (``status="done_unread"``); resume
    re-injects the stored output as an observation but does not reissue
    the tool call.

    ``replay`` — the crash happened between dispatch and step persistence;
    resume calls the tool again with the stored idempotency key. Tools
    that understand the key will short-circuit; tools that do not will
    run but the idempotency key preserves an audit trail.

    ``poll`` — reserved for async tools (Phase 2); resume queries the
    handle instead of re-invoking.
    """

    call: PendingToolCall
    action: str  # skip | inject | replay | poll
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ResumeSnapshot:
    """Materialised view of what a resume would do.

    ``is_resumable`` is False when the Loop is terminal (completed /
    failed) or no LoopState was found. When True, ``partial_assistant``
    carries the accumulated text to re-inject, ``replay_plans``
    describes every pending tool call, and ``wait_condition`` /
    ``retry_state`` are the authoritative records on the checkpoint.

    Callers apply the snapshot via :func:`apply_resume_snapshot` (next
    commit wires that into the supervisor).
    """

    loop_id: str
    is_resumable: bool
    state: LoopState | None
    partial_assistant: str = ""
    replay_plans: tuple[PendingToolReplayPlan, ...] = ()
    wait_condition_kind: str = ""
    retry_attempt: int = 0
    reason: str = ""


_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


def _completed_tool_step_ids(steps: Sequence[Step], *, call_id: str) -> tuple[str, ...]:
    """Return Step ids that represent a completed run of the same tool call.

    A Step is considered to "cover" a pending tool call when its
    metadata ``tool_call_id`` matches and its status is ``completed``.
    This is the signal that the tool already ran to completion on
    disk, so replay would duplicate side effects.
    """
    matching: list[str] = []
    for step in steps:
        if step.status != "completed":
            continue
        meta = dict(step.metadata or {})
        recorded_call_id = str(meta.get("tool_call_id") or "").strip()
        if recorded_call_id and recorded_call_id == call_id:
            matching.append(step.step_id)
    return tuple(matching)


def plan_pending_tool_replay(
    pending: Iterable[PendingToolCall],
    *,
    loop_steps: Sequence[Step],
) -> tuple[PendingToolReplayPlan, ...]:
    """Decide the replay action for every pending tool call.

    Applied in resume order: if the crash happened between
    ``register_pending_tool`` and ``_record_step(... status=completed)``
    the Step exists and we skip. If the Step does not exist but the
    pending status is ``done_unread``, we inject. If ``dispatched``
    and no Step, we replay with the idempotency key. ``running`` is a
    Phase 2 concept (async tools) and shows up here as ``poll``.
    """
    plans: list[PendingToolReplayPlan] = []
    for entry in pending:
        matching_step_ids = _completed_tool_step_ids(loop_steps, call_id=entry.call_id)
        if matching_step_ids:
            plans.append(
                PendingToolReplayPlan(
                    call=entry,
                    action="skip",
                    reason=(
                        "tool completed before crash; Step " + matching_step_ids[0] + " already records the outcome"
                    ),
                )
            )
            continue
        if entry.status == "done_unread":
            plans.append(
                PendingToolReplayPlan(
                    call=entry,
                    action="inject",
                    reason="tool result durable on disk; inject into observation stream",
                )
            )
            continue
        if entry.status == "running":
            plans.append(
                PendingToolReplayPlan(
                    call=entry,
                    action="poll",
                    reason="async tool; poll handle before replay",
                )
            )
            continue
        # default: dispatched and no completed Step
        plans.append(
            PendingToolReplayPlan(
                call=entry,
                action="replay",
                reason="no completed Step; replay with idempotency key",
            )
        )
    return tuple(plans)


def snapshot_resume(
    *,
    loop_id: str,
    state: LoopState | None,
    loop_steps: Sequence[Step],
) -> ResumeSnapshot:
    """Build the ResumeSnapshot without mutating storage.

    The supervisor and the CLI both call this in their "should I try to
    resume" check. Mutating the LoopState (clearing partial_assistant,
    advancing crash_marker to ``recovered``) is the caller's
    responsibility via :func:`apply_resume_snapshot`.
    """
    if state is None:
        return ResumeSnapshot(
            loop_id=loop_id,
            is_resumable=False,
            state=None,
            reason="no loop checkpoint on disk",
        )
    if state.status in _TERMINAL_STATUSES:
        return ResumeSnapshot(
            loop_id=loop_id,
            is_resumable=False,
            state=state,
            reason=f"loop status is terminal ({state.status})",
        )
    plans = plan_pending_tool_replay(state.pending_tool_calls, loop_steps=loop_steps)
    return ResumeSnapshot(
        loop_id=loop_id,
        is_resumable=True,
        state=state,
        partial_assistant=state.partial_assistant or "",
        replay_plans=plans,
        wait_condition_kind=state.wait_condition.kind if state.wait_condition is not None else "",
        retry_attempt=state.retry_state.attempt if state.retry_state is not None else 0,
        reason="ready",
    )


def apply_resume_snapshot(
    snapshot: ResumeSnapshot,
    *,
    now: datetime | None = None,
) -> LoopState | None:
    """Compute the post-resume LoopState after the caller has consumed the snapshot.

    Clears ``partial_assistant`` (it has been re-injected), removes any
    pending tool calls flagged ``skip`` or ``inject`` (they have been
    reconciled), flips ``crash_marker`` to ``"recovered"``, and stamps
    a fresh ``heartbeat_at``. Entries flagged ``replay`` or ``poll``
    survive so the next kernel turn sees them and proceeds.
    """
    if snapshot.state is None:
        return None
    current = now or datetime.now(timezone.utc)
    remaining_pending = tuple(plan.call for plan in snapshot.replay_plans if plan.action in {"replay", "poll"})
    return replace(
        snapshot.state,
        pending_tool_calls=remaining_pending,
        partial_assistant=None,
        heartbeat_at=current,
        updated_at=current,
        crash_marker="recovered",
    )


__all__ = [
    "PendingToolReplayPlan",
    "ResumeSnapshot",
    "apply_resume_snapshot",
    "plan_pending_tool_replay",
    "snapshot_resume",
]


# silence unused imports that document intent even when tests don't touch them
_ = field
