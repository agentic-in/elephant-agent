"""Generic webhook adapter and platform registration."""

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
    WEBHOOK_ADAPTER_ID,
    _account_ref,
    _attachment_refs,
    _conversation_ref,
    _object_map,
    _policy_hint,
    _sender_ref,
)


@dataclass(frozen=True, slots=True)
class WebhookMessagingAdapter:
    app: GatewayApp
    adapter_id: str = WEBHOOK_ADAPTER_ID

    def receive_event(
        self,
        payload: Mapping[str, object],
        *,
        reply_body: str | None = None,
        target_trusted: bool = True,
        consent_given: bool = True,
        is_external: bool = False,
    ) -> GatewayExchange:
        attachments = tuple(str(item) for item in payload.get("attachments", ()))
        attachment_refs = _attachment_refs(attachments)
        inbound_metadata = {
            "channel": "webhook",
            **_object_map(payload.get("metadata")),
        }
        inbound = GatewayInboundMessage(
            event_id=str(payload.get("event_id") or payload.get("message_id") or payload["conversation_id"]),
            account=_account_ref(
                self.adapter_id,
                account_id=str(payload.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID),
                tenant_id=(str(payload["tenant_id"]) if payload.get("tenant_id") is not None else None),
                surface="generic-webhook",
            ),
            conversation=_conversation_ref(
                str(payload["conversation_id"]),
                chat_type=str(payload.get("chat_type") or "external"),
            ),
            sender=_sender_ref(
                str(payload["external_user_id"]),
                display_name=(str(payload["display_name"]) if payload.get("display_name") is not None else None),
            ),
            body=str(payload["body"]),
            reply_to_message_id=(
                str(payload["reply_to_message_id"])
                if payload.get("reply_to_message_id") is not None
                else (str(payload["reply_to_event_id"]) if payload.get("reply_to_event_id") is not None else None)
            ),
            attachment_refs=attachment_refs,
            policy_hint=_policy_hint(
                target_trusted_default=target_trusted,
                consent_default=consent_given,
                is_external_default=is_external,
                audience_scope=str(payload.get("chat_type") or "external"),
            ),
            metadata=inbound_metadata,
        )
        response_metadata = {
            "channel": "webhook",
            **_object_map(payload.get("metadata")),
        }
        callback_url = payload.get("callback_url")
        if callback_url is not None:
            response_metadata["callback_url"] = str(callback_url)
        return self.app.handle_message(
            inbound,
            reply_body=reply_body,
            reply_to_message_id=inbound.reply_to_message_id or inbound.event_id,
            attachment_refs=inbound.attachment_refs,
            metadata=response_metadata,
        )


@dataclass(frozen=True, slots=True)
class WebhookGatewayPlatform:
    key: str = "webhook"

    def adapter_descriptor(self) -> GatewayAdapterDescriptor:
        return GatewayAdapterDescriptor(
            key=self.key,
            adapter_id=WEBHOOK_ADAPTER_ID,
            surface="generic-webhook",
            default_account_id=DEFAULT_GATEWAY_ACCOUNT_ID,
            operator_action="supply callback_url in inbound payload",
        )

    def build_adapter(self, app: GatewayApp) -> object:
        return WebhookMessagingAdapter(app=app)

    def service_registrations(self) -> tuple[GatewayServicePluginRegistration, ...]:
        return ()


WEBHOOK_PLATFORM = WebhookGatewayPlatform()

__all__ = ["WEBHOOK_PLATFORM", "WebhookGatewayPlatform", "WebhookMessagingAdapter"]
