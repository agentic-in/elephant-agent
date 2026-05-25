"""WeChat (Weixin) gateway bootstrap, account config, and iLink Bot API wiring.

Connects Elephant Agent to WeChat personal accounts via Tencent's iLink Bot API.
Design notes:
- Long-poll ``getupdates`` drives inbound delivery.
- Every outbound reply must echo the latest ``context_token`` for the peer.
- Media files move through an AES-128-ECB encrypted CDN protocol.
- QR login is exposed as a helper for the gateway setup wizard.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import secrets
import struct
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urlparse

from apps.runtime_layout import default_cli_state_dir
from packages.gateway_core import (
    DEFAULT_GATEWAY_ACCOUNT_ID,
    GatewayExchange,
    GatewayInboundMessage,
    GatewayOutboundMessage,
)

from .cli_control import (
    CliRuntimeFactory,
    GatewayCliBindingStore,
    GatewayCliControlService,
    load_gateway_cli_control_config,
)
from .plugins import GatewayManagedRuntime, GatewayPluginRegistry, default_gateway_runtime_path
from .runtime import GatewayApp, build_gateway_app
from .weixin_delivery import (
    _normalize_markdown_blocks,
    _pack_markdown_blocks_for_weixin,
    _split_delivery_units_for_weixin,
    _split_markdown_blocks,
    _split_text_for_weixin_delivery,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# iLink Bot API constants
# ---------------------------------------------------------------------------

ILINK_BASE_URL = "https://ilinkai.weixin.qq.com"
WEIXIN_CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"
ILINK_APP_ID = "bot"
CHANNEL_VERSION = "2.2.0"
ILINK_APP_CLIENT_VERSION = (2 << 16) | (2 << 8) | 0

EP_GET_UPDATES = "ilink/bot/getupdates"
EP_SEND_MESSAGE = "ilink/bot/sendmessage"
EP_SEND_TYPING = "ilink/bot/sendtyping"
EP_GET_CONFIG = "ilink/bot/getconfig"
EP_GET_UPLOAD_URL = "ilink/bot/getuploadurl"
EP_GET_BOT_QR = "ilink/bot/get_bot_qrcode"
EP_GET_QR_STATUS = "ilink/bot/get_qrcode_status"

LONG_POLL_TIMEOUT_MS = 35_000
API_TIMEOUT_MS = 15_000
CONFIG_TIMEOUT_MS = 10_000
QR_TIMEOUT_MS = 35_000

MAX_CONSECUTIVE_FAILURES = 3
RETRY_DELAY_SECONDS = 2
BACKOFF_DELAY_SECONDS = 30
SESSION_EXPIRED_ERRCODE = -14
MESSAGE_DEDUP_TTL_SECONDS = 300

# iLink message item types
ITEM_TEXT = 1
ITEM_IMAGE = 2
ITEM_VOICE = 3
ITEM_FILE = 4
ITEM_VIDEO = 5

MSG_TYPE_USER = 1
MSG_TYPE_BOT = 2
MSG_STATE_FINISH = 2

TYPING_START = 1
TYPING_STOP = 2

MEDIA_IMAGE = 1
MEDIA_VIDEO = 2
MEDIA_FILE = 3
MEDIA_VOICE = 4

# Transport identifiers
SUPPORTED_WEIXIN_TRANSPORTS = ("ilink",)

DEFAULT_WEIXIN_EVENT_PATH = "/weixin/events"


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
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    CRYPTO_AVAILABLE = True
except ImportError:
    default_backend = None  # type: ignore[assignment]
    Cipher = None  # type: ignore[assignment]
    algorithms = None  # type: ignore[assignment]
    modes = None  # type: ignore[assignment]
    CRYPTO_AVAILABLE = False


def _print_qr_centered(qr) -> None:
    """Print a QR code centered in the terminal using Rich if available, else raw print."""
    import io

    buffer = io.StringIO()
    qr.print_ascii(out=buffer, invert=True)
    qr_text = buffer.getvalue()
    try:
        from rich.align import Align
        from rich.console import Console
        from rich.text import Text

        console = Console()
        console.print(Align.center(Text(qr_text)))
    except Exception:
        # Fallback: manual centering using terminal width
        import shutil

        cols = shutil.get_terminal_size((80, 24)).columns
        for line in qr_text.splitlines():
            pad = max(0, (cols - len(line)) // 2)
            print(" " * pad + line)


def check_weixin_requirements() -> bool:
    """Return True when runtime dependencies for Weixin are available."""
    return AIOHTTP_AVAILABLE and CRYPTO_AVAILABLE


# ---------------------------------------------------------------------------
# SSL connector helper
# ---------------------------------------------------------------------------

def _make_ssl_connector() -> Optional["aiohttp.TCPConnector"]:
    """Return a TCPConnector with a certifi CA bundle, or None."""
    try:
        import ssl
        import certifi
    except ImportError:
        return None
    if not AIOHTTP_AVAILABLE:
        return None
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    return aiohttp.TCPConnector(ssl=ssl_ctx)


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _safe_id(value: Optional[str], keep: int = 8) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "?"
    if len(raw) <= keep:
        return raw
    return raw[:keep]


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _coerce_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _normalize_path(value: str | None) -> str:
    text = str(value or DEFAULT_WEIXIN_EVENT_PATH).strip() or DEFAULT_WEIXIN_EVENT_PATH
    return text if text.startswith("/") else f"/{text}"


def _normalize_transport(value: str | None) -> str:
    normalized = str(value or "ilink").strip().lower().replace("_", "-")
    if normalized in {"ilink", "weixin-ilink", "wxhook", "weixin-wxhook"}:
        return "ilink"
    raise ValueError(
        "weixin transport must be one of "
        f"{', '.join(SUPPORTED_WEIXIN_TRANSPORTS)}"
    )


# ---------------------------------------------------------------------------
# AES-128-ECB encryption / decryption
# ---------------------------------------------------------------------------

def _pkcs7_pad(data: bytes, block_size: int = 16) -> bytes:
    pad_len = block_size - (len(data) % block_size)
    return data + bytes([pad_len] * pad_len)


def _aes128_ecb_encrypt(plaintext: bytes, key: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
    encryptor = cipher.encryptor()
    return encryptor.update(_pkcs7_pad(plaintext)) + encryptor.finalize()


def _aes128_ecb_decrypt(ciphertext: bytes, key: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    if not padded:
        return padded
    pad_len = padded[-1]
    if 1 <= pad_len <= 16 and padded.endswith(bytes([pad_len]) * pad_len):
        return padded[:-pad_len]
    return padded


def _aes_padded_size(size: int) -> int:
    return ((size + 1 + 15) // 16) * 16


def _parse_aes_key(aes_key_b64: str) -> bytes:
    decoded = base64.b64decode(aes_key_b64)
    if len(decoded) == 16:
        return decoded
    if len(decoded) == 32:
        text = decoded.decode("ascii", errors="ignore")
        if text and all(ch in "0123456789abcdefABCDEF" for ch in text):
            return bytes.fromhex(text)
    raise ValueError(f"unexpected aes_key format ({len(decoded)} decoded bytes)")


# ---------------------------------------------------------------------------
# iLink API helpers
# ---------------------------------------------------------------------------

def _random_wechat_uin() -> str:
    value = struct.unpack(">I", secrets.token_bytes(4))[0]
    return base64.b64encode(str(value).encode("utf-8")).decode("ascii")


def _base_info() -> dict[str, Any]:
    return {"channel_version": CHANNEL_VERSION}


def _headers(token: Optional[str], body: str) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "Content-Length": str(len(body.encode("utf-8"))),
        "X-WECHAT-UIN": _random_wechat_uin(),
        "iLink-App-Id": ILINK_APP_ID,
        "iLink-App-ClientVersion": str(ILINK_APP_CLIENT_VERSION),
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def _api_post(
    session: "aiohttp.ClientSession",
    *,
    base_url: str,
    endpoint: str,
    payload: dict[str, Any],
    token: Optional[str],
    timeout_ms: int,
) -> dict[str, Any]:
    import asyncio

    body = _json_dumps({**payload, "base_info": _base_info()})
    url = f"{base_url.rstrip('/')}/{endpoint}"
    timeout = aiohttp.ClientTimeout(total=timeout_ms / 1000)
    async with session.post(url, data=body, headers=_headers(token, body), timeout=timeout) as response:
        raw = await response.text()
        if not response.ok:
            raise RuntimeError(f"iLink POST {endpoint} HTTP {response.status}: {raw[:200]}")
        return json.loads(raw)


async def _api_get(
    session: "aiohttp.ClientSession",
    *,
    base_url: str,
    endpoint: str,
    timeout_ms: int,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/{endpoint}"
    headers = {
        "iLink-App-Id": ILINK_APP_ID,
        "iLink-App-ClientVersion": str(ILINK_APP_CLIENT_VERSION),
    }
    timeout = aiohttp.ClientTimeout(total=timeout_ms / 1000)
    async with session.get(url, headers=headers, timeout=timeout) as response:
        raw = await response.text()
        if not response.ok:
            raise RuntimeError(f"iLink GET {endpoint} HTTP {response.status}: {raw[:200]}")
        return json.loads(raw)


async def _get_updates(
    session: "aiohttp.ClientSession",
    *,
    base_url: str,
    token: str,
    sync_buf: str,
    timeout_ms: int,
) -> dict[str, Any]:
    import asyncio

    try:
        return await _api_post(
            session,
            base_url=base_url,
            endpoint=EP_GET_UPDATES,
            payload={"get_updates_buf": sync_buf},
            token=token,
            timeout_ms=timeout_ms,
        )
    except asyncio.TimeoutError:
        return {"ret": 0, "msgs": [], "get_updates_buf": sync_buf}


async def _send_message(
    session: "aiohttp.ClientSession",
    *,
    base_url: str,
    token: str,
    to: str,
    text: str,
    context_token: Optional[str],
    client_id: str,
) -> dict[str, Any]:
    if not text or not text.strip():
        raise ValueError("_send_message: text must not be empty")
    message: dict[str, Any] = {
        "from_user_id": "",
        "to_user_id": to,
        "client_id": client_id,
        "message_type": MSG_TYPE_BOT,
        "message_state": MSG_STATE_FINISH,
        "item_list": [{"type": ITEM_TEXT, "text_item": {"text": text}}],
    }
    if context_token:
        message["context_token"] = context_token
    return await _api_post(
        session,
        base_url=base_url,
        endpoint=EP_SEND_MESSAGE,
        payload={"msg": message},
        token=token,
        timeout_ms=API_TIMEOUT_MS,
    )


async def _send_typing(
    session: "aiohttp.ClientSession",
    *,
    base_url: str,
    token: str,
    to_user_id: str,
    typing_ticket: str,
    status: int,
) -> None:
    await _api_post(
        session,
        base_url=base_url,
        endpoint=EP_SEND_TYPING,
        payload={
            "ilink_user_id": to_user_id,
            "typing_ticket": typing_ticket,
            "status": status,
        },
        token=token,
        timeout_ms=CONFIG_TIMEOUT_MS,
    )


async def _get_config(
    session: "aiohttp.ClientSession",
    *,
    base_url: str,
    token: str,
    user_id: str,
    context_token: Optional[str],
) -> dict[str, Any]:
    payload: dict[str, Any] = {"ilink_user_id": user_id}
    if context_token:
        payload["context_token"] = context_token
    return await _api_post(
        session,
        base_url=base_url,
        endpoint=EP_GET_CONFIG,
        payload=payload,
        token=token,
        timeout_ms=CONFIG_TIMEOUT_MS,
    )


# ---------------------------------------------------------------------------
# Context token persistence
# ---------------------------------------------------------------------------

def _account_dir(state_dir: str) -> Path:
    path = Path(state_dir) / "weixin" / "accounts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _account_file(state_dir: str, account_id: str) -> Path:
    return _account_dir(state_dir) / f"{account_id}.json"


def save_weixin_account(
    state_dir: str,
    *,
    account_id: str,
    token: str,
    base_url: str,
    user_id: str = "",
) -> None:
    """Persist account credentials for later reuse."""
    payload = {
        "token": token,
        "base_url": base_url,
        "user_id": user_id,
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    path = _account_file(state_dir, account_id)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def load_weixin_account(state_dir: str, account_id: str) -> Optional[dict[str, Any]]:
    """Load persisted account credentials."""
    path = _account_file(state_dir, account_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("weixin: failed to load account file for %s: %s", _safe_id(account_id), exc)
        return None


class ContextTokenStore:
    """Disk-backed ``context_token`` cache keyed by account + peer."""

    def __init__(self, state_dir: str):
        self._root = _account_dir(state_dir)
        self._cache: dict[str, str] = {}

    def _path(self, account_id: str) -> Path:
        return self._root / f"{account_id}.context-tokens.json"

    def _key(self, account_id: str, user_id: str) -> str:
        return f"{account_id}:{user_id}"

    def restore(self, account_id: str) -> None:
        path = self._path(account_id)
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("weixin: failed to restore context tokens for %s: %s", _safe_id(account_id), exc)
            return
        restored = 0
        for user_id, token in data.items():
            if isinstance(token, str) and token:
                self._cache[self._key(account_id, user_id)] = token
                restored += 1
        if restored:
            logger.info("weixin: restored %d context token(s) for %s", restored, _safe_id(account_id))

    def get(self, account_id: str, user_id: str) -> Optional[str]:
        return self._cache.get(self._key(account_id, user_id))

    def set(self, account_id: str, user_id: str, token: str) -> None:
        self._cache[self._key(account_id, user_id)] = token
        self._persist(account_id)

    def _persist(self, account_id: str) -> None:
        prefix = f"{account_id}:"
        payload = {
            key[len(prefix):]: value
            for key, value in self._cache.items()
            if key.startswith(prefix)
        }
        try:
            self._path(account_id).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            logger.warning("weixin: failed to persist context tokens for %s: %s", _safe_id(account_id), exc)


class TypingTicketCache:
    """Short-lived typing ticket cache from ``getconfig``."""

    def __init__(self, ttl_seconds: float = 600.0):
        self._ttl_seconds = ttl_seconds
        self._cache: dict[str, tuple[str, float]] = {}

    def get(self, user_id: str) -> Optional[str]:
        entry = self._cache.get(user_id)
        if not entry:
            return None
        if time.time() - entry[1] >= self._ttl_seconds:
            self._cache.pop(user_id, None)
            return None
        return entry[0]

    def set(self, user_id: str, ticket: str) -> None:
        self._cache[user_id] = (ticket, time.time())


# ---------------------------------------------------------------------------
# Sync buffer persistence
# ---------------------------------------------------------------------------

def _sync_buf_path(state_dir: str, account_id: str) -> Path:
    return _account_dir(state_dir) / f"{account_id}.sync.json"


def _load_sync_buf(state_dir: str, account_id: str) -> str:
    path = _sync_buf_path(state_dir, account_id)
    if not path.exists():
        return ""
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("get_updates_buf", "")
    except Exception as exc:
        logger.warning("weixin: failed to load sync buffer for %s: %s", _safe_id(account_id), exc)
        return ""


def _save_sync_buf(state_dir: str, account_id: str, sync_buf: str) -> None:
    path = _sync_buf_path(state_dir, account_id)
    path.write_text(
        json.dumps({"get_updates_buf": sync_buf}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# QR login flow
# ---------------------------------------------------------------------------

async def qr_login(
    state_dir: str,
    *,
    bot_type: str = "3",
    timeout_seconds: int = 480,
) -> Optional[dict[str, str]]:
    """Run the interactive iLink QR login flow.

    Returns a credential dict on success, or ``None`` if login fails or times out.
    """
    import asyncio

    if not AIOHTTP_AVAILABLE:
        raise RuntimeError("aiohttp is required for Weixin QR login")

    async with aiohttp.ClientSession(trust_env=True, connector=_make_ssl_connector()) as session:
        try:
            qr_resp = await _api_get(
                session,
                base_url=ILINK_BASE_URL,
                endpoint=f"{EP_GET_BOT_QR}?bot_type={bot_type}",
                timeout_ms=QR_TIMEOUT_MS,
            )
        except Exception as exc:
            logger.error("weixin: failed to fetch QR code: %s", exc)
            return None

        qrcode_value = str(qr_resp.get("qrcode") or "")
        qrcode_url = str(qr_resp.get("qrcode_img_content") or "")
        if not qrcode_value:
            logger.error("weixin: QR response missing qrcode")
            return None

        qr_scan_data = qrcode_url if qrcode_url else qrcode_value

        print("\n请使用微信扫描以下二维码：")
        if qrcode_url:
            print(qrcode_url)
        try:
            import qrcode

            qr = qrcode.QRCode()
            qr.add_data(qr_scan_data)
            qr.make(fit=True)
            _print_qr_centered(qr)
        except Exception as _qr_exc:
            print(f"（终端二维码渲染失败: {_qr_exc}，请直接打开上面的二维码链接）")

        deadline = time.time() + timeout_seconds
        current_base_url = ILINK_BASE_URL
        refresh_count = 0

        while time.time() < deadline:
            try:
                status_resp = await _api_get(
                    session,
                    base_url=current_base_url,
                    endpoint=f"{EP_GET_QR_STATUS}?qrcode={qrcode_value}",
                    timeout_ms=QR_TIMEOUT_MS,
                )
            except asyncio.TimeoutError:
                await asyncio.sleep(1)
                continue
            except Exception as exc:
                logger.warning("weixin: QR poll error: %s", exc)
                await asyncio.sleep(1)
                continue

            status = str(status_resp.get("status") or "wait")
            if status == "wait":
                print(".", end="", flush=True)
            elif status == "scaned":
                print("\n已扫码，请在微信里确认...")
            elif status == "scaned_but_redirect":
                redirect_host = str(status_resp.get("redirect_host") or "")
                if redirect_host:
                    current_base_url = f"https://{redirect_host}"
            elif status == "expired":
                refresh_count += 1
                if refresh_count > 3:
                    print("\n二维码多次过期，请重新执行登录。")
                    return None
                print(f"\n二维码已过期，正在刷新... ({refresh_count}/3)")
                try:
                    qr_resp = await _api_get(
                        session,
                        base_url=ILINK_BASE_URL,
                        endpoint=f"{EP_GET_BOT_QR}?bot_type={bot_type}",
                        timeout_ms=QR_TIMEOUT_MS,
                    )
                    qrcode_value = str(qr_resp.get("qrcode") or "")
                    qrcode_url = str(qr_resp.get("qrcode_img_content") or "")
                    qr_scan_data = qrcode_url if qrcode_url else qrcode_value
                    if qrcode_url:
                        print(qrcode_url)
                    try:
                        import qrcode as _qrcode
                        qr = _qrcode.QRCode()
                        qr.add_data(qr_scan_data)
                        qr.make(fit=True)
                        _print_qr_centered(qr)
                    except Exception as exc:
                        logger.warning("weixin: failed to render QR code in terminal: %s", exc)
                        pass
                except Exception as exc:
                    logger.error("weixin: QR refresh failed: %s", exc)
                    return None
            elif status == "confirmed":
                account_id = str(status_resp.get("ilink_bot_id") or "")
                token = str(status_resp.get("bot_token") or "")
                base_url = str(status_resp.get("baseurl") or ILINK_BASE_URL)
                user_id = str(status_resp.get("ilink_user_id") or "")
                if not account_id or not token:
                    logger.error("weixin: QR confirmed but credential payload was incomplete")
                    return None
                save_weixin_account(
                    state_dir,
                    account_id=account_id,
                    token=token,
                    base_url=base_url,
                    user_id=user_id,
                )
                print(f"\n微信连接成功，account_id={account_id}")
                return {
                    "account_id": account_id,
                    "token": token,
                    "base_url": base_url,
                    "user_id": user_id,
                }
            await asyncio.sleep(1)

        print("\n微信登录超时。")
        return None


# ---------------------------------------------------------------------------
# Message format helpers (inbound iLink → elephant)
# ---------------------------------------------------------------------------

def _extract_text(item_list: list[dict[str, Any]]) -> str:
    for item in item_list:
        if item.get("type") == ITEM_TEXT:
            text = str((item.get("text_item") or {}).get("text") or "")
            ref = item.get("ref_msg") or {}
            ref_item = ref.get("message_item") or {}
            ref_type = ref_item.get("type")
            if ref_type in (ITEM_IMAGE, ITEM_VIDEO, ITEM_FILE, ITEM_VOICE):
                title = ref.get("title") or ""
                prefix = f"[引用媒体: {title}]\n" if title else "[引用媒体]\n"
                return f"{prefix}{text}".strip()
            if ref_item:
                parts: list[str] = []
                if ref.get("title"):
                    parts.append(str(ref["title"]))
                ref_text = _extract_text([ref_item])
                if ref_text:
                    parts.append(ref_text)
                if parts:
                    return f"[引用: {' | '.join(parts)}]\n{text}".strip()
            return text
    for item in item_list:
        if item.get("type") == ITEM_VOICE:
            voice_text = str((item.get("voice_item") or {}).get("text") or "")
            if voice_text:
                return voice_text
    return ""


def _guess_chat_type(message: dict[str, Any], account_id: str) -> tuple[str, str]:
    room_id = str(message.get("room_id") or message.get("chat_room_id") or "").strip()
    to_user_id = str(message.get("to_user_id") or "").strip()
    is_group = bool(room_id) or (
        to_user_id and account_id and to_user_id != account_id and message.get("msg_type") == 1
    )
    if is_group:
        return "group", room_id or to_user_id or str(message.get("from_user_id") or "")
    return "dm", str(message.get("from_user_id") or "")


def _weixin_chat_type(payload: Mapping[str, object]) -> str:
    room = str(payload.get("room") or "").strip()
    if room:
        return "group"
    return "direct"


def _weixin_delivery_defaults(chat_type: str) -> tuple[bool, bool, bool]:
    if chat_type == "direct":
        return True, True, False
    return False, False, True


def _weixin_display_name(payload: Mapping[str, object]) -> str | None:
    for key in ("nickname", "display_name", "name", "from_user_name"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return None


def _weixin_body(payload: Mapping[str, object]) -> str:
    content = str(payload.get("content") or "").strip()
    if content:
        return content
    for key in ("text", "message", "body"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return "weixin-message"


# ---------------------------------------------------------------------------
# Account configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class WeixinGatewayAccountConfig:
    account_id: str = DEFAULT_GATEWAY_ACCOUNT_ID
    token: str = ""
    base_url: str = ILINK_BASE_URL
    cdn_base_url: str = WEIXIN_CDN_BASE_URL
    surface: str = "ilink"
    enabled: bool = True
    dm_policy: str = "open"
    group_policy: str = "disabled"
    allow_from: tuple[str, ...] = ()
    group_allow_from: tuple[str, ...] = ()
    split_multiline_messages: bool = False
    event_path: str = DEFAULT_WEIXIN_EVENT_PATH
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WeixinResolvedAccount:
    account_id: str
    config: WeixinGatewayAccountConfig


@dataclass(frozen=True, slots=True)
class WeixinGatewayEventResult:
    exchange: GatewayExchange | None
    response_body: Mapping[str, object]
    delivery_request: Mapping[str, object] | None = None
    delivery_response: Mapping[str, object] | None = None


def _coerce_list(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return (str(value).strip(),) if str(value).strip() else ()


def load_weixin_gateway_accounts(
    app: GatewayApp,
    *,
    respect_enabled: bool = True,
    include_disabled: bool = False,
) -> tuple[WeixinGatewayAccountConfig, ...]:
    manifest = app.loaded_profile.manifest if app.loaded_profile is not None else {}
    gateway_payload = _mapping(manifest.get("gateway")) or {}
    adapters_payload = _mapping(gateway_payload.get("adapters")) or {}
    weixin_payload = _mapping(adapters_payload.get("weixin"))
    if respect_enabled and weixin_payload is not None and weixin_payload.get("enabled") is False:
        return ()

    default_surface = _normalize_transport((weixin_payload or {}).get("surface"))
    default_event_path = _normalize_path((weixin_payload or {}).get("event_path"))
    accounts_payload = (weixin_payload or {}).get("accounts")
    if isinstance(accounts_payload, list) and accounts_payload:
        resolved: list[WeixinGatewayAccountConfig] = []
        for index, account_payload in enumerate(accounts_payload):
            account_mapping = _mapping(account_payload)
            if account_mapping is None:
                raise ValueError("gateway.adapters.weixin.accounts entries must be JSON objects")
            account_enabled = _coerce_bool(account_mapping.get("enabled"), default=True)
            if not include_disabled and not account_enabled:
                continue
            # Skip legacy wxhook accounts that have no iLink token
            account_token = str(account_mapping.get("token") or "")
            account_surface = _normalize_transport(account_mapping.get("surface"))
            if not account_token and account_surface == "ilink":
                continue
            resolved.append(
                WeixinGatewayAccountConfig(
                    account_id=str(account_mapping.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID),
                    token=str(account_mapping.get("token") or ""),
                    base_url=str(account_mapping.get("base_url") or ILINK_BASE_URL),
                    cdn_base_url=str(account_mapping.get("cdn_base_url") or WEIXIN_CDN_BASE_URL),
                    surface=str(account_mapping.get("surface") or default_surface),
                    enabled=account_enabled,
                    dm_policy=str(account_mapping.get("dm_policy") or "open"),
                    group_policy=str(account_mapping.get("group_policy") or "disabled"),
                    allow_from=_coerce_list(account_mapping.get("allow_from")),
                    group_allow_from=_coerce_list(account_mapping.get("group_allow_from")),
                    split_multiline_messages=_coerce_bool(
                        account_mapping.get("split_multiline_messages"), default=False
                    ),
                    event_path=_normalize_path(account_mapping.get("event_path") or default_event_path),
                    metadata={"manifest_index": index},
                )
            )
        return tuple(resolved)

    return (WeixinGatewayAccountConfig(surface=default_surface, event_path=default_event_path),)


def resolve_weixin_account(config: WeixinGatewayAccountConfig) -> WeixinResolvedAccount:
    return WeixinResolvedAccount(
        account_id=config.account_id,
        config=config,
    )


__all__ = [name for name in globals() if not name.startswith("_") and name not in {"logger"}]
