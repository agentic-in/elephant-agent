from __future__ import annotations

from datetime import UTC, datetime
import json
from types import SimpleNamespace
import unittest

from apps.gateway import (
    DEFAULT_FEISHU_APP_ID_ENV,
    DEFAULT_FEISHU_APP_SECRET_ENV,
    FEISHU_ADAPTER_ID,
    FeishuGatewayService,
    create_gateway_web_app,
    load_feishu_gateway_accounts,
)
from packages.contracts.layers import Episode
from tests.e2e.gateway.gateway_adapter_test_base import GatewayAdapterTestBase


class GatewayAdapterFeishuRuntimeE2ETests(GatewayAdapterTestBase):
    def test_feishu_gateway_service_uses_manifest_account_and_dispatches_reply(self) -> None:
        app, _, _ = self._build()
        shared_runtime_calls = self._install_shared_runtime_stub(app)
        expected_session_id = self._gateway_route_session_id(
            adapter_id=FEISHU_ADAPTER_ID,
            account_id="ops-feishu",
            conversation_id="oc_direct_service",
        )
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            requests.append((method, url, payload, headers))
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                self.assertEqual(payload["app_id"], "cli_feishu_bot")
                self.assertEqual(payload["app_secret"], "super-secret")
                return {
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                }
            self.assertTrue(
                url.endswith("/open-apis/im/v1/messages/om_service_bind/reply")
                or url.endswith("/open-apis/im/v1/messages/om_service_1/reply")
            )
            self.assertEqual(headers["Authorization"], "Bearer tenant-token")
            return {
                "code": 0,
                "msg": "ok",
                "data": {
                    "message_id": (
                        "om_reply_bind"
                        if url.endswith("/open-apis/im/v1/messages/om_service_bind/reply")
                        else "om_reply_1"
                    )
                },
            }

        class FakeCliRuntime:
            def __init__(self) -> None:
                now = datetime.now(UTC)
                self.demo_session = Episode(
                    episode_id="session-demo",
                    state_id="state:test",
                    personal_model_id="elephant:demo",
                    entry_surface="test",
                    elephant_id="demo",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )
                self.explain_calls: list[dict[str, object]] = []

            def list_herd(self, *, limit: int = 12) -> tuple[object, ...]:
                return (
                    SimpleNamespace(
                        elephant_id="demo",
                        latest_session_id=self.demo_session.episode_id,
                        latest_status=self.demo_session.status,
                        updated_at=self.demo_session.updated_at,
                        session_count=1,
                    ),
                )[:limit]

            def latest_session_for_elephant(self, elephant_id: str) -> Episode | None:
                return self.demo_session if elephant_id == "demo" else None

            def create_elephant(self, **kwargs) -> Episode:
                raise AssertionError("auto create should not be used in this test")

            def inspect_session(self, session_id: str) -> Episode:
                if session_id != self.demo_session.episode_id:
                    raise KeyError(session_id)
                return self.demo_session

            def prepare_session_surface(self, session_id: str) -> Episode:
                return self.inspect_session(session_id)

            def explain_next_step(self, **kwargs):
                self.explain_calls.append(dict(kwargs))
                prompt = str(kwargs["prompt"])
                return SimpleNamespace(execution=SimpleNamespace(summary=f"cli-handled:{prompt}"))

            def wake(self, session_id: str, *, inspect_only: bool = False):
                raise AssertionError("wake should not be used in this test")

        fake_runtime = FakeCliRuntime()
        service = FeishuGatewayService(
            app=app,
            http_requester=fake_request,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
            cli_runtime_factory=lambda profile_dir, state_dir: fake_runtime,
            default_cli_state_dir=str(self.state_dir),
        )

        accounts = load_feishu_gateway_accounts(app)
        self.assertEqual(accounts[0].account_id, "ops-feishu")
        self.assertEqual(accounts[0].event_path, "/hooks/feishu")
        self.assertEqual(accounts[0].surface, "long-connection")

        bind_result = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-service-bind",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                    "tenant_key": "tenant-alpha",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_service"},
                        "sender_type": "user",
                        "name": "Service Ada",
                    },
                    "message": {
                        "message_id": "om_service_bind",
                        "chat_id": "oc_direct_service",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "/elephant create demo"}),
                    },
                },
            }
        )

        self.assertEqual(bind_result.response_body["elephant_id"], "demo")
        self.assertEqual(bind_result.response_body["session_id"], expected_session_id)

        result = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-service-1",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                    "tenant_key": "tenant-alpha",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_service"},
                        "sender_type": "user",
                        "name": "Service Ada",
                    },
                    "message": {
                        "message_id": "om_service_1",
                        "chat_id": "oc_direct_service",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "hello from webhook"}),
                    },
                },
            }
        )

        self.assertIsNotNone(result.exchange)
        self.assertEqual(result.response_body["elephant_id"], "demo")
        self.assertEqual(result.response_body["state_id"], "state:demo")
        self.assertEqual(result.response_body["session_id"], expected_session_id)
        self.assertEqual(result.response_body["delivery_outcome"], "delivered")
        self.assertEqual(result.response_body["external_message_id"], "om_reply_1")
        self.assertEqual(
            shared_runtime_calls,
            [
                {
                    "session_id": expected_session_id,
                    "prompt": "hello from webhook",
                    "conversation_id": "oc_direct_service",
                }
            ],
        )
        self.assertEqual(len(requests), 3)

    def test_feishu_gateway_service_supports_account_secret_references(self) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"]["feishu"].update(
                {
                    "accounts": [
                        {
                            "account_id": "ops-feishu",
                            "secret_references": [
                                {
                                    "reference_id": "secret-feishu-app-id",
                                    "secret_key": "app_id",
                                    "metadata": {"env_var": "ELEPHANT_TEST_FEISHU_APP_ID"},
                                },
                                {
                                    "reference_id": "secret-feishu-app-secret",
                                    "secret_key": "app_secret",
                                    "metadata": {"env_var": "ELEPHANT_TEST_FEISHU_APP_SECRET"},
                                },
                            ],
                        }
                    ]
                }
            )
        )
        app, _, _ = self._build()
        shared_runtime_calls = self._install_shared_runtime_stub(app)
        expected_session_id = self._gateway_route_session_id(
            adapter_id=FEISHU_ADAPTER_ID,
            account_id="ops-feishu",
            conversation_id="oc_direct_service",
        )
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            requests.append((method, url, payload, headers))
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                self.assertEqual(payload["app_id"], "cli_feishu_bot")
                self.assertEqual(payload["app_secret"], "super-secret")
                return {
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                }
            self.assertTrue(
                url.endswith("/open-apis/im/v1/messages/om_service_secret_ref_bind/reply")
                or url.endswith("/open-apis/im/v1/messages/om_service_secret_ref/reply")
            )
            self.assertEqual(headers["Authorization"], "Bearer tenant-token")
            return {
                "code": 0,
                "msg": "ok",
                "data": {
                    "message_id": (
                        "om_reply_secret_ref_bind"
                        if url.endswith("/open-apis/im/v1/messages/om_service_secret_ref_bind/reply")
                        else "om_reply_secret_ref"
                    )
                },
            }

        class FakeCliRuntime:
            def __init__(self) -> None:
                now = datetime.now(UTC)
                self.demo_session = Episode(
                    episode_id="session-demo",
                    state_id="state:test",
                    personal_model_id="elephant:demo",
                    entry_surface="test",
                    elephant_id="demo",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )
                self.explain_calls: list[dict[str, object]] = []

            def list_herd(self, *, limit: int = 12) -> tuple[object, ...]:
                return (
                    SimpleNamespace(
                        elephant_id="demo",
                        latest_session_id=self.demo_session.episode_id,
                        latest_status=self.demo_session.status,
                        updated_at=self.demo_session.updated_at,
                        session_count=1,
                    ),
                )[:limit]

            def latest_session_for_elephant(self, elephant_id: str) -> Episode | None:
                return self.demo_session if elephant_id == "demo" else None

            def create_elephant(self, **kwargs) -> Episode:
                raise AssertionError("auto create should not be used in this test")

            def inspect_session(self, session_id: str) -> Episode:
                if session_id != self.demo_session.episode_id:
                    raise KeyError(session_id)
                return self.demo_session

            def prepare_session_surface(self, session_id: str) -> Episode:
                return self.inspect_session(session_id)

            def explain_next_step(self, **kwargs):
                self.explain_calls.append(dict(kwargs))
                prompt = str(kwargs["prompt"])
                return SimpleNamespace(execution=SimpleNamespace(summary=f"cli-handled:{prompt}"))

            def wake(self, session_id: str, *, inspect_only: bool = False):
                raise AssertionError("wake should not be used in this test")

        fake_runtime = FakeCliRuntime()
        service = FeishuGatewayService(
            app=app,
            http_requester=fake_request,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
            cli_runtime_factory=lambda profile_dir, state_dir: fake_runtime,
            default_cli_state_dir=str(self.state_dir),
        )

        accounts = load_feishu_gateway_accounts(app)
        self.assertEqual(accounts[0].account_id, "ops-feishu")
        self.assertEqual(accounts[0].app_id_env_var, "ELEPHANT_TEST_FEISHU_APP_ID")
        self.assertEqual(accounts[0].app_secret_env_var, "ELEPHANT_TEST_FEISHU_APP_SECRET")
        self.assertEqual(
            tuple(reference.reference_id for reference in accounts[0].secret_references),
            ("secret-feishu-app-id", "secret-feishu-app-secret"),
        )

        description = service.describe()
        self.assertEqual(description["accounts"][0]["credentials_source"], "secret_references")
        self.assertEqual(
            description["accounts"][0]["secret_reference_ids"],
            ("secret-feishu-app-id", "secret-feishu-app-secret"),
        )
        self.assertEqual(
            description["accounts"][0]["credential_env_vars"],
            ("ELEPHANT_TEST_FEISHU_APP_ID", "ELEPHANT_TEST_FEISHU_APP_SECRET"),
        )

        bind_result = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-service-secret-ref-bind",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                    "tenant_key": "tenant-alpha",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_service"},
                        "sender_type": "user",
                        "name": "Service Ada",
                    },
                    "message": {
                        "message_id": "om_service_secret_ref_bind",
                        "chat_id": "oc_direct_service",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "/elephant create demo"}),
                    },
                },
            }
        )

        self.assertEqual(bind_result.response_body["elephant_id"], "demo")
        self.assertEqual(bind_result.response_body["session_id"], expected_session_id)

        result = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-service-secret-ref",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                    "tenant_key": "tenant-alpha",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_service"},
                        "sender_type": "user",
                        "name": "Service Ada",
                    },
                    "message": {
                        "message_id": "om_service_secret_ref",
                        "chat_id": "oc_direct_service",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "hello from secret refs"}),
                    },
                },
            }
        )

        self.assertIsNotNone(result.exchange)
        self.assertEqual(result.response_body["elephant_id"], "demo")
        self.assertEqual(result.response_body["state_id"], "state:demo")
        self.assertEqual(result.response_body["session_id"], expected_session_id)
        self.assertEqual(result.response_body["external_message_id"], "om_reply_secret_ref")
        self.assertEqual(
            shared_runtime_calls,
            [
                {
                    "session_id": expected_session_id,
                    "prompt": "hello from secret refs",
                    "conversation_id": "oc_direct_service",
                }
            ],
        )
        self.assertEqual(len(requests), 3)

    def test_feishu_gateway_service_can_ignore_disabled_flag_when_requested(self) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"]["feishu"].update({"enabled": False})
        )
        app, _, _ = self._build()

        self.assertEqual(load_feishu_gateway_accounts(app), ())

        forced_accounts = load_feishu_gateway_accounts(app, respect_enabled=False)
        self.assertEqual(len(forced_accounts), 1)
        self.assertEqual(forced_accounts[0].account_id, "ops-feishu")

        service = FeishuGatewayService(
            app=app,
            environ={
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
            respect_enabled=False,
        )
        description = service.describe()
        self.assertEqual(description["accounts"][0]["account_id"], "ops-feishu")
        self.assertEqual(description["accounts"][0]["credentials_status"], "configured")

    def test_feishu_gateway_service_routes_replies_back_to_matched_account(self) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"]["feishu"].update(
                {
                    "accounts": [
                        {
                            "account_id": "ops-feishu",
                            "event_path": "/hooks/feishu",
                            "env": {
                                "app_id": "ELEPHANT_TEST_FEISHU_APP_ID",
                                "app_secret": "ELEPHANT_TEST_FEISHU_APP_SECRET",
                            },
                        },
                        {
                            "account_id": "support-feishu",
                            "event_path": "/hooks/feishu",
                            "env": {
                                "app_id": "ELEPHANT_TEST_FEISHU_SUPPORT_APP_ID",
                                "app_secret": "ELEPHANT_TEST_FEISHU_SUPPORT_APP_SECRET",
                            },
                        },
                    ]
                }
            )
        )
        app, _, _ = self._build()
        shared_runtime_calls = self._install_shared_runtime_stub(app)
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []

        class FakeCliRuntime:
            def __init__(self) -> None:
                now = datetime.now(UTC)
                self.demo_session = Episode(
                    episode_id="session-demo",
                    state_id="state:test",
                    personal_model_id="elephant:demo",
                    entry_surface="test",
                    elephant_id="demo",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )
                self.explain_calls: list[dict[str, object]] = []

            def list_herd(self, *, limit: int = 12):
                return (SimpleNamespace(elephant_id="demo"),)[:limit]

            def latest_session_for_elephant(self, elephant_id: str) -> Episode | None:
                return self.demo_session if elephant_id == "demo" else None

            def create_elephant(self, **kwargs):
                raise AssertionError("auto create should not be used in this test")

            def inspect_session(self, session_id: str) -> Episode:
                if session_id != self.demo_session.episode_id:
                    raise KeyError(session_id)
                return self.demo_session

            def prepare_session_surface(self, session_id: str) -> Episode:
                return self.inspect_session(session_id)

            def explain_next_step(self, **kwargs):
                self.explain_calls.append(dict(kwargs))
                prompt = str(kwargs["prompt"])
                return SimpleNamespace(execution=SimpleNamespace(summary=f"cli-handled:{prompt}"))

            def wake(self, session_id: str, *, inspect_only: bool = False):
                raise AssertionError("wake should not be used in this test")

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            requests.append((method, url, payload, headers))
            if url.endswith("/open-apis/auth/v3/tenant_access_token/internal"):
                app_id = str(payload["app_id"])
                if app_id == "cli_feishu_bot":
                    self.assertEqual(payload["app_secret"], "super-secret")
                    return {
                        "code": 0,
                        "msg": "ok",
                        "tenant_access_token": "tenant-token-ops",
                        "expire": 7200,
                    }
                self.assertEqual(app_id, "support_feishu_bot")
                self.assertEqual(payload["app_secret"], "support-secret")
                return {
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": "tenant-token-support",
                    "expire": 7200,
                }
            auth = headers.get("Authorization")
            self.assertIn(auth, {"Bearer tenant-token-ops", "Bearer tenant-token-support"})
            return {
                "code": 0,
                "msg": "ok",
                "data": {
                    "message_id": (
                        "om_reply_ops"
                        if auth == "Bearer tenant-token-ops"
                        else "om_reply_support"
                    )
                },
            }

        fake_runtime = FakeCliRuntime()
        service = FeishuGatewayService(
            app=app,
            http_requester=fake_request,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
                "ELEPHANT_TEST_FEISHU_SUPPORT_APP_ID": "support_feishu_bot",
                "ELEPHANT_TEST_FEISHU_SUPPORT_APP_SECRET": "support-secret",
            },
            cli_runtime_factory=lambda profile_dir, state_dir: fake_runtime,
            default_cli_state_dir=str(self.state_dir),
        )
        self._bind_cli_control_conversation(
            service,
            account_id="ops-feishu",
            conversation_id="oc_service_ops",
            elephant_id="demo",
            session_id=fake_runtime.demo_session.episode_id,
        )
        self._bind_cli_control_conversation(
            service,
            account_id="support-feishu",
            conversation_id="oc_service_support",
            elephant_id="demo",
            session_id=fake_runtime.demo_session.episode_id,
        )

        ops_result = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-service-ops",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                    "tenant_key": "tenant-ops",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_ops"},
                        "sender_type": "user",
                        "name": "Ops Ada",
                    },
                    "message": {
                        "message_id": "om_service_ops",
                        "chat_id": "oc_service_ops",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "hello from ops"}),
                    },
                },
            }
        )
        support_result = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-service-support",
                    "event_type": "im.message.receive_v1",
                    "app_id": "support_feishu_bot",
                    "tenant_key": "tenant-support",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_support"},
                        "sender_type": "user",
                        "name": "Support Ada",
                    },
                    "message": {
                        "message_id": "om_service_support",
                        "chat_id": "oc_service_support",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "hello from support"}),
                    },
                },
            }
        )

        self.assertEqual(ops_result.response_body["account_id"], "ops-feishu")
        self.assertEqual(ops_result.response_body["external_message_id"], "om_reply_ops")
        self.assertEqual(support_result.response_body["account_id"], "support-feishu")
        self.assertEqual(support_result.response_body["external_message_id"], "om_reply_support")
        self.assertEqual(
            [call["prompt"] for call in shared_runtime_calls],
            ["hello from ops", "hello from support"],
        )
        self.assertEqual(len(requests), 4)
        self.assertEqual(requests[0][2]["app_id"], "cli_feishu_bot")
        self.assertEqual(requests[1][3]["Authorization"], "Bearer tenant-token-ops")
        self.assertEqual(requests[2][2]["app_id"], "support_feishu_bot")
        self.assertEqual(requests[3][3]["Authorization"], "Bearer tenant-token-support")

    def test_feishu_gateway_web_app_handles_challenge_and_event_delivery(self) -> None:
        app, _, _ = self._build()
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            requests.append((method, url, payload, headers))
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
                "data": {"message_id": "om_reply_web_1"},
            }

        service = FeishuGatewayService(
            app=app,
            http_requester=fake_request,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
        )
        web_app = create_gateway_web_app(service)

        challenge_status, challenge_body = self._call_wsgi(
            web_app,
            method="POST",
            path="/hooks/feishu",
            payload={"challenge": "verify-me"},
        )
        self.assertEqual(challenge_status, "200 OK")
        self.assertEqual(challenge_body["challenge"], "verify-me")

        event_status, event_body = self._call_wsgi(
            web_app,
            method="POST",
            path="/hooks/feishu",
            payload={
                "schema": "2.0",
                "header": {
                    "event_id": "evt-web-1",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_web"},
                        "sender_type": "user",
                        "name": "Webhook Ada",
                    },
                    "message": {
                        "message_id": "om_web_1",
                        "chat_id": "oc_web_1",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "hello from http"}),
                    },
                },
            },
        )
        self.assertEqual(event_status, "200 OK")
        self.assertEqual(event_body["delivery_outcome"], "delivered")
        self.assertEqual(event_body["delivery_request_path"], "/open-apis/im/v1/messages/om_web_1/reply")
        self.assertEqual(len(requests), 2)

    def test_feishu_gateway_service_dedupes_duplicate_shared_runtime_events(self) -> None:
        app, _, _ = self._build()
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
            requests.append((method, url, payload, headers))
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
                "data": {"message_id": "om_reply_dedupe_1"},
            }

        service = FeishuGatewayService(
            app=app,
            http_requester=fake_request,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
        )
        payload = {
            "schema": "2.0",
            "header": {
                "event_id": "evt-dedupe-runtime-1",
                "event_type": "im.message.receive_v1",
                "app_id": "cli_feishu_bot",
            },
            "event": {
                "sender": {
                    "sender_id": {"open_id": "ou_runtime_dedupe"},
                    "sender_type": "user",
                    "name": "Runtime Ada",
                },
                "message": {
                    "message_id": "om_runtime_dedupe_1",
                    "chat_id": "oc_runtime_dedupe_1",
                    "chat_type": "p2p",
                    "message_type": "text",
                    "content": json.dumps({"text": "hello from duplicate runtime"}),
                },
            },
        }

        first = service.dispatch_event(payload, transport="long-connection")
        duplicate = service.dispatch_event(payload, transport="long-connection")

        self.assertEqual(first.response_body["delivery_outcome"], "delivered")
        self.assertEqual(first.response_body["external_message_id"], "om_reply_dedupe_1")
        self.assertEqual(duplicate.response_body["delivery_outcome"], "deduplicated")
        self.assertTrue(duplicate.response_body["duplicate_event"])
        self.assertEqual(duplicate.response_body["duplicate_handling"], "replayed-no-delivery")
        self.assertEqual(duplicate.response_body["initial_delivery_outcome"], "delivered")
        self.assertEqual(duplicate.response_body["external_message_id"], "om_reply_dedupe_1")
        self.assertEqual(len(requests), 2)


if __name__ == "__main__":
    unittest.main()
