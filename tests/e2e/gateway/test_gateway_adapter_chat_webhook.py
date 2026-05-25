from __future__ import annotations

import unittest

from apps.gateway import CHAT_BOT_ADAPTER_ID, WEBHOOK_ADAPTER_ID
from packages.gateway_core import DEFAULT_GATEWAY_ACCOUNT_ID
from packages.security.runtime import PolicyDecision
from tests.e2e.gateway.gateway_adapter_test_base import GatewayAdapterTestBase


class GatewayAdapterChatWebhookE2ETests(GatewayAdapterTestBase):
    def test_chat_bot_identity_mapping_and_session_reuse_persist_across_restart(self) -> None:
        app, chat_adapter, _ = self._build()
        self._bind_gateway_conversation(
            app,
            adapter_id=CHAT_BOT_ADAPTER_ID,
            conversation_id="chat-1",
        )

        first = chat_adapter.receive_text(
            conversation_id="chat-1",
            external_user_id="user-1",
            body="hello",
            display_name="Ada",
            event_id="evt-1",
        )
        self.assertFalse(first.route.is_new_session)
        self.assertEqual(first.delivery.outcome, "delivered")
        self.assertIsNotNone(first.delivery.outbound)
        assert first.delivery.outbound is not None
        self.assertEqual(
            first.delivery.outbound.metadata["runtime_surface"],
            "gateway.shared-runtime",
        )
        self.assertEqual(
            first.delivery.outbound.metadata["provider_id"],
            "openai-compatible",
        )
        self.assertTrue(first.delivery.outbound.metadata["context_bundle_id"].startswith("bundle:"))
        self.assertNotEqual(first.delivery.outbound.body, "ack: hello")
        first_records = app.recall_evidence_records(first.route.session.session_id)
        self.assertEqual(
            tuple(record.metadata.get("raw_user_query") for record in first_records if record.kind == "effective_user_query"),
            ("hello",),
        )
        self.assertEqual(len(tuple(record for record in first_records if record.kind == "emit_response")), 1)

        restarted_app, restarted_chat, _ = self._build()
        second = restarted_chat.receive_text(
            conversation_id="chat-1",
            external_user_id="user-1",
            body="follow-up",
            display_name="Ada Lovelace",
            event_id="evt-2",
        )

        self.assertFalse(second.route.is_new_session)
        self.assertEqual(first.route.identity.mapping_id, second.route.identity.mapping_id)
        self.assertEqual(first.route.identity.session_id, second.route.identity.session_id)
        self.assertEqual(second.route.identity.key.account_id, DEFAULT_GATEWAY_ACCOUNT_ID)
        self.assertEqual(second.route.inbound.account.account_id, DEFAULT_GATEWAY_ACCOUNT_ID)
        self.assertEqual(second.route.identity.display_name, "Ada Lovelace")
        self.assertEqual(
            second.route.session.session_id,
            f"session:{CHAT_BOT_ADAPTER_ID}:{DEFAULT_GATEWAY_ACCOUNT_ID}:chat-1",
        )
        self.assertEqual(second.route.session.profile_id, "you")
        self.assertIsNotNone(second.delivery.outbound)
        assert second.delivery.outbound is not None
        second_records = restarted_app.recall_evidence_records(second.route.session.session_id)
        self.assertEqual(
            tuple(record.metadata.get("raw_user_query") for record in second_records if record.kind == "effective_user_query"),
            ("hello", "follow-up"),
        )
        self.assertEqual(len(tuple(record for record in second_records if record.kind == "emit_response")), 2)
        self.assertEqual(len(restarted_app.identity_records()), 1)
        self.assertEqual(len(restarted_app.session_records()), 1)

    def test_chat_bot_identity_mapping_separates_accounts(self) -> None:
        app, chat_adapter, _ = self._build()
        self._bind_gateway_conversation(
            app,
            adapter_id=CHAT_BOT_ADAPTER_ID,
            account_id="ops-bot",
            conversation_id="chat-1",
        )
        self._bind_gateway_conversation(
            app,
            adapter_id=CHAT_BOT_ADAPTER_ID,
            account_id="support-bot",
            conversation_id="chat-1",
        )

        first = chat_adapter.receive_text(
            account_id="ops-bot",
            conversation_id="chat-1",
            external_user_id="user-1",
            body="hello",
            event_id="evt-ops",
        )
        second = chat_adapter.receive_text(
            account_id="support-bot",
            conversation_id="chat-1",
            external_user_id="user-1",
            body="hello again",
            event_id="evt-support",
        )

        self.assertNotEqual(first.route.identity.mapping_id, second.route.identity.mapping_id)
        self.assertNotEqual(first.route.session.session_id, second.route.session.session_id)
        self.assertEqual(first.route.identity.key.account_id, "ops-bot")
        self.assertEqual(second.route.identity.key.account_id, "support-bot")
        self.assertEqual(first.route.session.session_id, f"session:{CHAT_BOT_ADAPTER_ID}:ops-bot:chat-1")
        self.assertEqual(second.route.session.session_id, f"session:{CHAT_BOT_ADAPTER_ID}:support-bot:chat-1")
        self.assertEqual(len(app.identity_records()), 2)
        self.assertEqual(len(app.session_records()), 2)

    def test_webhook_delivery_normalizes_callback_metadata(self) -> None:
        app, _, webhook_adapter = self._build()
        self._bind_gateway_conversation(
            app,
            adapter_id=WEBHOOK_ADAPTER_ID,
            conversation_id="case-9",
        )

        exchange = webhook_adapter.receive_event(
            {
                "event_id": "webhook-1",
                "conversation_id": "case-9",
                "external_user_id": "customer-7",
                "body": "Need a status update.",
                "display_name": "Grace",
                "callback_url": "https://example.com/reply",
                "attachments": ["case.pdf", "case.pdf"],
                "metadata": {"source": "crm"},
            },
            reply_body="Ticket received.",
            target_trusted=True,
            consent_given=True,
        )

        self.assertEqual(exchange.delivery.outcome, "delivered")
        self.assertEqual(exchange.delivery.policy_result.decision, PolicyDecision.ALLOW)
        self.assertIsNotNone(exchange.delivery.outbound)
        assert exchange.delivery.outbound is not None
        self.assertEqual(
            exchange.delivery.outbound.session_id,
            f"session:{WEBHOOK_ADAPTER_ID}:{DEFAULT_GATEWAY_ACCOUNT_ID}:case-9",
        )
        self.assertEqual(exchange.delivery.outbound.attachments, ("case.pdf",))
        self.assertEqual(
            exchange.delivery.outbound.metadata["callback_url"],
            "https://example.com/reply",
        )
        self.assertEqual(exchange.delivery.outbound.metadata["source"], "crm")
        self.assertEqual(
            exchange.delivery.outbound.metadata["runtime_surface"],
            "gateway.shared-runtime",
        )
        self.assertEqual(exchange.delivery.external_message_id, exchange.delivery.outbound.message_id)

    def test_untrusted_webhook_delivery_is_blocked(self) -> None:
        app, _, webhook_adapter = self._build()
        self._bind_gateway_conversation(
            app,
            adapter_id=WEBHOOK_ADAPTER_ID,
            conversation_id="case-10",
        )

        exchange = webhook_adapter.receive_event(
            {
                "event_id": "webhook-2",
                "conversation_id": "case-10",
                "external_user_id": "customer-8",
                "body": "Send this outside.",
            },
            reply_body="blocked",
            target_trusted=False,
            consent_given=False,
            is_external=True,
        )

        self.assertEqual(exchange.delivery.outcome, "blocked")
        self.assertEqual(exchange.delivery.policy_result.decision, PolicyDecision.REVIEW)
        self.assertIsNone(exchange.delivery.outbound)
        self.assertIn(
            "recipient-verification",
            exchange.delivery.policy_result.required_controls,
        )



if __name__ == "__main__":
    unittest.main()
