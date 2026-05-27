from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import tempfile
from threading import Lock
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from apps.api import api_runtime_http_io_methods
from apps.api import api_runtime_impl
from apps.api.api_runtime_http_io_methods import __call__ as wsgi_call
from apps.api.api_runtime_http_io_methods import run_cron_job_now
from apps.api.api_runtime_context_compression import (
    compact_context_after_usage,
    _reflect_runtime,
)
from apps.api.api_runtime_cron_ops import run_proactive_ask_now
from apps.api.api_runtime_episode_queries import repository_episodes
from apps.api.api_runtime_http_methods import (
    _dispatch_elephants,
    _dispatch_internal,
    _dispatch_operator,
    stream_loop_events,
)
from apps.api.api_runtime_paths import _dispatch_paths
from apps.api.api_runtime_routes import API_HEALTH_ROUTE, API_V1_ROUTE_FAMILY_PATHS
from apps.api.capabilities import APITelemetrySink
from packages.context.epoch_store import FileEpochStore
from packages.context.session_projection import SessionContextEpoch
from packages.contracts import OpenQuestion
from packages.contracts.runtime import PromptMessage
from packages.operator.local_agents import LocalAgentRuntimeRecord
from packages.storage import RuntimeStorageRepository
from packages.tools.runtime import ToolInvocation, ToolLifecycleEvent, ToolRuntimeContext


def _diary_job() -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        job_id="cron:diary",
        name="Daily diary",
        schedule_text="0 2 * * *",
        schedule_kind="cron",
        action_kind="learning",
        status="scheduled",
        profile_id=None,
        elephant_id=None,
        payload={"trigger": "diary"},
        created_at=now,
        updated_at=now,
        next_run_at=now,
        last_run_at=None,
        run_count=0,
        last_summary="",
    )


def _dream_job() -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        job_id="cron:dream",
        name="Nightly dream",
        schedule_text="0 1 * * *",
        schedule_kind="cron",
        action_kind="learning",
        status="scheduled",
        profile_id=None,
        elephant_id=None,
        payload={"trigger": "dream"},
        created_at=now,
        updated_at=now,
        next_run_at=now,
        last_run_at=None,
        run_count=0,
        last_summary="",
    )


def _prompt_job() -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        job_id="cron:prompt",
        name="Prompt",
        schedule_text="0 1 * * *",
        schedule_kind="cron",
        action_kind="prompt",
        status="scheduled",
        profile_id=None,
        elephant_id=None,
        payload={"prompt": "hello"},
        created_at=now,
        updated_at=now,
        next_run_at=now,
        last_run_at=now,
        run_count=1,
        last_summary="hello from cron",
    )


class _CronRuntimeStub:
    def __init__(self, job: SimpleNamespace | None = None) -> None:
        self.job = job
        self.removed_job_id: str | None = None

    def inspect_job(self, job_id: str) -> SimpleNamespace:
        if self.job is None or self.job.job_id != job_id:
            raise KeyError(job_id)
        return self.job

    def remove_job(self, job_id: str) -> SimpleNamespace:
        self.removed_job_id = job_id
        if self.job is None:
            raise KeyError(job_id)
        return self.job


def _herd_app(root: Path) -> SimpleNamespace:
    repository = RuntimeStorageRepository(root / "state" / "elephant.sqlite3")
    repository.bootstrap()
    return SimpleNamespace(
        repository=repository,
        config=SimpleNamespace(install_root=root / "install"),
    )


def _local_runtime(
    *,
    runtime_id: str,
    provider_id: str = "codex",
    can_execute: bool = True,
) -> LocalAgentRuntimeRecord:
    return LocalAgentRuntimeRecord(
        runtime_id=runtime_id,
        provider_id=provider_id,
        command=provider_id,
        display_name="Codex" if provider_id == "codex" else provider_id,
        resolved_path=f"/tmp/{provider_id}",
        version=f"{provider_id} 1",
        status="detected",
        auth_status="configured",
        source="env",
        default_model="",
        can_execute=can_execute,
        role_title="coding implementer",
        role_prompt="Run focused coding work.",
        detected_at="2026-05-23T00:00:00+00:00",
        metadata={"adapter": "argv_prompt" if can_execute else ""},
    )


class APIRouteInventoryTest(unittest.TestCase):
    def test_declared_api_route_families_cover_dispatch_surface(self) -> None:
        self.assertEqual(API_HEALTH_ROUTE, "/healthz")
        self.assertEqual(
            API_V1_ROUTE_FAMILY_PATHS,
            (
                "/v1/providers",
                "/v1/internal",
                "/v1/operator",
                "/v1/herd",
                "/v1/paths",
                "/v1/episodes",
                "/v1/states",
            ),
        )


class APIBestEffortObservabilityTest(unittest.TestCase):
    def test_repository_episode_query_logs_direct_failure(self) -> None:
        repository = SimpleNamespace(
            list_episodes=mock.Mock(side_effect=RuntimeError("episode query failed")),
        )

        with self.assertLogs("apps.api.api_runtime_episode_queries", level="DEBUG") as captured:
            episodes = repository_episodes(repository)

        self.assertEqual(episodes, ())
        rendered_logs = "\n".join(captured.output)
        self.assertIn("Repository episode query failed", rendered_logs)
        self.assertIn("episode query failed", rendered_logs)

    def test_repository_episode_query_logs_fallback_failure(self) -> None:
        calls = {"count": 0}

        def list_episodes(**_kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise TypeError("legacy signature")
            raise RuntimeError("fallback failed")

        repository = SimpleNamespace(list_episodes=list_episodes)

        with self.assertLogs("apps.api.api_runtime_episode_queries", level="DEBUG") as captured:
            episodes = repository_episodes(repository, state_id="state:1")

        self.assertEqual(episodes, ())
        rendered_logs = "\n".join(captured.output)
        self.assertIn("Fallback repository episode query failed", rendered_logs)
        self.assertIn("fallback failed", rendered_logs)

    def test_persist_proactive_ask_config_logs_failure(self) -> None:
        with (
            mock.patch(
                "packages.runtime_config.global_config_path_for_state_dir",
                side_effect=RuntimeError("config path unavailable"),
            ),
            self.assertLogs("apps.api.api_runtime_http_io_methods", level="DEBUG") as captured,
        ):
            api_runtime_http_io_methods._persist_proactive_ask_config(
                Path("/tmp/elephant-state"),
                {"enabled": True},
            )

        rendered_logs = "\n".join(captured.output)
        self.assertIn("Failed to persist proactive ask config", rendered_logs)
        self.assertIn("config path unavailable", rendered_logs)

    def test_steady_embedding_runtime_logs_failure(self) -> None:
        embedding_service = SimpleNamespace(
            steady_async=mock.Mock(side_effect=RuntimeError("steady failed")),
        )

        with self.assertLogs("apps.api.api_runtime_impl", level="DEBUG") as captured:
            api_runtime_impl._steady_embedding_runtime(embedding_service)

        rendered_logs = "\n".join(captured.output)
        self.assertIn("steady_async() failed", rendered_logs)
        self.assertIn("steady failed", rendered_logs)

    def test_ensure_system_cron_jobs_logs_failure(self) -> None:
        with (
            mock.patch.object(
                api_runtime_impl,
                "ensure_nightly_learning_crons",
                side_effect=RuntimeError("cron bootstrap failed"),
            ),
            self.assertLogs("apps.api.api_runtime_impl", level="WARNING") as captured,
        ):
            api_runtime_impl._ensure_system_cron_jobs(SimpleNamespace())

        rendered_logs = "\n".join(captured.output)
        self.assertIn("Failed to ensure built-in system cron jobs", rendered_logs)
        self.assertIn("cron bootstrap failed", rendered_logs)


class HerdDiscoveryAPITest(unittest.TestCase):
    def test_discovery_scan_persists_local_agent_runtimes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = _herd_app(Path(tmpdir))
            record = _local_runtime(runtime_id="local-agent:codex:test")

            with mock.patch("apps.api.api_runtime_herd_local_agents.scan_local_agents", return_value=(record,)):
                response = _dispatch_elephants(app, "POST", ("discovery", "scan"), b"{}")

            persisted = app.repository.load_local_agent_runtime(record.runtime_id)

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(persisted)
        assert persisted is not None
        self.assertEqual(persisted.provider_id, "codex")
        self.assertTrue(response.payload["local_agent_runtimes"][0]["can_execute"])

    def test_adopt_creates_baby_elephant_with_runtime_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = _herd_app(Path(tmpdir))
            app.repository.create_state(
                personal_model_id="you",
                elephant_id="mother-elephant",
                state_id="state:mother-elephant",
                elephant_name="Mother Elephant",
                metadata={"herd_kind": "mother"},
            )
            record = _local_runtime(runtime_id="local-agent:codex:test")
            app.repository.upsert_local_agent_runtime(record)

            response = _dispatch_elephants(
                app,
                "POST",
                ("babies",),
                json.dumps(
                    {
                        "runtime_id": record.runtime_id,
                        "elephant_id": "codex-baby",
                        "display_name": "Codex Baby",
                        "role_title": "implementation runner",
                        "role_prompt": "Run focused implementation checks.",
                        "enabled": True,
                    }
                ).encode("utf-8"),
            )
            state = app.repository.load_state("state:codex-baby")

        self.assertEqual(response.status_code, 201)
        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state.elephant_name, "Codex Baby")
        self.assertEqual(state.personal_model_id, "you")
        self.assertEqual(state.metadata["herd_kind"], "baby")
        self.assertEqual(state.metadata["parent_elephant_id"], "mother-elephant")
        self.assertEqual(state.metadata["runtime_id"], record.runtime_id)
        self.assertEqual(state.metadata["provider_id"], "codex")
        self.assertEqual(state.metadata["role_title"], "implementation runner")
        self.assertEqual(state.metadata["enabled"], "true")

    def test_adopt_rejects_discovered_runtime_without_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = _herd_app(Path(tmpdir))
            record = _local_runtime(
                runtime_id="local-agent:cursor:test",
                provider_id="cursor-agent",
                can_execute=False,
            )
            app.repository.upsert_local_agent_runtime(record)

            with self.assertRaisesRegex(ValueError, "not executable"):
                _dispatch_elephants(
                    app,
                    "POST",
                    ("babies",),
                    json.dumps({"runtime_id": record.runtime_id}).encode("utf-8"),
                )


class PathsAPITest(unittest.TestCase):
    def test_creates_moves_and_checks_learning_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = _herd_app(Path(tmpdir))

            create_path = _dispatch_paths(
                app,
                "POST",
                (),
                json.dumps(
                    {
                        "title": "Healthy rhythm",
                        "description": "Build a durable sleep and gym routine.",
                        "review_mode": "trusted",
                        "steps": [
                            {
                                "title": "Draft first week plan",
                                "status": "next",
                                "assignee_elephant_id": "baby:coach",
                            }
                        ],
                    }
                ).encode("utf-8"),
            )
            path_payload = create_path.payload["path"]
            path_id = path_payload["path_id"]
            first_step_id = path_payload["steps"][0]["path_step_id"]

            moved = _dispatch_paths(
                app,
                "PATCH",
                (path_id, "steps", first_step_id),
                json.dumps({"status": "moving", "order_index": 0}).encode("utf-8"),
            )
            summary = _dispatch_paths(
                app,
                "POST",
                (path_id, "steps", first_step_id, "learning-summary"),
                json.dumps(
                    {
                        "what_done": "Created a one-week plan.",
                        "why_it_matters": "Turns intent into a small repeatable loop.",
                        "how_it_was_done": "Split bedtime and gym into checkable steps.",
                        "knowledge": "Habit loops need triggers and recovery space.",
                        "human_takeaway": "Start small and inspect the loop.",
                    }
                ).encode("utf-8"),
            )
            summary_id = summary.payload["summary"]["summary_id"]
            checked = _dispatch_paths(
                app,
                "POST",
                (path_id, "steps", first_step_id, "understanding-check"),
                json.dumps({"summary_id": summary_id, "understood": True}).encode("utf-8"),
            )
            dashboard = _dispatch_paths(app, "GET", (), b"{}")

        self.assertEqual(create_path.status_code, 201)
        self.assertEqual(moved.payload["step"]["status"], "moving")
        self.assertEqual(summary.payload["summary"]["understanding_check"]["status"], "pending")
        self.assertEqual(checked.payload["check"]["status"], "understood")
        self.assertEqual(dashboard.payload["paths"]["counts"]["paths"], 1)
        self.assertEqual(dashboard.payload["paths"]["counts"]["steps"], 1)
        self.assertEqual(dashboard.payload["paths"]["counts"]["understanding_pending"], 0)


class OperatorPersonalModelQuestionDispatchTest(unittest.TestCase):
    def test_answer_question_marks_answered_and_enqueues_question_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = _herd_app(Path(tmpdir))
            state = app.repository.create_state(
                personal_model_id="you",
                elephant_id="mother-elephant",
                state_id="state:mother-elephant",
                elephant_name="Mother Elephant",
            )
            app.repository.upsert_open_question(
                OpenQuestion(
                    question_id="oq:test",
                    personal_model_id=state.personal_model_id,
                    lens="world",
                    sub_lens="projects_priority",
                    text="Which project should I prioritize?",
                    rationale="Need user answer to prioritize help.",
                    priority=0.9,
                    sensitivity="low",
                    source="contextual",
                    created_at=datetime.now(timezone.utc),
                )
            )
            reflect_calls: list[dict[str, object]] = []

            def trigger_reflect_job(**kwargs: object) -> dict[str, object]:
                reflect_calls.append(dict(kwargs))
                return {"status": "queued", "job_id": "job:questions", "features": kwargs.get("features", "")}

            app.trigger_reflect_job = trigger_reflect_job
            response = _dispatch_operator(
                app,
                "POST",
                ("personal-model", "questions", "oq:test", "answer"),
                json.dumps(
                    {
                        "personal_model_id": state.personal_model_id,
                        "episode_id": "episode:question-answer",
                        "content": "Prioritize Semantic Router this week.",
                    }
                ).encode("utf-8"),
            )
            answered = app.repository.list_open_questions(
                personal_model_id=state.personal_model_id,
                status="answered",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(answered), 1)
        self.assertEqual(answered[0].question_id, "oq:test")
        self.assertEqual(answered[0].user_response_episode_ids, ("episode:question-answer",))
        self.assertEqual(reflect_calls, [{"trigger": "question_answer", "features": "questions"}])
        self.assertEqual(response.payload["reflect"]["job_id"], "job:questions")


class OperatorCronDispatchTest(unittest.TestCase):
    def test_rejects_delete_for_proactive_system_job(self) -> None:
        app = SimpleNamespace()

        response = _dispatch_operator(app, "DELETE", ("cron", "system:proactive-ask"), None)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.payload["error"], "system_cron_jobs_cannot_be_deleted")

    def test_allows_delete_for_diary_learning_job(self) -> None:
        cron_runtime = _CronRuntimeStub(job=_diary_job())
        app = SimpleNamespace(cron_runtime=cron_runtime)

        response = _dispatch_operator(app, "DELETE", ("cron", "cron:diary"), None)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.payload["cron"]["status"], "removed")
        self.assertEqual(cron_runtime.removed_job_id, "cron:diary")

    def test_rejects_delete_for_nightly_dream_system_job(self) -> None:
        cron_runtime = _CronRuntimeStub(job=_dream_job())
        app = SimpleNamespace(cron_runtime=cron_runtime)

        response = _dispatch_operator(app, "DELETE", ("cron", "cron:dream"), None)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.payload["error"], "system_cron_jobs_cannot_be_deleted")
        self.assertIsNone(cron_runtime.removed_job_id)

    def test_manual_run_for_proactive_system_job_uses_special_handler(self) -> None:
        calls: list[str] = []

        def run_proactive_ask_now() -> dict[str, object]:
            calls.append("run")
            return {"cron": {"run": {"outcome": "success"}}}

        app = SimpleNamespace(run_proactive_ask_now=run_proactive_ask_now)

        response = _dispatch_operator(app, "POST", ("cron", "system:proactive-ask", "run"), b"{}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, ["run"])
        self.assertEqual(response.payload["cron"]["run"]["outcome"], "success")

    def test_manual_run_uses_gateway_runtime_bridge_for_delivery(self) -> None:
        job = _prompt_job()
        execution = SimpleNamespace(
            job=job,
            outcome="success",
            summary="hello from cron",
            recorded_at=datetime.now(timezone.utc),
        )
        delivered: list[tuple[object, object]] = []
        runs: list[str] = []

        class _Bridge:
            def run_cron_job_now(self, *, cli_state_dir: Path, job_id: str):
                runs.append(job_id)
                return execution

            def build_cron_delivery_callback(self, **_kwargs):
                return lambda delivered_job, delivered_execution: delivered.append(
                    (delivered_job, delivered_execution)
                )

        with tempfile.TemporaryDirectory() as tmpdir:
            app = SimpleNamespace(
                repository=SimpleNamespace(database_path=Path(tmpdir) / "elephant.sqlite3"),
                gateway_runtime_bridge=_Bridge(),
            )
            payload = run_cron_job_now(app, "cron:prompt")

        self.assertEqual(runs, ["cron:prompt"])
        self.assertEqual(delivered, [(job, execution)])
        self.assertTrue(payload["cron"]["run"]["delivered"])

    def test_manual_run_reports_missing_cron_runtime_bridge(self) -> None:
        cron_runtime = _CronRuntimeStub(job=_prompt_job())
        with tempfile.TemporaryDirectory() as tmpdir:
            app = SimpleNamespace(
                repository=SimpleNamespace(database_path=Path(tmpdir) / "elephant.sqlite3"),
                cron_runtime=cron_runtime,
                gateway_runtime_bridge=None,
            )
            payload = run_cron_job_now(app, "cron:prompt")

        self.assertEqual(payload["cron"]["run"]["outcome"], "unavailable")
        self.assertEqual(payload["cron"]["run"]["delivery_error"], "cron runtime bridge unavailable")

    def test_proactive_ask_run_uses_gateway_runtime_bridge(self) -> None:
        calls: list[dict[str, object]] = []

        class _Bridge:
            def run_proactive_ask_once(self, **kwargs):
                calls.append(kwargs)
                return {
                    "scanned": 2,
                    "eligible": 1,
                    "enqueued": 1,
                    "skipped_no_questions": 0,
                    "skipped_pending": 0,
                    "skipped_policy": 1,
                    "skipped_unbound": 0,
                }

        with tempfile.TemporaryDirectory() as tmpdir:
            app = SimpleNamespace(
                repository=SimpleNamespace(database_path=Path(tmpdir) / "elephant.sqlite3"),
                gateway_runtime_bridge=_Bridge(),
            )
            payload = run_proactive_ask_now(app)

        self.assertEqual(len(calls), 1)
        self.assertEqual(payload["cron"]["run"]["outcome"], "success")
        self.assertTrue(payload["cron"]["run"]["delivered"])
        self.assertIn("enqueued=1", payload["cron"]["run"]["summary"])

    def test_proactive_ask_run_reports_missing_gateway_runtime_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = SimpleNamespace(
                repository=SimpleNamespace(database_path=Path(tmpdir) / "elephant.sqlite3"),
                gateway_runtime_bridge=None,
            )
            payload = run_proactive_ask_now(app)

        self.assertEqual(payload["cron"]["run"]["outcome"], "unavailable")
        self.assertEqual(payload["cron"]["run"]["delivery_error"], "gateway runtime bridge unavailable")


class APIContextCompressionTest(unittest.TestCase):
    def test_reflect_runtime_uses_runtime_bridge_when_api_has_no_sub_agent_runner(self) -> None:
        runtime = object()

        class _Bridge:
            def reflect_context_runtime(self, *, state_dir: Path):
                self.state_dir = state_dir
                return runtime

        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            bridge = _Bridge()
            app = SimpleNamespace(
                repository=SimpleNamespace(database_path=state_dir / "elephant.sqlite3"),
                gateway_runtime_bridge=bridge,
            )

            resolved = _reflect_runtime(app)

        self.assertIs(resolved, runtime)
        self.assertEqual(bridge.state_dir, state_dir)

    def test_after_turn_high_usage_compacts_epoch_like_chat_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            store = FileEpochStore(state_dir)
            episode_id = "episode-api-compress"
            store.save(
                SessionContextEpoch(
                    session_id=episode_id,
                    frozen=True,
                    frozen_prefix="## Stable prefix",
                    base_loop_context="",
                    thread_focus="High usage API chat",
                    history_messages=tuple(
                        PromptMessage(
                            role="user" if index % 2 == 0 else "assistant",
                            content=f"message {index} " + ("payload " * 200),
                        )
                        for index in range(18)
                    ),
                )
            )
            telemetry = APITelemetrySink()
            app = SimpleNamespace(
                repository=SimpleNamespace(
                    database_path=state_dir / "elephant.sqlite3"
                ),
                telemetry=telemetry,
                context=SimpleNamespace(runtime=SimpleNamespace(total_tokens=1000)),
            )
            outcome = SimpleNamespace(
                execution=SimpleNamespace(prompt_tokens=900, total_tokens=900),
                context=SimpleNamespace(token_budget=1000),
                event=SimpleNamespace(event_id="event:api-compress"),
                stages=(),
            )

            with mock.patch(
                "apps.api.api_runtime_context_compression._run_reflect_context_compressor",
                return_value="reflect summary",
            ) as reflect_compressor:
                compact_context_after_usage(app, episode_id, outcome)

            updated = store.load(episode_id)
            self.assertIsNotNone(updated)
            assert updated is not None
            reflect_compressor.assert_called_once()
            self.assertEqual(updated.compaction_count, 1)
            self.assertLess(len(updated.history_messages), 18)
            self.assertEqual(updated.compacted_history_summary, "reflect summary")
            self.assertIn("Reference summary: reflect summary", updated.frozen_prefix)
            details = [
                str((event.get("payload") or {}).get("detail") or "")
                for event in telemetry.events
                if event.get("event_type") == "kernel.stage"
                and event.get("episode_id") == episode_id
                and (event.get("payload") or {}).get("stage") == "context-compact"
            ]
            self.assertTrue(any("phase=compressing" in detail for detail in details))
            self.assertTrue(
                any(
                    "reason=usage" in detail
                    and "method=reflect" in detail
                    and "phase=compressing" not in detail
                    for detail in details
                )
            )
            results = [
                str((event.get("payload") or {}).get("result") or "")
                for event in telemetry.events
                if event.get("event_type") == "kernel.stage"
                and event.get("episode_id") == episode_id
                and (event.get("payload") or {}).get("stage") == "context-compact"
            ]
            self.assertTrue(
                any("Reflect context compression completed" in result for result in results)
            )

    def test_after_turn_short_high_usage_history_does_not_compact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            store = FileEpochStore(state_dir)
            episode_id = "episode-api-short-no-compress"
            store.save(
                SessionContextEpoch(
                    session_id=episode_id,
                    frozen=True,
                    frozen_prefix="## Stable prefix\n" + ("stable context " * 500),
                    history_messages=(
                        PromptMessage(role="user", content="hello"),
                        PromptMessage(role="assistant", content="hello back"),
                    ),
                )
            )
            telemetry = APITelemetrySink()
            app = SimpleNamespace(
                repository=SimpleNamespace(
                    database_path=state_dir / "elephant.sqlite3"
                ),
                telemetry=telemetry,
                context=SimpleNamespace(runtime=SimpleNamespace(total_tokens=1000)),
            )
            outcome = SimpleNamespace(
                execution=SimpleNamespace(prompt_tokens=900, total_tokens=900),
                context=SimpleNamespace(token_budget=1000),
                event=SimpleNamespace(event_id="event:api-short-no-compress"),
                stages=(),
            )

            with mock.patch(
                "apps.api.api_runtime_context_compression._run_reflect_context_compressor",
                return_value="should not run",
            ) as reflect_compressor:
                compact_context_after_usage(app, episode_id, outcome)

            reflect_compressor.assert_not_called()
            updated = store.load(episode_id)
            self.assertIsNotNone(updated)
            assert updated is not None
            self.assertEqual(updated.compaction_count, 0)
            self.assertEqual(len(updated.history_messages), 2)
            self.assertFalse(
                any(
                    event.get("event_type") == "kernel.stage"
                    and (event.get("payload") or {}).get("stage") == "context-compact"
                    for event in telemetry.events
                )
            )

    def test_after_turn_low_usage_does_not_emit_context_compact_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            store = FileEpochStore(state_dir)
            episode_id = "episode-api-no-compress"
            store.save(
                SessionContextEpoch(
                    session_id=episode_id,
                    frozen=True,
                    frozen_prefix="## Stable prefix",
                    history_messages=(
                        PromptMessage(role="user", content="hello"),
                        PromptMessage(role="assistant", content="hi"),
                    ),
                )
            )
            telemetry = APITelemetrySink()
            app = SimpleNamespace(
                repository=SimpleNamespace(
                    database_path=state_dir / "elephant.sqlite3"
                ),
                telemetry=telemetry,
                context=SimpleNamespace(runtime=SimpleNamespace(total_tokens=1000)),
            )
            outcome = SimpleNamespace(
                execution=SimpleNamespace(prompt_tokens=200, total_tokens=200),
                context=SimpleNamespace(token_budget=1000),
                event=SimpleNamespace(event_id="event:api-no-compress"),
                stages=(),
            )

            with mock.patch(
                "apps.api.api_runtime_context_compression._run_reflect_context_compressor",
                return_value="should not run",
            ) as reflect_compressor:
                compact_context_after_usage(app, episode_id, outcome)

            reflect_compressor.assert_not_called()
            updated = store.load(episode_id)
            self.assertIsNotNone(updated)
            assert updated is not None
            self.assertEqual(updated.compaction_count, 0)
            self.assertFalse(
                any(
                    event.get("event_type") == "kernel.stage"
                    and (event.get("payload") or {}).get("stage") == "context-compact"
                    for event in telemetry.events
                )
            )


class InternalDiaryDispatchTest(unittest.TestCase):
    def test_delete_diary_entry_routes_to_internal_method(self) -> None:
        calls: list[str] = []

        def delete_diary_entry(*, entry_date: str) -> dict[str, object]:
            calls.append(entry_date)
            return {"status": "deleted", "entry_date": entry_date, "deleted": True}

        app = SimpleNamespace(delete_diary_entry=delete_diary_entry)

        response = _dispatch_internal(app, "DELETE", ("diary", "2026-05-14"), None)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, ["2026-05-14"])
        self.assertEqual(response.payload["status"], "deleted")

    def test_delete_diary_entry_rejects_bad_date(self) -> None:
        def delete_diary_entry(*, entry_date: str) -> dict[str, object]:
            raise ValueError("entry_date must be YYYY-MM-DD")

        app = SimpleNamespace(delete_diary_entry=delete_diary_entry)

        response = _dispatch_internal(app, "DELETE", ("diary", "bad"), None)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.payload["error"], "entry_date must be YYYY-MM-DD")


class _StreamModelProvider:
    def __init__(self) -> None:
        self._stream_observer = None

    def set_stream_observer(self, observer) -> None:
        self._stream_observer = observer


class _StreamToolRuntime:
    def __init__(self) -> None:
        self.observer = None

    def subscribe(self, observer):
        self.observer = observer

        def _unsubscribe() -> None:
            self.observer = None

        return _unsubscribe


class _LoopResult:
    def __init__(self) -> None:
        self.outcome = SimpleNamespace(
            execution=SimpleNamespace(summary="stream complete"),
            turn_messages=(),
        )

    def to_record(self) -> dict[str, object]:
        return {
            "episode": {"episode_id": "session-stream"},
            "outcome": {"execution": {"summary": "stream complete"}},
            "steps": [
                {
                    "action": "record_input",
                    "summary": "source input recorded",
                    "outcome": "ok",
                }
            ],
        }


class LoopEventStreamTest(unittest.TestCase):
    def test_stream_loop_events_exposes_model_kernel_and_tool_activity(self) -> None:
        model_provider = _StreamModelProvider()
        tool_runtime = _StreamToolRuntime()
        telemetry = APITelemetrySink()

        def run_loop(episode_id: str, **_kwargs):
            model_provider._stream_observer("foreign stream", session_id="other-session")
            model_provider._stream_observer("Hello from stream.")
            telemetry.emit(
                {
                    "event_id": "stage-1",
                    "event_type": "kernel.stage",
                    "episode_id": episode_id,
                    "payload": {
                        "stage": "recall",
                        "detail": "retrieving personal context",
                        "event_id": "event-1",
                    },
                }
            )
            invocation = ToolInvocation(
                invocation_id=f"{episode_id}:tool.code.execute",
                tool_id="tool.code.execute",
                session_id=episode_id,
                context=ToolRuntimeContext(cwd=Path.cwd(), surface_id="api:test"),
                arguments={"code": "print('hello')"},
            )
            tool_runtime.observer(
                ToolLifecycleEvent(
                    event_id="tool-1",
                    invocation=invocation,
                    phase="execution.started",
                    detail="executing tool.code.execute",
                )
            )
            return _LoopResult()

        app = SimpleNamespace(
            model_provider=model_provider,
            tool_runtime=tool_runtime,
            telemetry=telemetry,
            run_loop=run_loop,
            _loop_stream_lock=Lock(),
        )

        events = list(stream_loop_events(app, "session-stream", prompt="hello"))
        event_types = [event["type"] for event in events]

        self.assertIn("loop.started", event_types)
        self.assertIn("assistant.delta", event_types)
        self.assertIn("kernel.stage", event_types)
        self.assertIn("tool.lifecycle", event_types)
        self.assertEqual(events[-1]["type"], "loop.completed")
        self.assertNotIn("foreign stream", [event.get("delta") for event in events])
        tool_event = next(event for event in events if event["type"] == "tool.lifecycle")
        self.assertEqual(tool_event["name"], "tool.code.execute")
        self.assertEqual(tool_event["status"], "running")
        self.assertEqual(events[-1]["reply_text"], "stream complete")
        self.assertEqual(events[-1]["reply"]["text"], "stream complete")
        self.assertNotIn("inspection", events[-1]["reply"])
        self.assertNotIn("outcome", events[-1]["reply"])

    def test_stream_loop_events_exposes_context_compact_stage(self) -> None:
        model_provider = _StreamModelProvider()
        tool_runtime = _StreamToolRuntime()
        telemetry = APITelemetrySink()

        def run_loop(episode_id: str, **_kwargs):
            telemetry.emit(
                {
                    "event_id": "context-compact-1",
                    "event_type": "kernel.stage",
                    "episode_id": episode_id,
                    "payload": {
                        "stage": "context-compact",
                        "detail": "reason=usage tokens=900->300",
                        "result": "Reflect context compression completed. method=reflect",
                    },
                }
            )
            return _LoopResult()

        app = SimpleNamespace(
            model_provider=model_provider,
            tool_runtime=tool_runtime,
            telemetry=telemetry,
            run_loop=run_loop,
            _loop_stream_lock=Lock(),
        )

        events = list(stream_loop_events(app, "session-stream", prompt="hello"))
        stage_event = next(event for event in events if event["type"] == "kernel.stage")

        self.assertEqual(stage_event["stage"], "context-compact")
        self.assertEqual(stage_event["detail"], "reason=usage tokens=900->300")
        self.assertEqual(stage_event["result"], "Reflect context compression completed. method=reflect")
        self.assertEqual(stage_event["status"], "running")

    def test_stream_loop_events_emits_heartbeat_while_loop_is_quiet(self) -> None:
        model_provider = _StreamModelProvider()
        tool_runtime = _StreamToolRuntime()
        telemetry = APITelemetrySink()

        def run_loop(_episode_id: str, **_kwargs):
            time.sleep(0.03)
            return _LoopResult()

        app = SimpleNamespace(
            model_provider=model_provider,
            tool_runtime=tool_runtime,
            telemetry=telemetry,
            run_loop=run_loop,
            _loop_stream_lock=Lock(),
        )

        with mock.patch("apps.api.api_runtime_http_methods._STREAM_KEEPALIVE_SECONDS", 0.01):
            events = list(stream_loop_events(app, "session-stream", prompt="hello"))

        event_types = [event["type"] for event in events]
        self.assertIn("stream.heartbeat", event_types)
        self.assertEqual(events[-1]["type"], "loop.completed")

    def test_wsgi_call_streams_sse_for_loop_endpoint(self) -> None:
        app = SimpleNamespace()
        calls: list[tuple[str, str]] = []

        def stream_events(episode_id: str, **kwargs):
            calls.append((episode_id, kwargs["prompt"]))
            yield {"type": "loop.started", "episode_id": episode_id}
            yield {"type": "assistant.delta", "delta": "hello"}
            yield {"type": "loop.completed", "reply_text": "done", "reply": {"outcome": {"execution": {"summary": "done"}}}}

        app.stream_loop_events = stream_events
        body = json.dumps({"prompt": "hello"}).encode("utf-8")
        captured: dict[str, object] = {}

        def start_response(status: str, headers: list[tuple[str, str]]) -> None:
            captured["status"] = status
            captured["headers"] = headers

        result = wsgi_call(
            app,
            {
                "REQUEST_METHOD": "POST",
                "PATH_INFO": "/v1/episodes/session-stream/loops/stream",
                "CONTENT_LENGTH": str(len(body)),
                "wsgi.input": BytesIO(body),
            },
            start_response,
        )

        chunks = list(result)
        self.assertEqual(captured["status"], "200 OK")
        headers = dict(captured["headers"])  # type: ignore[arg-type]
        self.assertEqual(headers["content-type"], "text/event-stream; charset=utf-8")
        header_names = {key.lower() for key, _value in captured["headers"]}  # type: ignore[index]
        self.assertNotIn("connection", header_names)
        self.assertEqual(calls, [("session-stream", "hello")])
        payload = b"".join(chunks).decode("utf-8")
        self.assertIn("event: loop.started", payload)
        self.assertIn('"delta":"hello"', payload)
        self.assertIn("event: loop.completed", payload)
        self.assertIn('"reply_text":"done"', payload)


if __name__ == "__main__":
    unittest.main()
