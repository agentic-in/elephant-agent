"""WeCom adapter and platform registration for ELEPHANT Bot API."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from packages.gateway_core import (
    DEFAULT_GATEWAY_ACCOUNT_ID,
    GatewayExchange,
    GatewayInboundMessage,
    GatewayOutboundMessage,
)

from ..plugins import GatewayAdapterDescriptor, GatewayServicePluginRegistration
from ..runtime_app import GatewayApp
from ..runtime_support import (
    WECOM_ADAPTER_ID,
    _account_ref,
    _conversation_ref,
    _policy_hint,
    _sender_ref,
)


@dataclass(frozen=True, slots=True)
class WecomMessagingAdapter:
    app: GatewayApp
    adapter_id: str = WECOM_ADAPTER_ID

    def normalize_event(
        self,
        payload: Mapping[str, object],
        *,
        account_id: str | None = None,
        transport: str = "websocket",
        target_trusted: bool | None = None,
        consent_given: bool | None = None,
        is_external: bool | None = None,
    ) -> GatewayInboundMessage:
        from ..wecom_support import (
            _wecom_body,
            _wecom_chat_type,
            _wecom_delivery_defaults,
            _wecom_display_name,
        )

        message_id = str(payload.get("message_id") or payload.get("msg_id") or "").strip()
        if not message_id:
            raise ValueError("wecom event requires message_id")

        sender_id = str(payload.get("sender_id") or payload.get("from_userid") or "").strip()
        if not sender_id:
            raise ValueError("wecom event requires sender_id or from_userid")

        chat_id = str(payload.get("chat_id") or payload.get("chatid") or sender_id or "").strip()
        chat_type = _wecom_chat_type(payload)

        conversation_id = chat_id
        parent_conversation_id = None

        resolved_account_id = account_id or DEFAULT_GATEWAY_ACCOUNT_ID
        target_trusted_default, consent_default, external_default = _wecom_delivery_defaults(chat_type)

        metadata = {
            "channel": "wecom",
            "sender_id": sender_id,
            "chat_type": chat_type,
            "transport": transport,
        }

        return GatewayInboundMessage(
            event_id=message_id,
            account=_account_ref(
                self.adapter_id,
                account_id=resolved_account_id,
                surface=f"wecom-{transport}",
                metadata={"event_transport": transport},
            ),
            conversation=_conversation_ref(
                conversation_id,
                parent_conversation_id=parent_conversation_id,
                chat_type=chat_type,
                metadata={"sender_id": sender_id, "chat_id": chat_id},
            ),
            sender=_sender_ref(
                sender_id,
                display_name=_wecom_display_name(payload),
                is_bot=False,
                metadata={},
            ),
            body=_wecom_body(payload),
            reply_to_message_id=message_id,
            attachment_refs=(),
            policy_hint=_policy_hint(
                target_trusted_default=(target_trusted_default if target_trusted is None else target_trusted),
                consent_default=consent_default if consent_given is None else consent_given,
                is_external_default=external_default if is_external is None else is_external,
                audience_scope=chat_type,
                metadata={"chat_type": chat_type},
            ),
            metadata=metadata,
        )

    def receive_event(
        self,
        payload: Mapping[str, object],
        *,
        account_id: str | None = None,
        transport: str = "websocket",
        reply_body: str | None = None,
        target_trusted: bool | None = None,
        consent_given: bool | None = None,
        is_external: bool | None = None,
    ) -> GatewayExchange:
        inbound = self.normalize_event(
            payload,
            account_id=account_id,
            transport=transport,
            target_trusted=target_trusted,
            consent_given=consent_given,
            is_external=is_external,
        )
        return self.app.handle_message(
            inbound,
            reply_body=reply_body,
            reply_to_message_id=inbound.event_id,
            attachment_refs=inbound.attachment_refs,
            metadata={
                **dict(inbound.metadata),
                "delivery_surface": inbound.account.surface or f"wecom-{transport}",
            },
        )

    def build_reply_request(self, outbound: GatewayOutboundMessage) -> Mapping[str, object]:
        return {
            "method": "POST",
            "endpoint": "aibot_send_msg",
            "body": {
                "msgid": outbound.reply_to_message_id,
                "response_type": "aibot_respond_msg",
                "text": outbound.body,
            },
        }


@dataclass(frozen=True, slots=True)
class WecomGatewayPlatform:
    key: str = "wecom"

    def adapter_descriptor(self) -> GatewayAdapterDescriptor:
        return GatewayAdapterDescriptor(
            key=self.key,
            adapter_id=WECOM_ADAPTER_ID,
            surface="wecom-websocket",
            default_account_id=DEFAULT_GATEWAY_ACCOUNT_ID,
            operator_action="configure ELEPHANT_WECOM_BOT_ID and ELEPHANT_WECOM_SECRET",
            identity_mapping="account_id + chatid + sender userid",
            preferred_transport="websocket",
            implemented_transports=("wecom-websocket",),
            supported_events=("aibot_msg_callback",),
            delivery_defaults={
                "direct": "allow",
                "group": "review",
            },
        )

    def build_adapter(self, app: GatewayApp) -> object:
        return WecomMessagingAdapter(app=app)

    def service_registrations(self) -> tuple[GatewayServicePluginRegistration, ...]:
        from ..wecom import WecomGatewayService

        return (
            GatewayServicePluginRegistration(
                key="wecom",
                factory=lambda app, **kwargs: WecomGatewayService(app=app, **kwargs),
                enabled_by_default=True,
            ),
        )


WECOM_PLATFORM = WecomGatewayPlatform()

__all__ = ["WECOM_PLATFORM", "WecomGatewayPlatform", "WecomMessagingAdapter"]
