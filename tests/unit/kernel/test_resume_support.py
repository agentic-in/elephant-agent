"""Unit tests for packages.kernel.resume_support.

Covers the three idempotency locks Phase 1 expects the resume path to
apply: pending tool call replay planning, partial-assistant capture,
and post-resume state compaction.
"""

from __future__ import annotations

from datetime import datetime, timezone
import unittest

from packages.contracts.layers import Step
from packages.contracts.runtime import (
    LoopState,
    PendingToolCall,
    RetryState,
    WaitCondition,
)
from packages.kernel.resume_support import (
    apply_resume_snapshot,
    plan_pending_tool_replay,
    snapshot_resume,
)


def _now() -> datetime:
    return datetime(2026, 5, 3, 12, 0, 0, tzinfo=timezone.utc)


def _state(
    *,
    status: str = "pending",
    pending: tuple[PendingToolCall, ...] = (),
    partial: str | None = None,
    wait: WaitCondition | None = None,
    retry: RetryState | None = None,
) -> LoopState:
    now = _now()
    return LoopState(
        run_id="run-1",
        episode_id="ep-1",
        source_event_id="evt-1",
        prompt="hi",
        status=status,
        phase="waiting" if status == "pending" else "model",
        step_count=len(pending),
        model_turn_count=1,
        tool_call_count=len(pending),
        max_model_turns=100,
        max_wall_time_seconds=3600,
        created_at=now,
        updated_at=now,
        wait_condition=wait,
        pending_tool_calls=pending,
        partial_assistant=partial,
        retry_state=retry,
    )


def _pending(
    call_id: str,
    *,
    status: str = "dispatched",
    idempotency_key: str | None = None,
) -> PendingToolCall:
    return PendingToolCall(
        call_id=call_id,
        tool_name="tool.shell.run",
        arguments={"cmd": f"echo {call_id}"},
        started_at=_now(),
        step_id=f"step:{call_id}",
        status=status,
        idempotency_key=idempotency_key or f"idem:{call_id}",
    )


def _step_for(call_id: str, *, status: str = "completed") -> Step:
    now = _now()
    return Step(
        step_id=f"step:{call_id}",
        loop_id="run-1",
        episode_id="ep-1",
        state_id="state-1",
        personal_model_id="pm-1",
        phase="acting",
        action="call_tool",
        status=status,
        sequence=0,
        created_at=now,
        outcome="ok",
        metadata={"tool_call_id": call_id, "tool_name": "tool.shell.run"},
    )


class PlanPendingToolReplayTest(unittest.TestCase):
    def test_skips_tools_with_existing_completed_step(self) -> None:
        plans = plan_pending_tool_replay(
            [_pending("call-A")],
            loop_steps=[_step_for("call-A")],
        )
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].action, "skip")
        self.assertIn("step:call-A", plans[0].reason)

    def test_replays_when_no_completed_step_exists(self) -> None:
        plans = plan_pending_tool_replay(
            [_pending("call-B")],
            loop_steps=[],
        )
        self.assertEqual(plans[0].action, "replay")

    def test_injects_when_status_is_done_unread(self) -> None:
        plans = plan_pending_tool_replay(
            [_pending("call-C", status="done_unread")],
            loop_steps=[],
        )
        self.assertEqual(plans[0].action, "inject")

    def test_polls_when_status_is_running(self) -> None:
        plans = plan_pending_tool_replay(
            [_pending("call-D", status="running")],
            loop_steps=[],
        )
        self.assertEqual(plans[0].action, "poll")

    def test_failed_step_does_not_count_as_completion(self) -> None:
        """A failed Step means the tool crashed the kernel mid-dispatch.

        Replay should still happen so the idempotency key can drive
        a deduplicated call.
        """
        plans = plan_pending_tool_replay(
            [_pending("call-E")],
            loop_steps=[_step_for("call-E", status="failed")],
        )
        self.assertEqual(plans[0].action, "replay")


class SnapshotResumeTest(unittest.TestCase):
    def test_missing_state_not_resumable(self) -> None:
        snap = snapshot_resume(loop_id="run-missing", state=None, loop_steps=())
        self.assertFalse(snap.is_resumable)
        self.assertIn("no loop checkpoint", snap.reason)

    def test_terminal_state_not_resumable(self) -> None:
        state = _state(status="completed")
        snap = snapshot_resume(loop_id=state.run_id, state=state, loop_steps=())
        self.assertFalse(snap.is_resumable)
        self.assertIn("terminal", snap.reason)

    def test_active_pending_state_resumable_with_full_fields(self) -> None:
        state = _state(
            pending=(_pending("call-A"), _pending("call-B")),
            partial="Half of the answer",
            wait=WaitCondition(kind="tool_callback", tool_handle_id="h"),
            retry=RetryState(attempt=2, last_error_kind="http_429"),
        )
        snap = snapshot_resume(
            loop_id=state.run_id,
            state=state,
            loop_steps=(_step_for("call-A"),),
        )
        self.assertTrue(snap.is_resumable)
        self.assertEqual(snap.partial_assistant, "Half of the answer")
        self.assertEqual(snap.wait_condition_kind, "tool_callback")
        self.assertEqual(snap.retry_attempt, 2)
        actions = [p.action for p in snap.replay_plans]
        self.assertEqual(actions, ["skip", "replay"])


class ApplyResumeSnapshotTest(unittest.TestCase):
    def test_clears_partial_and_skipped_pending(self) -> None:
        state = _state(
            pending=(_pending("call-A"), _pending("call-B")),
            partial="partial tokens",
            wait=WaitCondition(kind="budget_exhausted"),
        )
        snap = snapshot_resume(
            loop_id=state.run_id,
            state=state,
            loop_steps=(_step_for("call-A"),),
        )
        applied = apply_resume_snapshot(snap)
        self.assertIsNotNone(applied)
        # call-A was skipped, call-B remains to replay
        self.assertEqual([c.call_id for c in applied.pending_tool_calls], ["call-B"])
        self.assertIsNone(applied.partial_assistant)
        self.assertEqual(applied.crash_marker, "recovered")
        # heartbeat refreshed
        self.assertIsNotNone(applied.heartbeat_at)

    def test_none_state_applies_to_none(self) -> None:
        snap = snapshot_resume(loop_id="missing", state=None, loop_steps=())
        self.assertIsNone(apply_resume_snapshot(snap))

    def test_done_unread_entries_are_cleared(self) -> None:
        state = _state(
            pending=(
                _pending("call-A", status="done_unread"),
                _pending("call-B"),
            )
        )
        snap = snapshot_resume(loop_id=state.run_id, state=state, loop_steps=())
        applied = apply_resume_snapshot(snap)
        self.assertIsNotNone(applied)
        # call-A 'inject' was consumed; call-B 'replay' remains.
        self.assertEqual([c.call_id for c in applied.pending_tool_calls], ["call-B"])


if __name__ == "__main__":
    unittest.main()
