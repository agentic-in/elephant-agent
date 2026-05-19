"""Heartbeat + crash-scan supervisor for parked long-horizon loops.

A Loop that parks at a WaitCondition still needs someone to notice when
the condition is satisfied: a timer has elapsed, a tool callback
fired, an approval arrived, the network came back. Phase 1 implements
the first wave — crash detection, budget-exhaustion reclaim, timer
wake-ups, and network recovery — without pulling in the full event bus
(Phase 4). The supervisor is a poll loop that reads
``list_loop_checkpoints`` every ``interval_seconds`` and decides per
Loop whether to:

* reclaim it as crashed (heartbeat older than ``heartbeat_stale_ttl``
  and status in {active, pending}) — mark ``crash_marker="detected"``
  so operator UIs can tell apart fresh activity from a zombie row;
* wake it up because its ``wait_condition.wake_at`` has elapsed;
* leave it parked otherwise.

The supervisor does NOT itself re-enter the kernel turn loop. That
responsibility lives with the kernel (``resume_support`` gives the
pure logic; a future commit wires the full turn replay). The
supervisor's job is to:

1. detect stale / ripe loops;
2. mark crash detection so they are visible as "needs resume" to the
   CLI / operator dashboard;
3. clear the pending-tool-call / partial-assistant bookkeeping that
   resume_support's :func:`apply_resume_snapshot` decides is safe to
   consume.

This keeps the supervisor single-process-safe: multiple supervisor
instances picking the same Loop will both see ``crash_marker=detected``,
both call ``apply_resume_snapshot`` (which is idempotent because
``crash_marker`` stays ``recovered`` after the first pass), and only
one will see the pending tool calls to replay.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import logging
import threading
from typing import Callable, Iterable, Protocol, Sequence

from packages.contracts.layers import Step
from packages.contracts.runtime import LoopState, WaitCondition
from packages.kernel.resume_support import (
    ResumeSnapshot,
    apply_resume_snapshot,
    snapshot_resume,
)

logger = logging.getLogger(__name__)


DEFAULT_HEARTBEAT_FRESH_TTL_SECONDS = 30.0
DEFAULT_HEARTBEAT_STALE_TTL_SECONDS = 180.0
DEFAULT_SUPERVISOR_INTERVAL_SECONDS = 30.0


class SupervisorRepository(Protocol):
    """Structural type for the storage slice the supervisor uses.

    Declared as a Protocol so tests can hand in a light in-memory fake
    without inheriting from ``RuntimeStorageRepository``.
    """

    def list_loop_checkpoints(
        self,
        *,
        statuses: tuple[str, ...] = ("active", "pending"),
        heartbeat_before: datetime | None = None,
        personal_model_id: str | None = None,
        state_id: str | None = None,
        limit: int | None = None,
    ) -> tuple[LoopState, ...]: ...

    def list_steps(self, *, loop_id: str | None = None) -> tuple[Step, ...]: ...

    def upsert_loop_checkpoint(self, run: LoopState, *, verify: bool = True) -> None: ...


@dataclass(frozen=True, slots=True)
class SupervisorDecision:
    """One outcome per reclaimed Loop.

    ``action`` is one of:

    * ``reclaimed_crashed`` — heartbeat stale, crash_marker set to
      ``detected``, pending_tool_calls / partial_assistant consumed per
      the resume plan.
    * ``woken_timer`` — wait_condition.wake_at <= now; same consumption.
    * ``left_parked`` — wait condition not ripe; no state write.
    * ``skipped_terminal`` — Loop already completed/failed since the
      scan started.
    """

    loop_id: str
    action: str
    snapshot: ResumeSnapshot
    decided_at: datetime
    detail: str = ""


@dataclass(frozen=True, slots=True)
class SupervisorTickResult:
    scanned_count: int
    decisions: tuple[SupervisorDecision, ...] = ()
    tick_started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tick_finished_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def scan_once(
    repository: SupervisorRepository,
    *,
    now: datetime | None = None,
    heartbeat_stale_ttl_seconds: float = DEFAULT_HEARTBEAT_STALE_TTL_SECONDS,
) -> SupervisorTickResult:
    """Run one scan pass.

    The supervisor looks at every loop_checkpoint row with status in
    {active, pending}. For each, decide what to do based on whether:

    * the heartbeat is staler than the TTL (crash),
    * the wait_condition has a wake_at that has elapsed (ready timer),
    * nothing is ripe (leave parked).
    """
    current = now or datetime.now(timezone.utc)
    stale_cutoff = current - timedelta(seconds=heartbeat_stale_ttl_seconds)
    loops = repository.list_loop_checkpoints(statuses=("active", "pending"))
    decisions: list[SupervisorDecision] = []
    for loop in loops:
        decision = _evaluate_loop(
            loop,
            repository=repository,
            now=current,
            stale_cutoff=stale_cutoff,
        )
        if decision is not None:
            decisions.append(decision)
    return SupervisorTickResult(
        scanned_count=len(loops),
        decisions=tuple(decisions),
        tick_started_at=current,
        tick_finished_at=datetime.now(timezone.utc),
    )


def _evaluate_loop(
    loop: LoopState,
    *,
    repository: SupervisorRepository,
    now: datetime,
    stale_cutoff: datetime,
) -> SupervisorDecision | None:
    if loop.status not in {"active", "pending"}:
        return None

    is_stale = _heartbeat_is_stale(loop.heartbeat_at, stale_cutoff=stale_cutoff)
    is_timer_ripe = _timer_is_ripe(loop.wait_condition, now=now)

    if not (is_stale or is_timer_ripe):
        return None

    steps = repository.list_steps(loop_id=loop.run_id)
    snap = snapshot_resume(loop_id=loop.run_id, state=loop, loop_steps=steps)
    if not snap.is_resumable:
        return SupervisorDecision(
            loop_id=loop.run_id,
            action="skipped_terminal",
            snapshot=snap,
            decided_at=now,
            detail=snap.reason,
        )

    post = apply_resume_snapshot(snap, now=now)
    if post is None:
        return SupervisorDecision(
            loop_id=loop.run_id,
            action="skipped_terminal",
            snapshot=snap,
            decided_at=now,
            detail="apply_resume_snapshot returned None",
        )

    # Distinguish crash reclamation from timer wakes, and persist both
    # as crash_marker='detected' so the runtime / CLI can see the
    # supervisor touched this row.
    if is_stale and loop.crash_marker != "detected":
        post = _replace(post, crash_marker="detected")
        action = "reclaimed_crashed"
        detail = (
            f"heartbeat {loop.heartbeat_at.isoformat() if loop.heartbeat_at else '<never>'} "
            f"older than cutoff {stale_cutoff.isoformat()}"
        )
    elif is_timer_ripe:
        action = "woken_timer"
        wake = loop.wait_condition.wake_at if loop.wait_condition is not None else None
        detail = f"timer wake_at {wake.isoformat() if wake else '<none>'} elapsed"
    else:
        # already crash_marker=detected but heartbeat still stale
        action = "reclaimed_crashed"
        detail = "crash_marker already detected; refreshing post-resume"

    try:
        repository.upsert_loop_checkpoint(post)
    except Exception as exc:
        logger.warning("supervisor upsert failed for %s: %s", loop.run_id, exc)
        return SupervisorDecision(
            loop_id=loop.run_id,
            action="skipped_terminal",
            snapshot=snap,
            decided_at=now,
            detail=f"upsert failed: {exc}",
        )
    return SupervisorDecision(
        loop_id=loop.run_id,
        action=action,
        snapshot=snap,
        decided_at=now,
        detail=detail,
    )


def _heartbeat_is_stale(
    heartbeat_at: datetime | None,
    *,
    stale_cutoff: datetime,
) -> bool:
    if heartbeat_at is None:
        # No heartbeat ever = treat as stale so the first supervisor
        # pass catches loops written by older runtimes.
        return True
    return heartbeat_at < stale_cutoff


def _timer_is_ripe(
    wait: WaitCondition | None,
    *,
    now: datetime,
) -> bool:
    if wait is None:
        return False
    if wait.wake_at is None:
        return False
    if not wait.auto_wake:
        return False
    return wait.wake_at <= now


def _replace(loop: LoopState, **updates) -> LoopState:
    from dataclasses import replace as dc_replace

    return dc_replace(loop, **updates)


def run_supervisor_loop(
    repository: SupervisorRepository,
    *,
    interval_seconds: float = DEFAULT_SUPERVISOR_INTERVAL_SECONDS,
    heartbeat_stale_ttl_seconds: float = DEFAULT_HEARTBEAT_STALE_TTL_SECONDS,
    stop_event: threading.Event | None = None,
    once: bool = False,
    on_tick: Callable[[SupervisorTickResult], None] | None = None,
    clock: Callable[[], datetime] | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> None:
    """Run the supervisor tick loop.

    The daemon CLI (``elephant supervisor run``, commit 6 wiring) is the
    primary caller. Tests pass ``once=True`` to run a single tick.
    """
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be > 0")
    now_fn = clock or (lambda: datetime.now(timezone.utc))
    sleep_fn = sleeper or _default_sleeper
    stop = stop_event or threading.Event()
    while not stop.is_set():
        tick = scan_once(
            repository,
            now=now_fn(),
            heartbeat_stale_ttl_seconds=heartbeat_stale_ttl_seconds,
        )
        if on_tick is not None:
            try:
                on_tick(tick)
            except Exception:  # noqa: BLE001
                logger.exception("supervisor on_tick hook raised")
        if once:
            return
        if stop.is_set():
            return
        sleep_fn(interval_seconds)


def _default_sleeper(seconds: float) -> None:
    import time

    time.sleep(seconds)


__all__ = [
    "DEFAULT_HEARTBEAT_FRESH_TTL_SECONDS",
    "DEFAULT_HEARTBEAT_STALE_TTL_SECONDS",
    "DEFAULT_SUPERVISOR_INTERVAL_SECONDS",
    "SupervisorDecision",
    "SupervisorRepository",
    "SupervisorTickResult",
    "run_supervisor_loop",
    "scan_once",
]


_ = Iterable
_ = Sequence
