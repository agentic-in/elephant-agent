"""Support helpers and data contracts for the Feishu gateway."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import importlib.util
import json
import logging
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from packages.gateway_core import (
    DEFAULT_GATEWAY_ACCOUNT_ID,
    GatewayExchange,
)

from packages.auth import SecretReference


DEFAULT_FEISHU_APP_ID_ENV = "ELEPHANT_FEISHU_APP_ID"
DEFAULT_FEISHU_APP_SECRET_ENV = "ELEPHANT_FEISHU_APP_SECRET"
LEGACY_FEISHU_APP_ID_ENV = "FEISHU_APP_ID"
LEGACY_FEISHU_APP_SECRET_ENV = "FEISHU_APP_SECRET"
DEFAULT_FEISHU_BASE_URL = "https://open.feishu.cn"
DEFAULT_FEISHU_EVENT_PATH = "/feishu/events"
DEFAULT_FEISHU_TOKEN_PATH = "/open-apis/auth/v3/tenant_access_token/internal"
SUPPORTED_FEISHU_TRANSPORTS = ("long-connection",)
FEISHU_SDK_PIP_SPEC = "lark-oapi>=1.5.3,<2"
DEFAULT_FEISHU_INBOUND_EVENT_RETENTION_SECONDS = 60 * 60 * 24 * 3
DEFAULT_FEISHU_INBOUND_EVENT_MAX_RECORDS = 4096
DEFAULT_FEISHU_ASYNC_JOB_RETENTION_SECONDS = DEFAULT_FEISHU_INBOUND_EVENT_RETENTION_SECONDS
DEFAULT_FEISHU_ASYNC_JOB_MAX_RECORDS = DEFAULT_FEISHU_INBOUND_EVENT_MAX_RECORDS
DEFAULT_FEISHU_ASYNC_WORKER_COUNT = 2
DEFAULT_FEISHU_ASYNC_FAILURE_HISTORY = 5
DEFAULT_FEISHU_PLACEHOLDER_BODY = "已收到，正在处理中..."
DEFAULT_FEISHU_FAILURE_BODY = "处理失败，请稍后重试。"

HttpJsonRequester = Callable[[str, str, Mapping[str, object], Mapping[str, str]], Mapping[str, object]]
FeishuWSClientFactory = Callable[[Any, str, str, object, object | None], object]

LOGGER = logging.getLogger(__name__)


def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_path(value: str | None) -> str:
    text = str(value or DEFAULT_FEISHU_EVENT_PATH).strip() or DEFAULT_FEISHU_EVENT_PATH
    return text if text.startswith("/") else f"/{text}"


def _normalize_transport(value: str | None) -> str:
    normalized = str(value or "webhook").strip().lower().replace("_", "-")
    if normalized in {"long-connection", "longconnection", "websocket", "ws"}:
        return "long-connection"
    if normalized in {"event-subscription", "callback", "http", "webhook"}:
        return "webhook"
    raise ValueError("feishu transport must be one of long-connection, webhook")


def _normalize_configured_transport(value: str | None) -> str:
    normalized = str(value or "long-connection").strip().lower().replace("_", "-")
    if normalized in {"long-connection", "longconnection", "websocket", "ws"}:
        return "long-connection"
    if normalized in {"event-subscription", "callback", "http", "webhook"}:
        return "long-connection"
    raise ValueError("feishu configured transport must resolve to long-connection")


def _json_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")


def _default_json_request(
    method: str,
    url: str,
    payload: Mapping[str, object],
    headers: Mapping[str, str],
) -> Mapping[str, object]:
    request = Request(
        url,
        data=_json_bytes(payload),
        method=method.upper(),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "User-Agent": "elephant-gateway/feishu",
            **dict(headers),
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8")
        raise RuntimeError(f"feishu request failed with HTTP {exc.code}: {detail or exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"feishu request failed: {exc.reason}") from exc
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("feishu request returned a non-JSON response") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("feishu request returned a non-object JSON response")
    if int(parsed.get("code", 0) or 0) != 0:
        raise RuntimeError(f"feishu request rejected: code={parsed.get('code')} msg={parsed.get('msg')}")
    return parsed


def _lark_sdk_dependency_status() -> str:
    return "installed" if importlib.util.find_spec("lark_oapi") is not None else "missing_optional_dependency"


def _load_lark_sdk(lark_module: Any | None = None) -> Any:
    if lark_module is not None:
        return lark_module
    try:
        import lark_oapi as lark  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised by integration path
        raise RuntimeError(
            "Feishu long-connection transport requires the bundled dependency "
            "'lark-oapi'. Reinstall Elephant Agent or add the package to your environment if it is missing."
        ) from exc
    return lark


def _lark_log_level(lark_module: Any, level_name: str) -> object | None:
    log_levels = getattr(lark_module, "LogLevel", None)
    if log_levels is None:
        return None
    normalized = str(level_name or "INFO").strip().upper().replace("-", "_")
    return getattr(log_levels, normalized, None)


def _lark_event_payload(event: object, *, lark_module: Any) -> Mapping[str, object]:
    marshaled = getattr(getattr(lark_module, "JSON", None), "marshal", None)
    if not callable(marshaled):
        raise RuntimeError("lark_oapi.JSON.marshal is unavailable")
    raw = marshaled(event)
    try:
        parsed = json.loads(str(raw or "{}"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("lark_oapi long-connection event was not valid JSON") from exc
    if not isinstance(parsed, Mapping):
        raise RuntimeError("lark_oapi long-connection event did not marshal to a JSON object")
    return parsed


def _default_ws_client_factory(
    lark_module: Any,
    app_id: str,
    app_secret: str,
    event_handler: object,
    log_level: object | None,
) -> object:
    ws_client = getattr(getattr(lark_module, "ws", None), "Client", None)
    if ws_client is None:
        raise RuntimeError("lark_oapi long-connection client is unavailable")
    return ws_client(
        app_id,
        app_secret,
        event_handler=event_handler,
        log_level=log_level,
    )


@dataclass(frozen=True, slots=True)
class FeishuGatewayAccountConfig:
    account_id: str = DEFAULT_GATEWAY_ACCOUNT_ID
    app_id_env_var: str = DEFAULT_FEISHU_APP_ID_ENV
    app_secret_env_var: str = DEFAULT_FEISHU_APP_SECRET_ENV
    secret_references: tuple[SecretReference, ...] = ()
    surface: str = "webhook"
    event_path: str = DEFAULT_FEISHU_EVENT_PATH
    base_url: str = DEFAULT_FEISHU_BASE_URL
    token_path: str = DEFAULT_FEISHU_TOKEN_PATH
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FeishuResolvedAccount:
    account_id: str
    app_id: str
    app_secret: str
    config: FeishuGatewayAccountConfig


@dataclass(frozen=True, slots=True)
class FeishuGatewayEventResult:
    exchange: GatewayExchange | None
    response_body: Mapping[str, object]
    delivery_request: Mapping[str, object] | None = None
    delivery_response: Mapping[str, object] | None = None


@dataclass(slots=True)
class _FeishuTokenCacheEntry:
    token: str
    expires_at: float


@dataclass(frozen=True, slots=True)
class FeishuInboundEventRecord:
    account_id: str
    event_id: str | None
    message_id: str | None
    response_body: Mapping[str, object]
    recorded_at: float


__all__ = [
    "DEFAULT_FEISHU_APP_ID_ENV",
    "DEFAULT_FEISHU_APP_SECRET_ENV",
    "LEGACY_FEISHU_APP_ID_ENV",
    "LEGACY_FEISHU_APP_SECRET_ENV",
    "DEFAULT_FEISHU_BASE_URL",
    "DEFAULT_FEISHU_EVENT_PATH",
    "DEFAULT_FEISHU_TOKEN_PATH",
    "SUPPORTED_FEISHU_TRANSPORTS",
    "FEISHU_SDK_PIP_SPEC",
    "DEFAULT_FEISHU_INBOUND_EVENT_RETENTION_SECONDS",
    "DEFAULT_FEISHU_INBOUND_EVENT_MAX_RECORDS",
    "DEFAULT_FEISHU_ASYNC_JOB_RETENTION_SECONDS",
    "DEFAULT_FEISHU_ASYNC_JOB_MAX_RECORDS",
    "DEFAULT_FEISHU_ASYNC_WORKER_COUNT",
    "DEFAULT_FEISHU_ASYNC_FAILURE_HISTORY",
    "DEFAULT_FEISHU_PLACEHOLDER_BODY",
    "DEFAULT_FEISHU_FAILURE_BODY",
    "HttpJsonRequester",
    "FeishuWSClientFactory",
    "LOGGER",
    "_mapping",
    "_optional_text",
    "_normalize_path",
    "_normalize_transport",
    "_normalize_configured_transport",
    "_json_bytes",
    "_default_json_request",
    "_lark_sdk_dependency_status",
    "_load_lark_sdk",
    "_lark_log_level",
    "_lark_event_payload",
    "_default_ws_client_factory",
    "FeishuGatewayAccountConfig",
    "FeishuResolvedAccount",
    "FeishuGatewayEventResult",
    "_FeishuTokenCacheEntry",
    "FeishuInboundEventRecord",
]
