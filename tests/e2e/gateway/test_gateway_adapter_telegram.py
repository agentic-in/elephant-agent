from __future__ import annotations

import unittest

from apps.gateway import TELEGRAM_ADAPTER_ID, TelegramMessagingAdapter
from packages.gateway_core import DEFAULT_GATEWAY_ACCOUNT_ID
from packages.security.runtime import PolicyDecision
from tests.e2e.gateway.gateway_adapter_test_base import GatewayAdapterTestBase


class GatewayAdapterTelegramE2ETests(GatewayAdapterTestBase):
    def test_interruption_state_is_preserved_when_chat_resumes(self) -> None:
        app, chat_adapter, _ = self._build()

        first = chat_adapter.receive_text(
            conversation_id="chat-2",
            external_user_id="user-2",
            body="pause here",
            event_id="evt-3",
        )
        interrupted = app.interrupt_episode(
            first.route.session.session_id,
            interruption_state="awaiting-operator-reply",
        )

        self.assertEqual(interrupted.status, "interrupted")
        self.assertEqual(interrupted.interruption_state, "awaiting-operator-reply")

        restarted_app, restarted_chat, _ = self._build()
        resumed = restarted_chat.receive_text(
            conversation_id="chat-2",
            external_user_id="user-2",
            body="back again",
            event_id="evt-4",
        )

        self.assertFalse(resumed.route.is_new_session)
        self.assertEqual(resumed.route.session.status, "interrupted")
        self.assertEqual(
            resumed.route.session.interruption_state,
            "awaiting-operator-reply",
        )
        self.assertEqual(
            restarted_app.session_records()[0].interruption_state,
            "awaiting-operator-reply",
        )

    def test_telegram_private_update_reuses_identity_mapping_across_restart(self) -> None:
        app, _, _ = self._build()
        telegram = TelegramMessagingAdapter(app=app)

        first = telegram.receive_update(
            {
                "update_id": 9001,
                "message": {
                    "message_id": 42,
                    "chat": {"id": 55, "type": "private"},
                    "from": {"id": 7, "first_name": "Ada", "last_name": "Lovelace"},
                    "text": "hello from telegram",
                },
            },
        )
        self.assertTrue(first.route.is_new_session)
        self.assertEqual(first.delivery.outcome, "delivered")

        restarted_app, _, _ = self._build()
        restarted = TelegramMessagingAdapter(app=restarted_app)
        second = restarted.receive_update(
            {
                "update_id": 9002,
                "edited_message": {
                    "message_id": 43,
                    "chat": {"id": 55, "type": "private"},
                    "from": {"id": 7, "username": "ada"},
                    "text": "follow-up",
                },
            }
        )

        self.assertFalse(second.route.is_new_session)
        self.assertEqual(first.route.identity.mapping_id, second.route.identity.mapping_id)
        self.assertEqual(
            second.route.session.session_id,
            f"session:{TELEGRAM_ADAPTER_ID}:{DEFAULT_GATEWAY_ACCOUNT_ID}:55",
        )
        self.assertEqual(second.route.identity.display_name, "@ada")
        self.assertEqual(second.delivery.policy_result.decision, PolicyDecision.ALLOW)
        self.assertEqual(second.route.inbound.chat_type, "direct")
        self.assertEqual(len(restarted_app.identity_records()), 1)
        self.assertEqual(len(restarted_app.session_records()), 1)

    def test_telegram_group_update_defaults_to_review_and_tracks_thread(self) -> None:
        app, _, _ = self._build()
        telegram = TelegramMessagingAdapter(app=app)

        exchange = telegram.receive_update(
            {
                "update_id": 9003,
                "callback_query": {
                    "data": "approve",
                    "message": {
                        "message_id": 44,
                        "message_thread_id": 9,
                        "chat": {"id": -10012345, "type": "supergroup"},
                        "from": {"id": 8, "username": "grace"},
                        "caption": "Need an answer here.",
                        "photo": [
                            {"file_id": "photo-1"},
                            {"file_id": "photo-1"},
                        ],
                        "document": {"file_id": "doc-1"},
                    },
                },
            },
        )

        self.assertEqual(exchange.route.identity.key.adapter_id, TELEGRAM_ADAPTER_ID)
        self.assertEqual(exchange.route.identity.display_name, "@grace")
        self.assertEqual(exchange.route.inbound.conversation_id, "-10012345:9")
        self.assertEqual(
            exchange.route.session.session_id,
            f"session:{TELEGRAM_ADAPTER_ID}:{DEFAULT_GATEWAY_ACCOUNT_ID}:-10012345:9",
        )
        self.assertEqual(exchange.route.inbound.parent_conversation_id, "-10012345")
        self.assertEqual(exchange.route.inbound.thread_id, "9")
        self.assertEqual(exchange.route.inbound.chat_type, "group")
        self.assertEqual(exchange.route.inbound.attachments, ("photo-1", "doc-1"))
        self.assertEqual(exchange.route.inbound.metadata["update_kind"], "callback_query")
        self.assertEqual(exchange.route.inbound.metadata["message_thread_id"], "9")
        self.assertEqual(exchange.delivery.outcome, "blocked")
        self.assertEqual(exchange.delivery.policy_result.decision, PolicyDecision.REVIEW)
        self.assertIsNone(exchange.delivery.outbound)
        self.assertIn(
            "recipient-verification",
            exchange.delivery.policy_result.required_controls,
        )


if __name__ == "__main__":
    unittest.main()
