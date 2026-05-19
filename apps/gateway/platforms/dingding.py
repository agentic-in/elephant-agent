"""DingDing adapter and platform registration."""

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
    DINGDING_ADAPTER_ID,
    _account_ref,
    _conversation_ref,
    _policy_hint,
    _sender_ref,
)


@dataclass(frozen=True, slots=True)
class DingdingMessagingAdapter:
    app: GatewayApp
    adapter_id: str = DINGDING_ADAPTER_ID

    def normalize_event(
        self,
        payload: Mapping[str, object],
        *,
        account_id: str | None = None,
        transport: str = "stream",
        target_trusted: bool | None = None,
        consent_given: bool | None = None,
        is_external: bool | None = None,
    ) -> GatewayInboundMessage:
        from ..dingding_support import (
            _dingding_body,
            _dingding_chat_type,
            _dingding_delivery_defaults,
            _dingding_display_name,
        )

        message_id = str(payload.get("message_id") or payload.get("msg_id") or "").strip()
        if not message_id:
            raise ValueError("dingding event requires message_id")

        conversation_id = str(payload.get("conversation_id") or payload.get("chat_id") or "").strip()
        if not conversation_id:
            raise ValueError("dingding event requires conversation_id")

        sender_id = str(payload.get("sender_id") or payload.get("sender_staff_id") or "").strip()
        if not sender_id:
            raise ValueError("dingding event requires sender_id")

        chat_type = _dingding_chat_type(payload)
        resolved_account_id = account_id or DEFAULT_GATEWAY_ACCOUNT_ID

        target_trusted_default, consent_default, external_default = _dingding_delivery_defaults(chat_type)

        metadata = {
            "channel": "dingding",
            "conversation_id": conversation_id,
            "chat_type": chat_type,
            "transport": transport,
        }
        robot_code = str(payload.get("robot_code") or "").strip()
        if robot_code:
            metadata["robot_code"] = robot_code

        return GatewayInboundMessage(
            event_id=message_id,
            account=_account_ref(
                self.adapter_id,
                account_id=resolved_account_id,
                surface=f"dingding-{transport}",
                metadata={"event_transport": transport},
            ),
            conversation=_conversation_ref(
                conversation_id,
                chat_type=chat_type,
                metadata={"conversation_id": conversation_id},
            ),
            sender=_sender_ref(
                sender_id,
                display_name=_dingding_display_name(payload),
                is_bot=str(payload.get("sender_type") or "user") != "user",
                metadata={"sender_nick": str(payload.get("sender_nick") or "")},
            ),
            body=_dingding_body(payload),
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
        transport: str = "stream",
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
                "delivery_surface": inbound.account.surface or f"dingding-{transport}",
            },
        )

    def build_reply_request(self, outbound: GatewayOutboundMessage) -> Mapping[str, object]:
        from ..dingding_support import _dingding_reply_request

        if outbound.adapter_id != self.adapter_id:
            raise ValueError("dingding reply request requires a dingding outbound message")
        return _dingding_reply_request(outbound)


@dataclass(frozen=True, slots=True)
class DingdingGatewayPlatform:
    key: str = "dingding"

    def adapter_descriptor(self) -> GatewayAdapterDescriptor:
        return GatewayAdapterDescriptor(
            key=self.key,
            adapter_id=DINGDING_ADAPTER_ID,
            surface="dingding-stream",
            default_account_id=DEFAULT_GATEWAY_ACCOUNT_ID,
            operator_action="configure ELEPHANT_DINGDING_CLIENT_ID, ELEPHANT_DINGDING_CLIENT_SECRET, and ELEPHANT_DINGDING_ROBOT_CODE",
            identity_mapping="account_id + conversation_id + sender_id",
            preferred_transport="stream",
            implemented_transports=("dingtalk-stream",),
            supported_events=("chatbot_message",),
            delivery_defaults={
                "direct": "allow",
                "group": "review",
            },
            delivery_api="/v1.0/robot/oToMessages/batchSend",
        )

    def build_adapter(self, app: GatewayApp) -> object:
        return DingdingMessagingAdapter(app=app)

    def service_registrations(self) -> tuple[GatewayServicePluginRegistration, ...]:
        from ..dingding import DingdingGatewayService

        return (
            GatewayServicePluginRegistration(
                key="dingding",
                factory=lambda app, **kwargs: DingdingGatewayService(app=app, **kwargs),
                enabled_by_default=True,
            ),
        )


DINGDING_PLATFORM = DingdingGatewayPlatform()

__all__ = ["DINGDING_PLATFORM", "DingdingGatewayPlatform", "DingdingMessagingAdapter"]
