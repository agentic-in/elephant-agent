"""Tests for sandbox code execution launcher — Phase 1B.

Verifies that:
- Code execution still works when using the sandbox code launcher
- AST validation, project/strict mode, and tool RPC are preserved
- The sandbox launcher applies resource limits and env sanitisation
- The launcher is properly injected by SandboxToolExecutor
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.sandbox import SandboxConfig, SandboxCodeLauncher, LocalCodeLauncher
from packages.sandbox.config import CloudProfileOptions, ResourceLimits
from packages.sandbox.types import SessionHandle


class TestLocalCodeLauncher(unittest.TestCase):
    """LocalCodeLauncher preserves original subprocess behaviour."""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="test-code-local-"))
        self.launcher = LocalCodeLauncher()

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_start_creates_process(self) -> None:
        runner_path = self.tmpdir / "runner.py"
        runner_path.write_text("print('hello from runner')\n", encoding="utf-8")
        stdout_path = self.tmpdir / "stdout.txt"
        stderr_path = self.tmpdir / "stderr.txt"

        process = self.launcher.start(
            runner_path=runner_path,
            child_cwd=self.tmpdir,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        self.assertIsNotNone(process.pid)
        process.wait(timeout=10)

    def test_wait_and_collect_returns_results(self) -> None:
        runner_path = self.tmpdir / "runner.py"
        runner_path.write_text("print('test output')\n", encoding="utf-8")
        stdout_path = self.tmpdir / "stdout.txt"
        stderr_path = self.tmpdir / "stderr.txt"

        process = self.launcher.start(
            runner_path=runner_path,
            child_cwd=self.tmpdir,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )

        returncode, timed_out, stdout_text, stderr_text, diagnostics = self.launcher.wait_and_collect(
            process,
            timeout_seconds=10,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )

        self.assertEqual(returncode, 0)
        self.assertFalse(timed_out)
        self.assertIn("test output", stdout_text)
        self.assertEqual(diagnostics, ())


class TestSandboxCodeLauncher(unittest.TestCase):
    """SandboxCodeLauncher applies sandbox constraints to code runner."""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="test-code-sandbox-"))
        self.config = SandboxConfig(
            mode="all",
            resource_limits=ResourceLimits(max_wall_seconds=10, max_memory_mb=256),
        )
        self.launcher = SandboxCodeLauncher(
            config=self.config,
            session_id="test-code-session",
        )

    def tearDown(self) -> None:
        self.launcher.cleanup()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_start_creates_process(self) -> None:
        runner_path = self.tmpdir / "runner.py"
        runner_path.write_text("print('sandboxed')\n", encoding="utf-8")
        stdout_path = self.tmpdir / "stdout.txt"
        stderr_path = self.tmpdir / "stderr.txt"

        process = self.launcher.start(
            runner_path=runner_path,
            child_cwd=self.tmpdir,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        self.assertIsNotNone(process.pid)
        process.wait(timeout=10)

    def test_wait_and_collect_returns_results(self) -> None:
        runner_path = self.tmpdir / "runner.py"
        runner_path.write_text("print('sandbox output')\n", encoding="utf-8")
        stdout_path = self.tmpdir / "stdout.txt"
        stderr_path = self.tmpdir / "stderr.txt"

        process = self.launcher.start(
            runner_path=runner_path,
            child_cwd=self.tmpdir,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )

        returncode, timed_out, stdout_text, stderr_text, diagnostics = self.launcher.wait_and_collect(
            process,
            timeout_seconds=10,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )

        self.assertEqual(returncode, 0)
        self.assertFalse(timed_out)
        self.assertIn("sandbox output", stdout_text)

    def test_sandbox_env_sanitisation(self) -> None:
        """The sandbox launcher should strip sensitive env vars from the child."""
        runner_path = self.tmpdir / "runner.py"
        runner_path.write_text(
            "import os; print('HAS_SECRET=' + str('MY_SECRET_TOKEN' in os.environ))\n",
            encoding="utf-8",
        )
        stdout_path = self.tmpdir / "stdout.txt"
        stderr_path = self.tmpdir / "stderr.txt"

        # We set the secret in os.environ temporarily so the launcher
        # picks it up in its base_env and then strips it.
        original = os.environ.get("MY_SECRET_TOKEN")
        os.environ["MY_SECRET_TOKEN"] = "should-be-removed"
        try:
            process = self.launcher.start(
                runner_path=runner_path,
                child_cwd=self.tmpdir,
                env={},
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )

            returncode, timed_out, stdout_text, stderr_text, diagnostics = self.launcher.wait_and_collect(
                process,
                timeout_seconds=10,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )

            self.assertEqual(returncode, 0)
            self.assertIn("HAS_SECRET=False", stdout_text)
        finally:
            if original is None:
                os.environ.pop("MY_SECRET_TOKEN", None)
            else:
                os.environ["MY_SECRET_TOKEN"] = original

    def test_sandbox_sets_elephant_sandbox_env(self) -> None:
        """The sandbox launcher should set ELEPHANT_SANDBOX=1."""
        runner_path = self.tmpdir / "runner.py"
        runner_path.write_text(
            "import os; print('SANDBOX=' + os.environ.get('ELEPHANT_SANDBOX', '0'))\n",
            encoding="utf-8",
        )
        stdout_path = self.tmpdir / "stdout.txt"
        stderr_path = self.tmpdir / "stderr.txt"

        process = self.launcher.start(
            runner_path=runner_path,
            child_cwd=self.tmpdir,
            env={},
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )

        returncode, timed_out, stdout_text, stderr_text, diagnostics = self.launcher.wait_and_collect(
            process,
            timeout_seconds=10,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )

        self.assertEqual(returncode, 0)
        self.assertIn("SANDBOX=1", stdout_text)

    def test_timeout_kills_process(self) -> None:
        """A long-running code snippet should be killed by the governor."""
        runner_path = self.tmpdir / "runner.py"
        runner_path.write_text(
            "import time; time.sleep(60)\n",
            encoding="utf-8",
        )
        stdout_path = self.tmpdir / "stdout.txt"
        stderr_path = self.tmpdir / "stderr.txt"

        process = self.launcher.start(
            runner_path=runner_path,
            child_cwd=self.tmpdir,
            env={},
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )

        returncode, timed_out, stdout_text, stderr_text, diagnostics = self.launcher.wait_and_collect(
            process,
            timeout_seconds=1,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )

        self.assertTrue(timed_out)
        self.assertTrue(any("timeout" in d.lower() for d in diagnostics))

    def test_nonzero_exit_captured(self) -> None:
        """Non-zero exit code should be captured."""
        runner_path = self.tmpdir / "runner.py"
        runner_path.write_text("raise SystemExit(42)\n", encoding="utf-8")
        stdout_path = self.tmpdir / "stdout.txt"
        stderr_path = self.tmpdir / "stderr.txt"

        process = self.launcher.start(
            runner_path=runner_path,
            child_cwd=self.tmpdir,
            env={},
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )

        returncode, timed_out, stdout_text, stderr_text, diagnostics = self.launcher.wait_and_collect(
            process,
            timeout_seconds=10,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )

        self.assertEqual(returncode, 42)
        self.assertFalse(timed_out)

    def test_bind_invocation_emits_structured_session_events(self) -> None:
        events: list[dict[str, object]] = []
        launcher = SandboxCodeLauncher(
            config=self.config,
            session_id="test-code-session-events",
            event_sink=events.append,
            event_source="test.tool.runtime.sandbox",
        )
        self.addCleanup(launcher.cleanup)

        launcher.bind_invocation(
            invocation_id="inv-code-1",
            episode_id="episode-code-1",
            tool_id="tool.code.execute",
        )
        launcher._ensure_session(self.tmpdir, {})
        launcher.bind_invocation(
            invocation_id="inv-code-2",
            episode_id="episode-code-2",
            tool_id="tool.code.execute",
        )
        launcher._ensure_session(self.tmpdir, {})

        session_events = [event for event in events if event["name"] == "sandbox.session"]
        self.assertEqual([event["resolution"] for event in session_events], ["create", "reuse"])
        self.assertEqual(session_events[0]["tool_id"], "tool.code.execute")
        self.assertTrue(all(event["source"] == "test.tool.runtime.sandbox" for event in events))

    def test_cloud_backend_emits_cloud_created_event(self) -> None:
        events: list[dict[str, object]] = []
        config = SandboxConfig(
            mode="all",
            backend="cloud",
            cloud=CloudProfileOptions(provider="tencent", template="code-interpreter-v1", timeout=7200),
            resource_limits=ResourceLimits(max_wall_seconds=10),
        )
        handle = SessionHandle(
            session_id="code-session-cloud",
            backend_id="cloud",
            sandbox_root=self.tmpdir,
            cwd=self.tmpdir,
            snapshot_path=self.tmpdir / ".snapshot.sh",
            cwd_file=self.tmpdir / ".cwd",
            attachments=("sbx-code-123",),
        )
        backend = MagicMock()
        backend.create_session.return_value = handle
        launcher = SandboxCodeLauncher(
            config=config,
            session_id="code-session-cloud",
            backend=backend,
            event_sink=events.append,
            event_source="test.tool.runtime.sandbox",
        )
        self.addCleanup(launcher.cleanup)
        launcher.bind_invocation(
            invocation_id="inv-code-cloud",
            episode_id="episode-code-cloud",
            tool_id="tool.code.execute",
        )

        launcher._ensure_session(self.tmpdir, {})

        cloud_events = [event for event in events if event["name"] == "sandbox.cloud_created"]
        self.assertEqual(len(cloud_events), 1)
        self.assertEqual(cloud_events[0]["sandbox_id"], "sbx-code-123")
        self.assertEqual(cloud_events[0]["template"], "code-interpreter-v1")
        self.assertEqual(cloud_events[0]["timeout_seconds"], 7200)

    def test_trace_metadata_marks_reused_shared_session(self) -> None:
        handle = SessionHandle(
            session_id="code-session-shared",
            backend_id="local",
            sandbox_root=self.tmpdir,
            cwd=self.tmpdir,
            snapshot_path=self.tmpdir / ".snapshot.sh",
            cwd_file=self.tmpdir / ".cwd",
        )
        launcher = SandboxCodeLauncher(
            config=self.config,
            session_id="code-session-shared",
            session_provider=lambda _cwd, _env: (handle, "reuse"),
        )
        self.addCleanup(launcher.cleanup)
        launcher.bind_invocation(
            invocation_id="inv-code-shared",
            episode_id="episode-code-shared",
            tool_id="tool.code.execute",
        )

        launcher._ensure_session(self.tmpdir, {})
        metadata = launcher.trace_metadata()

        self.assertEqual(metadata.get("sandbox_resolution"), "reuse")
        self.assertEqual(metadata.get("sandbox_cached_session"), "true")


class TestCodeLauncherProtocol(unittest.TestCase):
    """Verify the CodeExecutionLauncher protocol compliance."""

    def test_sandbox_launcher_satisfies_protocol(self) -> None:
        from packages.sandbox.code_launcher import CodeExecutionLauncher

        self.assertIsInstance(self._make_launcher(), CodeExecutionLauncher)

    def test_local_launcher_satisfies_protocol(self) -> None:
        from packages.sandbox.code_launcher import CodeExecutionLauncher

        self.assertIsInstance(LocalCodeLauncher(), CodeExecutionLauncher)

    def _make_launcher(self) -> SandboxCodeLauncher:
        return SandboxCodeLauncher(
            config=SandboxConfig(mode="all"),
            session_id="protocol-test",
        )


class TestSandboxExecutorCodeLauncherInjection(unittest.TestCase):
    """SandboxToolExecutor injects code launcher for tool.code.execute."""

    def setUp(self) -> None:
        from packages.sandbox import SandboxToolExecutor, SecurityGuard, SandboxEnvironment, LocalBackend
        from packages.tools.runtime import InMemoryToolExecutor

        self.tmpdir = Path(tempfile.mkdtemp(prefix="test-code-exec-"))
        config = SandboxConfig(
            mode="all",
            resource_limits=ResourceLimits(max_wall_seconds=10),
        )
        delegate = InMemoryToolExecutor()
        backend = LocalBackend(config)
        env = SandboxEnvironment(config, backend)
        guard = SecurityGuard()
        self.executor = SandboxToolExecutor(
            delegate=delegate,
            config=config,
            environment=env,
            security_guard=guard,
            allowed_roots=(self.tmpdir,),
        )

    def tearDown(self) -> None:
        self.executor.cleanup_all_sessions()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_should_sandbox_code_execute_returns_true_when_active(self) -> None:
        from packages.tools.runtime import ToolDefinition

        defn = ToolDefinition(tool_id="tool.code.execute", display_name="Code", version="1")
        self.assertTrue(self.executor._should_sandbox_code_execute(defn))

    def test_should_sandbox_code_execute_returns_false_for_other_tools(self) -> None:
        from packages.tools.runtime import ToolDefinition

        defn = ToolDefinition(tool_id="tool.file.read", display_name="File", version="1")
        self.assertFalse(self.executor._should_sandbox_code_execute(defn))

    def test_should_sandbox_code_execute_returns_false_when_off(self) -> None:
        from packages.sandbox import SandboxToolExecutor, SecurityGuard, SandboxEnvironment, LocalBackend
        from packages.tools.runtime import InMemoryToolExecutor, ToolDefinition

        config = SandboxConfig(mode="off")
        delegate = InMemoryToolExecutor()
        backend = LocalBackend(config)
        env = SandboxEnvironment(config, backend)
        guard = SecurityGuard()
        executor = SandboxToolExecutor(
            delegate=delegate, config=config, environment=env, security_guard=guard,
        )

        defn = ToolDefinition(tool_id="tool.code.execute", display_name="Code", version="1")
        self.assertFalse(executor._should_sandbox_code_execute(defn))
        executor.cleanup_all_sessions()

    def test_inject_code_launcher_adds_key(self) -> None:
        from packages.tools.runtime import ToolInvocation, ToolRuntimeContext

        invocation = ToolInvocation(
            invocation_id="inv-1",
            tool_id="tool.code.execute",
            session_id="sess-1",
            context=ToolRuntimeContext(cwd=self.tmpdir),
            arguments={"code": "x = 1"},
        )

        launcher = self.executor._get_or_create_code_launcher("sess-1")
        modified = self.executor._inject_code_launcher(invocation, launcher)

        self.assertIn("__sandbox_code_launcher__", modified.arguments)
        self.assertIs(modified.arguments["__sandbox_code_launcher__"], launcher)

    def test_get_or_create_code_launcher_caches(self) -> None:
        launcher1 = self.executor._get_or_create_code_launcher("sess-a")
        launcher2 = self.executor._get_or_create_code_launcher("sess-a")
        self.assertIs(launcher1, launcher2)

    def test_get_or_create_code_launcher_different_sessions(self) -> None:
        launcher1 = self.executor._get_or_create_code_launcher("sess-a")
        launcher2 = self.executor._get_or_create_code_launcher("sess-b")
        self.assertIsNot(launcher1, launcher2)

    def test_cleanup_all_sessions_cleans_launchers(self) -> None:
        self.executor._get_or_create_code_launcher("sess-a")
        self.executor._get_or_create_code_launcher("sess-b")
        self.assertEqual(len(self.executor._code_launchers), 2)

        self.executor.cleanup_all_sessions()
        self.assertEqual(len(self.executor._code_launchers), 0)


if __name__ == "__main__":
    unittest.main()
