from __future__ import annotations

import json
import time
from queue import Queue
from threading import Lock, Thread
from types import SimpleNamespace
import unittest

from apps.api.api_runtime_http_methods import _StreamingClarifySurface, _dispatch_episodes
from packages.contracts import ExecutionResult


class StreamingClarifySurfaceTest(unittest.TestCase):
    def test_dispatch_endpoint_submits_answer_to_pending_stream_clarification(self) -> None:
        pending: dict[str, tuple[str, Queue[str]]] = {}
        pending_lock = Lock()
        events: list[dict[str, object]] = []
        surface = _StreamingClarifySurface(
            episode_id="episode-stream",
            enqueue=events.append,
            pending=pending,
            pending_lock=pending_lock,
            timeout_seconds=1.0,
        )
        captured: dict[str, object] = {}

        def ask() -> None:
            captured["result"] = surface.request_clarification(
                session_id="tool-session",
                question="Which file should I update?",
                mode="choice",
                choices=("README.md", "AGENTS.md"),
            )

        thread = Thread(target=ask)
        thread.start()
        for _ in range(100):
            if events:
                break
            time.sleep(0.01)

        self.assertTrue(events)
        requested = events[0]
        self.assertEqual(requested["type"], "clarify.requested")
        clarify_id = str(requested["clarify_id"])
        app = SimpleNamespace(_clarify_pending=pending, _clarify_pending_lock=pending_lock)

        with self.assertRaises(KeyError):
            _dispatch_episodes(
                app,
                "POST",
                ("other-episode", "clarifications", clarify_id),
                json.dumps({"answer": "README.md"}).encode("utf-8"),
            )

        response = _dispatch_episodes(
            app,
            "POST",
            ("episode-stream", "clarifications", clarify_id),
            json.dumps({"answer": "README.md"}).encode("utf-8"),
        )

        thread.join(timeout=1.0)
        self.assertFalse(thread.is_alive())
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.payload["status"], "submitted")
        self.assertIn("user_response: README.md", captured["result"].summary)
        self.assertEqual(pending, {})


class EpisodeTodoDispatchTest(unittest.TestCase):
    def test_patch_todo_status_invokes_session_todo_tool(self) -> None:
        calls: list[tuple[str, dict[str, object], str, str | None]] = []

        class ToolRuntimeStub:
            def invoke(self, tool_name, arguments, *, session_id, requester=None):
                calls.append((tool_name, dict(arguments), session_id, requester))
                return ExecutionResult(
                    execution_id="episode-1:tool.todo.manage",
                    episode_id=session_id,
                    outcome="success",
                    summary="updated: todo:abc | done | Ship the UI",
                    side_effects=("todo", "scratchpad"),
                )

        app = SimpleNamespace(tool_runtime=ToolRuntimeStub())
        response = _dispatch_episodes(
            app,
            "PATCH",
            ("episode-1", "todos", "todo%3Aabc"),
            json.dumps({"status": "done"}).encode("utf-8"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.payload["todo"]["status"], "done")
        self.assertEqual(
            calls,
            [
                (
                    "tool.todo.manage",
                    {"action": "complete", "item_id": "todo:abc"},
                    "episode-1",
                    "operator",
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
