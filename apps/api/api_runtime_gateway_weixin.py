"""Weixin QR helpers for the API gateway console surface."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
import asyncio
import time

from packages.gateway_core import weixin_bootstrap as weixin_qr

from .api_runtime_console_config import _write_manifest_to_config
from .api_runtime_gateway_ops import (
    _gateway_accounts,
    _gateway_adapter_payload,
    _gateway_manifest,
    _gateway_qr_matrix,
    _gateway_upsert_account,
    _gateway_view,
)


def _gateway_weixin_session_store(self) -> dict[str, dict[str, Any]]:
    store = getattr(self, "_gateway_weixin_qr_sessions", None)
    if not isinstance(store, dict):
        store = {}
        setattr(self, "_gateway_weixin_qr_sessions", store)
    return store


def _gateway_weixin_config_from_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    config = (
        payload.get("config") if isinstance(payload.get("config"), Mapping) else payload
    )
    return dict(config)


def _gateway_weixin_qr_payload(
    session_id: str, session_state: Mapping[str, Any], *, status: str = "wait"
) -> dict[str, Any]:
    scan_data = str(session_state.get("qrScanData") or "")
    return {
        "status": status,
        "service": "weixin",
        "action": "qr",
        "sessionId": session_id,
        "qrcode": session_state.get("qrcode"),
        "qrcodeUrl": session_state.get("qrcodeUrl"),
        "qrScanData": scan_data,
        "qrMatrix": _gateway_qr_matrix(scan_data) if scan_data else (),
        "expiresAt": session_state.get("expiresAt"),
    }


async def _fetch_weixin_qr(*, bot_type: str) -> dict[str, Any]:
    return await weixin_qr.fetch_weixin_qr(bot_type=bot_type)


async def _poll_weixin_qr(*, qrcode: str, base_url: str) -> dict[str, Any]:
    return await weixin_qr.poll_weixin_qr(qrcode=qrcode, base_url=base_url)


def _gateway_weixin_qr_start(self, payload: Mapping[str, Any]) -> dict[str, Any]:
    qr_resp = asyncio.run(_fetch_weixin_qr(bot_type=str(payload.get("botType") or "3")))
    qrcode_value = str(qr_resp.get("qrcode") or "")
    qrcode_url = str(qr_resp.get("qrcode_img_content") or "")
    if not qrcode_value:
        raise ValueError("WeChat QR response did not include qrcode")
    session_id = f"weixin-qr-{int(time.time() * 1000)}"
    scan_data = qrcode_url if qrcode_url else qrcode_value
    expires_at = datetime.fromtimestamp(time.time() + 480, UTC).isoformat()
    session_state = {
        "qrcode": qrcode_value,
        "qrcodeUrl": qrcode_url,
        "qrScanData": scan_data,
        "baseUrl": "https://ilinkai.weixin.qq.com",
        "expiresAt": expires_at,
        "config": _gateway_weixin_config_from_payload(payload),
    }
    _gateway_weixin_session_store(self)[session_id] = session_state
    return _gateway_weixin_qr_payload(session_id, session_state, status="wait")


def _gateway_persist_weixin_credentials(
    self, credentials: Mapping[str, Any], config: Mapping[str, Any]
) -> dict[str, Any]:
    database_path = self.repository.database_path
    state_dir = database_path.parent
    manifest = _gateway_manifest(state_dir)
    gateway_payload, adapters_payload, adapter_payload = _gateway_adapter_payload(
        manifest, "weixin"
    )
    accounts = _gateway_accounts(adapter_payload)
    account_id = str(
        credentials.get("account_id") or credentials.get("ilink_bot_id") or ""
    ).strip()
    token = str(credentials.get("token") or credentials.get("bot_token") or "").strip()
    if not account_id or not token:
        raise ValueError("WeChat QR confirmation did not include account_id and token")
    weixin_qr.save_weixin_account(
        str(state_dir),
        account_id=account_id,
        token=token,
        base_url=str(
            credentials.get("base_url")
            or credentials.get("baseurl")
            or weixin_qr.ILINK_BASE_URL
        ),
        user_id=str(
            credentials.get("user_id") or credentials.get("ilink_user_id") or ""
        ),
    )
    control_payload = (
        dict(adapter_payload.get("control"))
        if isinstance(adapter_payload.get("control"), Mapping)
        else {}
    )
    allow_group_chats = (
        bool(config.get("allowGroupChats"))
        if isinstance(config.get("allowGroupChats"), bool)
        else bool(control_payload.get("allow_group_chats") is True)
    )
    account_payload: dict[str, Any] = {
        "account_id": account_id,
        "token": token,
        "base_url": str(
            credentials.get("base_url")
            or credentials.get("baseurl")
            or weixin_qr.ILINK_BASE_URL
        ),
        "user_id": str(
            credentials.get("user_id") or credentials.get("ilink_user_id") or ""
        ),
        "surface": "ilink",
        "enabled": (
            bool(config.get("accountEnabled"))
            if isinstance(config.get("accountEnabled"), bool)
            else True
        ),
    }
    event_path = str(
        config.get("eventPath")
        or config.get("event_path")
        or adapter_payload.get("event_path")
        or "/weixin/events"
    ).strip()
    if event_path:
        account_payload["event_path"] = event_path
    adapter_payload["accounts"] = _gateway_upsert_account(accounts, account_payload)
    adapter_payload["surface"] = "ilink"
    adapter_payload["enabled"] = (
        bool(config.get("enabled")) if isinstance(config.get("enabled"), bool) else True
    )
    adapter_payload["event_path"] = event_path
    control_payload.pop("default_elephant_id", None)
    control_payload.pop("default_session_id", None)
    control_payload.pop("auto_create_elephant", None)
    if allow_group_chats:
        control_payload["allow_group_chats"] = True
    else:
        control_payload.pop("allow_group_chats", None)
    if control_payload:
        adapter_payload["control"] = control_payload
    else:
        adapter_payload.pop("control", None)
    adapters_payload["weixin"] = adapter_payload
    gateway_payload["adapters"] = adapters_payload
    manifest["gateway"] = gateway_payload
    manifest_path = _write_manifest_to_config(state_dir, manifest)
    return {
        "profileManifestPath": str(manifest_path),
        "gateway": _gateway_view(self, state_dir),
    }


def _gateway_weixin_qr_poll(self, payload: Mapping[str, Any]) -> dict[str, Any]:
    session_id = str(
        payload.get("sessionId") or payload.get("session_id") or ""
    ).strip()
    store = _gateway_weixin_session_store(self)
    session_state = store.get(session_id)
    if not session_id or session_state is None:
        raise ValueError(
            "WeChat QR session is missing or expired; start QR setup again"
        )
    if (
        time.time()
        > datetime.fromisoformat(str(session_state["expiresAt"])).timestamp()
    ):
        store.pop(session_id, None)
        return {
            **_gateway_weixin_qr_payload(session_id, session_state, status="expired"),
            "message": "QR session expired; start again.",
        }
    status_resp = asyncio.run(
        _poll_weixin_qr(
            qrcode=str(session_state["qrcode"]),
            base_url=str(
                session_state.get("baseUrl") or "https://ilinkai.weixin.qq.com"
            ),
        )
    )
    status = str(status_resp.get("status") or "wait")
    if status == "scaned_but_redirect":
        redirect_host = str(status_resp.get("redirect_host") or "").strip()
        if redirect_host:
            session_state["baseUrl"] = f"https://{redirect_host}"
        return {
            **_gateway_weixin_qr_payload(session_id, session_state, status=status),
            "message": "Redirected QR polling host.",
        }
    if status == "confirmed":
        credentials = {
            "account_id": str(status_resp.get("ilink_bot_id") or ""),
            "token": str(status_resp.get("bot_token") or ""),
            "base_url": str(
                status_resp.get("baseurl") or "https://ilinkai.weixin.qq.com"
            ),
            "user_id": str(status_resp.get("ilink_user_id") or ""),
        }
        persisted = _gateway_persist_weixin_credentials(
            self, credentials, dict(session_state.get("config") or {})
        )
        store.pop(session_id, None)
        return {
            **_gateway_weixin_qr_payload(session_id, session_state, status="confirmed"),
            "message": f"WeChat connected as {credentials['account_id']}",
            "credentials": {
                "account_id": credentials["account_id"],
                "base_url": credentials["base_url"],
                "user_id": credentials["user_id"],
            },
            **persisted,
        }
    if status == "need_verifycode":
        return {
            **_gateway_weixin_qr_payload(session_id, session_state, status=status),
            "message": "Scanned. Please confirm the verification code on your phone to continue.",
        }
    return {
        **_gateway_weixin_qr_payload(session_id, session_state, status=status),
        "message": "Scan the QR with WeChat and confirm login.",
    }
