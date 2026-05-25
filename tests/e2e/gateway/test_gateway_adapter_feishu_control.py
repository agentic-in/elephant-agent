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
    build_gateway_app,
)
from packages.contracts.layers import Episode
from packages.gateway_core import GatewayIdentityKey
from tests.e2e.gateway.gateway_adapter_test_base import GatewayAdapterTestBase


class GatewayAdapterFeishuControlE2ETests(GatewayAdapterTestBase):
    def test_feishu_control_defaults_to_local_cli_runtime_paths(self) -> None:
        gateway_state_dir = self.state_dir / "gateway"
        gateway_state_dir.mkdir()
        app, _, _ = build_gateway_app(
            provider_profile=self._provider_profile(),
            state_dir=gateway_state_dir,
            control_state_dir=self.state_dir,
        )

        class FakeCliRuntime:
            def list_herd(self, *, limit: int = 12) -> tuple[object, ...]:
                return (SimpleNamespace(elephant_id="demo"),)

            def latest_session_for_elephant(self, elephant_id: str):
                return None

            def create_elephant(self, *, elephant_id: str, profile_id=None, display_name=None, mode=None, session_id=None):
                raise AssertionError("create_elephant should not be called in describe path")

            def inspect_session(self, session_id: str):
                raise AssertionError("inspect_session should not be called in describe path")

            def prepare_session_surface(self, session_id: str):
                raise AssertionError("prepare_session_surface should not be called in describe path")

            def explain_next_step(
                self,
                *,
                session_id: str,
                prompt: str,
                state_query=None,
                tool_name=None,
                tool_arguments=None,
                delivery_payload=None,
            ):
                raise AssertionError("explain_next_step should not be called in describe path")

            def wake(self, session_id: str, *, inspect_only: bool = False):
                raise AssertionError("wake should not be called in describe path")

        service = FeishuGatewayService(
            app=app,
            cli_runtime_factory=lambda profile_dir, state_dir: FakeCliRuntime(),
            default_cli_state_dir=str(self.state_dir),
        )

        description = service.describe()
        control = description["control"]
        self.assertTrue(control["enabled"])
        self.assertEqual(control["state_dir"], str(self.state_dir))
        self.assertEqual(control["runtime_status"], "ready")
        self.assertEqual(control["known_elephants"], ("demo",))

    def test_feishu_control_bridge_binds_conversation_to_selected_elephant(self) -> None:
        app, _, _ = self._build()
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []
        expected_session_id = self._gateway_route_session_id(
            adapter_id=FEISHU_ADAPTER_ID,
            account_id="ops-feishu",
            conversation_id="oc_control_1",
        )
        shared_runtime_calls = self._install_shared_runtime_stub(
            app,
            session_ids={"oc_control_1": expected_session_id},
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
                "data": {"message_id": "om_reply_control_1"},
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
                self.ops_session = Episode(
                    episode_id="session-ops",
                    state_id="state:test",
                    personal_model_id="elephant:ops",
                    entry_surface="test",
                    elephant_id="ops",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )
            def list_herd(self, *, limit: int = 12) -> tuple[object, ...]:
                return (
                    SimpleNamespace(
                        elephant_id="demo",
                        latest_session_id=self.demo_session.episode_id,
                        latest_status=self.demo_session.status,
                        updated_at=self.demo_session.updated_at,
                        session_count=1,
                    ),
                    SimpleNamespace(
                        elephant_id="ops",
                        latest_session_id=self.ops_session.episode_id,
                        latest_status=self.ops_session.status,
                        updated_at=self.ops_session.updated_at,
                        session_count=1,
                    ),
                )[:limit]

            def latest_session_for_elephant(self, elephant_id: str) -> Episode | None:
                if elephant_id == "demo":
                    return self.demo_session
                if elephant_id == "ops":
                    return self.ops_session
                return None

            def create_elephant(self, **kwargs) -> Episode:
                raise AssertionError("auto create should not be used in this test")

            def inspect_session(self, session_id: str) -> Episode:
                if session_id == self.demo_session.episode_id:
                    return self.demo_session
                if session_id == self.ops_session.episode_id:
                    return self.ops_session
                raise KeyError(session_id)

            def prepare_session_surface(self, session_id: str) -> Episode:
                return self.inspect_session(session_id)

            def explain_next_step(self, **kwargs):
                raise AssertionError("plain text should route through the shared gateway runtime")

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

        bind_result = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-control-bind",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_control"},
                        "sender_type": "user",
                        "name": "Remote Ada",
                    },
                    "message": {
                        "message_id": "om_control_bind",
                        "chat_id": "oc_control_1",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "/elephant create demo"}),
                    },
                },
            }
        )

        self.assertIsNone(bind_result.exchange)
        self.assertEqual(bind_result.response_body["control_mode"], "cli-runtime")
        self.assertEqual(bind_result.response_body["elephant_id"], "demo")
        self.assertEqual(bind_result.response_body["session_id"], expected_session_id)
        self.assertEqual(shared_runtime_calls, [])

        follow_up = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-control-msg",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_control"},
                        "sender_type": "user",
                        "name": "Remote Ada",
                    },
                    "message": {
                        "message_id": "om_control_msg",
                        "chat_id": "oc_control_1",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "keep coding"}),
                    },
                },
            }
        )

        self.assertEqual(follow_up.response_body["elephant_id"], "demo")
        self.assertEqual(follow_up.response_body["session_id"], expected_session_id)
        self.assertEqual(shared_runtime_calls, [{"session_id": expected_session_id, "prompt": "keep coding", "conversation_id": "oc_control_1"}])
        self.assertEqual(len(requests), 3)

    def test_feishu_control_bridge_can_list_and_report_current_elephant(self) -> None:
        app, _, _ = self._build()
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []
        expected_session_id = self._gateway_route_session_id(
            adapter_id=FEISHU_ADAPTER_ID,
            account_id="ops-feishu",
            conversation_id="oc_control_elephant_status",
        )
        shared_runtime_calls = self._install_shared_runtime_stub(
            app,
            session_ids={"oc_control_elephant_status": expected_session_id},
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
                "data": {"message_id": "om_reply_control_session"},
            }

        class FakeCliRuntime:
            def __init__(self) -> None:
                now = datetime.now(UTC)
                self.demo_root_session = Episode(
                    episode_id="session-demo-root",
                    state_id="state:test",
                    personal_model_id="elephant:demo",
                    entry_surface="test",
                    elephant_id="demo",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )
                self.demo_latest_session = Episode(
                    episode_id="session-demo-latest",
                    state_id="state:test",
                    personal_model_id="elephant:demo",
                    entry_surface="test",
                    elephant_id="demo",
                    status="open",
                    started_at=now,
                    updated_at=now,
                    parent_episode_id=self.demo_root_session.episode_id,
                )
            def list_herd(self, *, limit: int = 12) -> tuple[object, ...]:
                return (
                    SimpleNamespace(
                        elephant_id="demo",
                        latest_session_id=self.demo_latest_session.episode_id,
                        latest_status=self.demo_latest_session.status,
                        updated_at=self.demo_latest_session.updated_at,
                        session_count=2,
                    ),
                )[:limit]

            def latest_session_for_elephant(self, elephant_id: str) -> Episode | None:
                if elephant_id == "demo":
                    return self.demo_latest_session
                return None

            def create_elephant(self, **kwargs) -> Episode:
                raise AssertionError("auto create should not be used in this test")

            def inspect_session(self, session_id: str) -> Episode:
                if session_id == self.demo_root_session.episode_id:
                    return self.demo_root_session
                if session_id == self.demo_latest_session.episode_id:
                    return self.demo_latest_session
                raise KeyError(session_id)

            def prepare_session_surface(self, session_id: str) -> Episode:
                return self.inspect_session(session_id)

            def explain_next_step(self, **kwargs):
                raise AssertionError("plain text should route through the shared gateway runtime")

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

        list_result = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-control-elephant-list",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_control"},
                        "sender_type": "user",
                        "name": "Remote Ada",
                    },
                    "message": {
                        "message_id": "om_control_elephant_list",
                        "chat_id": "oc_control_elephant_status",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "/elephant list"}),
                    },
                },
            }
        )

        assert list_result.delivery_request is not None
        rendered_listing = str(list_result.delivery_request["body"]["content"])
        self.assertIn("Available local Elephant Agent herd", rendered_listing)
        self.assertIn("demo", rendered_listing)
        self.assertIn("open", rendered_listing)
        self.assertIn("/elephant use <name>", rendered_listing)

        bind_result = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-control-use-elephant",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_control"},
                        "sender_type": "user",
                        "name": "Remote Ada",
                    },
                    "message": {
                        "message_id": "om_control_use_elephant",
                        "chat_id": "oc_control_elephant_status",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "/elephant create demo"}),
                    },
                },
            }
        )

        self.assertEqual(bind_result.response_body["elephant_id"], "demo")
        self.assertEqual(bind_result.response_body["session_id"], expected_session_id)

        current_result = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-control-current-elephant",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_control"},
                        "sender_type": "user",
                        "name": "Remote Ada",
                    },
                    "message": {
                        "message_id": "om_control_current_elephant",
                        "chat_id": "oc_control_elephant_status",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "/elephant current"}),
                    },
                },
            }
        )

        self.assertEqual(current_result.response_body["elephant_id"], "demo")
        self.assertEqual(current_result.response_body["session_id"], expected_session_id)
        assert current_result.delivery_request is not None
        rendered_current = str(current_result.delivery_request["body"]["content"])
        self.assertIn("Current elephant: `demo`", rendered_current)
        self.assertIn("route_status: `open`", rendered_current)

        follow_up = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-control-follow-up",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_control"},
                        "sender_type": "user",
                        "name": "Remote Ada",
                    },
                    "message": {
                        "message_id": "om_control_follow_up",
                        "chat_id": "oc_control_elephant_status",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "stay on the active elephant"}),
                    },
                },
            }
        )

        self.assertEqual(follow_up.response_body["elephant_id"], "demo")
        self.assertEqual(follow_up.response_body["session_id"], expected_session_id)
        self.assertEqual(shared_runtime_calls, [{"session_id": expected_session_id, "prompt": "stay on the active elephant", "conversation_id": "oc_control_elephant_status"}])
        self.assertGreaterEqual(len(requests), 5)

    def test_feishu_control_bridge_accepts_post_command_wrapped_elephant_use(self) -> None:
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
                "data": {"message_id": f"om_reply_post_{len(requests)}"},
            }

        class FakeCliRuntime:
            def __init__(self) -> None:
                now = datetime.now(UTC)
                self.demo_session = Episode(
                    episode_id="session-demo-root",
                    state_id="state:test",
                    personal_model_id="elephant:leo",
                    entry_surface="test",
                    elephant_id="leo",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )

            def list_herd(self, *, limit: int = 12) -> tuple[object, ...]:
                return (
                    SimpleNamespace(
                        elephant_id="leo",
                        latest_session_id=self.demo_session.episode_id,
                        latest_status=self.demo_session.status,
                        updated_at=self.demo_session.updated_at,
                        session_count=1,
                    ),
                )[:limit]

            def latest_session_for_elephant(self, elephant_id: str) -> Episode | None:
                if elephant_id == "leo":
                    return self.demo_session
                return None

            def create_elephant(self, **kwargs) -> Episode:
                raise AssertionError("auto create should not be used in this test")

            def inspect_session(self, session_id: str) -> Episode:
                if session_id == self.demo_session.episode_id:
                    return self.demo_session
                raise KeyError(session_id)

            def prepare_session_surface(self, session_id: str) -> Episode:
                return self.inspect_session(session_id)

            def explain_next_step(self, **kwargs):
                raise AssertionError("post command should bind, not forward to runtime")

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

        bind_result = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-control-use-elephant-post",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_control"},
                        "sender_type": "user",
                        "name": "Remote Ada",
                    },
                    "message": {
                        "message_id": "om_control_use_elephant_post",
                        "chat_id": "oc_control_elephant_post",
                        "chat_type": "p2p",
                        "message_type": "post",
                        "content": json.dumps(
                            {
                                "title": "",
                                "content": [
                                    [
                                        {"tag": "text", "text": "- "},
                                        {"tag": "text", "text": "/elephant create leo", "style": ["bold"]},
                                    ]
                                ],
                            }
                        ),
                    },
                },
            }
        )

        self.assertEqual(bind_result.response_body["elephant_id"], "leo")
        self.assertEqual(
            bind_result.response_body["session_id"],
            self._gateway_route_session_id(
                adapter_id=FEISHU_ADAPTER_ID,
                account_id="ops-feishu",
                conversation_id="oc_control_elephant_post",
            ),
        )
        self.assertEqual(bind_result.response_body["summary"], "elephant shaped")
        self.assertGreaterEqual(len(requests), 2)

    def test_feishu_control_bridge_reuses_parent_binding_inside_topic_replies(self) -> None:
        app, _, _ = self._build()
        requests: list[tuple[str, str, dict[str, object], dict[str, str]]] = []
        parent_session_id = self._gateway_route_session_id(
            adapter_id=FEISHU_ADAPTER_ID,
            account_id="ops-feishu",
            conversation_id="oc_topic_chat",
        )
        child_session_id = self._gateway_route_session_id(
            adapter_id=FEISHU_ADAPTER_ID,
            account_id="ops-feishu",
            conversation_id="oc_topic_chat:om_topic_root",
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
                "data": {"message_id": f"om_reply_topic_{len(requests)}"},
            }

        def on_shared_runtime_call(inbound, session_id: str) -> None:
            parent_identity = app.core.dependencies.identity_store.lookup(
                GatewayIdentityKey(
                    adapter_id=inbound.adapter_id,
                    account_id=inbound.account_id,
                    conversation_id=inbound.parent_conversation_id or inbound.conversation_id,
                )
            )
            assert parent_identity is not None
            app.core.bind_elephant(
                inbound,
                elephant_id=str(parent_identity.elephant_id),
                state_id=str(parent_identity.state_id),
            )

        shared_runtime_calls = self._install_shared_runtime_stub(
            app,
            session_ids={"oc_topic_chat:om_topic_root": child_session_id},
            on_call=on_shared_runtime_call,
        )

        class FakeCliRuntime:
            def __init__(self) -> None:
                now = datetime.now(UTC)
                self.demo_root_session = Episode(
                    episode_id="session-demo-root",
                    state_id="state:test",
                    personal_model_id="elephant:demo",
                    entry_surface="test",
                    elephant_id="demo",
                    status="open",
                    started_at=now,
                    updated_at=now,
                )
                self.demo_latest_session = Episode(
                    episode_id="session-demo-latest",
                    state_id="state:test",
                    personal_model_id="elephant:demo",
                    entry_surface="test",
                    elephant_id="demo",
                    status="open",
                    started_at=now,
                    updated_at=now,
                    parent_episode_id=self.demo_root_session.episode_id,
                )
            def list_herd(self, *, limit: int = 12) -> tuple[object, ...]:
                return (
                    SimpleNamespace(
                        elephant_id="demo",
                        latest_session_id=self.demo_latest_session.episode_id,
                        latest_status=self.demo_latest_session.status,
                        updated_at=self.demo_latest_session.updated_at,
                        session_count=2,
                    ),
                )[:limit]

            def latest_session_for_elephant(self, elephant_id: str) -> Episode | None:
                if elephant_id == "demo":
                    return self.demo_latest_session
                return None

            def create_elephant(self, **kwargs) -> Episode:
                raise AssertionError("auto create should not be used in this test")

            def inspect_session(self, session_id: str) -> Episode:
                if session_id == self.demo_root_session.episode_id:
                    return self.demo_root_session
                if session_id == self.demo_latest_session.episode_id:
                    return self.demo_latest_session
                raise KeyError(session_id)

            def prepare_session_surface(self, session_id: str) -> Episode:
                return self.inspect_session(session_id)

            def explain_next_step(self, **kwargs):
                raise AssertionError("plain text should route through the shared gateway runtime")

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

        bind_result = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-topic-use-elephant",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_control"},
                        "sender_type": "user",
                        "name": "Remote Ada",
                    },
                    "message": {
                        "message_id": "om_topic_use_elephant",
                        "chat_id": "oc_topic_chat",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "/elephant create demo"}),
                    },
                },
            }
        )

        self.assertEqual(bind_result.response_body["session_id"], parent_session_id)

        topic_follow_up = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-topic-follow-up",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_control"},
                        "sender_type": "user",
                        "name": "Remote Ada",
                    },
                    "message": {
                        "message_id": "om_topic_follow_up",
                        "chat_id": "oc_topic_chat",
                        "chat_type": "p2p",
                        "root_id": "om_topic_root",
                        "parent_id": "om_topic_root",
                        "message_type": "text",
                        "content": json.dumps({"text": "继续这个 session"}),
                    },
                },
            }
        )

        self.assertEqual(topic_follow_up.response_body["elephant_id"], "demo")
        self.assertEqual(topic_follow_up.response_body["session_id"], child_session_id)
        self.assertEqual(shared_runtime_calls, [{"session_id": child_session_id, "prompt": "继续这个 session", "conversation_id": "oc_topic_chat:om_topic_root"}])
        self.assertGreaterEqual(len(requests), 3)

        thread_identity = app.core.dependencies.identity_store.lookup(
            GatewayIdentityKey(
                adapter_id=FEISHU_ADAPTER_ID,
                account_id="ops-feishu",
                conversation_id="oc_topic_chat:om_topic_root",
            )
        )
        self.assertIsNotNone(thread_identity)
        assert thread_identity is not None
        self.assertEqual(thread_identity.session_id, child_session_id)

    def test_feishu_control_bridge_requires_binding_before_plain_text_routes(self) -> None:
        app, _, _ = self._build()

        def fake_request(
            method: str,
            url: str,
            payload: dict[str, object],
            headers: dict[str, str],
        ) -> dict[str, object]:
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
                "data": {"message_id": "om_reply_control_hint"},
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
                self.ops_session = Episode(
                    episode_id="session-ops",
                    state_id="state:test",
                    personal_model_id="elephant:ops",
                    entry_surface="test",
                    elephant_id="ops",
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
                    SimpleNamespace(
                        elephant_id="ops",
                        latest_session_id=self.ops_session.episode_id,
                        latest_status=self.ops_session.status,
                        updated_at=self.ops_session.updated_at,
                        session_count=1,
                    ),
                )[:limit]

            def latest_session_for_elephant(self, elephant_id: str) -> Episode | None:
                if elephant_id == "demo":
                    return self.demo_session
                if elephant_id == "ops":
                    return self.ops_session
                return None

            def create_elephant(self, **kwargs) -> Episode:
                raise AssertionError("auto create should not be used in this test")

            def inspect_session(self, session_id: str) -> Episode:
                if session_id == self.demo_session.episode_id:
                    return self.demo_session
                if session_id == self.ops_session.episode_id:
                    return self.ops_session
                raise KeyError(session_id)

            def prepare_session_surface(self, session_id: str) -> Episode:
                return self.inspect_session(session_id)

            def explain_next_step(self, **kwargs):
                self.explain_calls.append(dict(kwargs))
                prompt = str(kwargs["prompt"])
                return SimpleNamespace(
                    execution=SimpleNamespace(summary=f"cli-handled:{prompt}")
                )

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

        result = service.dispatch_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-control-unbound",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_control"},
                        "sender_type": "user",
                        "name": "Remote Ada",
                    },
                    "message": {
                        "message_id": "om_control_unbound",
                        "chat_id": "oc_control_unbound",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "hello there"}),
                    },
                },
            }
        )

        self.assertIsNone(result.exchange)
        self.assertEqual(result.response_body["control_mode"], "cli-runtime")
        self.assertNotIn("elephant_id", result.response_body)
        self.assertNotIn("session_id", result.response_body)
        self.assertEqual(len(fake_runtime.explain_calls), 0)
        assert result.delivery_request is not None
        self.assertEqual(result.delivery_request["body"]["msg_type"], "interactive")
        rendered_post = json.loads(result.delivery_request["body"]["content"])
        self.assertEqual(rendered_post["schema"], "2.0")
        rendered_text = rendered_post["body"]["elements"][0]["content"]
        self.assertIn("This conversation is not pinned yet.", rendered_text)
        self.assertIn("/elephant list", rendered_text)
        self.assertIn("/elephant use <name>", rendered_text)



if __name__ == "__main__":
    unittest.main()
