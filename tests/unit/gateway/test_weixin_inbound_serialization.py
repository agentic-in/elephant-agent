from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest import mock

from apps.gateway.weixin_service import MessageDeduplicator, WeixinGatewayService
from packages.gateway_core import (
    GatewayAccountRef,
    GatewayConversationRef,
    GatewayOutboundMessage,
)


class _FakeGatewayApp:
    def __init__(self) -> None:
        self.loaded_profile = None
        self.state_dir = None
        self.runtime_calls: list[str] = []

    def handle_message(self, inbound, **kwargs):
        self.runtime_calls.append(inbound.body)
        outbound = GatewayOutboundMessage(
            message_id=f"runtime:{inbound.event_id}",
            account=GatewayAccountRef(
                adapter_id=inbound.adapter_id,
                account_id=inbound.account_id,
                surface=inbound.account.surface,
            ),
            conversation=GatewayConversationRef(conversation_id=inbound.conversation_id),
            session_id=f"session:{inbound.conversation_id}",
            body=f"gateway-handled:{inbound.body}",
            reply_to_message_id=inbound.reply_to_message_id or inbound.event_id,
        )
        return SimpleNamespace(delivery=SimpleNamespace(outbound=outbound))


class WeixinInboundSerializationTest(unittest.TestCase):
    def _service(self) -> WeixinGatewayService:
        service = WeixinGatewayService(app=_FakeGatewayApp())
        service._resolved_account_id = "ops-weixin"
        service._resolved_dm_policy = "open"
        service._resolved_group_policy = "disabled"
        service._dedup = MessageDeduplicator()
        return service

    @staticmethod
    def _inbound_message(message_id: str, text: str) -> dict[str, object]:
        return {
            "message_id": message_id,
            "from_user_id": "wx-user-1",
            "item_list": [{"type": 1, "text_item": {"text": text}}],
        }

    def test_shared_runtime_path_stays_fifo_per_conversation(self) -> None:
        service = self._service()
        app = service.app

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

            with mock.patch.object(type(service), "_send_ilink_message", new=send_stub):
                first_task = asyncio.create_task(
                    service._process_message_safe(self._inbound_message("wx-runtime-1", "first message"))
                )
                second_task = asyncio.create_task(
                    service._process_message_safe(self._inbound_message("wx-runtime-2", "second message"))
                )

                await first_send_started.wait()
                await asyncio.sleep(0)
                self.assertFalse(second_send_started.is_set())
                self.assertEqual(app.runtime_calls, ["first message"])
                self.assertEqual(send_order, ["gateway-handled:first message"])

                release_first_send.set()
                await asyncio.gather(first_task, second_task)

            self.assertEqual(app.runtime_calls, ["first message", "second message"])
            self.assertEqual(
                send_order,
                ["gateway-handled:first message", "gateway-handled:second message"],
            )

        asyncio.run(scenario())

    def test_cli_control_path_stays_fifo_per_conversation(self) -> None:
        service = self._service()
        app = service.app
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

            with mock.patch.object(type(service), "_send_ilink_message", new=send_stub):
                first_task = asyncio.create_task(
                    service._process_message_safe(self._inbound_message("wx-control-1", "first control"))
                )
                second_task = asyncio.create_task(
                    service._process_message_safe(self._inbound_message("wx-control-2", "second control"))
                )

                await first_send_started.wait()
                await asyncio.sleep(0)
                self.assertFalse(second_send_started.is_set())
                self.assertEqual(control_calls, ["first control"])
                self.assertEqual(send_order, ["control:first control"])
                self.assertEqual(app.runtime_calls, [])

                release_first_send.set()
                await asyncio.gather(first_task, second_task)

            self.assertEqual(control_calls, ["first control", "second control"])
            self.assertEqual(send_order, ["control:first control", "control:second control"])
            self.assertEqual(app.runtime_calls, [])

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
