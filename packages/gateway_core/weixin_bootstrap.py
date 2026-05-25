"""Weixin iLink bootstrap helpers shared by app surfaces."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any

ILINK_BASE_URL = "https://ilinkai.weixin.qq.com"
ILINK_APP_ID = "bot"
ILINK_APP_CLIENT_VERSION = (2 << 16) | (2 << 8) | 0
EP_GET_BOT_QR = "ilink/bot/get_bot_qrcode"
EP_GET_QR_STATUS = "ilink/bot/get_qrcode_status"
QR_TIMEOUT_MS = 35_000

try:
    import aiohttp

    AIOHTTP_AVAILABLE = True
except ImportError:
    aiohttp = None  # type: ignore[assignment]
    AIOHTTP_AVAILABLE = False

try:
    import cryptography  # noqa: F401

    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False


def check_weixin_requirements() -> bool:
    """Return True when runtime dependencies for Weixin QR bootstrap exist."""
    return AIOHTTP_AVAILABLE and CRYPTO_AVAILABLE


def make_ssl_connector() -> "aiohttp.TCPConnector | None":
    """Return an aiohttp connector backed by certifi when available."""
    try:
        import ssl

        import certifi
    except ImportError:
        return None
    if not AIOHTTP_AVAILABLE:
        return None
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    return aiohttp.TCPConnector(ssl=ssl_ctx)


async def api_get(
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
            raise RuntimeError(
                f"iLink GET {endpoint} HTTP {response.status}: {raw[:200]}"
            )
        return json.loads(raw)


async def fetch_weixin_qr(*, bot_type: str) -> dict[str, Any]:
    if not check_weixin_requirements():
        raise RuntimeError(
            "WeChat QR login requires aiohttp and cryptography. Install gateway WeChat dependencies first."
        )
    async with aiohttp.ClientSession(
        trust_env=True, connector=make_ssl_connector()
    ) as session:
        return await api_get(
            session,
            base_url=ILINK_BASE_URL,
            endpoint=f"{EP_GET_BOT_QR}?bot_type={bot_type}",
            timeout_ms=QR_TIMEOUT_MS,
        )


async def poll_weixin_qr(*, qrcode: str, base_url: str) -> dict[str, Any]:
    if not check_weixin_requirements():
        raise RuntimeError(
            "WeChat QR login requires aiohttp and cryptography. Install gateway WeChat dependencies first."
        )
    async with aiohttp.ClientSession(
        trust_env=True, connector=make_ssl_connector()
    ) as session:
        return await api_get(
            session,
            base_url=base_url,
            endpoint=f"{EP_GET_QR_STATUS}?qrcode={qrcode}",
            timeout_ms=QR_TIMEOUT_MS,
        )


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
    """Persist account credentials for later reuse by Weixin gateway workers."""
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
