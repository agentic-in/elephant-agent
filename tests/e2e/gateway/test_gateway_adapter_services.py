from __future__ import annotations

import json
import unittest

from apps.gateway import (
    DEFAULT_FEISHU_APP_ID_ENV,
    DEFAULT_FEISHU_APP_SECRET_ENV,
    DEFAULT_TELEGRAM_BOT_TOKEN_ENV,
    FeishuGatewayService,
    TelegramGatewayService,
    create_gateway_web_app,
    load_telegram_gateway_accounts,
)
from tests.e2e.gateway.gateway_adapter_test_base import GatewayAdapterTestBase


class GatewayAdapterServicesE2ETests(GatewayAdapterTestBase):
    def test_telegram_gateway_service_uses_manifest_account_and_dispatches_reply(
        self,
    ) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"].update(
                {
                    "telegram": {
                        "enabled": True,
                        "event_path": "/hooks/telegram",
                        "accounts": [
                            {
                                "account_id": "ops-telegram",
                                "env": {
                                    "bot_token": "ELEPHANT_TEST_TELEGRAM_BOT_TOKEN",
                                },
                            }
                        ],
                    }
                }
            )
        )
        app, _, _ = self._build()
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            requests.append((method, url, payload, headers))
            self.assertEqual(method, "POST")
            self.assertTrue(url.endswith("/bottelegram-token/sendMessage"))
            self.assertEqual(payload["chat_id"], "77")
            self.assertEqual(payload["reply_to_message_id"], "301")
            return {
                "ok": True,
                "result": {"message_id": 999},
            }

        service = TelegramGatewayService(
            app=app,
            http_requester=fake_request,
            environ={
                DEFAULT_TELEGRAM_BOT_TOKEN_ENV: "",
                "ELEPHANT_TEST_TELEGRAM_BOT_TOKEN": "telegram-token",
            },
        )

        accounts = load_telegram_gateway_accounts(app)
        self.assertEqual(accounts[0].account_id, "ops-telegram")
        self.assertEqual(accounts[0].event_path, "/hooks/telegram")
        self.assertEqual(accounts[0].surface, "webhook")

        result = service.dispatch_update(
            {
                "update_id": 3001,
                "message": {
                    "message_id": 301,
                    "chat": {"id": 77, "type": "private"},
                    "from": {"id": 12, "username": "telegram_ada"},
                    "text": "hello from telegram service",
                },
            },
            path="/hooks/telegram",
        )

        self.assertIsNotNone(result.exchange)
        self.assertEqual(result.response_body["account_id"], "ops-telegram")
        self.assertEqual(result.response_body["delivery_outcome"], "delivered")
        self.assertEqual(result.response_body["external_message_id"], "999")
        assert result.delivery_request is not None
        self.assertEqual(result.delivery_request["path_label"], "/sendMessage")
        self.assertEqual(len(requests), 1)

    def test_gateway_web_app_can_mount_feishu_and_telegram_services(self) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"].update(
                {
                    "telegram": {
                        "enabled": True,
                        "event_path": "/hooks/telegram",
                        "accounts": [
                            {
                                "account_id": "ops-telegram",
                                "env": {
                                    "bot_token": "ELEPHANT_TEST_TELEGRAM_BOT_TOKEN",
                                },
                            }
                        ],
                    }
                }
            )
        )
        app, _, _ = self._build()
        feishu_requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []
        telegram_requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []

        def fake_feishu_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            feishu_requests.append((method, url, payload, headers))
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                return {
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                }
            return {
                "code": 0,
                "msg": "ok",
                "data": {"message_id": "om_reply_multi_1"},
            }

        def fake_telegram_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            telegram_requests.append((method, url, payload, headers))
            self.assertTrue(url.endswith("/bottelegram-token/sendMessage"))
            return {
                "ok": True,
                "result": {"message_id": 1001},
            }

        feishu_service = FeishuGatewayService(
            app=app,
            http_requester=fake_feishu_request,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
        )
        telegram_service = TelegramGatewayService(
            app=app,
            http_requester=fake_telegram_request,
            environ={
                DEFAULT_TELEGRAM_BOT_TOKEN_ENV: "",
                "ELEPHANT_TEST_TELEGRAM_BOT_TOKEN": "telegram-token",
            },
        )
        web_app = create_gateway_web_app(
            {
                "feishu": feishu_service,
                "telegram": telegram_service,
            },
            app=app,
        )

        health_status, health_body = self._call_wsgi(
            web_app,
            method="GET",
            path="/healthz",
        )
        self.assertEqual(health_status, "200 OK")
        self.assertIn("feishu", health_body["services"])
        self.assertIn("telegram", health_body["services"])

        feishu_status, feishu_body = self._call_wsgi(
            web_app,
            method="POST",
            path="/hooks/feishu",
            payload={
                "schema": "2.0",
                "header": {
                    "event_id": "evt-web-multi-feishu",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_web_multi"},
                        "sender_type": "user",
                        "name": "Webhook Ada",
                    },
                    "message": {
                        "message_id": "om_web_multi_1",
                        "chat_id": "oc_web_multi_1",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "hello from multi feishu"}),
                    },
                },
            },
        )
        self.assertEqual(feishu_status, "200 OK")
        self.assertEqual(feishu_body["delivery_outcome"], "delivered")

        telegram_status, telegram_body = self._call_wsgi(
            web_app,
            method="POST",
            path="/hooks/telegram",
            payload={
                "update_id": 9100,
                "message": {
                    "message_id": 91,
                    "chat": {"id": 88, "type": "private"},
                    "from": {"id": 11, "username": "multi_ada"},
                    "text": "hello from multi telegram",
                },
            },
        )
        self.assertEqual(telegram_status, "200 OK")
        self.assertEqual(telegram_body["delivery_outcome"], "delivered")
        self.assertEqual(telegram_body["delivery_request_path"], "/sendMessage")
        self.assertEqual(len(feishu_requests), 2)
        self.assertEqual(len(telegram_requests), 1)


if __name__ == "__main__":
    unittest.main()
