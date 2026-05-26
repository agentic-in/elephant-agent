"""Tests for SandboxEnvironment — session creation, execution, and cleanup."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.sandbox import SandboxConfig, SandboxEnvironment, LocalBackend
from packages.sandbox.config import ResourceLimits
from packages.sandbox.types import SessionHandle


class TestSandboxEnvironmentSession(unittest.TestCase):
    """SandboxEnvironment session lifecycle tests."""

    def setUp(self) -> None:
        self.config = SandboxConfig(
            mode="all",
            resource_limits=ResourceLimits(max_wall_seconds=10),
        )
        self.backend = LocalBackend(self.config)
        self.env = SandboxEnvironment(self.config, self.backend)
        self.tmpdir = Path(tempfile.mkdtemp(prefix="test-env-"))

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_session_returns_handle(self) -> None:
        handle = self.env.create_session(session_id="sess-1", cwd=self.tmpdir, env={})
        self.assertIsInstance(handle, SessionHandle)
        self.assertEqual(handle.session_id, "sess-1")

    def test_create_session_sandbox_root_exists(self) -> None:
        handle = self.env.create_session(session_id="sess-2", cwd=self.tmpdir, env={})
        self.assertTrue(handle.sandbox_root.exists())

    def test_create_session_sets_cwd(self) -> None:
        handle = self.env.create_session(session_id="sess-3", cwd=self.tmpdir, env={})
        self.assertEqual(handle.cwd, self.tmpdir)


class TestSandboxEnvironmentExecute(unittest.TestCase):
    """SandboxEnvironment.execute tests."""

    def setUp(self) -> None:
        self.config = SandboxConfig(
            mode="all",
            resource_limits=ResourceLimits(max_wall_seconds=10),
        )
        self.backend = LocalBackend(self.config)
        self.env = SandboxEnvironment(self.config, self.backend)
        self.tmpdir = Path(tempfile.mkdtemp(prefix="test-env-"))
        self.handle = self.env.create_session(session_id="exec-sess", cwd=self.tmpdir, env={})

    def tearDown(self) -> None:
        self.env.cleanup(self.handle)
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_execute_echo_command(self) -> None:
        output = self.env.execute(self.handle, "echo hello")
        self.assertEqual(output.returncode, 0)
        self.assertIn("hello", output.stdout)

    def test_execute_captures_stderr(self) -> None:
        output = self.env.execute(
            self.handle, "python3 -c \"import sys; sys.stderr.write('err\\n')\""
        )
        self.assertIn("err", output.stderr)

    def test_execute_nonzero_returncode(self) -> None:
        output = self.env.execute(self.handle, "exit 5")
        self.assertEqual(output.returncode, 5)

    def test_execute_with_custom_timeout(self) -> None:
        output = self.env.execute(self.handle, "sleep 30", timeout_seconds=1)
        self.assertTrue(output.timed_out)


class TestSandboxEnvironmentCleanup(unittest.TestCase):
    """SandboxEnvironment.cleanup tests."""

    def setUp(self) -> None:
        self.config = SandboxConfig(
            mode="all",
        )
        self.backend = LocalBackend(self.config)
        self.env = SandboxEnvironment(self.config, self.backend)
        self.tmpdir = Path(tempfile.mkdtemp(prefix="test-env-"))

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_cleanup_removes_session_directory(self) -> None:
        handle = self.env.create_session(session_id="cleanup-sess", cwd=self.tmpdir, env={})
        sandbox_root = handle.sandbox_root
        self.assertTrue(sandbox_root.exists())
        self.env.cleanup(handle)
        self.assertFalse(sandbox_root.exists())


if __name__ == "__main__":
    unittest.main()
