from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from apps.episode_runtime import install_app_episode_runtime
from packages.capabilities import CapabilityDescriptor
from packages.contracts import ContextBundle, ExecutionResult
from packages.contracts.layers import Episode
from packages.contracts.runtime import (
    EvidenceRetrievalRequest,
    EvidenceRetrievalResult,
    RecallEvidence,
    PersonalModelRuntimeState,
    RecallReasons,
    RuntimeModelChoice,
    EmbeddingIndexPolicy,
)
from packages.kernel import KernelDependencies, KernelService, KernelSourceRequest
from packages.kernel.loop_checkpoint_support import LoopCheckpointService
from packages.storage import RuntimeStorageRepository


class _RecallCapability:
    descriptor = CapabilityDescriptor("recall.test", "recall", "1")

    def retrieve_evidence(self, request: EvidenceRetrievalRequest) -> EvidenceRetrievalResult:
        return EvidenceRetrievalResult(
            request=request,
            scope_episode_ids=(request.episode_id,),
            scope_reason="test",
            candidates=(),
            recall_reasons=RecallReasons(scope_reason="test"),
            index_policy=EmbeddingIndexPolicy(
                model_id="test",
                lexical_index_version="test",
                embedding_index_version="test",
            ),
        )


class _ContextCapability:
    descriptor = CapabilityDescriptor("context.test", "context", "1")

    def assemble(
        self,
        episode: Episode,
        work_items: tuple[object, ...],
        recall_items: tuple[RecallEvidence, ...],
        *,
        state_focus=None,
    ) -> ContextBundle:
        del work_items, recall_items, state_focus
        return ContextBundle(
            bundle_id=f"context:{episode.episode_id}",
            episode_id=episode.episode_id,
            token_budget=2048,
        )


class _ModelProvider:
    descriptor = CapabilityDescriptor("model.test", "model_provider", "1")

    def selection_state(self) -> RuntimeModelChoice | None:
        return None

    def generate(
        self,
        *,
        profile: PersonalModelRuntimeState,
        session: Episode,
        context: ContextBundle,
        prompt: str,
        model_role: str = "strong",
    ) -> ExecutionResult:
        del profile, context, model_role
        return ExecutionResult(
            execution_id=f"execution:{session.episode_id}",
            episode_id=session.episode_id,
            outcome="ok",
            summary=f"handled:{prompt}",
            prompt_tokens=3,
            completion_tokens=2,
            total_tokens=5,
        )


class _Telemetry:
    descriptor = CapabilityDescriptor("telemetry.test", "telemetry", "1")

    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, event: dict[str, object]) -> None:
        self.events.append(dict(event))


class KernelTurnLifecycleResetTest(unittest.TestCase):
    def test_replaying_same_checkpoint_step_updates_in_place_without_duplicate_sequence_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            lifecycle = install_app_episode_runtime(repository)
            episode = lifecycle.start_episode(
                PersonalModelRuntimeState(
                    profile_id="personal-model-reset",
                    display_name="Elephant Agent",
                    mode="companion",
                ),
                elephant_id="elephant-reset",
                episode_id="episode-reset",
            )
            loop_service = LoopCheckpointService()
            run = loop_service.start_loop(
                episode_id=episode.episode_id,
                source_event_id="event-replay",
                prompt="Continue the saved work.",
            )
            repository.upsert_loop_checkpoint(run)

            updated_run, first_step = loop_service.record_context_prompt(run, system_prompt="alpha prompt")
            repository.upsert_loop_checkpoint(updated_run)
            repository.append_loop_checkpoint_step(first_step)

            replayed_run, replayed_step = loop_service.record_context_prompt(run, system_prompt="beta prompt")
            repository.upsert_loop_checkpoint(replayed_run)
            repository.append_loop_checkpoint_step(replayed_step)

            persisted = repository.list_loop_checkpoint_steps(run.run_id)

        self.assertEqual(len(persisted), 1)
        self.assertEqual(persisted[0].step_id, first_step.step_id)
        self.assertEqual(persisted[0].content, "beta prompt")
        self.assertEqual(persisted[0].step_index, 1)

    def test_kernel_turn_uses_state_query_without_goal_graph_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            lifecycle = install_app_episode_runtime(repository)
            episode = lifecycle.start_episode(
                PersonalModelRuntimeState(
                    profile_id="personal-model-reset",
                    display_name="Elephant Agent",
                    mode="companion",
                ),
                elephant_id="elephant-reset",
                episode_id="episode-reset",
            )
            telemetry = _Telemetry()
            service = KernelService(
                KernelDependencies(
                    storage=repository,
                    context=_ContextCapability(),
                    recall=_RecallCapability(),
                    model_provider=_ModelProvider(),
                    telemetry=telemetry,
                )
            )

            outcome = service.run(
                KernelSourceRequest(
                    route_id=episode.episode_id,
                    prompt="What should we do next?",
                    surface="test",
                    route_profile_id=episode.personal_model_id,
                    route_status=episode.status,
                    route_started_at=episode.started_at,
                    state_query="Continue the reset implementation",
                )
            )

        self.assertIn("handled:What should we do next?", outcome.state.summary)
        self.assertIn("handled:What should we do next?", outcome.execution.summary)
        self.assertGreaterEqual(outcome.model_turn_count, 1)
        self.assertTrue(telemetry.events)

    def test_checkpoint_trigger_is_surfaced_on_enqueued_learning_job(self) -> None:
        """Reflection is moved off the hot path; the kernel only enqueues.

        The primary trigger classifier (``_primary_learning_trigger``)
        decides between ``episode_close`` / ``checkpoint`` /
        ``episode_failed`` based on the executed Loop. This test pins
        that a checkpoint Step in the recorded steps produces
        ``trigger="checkpoint"`` on the enqueued learning job, so the
        learning-worker's lighter triage path is chosen.
        """
        from packages.contracts.layers import Step
        from packages.contracts.runtime import ExecutionResult
        from packages.kernel.runtime_impl import _primary_learning_trigger

        now = datetime(2026, 4, 24, tzinfo=timezone.utc)
        execution = ExecutionResult(
            execution_id="exec-1",
            episode_id="ep-1",
            outcome="paused",
            summary="parked",
        )
        self.assertEqual(_primary_learning_trigger(execution=execution, steps=()), "checkpoint")

        execution_ok = ExecutionResult(
            execution_id="exec-2",
            episode_id="ep-1",
            outcome="ok",
            summary="done",
        )
        checkpoint_step = Step(
            step_id="step:cp",
            loop_id="loop-1",
            episode_id="ep-1",
            state_id="state-1",
            personal_model_id="pm-1",
            phase="acting",
            action="checkpoint",
            status="completed",
            sequence=0,
            created_at=now,
        )
        # A completed checkpoint step on an otherwise-ok loop -> checkpoint trigger.
        self.assertEqual(
            _primary_learning_trigger(execution=execution_ok, steps=(checkpoint_step,)),
            "checkpoint",
        )
        # Plain terminal outcome -> episode_close.
        self.assertEqual(
            _primary_learning_trigger(execution=execution_ok, steps=()),
            "episode_close",
        )
        # Failure outcome -> episode_failed.
        execution_fail = ExecutionResult(
            execution_id="exec-3",
            episode_id="ep-1",
            outcome="failed",
            summary="error",
        )
        self.assertEqual(
            _primary_learning_trigger(execution=execution_fail, steps=()),
            "episode_failed",
        )


if __name__ == "__main__":
    unittest.main()
