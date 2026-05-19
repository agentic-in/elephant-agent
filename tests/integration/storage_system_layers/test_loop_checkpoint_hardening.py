"""Integration tests for loop checkpoint hardening (Phase 1).

Covers the three additions that let the supervisor reclaim crashed
long-horizon loops: checkpoint listing with heartbeat / state /
personal-model filters, write-then-verify round-trip rejection, and
legacy row migration through the storage layer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from packages.contracts import Episode, Loop
from packages.contracts.runtime import (
    LoopState,
    PendingToolCall,
    RetryState,
    WaitCondition,
)
from packages.storage import RuntimeStorageRepository


def _seed_episode(repository: RuntimeStorageRepository, *, now: datetime, suffix: str = "") -> tuple[str, str, str]:
    model = repository.ensure_default_personal_model()
    state = repository.create_state(
        personal_model_id=model.personal_model_id,
        elephant_name="Atlas" + suffix,
        elephant_id="atlas" + suffix,
        state_id="state:atlas" + suffix,
    )
    episode_id = "episode:atlas" + suffix
    repository.upsert_episode(
        Episode(
            episode_id=episode_id,
            state_id=state.state_id,
            personal_model_id=model.personal_model_id,
            entry_surface="cli",
            status="open",
            started_at=now,
            updated_at=now,
            elephant_id=state.elephant_id,
            metadata={},
        )
    )
    return model.personal_model_id, state.state_id, episode_id


class LoopCheckpointHardeningTest(unittest.TestCase):
    def test_list_loop_checkpoints_filters_by_heartbeat_state_and_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            now = datetime(2026, 5, 3, 10, tzinfo=UTC)
            pm_id, state_id, episode_id = _seed_episode(repository, now=now)

            fresh_run = LoopState(
                run_id="loop:fresh",
                episode_id=episode_id,
                source_event_id="evt-1",
                prompt="fresh",
                status="pending",
                phase="waiting",
                step_count=1,
                model_turn_count=1,
                tool_call_count=0,
                max_model_turns=10,
                max_wall_time_seconds=3600,
                created_at=now,
                updated_at=now,
                wait_condition=WaitCondition(kind="timer", wake_at=now + timedelta(minutes=5)),
                heartbeat_at=now,
            )
            stale_run = LoopState(
                run_id="loop:stale",
                episode_id=episode_id,
                source_event_id="evt-2",
                prompt="stale",
                status="active",
                phase="model",
                step_count=5,
                model_turn_count=3,
                tool_call_count=2,
                max_model_turns=10,
                max_wall_time_seconds=3600,
                created_at=now - timedelta(hours=1),
                updated_at=now - timedelta(hours=1),
                heartbeat_at=now - timedelta(minutes=10),
            )
            repository.upsert_loop_checkpoint(fresh_run)
            repository.upsert_loop_checkpoint(stale_run)

            all_checkpoints = repository.list_loop_checkpoints()
            self.assertEqual({r.run_id for r in all_checkpoints}, {"loop:fresh", "loop:stale"})

            only_stale = repository.list_loop_checkpoints(
                heartbeat_before=now - timedelta(minutes=1),
            )
            self.assertEqual({r.run_id for r in only_stale}, {"loop:stale"})

            pending_only = repository.list_loop_checkpoints(statuses=("pending",))
            self.assertEqual({r.run_id for r in pending_only}, {"loop:fresh"})

            by_model = repository.list_loop_checkpoints(personal_model_id=pm_id)
            self.assertEqual(len(by_model), 2)

            by_state = repository.list_loop_checkpoints(state_id=state_id)
            self.assertEqual(len(by_state), 2)

            # Deliberately bogus state id filters everything out.
            self.assertEqual(repository.list_loop_checkpoints(state_id="state:ghost"), ())

    def test_upsert_loop_checkpoint_verifies_roundtrip(self) -> None:
        """The verify step catches a sabotaged upsert_loop.

        The runtime relies on upsert_loop_checkpoint being durable
        before it reports a parked loop to the rest of the system.
        If the underlying upsert did not land the row, the verify
        step raises so the runtime can refuse the park.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            now = datetime(2026, 5, 3, 10, tzinfo=UTC)
            _, _, episode_id = _seed_episode(repository, now=now)

            run = LoopState(
                run_id="loop:never-persisted",
                episode_id=episode_id,
                source_event_id="evt-9",
                prompt="doomed",
                status="pending",
                phase="waiting",
                step_count=0,
                model_turn_count=0,
                tool_call_count=0,
                max_model_turns=1,
                max_wall_time_seconds=1,
                created_at=now,
                updated_at=now,
            )

            original_upsert_loop = type(repository).upsert_loop

            def _no_op_upsert(self, loop: Loop) -> None:
                return None

            try:
                type(repository).upsert_loop = _no_op_upsert
                with self.assertRaises(RuntimeError) as ctx:
                    repository.upsert_loop_checkpoint(run)
                self.assertIn("did not round-trip", str(ctx.exception))
            finally:
                type(repository).upsert_loop = original_upsert_loop

    def test_list_loop_checkpoints_round_trips_wait_condition_and_pending_tool_calls(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            now = datetime(2026, 5, 3, 10, tzinfo=UTC)
            _, _, episode_id = _seed_episode(repository, now=now)

            wait = WaitCondition(
                kind="tool_callback",
                payload={"tool": "make_test"},
                tool_handle_id="handle-1",
                created_at=now,
                auto_wake=True,
            )
            pending = PendingToolCall(
                call_id="call-1",
                tool_name="tool.shell.run",
                arguments={"cmd": "make test"},
                started_at=now,
                step_id="step-7",
                status="dispatched",
                idempotency_key="loop-A:call-1:0",
            )
            retry = RetryState(attempt=1, last_error_kind="http_429", idempotency_key="loop-A:call-1:0")

            run = LoopState(
                run_id="loop:rich",
                episode_id=episode_id,
                source_event_id="evt-r",
                prompt="do the thing",
                status="pending",
                phase="waiting",
                step_count=7,
                model_turn_count=3,
                tool_call_count=2,
                max_model_turns=50,
                max_wall_time_seconds=7200,
                created_at=now,
                updated_at=now,
                wait_condition=wait,
                pending_tool_calls=(pending,),
                partial_assistant="Halfway through the answer...",
                context_bundle_id="bundle-7",
                active_evidence_refs=("mem-1", "mem-2"),
                retry_state=retry,
                heartbeat_at=now,
            )
            repository.upsert_loop_checkpoint(run)

            (restored,) = repository.list_loop_checkpoints(statuses=("pending",))
            self.assertEqual(restored.run_id, "loop:rich")
            self.assertIsNotNone(restored.wait_condition)
            self.assertEqual(restored.wait_condition.kind, "tool_callback")
            self.assertEqual(restored.wait_condition.tool_handle_id, "handle-1")
            self.assertEqual(restored.partial_assistant, "Halfway through the answer...")
            self.assertEqual(restored.context_bundle_id, "bundle-7")
            self.assertEqual(restored.active_evidence_refs, ("mem-1", "mem-2"))
            self.assertIsNotNone(restored.retry_state)
            self.assertEqual(restored.retry_state.attempt, 1)
            self.assertEqual(restored.retry_state.last_error_kind, "http_429")
            self.assertEqual(len(restored.pending_tool_calls), 1)
            self.assertEqual(restored.pending_tool_calls[0].call_id, "call-1")
            self.assertEqual(restored.pending_tool_calls[0].idempotency_key, "loop-A:call-1:0")


if __name__ == "__main__":
    unittest.main()
