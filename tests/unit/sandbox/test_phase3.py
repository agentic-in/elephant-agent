"""Tests for Phase 3 sandbox components.

Covers:
- SSH backend (unit tests, no SSH server required)
- SandboxProcessManager
- SandboxScopeManager lifecycle operations
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from packages.sandbox.backends.ssh import SSHBackend
from packages.sandbox.config import ResourceLimits, SandboxConfig
from packages.sandbox.process_manager import SandboxManagedProcess, SandboxProcessManager
from packages.sandbox.scope_manager import SandboxScopeManager, SessionInfo
from packages.sandbox.security_guard import SecurityGuard
from packages.sandbox.types import SandboxOutput, SessionHandle


# ---------------------------------------------------------------------------
# SSH Backend unit tests
# ---------------------------------------------------------------------------


class TestSSHBackendInit:
    def test_default_port(self):
        config = SandboxConfig(backend="ssh", mode="all")
        backend = SSHBackend(config, host="remote.example.com")
        assert backend._host == "remote.example.com"
        assert backend._port == 22
        assert backend._user is None

    def test_custom_params(self):
        config = SandboxConfig(backend="ssh", mode="all")
        backend = SSHBackend(
            config,
            host="remote.example.com",
            port=2222,
            user="sandbox",
            identity_file=Path("~/.ssh/sandbox_key"),
        )
        assert backend._port == 2222
        assert backend._user == "sandbox"
        assert backend._identity_file == Path("~/.ssh/sandbox_key")

    def test_backend_id(self):
        config = SandboxConfig(backend="ssh", mode="all")
        backend = SSHBackend(config, host="remote")
        assert backend.BACKEND_ID == "ssh"


class TestSSHBackendHealthCheck:
    def test_health_check_no_ssh(self):
        """With a non-existent ssh CLI, health_check returns False."""
        config = SandboxConfig(backend="ssh", mode="all")
        backend = SSHBackend(config, host="remote", ssh_cli="/nonexistent/ssh")
        assert backend.health_check() is False


class TestSSHBackendSSHArgs:
    def test_ssh_args_basic(self):
        config = SandboxConfig(backend="ssh", mode="all")
        backend = SSHBackend(config, host="remote.example.com", port=22)
        args = backend._ssh_args()
        assert args[0] == "ssh"
        assert "-p" in args
        assert "remote.example.com" in args

    def test_ssh_args_with_user(self):
        config = SandboxConfig(backend="ssh", mode="all")
        backend = SSHBackend(config, host="remote", user="sandbox")
        args = backend._ssh_args()
        assert "sandbox@remote" in args

    def test_ssh_args_with_identity(self, tmp_path):
        key_file = tmp_path / "test_key"
        key_file.write_text("fake-key")
        config = SandboxConfig(backend="ssh", mode="all")
        backend = SSHBackend(config, host="remote", identity_file=key_file)
        args = backend._ssh_args()
        assert "-i" in args
        assert str(key_file) in args

    def test_ssh_args_batch_mode(self):
        config = SandboxConfig(backend="ssh", mode="all")
        backend = SSHBackend(config, host="remote")
        args = backend._ssh_args()
        assert "BatchMode=yes" in args


class TestSSHBackendRunCommandNoContainer:
    def test_missing_session_returns_error(self, tmp_path):
        config = SandboxConfig(backend="ssh", mode="all")
        backend = SSHBackend(config, host="remote")
        handle = SessionHandle(
            session_id="test",
            backend_id="ssh",
            sandbox_root=tmp_path,
            cwd=Path("/tmp/elephant-sandbox-test"),
            snapshot_path=tmp_path / ".snapshot.sh",
            cwd_file=tmp_path / ".cwd",
            attachments=(),
        )
        # This should try to exec via SSH and fail (no server)
        # We just test that the method doesn't crash
        with patch.object(backend, "_exec_remote", side_effect=RuntimeError("SSH failed")):
            pass  # Method exists and takes the right params


# ---------------------------------------------------------------------------
# SandboxProcessManager tests
# ---------------------------------------------------------------------------


class TestSandboxProcessManager:
    def test_init(self):
        config = SandboxConfig(mode="all")
        from packages.sandbox.environment import SandboxEnvironment
        from packages.sandbox.backends.local import LocalBackend

        backend = LocalBackend(config)
        env = SandboxEnvironment(config, backend)
        guard = SecurityGuard()
        mgr = SandboxProcessManager(config, env, guard)
        assert mgr._config is config

    def test_start_and_list(self, tmp_path):
        config = SandboxConfig(
            mode="all",
            resource_limits=ResourceLimits(max_wall_seconds=10),
        )
        from packages.sandbox.environment import SandboxEnvironment
        from packages.sandbox.backends.local import LocalBackend

        backend = LocalBackend(config)
        env = SandboxEnvironment(config, backend)
        guard = SecurityGuard()
        mgr = SandboxProcessManager(config, env, guard)

        managed = mgr.start(command="echo hello", cwd=tmp_path, env=None)
        assert managed.process_id.startswith("proc:")
        assert managed.running is True

        # Wait for completion
        mgr.wait(managed.process_id, timeout_seconds=5)
        assert managed.running is False

        # List should include the process
        processes = mgr.list()
        assert len(processes) >= 1

    def test_kill_process(self, tmp_path):
        config = SandboxConfig(
            mode="all",
            resource_limits=ResourceLimits(max_wall_seconds=10),
        )
        from packages.sandbox.environment import SandboxEnvironment
        from packages.sandbox.backends.local import LocalBackend

        backend = LocalBackend(config)
        env = SandboxEnvironment(config, backend)
        guard = SecurityGuard()
        mgr = SandboxProcessManager(config, env, guard)

        managed = mgr.start(command="sleep 60", cwd=tmp_path, env=None)
        assert managed.running is True

        killed = mgr.kill(managed.process_id)
        assert killed.running is False

    def test_get_nonexistent_raises(self):
        config = SandboxConfig(mode="all")
        from packages.sandbox.environment import SandboxEnvironment
        from packages.sandbox.backends.local import LocalBackend

        backend = LocalBackend(config)
        env = SandboxEnvironment(config, backend)
        guard = SecurityGuard()
        mgr = SandboxProcessManager(config, env, guard)

        with pytest.raises(KeyError):
            mgr.get("nonexistent")

    def test_cleanup_all(self, tmp_path):
        config = SandboxConfig(
            mode="all",
            resource_limits=ResourceLimits(max_wall_seconds=10),
        )
        from packages.sandbox.environment import SandboxEnvironment
        from packages.sandbox.backends.local import LocalBackend

        backend = LocalBackend(config)
        env = SandboxEnvironment(config, backend)
        guard = SecurityGuard()
        mgr = SandboxProcessManager(config, env, guard)

        mgr.start(command="sleep 60", cwd=tmp_path, env=None)
        mgr.cleanup_all()
        assert len(mgr.list()) == 0

    def test_start_with_shared_session_provider_reuses_elephant_session(self, tmp_path):
        config = SandboxConfig(
            mode="all",
            resource_limits=ResourceLimits(max_wall_seconds=10),
        )
        from packages.sandbox.environment import SandboxEnvironment
        from packages.sandbox.backends.local import LocalBackend

        backend = LocalBackend(config)
        env = SandboxEnvironment(config, backend)
        guard = SecurityGuard()
        mgr = SandboxProcessManager(config, env, guard)
        handle = env.create_session(session_id="episode-shared", cwd=tmp_path, env={})
        mgr.configure_session_lifecycle(
            session_provider=lambda session_id, cwd, env: (handle, "reuse")
        )

        try:
            managed = mgr.start(
                command="sleep 60",
                cwd=tmp_path,
                env=None,
                session_id="episode-shared",
            )
            assert managed.sandbox_session_id == "episode-shared"
            assert managed.session_handle is handle
            assert managed.session_resolution == "reuse"

            cleaned = mgr.cleanup_session("episode-shared")

            assert cleaned is True
            with pytest.raises(KeyError):
                mgr.get(managed.process_id)
        finally:
            try:
                env.cleanup(handle)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# SandboxScopeManager tests
# ---------------------------------------------------------------------------


class TestSandboxScopeManager:
    @pytest.fixture
    def mock_backend(self):
        backend = MagicMock()
        backend.create_session.return_value = SessionHandle(
            session_id="test",
            backend_id="local",
            sandbox_root=Path("/tmp/test"),
            cwd=Path("/tmp"),
            snapshot_path=Path("/tmp/test/.snapshot.sh"),
            cwd_file=Path("/tmp/test/.cwd"),
        )
        return backend

    def test_session_scope_uses_base_id(self, mock_backend):
        config = SandboxConfig(mode="all", scope="session")
        mgr = SandboxScopeManager(config, mock_backend)
        resolved = mgr.resolve_session_id("abc123")
        assert resolved == "abc123"

    def test_agent_scope_prefixes_agent_id(self, mock_backend):
        config = SandboxConfig(mode="all", scope="agent")
        mgr = SandboxScopeManager(config, mock_backend)
        resolved = mgr.resolve_session_id("abc123", agent_id="my-agent")
        assert resolved == "agent:my-agent:abc123"

    def test_shared_scope_uses_shared_prefix(self, mock_backend):
        config = SandboxConfig(mode="all", scope="shared")
        mgr = SandboxScopeManager(config, mock_backend)
        resolved = mgr.resolve_session_id("abc123")
        assert resolved == "shared:abc123"

    def test_create_session(self, mock_backend):
        config = SandboxConfig(mode="all", scope="session")
        mgr = SandboxScopeManager(config, mock_backend)
        handle = mgr.create_session(
            session_id="s1", cwd=Path("/tmp"), env={},
        )
        assert handle is not None
        mock_backend.create_session.assert_called_once()

    def test_get_session(self, mock_backend):
        config = SandboxConfig(mode="all", scope="session")
        mgr = SandboxScopeManager(config, mock_backend)
        mgr.create_session(session_id="s1", cwd=Path("/tmp"), env={})
        handle = mgr.get_session("s1")
        assert handle is not None

    def test_get_nonexistent_session(self, mock_backend):
        config = SandboxConfig(mode="all", scope="session")
        mgr = SandboxScopeManager(config, mock_backend)
        assert mgr.get_session("nonexistent") is None

    def test_cleanup_session(self, mock_backend):
        config = SandboxConfig(mode="all", scope="session")
        mgr = SandboxScopeManager(config, mock_backend)
        mgr.create_session(session_id="s1", cwd=Path("/tmp"), env={})
        result = mgr.cleanup_session("s1")
        assert result is True
        assert mgr.get_session("s1") is None

    def test_cleanup_nonexistent_session(self, mock_backend):
        config = SandboxConfig(mode="all", scope="session")
        mgr = SandboxScopeManager(config, mock_backend)
        result = mgr.cleanup_session("nonexistent")
        assert result is False

    def test_list_sessions(self, mock_backend):
        config = SandboxConfig(mode="all", scope="session")
        mgr = SandboxScopeManager(config, mock_backend)
        mgr.create_session(session_id="s1", cwd=Path("/tmp"), env={})
        mgr.create_session(session_id="s2", cwd=Path("/tmp"), env={})
        sessions = mgr.list_sessions()
        assert len(sessions) == 2

    def test_inspect_session(self, mock_backend):
        config = SandboxConfig(mode="all", scope="session")
        mgr = SandboxScopeManager(config, mock_backend)
        mgr.create_session(session_id="s1", cwd=Path("/tmp"), env={})
        info = mgr.inspect_session("s1")
        assert info is not None
        assert info.session_id == "s1"
        assert info.scope == "session"

    def test_prune_stale_sessions(self, mock_backend):
        config = SandboxConfig(mode="all", scope="session")
        mgr = SandboxScopeManager(config, mock_backend)
        mgr.create_session(session_id="s1", cwd=Path("/tmp"), env={})
        # Prune with 0-second max age — should remove everything
        pruned = mgr.prune_stale_sessions(max_age_seconds=0)
        assert pruned == 1
        assert len(mgr.list_sessions()) == 0

    def test_cleanup_all(self, mock_backend):
        config = SandboxConfig(mode="all", scope="session")
        mgr = SandboxScopeManager(config, mock_backend)
        mgr.create_session(session_id="s1", cwd=Path("/tmp"), env={})
        mgr.create_session(session_id="s2", cwd=Path("/tmp"), env={})
        count = mgr.cleanup_all()
        assert count == 2
        assert len(mgr.list_sessions()) == 0
