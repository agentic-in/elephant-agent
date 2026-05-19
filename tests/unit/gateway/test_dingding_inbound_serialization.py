"""Unit tests for DingDing same-conversation inbound serialization."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest import mock

from apps.gateway.dingding_service import DingdingGatewayService
from apps.gateway.dingding_support import (
    DingdingGatewayAccountConfig,
    DingdingResolvedAccount,
)


def _make_account(account_id: str = "ops-dingding") -> DingdingResolvedAccount:
    return DingdingResolvedAccount(
        account_id=account_id,
        client_id="test-client-id",
        client_secret="test-client-secret",
        robot_code="test-robot-code",
        config=DingdingGatewayAccountConfig(account_id=account_id),
    )


def _inbound_message(
    message_id: str,
    text: str,
    *,
    conversation_id: str = "",
    conversation_type: str = "1",
    sender_id: str = "user-1",
) -> dict[str, object]:
    return {
        "message_id": message_id,
        "sender_id": sender_id,
        "conversation_id": conversation_id,
        "conversation_type": conversation_type,
        "text": {"content": text},
        "robot_code": "test-robot-code",
    }


class _FakeGatewayApp:
    """Minimal GatewayApp stub for unit tests."""

    def __init__(self) -> None:
        self.runtime_calls: list[str] = []
        self.loaded_profile = None
        self.state_dir = None
        self.core = SimpleNamespace(
            route_inbound=lambda *a, **kw: SimpleNamespace(delivery=SimpleNamespace(outbound=None))
        )
        self.loaded_profile = None

    def handle_message(self, inbound, **kwargs):
        self.runtime_calls.append(inbound.body)
        return SimpleNamespace(
            delivery=SimpleNamespace(outbound=None),
        )


class DingdingInboundSerializationTests(unittest.TestCase):
    def test_same_conversation_serializes_across_runtime_path(self) -> None:
        app = _FakeGatewayApp()
        service = DingdingGatewayService(app=app)
        account = _make_account()

        async def scenario() -> None:
            first_started = asyncio.Event()
            release_first = asyncio.Event()
            second_started = asyncio.Event()
            send_order: list[str] = []

            async def send_stub(_self, delivery_request, **kw) -> None:
                body = delivery_request.get("body", {}) if isinstance(delivery_request, dict) else {}
                text = body.get("msgParam", "sent") if isinstance(body, dict) else "sent"
                send_order.append(str(text))
                if len(send_order) == 1:
                    first_started.set()
                    await release_first.wait()
                else:
                    second_started.set()

            with mock.patch.object(type(service), "_send_dingtalk_reply", new=send_stub):
                first_task = asyncio.create_task(
                    service._on_dingtalk_message_safe(
                        _inbound_message("dd-serial-1", "first message"),
                        account=account,
                        adapter=service.adapter,
                        dingtalk_module=SimpleNamespace(),
                    )
                )
                second_task = asyncio.create_task(
                    service._on_dingtalk_message_safe(
                        _inbound_message("dd-serial-2", "second message"),
                        account=account,
                        adapter=service.adapter,
                        dingtalk_module=SimpleNamespace(),
                    )
                )

                await first_started.wait()
                await asyncio.sleep(0)
                # Second message must not start while first is still processing
                self.assertFalse(second_started.is_set())
                self.assertEqual(app.runtime_calls, ["first message"])

                release_first.set()
                await asyncio.gather(first_task, second_task)

            self.assertEqual(app.runtime_calls, ["first message", "second message"])

    def test_same_conversation_serializes_cli_control_path(self) -> None:
        app = _FakeGatewayApp()
        service = DingdingGatewayService(app=app)
        account = _make_account()
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
            first_started = asyncio.Event()
            release_first = asyncio.Event()
            second_started = asyncio.Event()
            send_order: list[str] = []

            async def send_stub(_self, delivery_request, **kw) -> None:
                send_order.append("sent")
                if len(send_order) == 1:
                    first_started.set()
                    await release_first.wait()
                else:
                    second_started.set()

            with mock.patch.object(
                type(app),
                "handle_message",
                side_effect=AssertionError("should not run"),
            ):
                with mock.patch.object(type(service), "_send_dingtalk_reply", new=send_stub):
                    first_task = asyncio.create_task(
                        service._on_dingtalk_message_safe(
                            _inbound_message("dd-control-1", "first control"),
                            account=account,
                            adapter=service.adapter,
                            dingtalk_module=SimpleNamespace(),
                        )
                    )
                    second_task = asyncio.create_task(
                        service._on_dingtalk_message_safe(
                            _inbound_message("dd-control-2", "second control"),
                            account=account,
                            adapter=service.adapter,
                            dingtalk_module=SimpleNamespace(),
                        )
                    )

                    await first_started.wait()
                    await asyncio.sleep(0)
                    self.assertFalse(second_started.is_set())
                    self.assertEqual(control_calls, ["first control"])

                    release_first.set()
                    await asyncio.gather(first_task, second_task)

            self.assertEqual(control_calls, ["first control", "second control"])
            self.assertEqual(app.runtime_calls, [])

    def test_different_conversations_run_in_parallel(self) -> None:
        app = _FakeGatewayApp()
        service = DingdingGatewayService(app=app)
        account = _make_account()

        async def scenario() -> None:
            first_started = asyncio.Event()
            release_first = asyncio.Event()
            second_started = asyncio.Event()

            async def send_stub(_self, delivery_request, **kw) -> None:
                pass

            with mock.patch.object(type(service), "_send_dingtalk_reply", new=send_stub):
                # Different sender_ids → different conversations → parallel
                first_task = asyncio.create_task(
                    service._on_dingtalk_message_safe(
                        _inbound_message("dd-para-1", "msg from user-a", sender_id="user-a"),
                        account=account,
                        adapter=service.adapter,
                        dingtalk_module=SimpleNamespace(),
                    )
                )
                second_task = asyncio.create_task(
                    service._on_dingtalk_message_safe(
                        _inbound_message("dd-para-2", "msg from user-b", sender_id="user-b"),
                        account=account,
                        adapter=service.adapter,
                        dingtalk_module=SimpleNamespace(),
                    )
                )

                # Both should complete without blocking each other
                await asyncio.gather(first_task, second_task)

            self.assertEqual(app.runtime_calls, ["msg from user-a", "msg from user-b"])

    def test_self_message_skips_serialization(self) -> None:
        app = _FakeGatewayApp()
        service = DingdingGatewayService(app=app)
        account = _make_account()

        async def scenario() -> None:
            async def send_stub(_self, delivery_request, **kw) -> None:
                pass

            with mock.patch.object(type(service), "_send_dingtalk_reply", new=send_stub):
                # sender_id == robot_code → self message → skip serialization
                await service._on_dingtalk_message_safe(
                    _inbound_message("dd-self-1", "self message", sender_id="test-robot-code"),
                    account=account,
                    adapter=service.adapter,
                    dingtalk_module=SimpleNamespace(),
                )

            self.assertEqual(app.runtime_calls, ["self message"])


if __name__ == "__main__":
    unittest.main()
