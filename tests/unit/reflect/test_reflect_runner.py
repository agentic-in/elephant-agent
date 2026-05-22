from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from apps.reflect.runner import run_reflect_agent
from packages.contracts.runtime import LearningJob


def _learning_job(job_id: str) -> LearningJob:
    now = datetime.now(timezone.utc)
    return LearningJob(
        job_id=job_id,
        job_type="context_compaction",
        trigger="context_compaction",
        status="running",
        personal_model_id="pm",
        state_id="state",
        episode_id="episode",
        summary="synchronous context compression",
        progress_stage="agent_running",
        progress_detail="synchronous compress",
        attempt_count=1,
        max_attempts=1,
        available_at=now,
        created_at=now,
        started_at=now,
        worker_id="context-compress-sync",
        metadata={"features": "compress", "compressed_messages": "user: hello"},
    )


class MissingJobRepository:
    def load_episode(self, episode_id: str) -> SimpleNamespace:
        return SimpleNamespace(episode_id=episode_id)

    def list_personal_model_facts(self, **_: object) -> tuple[object, ...]:
        return ()

    def update_learning_job_progress(self, job_id: str, **_: object) -> None:
        raise KeyError(job_id)

    def write_learning_job_result(self, job_id: str, *_: object, **__: object) -> None:
        raise KeyError(job_id)


class RecordingRepository:
    def __init__(self) -> None:
        self.progress_updates: list[dict[str, object]] = []
        self.result_payload: dict[str, object] | None = None

    def load_episode(self, episode_id: str) -> SimpleNamespace:
        return SimpleNamespace(episode_id=episode_id)

    def list_personal_model_facts(self, **_: object) -> tuple[object, ...]:
        return ()

    def update_learning_job_progress(self, job_id: str, **kwargs: object) -> None:
        self.progress_updates.append({"job_id": job_id, **kwargs})

    def write_learning_job_result(self, _job_id: str, payload: dict[str, object], **_: object) -> None:
        self.result_payload = payload


class RecordingToolRuntime:
    def __init__(self) -> None:
        self.observers = []

    def subscribe(self, observer):
        self.observers.append(observer)

        def unsubscribe() -> None:
            if observer in self.observers:
                self.observers.remove(observer)

        return unsubscribe

    def emit(self, *, phase: str, tool_id: str, arguments: dict[str, object]) -> None:
        invocation = SimpleNamespace(tool_id=tool_id, arguments=arguments)
        event = SimpleNamespace(phase=phase, invocation=invocation)
        for observer in tuple(self.observers):
            observer(event)


class ReflectRunnerTest(unittest.TestCase):
    def test_unpersisted_reflect_invocation_can_return_summary_without_learning_job_row(self) -> None:
        runtime = SimpleNamespace(
            repository=MissingJobRepository(),
            run_sub_agent=lambda **_: {"summary": "Compressed summary", "status": "completed", "side_effects": ()},
        )

        result = run_reflect_agent(
            runtime,
            _learning_job("sync-compress:abc123"),
            explicit_features=("compress",),
            persist_result=False,
        )

        self.assertEqual(result.status, "no_op")
        self.assertEqual(result.summary, "Compressed summary")

    def test_missing_non_sync_job_still_raises(self) -> None:
        runtime = SimpleNamespace(
            repository=MissingJobRepository(),
            run_sub_agent=lambda **_: {"summary": "Summary", "status": "completed", "side_effects": ()},
        )

        with self.assertRaises(KeyError):
            run_reflect_agent(runtime, _learning_job("learning-job:missing"), explicit_features=("compress",))

    def test_reflect_runner_persists_structured_tool_event_progress(self) -> None:
        repository = RecordingRepository()
        tool_runtime = RecordingToolRuntime()

        def run_sub_agent(**_: object) -> dict[str, object]:
            tool_runtime.emit(
                phase="requested",
                tool_id="tool.personal_model.search",
                arguments={"query": "onboarding"},
            )
            tool_runtime.emit(
                phase="execution.started",
                tool_id="tool.personal_model.search",
                arguments={"query": "onboarding"},
            )
            tool_runtime.emit(
                phase="execution.completed",
                tool_id="tool.personal_model.search",
                arguments={"query": "onboarding"},
            )
            return {"summary": "Updated memory", "status": "completed", "side_effects": ()}

        runtime = SimpleNamespace(
            repository=repository,
            tool_runtime=tool_runtime,
            run_sub_agent=run_sub_agent,
        )

        result = run_reflect_agent(runtime, _learning_job("learning-job:tools"), explicit_features=("compress",))

        structured = [
            update
            for update in repository.progress_updates
            if str(update.get("progress_detail", "")).startswith("tool_event_v1=")
        ]
        self.assertEqual(result.tool_names, ("tool.personal_model.search",))
        self.assertTrue(structured)
        self.assertEqual(structured[-1]["progress_stage"], "tool_completed")
        detail = str(structured[-1]["progress_detail"])
        self.assertIn('"phase":"execution.completed"', detail)
        self.assertIn('"completed_tools":["tool.personal_model.search"]', detail)
        self.assertIn('"events":[', detail)


if __name__ == "__main__":
    unittest.main()
