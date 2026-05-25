from __future__ import annotations

import json
import unittest

from apps.gateway import (
    FEISHU_ADAPTER_ID,
    FeishuMessagingAdapter,
)
from packages.gateway_core import GatewayAccountRef, GatewayConversationRef, GatewayOutboundMessage
from packages.security.runtime import PolicyDecision
from tests.e2e.gateway.gateway_adapter_test_base import GatewayAdapterTestBase


class GatewayAdapterFeishuEventsE2ETests(GatewayAdapterTestBase):
    def test_feishu_p2p_event_reuses_identity_mapping_across_restart(self) -> None:
        app, _, _ = self._build()
        feishu = FeishuMessagingAdapter(app=app)

        first = feishu.receive_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-feishu-1",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                    "tenant_key": "tenant-alpha",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_ada"},
                        "sender_type": "user",
                        "name": "Ada",
                    },
                    "message": {
                        "message_id": "om_direct_1",
                        "chat_id": "oc_direct_1",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "hello from feishu"}),
                    },
                },
            },
            reply_body="pong",
        )
        self.assertTrue(first.route.is_new_session)
        self.assertEqual(first.route.identity.key.account_id, "cli_feishu_bot")
        self.assertEqual(first.route.inbound.account.tenant_id, "tenant-alpha")
        self.assertEqual(first.route.inbound.chat_type, "direct")
        self.assertEqual(first.delivery.policy_result.decision, PolicyDecision.ALLOW)
        self.assertIsNotNone(first.delivery.outbound)
        assert first.delivery.outbound is not None
        self.assertEqual(
            first.delivery.outbound.session_id,
            f"session:{FEISHU_ADAPTER_ID}:cli_feishu_bot:oc_direct_1",
        )

        restarted_app, _, _ = self._build()
        restarted = FeishuMessagingAdapter(app=restarted_app)
        second = restarted.receive_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-feishu-2",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                    "tenant_key": "tenant-alpha",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_ada"},
                        "sender_type": "user",
                        "display_name": "Ada Lovelace",
                    },
                    "message": {
                        "message_id": "om_direct_2",
                        "chat_id": "oc_direct_1",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": "follow-up"}),
                    },
                },
            }
        )

        self.assertFalse(second.route.is_new_session)
        self.assertEqual(first.route.identity.mapping_id, second.route.identity.mapping_id)
        self.assertEqual(second.route.identity.display_name, "Ada Lovelace")
        self.assertEqual(
            second.route.session.session_id,
            f"session:{FEISHU_ADAPTER_ID}:cli_feishu_bot:oc_direct_1",
        )
        self.assertEqual(len(restarted_app.identity_records()), 1)
        self.assertEqual(len(restarted_app.session_records()), 1)

    def test_feishu_group_thread_defaults_to_review_and_builds_reply_request(self) -> None:
        app, _, _ = self._build()
        feishu = FeishuMessagingAdapter(app=app)

        exchange = feishu.receive_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-feishu-3",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                    "tenant_key": "tenant-alpha",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_grace"},
                        "sender_type": "user",
                        "name": "Grace",
                    },
                    "message": {
                        "message_id": "om_group_2",
                        "root_id": "om_group_root",
                        "parent_id": "om_group_parent",
                        "chat_id": "oc_group_1",
                        "chat_type": "group",
                        "message_type": "text",
                        "content": json.dumps({"text": "Need an answer here."}),
                    },
                },
            },
            reply_body="Working on it.",
        )

        self.assertEqual(exchange.route.inbound.conversation_id, "oc_group_1:om_group_root")
        self.assertEqual(exchange.route.inbound.parent_conversation_id, "oc_group_1")
        self.assertEqual(exchange.route.inbound.thread_id, "om_group_root")
        self.assertEqual(exchange.route.inbound.reply_to_message_id, "om_group_parent")
        self.assertEqual(exchange.route.inbound.chat_type, "group")
        self.assertEqual(
            exchange.route.session.session_id,
            f"session:{FEISHU_ADAPTER_ID}:cli_feishu_bot:oc_group_1:om_group_root",
        )
        self.assertEqual(exchange.delivery.outcome, "blocked")
        self.assertEqual(exchange.delivery.policy_result.decision, PolicyDecision.REVIEW)
        self.assertIsNone(exchange.delivery.outbound)

        rendered = feishu.build_reply_request(
            GatewayOutboundMessage(
                message_id="delivery-1",
                account=GatewayAccountRef(
                    adapter_id=FEISHU_ADAPTER_ID,
                    account_id="cli_feishu_bot",
                    tenant_id="tenant-alpha",
                    surface="feishu-long-connection",
                ),
                conversation=GatewayConversationRef(
                    conversation_id="oc_group_1:om_group_root",
                    parent_conversation_id="oc_group_1",
                    thread_id="om_group_root",
                    chat_type="group",
                ),
                session_id="session:ignored",
                body="# Working on it\n\n- Check session state\n- Send the next update",
                reply_to_message_id="om_group_2",
            )
        )
        self.assertEqual(
            rendered["path"],
            "/open-apis/im/v1/messages/om_group_2/reply",
        )
        self.assertEqual(rendered["body"]["msg_type"], "interactive")
        self.assertTrue(rendered["body"]["reply_in_thread"])
        content = json.loads(rendered["body"]["content"])
        self.assertEqual(content["schema"], "2.0")
        self.assertEqual(content["header"]["title"]["content"], "Working on it")
        self.assertEqual(content["header"]["padding"], "12px 12px 12px 12px")
        self.assertTrue(content["config"]["wide_screen_mode"])
        self.assertEqual(content["body"]["direction"], "vertical")
        self.assertEqual(content["body"]["padding"], "12px 12px 12px 12px")
        self.assertEqual(
            content["body"]["elements"],
            [
                {
                    "tag": "markdown",
                    "content": "- Check session state\n- Send the next update",
                    "text_align": "left",
                }
            ],
        )
        self.assertLessEqual(len(rendered["body"]["uuid"]), 50)
        self.assertTrue(rendered["body"]["uuid"].startswith("elephant-"))

    def test_feishu_reply_request_wraps_command_code_and_formula_blocks(self) -> None:
        app, _, _ = self._build()
        feishu = FeishuMessagingAdapter(app=app)

        rendered = feishu.build_reply_request(
            GatewayOutboundMessage(
                message_id="feishu-rich-1",
                account=GatewayAccountRef(
                    adapter_id=FEISHU_ADAPTER_ID,
                    account_id="cli_feishu_bot",
                    tenant_id="tenant-alpha",
                    surface="feishu-long-connection",
                ),
                conversation=GatewayConversationRef(
                    conversation_id="oc_direct_1",
                    chat_type="direct",
                ),
                session_id="session:feishu-rich-1",
                body=(
                    "Run these commands:\n\n"
                    "uv run -m pytest\n"
                    "git status\n\n"
                    "def add(a, b):\n"
                    "    return a + b\n\n"
                    "x^2 + y^2 = z^2"
                ),
                reply_to_message_id="om-rich-1",
            )
        )

        self.assertEqual(rendered["body"]["msg_type"], "interactive")
        content = json.loads(rendered["body"]["content"])
        self.assertEqual(content["schema"], "2.0")
        self.assertEqual(content["header"]["title"]["content"], "Elephant Agent")
        self.assertEqual(content["body"]["elements"][0]["tag"], "markdown")
        self.assertEqual(
            content["body"]["elements"][0]["content"],
            (
                "Run these commands:\n\n"
                "```bash\n"
                "uv run -m pytest\n"
                "git status\n"
                "```\n\n"
                "```python\n"
                "def add(a, b):\n"
                "    return a + b\n"
                "```\n\n"
                "```latex\n"
                "x^2 + y^2 = z^2\n"
                "```"
            ),
        )

    def test_feishu_post_message_body_preserves_rich_text_rows(self) -> None:
        app, _, _ = self._build()
        feishu = FeishuMessagingAdapter(app=app)

        inbound = feishu.normalize_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-feishu-post-command",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                    "tenant_key": "tenant-alpha",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_post_user"},
                        "sender_type": "user",
                        "name": "Post User",
                    },
                    "message": {
                        "message_id": "om_post_command",
                        "chat_id": "oc_direct_post",
                        "chat_type": "p2p",
                        "message_type": "post",
                        "content": json.dumps(
                            {
                                "title": "",
                                "content": [
                                    [
                                        {"tag": "text", "text": "- "},
                                        {"tag": "text", "text": "/elephant create leo"},
                                    ]
                                ],
                            }
                        ),
                    },
                },
            }
        )

        self.assertEqual(inbound.body, "- /elephant create leo")
        self.assertEqual(inbound.metadata["message_type"], "post")

    def test_feishu_attachment_refs_preserve_kind_order_and_dedupe_ids(self) -> None:
        app, _, _ = self._build()
        feishu = FeishuMessagingAdapter(app=app)

        inbound = feishu.normalize_event(
            {
                "schema": "2.0",
                "header": {
                    "event_id": "evt-feishu-attachments",
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_feishu_bot",
                    "tenant_key": "tenant-alpha",
                },
                "event": {
                    "sender": {
                        "sender_id": {"open_id": "ou_files"},
                        "sender_type": "user",
                        "name": "Ada Files",
                    },
                    "message": {
                        "message_id": "om_attach_1",
                        "chat_id": "oc_direct_attach",
                        "chat_type": "p2p",
                        "message_type": "file",
                        "content": json.dumps(
                            {
                                "image_key": "img-1",
                                "file_key": "file-1",
                                "audio_key": "audio-1",
                                "media_key": "media-1",
                            }
                        ),
                    },
                },
            }
        )

        self.assertEqual(inbound.attachments, ("img-1", "file-1", "audio-1", "media-1"))
        self.assertEqual(
            tuple((ref.attachment_id, ref.kind) for ref in inbound.attachment_refs),
            (
                ("img-1", "image"),
                ("file-1", "file"),
                ("audio-1", "audio"),
                ("media-1", "media"),
            ),
        )


if __name__ == "__main__":
    unittest.main()
