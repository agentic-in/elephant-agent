"""Feishu adapter and platform registration."""

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
    FEISHU_ADAPTER_ID,
    _account_ref,
    _conversation_ref,
    _feishu_attachment_refs,
    _feishu_display_name,
    _feishu_message_body,
    _feishu_message_content,
    _feishu_reply_request,
    _feishu_sender_user_id,
    _normalized_chat_type,
    _policy_hint,
    _sender_ref,
)


@dataclass(frozen=True, slots=True)
class FeishuMessagingAdapter:
    app: GatewayApp
    adapter_id: str = FEISHU_ADAPTER_ID

    def normalize_event(
        self,
        payload: Mapping[str, object],
        *,
        account_id: str | None = None,
        transport: str = "long-connection",
        target_trusted: bool | None = None,
        consent_given: bool | None = None,
        is_external: bool | None = None,
    ) -> GatewayInboundMessage:
        header = payload.get("header")
        if not isinstance(header, Mapping):
            raise ValueError("feishu event requires a header payload")
        event = payload.get("event")
        if not isinstance(event, Mapping):
            raise ValueError("feishu event requires an event payload")
        sender = event.get("sender")
        message = event.get("message")
        if not isinstance(sender, Mapping) or not isinstance(message, Mapping):
            raise ValueError("feishu event requires sender and message payloads")

        event_type = str(header.get("event_type") or "")
        if event_type and event_type != "im.message.receive_v1":
            raise ValueError(f"unsupported feishu event type: {event_type}")

        tenant_key = (
            str(header["tenant_key"])
            if header.get("tenant_key") is not None
            else (str(event["tenant_key"]) if event.get("tenant_key") is not None else None)
        )
        resolved_account_id = account_id or (
            str(header["app_id"]) if header.get("app_id") is not None else DEFAULT_GATEWAY_ACCOUNT_ID
        )

        chat_id = str(message.get("chat_id") or "")
        if not chat_id:
            raise ValueError("feishu message payload requires chat_id")
        chat_type = str(message.get("chat_type") or "group")
        normalized_chat_type = _normalized_chat_type(chat_type)
        message_id = str(message.get("message_id") or header.get("event_id") or "")
        if not message_id:
            raise ValueError("feishu message payload requires message_id")
        root_id = (
            str(message["root_id"]) if message.get("root_id") is not None and str(message["root_id"]).strip() else None
        )
        parent_id = (
            str(message["parent_id"])
            if message.get("parent_id") is not None and str(message["parent_id"]).strip()
            else None
        )
        message_type = str(message.get("message_type") or "text")
        content = _feishu_message_content(message.get("content"))
        attachment_refs = _feishu_attachment_refs(content)
        conversation_id = f"{chat_id}:{root_id}" if root_id is not None else chat_id
        transport_label = str(transport or "event-subscription").strip() or "event-subscription"

        inbound_metadata = {
            "channel": "feishu",
            "event_type": event_type or "im.message.receive_v1",
            "chat_id": chat_id,
            "chat_type": chat_type,
            "message_type": message_type,
            "message_id": message_id,
            "tenant_key": tenant_key or "",
        }
        if root_id is not None:
            inbound_metadata["root_id"] = root_id
        if parent_id is not None:
            inbound_metadata["parent_id"] = parent_id
        mentions = event.get("mentions")
        if isinstance(mentions, list):
            inbound_metadata["mention_count"] = len(mentions)

        target_trusted_default = chat_type == "p2p"
        consent_default = chat_type == "p2p"
        external_default = chat_type != "p2p"
        return GatewayInboundMessage(
            event_id=message_id,
            account=_account_ref(
                self.adapter_id,
                account_id=resolved_account_id,
                tenant_id=tenant_key,
                surface=f"feishu-{transport_label}",
                metadata={"event_transport": transport_label},
            ),
            conversation=_conversation_ref(
                conversation_id,
                parent_conversation_id=chat_id if root_id is not None else None,
                thread_id=root_id,
                chat_type=normalized_chat_type,
                metadata={
                    "raw_chat_type": chat_type,
                    "message_id": message_id,
                },
            ),
            sender=_sender_ref(
                _feishu_sender_user_id(sender),
                display_name=_feishu_display_name(sender),
                is_bot=str(sender.get("sender_type") or "user") != "user",
                metadata={
                    "sender_type": str(sender.get("sender_type") or "user"),
                    "tenant_key": (str(sender["tenant_key"]) if sender.get("tenant_key") is not None else ""),
                },
            ),
            body=_feishu_message_body(message_type, content),
            reply_to_message_id=parent_id or root_id or message_id,
            attachment_refs=attachment_refs,
            policy_hint=_policy_hint(
                target_trusted_default=(target_trusted_default if target_trusted is None else target_trusted),
                consent_default=consent_default if consent_given is None else consent_given,
                is_external_default=external_default if is_external is None else is_external,
                audience_scope=normalized_chat_type,
                metadata={
                    "raw_chat_type": chat_type,
                    "tenant_key": tenant_key or "",
                },
            ),
            metadata=inbound_metadata,
        )

    def receive_event(
        self,
        payload: Mapping[str, object],
        *,
        account_id: str | None = None,
        transport: str = "long-connection",
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
            reply_to_message_id=inbound.reply_to_message_id or inbound.event_id,
            attachment_refs=inbound.attachment_refs,
            metadata={
                **dict(inbound.metadata),
                "delivery_surface": inbound.account.surface or f"feishu-{transport}",
            },
        )

    def build_reply_request(self, outbound: GatewayOutboundMessage) -> Mapping[str, object]:
        if outbound.adapter_id != self.adapter_id:
            raise ValueError("feishu reply request requires a feishu outbound message")
        return _feishu_reply_request(outbound)


@dataclass(frozen=True, slots=True)
class FeishuGatewayPlatform:
    key: str = "feishu"

    def adapter_descriptor(self) -> GatewayAdapterDescriptor:
        return GatewayAdapterDescriptor(
            key=self.key,
            adapter_id=FEISHU_ADAPTER_ID,
            surface="feishu-messaging",
            default_account_id=DEFAULT_GATEWAY_ACCOUNT_ID,
            operator_action="configure gateway.adapters.feishu account env refs for the SDK long-connection path used by im.message.receive_v1",
            identity_mapping="account_id + chat_id + sender_id (+ root_id when replying in thread)",
            preferred_transport="long-connection",
            implemented_transports=("python-sdk-long-connection",),
            supported_events=("im.message.receive_v1",),
            delivery_defaults={
                "p2p": "allow",
                "group": "review",
            },
            delivery_api="/open-apis/im/v1/messages/:message_id/reply",
        )

    def build_adapter(self, app: GatewayApp) -> object:
        return FeishuMessagingAdapter(app=app)

    def service_registrations(self) -> tuple[GatewayServicePluginRegistration, ...]:
        from ..feishu import FeishuGatewayService

        return (
            GatewayServicePluginRegistration(
                key="feishu",
                factory=lambda app, **kwargs: FeishuGatewayService(app=app, **kwargs),
                enabled_by_default=True,
            ),
        )


FEISHU_PLATFORM = FeishuGatewayPlatform()

__all__ = ["FEISHU_PLATFORM", "FeishuGatewayPlatform", "FeishuMessagingAdapter"]
