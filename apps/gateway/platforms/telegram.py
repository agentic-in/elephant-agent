"""Telegram adapter and platform registration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from packages.gateway_core import (
    DEFAULT_GATEWAY_ACCOUNT_ID,
    GatewayExchange,
    GatewayInboundMessage,
)

from ..plugins import GatewayAdapterDescriptor, GatewayServicePluginRegistration
from ..runtime_app import GatewayApp
from ..runtime_support import (
    TELEGRAM_ADAPTER_ID,
    _account_ref,
    _attachment_refs,
    _conversation_ref,
    _normalized_chat_type,
    _policy_hint,
    _sender_ref,
    _telegram_attachment_ids,
    _telegram_conversation_id,
    _telegram_delivery_defaults,
    _telegram_display_name,
)


@dataclass(frozen=True, slots=True)
class TelegramMessagingAdapter:
    app: GatewayApp
    adapter_id: str = TELEGRAM_ADAPTER_ID

    def receive_update(
        self,
        payload: Mapping[str, object],
        *,
        account_id: str = DEFAULT_GATEWAY_ACCOUNT_ID,
        reply_body: str | None = None,
        target_trusted: bool | None = None,
        consent_given: bool | None = None,
        is_external: bool | None = None,
    ) -> GatewayExchange:
        update_kind = "message"
        message = payload.get("message")
        callback_data: str | None = None
        if not isinstance(message, Mapping):
            message = payload.get("edited_message")
            if isinstance(message, Mapping):
                update_kind = "edited_message"
        if not isinstance(message, Mapping):
            callback_query = payload.get("callback_query")
            if isinstance(callback_query, Mapping):
                nested_message = callback_query.get("message")
                if isinstance(nested_message, Mapping):
                    message = nested_message
                    update_kind = "callback_query"
                    if callback_query.get("data") is not None:
                        callback_data = str(callback_query["data"])
                    if not isinstance(message.get("from"), Mapping) and isinstance(callback_query.get("from"), Mapping):
                        message = {
                            **message,
                            "from": callback_query["from"],
                        }
        if not isinstance(message, Mapping):
            raise ValueError("telegram update requires message, edited_message, or callback_query.message")
        chat = message.get("chat")
        sender = message.get("from")
        if not isinstance(chat, Mapping) or not isinstance(sender, Mapping):
            raise ValueError("telegram update requires chat and from payloads")
        chat_id = str(chat["id"])
        chat_type = str(chat.get("type") or "private")
        thread_id = message.get("message_thread_id")
        normalized_chat_type = _normalized_chat_type(chat_type)
        attachment_refs = _attachment_refs(_telegram_attachment_ids(message))
        message_id = str(message["message_id"]) if message.get("message_id") is not None else None
        metadata = {
            "channel": "telegram",
            "chat_type": chat_type,
            "update_kind": update_kind,
            "chat_id": chat_id,
        }
        if message_id is not None:
            metadata["message_id"] = message_id
        if sender.get("username") is not None:
            metadata["username"] = str(sender["username"])
        if thread_id is not None:
            metadata["message_thread_id"] = str(thread_id)
        if message.get("reply_to_message") is not None:
            metadata["reply_to_message_id"] = str(dict(message["reply_to_message"]).get("message_id") or "")
        if callback_data is not None:
            metadata["callback_data"] = callback_data
        target_trusted_default, consent_default, external_default = _telegram_delivery_defaults(chat_type)
        resolved_thread_id = str(thread_id) if thread_id is not None else None
        inbound = GatewayInboundMessage(
            event_id=str(payload.get("update_id") or message.get("message_id") or chat["id"]),
            account=_account_ref(
                self.adapter_id,
                account_id=account_id,
                surface="telegram-bot-api",
            ),
            conversation=_conversation_ref(
                _telegram_conversation_id(chat_id, thread_id),
                parent_conversation_id=chat_id if resolved_thread_id is not None else None,
                thread_id=resolved_thread_id,
                chat_type=normalized_chat_type,
                metadata={"raw_chat_type": chat_type},
            ),
            sender=_sender_ref(
                str(sender["id"]),
                display_name=_telegram_display_name(sender),
                username=(f"@{str(sender['username'])}" if sender.get("username") is not None else None),
                is_bot=bool(sender.get("is_bot", False)),
            ),
            body=str(message.get("text") or message.get("caption") or callback_data or "telegram-event"),
            reply_to_message_id=(str(metadata.get("reply_to_message_id") or message_id or "") or None),
            attachment_refs=attachment_refs,
            policy_hint=_policy_hint(
                target_trusted_default=(target_trusted_default if target_trusted is None else target_trusted),
                consent_default=consent_default if consent_given is None else consent_given,
                is_external_default=external_default if is_external is None else is_external,
                audience_scope=normalized_chat_type,
                metadata={"raw_chat_type": chat_type},
            ),
            metadata=metadata,
        )
        return self.app.handle_message(
            inbound,
            reply_body=reply_body,
            reply_to_message_id=inbound.reply_to_message_id or inbound.event_id,
            attachment_refs=attachment_refs,
            metadata={
                **metadata,
                "delivery_surface": "telegram-bot-api",
            },
        )


@dataclass(frozen=True, slots=True)
class TelegramGatewayPlatform:
    key: str = "telegram"

    def adapter_descriptor(self) -> GatewayAdapterDescriptor:
        return GatewayAdapterDescriptor(
            key=self.key,
            adapter_id=TELEGRAM_ADAPTER_ID,
            surface="telegram-bot-api",
            default_account_id=DEFAULT_GATEWAY_ACCOUNT_ID,
            operator_action="configure TELEGRAM_BOT_TOKEN and forward Bot API updates into the gateway",
            identity_mapping="account_id + chat.id + from.id (+ message_thread_id when present)",
            supported_updates=("message", "edited_message", "callback_query"),
            delivery_defaults={
                "private": "allow",
                "group": "review",
                "supergroup": "review",
                "channel": "review",
            },
        )

    def build_adapter(self, app: GatewayApp) -> object:
        return TelegramMessagingAdapter(app=app)

    def service_registrations(self) -> tuple[GatewayServicePluginRegistration, ...]:
        from ..telegram import TelegramGatewayService

        return (
            GatewayServicePluginRegistration(
                key="telegram",
                factory=lambda app, **kwargs: TelegramGatewayService(app=app, **kwargs),
                enabled_by_default=False,
            ),
        )


TELEGRAM_PLATFORM = TelegramGatewayPlatform()

__all__ = ["TELEGRAM_PLATFORM", "TelegramGatewayPlatform", "TelegramMessagingAdapter"]
