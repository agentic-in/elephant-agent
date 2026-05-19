"""Discord adapter and platform registration."""

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
    DISCORD_ADAPTER_ID,
    _account_ref,
    _conversation_ref,
    _discord_attachment_refs,
    _discord_body,
    _discord_delivery_defaults,
    _discord_display_name,
    _discord_chat_type,
    _discord_reply_request,
    _policy_hint,
    _sender_ref,
)


@dataclass(frozen=True, slots=True)
class DiscordMessagingAdapter:
    app: GatewayApp
    adapter_id: str = DISCORD_ADAPTER_ID

    def normalize_event(
        self,
        payload: Mapping[str, object],
        *,
        account_id: str = DEFAULT_GATEWAY_ACCOUNT_ID,
        transport: str = "gateway",
        target_trusted: bool | None = None,
        consent_given: bool | None = None,
        is_external: bool | None = None,
    ) -> GatewayInboundMessage:
        message_id = str(payload.get("id") or "").strip()
        if not message_id:
            raise ValueError("discord event requires id")
        channel_id = str(payload.get("channel_id") or "").strip()
        if not channel_id:
            raise ValueError("discord event requires channel_id")
        author = payload.get("author")
        if not isinstance(author, Mapping):
            raise ValueError("discord event requires author payload")
        member = payload.get("member")
        if member is not None and not isinstance(member, Mapping):
            raise ValueError("discord event member payload must be an object when present")
        chat_type = _discord_chat_type(payload)
        thread_id = str(payload.get("thread_id") or "").strip() or None
        parent_conversation_id = str(payload.get("parent_id") or "").strip() or None
        if chat_type == "topic":
            thread_id = thread_id or channel_id
        else:
            thread_id = None
            parent_conversation_id = None
        conversation_id = thread_id or channel_id
        attachment_refs = _discord_attachment_refs(payload.get("attachments"))
        reply_reference = payload.get("message_reference")
        reply_to_message_id = None
        if isinstance(reply_reference, Mapping) and reply_reference.get("message_id") is not None:
            reply_to_message_id = str(reply_reference["message_id"])
        elif payload.get("reply_to_message_id") is not None:
            reply_to_message_id = str(payload["reply_to_message_id"])
        target_trusted_default, consent_default, external_default = _discord_delivery_defaults(chat_type)
        metadata = {
            "channel": "discord",
            "guild_id": str(payload.get("guild_id") or ""),
            "channel_id": channel_id,
            "chat_type": chat_type,
            "transport": transport,
        }
        if parent_conversation_id is not None:
            metadata["parent_id"] = parent_conversation_id
        if thread_id is not None:
            metadata["thread_id"] = thread_id
        return GatewayInboundMessage(
            event_id=message_id,
            account=_account_ref(
                self.adapter_id,
                account_id=account_id,
                surface=f"discord-{transport}",
                metadata={"event_transport": transport},
            ),
            conversation=_conversation_ref(
                conversation_id,
                parent_conversation_id=parent_conversation_id,
                thread_id=thread_id,
                chat_type=chat_type,
                metadata={"channel_id": channel_id},
            ),
            sender=_sender_ref(
                str(author.get("id") or ""),
                display_name=_discord_display_name(author, member=member),
                username=(f"@{str(author['username'])}" if author.get("username") is not None else None),
                is_bot=bool(author.get("bot", False)),
                metadata={"global_name": str(author.get("global_name") or "")},
            ),
            body=_discord_body(payload),
            reply_to_message_id=reply_to_message_id,
            attachment_refs=attachment_refs,
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
        account_id: str = DEFAULT_GATEWAY_ACCOUNT_ID,
        transport: str = "gateway",
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
                "delivery_surface": inbound.account.surface or f"discord-{transport}",
            },
        )

    def build_reply_request(self, outbound: GatewayOutboundMessage) -> Mapping[str, object]:
        if outbound.adapter_id != self.adapter_id:
            raise ValueError("discord reply request requires a discord outbound message")
        return _discord_reply_request(outbound)


@dataclass(frozen=True, slots=True)
class DiscordGatewayPlatform:
    key: str = "discord"

    def adapter_descriptor(self) -> GatewayAdapterDescriptor:
        return GatewayAdapterDescriptor(
            key=self.key,
            adapter_id=DISCORD_ADAPTER_ID,
            surface="discord-gateway",
            default_account_id=DEFAULT_GATEWAY_ACCOUNT_ID,
            operator_action="configure ELEPHANT_DISCORD_BOT_TOKEN, enable the MESSAGE_CONTENT intent, and run the managed Discord gateway service",
            identity_mapping="account_id + channel_id + author.id (+ thread_id when present)",
            preferred_transport="gateway",
            implemented_transports=("discord.py-gateway",),
            supported_events=("MESSAGE_CREATE", "THREAD_CREATE", "THREAD_UPDATE"),
            delivery_defaults={
                "direct": "allow",
                "channel": "review",
                "topic": "review",
            },
            delivery_api="/channels/{channel_id}/messages",
        )

    def build_adapter(self, app: GatewayApp) -> object:
        return DiscordMessagingAdapter(app=app)

    def service_registrations(self) -> tuple[GatewayServicePluginRegistration, ...]:
        from ..discord import DiscordGatewayService

        return (
            GatewayServicePluginRegistration(
                key="discord",
                factory=lambda app, **kwargs: DiscordGatewayService(app=app, **kwargs),
                enabled_by_default=True,
            ),
        )


DISCORD_PLATFORM = DiscordGatewayPlatform()

__all__ = ["DISCORD_PLATFORM", "DiscordGatewayPlatform", "DiscordMessagingAdapter"]
