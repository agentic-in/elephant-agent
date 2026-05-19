"""WeChat (Weixin) adapter and platform registration for iLink Bot API."""

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
    WEIXIN_ADAPTER_ID,
    _account_ref,
    _conversation_ref,
    _policy_hint,
    _sender_ref,
)


@dataclass(frozen=True, slots=True)
class WeixinMessagingAdapter:
    app: GatewayApp
    adapter_id: str = WEIXIN_ADAPTER_ID

    def normalize_event(
        self,
        payload: Mapping[str, object],
        *,
        account_id: str | None = None,
        transport: str = "ilink",
        target_trusted: bool | None = None,
        consent_given: bool | None = None,
        is_external: bool | None = None,
    ) -> GatewayInboundMessage:
        from ..weixin_support import (
            _weixin_body,
            _weixin_chat_type,
            _weixin_delivery_defaults,
            _weixin_display_name,
        )

        message_id = str(payload.get("message_id") or payload.get("msg_id") or "").strip()
        if not message_id:
            raise ValueError("weixin event requires message_id")

        from_user = str(payload.get("from_user") or payload.get("from_wxid") or "").strip()
        if not from_user:
            raise ValueError("weixin event requires from_user or from_wxid")

        room = str(payload.get("room") or payload.get("room_wxid") or "").strip()
        chat_type = _weixin_chat_type(payload)

        if room:
            conversation_id = room
            parent_conversation_id = None
        else:
            conversation_id = from_user
            parent_conversation_id = None

        resolved_account_id = account_id or DEFAULT_GATEWAY_ACCOUNT_ID
        target_trusted_default, consent_default, external_default = _weixin_delivery_defaults(chat_type)

        metadata = {
            "channel": "weixin",
            "from_user": from_user,
            "chat_type": chat_type,
            "transport": transport,
        }
        if room:
            metadata["room"] = room

        return GatewayInboundMessage(
            event_id=message_id,
            account=_account_ref(
                self.adapter_id,
                account_id=resolved_account_id,
                surface=f"weixin-{transport}",
                metadata={"event_transport": transport},
            ),
            conversation=_conversation_ref(
                conversation_id,
                parent_conversation_id=parent_conversation_id,
                chat_type=chat_type,
                metadata={"from_user": from_user, "room": room or ""},
            ),
            sender=_sender_ref(
                from_user,
                display_name=_weixin_display_name(payload),
                is_bot=False,
                metadata={},
            ),
            body=_weixin_body(payload),
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
        transport: str = "ilink",
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
                "delivery_surface": inbound.account.surface or f"weixin-{transport}",
            },
        )

    def build_reply_request(self, outbound: GatewayOutboundMessage) -> Mapping[str, object]:
        # In iLink mode, replies are sent directly via _send_ilink_message,
        # not via a separate HTTP request. This method keeps the platform
        # interface complete for transports that do build HTTP reply requests.
        return {
            "method": "POST",
            "endpoint": "ilink/bot/sendmessage",
            "body": {
                "to_user_id": outbound.conversation_id,
                "text": outbound.body,
            },
        }


@dataclass(frozen=True, slots=True)
class WeixinGatewayPlatform:
    key: str = "weixin"

    def adapter_descriptor(self) -> GatewayAdapterDescriptor:
        return GatewayAdapterDescriptor(
            key=self.key,
            adapter_id=WEIXIN_ADAPTER_ID,
            surface="weixin-ilink",
            default_account_id=DEFAULT_GATEWAY_ACCOUNT_ID,
            operator_action="scan QR code via 'elephant gateway weixin setup' to obtain iLink credentials",
            identity_mapping="account_id + from_user_id (+ room_id when group chat)",
            preferred_transport="ilink",
            implemented_transports=("weixin-ilink",),
            supported_events=("ilink_long_poll",),
            delivery_defaults={
                "direct": "allow",
                "group": "review",
            },
            delivery_api="ilink/bot/sendmessage",
        )

    def build_adapter(self, app: GatewayApp) -> object:
        return WeixinMessagingAdapter(app=app)

    def service_registrations(self) -> tuple[GatewayServicePluginRegistration, ...]:
        from ..weixin import WeixinGatewayService

        return (
            GatewayServicePluginRegistration(
                key="weixin",
                factory=lambda app, **kwargs: WeixinGatewayService(app=app, **kwargs),
                enabled_by_default=True,
            ),
        )


WEIXIN_PLATFORM = WeixinGatewayPlatform()

__all__ = ["WEIXIN_PLATFORM", "WeixinGatewayPlatform", "WeixinMessagingAdapter"]
