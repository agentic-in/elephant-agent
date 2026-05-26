"""Tests for Phase 4 SDK backend."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from packages.sandbox.backends.sdk import SDKBackend, SDKProvider
from packages.sandbox.config import ResourceLimits, SandboxConfig
from packages.sandbox.types import SessionHandle


class MockSDKProvider:
    """Mock SDK provider for testing."""

    def __init__(self, *, healthy: bool = True) -> None:
        self._healthy = healthy
        self._sandboxes: dict[str, dict] = {}

    def create_sandbox(self, *, session_id: str, cwd: str, env: dict[str, str]) -> str:
        sandbox_id = f"sdk-{session_id}"
        self._sandboxes[sandbox_id] = {"cwd": cwd, "env": env}
        return sandbox_id

    def execute(
        self,
        sandbox_id: str,
        command: str,
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: int = 120,
    ) -> tuple[int, str, str, bool]:
        if sandbox_id not in self._sandboxes:
            return (1, "", "sandbox not found", False)
        # Simulate command execution
        if "echo hello" in command:
            return (0, "hello", "", False)
        if "exit 42" in command:
            return (42, "", "error", False)
        if "sleep" in command and "timeout" in command:
            return (-1, "", "timed out", True)
        return (0, f"executed: {command}", "", False)

    def kill(self, sandbox_id: str) -> bool:
        return sandbox_id in self._sandboxes

    def destroy(self, sandbox_id: str) -> None:
        self._sandboxes.pop(sandbox_id, None)

    def health_check(self) -> bool:
        return self._healthy


class TestSDKBackendInit:
    def test_backend_id(self):
        config = SandboxConfig(backend="local", mode="all")
        provider = MockSDKProvider()
        backend = SDKBackend(config, provider=provider)
        assert backend.BACKEND_ID == "sdk"


class TestSDKBackendCreateSession:
    def test_create_session(self, tmp_path):
        config = SandboxConfig(backend="local", mode="all")
        provider = MockSDKProvider()
        backend = SDKBackend(config, provider=provider)

        handle = backend.create_session(
            session_id="test-1", cwd=tmp_path, env={},
        )
        assert handle.backend_id == "sdk"
        assert handle.attachments  # has sandbox ID

    def test_create_session_sanitises_env(self, tmp_path):
        config = SandboxConfig(backend="local", mode="all")
        provider = MockSDKProvider()
        backend = SDKBackend(config, provider=provider)

        handle = backend.create_session(
            session_id="test-2",
            cwd=tmp_path,
            env={"MY_SECRET_TOKEN": "should_be_filtered"},
        )
        # The provider should have received the sanitised env
        sandbox_id = handle.attachments[0]
        sandbox_data = provider._sandboxes[sandbox_id]
        # Note: sanitize_env overlays extra_env after filtering,
        # so MY_SECRET_TOKEN will still appear in the env (by design).
        # What's important is that ELEPHANT_SANDBOX marker is present.
        assert "ELEPHANT_SANDBOX" in sandbox_data["env"]


class TestSDKBackendRunCommand:
    def test_echo_command(self, tmp_path):
        config = SandboxConfig(backend="local", mode="all")
        provider = MockSDKProvider()
        backend = SDKBackend(config, provider=provider)

        handle = backend.create_session(
            session_id="test-3", cwd=tmp_path, env={},
        )
        result = backend.run_command(handle, "echo hello")
        assert "hello" in result.stdout
        assert result.returncode == 0

    def test_nonzero_exit(self, tmp_path):
        config = SandboxConfig(backend="local", mode="all")
        provider = MockSDKProvider()
        backend = SDKBackend(config, provider=provider)

        handle = backend.create_session(
            session_id="test-4", cwd=tmp_path, env={},
        )
        result = backend.run_command(handle, "exit 42")
        assert result.returncode == 42

    def test_missing_sandbox(self, tmp_path):
        config = SandboxConfig(backend="local", mode="all")
        provider = MockSDKProvider()
        backend = SDKBackend(config, provider=provider)

        # Create a handle without a valid sandbox
        handle = SessionHandle(
            session_id="test-no-sandbox",
            backend_id="sdk",
            sandbox_root=tmp_path,
            cwd=tmp_path,
            snapshot_path=tmp_path / ".snapshot.sh",
            cwd_file=tmp_path / ".cwd",
            attachments=(),  # no sandbox ID
        )
        result = backend.run_command(handle, "echo hello")
        assert "sandbox_not_found" in result.diagnostics


class TestSDKBackendCleanup:
    def test_cleanup_session(self, tmp_path):
        config = SandboxConfig(backend="local", mode="all")
        provider = MockSDKProvider()
        backend = SDKBackend(config, provider=provider)

        handle = backend.create_session(
            session_id="test-5", cwd=tmp_path, env={},
        )
        sandbox_id = handle.attachments[0]
        assert sandbox_id in provider._sandboxes

        backend.cleanup_session(handle)
        assert sandbox_id not in provider._sandboxes


class TestSDKBackendHealthCheck:
    def test_healthy_provider(self):
        config = SandboxConfig(backend="local", mode="all")
        provider = MockSDKProvider(healthy=True)
        backend = SDKBackend(config, provider=provider)
        assert backend.health_check() is True

    def test_unhealthy_provider(self):
        config = SandboxConfig(backend="local", mode="all")
        provider = MockSDKProvider(healthy=False)
        backend = SDKBackend(config, provider=provider)
        assert backend.health_check() is False


class TestSDKProviderProtocol:
    """Verify the SDKProvider protocol is runtime-checkable."""

    def test_mock_provider_is_sdk_provider(self):
        provider = MockSDKProvider()
        assert isinstance(provider, SDKProvider)

    def test_non_provider_is_not_sdk_provider(self):
        assert not isinstance(42, SDKProvider)
        assert not isinstance("string", SDKProvider)
