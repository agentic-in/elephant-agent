from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
import unittest
from unittest import mock

from apps.gateway import (
    WECOM_ADAPTER_ID,
    WEIXIN_ADAPTER_ID,
    WecomGatewayService,
    WeixinGatewayService,
)
from apps.gateway.weixin_service import MessageDeduplicator
from packages.contracts.layers import Episode
from tests.e2e.gateway.gateway_adapter_test_base import GatewayAdapterTestBase


class GatewayAdapterWeixinWecomE2ETests(GatewayAdapterTestBase):
    def test_weixin_and_wecom_default_control_bridge_handles_elephant_commands(self) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"].update(
                {
                    "weixin": {
                        "enabled": True,
                        "surface": "ilink",
                        "accounts": [
                            {
                                "account_id": "ops-weixin",
                                "token": "wx-token",
                                "base_url": "https://ilinkai.weixin.qq.com",
                                "surface": "ilink",
                            }
                        ],
                    },
                    "wecom": {
                        "enabled": True,
                        "surface": "websocket",
                        "accounts": [
                            {
                                "account_id": "ops-wecom",
                                "env": {
                                    "bot_id": "ELEPHANT_TEST_WECOM_BOT_ID",
                                    "secret": "ELEPHANT_TEST_WECOM_SECRET",
                                },
                            }
                        ],
                    },
                }
            )
        )
        app, _, _ = self._build()

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

            def session_ids_for_elephant(self, elephant_id: str) -> tuple[str, ...]:
                return (self.demo_session.episode_id,) if elephant_id == "demo" else ()

            def create_elephant(self, **kwargs) -> Episode:
                raise AssertionError("auto create should not be used in this test")

            def inspect_session(self, session_id: str) -> Episode:
                if session_id != self.demo_session.episode_id:
                    raise KeyError(session_id)
                return self.demo_session

            def prepare_session_surface(self, session_id: str) -> Episode:
                return self.inspect_session(session_id)

            def explain_next_step(self, **kwargs):
                raise AssertionError("plain text should route through the shared gateway runtime")

            def compact_session_context(self, session_id: str, **kwargs):
                raise AssertionError("gateway shared-runtime path owns compaction")

            def wake(self, session_id: str, *, inspect_only: bool = False):
                raise AssertionError("wake should not be used in this test")

            def schedule_learning_for_session(self, **kwargs) -> None:
                raise AssertionError("switch learning should not run in this test")

        cases = (
            (
                WeixinGatewayService(
                    app=app,
                    cli_runtime_factory=lambda profile_dir, state_dir: FakeCliRuntime(),
                    default_cli_state_dir=str(self.state_dir),
                ),
                WEIXIN_ADAPTER_ID,
                "ops-weixin",
                "wx-user-1",
                "ilink",
                lambda service, body: service.adapter.normalize_event(
                    {
                        "message_id": f"wx-{body.replace(' ', '-')}",
                        "from_wxid": "wx-user-1",
                        "content": body,
                        "chat_type": "direct",
                        "transport": "ilink",
                    },
                    account_id="ops-weixin",
                    transport="ilink",
                ),
            ),
            (
                WecomGatewayService(
                    app=app,
                    cli_runtime_factory=lambda profile_dir, state_dir: FakeCliRuntime(),
                    default_cli_state_dir=str(self.state_dir),
                    environ={"ELEPHANT_TEST_WECOM_BOT_ID": "bot-id", "ELEPHANT_TEST_WECOM_SECRET": "secret"},
                ),
                WECOM_ADAPTER_ID,
                "ops-wecom",
                "wecom-chat-1",
                "websocket",
                lambda service, body: service.adapter.normalize_event(
                    {
                        "message_id": f"wecom-{body.replace(' ', '-')}",
                        "sender_id": "wecom-user-1",
                        "chat_id": "wecom-chat-1",
                        "chat_type": "direct",
                        "content": body,
                        "transport": "websocket",
                    },
                    account_id="ops-wecom",
                    transport="websocket",
                ),
            ),
        )

        for service, adapter_id, account_id, conversation_id, _transport, inbound_factory in cases:
            with self.subTest(service=service.service_key):
                self.assertIsNotNone(service.cli_control)
                control = service.describe()["control"]
                self.assertTrue(control["enabled"])
                self.assertEqual(control["runtime_status"], "ready")

                list_result = service.cli_control.handle_message(inbound_factory(service, "/elephant list"))
                self.assertTrue(list_result.handled)
                self.assertIn("Available local Elephant Agent herd", list_result.body or "")
                self.assertIn("demo", list_result.body or "")

                bind_result = service.cli_control.handle_message(inbound_factory(service, "/elephant create demo"))
                self.assertTrue(bind_result.handled)
                self.assertEqual(bind_result.elephant_id, "demo")
                self.assertEqual(
                    bind_result.session_id,
                    self._gateway_route_session_id(
                        adapter_id=adapter_id,
                        account_id=account_id,
                        conversation_id=conversation_id,
                    ),
                )

                follow_up = service.cli_control.handle_message(inbound_factory(service, "hello after binding"))
                self.assertFalse(follow_up.handled)
                self.assertEqual(follow_up.elephant_id, "demo")
                self.assertEqual(follow_up.session_id, bind_result.session_id)

    def test_weixin_ilink_serializes_same_conversation_across_runtime_and_reply_send(self) -> None:
        app, _, _ = self._build()
        service = WeixinGatewayService(app=app)
        service._resolved_account_id = "ops-weixin"
        service._resolved_dm_policy = "open"
        service._resolved_group_policy = "disabled"
        service._dedup = MessageDeduplicator()
        self._bind_gateway_conversation(
            app,
            adapter_id=WEIXIN_ADAPTER_ID,
            account_id="ops-weixin",
            conversation_id="wx-user-1",
            elephant_id="demo",
        )
        shared_runtime_calls = self._install_shared_runtime_stub(app)

        async def scenario() -> None:
            first_send_started = asyncio.Event()
            release_first_send = asyncio.Event()
            second_send_started = asyncio.Event()
            send_order: list[str] = []

            async def send_stub(_service, outbound) -> None:
                send_order.append(outbound.body)
                if len(send_order) == 1:
                    first_send_started.set()
                    await release_first_send.wait()
                else:
                    second_send_started.set()

            def inbound_message(message_id: str, text: str) -> dict[str, object]:
                return {
                    "message_id": message_id,
                    "from_user_id": "wx-user-1",
                    "item_list": [{"type": 1, "text_item": {"text": text}}],
                }

            with mock.patch.object(type(service), "_send_ilink_message", new=send_stub):
                first_task = asyncio.create_task(
                    service._process_message_safe(inbound_message("wx-serial-1", "first message"))
                )
                second_task = asyncio.create_task(
                    service._process_message_safe(inbound_message("wx-serial-2", "second message"))
                )

                await first_send_started.wait()
                await asyncio.sleep(0)
                self.assertFalse(second_send_started.is_set())
                self.assertEqual([call["prompt"] for call in shared_runtime_calls], ["first message"])
                self.assertEqual(send_order, ["gateway-handled:first message"])

                release_first_send.set()
                await asyncio.gather(first_task, second_task)

            self.assertEqual(
                [call["prompt"] for call in shared_runtime_calls],
                ["first message", "second message"],
            )
            self.assertEqual(
                send_order,
                ["gateway-handled:first message", "gateway-handled:second message"],
            )

        asyncio.run(scenario())

    def test_weixin_ilink_serializes_same_conversation_for_cli_control_messages(self) -> None:
        app, _, _ = self._build()
        service = WeixinGatewayService(app=app)
        service._resolved_account_id = "ops-weixin"
        service._resolved_dm_policy = "open"
        service._resolved_group_policy = "disabled"
        service._dedup = MessageDeduplicator()
        control_calls: list[str] = []

        def control_handle(inbound):
            control_calls.append(inbound.body)
            return SimpleNamespace(
                handled=True,
                body=f"control:{inbound.body}",
                session_id=f"control:{inbound.conversation_id}",
                summary=f"handled:{inbound.body}",
            )

        service.cli_control = SimpleNamespace(handle_message=control_handle)

        async def scenario() -> None:
            first_send_started = asyncio.Event()
            release_first_send = asyncio.Event()
            second_send_started = asyncio.Event()
            send_order: list[str] = []

            async def send_stub(_service, outbound) -> None:
                send_order.append(outbound.body)
                if len(send_order) == 1:
                    first_send_started.set()
                    await release_first_send.wait()
                else:
                    second_send_started.set()

            def inbound_message(message_id: str, text: str) -> dict[str, object]:
                return {
                    "message_id": message_id,
                    "from_user_id": "wx-user-1",
                    "item_list": [{"type": 1, "text_item": {"text": text}}],
                }

            with mock.patch.object(type(app), "handle_message", side_effect=AssertionError("shared runtime should not run for handled control messages")):
                with mock.patch.object(type(service), "_send_ilink_message", new=send_stub):
                    first_task = asyncio.create_task(
                        service._process_message_safe(inbound_message("wx-control-1", "first control"))
                    )
                    second_task = asyncio.create_task(
                        service._process_message_safe(inbound_message("wx-control-2", "second control"))
                    )

                    await first_send_started.wait()
                    await asyncio.sleep(0)
                    self.assertFalse(second_send_started.is_set())
                    self.assertEqual(control_calls, ["first control"])
                    self.assertEqual(send_order, ["control:first control"])

                    release_first_send.set()
                    await asyncio.gather(first_task, second_task)

            self.assertEqual(control_calls, ["first control", "second control"])
            self.assertEqual(send_order, ["control:first control", "control:second control"])

        asyncio.run(scenario())



if __name__ == "__main__":
    unittest.main()
