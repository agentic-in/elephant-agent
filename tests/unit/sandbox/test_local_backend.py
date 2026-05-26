"""Tests for LocalBackend — session lifecycle and command execution."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.sandbox import LocalBackend
from packages.sandbox.config import ResourceLimits, SandboxConfig
from packages.sandbox.types import SessionHandle


class TestLocalBackendSessionLifecycle(unittest.TestCase):
    """LocalBackend session create / read / cleanup tests."""

    def setUp(self) -> None:
        self.config = SandboxConfig(
            mode="all",
            resource_limits=ResourceLimits(max_wall_seconds=10),
        )
        self.backend = LocalBackend(self.config)
        self.tmpdir = Path(tempfile.mkdtemp(prefix="test-sandbox-"))

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_session_returns_handle(self) -> None:
        handle = self.backend.create_session(
            session_id="test-1", cwd=self.tmpdir, env={}
        )
        self.assertIsInstance(handle, SessionHandle)
        self.assertEqual(handle.session_id, "test-1")

    def test_create_session_makes_sandbox_root(self) -> None:
        handle = self.backend.create_session(
            session_id="test-2", cwd=self.tmpdir, env={}
        )
        self.assertTrue(handle.sandbox_root.exists())

    def test_create_session_writes_snapshot_file(self) -> None:
        handle = self.backend.create_session(
            session_id="test-3", cwd=self.tmpdir, env={}
        )
        self.assertTrue(handle.snapshot_path.exists())

    def test_create_session_writes_cwd_file(self) -> None:
        handle = self.backend.create_session(
            session_id="test-4", cwd=self.tmpdir, env={}
        )
        self.assertTrue(handle.cwd_file.exists())

    def test_cleanup_session_removes_directory(self) -> None:
        handle = self.backend.create_session(
            session_id="test-5", cwd=self.tmpdir, env={}
        )
        sandbox_root = handle.sandbox_root
        self.assertTrue(sandbox_root.exists())
        self.backend.cleanup_session(handle)
        self.assertFalse(sandbox_root.exists())


class TestLocalBackendRunCommand(unittest.TestCase):
    """LocalBackend.run_command tests."""

    def setUp(self) -> None:
        self.config = SandboxConfig(
            mode="all",
            resource_limits=ResourceLimits(max_wall_seconds=10),
        )
        self.backend = LocalBackend(self.config)
        self.tmpdir = Path(tempfile.mkdtemp(prefix="test-sandbox-"))
        self.handle = self.backend.create_session(
            session_id="cmd-test", cwd=self.tmpdir, env={}
        )

    def tearDown(self) -> None:
        self.backend.cleanup_session(self.handle)
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_echo_command(self) -> None:
        output = self.backend.run_command(self.handle, "echo hello")
        self.assertEqual(output.returncode, 0)
        self.assertIn("hello", output.stdout)

    def test_respects_cwd_parameter(self) -> None:
        with tempfile.TemporaryDirectory() as nested_dir:
            output = self.backend.run_command(
                self.handle, "pwd", cwd=Path(nested_dir)
            )
            self.assertIn(nested_dir, output.stdout)

    def test_timeout_kills_process(self) -> None:
        output = self.backend.run_command(
            self.handle, "sleep 30", timeout_seconds=1
        )
        self.assertTrue(output.timed_out)

    def test_captures_stderr(self) -> None:
        output = self.backend.run_command(
            self.handle, "python3 -c \"import sys; sys.stderr.write('err\\n')\""
        )
        self.assertIn("err", output.stderr)

    def test_captures_nonzero_returncode(self) -> None:
        output = self.backend.run_command(self.handle, "exit 7")
        self.assertEqual(output.returncode, 7)

    def test_cwd_updates_after_cd(self) -> None:
        """After a cd command, the cwd file should be updated."""
        with tempfile.TemporaryDirectory() as nested_dir:
            self.backend.run_command(
                self.handle, f"cd {nested_dir}"
            )
            cwd = self.backend.read_cwd(self.handle)
            self.assertEqual(cwd, Path(nested_dir))


class TestLocalBackendReadCwd(unittest.TestCase):
    """LocalBackend.read_cwd tests."""

    def setUp(self) -> None:
        self.config = SandboxConfig(
            mode="all",
            resource_limits=ResourceLimits(max_wall_seconds=10),
        )
        self.backend = LocalBackend(self.config)
        self.tmpdir = Path(tempfile.mkdtemp(prefix="test-sandbox-"))
        self.handle = self.backend.create_session(
            session_id="cwd-test", cwd=self.tmpdir, env={}
        )

    def tearDown(self) -> None:
        self.backend.cleanup_session(self.handle)
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_read_cwd_returns_initial_cwd(self) -> None:
        cwd = self.backend.read_cwd(self.handle)
        self.assertEqual(cwd, self.tmpdir)


class TestLocalBackendHealthCheck(unittest.TestCase):
    """LocalBackend.health_check tests."""

    def test_health_check_returns_true(self) -> None:
        config = SandboxConfig()
        backend = LocalBackend(config)
        self.assertTrue(backend.health_check())


if __name__ == "__main__":
    unittest.main()
