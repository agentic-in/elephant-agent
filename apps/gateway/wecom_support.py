"""WeCom (Enterprise WeChat) gateway bootstrap, account config, and WebSocket delivery wiring."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import os

from packages.gateway_core import (
    DEFAULT_GATEWAY_ACCOUNT_ID,
    GatewayExchange,
    GatewayOutboundMessage,
)

from .runtime import GatewayApp

# ---------------------------------------------------------------------------
# Environment variable defaults
# ---------------------------------------------------------------------------

DEFAULT_WECOM_BOT_ID_ENV = "ELEPHANT_WECOM_BOT_ID"
DEFAULT_WECOM_SECRET_ENV = "ELEPHANT_WECOM_SECRET"

SUPPORTED_WECOM_TRANSPORTS = ("websocket",)

# ---------------------------------------------------------------------------
# WeCom AI Bot WebSocket protocol commands
# ---------------------------------------------------------------------------

APP_CMD_SUBSCRIBE = "aibot_subscribe"
APP_CMD_CALLBACK = "aibot_msg_callback"
APP_CMD_LEGACY_CALLBACK = "aibot_callback"
APP_CMD_SEND = "aibot_send_msg"
APP_CMD_RESPONSE = "aibot_respond_msg"
APP_CMD_PING = "ping"

# ---------------------------------------------------------------------------
# Connection and protocol constants
# ---------------------------------------------------------------------------

DEFAULT_WECOM_WS_URL = "wss://openws.work.weixin.qq.com"

MAX_MESSAGE_LENGTH = 4000
CONNECT_TIMEOUT_SECONDS = 20.0
REQUEST_TIMEOUT_SECONDS = 15.0
HEARTBEAT_INTERVAL_SECONDS = 30.0
RECONNECT_BACKOFF = [2, 5, 10, 30, 60]
MESSAGE_DEDUP_TTL_SECONDS = 300

# ---------------------------------------------------------------------------
# Dependency gates
# ---------------------------------------------------------------------------

try:
    import aiohttp

    AIOHTTP_AVAILABLE = True
except ImportError:
    aiohttp = None  # type: ignore[assignment]
    AIOHTTP_AVAILABLE = False

try:
    import httpx

    HTTPX_AVAILABLE = True
except ImportError:
    httpx = None  # type: ignore[assignment]
    HTTPX_AVAILABLE = False


def check_wecom_requirements() -> bool:
    """Return True when runtime dependencies for WeCom are available."""
    return AIOHTTP_AVAILABLE and HTTPX_AVAILABLE


WECOM_AVAILABLE = AIOHTTP_AVAILABLE and HTTPX_AVAILABLE


def _wecom_dependency_status() -> str:
    """Return ``"installed"`` when all WeCom dependencies are present, otherwise
    ``"missing_optional_dependency"``."""
    if AIOHTTP_AVAILABLE and HTTPX_AVAILABLE:
        return "installed"
    return "missing_optional_dependency"


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_bool(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def _normalize_transport(value: str | None) -> str:
    normalized = str(value or "websocket").strip().lower().replace("_", "-")
    if normalized in {"websocket", "wecom-websocket"}:
        return "websocket"
    raise ValueError(f"wecom transport must be one of {', '.join(SUPPORTED_WECOM_TRANSPORTS)}")


def _coerce_list(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return (str(value).strip(),) if str(value).strip() else ()


def _extract_wecom_text(body: object) -> str:
    """Extract text content from a WeCom message body.

    Checks body.text.content, body.mixed.msg_item, and body.voice.content
    in order, returning the first non-empty text found.
    """
    body_map = _mapping(body)
    if body_map is None:
        return ""

    # body.text.content
    text_map = _mapping(body_map.get("text"))
    if text_map is not None:
        content = str(text_map.get("content") or "").strip()
        if content:
            return content

    # body.mixed.msg_item
    mixed = _mapping(body_map.get("mixed"))
    if mixed is not None:
        msg_item = mixed.get("msg_item")
        if isinstance(msg_item, list):
            for item in msg_item:
                item_map = _mapping(item)
                if item_map is None:
                    continue
                item_type = str(item_map.get("type") or "").strip().lower()
                if item_type == "text":
                    text = str(item_map.get("content") or "").strip()
                    if text:
                        return text
        elif isinstance(msg_item, Mapping):
            text = str(msg_item.get("content") or "").strip()
            if text:
                return text

    # body.voice.content
    voice_map = _mapping(body_map.get("voice"))
    if voice_map is not None:
        content = str(voice_map.get("content") or "").strip()
        if content:
            return content

    return ""


# ---------------------------------------------------------------------------
# Account configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WecomGatewayAccountConfig:
    account_id: str = DEFAULT_GATEWAY_ACCOUNT_ID
    bot_id_env_var: str = DEFAULT_WECOM_BOT_ID_ENV
    secret_env_var: str = DEFAULT_WECOM_SECRET_ENV
    surface: str = "websocket"
    enabled: bool = True
    ws_url: str = DEFAULT_WECOM_WS_URL
    dm_policy: str = "open"
    group_policy: str = "open"
    allow_from: tuple[str, ...] = ()
    group_allow_from: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WecomResolvedAccount:
    account_id: str
    bot_id: str
    secret: str
    config: WecomGatewayAccountConfig


@dataclass(frozen=True, slots=True)
class WecomGatewayEventResult:
    exchange: GatewayExchange | None
    response_body: Mapping[str, object]
    delivery_request: Mapping[str, object] | None = None
    delivery_response: Mapping[str, object] | None = None


# ---------------------------------------------------------------------------
# Account loading and resolution
# ---------------------------------------------------------------------------


def load_wecom_gateway_accounts(
    app: GatewayApp,
    *,
    respect_enabled: bool = True,
    include_disabled: bool = False,
) -> tuple[WecomGatewayAccountConfig, ...]:
    manifest = app.loaded_profile.manifest if app.loaded_profile is not None else {}
    gateway_payload = _mapping(manifest.get("gateway")) or {}
    adapters_payload = _mapping(gateway_payload.get("adapters")) or {}
    wecom_payload = _mapping(adapters_payload.get("wecom"))
    if respect_enabled and wecom_payload is not None and wecom_payload.get("enabled") is False:
        return ()

    default_surface = _normalize_transport((wecom_payload or {}).get("surface"))
    accounts_payload = (wecom_payload or {}).get("accounts")
    if isinstance(accounts_payload, list) and accounts_payload:
        resolved: list[WecomGatewayAccountConfig] = []
        for index, account_payload in enumerate(accounts_payload):
            account_mapping = _mapping(account_payload)
            if account_mapping is None:
                raise ValueError("gateway.adapters.wecom.accounts entries must be JSON objects")
            account_enabled = _coerce_bool(account_mapping.get("enabled"), default=True)
            if not include_disabled and not account_enabled:
                continue
            env_payload = _mapping(account_mapping.get("env")) or {}
            resolved.append(
                WecomGatewayAccountConfig(
                    account_id=str(account_mapping.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID),
                    bot_id_env_var=str(env_payload.get("bot_id") or DEFAULT_WECOM_BOT_ID_ENV),
                    secret_env_var=str(env_payload.get("secret") or DEFAULT_WECOM_SECRET_ENV),
                    surface=str(account_mapping.get("surface") or default_surface),
                    enabled=account_enabled,
                    ws_url=str(account_mapping.get("ws_url") or DEFAULT_WECOM_WS_URL),
                    dm_policy=str(account_mapping.get("dm_policy") or "open"),
                    group_policy=str(account_mapping.get("group_policy") or "open"),
                    allow_from=_coerce_list(account_mapping.get("allow_from")),
                    group_allow_from=_coerce_list(account_mapping.get("group_allow_from")),
                    metadata={"manifest_index": index},
                )
            )
        return tuple(resolved)

    return (WecomGatewayAccountConfig(surface=default_surface),)


def resolve_wecom_account(
    config: WecomGatewayAccountConfig,
    *,
    environ: Mapping[str, str] | None = None,
) -> WecomResolvedAccount:
    env = environ or os.environ
    bot_id = str(env.get(config.bot_id_env_var) or "").strip()
    secret = str(env.get(config.secret_env_var) or "").strip()
    if not bot_id:
        raise LookupError(f"wecom account '{config.account_id}' requires {config.bot_id_env_var}")
    if not secret:
        raise LookupError(f"wecom account '{config.account_id}' requires {config.secret_env_var}")
    return WecomResolvedAccount(
        account_id=config.account_id,
        bot_id=bot_id,
        secret=secret,
        config=config,
    )


# ---------------------------------------------------------------------------
# Inbound message helpers
# ---------------------------------------------------------------------------


def _wecom_delivery_defaults(chat_type: str) -> tuple[bool, bool, bool]:
    if chat_type == "direct":
        return True, True, False
    return False, False, True


def _wecom_display_name(payload: Mapping[str, object]) -> str | None:
    for key in ("userid", "name", "display_name", "from_user_name"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return None


def _wecom_chat_type(payload: Mapping[str, object]) -> str:
    chattype = str(payload.get("chattype") or "").strip().lower()
    if chattype == "group":
        return "group"
    return "direct"


def _wecom_body(payload: Mapping[str, object]) -> str:
    body = _mapping(payload.get("body"))
    if body is not None:
        text_content = _mapping(body.get("text"))
        if text_content is not None:
            content = str(text_content.get("content") or "").strip()
            if content:
                return content
        mixed = body.get("mixed")
        if mixed is not None:
            if isinstance(mixed, str):
                text = mixed.strip()
                if text:
                    return text
            elif isinstance(mixed, Mapping):
                text = str(mixed.get("content") or "").strip()
                if text:
                    return text
    content = str(payload.get("content") or "").strip()
    if content:
        return content
    return "wecom-message"


def _wecom_reply_request(outbound: GatewayOutboundMessage) -> Mapping[str, object]:
    rendered_body = outbound.body
    return {
        "command": APP_CMD_RESPONSE,
        "body": {
            "msgid": outbound.metadata.get("msgid", ""),
            "content": rendered_body,
        },
    }


__all__ = [name for name in globals() if not name.startswith("__")]
