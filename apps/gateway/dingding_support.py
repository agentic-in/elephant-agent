"""DingDing gateway bootstrap, account config, and delivery wiring."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import importlib.util
import os

from packages.gateway_core import (
    DEFAULT_GATEWAY_ACCOUNT_ID,
    GatewayExchange,
    GatewayOutboundMessage,
)

from .runtime import (
    GatewayApp,
)

DEFAULT_DINGDING_CLIENT_ID_ENV = "ELEPHANT_DINGDING_CLIENT_ID"
DEFAULT_DINGDING_CLIENT_SECRET_ENV = "ELEPHANT_DINGDING_CLIENT_SECRET"
DEFAULT_DINGDING_ROBOT_CODE_ENV = "ELEPHANT_DINGDING_ROBOT_CODE"
SUPPORTED_DINGDING_TRANSPORTS = ("stream",)
DINGTALK_STREAM_PIP_SPEC = "dingtalk-stream>=0.24.0"


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
    normalized = str(value or "stream").strip().lower().replace("_", "-")
    if normalized in {"stream", "dingtalk-stream"}:
        return "stream"
    raise ValueError(f"dingding transport must be one of {', '.join(SUPPORTED_DINGDING_TRANSPORTS)}")


def _dingtalk_stream_dependency_status() -> str:
    return "installed" if importlib.util.find_spec("dingtalk_stream") is not None else "missing_optional_dependency"


def _load_dingtalk_stream_sdk(dingtalk_module: object | None = None) -> object:
    if dingtalk_module is not None:
        return dingtalk_module
    try:
        import dingtalk_stream  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "DingDing gateway transport requires the 'dingtalk-stream' package. "
            "Install it with: pip install dingtalk-stream"
        ) from exc
    return dingtalk_stream


@dataclass(frozen=True, slots=True)
class DingdingGatewayAccountConfig:
    account_id: str = DEFAULT_GATEWAY_ACCOUNT_ID
    client_id_env_var: str = DEFAULT_DINGDING_CLIENT_ID_ENV
    client_secret_env_var: str = DEFAULT_DINGDING_CLIENT_SECRET_ENV
    robot_code_env_var: str = DEFAULT_DINGDING_ROBOT_CODE_ENV
    surface: str = "stream"
    enabled: bool = True
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DingdingResolvedAccount:
    account_id: str
    client_id: str
    client_secret: str
    robot_code: str
    config: DingdingGatewayAccountConfig


@dataclass(frozen=True, slots=True)
class DingdingGatewayEventResult:
    exchange: GatewayExchange | None
    response_body: Mapping[str, object]
    delivery_request: Mapping[str, object] | None = None
    delivery_response: Mapping[str, object] | None = None


def load_dingding_gateway_accounts(
    app: GatewayApp,
    *,
    respect_enabled: bool = True,
    include_disabled: bool = False,
) -> tuple[DingdingGatewayAccountConfig, ...]:
    manifest = app.loaded_profile.manifest if app.loaded_profile is not None else {}
    gateway_payload = _mapping(manifest.get("gateway")) or {}
    adapters_payload = _mapping(gateway_payload.get("adapters")) or {}
    dingding_payload = _mapping(adapters_payload.get("dingding"))
    if respect_enabled and dingding_payload is not None and dingding_payload.get("enabled") is False:
        return ()

    default_surface = _normalize_transport((dingding_payload or {}).get("surface"))
    accounts_payload = (dingding_payload or {}).get("accounts")
    if isinstance(accounts_payload, list) and accounts_payload:
        resolved: list[DingdingGatewayAccountConfig] = []
        for index, account_payload in enumerate(accounts_payload):
            account_mapping = _mapping(account_payload)
            if account_mapping is None:
                raise ValueError("gateway.adapters.dingding.accounts entries must be JSON objects")
            account_enabled = _coerce_bool(account_mapping.get("enabled"), default=True)
            if not include_disabled and not account_enabled:
                continue
            env_payload = _mapping(account_mapping.get("env")) or {}
            resolved.append(
                DingdingGatewayAccountConfig(
                    account_id=str(account_mapping.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID),
                    client_id_env_var=str(env_payload.get("client_id") or DEFAULT_DINGDING_CLIENT_ID_ENV),
                    client_secret_env_var=str(env_payload.get("client_secret") or DEFAULT_DINGDING_CLIENT_SECRET_ENV),
                    robot_code_env_var=str(env_payload.get("robot_code") or DEFAULT_DINGDING_ROBOT_CODE_ENV),
                    surface=str(account_mapping.get("surface") or default_surface),
                    enabled=account_enabled,
                    metadata={"manifest_index": index},
                )
            )
        return tuple(resolved)

    return (DingdingGatewayAccountConfig(surface=default_surface),)


def resolve_dingding_account(
    config: DingdingGatewayAccountConfig,
    *,
    environ: Mapping[str, str] | None = None,
) -> DingdingResolvedAccount:
    env = environ or os.environ
    client_id = str(env.get(config.client_id_env_var) or "").strip()
    client_secret = str(env.get(config.client_secret_env_var) or "").strip()
    robot_code = str(env.get(config.robot_code_env_var) or "").strip()
    if not client_id:
        raise LookupError(f"dingding account '{config.account_id}' requires {config.client_id_env_var}")
    if not client_secret:
        raise LookupError(f"dingding account '{config.account_id}' requires {config.client_secret_env_var}")
    return DingdingResolvedAccount(
        account_id=config.account_id,
        client_id=client_id,
        client_secret=client_secret,
        robot_code=robot_code,
        config=config,
    )


def _dingding_delivery_defaults(chat_type: str) -> tuple[bool, bool, bool]:
    if chat_type == "direct":
        return True, True, False
    return False, False, True


def _dingding_display_name(payload: Mapping[str, object]) -> str | None:
    for key in ("nick", "display_name", "name", "sender_nick"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return None


def _dingding_chat_type(payload: Mapping[str, object]) -> str:
    conversation_type = str(payload.get("conversation_type") or "").strip().lower()
    if conversation_type in {"1", "p2p", "private", "direct"}:
        return "direct"
    if conversation_type in {"2", "group"}:
        return "group"
    return "direct"


def _dingding_body(payload: Mapping[str, object]) -> str:
    content = str(payload.get("content") or "").strip()
    if content:
        return content
    text_content = payload.get("text", {})
    if isinstance(text_content, Mapping):
        text = str(text_content.get("content") or text_content.get("text") or "").strip()
        if text:
            return text
    return "dingding-message"


def _dingding_reply_request(outbound: GatewayOutboundMessage) -> Mapping[str, object]:
    rendered_body = outbound.body
    return {
        "method": "POST",
        "path": "/v1.0/robot/oToMessages/batchSend",
        "body": {
            "robotCode": outbound.metadata.get("robot_code", ""),
            "userIds": [outbound.conversation_id],
            "msgKey": "sampleMarkdown",
            "msgParam": rendered_body,
        },
    }


__all__ = [name for name in globals() if not name.startswith("__")]
