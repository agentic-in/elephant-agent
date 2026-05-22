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

from apps.api.api_runtime_http_methods import __call__ as wsgi_call
from apps.api.api_runtime_context_compression import (
    compact_context_after_usage,
)
from apps.api.api_runtime_http_methods import (
    _dispatch_internal,
    _dispatch_operator,
    stream_loop_events,
)
from apps.api.capabilities import APITelemetrySink
from packages.context.epoch_store import FileEpochStore
from packages.context.session_projection import SessionContextEpoch
from packages.contracts.runtime import PromptMessage
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


class APIContextCompressionTest(unittest.TestCase):
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
