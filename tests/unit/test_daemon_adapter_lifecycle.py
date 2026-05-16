"""Unit tests for daemon adapter preflight and dynamic lifecycle.

Tests the has_credentials() method on each IM service and the preflight
logic in start_adapter(), stop_adapter(), and DaemonServiceStatus.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import MagicMock, patch


# ── has_credentials() tests ──────────────────────────────────────


class TestDingdingHasCredentials:
    """Test DingdingGatewayService.has_credentials()."""

    def test_no_configs_returns_false(self) -> None:
        from apps.gateway.dingding_service import DingdingGatewayService

        service = DingdingGatewayService.__new__(DingdingGatewayService)
        service.account_configs = ()
        service.environ = {}
        assert service.has_credentials() is False

    def test_missing_env_vars_returns_false(self) -> None:
        from apps.gateway.dingding_service import DingdingGatewayService
        from apps.gateway.dingding_support import DingdingGatewayAccountConfig

        service = DingdingGatewayService.__new__(DingdingGatewayService)
        service.account_configs = (DingdingGatewayAccountConfig(account_id="test"),)
        service.environ = {}
        assert service.has_credentials() is False

    def test_with_credentials_returns_true(self) -> None:
        from apps.gateway.dingding_service import DingdingGatewayService
        from apps.gateway.dingding_support import DingdingGatewayAccountConfig

        service = DingdingGatewayService.__new__(DingdingGatewayService)
        service.account_configs = (DingdingGatewayAccountConfig(account_id="test"),)
        service.environ = {
            "ELEPHANT_DINGDING_CLIENT_ID": "cid",
            "ELEPHANT_DINGDING_CLIENT_SECRET": "csecret",
        }
        assert service.has_credentials() is True


class TestDiscordHasCredentials:
    """Test DiscordGatewayService.has_credentials()."""

    def test_no_configs_returns_false(self) -> None:
        from apps.gateway.discord_service import DiscordGatewayService

        service = DiscordGatewayService.__new__(DiscordGatewayService)
        service.account_configs = ()
        service.environ = {}
        assert service.has_credentials() is False

    def test_missing_env_returns_false(self) -> None:
        from apps.gateway.discord_service import DiscordGatewayService
        from apps.gateway.discord_support import DiscordGatewayAccountConfig

        service = DiscordGatewayService.__new__(DiscordGatewayService)
        service.account_configs = (DiscordGatewayAccountConfig(account_id="test"),)
        service.environ = {}
        assert service.has_credentials() is False

    def test_with_token_returns_true(self) -> None:
        from apps.gateway.discord_service import DiscordGatewayService
        from apps.gateway.discord_support import DiscordGatewayAccountConfig

        service = DiscordGatewayService.__new__(DiscordGatewayService)
        service.account_configs = (DiscordGatewayAccountConfig(account_id="test"),)
        service.environ = {"ELEPHANT_DISCORD_BOT_TOKEN": "fake_token_123"}
        assert service.has_credentials() is True


class TestFeishuHasCredentials:
    """Test FeishuGatewayService.has_credentials()."""

    def test_no_configs_returns_false(self) -> None:
        from apps.gateway.feishu_impl import FeishuGatewayService

        service = FeishuGatewayService.__new__(FeishuGatewayService)
        service.account_configs = ()
        service.environ = {}
        assert service.has_credentials() is False

    def test_missing_env_returns_false(self) -> None:
        from apps.gateway.feishu_impl import FeishuGatewayService
        from apps.gateway.feishu_accounts import FeishuGatewayAccountConfig

        service = FeishuGatewayService.__new__(FeishuGatewayService)
        service.account_configs = (FeishuGatewayAccountConfig(account_id="test"),)
        service.environ = {}
        assert service.has_credentials() is False

    def test_with_credentials_returns_true(self) -> None:
        from apps.gateway.feishu_impl import FeishuGatewayService
        from apps.gateway.feishu_accounts import FeishuGatewayAccountConfig

        service = FeishuGatewayService.__new__(FeishuGatewayService)
        service.account_configs = (FeishuGatewayAccountConfig(account_id="test"),)
        service.environ = {
            "ELEPHANT_FEISHU_APP_ID": "cli_test",
            "ELEPHANT_FEISHU_APP_SECRET": "secret_test",
        }
        assert service.has_credentials() is True


class TestWecomHasCredentials:
    """Test WecomGatewayService.has_credentials()."""

    def test_no_configs_returns_false(self) -> None:
        from apps.gateway.wecom_service import WecomGatewayService

        service = WecomGatewayService.__new__(WecomGatewayService)
        service.account_configs = ()
        service.environ = {}
        assert service.has_credentials() is False

    def test_missing_env_returns_false(self) -> None:
        from apps.gateway.wecom_service import WecomGatewayService
        from apps.gateway.wecom_support import WecomGatewayAccountConfig

        service = WecomGatewayService.__new__(WecomGatewayService)
        service.account_configs = (WecomGatewayAccountConfig(account_id="test"),)
        service.environ = {}
        assert service.has_credentials() is False

    def test_with_credentials_returns_true(self) -> None:
        from apps.gateway.wecom_service import WecomGatewayService
        from apps.gateway.wecom_support import WecomGatewayAccountConfig

        service = WecomGatewayService.__new__(WecomGatewayService)
        service.account_configs = (WecomGatewayAccountConfig(account_id="test"),)
        service.environ = {
            "ELEPHANT_WECOM_BOT_ID": "bot123",
            "ELEPHANT_WECOM_SECRET": "secret123",
        }
        assert service.has_credentials() is True


class TestWeixinHasCredentials:
    """Test WeixinGatewayService.has_credentials() — special logic.

    WeixinGatewayService is a slotted dataclass, so _state_dir can't be
    monkey-patched. We set runtime_state_dir which _state_dir() reads from.
    """

    def test_no_configs_returns_false(self) -> None:
        from apps.gateway.weixin_service import WeixinGatewayService

        service = WeixinGatewayService.__new__(WeixinGatewayService)
        service.account_configs = ()
        service.runtime_state_dir = Path("/tmp")
        assert service.has_credentials() is False

    def test_default_account_no_token_returns_false(self) -> None:
        from apps.gateway.weixin_service import WeixinGatewayService
        from apps.gateway.weixin_support import WeixinGatewayAccountConfig

        service = WeixinGatewayService.__new__(WeixinGatewayService)
        service.account_configs = (WeixinGatewayAccountConfig(account_id="default", token=""),)
        service.runtime_state_dir = Path("/tmp")
        with patch("apps.gateway.weixin_service.load_weixin_account", return_value=None):
            assert service.has_credentials() is False

    def test_with_token_and_real_account_id_returns_true(self) -> None:
        from apps.gateway.weixin_service import WeixinGatewayService
        from apps.gateway.weixin_support import WeixinGatewayAccountConfig

        service = WeixinGatewayService.__new__(WeixinGatewayService)
        service.account_configs = (
            WeixinGatewayAccountConfig(account_id="wx_real_account", token="some_token"),
        )
        service.runtime_state_dir = Path("/tmp")
        assert service.has_credentials() is True

    def test_saved_token_in_local_storage_returns_true(self) -> None:
        from apps.gateway.weixin_service import WeixinGatewayService
        from apps.gateway.weixin_support import WeixinGatewayAccountConfig

        service = WeixinGatewayService.__new__(WeixinGatewayService)
        service.account_configs = (
            WeixinGatewayAccountConfig(account_id="wx_account", token=""),
        )
        service.runtime_state_dir = Path("/tmp")
        with patch(
            "apps.gateway.weixin_service.load_weixin_account",
            return_value={"token": "saved_token"},
        ):
            assert service.has_credentials() is True


class TestTelegramHasCredentials:
    """Test TelegramGatewayService.has_credentials()."""

    def test_no_configs_returns_false(self) -> None:
        from apps.gateway.telegram import TelegramGatewayService

        service = TelegramGatewayService.__new__(TelegramGatewayService)
        service.account_configs = ()
        service.environ = {}
        assert service.has_credentials() is False

    def test_missing_env_returns_false(self) -> None:
        from apps.gateway.telegram import TelegramGatewayService
        from apps.gateway.telegram import TelegramGatewayAccountConfig

        service = TelegramGatewayService.__new__(TelegramGatewayService)
        service.account_configs = (TelegramGatewayAccountConfig(account_id="test"),)
        service.environ = {}
        assert service.has_credentials() is False

    def test_with_token_returns_true(self) -> None:
        from apps.gateway.telegram import TelegramGatewayService
        from apps.gateway.telegram import TelegramGatewayAccountConfig

        service = TelegramGatewayService.__new__(TelegramGatewayService)
        service.account_configs = (TelegramGatewayAccountConfig(account_id="test"),)
        service.environ = {"ELEPHANT_TELEGRAM_BOT_TOKEN": "123456:ABC"}
        assert service.has_credentials() is True


# ── ServiceDaemon preflight & lifecycle tests ────────────────────


class TestDaemonServiceStatus:
    """Test DaemonServiceStatus supports skipped state."""

    def test_skipped_status(self) -> None:
        from apps.daemon import DaemonServiceStatus

        status = DaemonServiceStatus(name="test", status="skipped", last_error="no credentials")
        assert status.status == "skipped"
        assert status.last_error == "no credentials"

    def test_all_valid_status_values(self) -> None:
        from apps.daemon import DaemonServiceStatus

        for valid_status in ("idle", "running", "failed", "stopped", "skipped"):
            s = DaemonServiceStatus(name="test", status=valid_status)
            assert s.status == valid_status


class TestDaemonStartAdapter:
    """Test ServiceDaemon.start_adapter() logic."""

    def test_start_adapter_no_gateway(self) -> None:
        from apps.daemon import ServiceDaemon

        async def _run():
            daemon = ServiceDaemon(
                state_dir=Path("/tmp/test-daemon"),
                cli_state_dir=Path("/tmp/test-cli"),
            )
            daemon._gateway_app = None
            result = await daemon.start_adapter("discord")
            assert result["status"] == "error"
            assert "gateway not initialized" in result["reason"]

        asyncio.run(_run())

    def test_start_adapter_already_running(self) -> None:
        from apps.daemon import ServiceDaemon, DaemonServiceStatus

        async def _run():
            daemon = ServiceDaemon(
                state_dir=Path("/tmp/test-daemon"),
                cli_state_dir=Path("/tmp/test-cli"),
            )
            daemon._service_statuses["discord"] = DaemonServiceStatus(
                name="discord", status="running"
            )
            result = await daemon.start_adapter("discord")
            assert result["status"] == "already_running"

        asyncio.run(_run())


class TestDaemonStopAdapter:
    """Test ServiceDaemon.stop_adapter() logic."""

    def test_stop_adapter_not_running(self) -> None:
        from apps.daemon import ServiceDaemon

        async def _run():
            daemon = ServiceDaemon(
                state_dir=Path("/tmp/test-daemon"),
                cli_state_dir=Path("/tmp/test-cli"),
            )
            result = await daemon.stop_adapter("discord")
            assert result["status"] == "not_running"

        asyncio.run(_run())

    def test_stop_adapter_skipped_is_not_running(self) -> None:
        from apps.daemon import ServiceDaemon, DaemonServiceStatus

        async def _run():
            daemon = ServiceDaemon(
                state_dir=Path("/tmp/test-daemon"),
                cli_state_dir=Path("/tmp/test-cli"),
            )
            daemon._service_statuses["discord"] = DaemonServiceStatus(
                name="discord", status="skipped"
            )
            result = await daemon.stop_adapter("discord")
            assert result["status"] == "not_running"

        asyncio.run(_run())


# ── DaemonService protocol test ──────────────────────────────────


class TestDaemonServiceProtocol:
    """Test that DaemonService protocol includes has_credentials."""

    def test_protocol_defines_has_credentials(self) -> None:
        from apps.gateway.plugins import DaemonService
        import inspect

        # DaemonService is a Protocol; check that has_credentials is in its members
        members = dict(inspect.getmembers(DaemonService))
        assert "has_credentials" in members
