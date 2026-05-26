"""Tests for SandboxToolExecutor — delegation and sandbox hit logic."""

from __future__ import annotations

import gc
import os
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.sandbox import SandboxConfig, SandboxToolExecutor, SecurityGuard, LocalBackend, SandboxEnvironment
from packages.sandbox.config import CloudProfileOptions, ResourceLimits
from packages.sandbox.types import SessionHandle
from packages.contracts.runtime import ExecutionResult
from packages.tools import BuiltinToolDependencies, build_tool_runtime
from packages.tools.runtime import (
    ToolDefinition,
    ToolInvocation,
    ToolRuntimeContext,
    ToolSideEffectMetadata,
    ToolAvailability,
    InMemoryToolExecutor,
)


def _make_terminal_def() -> ToolDefinition:
    return ToolDefinition(
        tool_id="tool.terminal.exec",
        display_name="Terminal",
        version="1",
    )


def _make_other_def() -> ToolDefinition:
    return ToolDefinition(
        tool_id="tool.other.action",
        display_name="Other",
        version="1",
    )


def _make_invocation(
    tool_id: str = "tool.terminal.exec",
    background: bool = False,
    cwd: Path | None = None,
) -> ToolInvocation:
    ctx = ToolRuntimeContext(cwd=cwd or Path.cwd())
    args: dict = {}
    if tool_id == "tool.terminal.exec":
        args = {"command": "echo hi", "background": background}
    return ToolInvocation(
        invocation_id="inv-1",
        tool_id=tool_id,
        session_id="sess-1",
        context=ctx,
        arguments=args,
    )


def _success_handler(invocation: ToolInvocation) -> ExecutionResult:
    return ExecutionResult(
        execution_id="exec-1",
        episode_id=invocation.session_id,
        outcome="success",
        summary="ok",
    )


def _build_executor(
    mode: str = "off",
    allowed_roots: tuple[Path, ...] = (),
    event_sink=None,
    config: SandboxConfig | None = None,
) -> tuple[SandboxToolExecutor, SandboxConfig]:
    """Build a SandboxToolExecutor with the given mode."""
    delegate = InMemoryToolExecutor()
    delegate.bind("tool.terminal.exec", _success_handler)
    delegate.bind("tool.other.action", _success_handler)

    config = config or SandboxConfig(
        mode=mode,
        resource_limits=ResourceLimits(max_wall_seconds=10),
    )
    backend = LocalBackend(config)
    env = SandboxEnvironment(config, backend)
    guard = SecurityGuard()

    executor = SandboxToolExecutor(
        delegate=delegate,
        config=config,
        environment=env,
        security_guard=guard,
        allowed_roots=allowed_roots,
        event_sink=event_sink,
        event_source="test.tool.runtime.sandbox",
    )
    return executor, config


class TestSandboxExecutorOffMode(unittest.TestCase):
    """When config mode is 'off', everything delegates."""

    def setUp(self) -> None:
        self.executor, self.config = _build_executor(mode="off")
        self.tmpdir = Path(tempfile.mkdtemp(prefix="test-exec-"))

    def tearDown(self) -> None:
        self.executor.cleanup_all_sessions()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_terminal_exec_delegates_when_off(self) -> None:
        defn = _make_terminal_def()
        inv = _make_invocation()
        result = self.executor.execute(defn, inv)
        self.assertEqual(result.outcome, "success")

    def test_other_tool_delegates_when_off(self) -> None:
        defn = _make_other_def()
        inv = _make_invocation(tool_id="tool.other.action")
        result = self.executor.execute(defn, inv)
        self.assertEqual(result.outcome, "success")


class TestSandboxExecutorBindUnbind(unittest.TestCase):
    """bind and unbind delegate correctly."""

    def setUp(self) -> None:
        self.executor, _ = _build_executor(mode="all")

    def tearDown(self) -> None:
        self.executor.cleanup_all_sessions()

    def test_bind_registers_handler(self) -> None:
        self.executor.bind("tool.test", _success_handler)
        # Should be able to execute after bind (delegates because tool is not terminal.exec)
        defn = ToolDefinition(tool_id="tool.test", display_name="Test", version="1")
        inv = _make_invocation(tool_id="tool.test")
        result = self.executor.execute(defn, inv)
        self.assertEqual(result.outcome, "success")

    def test_unbind_removes_handler(self) -> None:
        self.executor.bind("tool.test", _success_handler)
        removed = self.executor.unbind("tool.test")
        self.assertTrue(removed)

    def test_unbind_unknown_returns_false(self) -> None:
        removed = self.executor.unbind("tool.nonexistent")
        self.assertFalse(removed)


class TestSandboxExecutorAllMode(unittest.TestCase):
    """When config mode is 'all', sandbox hit logic applies."""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="test-exec-"))
        self.executor, self.config = _build_executor(
            mode="all",
            allowed_roots=(self.tmpdir,),
        )

    def tearDown(self) -> None:
        self.executor.cleanup_all_sessions()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_terminal_foreground_goes_through_sandbox(self) -> None:
        """tool.terminal.exec with background=false should go through sandbox."""
        defn = _make_terminal_def()
        inv = _make_invocation(background=False, cwd=self.tmpdir)
        result = self.executor.execute(defn, inv)
        # Should complete successfully through sandbox path
        self.assertEqual(result.outcome, "success")

    def test_terminal_background_returns_success(self) -> None:
        """tool.terminal.exec with background=true should still return a valid result."""
        defn = _make_terminal_def()
        inv = _make_invocation(background=True, cwd=self.tmpdir)
        result = self.executor.execute(defn, inv)
        self.assertEqual(result.outcome, "success")

    def test_terminal_background_reuses_foreground_session(self) -> None:
        defn = _make_terminal_def()
        foreground = _make_invocation(background=False, cwd=self.tmpdir)
        background = ToolInvocation(
            invocation_id="inv-bg-reuse",
            tool_id="tool.terminal.exec",
            session_id=foreground.session_id,
            context=foreground.context,
            arguments={"command": "echo hi", "background": True},
        )

        self.executor.execute(defn, foreground)
        result = self.executor.execute(defn, background)

        self.assertEqual(result.trace_metadata.get("sandbox_resolution"), "reuse")
        self.assertEqual(result.trace_metadata.get("sandbox_cached_session"), "true")

    def test_terminal_foreground_logs_create_then_reuse(self) -> None:
        defn = _make_terminal_def()
        first = _make_invocation(background=False, cwd=self.tmpdir)
        second = _make_invocation(background=False, cwd=self.tmpdir)
        second = ToolInvocation(
            invocation_id="inv-2",
            tool_id=second.tool_id,
            session_id=second.session_id,
            context=second.context,
            arguments=second.arguments,
        )

        with self.assertLogs("packages.sandbox.executor", level="INFO") as captured:
            self.executor.execute(defn, first)
            self.executor.execute(defn, second)

        joined = "\n".join(captured.output)
        self.assertIn("sandbox.invoke", joined)
        self.assertIn("tool_id=tool.terminal.exec", joined)
        self.assertIn("invocation_id=inv-1", joined)
        self.assertIn("invocation_id=inv-2", joined)
        self.assertIn("session_id=sess-1", joined)
        self.assertIn("resolution=create", joined)
        self.assertIn("resolution=reuse", joined)
        self.assertIn("pid=", joined)
        self.assertIn("executor_id=", joined)

    def test_non_terminal_tool_delegates(self) -> None:
        """Non-terminal tools should always delegate."""
        defn = _make_other_def()
        inv = _make_invocation(tool_id="tool.other.action")
        result = self.executor.execute(defn, inv)
        self.assertEqual(result.outcome, "success")

    def test_terminal_foreground_emits_structured_sandbox_events(self) -> None:
        events: list[dict[str, object]] = []
        executor, _config = _build_executor(
            mode="all",
            allowed_roots=(self.tmpdir,),
            event_sink=events.append,
        )
        self.addCleanup(executor.cleanup_all_sessions)
        defn = _make_terminal_def()

        first = _make_invocation(background=False, cwd=self.tmpdir)
        second = ToolInvocation(
            invocation_id="inv-2",
            tool_id="tool.terminal.exec",
            session_id="sess-1",
            context=first.context,
            arguments=first.arguments,
        )

        executor.execute(defn, first)
        executor.execute(defn, second)

        invoke_events = [event for event in events if event["name"] == "sandbox.invoke"]
        session_events = [event for event in events if event["name"] == "sandbox.session"]
        self.assertEqual(len(invoke_events), 2)
        self.assertEqual([event["resolution"] for event in session_events], ["create", "reuse"])
        self.assertTrue(all(event["source"] == "test.tool.runtime.sandbox" for event in events))
        self.assertEqual(session_events[0]["sandbox_id"], None)

    def test_terminal_foreground_result_includes_trace_metadata(self) -> None:
        defn = _make_terminal_def()
        first = _make_invocation(background=False, cwd=self.tmpdir)
        second = ToolInvocation(
            invocation_id="inv-2",
            tool_id="tool.terminal.exec",
            session_id="sess-1",
            context=first.context,
            arguments=first.arguments,
        )

        first_result = self.executor.execute(defn, first)
        second_result = self.executor.execute(defn, second)

        self.assertEqual(first_result.trace_metadata.get("sandbox_backend"), "local")
        self.assertEqual(first_result.trace_metadata.get("sandbox_backend_class"), "LocalBackend")
        self.assertEqual(first_result.trace_metadata.get("sandbox_resolution"), "create")
        self.assertEqual(first_result.trace_metadata.get("sandbox_cwd"), str(self.tmpdir.resolve()))
        self.assertEqual(first_result.trace_metadata.get("sandbox_cached_session"), "false")
        self.assertEqual(second_result.trace_metadata.get("sandbox_resolution"), "reuse")
        self.assertEqual(second_result.trace_metadata.get("sandbox_cached_session"), "true")

    def test_cloud_trace_metadata_includes_provider_fields(self) -> None:
        config = SandboxConfig(
            mode="all",
            backend="cloud",
            cloud=CloudProfileOptions(provider="tencent", template="code-interpreter-v1", timeout=7200),
            resource_limits=ResourceLimits(max_wall_seconds=10),
        )
        executor, _ = _build_executor(mode="all", allowed_roots=(self.tmpdir,), config=config)
        self.addCleanup(executor.cleanup_all_sessions)
        handle = SessionHandle(
            session_id="sess-1",
            backend_id="cloud",
            sandbox_root=self.tmpdir,
            cwd=self.tmpdir,
            snapshot_path=self.tmpdir / ".snapshot.sh",
            cwd_file=self.tmpdir / ".cwd",
            attachments=("sbx-test-123",),
        )

        metadata = executor._sandbox_trace_metadata(
            handle=handle,
            cwd=self.tmpdir,
            resolution="create",
            cached_session=False,
        )

        self.assertEqual(metadata.get("sandbox_backend"), "cloud")
        self.assertEqual(metadata.get("sandbox_provider"), "tencent")
        self.assertEqual(metadata.get("sandbox_template"), "code-interpreter-v1")
        self.assertEqual(metadata.get("sandbox_timeout_seconds"), "7200")
        self.assertEqual(metadata.get("sandbox_id"), "sbx-test-123")

    def test_emit_cloud_created_serializes_cloud_metadata(self) -> None:
        events: list[dict[str, object]] = []
        config = SandboxConfig(
            mode="all",
            backend="cloud",
            cloud=CloudProfileOptions(provider="tencent", template="code-interpreter-v1", timeout=7200),
            resource_limits=ResourceLimits(max_wall_seconds=10),
        )
        executor, _ = _build_executor(
            mode="all",
            allowed_roots=(self.tmpdir,),
            event_sink=events.append,
            config=config,
        )
        self.addCleanup(executor.cleanup_all_sessions)
        invocation = _make_invocation(background=False, cwd=self.tmpdir)
        handle = SessionHandle(
            session_id=invocation.session_id,
            backend_id="cloud",
            sandbox_root=self.tmpdir,
            cwd=self.tmpdir,
            snapshot_path=self.tmpdir / ".snapshot.sh",
            cwd_file=self.tmpdir / ".cwd",
            attachments=("sbx-test-123",),
        )

        executor._emit_cloud_created(invocation=invocation, handle=handle, cwd=self.tmpdir)

        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["name"], "sandbox.cloud_created")
        self.assertEqual(event["sandbox_id"], "sbx-test-123")
        self.assertEqual(event["template"], "code-interpreter-v1")
        self.assertEqual(event["timeout_seconds"], 7200)


class TestSandboxToolRuntimeFactory(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="test-runtime-factory-"))

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_background_terminal_and_process_manage_share_sandbox_manager(self) -> None:
        runtime = build_tool_runtime(
            enabled_overrides={},
            dependencies=BuiltinToolDependencies(cwd=self.tmpdir),
            sandbox_config=SandboxConfig(
                mode="all",
                resource_limits=ResourceLimits(max_wall_seconds=10),
            ),
        )
        self.addCleanup(getattr(runtime.executor, "cleanup_all_sessions", lambda: None))

        started = runtime.invoke(
            "tool.terminal.exec",
            {
                "command": f"{sys.executable} -c \"import time; print('bg-finished'); time.sleep(0.1)\"",
                "background": True,
            },
            session_id="session-process",
        )
        process_id = started.summary.splitlines()[0].split(": ", 1)[1]

        listed = runtime.invoke(
            "tool.process.manage",
            {"action": "list"},
            session_id="session-process",
        )
        waited = runtime.invoke(
            "tool.process.manage",
            {
                "action": "wait",
                "process_id": process_id,
                "timeout_seconds": 2,
            },
            session_id="session-process",
        )

        self.assertIn(process_id, listed.summary)
        self.assertIn("status: exited(0)", waited.summary)
        self.assertIn("bg-finished", waited.summary)

    def test_background_terminal_cleanup_does_not_emit_resource_warnings(self) -> None:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ResourceWarning)
            runtime = build_tool_runtime(
                enabled_overrides={},
                dependencies=BuiltinToolDependencies(cwd=self.tmpdir),
                sandbox_config=SandboxConfig(
                    mode="all",
                    resource_limits=ResourceLimits(max_wall_seconds=10),
                ),
            )
            runtime.invoke(
                "tool.terminal.exec",
                {
                    "command": f"{sys.executable} -c \"import time; time.sleep(5)\"",
                    "background": True,
                },
                session_id="session-cleanup",
            )
            getattr(runtime.executor, "cleanup_all_sessions", lambda: None)()
            runtime = None
            gc.collect()

        resource_warnings = [warning for warning in caught if warning.category is ResourceWarning]
        self.assertEqual(resource_warnings, [])

    def test_factory_forwards_sandbox_events(self) -> None:
        events: list[dict[str, object]] = []
        runtime = build_tool_runtime(
            enabled_overrides={},
            dependencies=BuiltinToolDependencies(cwd=self.tmpdir),
            sandbox_config=SandboxConfig(
                mode="all",
                resource_limits=ResourceLimits(max_wall_seconds=10),
            ),
            sandbox_event_sink=events.append,
            sandbox_event_source="test.tool.runtime.sandbox",
        )
        self.addCleanup(getattr(runtime.executor, "cleanup_all_sessions", lambda: None))

        runtime.invoke(
            "tool.terminal.exec",
            {"command": "echo hi", "background": False},
            session_id="session-events",
        )

        self.assertTrue(any(event["name"] == "sandbox.session" for event in events))
        self.assertTrue(all(event["source"] == "test.tool.runtime.sandbox" for event in events))


if __name__ == "__main__":
    unittest.main()
