"""Unit tests for packages.harness.supervisor."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import unittest

from packages.contracts.layers import Step
from packages.contracts.runtime import (
    LoopState,
    PendingToolCall,
    WaitCondition,
)
from packages.harness.supervisor import (
    scan_once,
)


def _now() -> datetime:
    return datetime(2026, 5, 3, 12, 0, 0, tzinfo=timezone.utc)


def _loop(
    *,
    run_id: str,
    status: str = "pending",
    heartbeat_at: datetime | None = None,
    wait_condition: WaitCondition | None = None,
    pending_tool_calls: tuple[PendingToolCall, ...] = (),
    partial: str | None = None,
    crash_marker: str | None = None,
) -> LoopState:
    now = _now()
    return LoopState(
        run_id=run_id,
        episode_id="ep-1",
        source_event_id="evt-1",
        prompt="hi",
        status=status,
        phase="waiting" if status == "pending" else "model",
        step_count=1,
        model_turn_count=1,
        tool_call_count=0,
        max_model_turns=100,
        max_wall_time_seconds=3600,
        created_at=now,
        updated_at=now,
        wait_condition=wait_condition,
        pending_tool_calls=pending_tool_calls,
        partial_assistant=partial,
        heartbeat_at=heartbeat_at,
        crash_marker=crash_marker,
    )


def _pending(call_id: str) -> PendingToolCall:
    return PendingToolCall(
        call_id=call_id,
        tool_name="tool.shell.run",
        arguments={"cmd": "echo"},
        started_at=_now(),
        step_id=f"step:{call_id}",
        status="dispatched",
        idempotency_key=f"idem:{call_id}",
    )


@dataclass
class _FakeRepository:
    loops: list[LoopState] = field(default_factory=list)
    steps_by_loop: dict[str, list[Step]] = field(default_factory=dict)
    upserts: list[LoopState] = field(default_factory=list)

    def list_loop_checkpoints(
        self,
        *,
        statuses: tuple[str, ...] = ("active", "pending"),
        heartbeat_before: datetime | None = None,
        personal_model_id: str | None = None,
        state_id: str | None = None,
        limit: int | None = None,
    ) -> tuple[LoopState, ...]:
        result = [loop for loop in self.loops if loop.status in statuses]
        return tuple(result)

    def list_steps(self, *, loop_id: str | None = None) -> tuple[Step, ...]:
        if loop_id is None:
            return ()
        return tuple(self.steps_by_loop.get(loop_id, ()))

    def upsert_loop_checkpoint(self, run: LoopState, *, verify: bool = True) -> None:
        self.upserts.append(run)
        for index, existing in enumerate(self.loops):
            if existing.run_id == run.run_id:
                self.loops[index] = run
                return
        self.loops.append(run)


class SupervisorScanTest(unittest.TestCase):
    def test_stale_heartbeat_marks_crash_and_consumes_partial(self) -> None:
        now = _now()
        repo = _FakeRepository(
            loops=[
                _loop(
                    run_id="loop:stale",
                    status="active",
                    heartbeat_at=now - timedelta(minutes=10),
                    wait_condition=WaitCondition(kind="budget_exhausted"),
                    pending_tool_calls=(_pending("call-A"),),
                    partial="incomplete answer",
                )
            ]
        )
        result = scan_once(repo, now=now, heartbeat_stale_ttl_seconds=60)
        self.assertEqual(result.scanned_count, 1)
        self.assertEqual(len(result.decisions), 1)
        decision = result.decisions[0]
        self.assertEqual(decision.action, "reclaimed_crashed")
        self.assertEqual(len(repo.upserts), 1)
        reclaimed = repo.upserts[0]
        self.assertEqual(reclaimed.crash_marker, "detected")
        self.assertIsNone(reclaimed.partial_assistant)

    def test_fresh_heartbeat_left_alone(self) -> None:
        now = _now()
        repo = _FakeRepository(
            loops=[
                _loop(
                    run_id="loop:fresh",
                    status="active",
                    heartbeat_at=now - timedelta(seconds=5),
                    wait_condition=WaitCondition(kind="budget_exhausted"),
                )
            ]
        )
        result = scan_once(repo, now=now, heartbeat_stale_ttl_seconds=60)
        self.assertEqual(len(result.decisions), 0)
        self.assertEqual(repo.upserts, [])

    def test_timer_wake_ripe_wakes_loop(self) -> None:
        now = _now()
        repo = _FakeRepository(
            loops=[
                _loop(
                    run_id="loop:timer",
                    status="pending",
                    heartbeat_at=now,
                    wait_condition=WaitCondition(
                        kind="timer",
                        wake_at=now - timedelta(seconds=1),
                        auto_wake=True,
                    ),
                )
            ]
        )
        result = scan_once(repo, now=now, heartbeat_stale_ttl_seconds=60)
        self.assertEqual(len(result.decisions), 1)
        self.assertEqual(result.decisions[0].action, "woken_timer")

    def test_timer_not_yet_ripe_left_parked(self) -> None:
        now = _now()
        repo = _FakeRepository(
            loops=[
                _loop(
                    run_id="loop:timer-future",
                    status="pending",
                    heartbeat_at=now,
                    wait_condition=WaitCondition(
                        kind="timer",
                        wake_at=now + timedelta(minutes=5),
                        auto_wake=True,
                    ),
                )
            ]
        )
        result = scan_once(repo, now=now, heartbeat_stale_ttl_seconds=60)
        self.assertEqual(len(result.decisions), 0)

    def test_auto_wake_disabled_not_ripe_even_if_wake_at_passed(self) -> None:
        """A user-gated park (auto_wake=False) waits for an explicit resume."""
        now = _now()
        repo = _FakeRepository(
            loops=[
                _loop(
                    run_id="loop:manual",
                    status="pending",
                    heartbeat_at=now,
                    wait_condition=WaitCondition(
                        kind="budget_exhausted",
                        wake_at=now - timedelta(hours=1),
                        auto_wake=False,
                    ),
                )
            ]
        )
        result = scan_once(repo, now=now, heartbeat_stale_ttl_seconds=60)
        self.assertEqual(len(result.decisions), 0)

    def test_missing_heartbeat_treated_as_stale(self) -> None:
        now = _now()
        repo = _FakeRepository(
            loops=[
                _loop(
                    run_id="loop:no-hb",
                    status="pending",
                    heartbeat_at=None,
                    wait_condition=WaitCondition(kind="budget_exhausted"),
                )
            ]
        )
        result = scan_once(repo, now=now, heartbeat_stale_ttl_seconds=60)
        self.assertEqual(len(result.decisions), 1)
        self.assertEqual(result.decisions[0].action, "reclaimed_crashed")

    def test_existing_completed_step_skips_tool_replay_on_reclaim(self) -> None:
        now = _now()
        repo = _FakeRepository(
            loops=[
                _loop(
                    run_id="loop:step-done",
                    status="active",
                    heartbeat_at=now - timedelta(hours=1),
                    wait_condition=WaitCondition(kind="budget_exhausted"),
                    pending_tool_calls=(_pending("call-A"),),
                )
            ],
            steps_by_loop={
                "loop:step-done": [
                    Step(
                        step_id="step:call-A",
                        loop_id="loop:step-done",
                        episode_id="ep-1",
                        state_id="state-1",
                        personal_model_id="pm-1",
                        phase="acting",
                        action="call_tool",
                        status="completed",
                        sequence=0,
                        created_at=now,
                        outcome="ok",
                        metadata={
                            "tool_call_id": "call-A",
                            "tool_name": "tool.shell.run",
                        },
                    )
                ]
            },
        )
        result = scan_once(repo, now=now, heartbeat_stale_ttl_seconds=60)
        self.assertEqual(len(result.decisions), 1)
        reclaimed = repo.upserts[0]
        # call-A was recognized as already completed; pending_tool_calls now empty.
        self.assertEqual(reclaimed.pending_tool_calls, ())


if __name__ == "__main__":
    unittest.main()
