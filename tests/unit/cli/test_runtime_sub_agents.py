from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

from apps.cli.runtime_cron_sub_agents import _run_prepared_sub_agent_child
from packages.contracts import ExecutionResult
from packages.operator.local_agent_adapters import LocalAgentExecutionResult
from packages.operator.local_agents import LocalAgentRuntimeRecord
from packages.tools import ToolInvocation, ToolLifecycleEvent


class _ParentToolRuntime:
    def __init__(self) -> None:
        self.events: list[ToolLifecycleEvent] = []

    def _emit_event(self, event: ToolLifecycleEvent) -> None:
        self.events.append(event)


class _ChildToolRuntime:
    descriptor = SimpleNamespace()

    def __init__(self) -> None:
        self.observers = []

    def subscribe(self, observer):
        self.observers.append(observer)

        def unsubscribe() -> None:
            if observer in self.observers:
                self.observers.remove(observer)

        return unsubscribe

    def invoke(self, tool_name, arguments, *, session_id, requester=None):
        invocation = ToolInvocation(
            invocation_id=f"{session_id}:{tool_name}",
            tool_id=tool_name,
            session_id=session_id,
            arguments=dict(arguments),
            requested_at=datetime.now(timezone.utc),
            requester=requester,
        )
        event = ToolLifecycleEvent(
            event_id=f"{invocation.invocation_id}:execution.started",
            invocation=invocation,
            phase="execution.started",
            detail=f"executing {tool_name}",
        )
        for observer in tuple(self.observers):
            observer(event)
        return ExecutionResult(
            execution_id=invocation.invocation_id,
            episode_id=session_id,
            outcome="success",
            summary="tool completed",
            side_effects=(tool_name,),
        )


class _ChildModelProvider:
    def __init__(self, tool_runtime: _ChildToolRuntime) -> None:
        self.tool_runtime = tool_runtime
        self._stream_observer = None

    def set_stream_observer(self, observer) -> None:
        self._stream_observer = observer

    def emit(self, delta: str) -> None:
        if self._stream_observer is not None:
            self._stream_observer(delta, session_id="episode:child")


class RuntimeSubAgentTest(unittest.TestCase):
    def test_learning_sub_agent_relays_allowed_tool_events_to_parent_runtime(self) -> None:
        parent_tool_runtime = _ParentToolRuntime()
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        parent_runtime = SimpleNamespace(
            tool_runtime=parent_tool_runtime,
            paths=SimpleNamespace(state_dir=Path(tempdir.name)),
        )
        child_tool_runtime = _ChildToolRuntime()
        child_runtime = SimpleNamespace(
            tool_runtime=child_tool_runtime,
            model_provider=SimpleNamespace(tool_runtime=child_tool_runtime),
            prepare_session_surface=mock.Mock(),
            close=mock.Mock(),
        )

        def run_turn(**kwargs):
            child_runtime.tool_runtime.invoke(
                "tool.personal_model.search",
                {"query": "onboarding"},
                session_id=str(kwargs["session_id"]),
                requester="model",
            )
            return SimpleNamespace(
                execution=ExecutionResult(
                    execution_id="exec:learning-child",
                    episode_id=str(kwargs["session_id"]),
                    outcome="success",
                    summary="learning result written",
                )
            )

        child_runtime._run_turn = mock.Mock(side_effect=run_turn)
        prepared_child = {
            "session_id": "episode:child",
            "parent_session_id": "episode:parent",
            "task": "Mode: init\nLearning context packet: compact facts",
            "name": "Init learning",
            "skills": (),
            "allowed_tools": ("tool.personal_model.search",),
            "system_prompt": "[SYSTEM: Background Learning Agent]",
            "learning_agent": True,
            "child_metadata": {},
        }

        with mock.patch("apps.cli.runtime_cron_sub_agents._create_child_runtime", return_value=child_runtime):
            result = _run_prepared_sub_agent_child(parent_runtime, prepared_child=prepared_child)

        self.assertEqual(result["status"], "completed")
        self.assertTrue(
            any(
                event.invocation.tool_id == "tool.personal_model.search"
                and event.phase == "execution.started"
                for event in parent_tool_runtime.events
            )
        )

    def test_learning_sub_agent_relays_model_stream_to_parent_runtime(self) -> None:
        parent_tool_runtime = _ParentToolRuntime()
        parent_stream: list[str] = []
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        parent_runtime = SimpleNamespace(
            tool_runtime=parent_tool_runtime,
            model_provider=SimpleNamespace(_stream_observer=lambda delta, **_: parent_stream.append(delta)),
            paths=SimpleNamespace(state_dir=Path(tempdir.name)),
        )
        child_tool_runtime = _ChildToolRuntime()
        child_model_provider = _ChildModelProvider(child_tool_runtime)
        child_runtime = SimpleNamespace(
            tool_runtime=child_tool_runtime,
            model_provider=child_model_provider,
            prepare_session_surface=mock.Mock(),
            close=mock.Mock(),
        )

        def run_turn(**kwargs):
            child_model_provider.emit("I'll inspect the onboarding facts before updating memory.")
            return SimpleNamespace(
                execution=ExecutionResult(
                    execution_id="exec:learning-child",
                    episode_id=str(kwargs["session_id"]),
                    outcome="success",
                    summary="learning result written",
                )
            )

        child_runtime._run_turn = mock.Mock(side_effect=run_turn)
        prepared_child = {
            "session_id": "episode:child",
            "parent_session_id": "episode:parent",
            "task": "Mode: init\nLearning context packet: compact facts",
            "name": "Init learning",
            "skills": (),
            "allowed_tools": (),
            "system_prompt": "[SYSTEM: Background Learning Agent]",
            "learning_agent": True,
            "child_metadata": {},
        }

        with mock.patch("apps.cli.runtime_cron_sub_agents._create_child_runtime", return_value=child_runtime):
            result = _run_prepared_sub_agent_child(parent_runtime, prepared_child=prepared_child)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(parent_stream, ["I'll inspect the onboarding facts before updating memory."])
        self.assertIsNone(child_model_provider._stream_observer)

    def test_local_cli_baby_dispatches_directly_to_bound_runtime(self) -> None:
        parent_tool_runtime = _ParentToolRuntime()
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        baby_state = SimpleNamespace(
            elephant_id="codex-baby",
            state_id="state:codex-baby",
            personal_model_id="you",
        )
        runtime_record = LocalAgentRuntimeRecord(
            runtime_id="local-agent:codex:test",
            provider_id="codex",
            command="codex",
            display_name="Codex",
            resolved_path="/tmp/codex",
            can_execute=True,
            role_title="coding implementer",
            role_prompt="Run focused coding tasks.",
        )
        parent_runtime = SimpleNamespace(
            tool_runtime=parent_tool_runtime,
            paths=SimpleNamespace(state_dir=Path(tempdir.name)),
        )
        prepared_child = {
            "session_id": "episode:child",
            "parent_session_id": "episode:parent",
            "task": "Run tests",
            "name": "Codex Baby",
            "prompt": "Role: coding implementer\nTask: Run tests",
            "skills": (),
            "allowed_tools": (),
            "learning_agent": False,
            "child_metadata": {},
            "backend": "local_cli",
            "baby": {
                "state": baby_state,
                "runtime": runtime_record,
                "role_title": "coding implementer",
            },
            "timeout_seconds": "5",
        }
        fake_result = LocalAgentExecutionResult(
            status="completed",
            summary="tests passed",
            stdout="tests passed",
            stderr="",
            exit_code=0,
            provider_id="codex",
            runtime_id=runtime_record.runtime_id,
        )

        with mock.patch(
            "apps.cli.runtime_cron_sub_agents.run_local_agent_cli",
            return_value=fake_result,
        ) as run_cli, mock.patch(
            "apps.cli.runtime_cron_sub_agents._create_child_runtime"
        ) as create_child_runtime:
            result = _run_prepared_sub_agent_child(parent_runtime, prepared_child=prepared_child)

        create_child_runtime.assert_not_called()
        run_cli.assert_called_once()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["child_episode_id"], "episode:child")
        self.assertEqual(result["baby_id"], "codex-baby")
        self.assertEqual(result["provider_id"], "codex")
        self.assertEqual(result["runtime_id"], runtime_record.runtime_id)
        self.assertEqual(
            [event.phase for event in parent_tool_runtime.events],
            ["execution.started", "execution.completed"],
        )


if __name__ == "__main__":
    unittest.main()
