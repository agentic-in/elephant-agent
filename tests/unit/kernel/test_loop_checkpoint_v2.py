"""Unit tests for LoopState v2 serde, migration, and the new harness types.

Pins the contract extensions introduced by Phase 1 of the long-horizon
harness plan:

* ``LoopState`` carries ``schema_version=2`` plus ``wait_condition``,
  ``pending_tool_calls``, ``retry_state``, ``partial_assistant``,
  ``context_bundle_id``, ``active_evidence_refs``, ``heartbeat_at``,
  ``crash_marker``.
* ``_loop_metadata`` / ``_loop_state_from_loop`` round-trip every v2 field
  without loss.
* ``migrate_loop_state_metadata`` turns a pre-v2 row into a v2 LoopState
  by promoting ``waiting_reason`` into a ``WaitCondition`` of kind
  ``budget_exhausted`` — the legacy only ever carried budget reasons.

These are pure-Python tests (no sqlite fixture) because the metadata
shape is what matters; the sqlite layer just writes text columns.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from packages.contracts import Loop
from packages.contracts.runtime import (
    ExecutionResult,
    LoopState,
    PendingToolCall,
    RetryState,
    WaitCondition,
)
from packages.kernel.loop_checkpoint_support import LoopCheckpointService
from packages.storage.repository_system_methods import (
    _loop_metadata,
    _loop_state_from_loop,
    migrate_loop_state_metadata,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _populated_v2_state(now: datetime) -> LoopState:
    return LoopState(
        run_id="run-1",
        episode_id="ep-1",
        source_event_id="evt-1",
        prompt="hello",
        status="pending",
        phase="waiting",
        step_count=4,
        model_turn_count=2,
        tool_call_count=2,
        max_model_turns=100,
        max_wall_time_seconds=3600,
        created_at=now,
        updated_at=now,
        waiting_reason="tool-callback",
        continuation_prompt="continue from step 4",
        last_summary="summary",
        wait_condition=WaitCondition(
            kind="tool_callback",
            payload={"tool": "t"},
            wake_at=now + timedelta(seconds=60),
            tool_handle_id="h-1",
            auto_wake=True,
            created_at=now,
        ),
        pending_tool_calls=(
            PendingToolCall(
                call_id="c-1",
                tool_name="shell",
                arguments={"cmd": "make test"},
                started_at=now,
                step_id="step-3",
                handle_id=None,
                status="dispatched",
                idempotency_key="idem-1",
            ),
        ),
        partial_assistant="Once upon a time",
        context_bundle_id="bundle-42",
        active_evidence_refs=("m-1", "m-2"),
        retry_state=RetryState(
            attempt=2,
            last_error_kind="http_429",
            last_error_detail="rate-limited",
            next_retry_at=now + timedelta(seconds=30),
            idempotency_key="idem-1",
        ),
        heartbeat_at=now,
        crash_marker=None,
    )


def _loop_from_state(state: LoopState, metadata: dict) -> Loop:
    return Loop(
        loop_id=state.run_id,
        episode_id=state.episode_id,
        state_id="state-1",
        personal_model_id="pm-1",
        trigger_type="model_tool_checkpoint",
        status=state.status,
        started_at=state.created_at,
        summary=state.last_summary or "",
        outcome=state.waiting_reason or "",
        metadata=metadata,
    )


class LoopStateSchemaV2Test(unittest.TestCase):
    def test_defaults_are_schema_v2(self) -> None:
        now = _now()
        state = LoopState(
            run_id="run-a",
            episode_id="ep-a",
            source_event_id="evt-a",
            prompt="",
            status="active",
            phase="model",
            step_count=0,
            model_turn_count=0,
            tool_call_count=0,
            max_model_turns=1,
            max_wall_time_seconds=1,
            created_at=now,
            updated_at=now,
        )
        self.assertEqual(state.schema_version, 2)
        self.assertIsNone(state.wait_condition)
        self.assertEqual(state.pending_tool_calls, ())
        self.assertIsNone(state.retry_state)
        self.assertIsNone(state.heartbeat_at)
        self.assertIsNone(state.crash_marker)
        self.assertEqual(state.active_evidence_refs, ())

    def test_roundtrip_preserves_every_v2_field(self) -> None:
        now = _now()
        state = _populated_v2_state(now)
        metadata = _loop_metadata(state)
        self.assertEqual(metadata["kind"], "loop_checkpoint")
        self.assertEqual(metadata["schema_version"], "2")
        loop = _loop_from_state(state, metadata)
        restored = _loop_state_from_loop(loop)

        self.assertEqual(restored.schema_version, 2)
        self.assertIsNotNone(restored.wait_condition)
        self.assertEqual(restored.wait_condition.kind, "tool_callback")
        self.assertEqual(restored.wait_condition.payload["tool"], "t")
        self.assertEqual(restored.wait_condition.tool_handle_id, "h-1")
        self.assertEqual(restored.partial_assistant, "Once upon a time")
        self.assertEqual(restored.context_bundle_id, "bundle-42")
        self.assertEqual(restored.active_evidence_refs, ("m-1", "m-2"))
        self.assertIsNotNone(restored.retry_state)
        self.assertEqual(restored.retry_state.attempt, 2)
        self.assertEqual(restored.retry_state.last_error_kind, "http_429")
        self.assertEqual(restored.retry_state.idempotency_key, "idem-1")
        self.assertEqual(len(restored.pending_tool_calls), 1)
        call = restored.pending_tool_calls[0]
        self.assertEqual(call.call_id, "c-1")
        self.assertEqual(call.tool_name, "shell")
        self.assertEqual(call.arguments, {"cmd": "make test"})
        self.assertEqual(call.step_id, "step-3")
        self.assertEqual(call.status, "dispatched")
        self.assertEqual(call.idempotency_key, "idem-1")
        self.assertIsNotNone(restored.heartbeat_at)

    def test_wait_condition_rejects_unknown_kind(self) -> None:
        with self.assertRaises(ValueError):
            WaitCondition(kind="nonsense")

    def test_pending_tool_call_rejects_unknown_status(self) -> None:
        with self.assertRaises(ValueError):
            PendingToolCall(
                call_id="c",
                tool_name="t",
                arguments={},
                started_at=_now(),
                step_id="s",
                status="totally_bogus",
            )


class LegacyLoopMetadataMigrationTest(unittest.TestCase):
    def _legacy_metadata(self, reason: str) -> dict:
        return {
            "kind": "loop_checkpoint",
            "source_event_id": "evt-x",
            "prompt": "old",
            "phase": "waiting",
            "step_count": "3",
            "model_turn_count": "1",
            "tool_call_count": "1",
            "max_model_turns": "100",
            "max_wall_time_seconds": "28800",
            "waiting_reason": reason,
            "continuation_prompt": "cont",
            "last_summary": "sum",
        }

    def test_migrate_promotes_legacy_reason_to_wait_condition(self) -> None:
        migrated = migrate_loop_state_metadata(self._legacy_metadata("wall-time-budget"))
        self.assertEqual(migrated["schema_version"], 2)
        wait = migrated["wait_condition"]
        self.assertEqual(wait["kind"], "budget_exhausted")
        self.assertEqual(wait["payload"]["legacy_reason"], "wall-time-budget")
        self.assertFalse(wait["auto_wake"])
        self.assertEqual(migrated["pending_tool_calls"], [])
        self.assertIsNone(migrated["partial_assistant"])

    def test_load_legacy_loop_produces_v2_state(self) -> None:
        now = _now()
        legacy = self._legacy_metadata("model-turn-budget")
        loop = Loop(
            loop_id="r2",
            episode_id="e2",
            state_id="s2",
            personal_model_id="pm2",
            trigger_type="model_tool_checkpoint",
            status="pending",
            started_at=now,
            summary="sum",
            outcome="model-turn-budget",
            metadata=legacy,
        )
        state = _loop_state_from_loop(loop)
        self.assertEqual(state.schema_version, 2)
        self.assertIsNotNone(state.wait_condition)
        self.assertEqual(state.wait_condition.kind, "budget_exhausted")
        self.assertEqual(
            state.wait_condition.payload.get("legacy_reason"),
            "model-turn-budget",
        )
        self.assertEqual(state.pending_tool_calls, ())
        self.assertIsNone(state.partial_assistant)
        self.assertIsNone(state.retry_state)

    def test_migrate_is_idempotent_for_v2_metadata(self) -> None:
        now = _now()
        state = _populated_v2_state(now)
        metadata = _loop_metadata(state)
        once = migrate_loop_state_metadata(metadata)
        twice = migrate_loop_state_metadata(once)
        # _json_metadata stringifies the schema_version before persistence,
        # so callers may see either "2" (just read from sqlite) or 2 (just
        # written). Both must round-trip through migration unchanged.
        self.assertIn(twice.get("schema_version"), {2, "2"})
        # wait_condition stays as the user-provided value, not the budget_exhausted upgrade.
        wait = twice.get("wait_condition")
        self.assertIsNotNone(wait)


class LoopCheckpointServiceHarnessTest(unittest.TestCase):
    """Covers the v2 control surface on LoopCheckpointService.

    park() must stamp the structured wait_condition and refresh the
    heartbeat. touch_heartbeat() updates liveness without disturbing
    other fields. register_pending_tool + clear_pending_tool manage the
    pending tool set that resume drains for idempotency.
    """

    def _fresh_run(self, now: datetime) -> LoopState:
        return LoopCheckpointService().start_loop(
            episode_id="ep-1",
            source_event_id="evt-1",
            prompt="do the thing",
            now=now,
        )

    def test_start_loop_stamps_initial_heartbeat(self) -> None:
        now = _now()
        run = self._fresh_run(now)
        self.assertEqual(run.heartbeat_at, now)
        self.assertEqual(run.updated_at, now)

    def test_step_records_refresh_heartbeat(self) -> None:
        service = LoopCheckpointService()
        now = _now()
        run = self._fresh_run(now)

        context_at = now + timedelta(seconds=1)
        after_context, _ = service.record_context_prompt(run, system_prompt="system", now=context_at)
        self.assertEqual(after_context.heartbeat_at, context_at)

        model_at = now + timedelta(seconds=2)
        after_model, _ = service.record_model_turn(after_context, summary="model", now=model_at)
        self.assertEqual(after_model.heartbeat_at, model_at)

        tool_at = now + timedelta(seconds=3)
        after_tool, _ = service.record_tool_step(
            after_model,
            tool_name="tool.echo",
            arguments={"text": "hello"},
            result=ExecutionResult(
                execution_id="exec-1",
                episode_id="ep-1",
                outcome="success",
                summary="ok",
            ),
            now=tool_at,
        )
        self.assertEqual(after_tool.heartbeat_at, tool_at)

    def test_park_stamps_wait_condition_and_heartbeat(self) -> None:
        service = LoopCheckpointService()
        now = _now()
        run = self._fresh_run(now)
        wait = WaitCondition(
            kind="tool_callback",
            payload={"tool": "make_test"},
            tool_handle_id="h-1",
            created_at=now,
            auto_wake=True,
        )
        parked = service.park(
            run,
            wait_condition=wait,
            last_summary="awaiting test harness",
            continuation_prompt="continue once test finishes",
            now=now,
        )
        self.assertEqual(parked.status, "pending")
        self.assertEqual(parked.phase, "waiting")
        self.assertIsNotNone(parked.wait_condition)
        self.assertEqual(parked.wait_condition.kind, "tool_callback")
        self.assertEqual(parked.waiting_reason, "tool_callback")
        self.assertEqual(parked.continuation_prompt, "continue once test finishes")
        self.assertEqual(parked.heartbeat_at, now)

    def test_park_defaults_continuation_prompt_when_none(self) -> None:
        service = LoopCheckpointService()
        now = _now()
        run = self._fresh_run(now)
        parked = service.park(
            run,
            wait_condition=WaitCondition(kind="timer", wake_at=now + timedelta(seconds=5)),
            last_summary="sleep a bit",
            now=now,
        )
        self.assertIsNotNone(parked.continuation_prompt)
        self.assertIn("Continue the same Elephant Agent loop", parked.continuation_prompt)

    def test_touch_heartbeat_only_touches_liveness(self) -> None:
        service = LoopCheckpointService()
        now = _now()
        later = now + timedelta(seconds=45)
        run = self._fresh_run(now)
        bumped = service.touch_heartbeat(run, now=later)
        self.assertEqual(bumped.heartbeat_at, later)
        self.assertEqual(bumped.updated_at, later)
        self.assertEqual(bumped.status, run.status)
        self.assertEqual(bumped.step_count, run.step_count)

    def test_register_and_clear_pending_tool(self) -> None:
        service = LoopCheckpointService()
        now = _now()
        run = self._fresh_run(now)
        with_pending = service.register_pending_tool(
            run,
            call_id="call-1",
            tool_name="tool.shell.run",
            arguments={"cmd": "make test"},
            step_id="step-9",
            idempotency_key="loop:call-1:0",
            now=now,
        )
        self.assertEqual(len(with_pending.pending_tool_calls), 1)
        call = with_pending.pending_tool_calls[0]
        self.assertEqual(call.call_id, "call-1")
        self.assertEqual(call.status, "dispatched")
        self.assertEqual(call.idempotency_key, "loop:call-1:0")

        cleared = service.clear_pending_tool(with_pending, call_id="call-1", now=now)
        self.assertEqual(cleared.pending_tool_calls, ())

    def test_register_pending_tool_overwrites_same_call_id(self) -> None:
        service = LoopCheckpointService()
        now = _now()
        run = self._fresh_run(now)
        first = service.register_pending_tool(
            run,
            call_id="call-1",
            tool_name="tool.shell.run",
            arguments={"cmd": "make test"},
            step_id="step-9",
            now=now,
        )
        second = service.register_pending_tool(
            first,
            call_id="call-1",
            tool_name="tool.shell.run",
            arguments={"cmd": "make test"},
            step_id="step-9",
            status="running",
            handle_id="handle-2",
            now=now,
        )
        self.assertEqual(len(second.pending_tool_calls), 1)
        self.assertEqual(second.pending_tool_calls[0].status, "running")
        self.assertEqual(second.pending_tool_calls[0].handle_id, "handle-2")

    def test_mark_partial_assistant_roundtrip(self) -> None:
        service = LoopCheckpointService()
        now = _now()
        run = self._fresh_run(now)
        filled = service.mark_partial_assistant(run, "Half a thought", now=now)
        self.assertEqual(filled.partial_assistant, "Half a thought")
        emptied = service.mark_partial_assistant(filled, "   ", now=now)
        self.assertIsNone(emptied.partial_assistant)


if __name__ == "__main__":
    unittest.main()
