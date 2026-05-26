from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from apps.api.api_runtime_episode_queries import repository_episodes
from apps.api.api_runtime_internal_methods import _dashboard_step_row
from apps.api.api_runtime_internal_sections import (
    _dashboard_question_config,
    _fill_diary,
    _fill_questions,
    _fill_reflect,
    _fill_states,
    _latest_episode_row,
    _personal_model_facts,
    _provider_catalog_rows,
    _state_projection_rows,
)
from apps.api.api_runtime_trace_queries import steps_by_loop_for_episodes
from packages.contracts.layers import Episode, Step
from packages.contracts.runtime import LearningJob


class InternalDashboardStepRowsTest(unittest.TestCase):
    def test_dashboard_trace_steps_are_loaded_once_per_episode_when_supported(self) -> None:
        class Repository:
            def __init__(self) -> None:
                self.step_calls: list[dict[str, object]] = []

            def list_steps(self, **kwargs: object) -> tuple[Step, ...]:
                self.step_calls.append(dict(kwargs))
                if "loop_id" in kwargs:
                    raise AssertionError(f"unexpected per-loop step query: {kwargs!r}")
                return (
                    _step("step:2", "loop:2", 1),
                    _step("step:1", "loop:1", 1),
                )

        repository = Repository()
        episode = _episode("episode:new", "2026-05-02T00:00:00+00:00")
        loops = (
            SimpleNamespace(loop_id="loop:1", episode_id=episode.episode_id),
            SimpleNamespace(loop_id="loop:2", episode_id=episode.episode_id),
        )

        steps_by_loop = steps_by_loop_for_episodes(repository, episodes=(episode,), loops=loops)

        self.assertEqual(tuple(step.step_id for step in steps_by_loop["loop:1"]), ("step:1",))
        self.assertEqual(tuple(step.step_id for step in steps_by_loop["loop:2"]), ("step:2",))
        self.assertEqual(repository.step_calls, [{"episode_id": "episode:new"}])

    def test_latest_episode_row_uses_bounded_newest_first_repository_query(self) -> None:
        class Repository:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            def list_episodes(self, **kwargs: object) -> tuple[Episode, ...]:
                self.calls.append(dict(kwargs))
                return (
                    _episode("episode:new", "2026-05-02T00:00:00+00:00"),
                    _episode("episode:old", "2026-05-01T00:00:00+00:00"),
                )

        repository = Repository()

        rows = _latest_episode_row(SimpleNamespace(repository=repository), limit=2)

        self.assertEqual(repository.calls, [{"limit": 2, "newest_first": True}])
        self.assertEqual(tuple(row["episode_id"] for row in rows), ("episode:new", "episode:old"))

    def test_repository_episodes_falls_back_for_older_test_doubles(self) -> None:
        class Repository:
            def list_episodes(self) -> tuple[Episode, ...]:
                return (
                    _episode("episode:old", "2026-05-01T00:00:00+00:00"),
                    _episode("episode:new", "2026-05-02T00:00:00+00:00"),
                )

        episodes = repository_episodes(Repository(), limit=1, newest_first=True)

        self.assertEqual(tuple(episode.episode_id for episode in episodes), ("episode:new",))

    def test_reflect_section_loads_only_learning_job_episodes(self) -> None:
        class Repository:
            def __init__(self, database_path: Path) -> None:
                self.database_path = database_path
                self.loaded_episode_ids: list[str] = []

            def list_states(self) -> tuple[object, ...]:
                return (
                    SimpleNamespace(
                        state_id="state:test",
                        elephant_id="elephant:test",
                        elephant_name="Test",
                        updated_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
                    ),
                )

            def current_state(self) -> object | None:
                return None

            def list_episodes(self) -> tuple[Episode, ...]:
                raise AssertionError("reflect should not scan all episodes")

            def list_learning_jobs(self, *, limit: int) -> tuple[LearningJob, ...]:
                if limit != 500:
                    raise AssertionError(limit)
                return (
                    LearningJob(
                        job_id="job:1",
                        job_type="reflection",
                        trigger="episode_exit",
                        status="completed",
                        personal_model_id="you",
                        state_id="state:test",
                        episode_id="episode:new",
                    ),
                )

            def load_episode(self, episode_id: str) -> Episode:
                self.loaded_episode_ids.append(episode_id)
                return _episode(episode_id, "2026-05-02T00:00:00+00:00")

        with tempfile.TemporaryDirectory() as tmpdir:
            repository = Repository(Path(tmpdir) / "state" / "elephant.sqlite3")
            dashboard: dict[str, object] = {}

            _fill_reflect(dashboard, SimpleNamespace(repository=repository))

        self.assertEqual(repository.loaded_episode_ids, ["episode:new"])
        self.assertEqual(dashboard["learning"]["jobs"][0]["entry_surface"], "cli")

    def test_tool_execute_detail_includes_exact_tool_result(self) -> None:
        step = Step(
            step_id="step:tool",
            loop_id="loop:test",
            episode_id="episode:test",
            state_id="state:test",
            personal_model_id="you",
            phase="acting",
            action="call_tool",
            status="completed",
            sequence=1,
            created_at=datetime.now(timezone.utc),
            summary="tool.diary.list description should not be the result",
            metadata={
                "tool_name": "tool.diary.list",
                "tool_arguments": '{"limit":5}',
                "tool_result": '{"entries":[],"count":0}',
                "execution_id": "exec:tool",
            },
        )

        row = _dashboard_step_row(step, {})

        self.assertEqual(row["event_type"], "tool_execute")
        self.assertEqual(row["content"], '{"entries":[],"count":0}')
        self.assertEqual(row["detail"]["tool_name"], "tool.diary.list")
        self.assertEqual(row["detail"]["tool_arguments"], '{"limit":5}')
        self.assertEqual(row["detail"]["tool_result"], '{"entries":[],"count":0}')

    def test_dashboard_projection_logs_runtime_lookup_fallback(self) -> None:
        class Repository:
            def list_local_agent_runtimes(self) -> tuple[object, ...]:
                raise RuntimeError("runtime table unavailable")

        with self.assertLogs("apps.api.api_runtime_internal_sections", level="DEBUG") as logs:
            elephant_rows, state_rows = _state_projection_rows(
                (),
                current_state=None,
                install_root=None,
                repository=Repository(),
            )

        self.assertEqual(elephant_rows, [])
        self.assertEqual(state_rows, [])
        self.assertIn("Failed to load local agent runtimes for dashboard state projection", "\n".join(logs.output))

    def test_personal_model_fact_lookup_logs_failure_and_returns_empty(self) -> None:
        class Repository:
            def list_personal_model_facts(self, **_: object) -> tuple[object, ...]:
                raise RuntimeError("facts unavailable")

        with self.assertLogs("apps.api.api_runtime_internal_sections", level="DEBUG") as logs:
            facts = _personal_model_facts(Repository(), "you", "active")

        self.assertEqual(facts, ())
        self.assertIn("Failed to load Personal Model facts for dashboard projection", "\n".join(logs.output))

    def test_provider_catalog_logs_discovered_state_failure(self) -> None:
        class Record:
            def as_mapping(self) -> dict[str, str]:
                return {"provider_id": "missing-provider"}

        class RuntimeResolver:
            def list_catalog(self) -> tuple[Record, ...]:
                return (Record(),)

        class ModelProvider:
            runtime_resolver = RuntimeResolver()

            def discovered_provider_state(self, provider_id: str) -> object:
                del provider_id
                raise RuntimeError("provider discovery unavailable")

        with self.assertLogs("apps.api.api_runtime_internal_sections", level="DEBUG") as logs:
            rows = _provider_catalog_rows(SimpleNamespace(model_provider=ModelProvider()), {})

        self.assertEqual(rows[0]["provider_id"], "missing-provider")
        self.assertIn("Failed to load discovered provider state for dashboard models section", "\n".join(logs.output))

    def test_fill_states_logs_local_runtime_fallback(self) -> None:
        class Repository:
            def list_states(self) -> tuple[object, ...]:
                return ()

            def current_state(self) -> None:
                return None

            def list_local_agent_runtimes(self) -> tuple[object, ...]:
                raise RuntimeError("runtime table unavailable")

        dashboard: dict[str, object] = {}
        api = SimpleNamespace(repository=Repository(), config=SimpleNamespace(install_root=None))

        with self.assertLogs("apps.api.api_runtime_internal_sections", level="DEBUG") as logs:
            states, current_state = _fill_states(dashboard, api)

        self.assertEqual(states, ())
        self.assertIsNone(current_state)
        self.assertEqual(dashboard["local_agent_runtimes"], ())
        self.assertIn("Failed to load local agent runtimes for dashboard overview section", "\n".join(logs.output))

    def test_fill_questions_logs_best_effort_failures(self) -> None:
        class Repository:
            @property
            def database_path(self) -> Path:
                raise RuntimeError("config path unavailable")

            def ensure_default_personal_model(self, **_: object) -> None:
                raise RuntimeError("personal model unavailable")

            def list_personal_model_facts(self, **_: object) -> tuple[object, ...]:
                raise RuntimeError("facts unavailable")

            def list_open_questions(self, **_: object) -> tuple[object, ...]:
                raise RuntimeError("questions unavailable")

        dashboard: dict[str, object] = {}

        with self.assertLogs("apps.api.api_runtime_internal_sections", level="DEBUG") as logs:
            _fill_questions(dashboard, SimpleNamespace(repository=Repository()))

        rendered_logs = "\n".join(logs.output)
        self.assertEqual(dashboard["questions"]["facts"], ())
        self.assertIn("Failed to ensure default Personal Model for dashboard questions section", rendered_logs)
        self.assertIn("Failed to load active facts for dashboard questions section", rendered_logs)
        self.assertIn("Failed to load open questions for dashboard questions section", rendered_logs)
        self.assertIn("Failed to load asked questions for dashboard questions section", rendered_logs)
        self.assertIn("Failed to load answered questions for dashboard questions section", rendered_logs)
        self.assertIn("Failed to load dismissed questions for dashboard questions section", rendered_logs)
        self.assertIn("Failed to load dashboard question config", rendered_logs)

    def test_question_config_logs_failure_and_returns_empty(self) -> None:
        class Repository:
            @property
            def database_path(self) -> Path:
                raise RuntimeError("config path unavailable")

        with self.assertLogs("apps.api.api_runtime_internal_sections", level="DEBUG") as logs:
            config = _dashboard_question_config(Repository())

        self.assertEqual(config, {})
        self.assertIn("Failed to load dashboard question config", "\n".join(logs.output))

    def test_fill_diary_logs_lookup_failure(self) -> None:
        class Repository:
            def ensure_default_personal_model(self) -> object:
                raise RuntimeError("personal model unavailable")

        dashboard: dict[str, object] = {}

        with self.assertLogs("apps.api.api_runtime_internal_sections", level="DEBUG") as logs:
            _fill_diary(dashboard, SimpleNamespace(repository=Repository()))

        self.assertEqual(dashboard["diary"]["entries"], ())
        self.assertIn("Failed to load diary entries for dashboard section", "\n".join(logs.output))


def _episode(episode_id: str, started_at: str) -> Episode:
    return Episode(
        episode_id=episode_id,
        state_id="state:test",
        personal_model_id="you",
        entry_surface="cli",
        status="closed",
        started_at=datetime.fromisoformat(started_at),
    )


def _step(step_id: str, loop_id: str, sequence: int) -> Step:
    return Step(
        step_id=step_id,
        loop_id=loop_id,
        episode_id="episode:new",
        state_id="state:test",
        personal_model_id="you",
        phase="acting",
        action="call_tool",
        status="completed",
        sequence=sequence,
        created_at=datetime(2026, 5, 2, tzinfo=timezone.utc),
        metadata={"tool_name": "tool.test"},
    )
    def test_tool_execute_detail_truncates_large_dashboard_payloads(self) -> None:
        large_arguments = '{"command":"' + ('x' * 5_200) + '"}'
        large_result = 'y' * 9_200
        step = Step(
            step_id="step:tool-large",
            loop_id="loop:test",
            episode_id="episode:test",
            state_id="state:test",
            personal_model_id="you",
            phase="acting",
            action="call_tool",
            status="completed",
            sequence=2,
            created_at=datetime.now(timezone.utc),
            summary="large tool result",
            metadata={
                "tool_name": "tool.terminal.exec",
                "tool_arguments": large_arguments,
                "tool_result": large_result,
                "execution_id": "exec:tool-large",
            },
        )

        row = _dashboard_step_row(step, {})

        self.assertIn("[truncated ", row["content"])
        self.assertIn("[truncated ", row["detail"]["tool_arguments"])
        self.assertIn("[truncated ", row["detail"]["tool_result"])
        self.assertLess(len(row["detail"]["tool_arguments"]), len(large_arguments))
        self.assertLess(len(row["detail"]["tool_result"]), len(large_result))

    def test_tool_execute_detail_includes_sandbox_trace_metadata(self) -> None:
        step = Step(
            step_id="step:sandbox",
            loop_id="loop:test",
            episode_id="episode:test",
            state_id="state:test",
            personal_model_id="you",
            phase="acting",
            action="call_tool",
            status="completed",
            sequence=2,
            created_at=datetime.now(timezone.utc),
            summary="sandbox write complete",
            metadata={
                "tool_name": "tool.file.write",
                "tool_arguments": '{"path":"demo.py"}',
                "tool_result": "path: /home/user/demo.py",
                "execution_id": "exec:sandbox",
                "sandbox_backend": "cloud",
                "sandbox_provider": "tencent",
                "sandbox_backend_class": "TencentCloudBackend",
                "sandbox_id": "sbx-123",
                "sandbox_resolution": "reuse",
                "sandbox_cwd": "/home/user",
                "sandbox_template": "code-interpreter-v1",
                "sandbox_timeout_seconds": "3600",
                "sandbox_cached_session": "true",
            },
        )

        row = _dashboard_step_row(step, {})

        self.assertEqual(row["detail"]["sandbox_backend"], "cloud")
        self.assertEqual(row["detail"]["sandbox_provider"], "tencent")
        self.assertEqual(row["detail"]["sandbox_backend_class"], "TencentCloudBackend")
        self.assertEqual(row["detail"]["sandbox_id"], "sbx-123")
        self.assertEqual(row["detail"]["sandbox_resolution"], "reuse")
        self.assertEqual(row["detail"]["sandbox_cwd"], "/home/user")
        self.assertEqual(row["detail"]["sandbox_template"], "code-interpreter-v1")
        self.assertEqual(row["detail"]["sandbox_timeout_seconds"], "3600")
        self.assertEqual(row["detail"]["sandbox_cached_session"], "true")


if __name__ == "__main__":
    unittest.main()
