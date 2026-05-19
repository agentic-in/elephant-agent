"""Local chat adapter and platform registration."""

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
    CHAT_BOT_ADAPTER_ID,
    _account_ref,
    _attachment_refs,
    _conversation_ref,
    _object_map,
    _policy_hint,
    _sender_ref,
)


@dataclass(frozen=True, slots=True)
class ChatBotMessagingAdapter:
    app: GatewayApp
    adapter_id: str = CHAT_BOT_ADAPTER_ID

    def receive_text(
        self,
        *,
        conversation_id: str,
        external_user_id: str,
        body: str,
        account_id: str = DEFAULT_GATEWAY_ACCOUNT_ID,
        display_name: str | None = None,
        event_id: str | None = None,
        attachments: tuple[str, ...] = (),
        metadata: Mapping[str, object] | None = None,
        reply_body: str | None = None,
        target_trusted: bool = True,
        consent_given: bool = True,
        is_external: bool = False,
    ) -> GatewayExchange:
        attachment_refs = _attachment_refs(attachments)
        inbound_metadata = _object_map(metadata)
        inbound = GatewayInboundMessage(
            event_id=event_id or f"{self.adapter_id}:{conversation_id}:{external_user_id}",
            account=_account_ref(
                self.adapter_id,
                account_id=account_id,
                surface="local-chat",
            ),
            conversation=_conversation_ref(conversation_id, chat_type="direct"),
            sender=_sender_ref(external_user_id, display_name=display_name),
            body=body,
            attachment_refs=attachment_refs,
            policy_hint=_policy_hint(
                target_trusted_default=target_trusted,
                consent_default=consent_given,
                is_external_default=is_external,
                audience_scope="direct",
            ),
            metadata=inbound_metadata,
        )
        return self.app.handle_message(
            inbound,
            reply_body=reply_body,
            attachment_refs=attachment_refs,
            metadata={
                "channel": "chat-bot",
                **inbound_metadata,
            },
        )


@dataclass(frozen=True, slots=True)
class ChatBotGatewayPlatform:
    key: str = "chat_bot"

    def adapter_descriptor(self) -> GatewayAdapterDescriptor:
        return GatewayAdapterDescriptor(
            key=self.key,
            adapter_id=CHAT_BOT_ADAPTER_ID,
            surface="local-chat",
            default_account_id=DEFAULT_GATEWAY_ACCOUNT_ID,
            operator_action="none",
        )

    def build_adapter(self, app: GatewayApp) -> object:
        return ChatBotMessagingAdapter(app=app)

    def service_registrations(self) -> tuple[GatewayServicePluginRegistration, ...]:
        return ()


CHAT_BOT_PLATFORM = ChatBotGatewayPlatform()

__all__ = ["CHAT_BOT_PLATFORM", "ChatBotGatewayPlatform", "ChatBotMessagingAdapter"]
