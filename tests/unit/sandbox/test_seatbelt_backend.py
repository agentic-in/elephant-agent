"""Unit tests for the macOS Seatbelt sandbox backend."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from packages.sandbox.backends.seatbelt import SeatbeltBackend, _seatbelt_policy
from packages.sandbox.config import SandboxConfig


class SeatbeltPolicyTests(unittest.TestCase):
    """Test Seatbelt policy generation."""

    def test_default_deny_policy(self):
        policy = _seatbelt_policy()
        self.assertIn("(version 1)", policy)
        self.assertIn("(deny default)", policy)

    def test_writable_roots_in_policy(self):
        policy = _seatbelt_policy(writable_roots=(Path("/tmp/test"),))
        self.assertIn('/tmp/test', policy)
        self.assertIn("file-write*", policy)

    def test_network_allowed(self):
        policy = _seatbelt_policy(allow_network=True)
        self.assertIn("(allow network-outbound)", policy)
        self.assertIn("(allow network-inbound)", policy)

    def test_network_loopback_allowed(self):
        policy = _seatbelt_policy(allow_network_loopback=True)
        self.assertIn("unix-socket", policy)
        self.assertIn("(deny network-outbound)", policy)
        # Full outbound not allowed in loopback-only mode
        self.assertNotIn("(allow network-outbound)\n", policy)

    def test_no_network_by_default(self):
        policy = _seatbelt_policy()
        self.assertNotIn("network-outbound", policy)
        self.assertNotIn("network-inbound", policy)

    def test_process_lifecycle_allowed(self):
        policy = _seatbelt_policy()
        self.assertIn("(allow process-exec)", policy)
        self.assertIn("(allow process-fork)", policy)

    def test_file_read_allowed_by_default(self):
        policy = _seatbelt_policy()
        self.assertIn("(allow file-read*)", policy)

    def test_dev_null_and_urandom_writable(self):
        policy = _seatbelt_policy()
        self.assertIn("/dev/null", policy)
        self.assertIn("/dev/urandom", policy)

    def test_private_tmp_writable(self):
        policy = _seatbelt_policy()
        self.assertIn("/private/tmp", policy)


class SeatbeltBackendTests(unittest.TestCase):
    """Test SeatbeltBackend implementation."""

    def test_backend_id(self):
        backend = SeatbeltBackend(SandboxConfig())
        self.assertEqual(backend.BACKEND_ID, "seatbelt")

    def test_health_check_on_macos(self):
        backend = SeatbeltBackend(SandboxConfig())
        with mock.patch.object(sys, "platform", "darwin"):
            with mock.patch("os.path.isfile", return_value=True):
                with mock.patch("os.access", return_value=True):
                    self.assertTrue(backend.health_check())

    def test_health_check_on_linux(self):
        backend = SeatbeltBackend(SandboxConfig())
        with mock.patch.object(sys, "platform", "linux"):
            self.assertFalse(backend.health_check())

    def test_health_check_no_sandbox_exec(self):
        backend = SeatbeltBackend(SandboxConfig())
        with mock.patch.object(sys, "platform", "darwin"):
            with mock.patch("os.path.isfile", return_value=False):
                self.assertFalse(backend.health_check())

    def test_create_session(self):
        backend = SeatbeltBackend(SandboxConfig(mode="all", backend="seatbelt"))
        with tempfile.TemporaryDirectory() as tmpdir:
            handle = backend.create_session(
                session_id="test-session",
                cwd=Path(tmpdir),
                env={},
            )
            self.assertEqual(handle.backend_id, "seatbelt")
            self.assertEqual(handle.session_id, "test-session")
            self.assertTrue(handle.sandbox_root.exists())
            # Policy file should exist
            policy_path = backend._policy_path(handle)
            self.assertTrue(policy_path.exists())
            policy_text = policy_path.read_text(encoding="utf-8")
            self.assertIn("(deny default)", policy_text)
            backend.cleanup_session(handle)

    def test_cleanup_session_removes_directory(self):
        backend = SeatbeltBackend(SandboxConfig(mode="all", backend="seatbelt"))
        with tempfile.TemporaryDirectory() as tmpdir:
            handle = backend.create_session(
                session_id="test-cleanup",
                cwd=Path(tmpdir),
                env={},
            )
            sandbox_root = handle.sandbox_root
            self.assertTrue(sandbox_root.exists())
            backend.cleanup_session(handle)
            self.assertFalse(sandbox_root.exists())

    @unittest.skipUnless(sys.platform == "darwin", "Seatbelt only works on macOS")
    def test_run_command_blocked_network(self):
        """Verify that a command trying to access the network is blocked."""
        backend = SeatbeltBackend(SandboxConfig(mode="all", backend="seatbelt"))
        with tempfile.TemporaryDirectory() as tmpdir:
            handle = backend.create_session(
                session_id="test-network-block",
                cwd=Path(tmpdir),
                env={},
            )
            # curl should fail because network is denied by default
            result = backend.run_command(
                handle,
                "curl -s --connect-timeout 1 https://httpbin.org/ip 2>&1 || echo NETWORK_BLOCKED",
                timeout_seconds=15,
            )
            self.assertIn("NETWORK_BLOCKED", result.stdout)
            backend.cleanup_session(handle)

    @unittest.skipUnless(sys.platform == "darwin", "Seatbelt only works on macOS")
    def test_run_command_allowed_file_write(self):
        """Verify that writing to the cwd is allowed."""
        backend = SeatbeltBackend(SandboxConfig(mode="all", backend="seatbelt", workspace_access="rw"))
        with tempfile.TemporaryDirectory() as tmpdir:
            handle = backend.create_session(
                session_id="test-write-allow",
                cwd=Path(tmpdir),
                env={},
            )
            result = backend.run_command(
                handle,
                f"touch {tmpdir}/test-write.txt && echo WRITE_OK",
                timeout_seconds=10,
            )
            self.assertIn("WRITE_OK", result.stdout)
            backend.cleanup_session(handle)


class SeatbeltConfigTests(unittest.TestCase):
    """Test Seatbelt-specific config options."""

    def test_seatbelt_options_in_config(self):
        config = SandboxConfig(
            mode="all",
            backend="seatbelt",
            seatbelt=SandboxConfig.__dataclass_fields__["seatbelt"].default_factory(),
        )
        self.assertFalse(config.seatbelt.allow_network)
        self.assertTrue(config.seatbelt.allow_network_loopback)

    def test_from_config_section_with_seatbelt(self):
        section = {
            "mode": "all",
            "backend": "seatbelt",
            "seatbelt": {
                "allow_network": True,
                "allow_network_loopback": False,
            },
        }
        config = SandboxConfig.from_config_section(section)
        self.assertEqual(config.backend, "seatbelt")
        self.assertTrue(config.seatbelt.allow_network)
        self.assertFalse(config.seatbelt.allow_network_loopback)

    def test_to_config_section_includes_seatbelt(self):
        config = SandboxConfig(mode="all", backend="seatbelt")
        section = config.to_config_section()
        self.assertIn("seatbelt", section)
        self.assertIn("allow_network", section["seatbelt"])


if __name__ == "__main__":
    unittest.main()
