from __future__ import annotations

from datetime import UTC, datetime
import json
from types import SimpleNamespace
import threading
import time
import unittest
from unittest import mock

from apps.gateway import (
    DEFAULT_FEISHU_APP_ID_ENV,
    DEFAULT_FEISHU_APP_SECRET_ENV,
    FEISHU_ADAPTER_ID,
    FeishuGatewayService,
)
from packages.contracts.layers import Episode
from tests.e2e.gateway.gateway_adapter_test_base import GatewayAdapterTestBase


class GatewayAdapterFeishuLongConnectionE2ETests(GatewayAdapterTestBase):
    def test_feishu_gateway_service_starts_python_sdk_long_connection(self) -> None:
        app, _, _ = self._build()
        shared_runtime_calls = self._install_shared_runtime_stub(app)
        expected_session_id = self._gateway_route_session_id(
            adapter_id=FEISHU_ADAPTER_ID,
            account_id="ops-feishu",
            conversation_id="oc_ws_1",
        )
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []
        captured: dict[str, object] = {}

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
                "data": {"message_id": "om_reply_ws_1"},
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

        class FakeSDKEvent:
            def __init__(self, payload: dict[str, object]) -> None:
                self.payload = payload

        class FakeEventHandler:
            def __init__(self, callback) -> None:
                self.message_handler = callback

        class FakeEventDispatcherBuilder:
            def __init__(self) -> None:
                self.callback = None

            def register_p2_im_message_receive_v1(self, callback):
                self.callback = callback
                return self

            def build(self):
                assert self.callback is not None
                return FakeEventHandler(self.callback)

        class FakeEventDispatcherHandler:
            @staticmethod
            def builder(encrypt_key: str, verification_token: str, level=None):
                captured["builder"] = {
                    "encrypt_key": encrypt_key,
                    "verification_token": verification_token,
                    "log_level": level,
                }
                return FakeEventDispatcherBuilder()

        class FakeJSON:
            @staticmethod
            def marshal(event: FakeSDKEvent) -> str:
                return json.dumps(event.payload)

        class FakeLogLevel:
            INFO = "INFO"

        class FakeWSClient:
            def __init__(self, app_id: str, app_secret: str, *, event_handler, log_level=None) -> None:
                captured["client"] = {
                    "app_id": app_id,
                    "app_secret": app_secret,
                    "log_level": log_level,
                }
                self.event_handler = event_handler

            def start(self) -> None:
                self.event_handler.message_handler(
                    FakeSDKEvent(
                        {
                            "schema": "2.0",
                            "header": {
                                "event_id": "evt-ws-1",
                                "event_type": "im.message.receive_v1",
                                "app_id": "cli_feishu_bot",
                                "tenant_key": "tenant-alpha",
                            },
                            "event": {
                                "sender": {
                                    "sender_id": {"open_id": "ou_ws"},
                                    "sender_type": "user",
                                    "name": "WS Ada",
                                },
                                "message": {
                                    "message_id": "om_ws_1",
                                    "chat_id": "oc_ws_1",
                                    "chat_type": "p2p",
                                    "message_type": "text",
                                    "content": json.dumps({"text": "hello from ws"}),
                                },
                            },
                        }
                    )
                )

        class FakeWS:
            Client = FakeWSClient

        class FakeLark:
            EventDispatcherHandler = FakeEventDispatcherHandler
            JSON = FakeJSON
            LogLevel = FakeLogLevel
            ws = FakeWS

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
        self._bind_cli_control_conversation(
            service,
            account_id="ops-feishu",
            conversation_id="oc_ws_1",
            elephant_id="demo",
            session_id=fake_runtime.demo_session.episode_id,
        )

        description = service.describe()
        self.assertEqual(description["implemented_transports"][0], "python-sdk-long-connection")
        self.assertEqual(description["control"]["runtime_status"], "ready")

        try:
            service.start_long_connection(account_id="ops-feishu", lark_module=FakeLark())

            self.assertEqual(captured["client"]["app_id"], "cli_feishu_bot")
            self.assertEqual(captured["client"]["app_secret"], "super-secret")
            self.assertEqual(captured["client"]["log_level"], "INFO")
            self._wait_until(
                lambda: len(shared_runtime_calls) == 1,
                message="expected async long-connection job to reach shared gateway runtime",
            )
            self._wait_until(
                lambda: len(requests) == 3,
                message="expected placeholder and final Feishu replies",
            )
            self.assertEqual(shared_runtime_calls[0]["session_id"], expected_session_id)
            self.assertEqual(shared_runtime_calls[0]["prompt"], "hello from ws")
        finally:
            service.shutdown_async_processing()

    def test_feishu_gateway_service_dedupes_duplicate_long_connection_control_events(self) -> None:
        app, _, _ = self._build()
        shared_runtime_calls = self._install_shared_runtime_stub(app)
        expected_session_id = self._gateway_route_session_id(
            adapter_id=FEISHU_ADAPTER_ID,
            account_id="ops-feishu",
            conversation_id="oc_ws_dedupe_1",
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
                return {
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                }
            return {
                "code": 0,
                "msg": "ok",
                "data": {"message_id": "om_reply_ws_dedupe_1"},
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

        class FakeSDKEvent:
            def __init__(self, payload: dict[str, object]) -> None:
                self.payload = payload

        class FakeEventHandler:
            def __init__(self, callback) -> None:
                self.message_handler = callback

        class FakeEventDispatcherBuilder:
            def __init__(self) -> None:
                self.callback = None

            def register_p2_im_message_receive_v1(self, callback):
                self.callback = callback
                return self

            def build(self):
                assert self.callback is not None
                return FakeEventHandler(self.callback)

        class FakeEventDispatcherHandler:
            @staticmethod
            def builder(encrypt_key: str, verification_token: str, level=None):
                return FakeEventDispatcherBuilder()

        class FakeJSON:
            @staticmethod
            def marshal(event: FakeSDKEvent) -> str:
                return json.dumps(event.payload)

        class FakeLogLevel:
            INFO = "INFO"

        class FakeWSClient:
            def __init__(self, app_id: str, app_secret: str, *, event_handler, log_level=None) -> None:
                self.event_handler = event_handler

            def start(self) -> None:
                payload = {
                    "schema": "2.0",
                    "header": {
                        "event_id": "evt-ws-dedupe-1",
                        "event_type": "im.message.receive_v1",
                        "app_id": "cli_feishu_bot",
                        "tenant_key": "tenant-alpha",
                    },
                    "event": {
                        "sender": {
                            "sender_id": {"open_id": "ou_ws_dedupe"},
                            "sender_type": "user",
                            "name": "WS Ada",
                        },
                        "message": {
                            "message_id": "om_ws_dedupe_1",
                            "chat_id": "oc_ws_dedupe_1",
                            "chat_type": "p2p",
                            "message_type": "text",
                            "content": json.dumps({"text": "hello from duplicated ws"}),
                        },
                    },
                }
                self.event_handler.message_handler(FakeSDKEvent(payload))
                self.event_handler.message_handler(FakeSDKEvent(payload))

        class FakeWS:
            Client = FakeWSClient

        class FakeLark:
            EventDispatcherHandler = FakeEventDispatcherHandler
            JSON = FakeJSON
            LogLevel = FakeLogLevel
            ws = FakeWS

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
        self._bind_cli_control_conversation(
            service,
            account_id="ops-feishu",
            conversation_id="oc_ws_dedupe_1",
            elephant_id="demo",
            session_id=fake_runtime.demo_session.episode_id,
        )

        try:
            service.start_long_connection(account_id="ops-feishu", lark_module=FakeLark())

            self._wait_until(
                lambda: len(shared_runtime_calls) == 1,
                message="expected duplicate long-connection event to execute once",
            )
            self._wait_until(
                lambda: len(requests) == 3,
                message="expected only one placeholder and one final reply for duplicate events",
            )
            self.assertEqual(shared_runtime_calls[0]["session_id"], expected_session_id)
            self.assertEqual(shared_runtime_calls[0]["prompt"], "hello from duplicated ws")
        finally:
            service.shutdown_async_processing()

    def test_feishu_long_connection_acknowledges_before_runtime_finishes(self) -> None:
        app, _, _ = self._build()
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []
        runtime_started = threading.Event()
        release_runtime = threading.Event()

        def block_shared_runtime(_inbound, _session_id: str) -> None:
            runtime_started.set()
            release_runtime.wait(timeout=45.0)

        shared_runtime_calls = self._install_shared_runtime_stub(
            app,
            on_call=block_shared_runtime,
        )

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
                "data": {"message_id": f"om_reply_async_{len(requests)}"},
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
                return (SimpleNamespace(elephant_id="demo"),)[:limit]

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
                raise AssertionError("plain text should route through shared gateway runtime")

            def wake(self, session_id: str, *, inspect_only: bool = False):
                raise AssertionError("wake should not be used in this test")

        class FakeSDKEvent:
            def __init__(self, payload: dict[str, object]) -> None:
                self.payload = payload

        class FakeEventHandler:
            def __init__(self, callback) -> None:
                self.message_handler = callback

        class FakeEventDispatcherBuilder:
            def __init__(self) -> None:
                self.callback = None

            def register_p2_im_message_receive_v1(self, callback):
                self.callback = callback
                return self

            def build(self):
                assert self.callback is not None
                return FakeEventHandler(self.callback)

        class FakeEventDispatcherHandler:
            @staticmethod
            def builder(encrypt_key: str, verification_token: str, level=None):
                return FakeEventDispatcherBuilder()

        class FakeJSON:
            @staticmethod
            def marshal(event: FakeSDKEvent) -> str:
                return json.dumps(event.payload)

        class FakeLogLevel:
            INFO = "INFO"

        blocked_payload = self._feishu_message_event(
            event_id="evt-blocked-1",
            message_id="om_blocked_1",
            chat_id="oc_blocked_1",
            text="please block for a while",
        )

        class FakeWSClient:
            def __init__(self, app_id: str, app_secret: str, *, event_handler, log_level=None) -> None:
                self.event_handler = event_handler

            def start(self) -> None:
                self.event_handler.message_handler(FakeSDKEvent(blocked_payload))

        class FakeWS:
            Client = FakeWSClient

        class FakeLark:
            EventDispatcherHandler = FakeEventDispatcherHandler
            JSON = FakeJSON
            LogLevel = FakeLogLevel
            ws = FakeWS

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
        self._bind_cli_control_conversation(
            service,
            account_id="ops-feishu",
            conversation_id="oc_blocked_1",
            elephant_id="demo",
            session_id=fake_runtime.demo_session.episode_id,
        )

        try:
            started_at = time.monotonic()
            service.start_long_connection(account_id="ops-feishu", lark_module=FakeLark())
            elapsed = time.monotonic() - started_at

            self.assertLess(elapsed, 0.5)
            self.assertTrue(runtime_started.wait(timeout=1.0))
            self._wait_until(
                lambda: len(requests) >= 2,
                message="expected placeholder reply before runtime is released",
            )

            release_runtime.set()
            self._wait_until(
                lambda: len(shared_runtime_calls) == 1 and len(requests) == 3,
                message="expected final reply after async runtime finishes",
            )
        finally:
            release_runtime.set()
            service.shutdown_async_processing()

    def test_feishu_long_connection_duplicate_statuses_are_stateful(self) -> None:
        app, _, _ = self._build()
        service = FeishuGatewayService(
            app=app,
            environ={
                DEFAULT_FEISHU_APP_ID_ENV: "",
                DEFAULT_FEISHU_APP_SECRET_ENV: "",
                "ELEPHANT_TEST_FEISHU_APP_ID": "cli_feishu_bot",
                "ELEPHANT_TEST_FEISHU_APP_SECRET": "super-secret",
            },
        )
        assert service.adapter is not None
        assert service.async_job_store is not None
        payload = self._feishu_message_event(
            event_id="evt-stateful-1",
            message_id="om_stateful_1",
            chat_id="oc_stateful_1",
            text="stateful duplicate",
        )
        inbound = service.adapter.normalize_event(
            payload,
            account_id="ops-feishu",
            transport="long-connection",
        )

        with mock.patch.object(FeishuGatewayService, "_ensure_async_workers"), mock.patch.object(
            FeishuGatewayService, "_schedule_async_job", return_value=False
        ):
            job_key, _, created = service.async_job_store.create_or_get(
                account_id=inbound.account_id,
                conversation_id=inbound.conversation_id,
                event_id="evt-stateful-1",
                message_id="om_stateful_1",
                payload=payload,
                transport="long-connection",
            )
            self.assertTrue(created)

            queued = service.accept_long_connection_event(payload, account_id="ops-feishu")
            self.assertTrue(queued.response_body["duplicate_event"])
            self.assertEqual(queued.response_body["async_job_status"], "queued")
            self.assertEqual(queued.response_body["duplicate_handling"], "queued")

            service.async_job_store.mark_running(job_key)
            running = service.accept_long_connection_event(payload, account_id="ops-feishu")
            self.assertEqual(running.response_body["async_job_status"], "running")
            self.assertEqual(running.response_body["delivery_outcome"], "processing")

            service.async_job_store.complete(
                job_key,
                response_body={
                    "ok": True,
                    "adapter_id": FEISHU_ADAPTER_ID,
                    "transport": "long-connection",
                    "account_id": inbound.account_id,
                    "conversation_id": inbound.conversation_id,
                    "delivery_outcome": "delivered",
                    "external_message_id": "om_done",
                },
                external_message_id="om_done",
            )
            completed = service.accept_long_connection_event(payload, account_id="ops-feishu")
            self.assertEqual(completed.response_body["delivery_outcome"], "deduplicated")
            self.assertTrue(completed.response_body["duplicate_event"])

            failed_payload = self._feishu_message_event(
                event_id="evt-stateful-2",
                message_id="om_stateful_2",
                chat_id="oc_stateful_2",
                text="stateful failure",
            )
            failed_inbound = service.adapter.normalize_event(
                failed_payload,
                account_id="ops-feishu",
                transport="long-connection",
            )
            failed_key, _, failed_created = service.async_job_store.create_or_get(
                account_id=failed_inbound.account_id,
                conversation_id=failed_inbound.conversation_id,
                event_id="evt-stateful-2",
                message_id="om_stateful_2",
                payload=failed_payload,
                transport="long-connection",
            )
            self.assertTrue(failed_created)
            service.async_job_store.fail(
                failed_key,
                failure_summary="simulated failure",
            )
            failed = service.accept_long_connection_event(failed_payload, account_id="ops-feishu")
            self.assertEqual(failed.response_body["async_job_status"], "failed")
            self.assertEqual(failed.response_body["duplicate_handling"], "failed")


if __name__ == "__main__":
    unittest.main()
