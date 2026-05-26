"""Unit tests for Tencent Cloud Agent Runtime sandbox backend."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from packages.sandbox.config import CloudProfileOptions, CloudSandboxOptions, SandboxConfig
from packages.sandbox.backends.tencent_cloud import (
    TencentCloudBackend,
    TencentCloudFactory,
    TencentCloudSandboxProvider,
    _truncate,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_config(**cloud_overrides) -> SandboxConfig:
    profile = CloudProfileOptions(**cloud_overrides)
    return SandboxConfig(
        mode="all",
        backend="cloud",
        cloud=profile,
    )


# ---------------------------------------------------------------------------
# _truncate
# ---------------------------------------------------------------------------

class TestTruncate:
    def test_short_text(self):
        assert _truncate("hello", 100) == "hello"

    def test_exact_limit(self):
        text = "a" * 50
        assert _truncate(text, 50) == text

    def test_over_limit(self):
        text = "a" * 200
        result = _truncate(text, 50)
        assert "truncated" in result
        assert len(result.encode("utf-8")) <= 100  # approx

    def test_unicode(self):
        text = "中文" * 100
        result = _truncate(text, 50)
        assert "truncated" in result


# ---------------------------------------------------------------------------
# TencentCloudSandboxProvider
# ---------------------------------------------------------------------------

class TestTencentCloudSandboxProvider:
    def test_health_check_no_api_key(self):
        config = _make_config(api_key="")
        with patch.dict(os.environ, {"E2B_API_KEY": ""}, clear=False):
            provider = TencentCloudSandboxProvider(config)
            assert not provider.health_check()

    def test_health_check_with_api_key(self):
        config = _make_config(api_key="ark_test123")
        provider = TencentCloudSandboxProvider(config)
        result = provider.health_check()
        assert isinstance(result, bool)

    def test_create_sandbox_sets_env_vars(self):
        config = _make_config(
            template="code-interpreter-v1",
            domain="ap-guangzhou.tencentags.com",
            api_key="ark_test123",
            timeout=7200,
        )
        provider = TencentCloudSandboxProvider(config)
        # Just verify config is accessible
        assert provider._profile.domain == "ap-guangzhou.tencentags.com"
        assert provider._profile.api_key == "ark_test123"

    def test_execute_no_sandbox(self):
        config = _make_config()
        provider = TencentCloudSandboxProvider(config)
        rc, stdout, stderr, timed_out = provider.execute("nonexistent-id", "echo hello")
        assert rc == 1
        assert "not found" in stderr.lower()

    def test_destroy(self):
        config = _make_config()
        provider = TencentCloudSandboxProvider(config)
        provider.destroy("nonexistent-id")

    def test_accepts_explicit_profile(self):
        profile = CloudProfileOptions(provider="tencent", domain="ap-shanghai.tencentags.com", api_key="ark_explicit")
        config = _make_config()  # default profile
        provider = TencentCloudSandboxProvider(config, profile=profile)
        assert provider._profile is profile
        assert provider._profile.domain == "ap-shanghai.tencentags.com"


# ---------------------------------------------------------------------------
# TencentCloudBackend
# ---------------------------------------------------------------------------

class TestTencentCloudBackend:
    def test_backend_id(self):
        config = _make_config()
        backend = TencentCloudBackend(config)
        assert backend.BACKEND_ID == "cloud"

    def test_create_session_logs_cloud_sandbox_identity(self, caplog):
        config = _make_config(template="code-interpreter-v1", timeout=7200)
        backend = TencentCloudBackend(config)
        fake_sandbox = SimpleNamespace(
            sandbox_id="sbx-test-123",
            commands=SimpleNamespace(
                run=MagicMock(
                    return_value=SimpleNamespace(stdout="diag", stderr="", exit_code=0)
                )
            ),
            kill=MagicMock(),
        )

        with patch.object(backend, "_create_cloud_sandbox", return_value=fake_sandbox):
            with caplog.at_level(logging.INFO, logger="packages.sandbox.backends.tencent_cloud"):
                handle = backend.create_session(
                    session_id="episode-123",
                    cwd=Path("/tmp"),
                    env={},
                )

        assert "sandbox.cloud_created" in caplog.text
        assert "session_id=episode-123" in caplog.text
        assert "sandbox_id=sbx-test-123" in caplog.text
        assert "template=code-interpreter-v1" in caplog.text
        assert "timeout_seconds=7200" in caplog.text
        backend.cleanup_session(handle)

    def test_health_check_no_api_key(self):
        config = _make_config(api_key="")
        with patch.dict(os.environ, {"E2B_API_KEY": ""}, clear=False):
            backend = TencentCloudBackend(config)
            assert not backend.health_check()

    def test_health_check_with_api_key(self):
        config = _make_config(api_key="ark_test123")
        backend = TencentCloudBackend(config)
        result = backend.health_check()
        assert isinstance(result, bool)

    def test_run_command_no_sandbox(self):
        config = _make_config()
        backend = TencentCloudBackend(config)
        handle = MagicMock()
        handle.session_id = "test-session"
        handle.cwd = Path("/tmp")
        result = backend.run_command(handle, "echo hello")
        assert result.returncode == 1
        assert "not found" in result.stderr.lower()

    def test_kill_process_no_sandbox(self):
        config = _make_config()
        backend = TencentCloudBackend(config)
        handle = MagicMock()
        handle.session_id = "test-session"
        assert not backend.kill_process(handle, 12345)

    def test_run_command_uses_stable_launch_cwd(self):
        config = _make_config()
        backend = TencentCloudBackend(config)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".cwd", delete=False) as cwd_file:
            cwd_file.write("/home/user")
            cwd_file.flush()
            cwd_file_path = Path(cwd_file.name)

        handle = SimpleNamespace(
            session_id="test-session",
            cwd=Path("/tmp"),
            cwd_file=cwd_file_path,
        )
        backend._cwd_map[handle.session_id] = "/home/user"

        sandbox = MagicMock()
        sandbox.commands.run.return_value = SimpleNamespace(
            exit_code=0,
            stdout="ok",
            stderr="",
        )
        sandbox.files.read.return_value = "/home/user/felix"
        backend._sandboxes[handle.session_id] = sandbox

        try:
            result = backend.run_command(
                handle,
                "pwd",
                cwd=Path("/Users/wuhao/.elephant/workspaces/felix"),
            )
        finally:
            os.unlink(cwd_file_path)

        assert result.returncode == 0
        assert result.stdout == "ok"
        _, kwargs = sandbox.commands.run.call_args
        assert kwargs["cwd"] == "/home/user"
        assert "mkdir -p '/home/user/felix'" in sandbox.commands.run.call_args.args[0]
        assert backend._cwd_map[handle.session_id] == "/home/user/felix"

    def test_read_cwd_from_file(self):
        config = _make_config()
        backend = TencentCloudBackend(config)
        handle = MagicMock()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cwd", delete=False) as f:
            f.write("/home/user/project")
            f.flush()
            handle.cwd_file = Path(f.name)
        result = backend.read_cwd(handle)
        assert result == Path("/home/user/project")
        os.unlink(f.name)

    def test_read_cwd_fallback(self):
        config = _make_config()
        backend = TencentCloudBackend(config)
        handle = MagicMock()
        handle.cwd = Path("/home/user")
        handle.cwd_file = Path("/nonexistent/.cwd")
        result = backend.read_cwd(handle)
        assert result == Path("/home/user")

    def test_cleanup_session_no_sandbox(self):
        import tempfile
        config = _make_config()
        backend = TencentCloudBackend(config)
        sandbox_root = Path(tempfile.mkdtemp(prefix="test-cloud-"))
        handle = MagicMock()
        handle.session_id = "test-session"
        handle.sandbox_root = sandbox_root
        backend.cleanup_session(handle)
        assert not sandbox_root.exists()

    def test_accepts_explicit_profile(self):
        profile = CloudProfileOptions(provider="tencent", domain="ap-shanghai.tencentags.com", api_key="ark_explicit")
        config = _make_config()
        backend = TencentCloudBackend(config, profile=profile)
        assert backend._profile is profile


# ---------------------------------------------------------------------------
# TencentCloudFactory
# ---------------------------------------------------------------------------

class TestTencentCloudFactory:
    def test_create(self):
        config = _make_config(api_key="ark_factory")
        factory = TencentCloudFactory()
        backend = factory.create(config, config.effective_cloud())
        assert isinstance(backend, TencentCloudBackend)
        assert backend._profile.api_key == "ark_factory"


# ---------------------------------------------------------------------------
# CloudProfileOptions
# ---------------------------------------------------------------------------

class TestCloudProfileOptions:
    def test_defaults(self):
        opts = CloudProfileOptions()
        assert opts.provider == "tencent"
        assert opts.template == ""
        assert opts.domain == "ap-guangzhou.tencentags.com"
        assert opts.api_key == ""
        assert opts.timeout == 3600
        assert opts.allow_internet is True
        assert opts.extra == {}

    def test_custom(self):
        opts = CloudProfileOptions(
            provider="e2b",
            template="code-interpreter-v1",
            domain="e2b.dev",
            api_key="e2b_abc123",
            timeout=7200,
            allow_internet=False,
            extra={"region": "us-east-1"},
        )
        assert opts.provider == "e2b"
        assert opts.template == "code-interpreter-v1"
        assert opts.domain == "e2b.dev"
        assert opts.api_key == "e2b_abc123"
        assert opts.timeout == 7200
        assert opts.allow_internet is False
        assert opts.extra["region"] == "us-east-1"

    def test_frozen(self):
        opts = CloudProfileOptions()
        with pytest.raises(AttributeError):
            opts.provider = "aws"  # type: ignore[misc]

    def test_backward_compat_alias(self):
        assert CloudSandboxOptions is CloudProfileOptions


# ---------------------------------------------------------------------------
# SandboxConfig with cloud
# ---------------------------------------------------------------------------

class TestSandboxConfigCloud:
    def test_backend_literal_includes_cloud(self):
        from packages.sandbox.config import SandboxBackend
        config = SandboxConfig(backend="cloud")
        assert config.backend == "cloud"

    def test_from_config_section(self):
        section = {
            "mode": "all",
            "backend": "cloud",
            "cloud": {
                "provider": "tencent",
                "template": "my-template",
                "domain": "ap-shanghai.tencentags.com",
                "api_key": "ark_test123",
                "timeout": 1800,
                "allow_internet": False,
            },
        }
        config = SandboxConfig.from_config_section(section)
        assert config.backend == "cloud"
        assert config.cloud.provider == "tencent"
        assert config.cloud.template == "my-template"
        assert config.cloud.domain == "ap-shanghai.tencentags.com"
        assert config.cloud.api_key == "ark_test123"
        assert config.cloud.timeout == 1800
        assert config.cloud.allow_internet is False

    def test_to_config_section(self):
        config = SandboxConfig(
            mode="all",
            backend="cloud",
            cloud=CloudProfileOptions(
                provider="tencent",
                template="test-tpl",
                api_key="ark_key",
                timeout=600,
            ),
        )
        section = config.to_config_section()
        assert section["backend"] == "cloud"
        assert section["cloud"]["provider"] == "tencent"
        assert section["cloud"]["template"] == "test-tpl"
        assert section["cloud"]["api_key"] == "ark_key"
        assert section["cloud"]["timeout"] == 600

    def test_roundtrip(self):
        original = SandboxConfig(
            mode="all",
            backend="cloud",
            cloud=CloudProfileOptions(
                provider="tencent",
                template="tpl",
                domain="ap-guangzhou.tencentags.com",
                api_key="ark_round",
                timeout=999,
                allow_internet=False,
            ),
        )
        section = original.to_config_section()
        restored = SandboxConfig.from_config_section(section)
        assert restored.cloud.provider == "tencent"
        assert restored.cloud.template == "tpl"
        assert restored.cloud.api_key == "ark_round"
        assert restored.cloud.timeout == 999
        assert restored.cloud.allow_internet is False
