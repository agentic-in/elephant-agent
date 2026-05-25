"""Gateway service catalog for the API console surface."""

from __future__ import annotations

from typing import Any

_GATEWAY_SERVICE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "service": "weixin",
        "label": "WeChat",
        "adapterId": "messaging.weixin",
        "surface": "weixin-ilink",
        "defaultTransport": "ilink",
        "transports": ("ilink",),
        "summary": "WeChat iLink bridge with the same scan-to-login QR flow as `elephant gateway setup`.",
        "eventPath": "/weixin/events",
        "secretFields": (),
        "supportsDirectConfig": True,
        "setupNote": "Click Connect & start WeChat, scan the QR with WeChat, then Dashboard automatically detects confirmation and starts the bridge.",
    },
    {
        "service": "feishu",
        "label": "Feishu",
        "adapterId": "messaging.feishu",
        "surface": "feishu-messaging",
        "defaultTransport": "long-connection",
        "transports": ("long-connection",),
        "summary": "Feishu bot long-connection bridge for p2p and group chat messages.",
        "eventPath": "/feishu/events",
        "secretFields": (
            {
                "key": "app_id",
                "label": "App ID",
                "defaultEnvVar": "ELEPHANT_FEISHU_APP_ID",
            },
            {
                "key": "app_secret",
                "label": "App Secret",
                "defaultEnvVar": "ELEPHANT_FEISHU_APP_SECRET",
            },
        ),
        "supportsDirectConfig": True,
    },
    {
        "service": "discord",
        "label": "Discord",
        "adapterId": "messaging.discord",
        "surface": "discord-gateway",
        "defaultTransport": "gateway",
        "transports": ("gateway",),
        "summary": "Discord bot gateway bridge for DMs, channels, and threads.",
        "secretFields": (
            {
                "key": "bot_token",
                "label": "Bot token",
                "defaultEnvVar": "ELEPHANT_DISCORD_BOT_TOKEN",
            },
        ),
        "supportsDirectConfig": True,
    },
    {
        "service": "dingding",
        "label": "DingDing",
        "adapterId": "messaging.dingding",
        "surface": "dingding-stream",
        "defaultTransport": "stream",
        "transports": ("stream",),
        "summary": "DingDing stream bridge for chatbot messages.",
        "secretFields": (
            {
                "key": "client_id",
                "label": "Client ID",
                "defaultEnvVar": "ELEPHANT_DINGDING_CLIENT_ID",
            },
            {
                "key": "client_secret",
                "label": "Client Secret",
                "defaultEnvVar": "ELEPHANT_DINGDING_CLIENT_SECRET",
            },
            {
                "key": "robot_code",
                "label": "Robot Code",
                "defaultEnvVar": "ELEPHANT_DINGDING_ROBOT_CODE",
            },
        ),
        "supportsDirectConfig": True,
    },
    {
        "service": "wecom",
        "label": "WeCom",
        "adapterId": "messaging.wecom",
        "surface": "wecom-websocket",
        "defaultTransport": "websocket",
        "transports": ("websocket",),
        "summary": "WeCom AI Bot WebSocket bridge for chats and groups.",
        "secretFields": (
            {
                "key": "bot_id",
                "label": "Bot ID",
                "defaultEnvVar": "ELEPHANT_WECOM_BOT_ID",
            },
            {
                "key": "secret",
                "label": "Secret",
                "defaultEnvVar": "ELEPHANT_WECOM_SECRET",
            },
        ),
        "supportsDirectConfig": True,
    },
)
_GATEWAY_SERVICE_BY_KEY = {
    str(spec["service"]): spec for spec in _GATEWAY_SERVICE_SPECS
}
