from __future__ import annotations

from .discord_support import *  # noqa: F401,F403


@dataclass(frozen=True, slots=True)
class DiscordPyDeliveryTransport:
    client: object
    discord_module: Any

    async def send_request(
        self,
        request: Mapping[str, object],
        *,
        account: DiscordResolvedAccount,
    ) -> Mapping[str, object]:
        del account
        body = _mapping(request.get("body"))
        if body is None:
            raise RuntimeError("discord delivery request is missing the body payload")
        channel = await self._resolve_channel(request)
        content = str(body.get("content") or "")
        allowed_mentions = self._allowed_mentions()
        reply_message_id: str | None = None
        reply_payload = _mapping(body.get("message_reference"))
        if reply_payload is not None:
            resolved_reply_message_id = str(reply_payload.get("message_id") or "").strip()
            if resolved_reply_message_id:
                reply_message_id = resolved_reply_message_id
        if len(content) > DISCORD_ATTACHMENT_FALLBACK_THRESHOLD:
            attachment = self._build_text_attachment(content)
            if attachment is not None:
                message = await self._send_attachment_fallback(
                    channel=channel,
                    content=content,
                    attachment=attachment,
                    allowed_mentions=allowed_mentions,
                    reply_message_id=reply_message_id,
                )
                return {
                    "id": str(getattr(message, "id", "")),
                    "channel_id": str(getattr(channel, "id", request.get("channel_id") or "")),
                    "chunk_count": 1,
                    "delivery_mode": "attachment",
                    "attachment_filename": DISCORD_ATTACHMENT_FALLBACK_FILENAME,
                }
        chunk_limit = (
            DISCORD_MESSAGE_CONTENT_LIMIT - DISCORD_FENCE_SPLIT_RESERVE
            if "```" in content
            else DISCORD_MESSAGE_CONTENT_LIMIT
        )
        content_chunks = _rebalance_discord_fenced_chunks(_split_discord_message_content(content, limit=chunk_limit))
        message = await self._send_content_chunks(
            channel=channel,
            content_chunks=content_chunks,
            allowed_mentions=allowed_mentions,
            reply_message_id=reply_message_id,
        )
        return {
            "id": str(getattr(message, "id", "")),
            "channel_id": str(getattr(channel, "id", request.get("channel_id") or "")),
            "chunk_count": len(content_chunks),
            "delivery_mode": "chunked" if len(content_chunks) > 1 else "inline",
        }

    def _build_text_attachment(self, content: str) -> object | None:
        file_type = getattr(self.discord_module, "File", None)
        if file_type is None:
            return None
        return file_type(
            fp=io.BytesIO(content.encode("utf-8")),
            filename=DISCORD_ATTACHMENT_FALLBACK_FILENAME,
            description="Full Discord reply body",
        )

    async def _send_attachment_fallback(
        self,
        *,
        channel: object,
        content: str,
        attachment: object,
        allowed_mentions: object | None,
        reply_message_id: str | None,
    ) -> object:
        notice = self._attachment_notice(content)
        return await self._send_reply_or_channel_message(
            channel=channel,
            content=notice,
            allowed_mentions=allowed_mentions,
            reply_message_id=reply_message_id,
            file=attachment,
        )

    def _attachment_notice(self, content: str) -> str:
        return (
            "Reply too long for Discord inline delivery "
            f"({len(content)} chars); full content is attached as "
            f"{DISCORD_ATTACHMENT_FALLBACK_FILENAME}."
        )

    async def _send_content_chunks(
        self,
        *,
        channel: object,
        content_chunks: tuple[str, ...],
        allowed_mentions: object | None,
        reply_message_id: str | None,
    ) -> object:
        first_chunk, *remaining_chunks = content_chunks
        message = await self._send_reply_or_channel_message(
            channel=channel,
            content=first_chunk,
            allowed_mentions=allowed_mentions,
            reply_message_id=reply_message_id,
        )
        for chunk in remaining_chunks:
            await self._send_channel_message(
                channel=channel,
                content=chunk,
                allowed_mentions=allowed_mentions,
            )
        return message

    async def _send_reply_or_channel_message(
        self,
        *,
        channel: object,
        content: str,
        allowed_mentions: object | None,
        reply_message_id: str | None,
        file: object | None = None,
    ) -> object:
        if reply_message_id and hasattr(channel, "get_partial_message"):
            partial_message = channel.get_partial_message(_snowflake(reply_message_id))
            reply = getattr(partial_message, "reply", None)
            if callable(reply):
                return await _maybe_await(
                    reply(
                        content=content,
                        allowed_mentions=allowed_mentions,
                        mention_author=False,
                        file=file,
                    )
                )
        return await self._send_channel_message(
            channel=channel,
            content=content,
            allowed_mentions=allowed_mentions,
            file=file,
        )

    async def _send_channel_message(
        self,
        *,
        channel: object,
        content: str,
        allowed_mentions: object | None,
        file: object | None = None,
    ) -> object:
        send = getattr(channel, "send", None)
        if not callable(send):
            raise RuntimeError("discord channel does not expose send()")
        return await _maybe_await(
            send(
                content=content,
                allowed_mentions=allowed_mentions,
                file=file,
            )
        )

    async def _resolve_channel(self, request: Mapping[str, object]) -> object:
        channel_id = request.get("channel_id")
        if channel_id is None:
            raise RuntimeError("discord delivery request is missing channel_id")
        resolved_channel_id = _snowflake(channel_id)
        get_channel = getattr(self.client, "get_channel", None)
        if callable(get_channel):
            channel = get_channel(resolved_channel_id)
            if channel is not None:
                return channel
        fetch_channel = getattr(self.client, "fetch_channel", None)
        if callable(fetch_channel):
            channel = await _maybe_await(fetch_channel(resolved_channel_id))
            if channel is not None:
                return channel
        raise RuntimeError(f"discord channel '{channel_id}' is unavailable to the active client")

    def _allowed_mentions(self) -> object | None:
        allowed_mentions_type = getattr(self.discord_module, "AllowedMentions", None)
        if allowed_mentions_type is None:
            return None
        return allowed_mentions_type(
            everyone=False,
            users=False,
            roles=False,
            replied_user=False,
        )
