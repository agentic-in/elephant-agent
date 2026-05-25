from __future__ import annotations

import asyncio
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime
import io
import json
import os
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

from apps.gateway import (
    DEFAULT_DISCORD_BOT_TOKEN_ENV,
    DISCORD_ADAPTER_ID,
    DiscordGatewayService,
    DiscordMessagingAdapter,
    GatewayAdapterDescriptor,
    load_discord_gateway_accounts,
)
from apps.gateway.discord import DiscordPyDeliveryTransport
import apps.gateway.__main__ as gateway_main
from apps.gateway.__main__ import command_main
from packages.contracts.layers import Episode
from packages.gateway_core import (
    DEFAULT_GATEWAY_ACCOUNT_ID,
    GatewayAccountRef,
    GatewayConversationRef,
    GatewayOutboundMessage,
)
from packages.security.runtime import PolicyDecision
from tests.e2e.gateway.gateway_adapter_test_base import GatewayAdapterTestBase


class GatewayAdapterDiscordRuntimeE2ETests(GatewayAdapterTestBase):
    class _FakeDiscordDeliveryTransport:
        def __init__(self) -> None:
            self.requests: list[tuple[dict[str, object], object]] = []

        async def send_request(self, request, *, account):
            normalized_request = {str(key): value for key, value in request.items()}
            self.requests.append((normalized_request, account))
            return {"id": "discord-reply-1"}

    def test_discord_service_dispatch_event_delivers_dm_reply_with_mentions_suppressed(
        self,
    ) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"].update(
                {
                    "discord": {
                        "enabled": True,
                        "accounts": [
                            {
                                "account_id": "ops-discord",
                                "env": {"bot_token": "ELEPHANT_TEST_DISCORD_BOT_TOKEN"},
                            }
                        ],
                    }
                }
            )
        )

        app, _, _ = self._build()
        self._bind_gateway_conversation(
            app,
            adapter_id=DISCORD_ADAPTER_ID,
            account_id="ops-discord",
            conversation_id="dm-1",
        )
        service = DiscordGatewayService(
            app=app,
            environ={"ELEPHANT_TEST_DISCORD_BOT_TOKEN": "discord-token-123"},
        )
        delivery_transport = self._FakeDiscordDeliveryTransport()

        result = asyncio.run(
            service.dispatch_event(
                {
                    "id": "msg-1",
                    "channel_id": "dm-1",
                    "content": "hello from discord",
                    "chat_type": "direct",
                    "author": {
                        "id": "user-1",
                        "username": "ada",
                        "global_name": "Ada Lovelace",
                    },
                    "attachments": [],
                },
                account_id="ops-discord",
                delivery_transport=delivery_transport,
            )
        )

        self.assertEqual(result.response_body["delivery_outcome"], "delivered")
        self.assertEqual(
            result.response_body["policy_decision"],
            str(PolicyDecision.ALLOW),
        )
        self.assertEqual(result.response_body["external_message_id"], "discord-reply-1")
        self.assertEqual(len(delivery_transport.requests), 1)
        request, account = delivery_transport.requests[0]
        self.assertEqual(account.account_id, "ops-discord")
        self.assertEqual(request["path"], "/channels/dm-1/messages")
        self.assertEqual(request["channel_id"], "dm-1")
        self.assertEqual(
            request["body"]["allowed_mentions"], {"parse": [], "replied_user": False}
        )
        self.assertEqual(
            request["body"]["message_reference"]["message_id"],
            "msg-1",
        )

    def test_discord_service_can_route_through_cli_control_bridge(self) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"].update(
                {
                    "discord": {
                        "enabled": True,
                        "surface": "gateway",
                        "control": {},
                        "accounts": [
                            {
                                "account_id": "ops-discord",
                                "env": {"bot_token": "ELEPHANT_TEST_DISCORD_BOT_TOKEN"},
                            }
                        ],
                    }
                }
            )
        )

        app, _, _ = self._build()
        shared_runtime_calls = self._install_shared_runtime_stub(app)
        expected_session_id = self._gateway_route_session_id(
            adapter_id=DISCORD_ADAPTER_ID,
            account_id="ops-discord",
            conversation_id="dm-control-1",
        )

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
                raise AssertionError(
                    "plain text should route through the shared gateway runtime"
                )

            def compact_session_context(self, session_id: str, **kwargs):
                raise AssertionError("gateway shared-runtime path owns compaction")

            def wake(self, session_id: str, *, inspect_only: bool = False):
                raise AssertionError("wake should not be used in this test")

        fake_runtime = FakeCliRuntime()
        service = DiscordGatewayService(
            app=app,
            environ={"ELEPHANT_TEST_DISCORD_BOT_TOKEN": "discord-token-123"},
            cli_runtime_factory=lambda profile_dir, state_dir: fake_runtime,
            default_cli_state_dir=str(self.state_dir),
        )
        delivery_transport = self._FakeDiscordDeliveryTransport()

        description = service.describe()
        self.assertTrue(description["control"]["enabled"])
        self.assertEqual(description["control"]["runtime_status"], "ready")
        self.assertEqual(description["control"]["known_elephants"], ("demo",))

        bind_result = asyncio.run(
            service.dispatch_event(
                {
                    "id": "msg-control-bind",
                    "channel_id": "dm-control-1",
                    "content": "/elephant create demo",
                    "chat_type": "direct",
                    "author": {
                        "id": "user-1",
                        "username": "ada",
                        "global_name": "Ada Lovelace",
                    },
                    "attachments": [],
                },
                account_id="ops-discord",
                delivery_transport=delivery_transport,
            )
        )

        self.assertIsNone(bind_result.exchange)
        self.assertEqual(bind_result.response_body["control_mode"], "cli-runtime")
        self.assertEqual(bind_result.response_body["elephant_id"], "demo")
        self.assertEqual(bind_result.response_body["session_id"], expected_session_id)

        result = asyncio.run(
            service.dispatch_event(
                {
                    "id": "msg-control-1",
                    "channel_id": "dm-control-1",
                    "content": "hello from discord control",
                    "chat_type": "direct",
                    "author": {
                        "id": "user-1",
                        "username": "ada",
                        "global_name": "Ada Lovelace",
                    },
                    "attachments": [],
                },
                account_id="ops-discord",
                delivery_transport=delivery_transport,
            )
        )

        self.assertIsNotNone(result.exchange)
        self.assertEqual(result.response_body["elephant_id"], "demo")
        self.assertEqual(result.response_body["state_id"], "state:demo")
        self.assertEqual(result.response_body["session_id"], expected_session_id)
        self.assertEqual(result.response_body["delivery_outcome"], "delivered")
        self.assertEqual(result.response_body["external_message_id"], "discord-reply-1")
        self.assertEqual(
            shared_runtime_calls,
            [
                {
                    "session_id": expected_session_id,
                    "prompt": "hello from discord control",
                    "conversation_id": "dm-control-1",
                }
            ],
        )
        self.assertEqual(len(delivery_transport.requests), 2)
        request, account = delivery_transport.requests[-1]
        self.assertEqual(account.account_id, "ops-discord")
        self.assertEqual(request["path"], "/channels/dm-control-1/messages")
        self.assertEqual(
            request["body"]["content"], "gateway-handled:hello from discord control"
        )
        self.assertEqual(
            request["body"]["message_reference"]["message_id"],
            "msg-control-1",
        )

    def test_discord_adapter_routes_thread_messages_under_parent_channel(self) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"].update(
                {
                    "discord": {
                        "enabled": True,
                        "accounts": [
                            {
                                "account_id": "ops-discord",
                                "env": {"bot_token": "ELEPHANT_TEST_DISCORD_BOT_TOKEN"},
                            }
                        ],
                    }
                }
            )
        )

        app, _, _ = self._build()
        service = DiscordGatewayService(
            app=app,
            environ={"ELEPHANT_TEST_DISCORD_BOT_TOKEN": "discord-token-123"},
        )
        assert service.adapter is not None
        exchange = service.adapter.receive_event(
            {
                "id": "msg-thread-1",
                "channel_id": "thread-42",
                "parent_id": "channel-7",
                "thread_id": "thread-42",
                "guild_id": "guild-1",
                "chat_type": "topic",
                "content": "thread hello",
                "author": {
                    "id": "user-1",
                    "username": "ada",
                    "global_name": "Ada Lovelace",
                },
                "attachments": [],
            },
            account_id="ops-discord",
        )

        self.assertEqual(exchange.route.inbound.conversation_id, "thread-42")
        self.assertEqual(
            exchange.route.inbound.conversation.parent_conversation_id, "channel-7"
        )
        self.assertEqual(exchange.route.inbound.conversation.thread_id, "thread-42")
        self.assertEqual(exchange.route.inbound.chat_type, "topic")
        self.assertEqual(
            exchange.route.session.session_id,
            "session:messaging.discord:ops-discord:thread-42",
        )

    def test_discord_service_should_ignore_bot_self_and_system_sdk_messages(
        self,
    ) -> None:
        app, _, _ = self._build()
        service = DiscordGatewayService(app=app)

        self.assertTrue(
            service.should_ignore_sdk_message(
                SimpleNamespace(
                    author=SimpleNamespace(id="bot-1", bot=True),
                    type=SimpleNamespace(name="default"),
                )
            )
        )
        self.assertTrue(
            service.should_ignore_sdk_message(
                SimpleNamespace(
                    author=SimpleNamespace(id="self-1", bot=False),
                    type=SimpleNamespace(name="default"),
                ),
                self_user_id="self-1",
            )
        )
        self.assertTrue(
            service.should_ignore_sdk_message(
                SimpleNamespace(
                    author=SimpleNamespace(id="user-1", bot=False),
                    type=SimpleNamespace(name="thread_created"),
                )
            )
        )
        self.assertFalse(
            service.should_ignore_sdk_message(
                SimpleNamespace(
                    author=SimpleNamespace(id="user-1", bot=False),
                    type=SimpleNamespace(name="reply"),
                )
            )
        )

    def test_discord_gateway_service_starts_sdk_client_and_dispatches_replies(
        self,
    ) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"].update(
                {
                    "discord": {
                        "enabled": True,
                        "accounts": [
                            {
                                "account_id": "ops-discord",
                                "env": {"bot_token": "ELEPHANT_TEST_DISCORD_BOT_TOKEN"},
                            }
                        ],
                    }
                }
            )
        )

        app, _, _ = self._build()
        requests: list[dict[str, object]] = []
        captured: dict[str, object] = {}

        class FakeAllowedMentions:
            def __init__(self, **kwargs) -> None:
                self.kwargs = kwargs

        class FakeIntents:
            def __init__(self) -> None:
                self.guilds = False
                self.messages = False
                self.message_content = False

            @classmethod
            def none(cls):
                return cls()

        class FakeSentMessage:
            def __init__(self, message_id: str) -> None:
                self.id = message_id

        class FakePartialMessage:
            def __init__(self, channel_id: object, message_id: object) -> None:
                self.channel_id = channel_id
                self.message_id = message_id

            async def reply(
                self, *, content, allowed_mentions=None, mention_author=None, file=None
            ):
                requests.append(
                    {
                        "mode": "reply",
                        "channel_id": self.channel_id,
                        "message_id": self.message_id,
                        "content": content,
                        "allowed_mentions": getattr(allowed_mentions, "kwargs", None),
                        "mention_author": mention_author,
                        "file": file,
                    }
                )
                return FakeSentMessage("discord-send-1")

        class FakeChannel:
            def __init__(self, channel_id: object) -> None:
                self.id = channel_id

            def get_partial_message(self, message_id: object) -> FakePartialMessage:
                return FakePartialMessage(self.id, message_id)

            async def send(self, *, content, allowed_mentions=None):
                requests.append(
                    {
                        "mode": "send",
                        "channel_id": self.id,
                        "content": content,
                        "allowed_mentions": getattr(allowed_mentions, "kwargs", None),
                    }
                )
                return FakeSentMessage("discord-send-2")

        class FakeClient:
            def __init__(self, *, intents) -> None:
                captured["intents"] = intents
                self._events: dict[str, object] = {}
                self.user = SimpleNamespace(id="bot-1")
                self._channel = FakeChannel("2001")

            def event(self, func):
                self._events[func.__name__] = func
                return func

            def get_channel(self, channel_id: object) -> FakeChannel:
                captured["channel_lookup"] = channel_id
                return self._channel

            async def start(self, token: str) -> None:
                captured["token"] = token
                await self._events["on_message"](
                    SimpleNamespace(
                        id="1001",
                        content="hello from sdk",
                        author=SimpleNamespace(
                            id="user-1",
                            bot=False,
                            name="ada",
                            username="ada",
                            global_name="Ada Lovelace",
                        ),
                        channel=SimpleNamespace(id="2001", parent=None),
                        guild=None,
                        attachments=(),
                        reference=None,
                        type=SimpleNamespace(name="default"),
                    )
                )

            async def close(self) -> None:
                captured["closed"] = True

        class FakeDiscord:
            AllowedMentions = FakeAllowedMentions
            Intents = FakeIntents
            Client = FakeClient

        service = DiscordGatewayService(
            app=app,
            environ={"ELEPHANT_TEST_DISCORD_BOT_TOKEN": "discord-token-123"},
        )
        clients = asyncio.run(service.start_gateway(discord_module=FakeDiscord()))

        self.assertEqual(len(clients), 1)
        self.assertEqual(captured["token"], "discord-token-123")
        intents = captured["intents"]
        self.assertTrue(intents.guilds)
        self.assertTrue(intents.messages)
        self.assertTrue(intents.message_content)
        self.assertEqual(captured["channel_lookup"], 2001)
        self.assertTrue(captured["closed"])
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["mode"], "reply")
        self.assertEqual(requests[0]["message_id"], 1001)
        self.assertEqual(
            requests[0]["allowed_mentions"],
            {
                "everyone": False,
                "users": False,
                "roles": False,
                "replied_user": False,
            },
        )
        self.assertFalse(requests[0]["mention_author"])

    def test_discord_delivery_transport_splits_long_reply_content(self) -> None:
        requests: list[dict[str, object]] = []

        class FakeAllowedMentions:
            def __init__(self, **kwargs) -> None:
                self.kwargs = kwargs

        class FakeSentMessage:
            def __init__(self, message_id: str) -> None:
                self.id = message_id

        class FakePartialMessage:
            def __init__(self, channel_id: object, message_id: object) -> None:
                self.channel_id = channel_id
                self.message_id = message_id

            async def reply(
                self, *, content, allowed_mentions=None, mention_author=None, file=None
            ):
                requests.append(
                    {
                        "mode": "reply",
                        "channel_id": self.channel_id,
                        "message_id": self.message_id,
                        "content": content,
                        "allowed_mentions": getattr(allowed_mentions, "kwargs", None),
                        "mention_author": mention_author,
                        "file": file,
                    }
                )
                return FakeSentMessage("discord-reply-1")

        class FakeChannel:
            def __init__(self, channel_id: object) -> None:
                self.id = channel_id
                self.sent_messages = 0

            def get_partial_message(self, message_id: object) -> FakePartialMessage:
                return FakePartialMessage(self.id, message_id)

            async def send(self, *, content, allowed_mentions=None, file=None):
                self.sent_messages += 1
                requests.append(
                    {
                        "mode": "send",
                        "channel_id": self.id,
                        "content": content,
                        "allowed_mentions": getattr(allowed_mentions, "kwargs", None),
                        "file": file,
                    }
                )
                return FakeSentMessage(f"discord-send-{self.sent_messages}")

        class FakeClient:
            def __init__(self) -> None:
                self._channel = FakeChannel("2001")

            def get_channel(self, channel_id: object) -> FakeChannel:
                self.channel_lookup = channel_id
                return self._channel

        class FakeDiscord:
            AllowedMentions = FakeAllowedMentions

        long_content = ("A" * 1500) + "\n" + ("B" * 700)
        transport = DiscordPyDeliveryTransport(
            client=FakeClient(), discord_module=FakeDiscord()
        )

        response = asyncio.run(
            transport.send_request(
                {
                    "channel_id": "2001",
                    "body": {
                        "content": long_content,
                        "message_reference": {"message_id": "1001"},
                    },
                },
                account=SimpleNamespace(account_id="ops-discord"),
            )
        )

        self.assertEqual(response["id"], "discord-reply-1")
        self.assertEqual(response["chunk_count"], 2)
        self.assertEqual(response["delivery_mode"], "chunked")
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0]["mode"], "reply")
        self.assertEqual(requests[1]["mode"], "send")
        self.assertFalse(requests[0]["mention_author"])
        self.assertIsNone(requests[0]["file"])
        self.assertIsNone(requests[1]["file"])
        self.assertEqual(
            "".join(str(item["content"]) for item in requests), long_content
        )
        self.assertTrue(all(len(str(item["content"])) <= 2000 for item in requests))

    def test_discord_reply_request_wraps_command_code_and_formula_blocks(self) -> None:
        app, _, _ = self._build()
        discord = DiscordMessagingAdapter(app=app)

        rendered = discord.build_reply_request(
            GatewayOutboundMessage(
                message_id="discord-rich-1",
                account=GatewayAccountRef(
                    adapter_id=DISCORD_ADAPTER_ID,
                    account_id="ops-discord",
                    surface="discord-gateway",
                ),
                conversation=GatewayConversationRef(
                    conversation_id="dm-1",
                    chat_type="direct",
                ),
                session_id="session:discord-rich-1",
                body=(
                    "Run these commands:\n\n"
                    "uv run -m pytest\n"
                    "git status\n\n"
                    "def add(a, b):\n"
                    "    return a + b\n\n"
                    "x^2 + y^2 = z^2"
                ),
                reply_to_message_id="msg-rich-1",
            )
        )

        content = str(rendered["body"]["content"])
        self.assertIn("```bash\nuv run -m pytest\ngit status\n```", content)
        self.assertIn("```python\ndef add(a, b):\n    return a + b\n```", content)
        self.assertIn("```tex\nx^2 + y^2 = z^2\n```", content)

    def test_discord_delivery_transport_keeps_fenced_blocks_balanced_across_chunks(
        self,
    ) -> None:
        requests: list[dict[str, object]] = []

        class FakeAllowedMentions:
            def __init__(self, **kwargs) -> None:
                self.kwargs = kwargs

        class FakeSentMessage:
            def __init__(self, message_id: str) -> None:
                self.id = message_id

        class FakePartialMessage:
            def __init__(self, channel_id: object, message_id: object) -> None:
                self.channel_id = channel_id
                self.message_id = message_id

            async def reply(
                self, *, content, allowed_mentions=None, mention_author=None, file=None
            ):
                requests.append(
                    {
                        "mode": "reply",
                        "channel_id": self.channel_id,
                        "message_id": self.message_id,
                        "content": content,
                        "allowed_mentions": getattr(allowed_mentions, "kwargs", None),
                        "mention_author": mention_author,
                        "file": file,
                    }
                )
                return FakeSentMessage("discord-fence-reply-1")

        class FakeChannel:
            def __init__(self, channel_id: object) -> None:
                self.id = channel_id
                self.sent_messages = 0

            def get_partial_message(self, message_id: object) -> FakePartialMessage:
                return FakePartialMessage(self.id, message_id)

            async def send(self, *, content, allowed_mentions=None, file=None):
                self.sent_messages += 1
                requests.append(
                    {
                        "mode": "send",
                        "channel_id": self.id,
                        "content": content,
                        "allowed_mentions": getattr(allowed_mentions, "kwargs", None),
                        "file": file,
                    }
                )
                return FakeSentMessage(f"discord-fence-send-{self.sent_messages}")

        class FakeClient:
            def __init__(self) -> None:
                self._channel = FakeChannel("2001")

            def get_channel(self, channel_id: object) -> FakeChannel:
                self.channel_lookup = channel_id
                return self._channel

        class FakeDiscord:
            AllowedMentions = FakeAllowedMentions

        long_content = "```python\n" + ("print('chunk-safe')\n" * 220) + "```"
        transport = DiscordPyDeliveryTransport(
            client=FakeClient(), discord_module=FakeDiscord()
        )

        response = asyncio.run(
            transport.send_request(
                {
                    "channel_id": "2001",
                    "body": {
                        "content": long_content,
                        "message_reference": {"message_id": "1001"},
                    },
                },
                account=SimpleNamespace(account_id="ops-discord"),
            )
        )

        self.assertEqual(response["delivery_mode"], "chunked")
        self.assertGreater(len(requests), 1)
        self.assertEqual(response["chunk_count"], len(requests))
        self.assertTrue(all(len(str(item["content"])) <= 2000 for item in requests))
        self.assertTrue(
            all(str(item["content"]).count("```") % 2 == 0 for item in requests)
        )
        self.assertTrue(str(requests[0]["content"]).startswith("```python"))
        self.assertTrue(str(requests[-1]["content"]).rstrip().endswith("```"))

    def test_discord_delivery_transport_uses_attachment_fallback_for_very_long_reply(
        self,
    ) -> None:
        requests: list[dict[str, object]] = []

        class FakeAllowedMentions:
            def __init__(self, **kwargs) -> None:
                self.kwargs = kwargs

        class FakeFile:
            def __init__(self, *, fp, filename, description=None) -> None:
                self.filename = filename
                self.description = description
                self.content = fp.read().decode("utf-8")

        class FakeSentMessage:
            def __init__(self, message_id: str) -> None:
                self.id = message_id

        class FakePartialMessage:
            def __init__(self, channel_id: object, message_id: object) -> None:
                self.channel_id = channel_id
                self.message_id = message_id

            async def reply(
                self, *, content, allowed_mentions=None, mention_author=None, file=None
            ):
                requests.append(
                    {
                        "mode": "reply",
                        "channel_id": self.channel_id,
                        "message_id": self.message_id,
                        "content": content,
                        "allowed_mentions": getattr(allowed_mentions, "kwargs", None),
                        "mention_author": mention_author,
                        "file": file,
                    }
                )
                return FakeSentMessage("discord-reply-attachment")

        class FakeChannel:
            def __init__(self, channel_id: object) -> None:
                self.id = channel_id

            def get_partial_message(self, message_id: object) -> FakePartialMessage:
                return FakePartialMessage(self.id, message_id)

            async def send(self, *, content, allowed_mentions=None, file=None):
                requests.append(
                    {
                        "mode": "send",
                        "channel_id": self.id,
                        "content": content,
                        "allowed_mentions": getattr(allowed_mentions, "kwargs", None),
                        "file": file,
                    }
                )
                return FakeSentMessage("discord-send-attachment")

        class FakeClient:
            def __init__(self) -> None:
                self._channel = FakeChannel("2001")

            def get_channel(self, channel_id: object) -> FakeChannel:
                self.channel_lookup = channel_id
                return self._channel

        class FakeDiscord:
            AllowedMentions = FakeAllowedMentions
            File = FakeFile

        long_content = "HTTP SERVER\n" * 900
        transport = DiscordPyDeliveryTransport(
            client=FakeClient(), discord_module=FakeDiscord()
        )

        response = asyncio.run(
            transport.send_request(
                {
                    "channel_id": "2001",
                    "body": {
                        "content": long_content,
                        "message_reference": {"message_id": "1001"},
                    },
                },
                account=SimpleNamespace(account_id="ops-discord"),
            )
        )

        self.assertEqual(response["id"], "discord-reply-attachment")
        self.assertEqual(response["delivery_mode"], "attachment")
        self.assertEqual(response["attachment_filename"], "reply.md")
        self.assertEqual(response["chunk_count"], 1)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["mode"], "reply")
        self.assertFalse(requests[0]["mention_author"])
        self.assertIn(
            "Reply too long for Discord inline delivery", str(requests[0]["content"])
        )
        self.assertIsNotNone(requests[0]["file"])
        self.assertEqual(requests[0]["file"].filename, "reply.md")
        self.assertEqual(requests[0]["file"].description, "Full Discord reply body")
        self.assertEqual(requests[0]["file"].content, long_content)

    def test_discord_gateway_service_skips_blocked_enabled_accounts_during_multi_start(
        self,
    ) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"].update(
                {
                    "discord": {
                        "enabled": True,
                        "accounts": [
                            {
                                "account_id": "ops-discord",
                                "enabled": True,
                                "env": {"bot_token": "ELEPHANT_TEST_DISCORD_BOT_TOKEN"},
                            },
                            {
                                "account_id": "shadow-discord",
                                "enabled": True,
                                "env": {
                                    "bot_token": "ELEPHANT_MISSING_DISCORD_BOT_TOKEN"
                                },
                            },
                        ],
                    }
                }
            )
        )
        app, _, _ = self._build()
        captured_tokens: list[str] = []

        class FakeIntents:
            @staticmethod
            def none() -> "FakeIntents":
                intents = FakeIntents()
                intents.guilds = False
                intents.messages = False
                intents.message_content = False
                return intents

        class FakeAllowedMentions:
            def __init__(self, **kwargs) -> None:
                self.payload = dict(kwargs)

        class FakeClient:
            def __init__(self, *, intents) -> None:
                self.intents = intents
                self.user = SimpleNamespace(id="bot-1")

            def event(self, handler):
                self.on_message = handler
                return handler

            async def start(self, token: str) -> None:
                captured_tokens.append(token)

            async def close(self) -> None:
                return None

        class FakeDiscord:
            AllowedMentions = FakeAllowedMentions
            Intents = FakeIntents
            Client = FakeClient

        service = DiscordGatewayService(
            app=app,
            environ={"ELEPHANT_TEST_DISCORD_BOT_TOKEN": "discord-token-123"},
        )
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            clients = asyncio.run(service.start_gateway(discord_module=FakeDiscord()))

        self.assertEqual(len(clients), 1)
        self.assertEqual(captured_tokens, ["discord-token-123"])
        self.assertIn("Skipping Discord account 'shadow-discord'", stderr.getvalue())
        self.assertEqual(
            service.describe()["account_status"]["service_status"], "degraded"
        )


if __name__ == "__main__":
    unittest.main()
