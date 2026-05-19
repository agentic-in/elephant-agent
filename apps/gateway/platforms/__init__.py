"""Builtin gateway platform plugins."""

from __future__ import annotations

from .chat_bot import CHAT_BOT_PLATFORM, ChatBotGatewayPlatform, ChatBotMessagingAdapter
from .dingding import (
    DINGDING_PLATFORM,
    DingdingGatewayPlatform,
    DingdingMessagingAdapter,
)
from .discord import DISCORD_PLATFORM, DiscordGatewayPlatform, DiscordMessagingAdapter
from .feishu import FEISHU_PLATFORM, FeishuGatewayPlatform, FeishuMessagingAdapter
from .telegram import (
    TELEGRAM_PLATFORM,
    TelegramGatewayPlatform,
    TelegramMessagingAdapter,
)
from .wecom import WECOM_PLATFORM, WecomGatewayPlatform, WecomMessagingAdapter
from .weixin import WEIXIN_PLATFORM, WeixinGatewayPlatform, WeixinMessagingAdapter
from .webhook import WEBHOOK_PLATFORM, WebhookGatewayPlatform, WebhookMessagingAdapter

BUILTIN_GATEWAY_PLATFORMS = (
    CHAT_BOT_PLATFORM,
    WEBHOOK_PLATFORM,
    TELEGRAM_PLATFORM,
    DISCORD_PLATFORM,
    FEISHU_PLATFORM,
    DINGDING_PLATFORM,
    WECOM_PLATFORM,
    WEIXIN_PLATFORM,
)

__all__ = [
    "BUILTIN_GATEWAY_PLATFORMS",
    "CHAT_BOT_PLATFORM",
    "DINGDING_PLATFORM",
    "DISCORD_PLATFORM",
    "FEISHU_PLATFORM",
    "TELEGRAM_PLATFORM",
    "WECOM_PLATFORM",
    "WEIXIN_PLATFORM",
    "WEBHOOK_PLATFORM",
    "ChatBotGatewayPlatform",
    "ChatBotMessagingAdapter",
    "DingdingGatewayPlatform",
    "DingdingMessagingAdapter",
    "DiscordGatewayPlatform",
    "DiscordMessagingAdapter",
    "FeishuGatewayPlatform",
    "FeishuMessagingAdapter",
    "TelegramGatewayPlatform",
    "TelegramMessagingAdapter",
    "WecomGatewayPlatform",
    "WecomMessagingAdapter",
    "WeixinGatewayPlatform",
    "WeixinMessagingAdapter",
    "WebhookGatewayPlatform",
    "WebhookMessagingAdapter",
]
