"""Integration test: reflection runs off the hot path (Phase 1).

After a Loop completes, the kernel must enqueue exactly one
``episode_boundary_learning`` job for the Episode and must not call
legacy in-turn reflection or skill-crystallization hooks
synchronously. The learning-worker process picks the job up separately
(``apps/learning_worker_runtime.py``).

Pins:

* the trigger on the enqueued job reflects the Loop outcome
  (episode_close / checkpoint / episode_failed);
* no synchronous reflection calls happen during ``run()``;
* idempotency — a second ``run()`` on the same episode does not
  create a duplicate queued job (INSERT OR REPLACE is keyed by
  ``(job_type, episode_id)``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from packages.contracts.runtime import (
    ContextBundle,
    ExecutionResult,
    PromptEnvelope,
)
from packages.kernel.runtime import (
    KernelDependencies,
    KernelService,
    KernelSourceRequest,
)
from packages.storage import RuntimeStorageRepository


@dataclass
class _TrackingRecallCapability:
    reflection_calls: int = 0
    crystallization_calls: int = 0

    def retrieve_evidence(self, _request):  # pragma: no cover - unused
        return SimpleNamespace(
            candidates=(),
            scope_episode_ids=(),
            scope_reason="",
            recall_reasons=SimpleNamespace(vector_cache_status=""),
        )

    def search(self, *args, **kwargs):  # pragma: no cover
        return ()

    def run_reflection_window(self, *_, **__):
        self.reflection_calls += 1
        return SimpleNamespace(window_record=SimpleNamespace(record_id="rw"), trigger="episode_close")

    def run_skill_crystallization(self, *_, **__):
        self.crystallization_calls += 1
        return None


class _ContextCapability:
    def assemble(self, session, work_items, recall_items, *, state_focus=None):
        envelope = PromptEnvelope(
            frozen_prefix="",
            session_snapshot="",
            loop_context="",
            messages=(),
        )
        return ContextBundle(
            bundle_id=f"bundle:{session.episode_id}",
            episode_id=session.episode_id,
            prompt_envelope=envelope,
            token_budget=1024,
            rendered_prompt="",
            artifact_ids=(),
        )

    def last_projection_compaction(self):
        return None

    def force_projection_compaction(self, *, reason: str = ""):
        return None

    def flush_projection_cache(self):
        pass


class _ModelProvider:
    def generate(self, *_, **__):
        return ExecutionResult(
            execution_id="exec-1",
            episode_id="ep-1",
            outcome="ok",
            summary="done",
        )


class _Telemetry:
    def emit(self, _event):
        pass


class ReflectionOffHotPathTest(unittest.TestCase):
    def test_run_enqueues_learning_job_without_calling_reflection_synchronously(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            recall = _TrackingRecallCapability()
            service = KernelService(
                KernelDependencies(
                    storage=repository,
                    context=_ContextCapability(),
                    recall=recall,
                    model_provider=_ModelProvider(),
                    telemetry=_Telemetry(),
                )
            )

            outcome = service.run(
                KernelSourceRequest(
                    route_id="ep-reflection-off",
                    prompt="what should I do next",
                    surface="test",
                    route_profile_id="pm-test",
                    route_status="active",
                    route_started_at=datetime(2026, 5, 3, tzinfo=timezone.utc),
                    state_query="long-horizon run",
                )
            )

            # Reflection must not have been called during run().
            self.assertEqual(recall.reflection_calls, 0)
            self.assertEqual(recall.crystallization_calls, 0)

            jobs = repository.list_learning_jobs(episode_id=outcome.episode.episode_id)
            self.assertEqual(len(jobs), 1, "exactly one learning job should be queued")
            job = jobs[0]
            self.assertEqual(job.job_type, "episode_boundary_learning")
            self.assertEqual(job.status, "queued")
            self.assertIn(job.trigger, {"episode_close", "checkpoint", "episode_failed"})

    def test_internal_learning_agent_turn_does_not_enqueue_recursive_learning_job(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            service = KernelService(
                KernelDependencies(
                    storage=repository,
                    context=_ContextCapability(),
                    recall=_TrackingRecallCapability(),
                    model_provider=_ModelProvider(),
                    telemetry=_Telemetry(),
                )
            )

            outcome = service.run(
                KernelSourceRequest(
                    route_id="ep-learning-agent",
                    prompt="[SYSTEM: Background Learning Agent] write learning result",
                    surface="learning.sub_agent",
                    source_event_type="turn.internal",
                    source_payload={"context_mode": "learning_agent"},
                    route_profile_id="pm-test",
                    route_status="active",
                    route_started_at=datetime(2026, 5, 3, tzinfo=timezone.utc),
                )
            )

            jobs = repository.list_learning_jobs(episode_id=outcome.episode.episode_id)
            self.assertEqual(jobs, ())

    def test_second_run_on_same_episode_does_not_duplicate_job(self) -> None:
        """INSERT OR REPLACE keyed by (job_type, episode_id) keeps the queue sane."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = RuntimeStorageRepository(Path(tmpdir) / "elephant.sqlite3")
            repository.bootstrap()
            service = KernelService(
                KernelDependencies(
                    storage=repository,
                    context=_ContextCapability(),
                    recall=_TrackingRecallCapability(),
                    model_provider=_ModelProvider(),
                    telemetry=_Telemetry(),
                )
            )

            for _ in range(3):
                outcome = service.run(
                    KernelSourceRequest(
                        route_id="ep-duplicate",
                        prompt="hello",
                        surface="test",
                        route_profile_id="pm-test",
                        route_status="active",
                        route_started_at=datetime(2026, 5, 3, tzinfo=timezone.utc),
                    )
                )

            jobs = repository.list_learning_jobs(episode_id=outcome.episode.episode_id)
            self.assertEqual(len(jobs), 1)


if __name__ == "__main__":
    unittest.main()
