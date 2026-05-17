"""Telegram transport bootstrap for the gateway surface."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from packages.gateway_core import GatewayExchange, GatewayOutboundMessage

from .plugins import GatewayPluginRegistry
from .runtime import DEFAULT_GATEWAY_ACCOUNT_ID, GatewayApp, TelegramMessagingAdapter, build_gateway_app

DEFAULT_TELEGRAM_BOT_TOKEN_ENV = "ELEPHANT_TELEGRAM_BOT_TOKEN"
LEGACY_TELEGRAM_BOT_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
DEFAULT_TELEGRAM_BASE_URL = "https://api.telegram.org"
DEFAULT_TELEGRAM_EVENT_PATH = "/telegram/events"
SUPPORTED_TELEGRAM_TRANSPORTS = ("webhook",)

HttpJsonRequester = Callable[[str, str, Mapping[str, object], Mapping[str, str]], Mapping[str, object]]


def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _normalize_path(value: str | None) -> str:
    text = str(value or DEFAULT_TELEGRAM_EVENT_PATH).strip() or DEFAULT_TELEGRAM_EVENT_PATH
    return text if text.startswith("/") else f"/{text}"


def _normalize_transport(value: str | None) -> str:
    normalized = str(value or "webhook").strip().lower().replace("_", "-")
    if normalized in {"callback", "http", "webhook"}:
        return "webhook"
    raise ValueError(
        "telegram transport must be one of "
        f"{', '.join(SUPPORTED_TELEGRAM_TRANSPORTS)}"
    )


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
            "User-Agent": "elephant-gateway/telegram",
            **dict(headers),
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8")
        raise RuntimeError(
            f"telegram request failed with HTTP {exc.code}: {detail or exc.reason}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(f"telegram request failed: {exc.reason}") from exc
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("telegram request returned a non-JSON response") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("telegram request returned a non-object JSON response")
    if parsed.get("ok") is False:
        raise RuntimeError(
            f"telegram request rejected: description={parsed.get('description')} error_code={parsed.get('error_code')}"
        )
    return parsed


@dataclass(frozen=True, slots=True)
class TelegramGatewayAccountConfig:
    account_id: str = DEFAULT_GATEWAY_ACCOUNT_ID
    bot_token_env_var: str = DEFAULT_TELEGRAM_BOT_TOKEN_ENV
    surface: str = "webhook"
    event_path: str = DEFAULT_TELEGRAM_EVENT_PATH
    base_url: str = DEFAULT_TELEGRAM_BASE_URL
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TelegramResolvedAccount:
    account_id: str
    bot_token: str
    config: TelegramGatewayAccountConfig


@dataclass(frozen=True, slots=True)
class TelegramGatewayEventResult:
    exchange: GatewayExchange | None
    response_body: Mapping[str, object]
    delivery_request: Mapping[str, object] | None = None
    delivery_response: Mapping[str, object] | None = None


def load_telegram_gateway_accounts(app: GatewayApp) -> tuple[TelegramGatewayAccountConfig, ...]:
    manifest = app.loaded_profile.manifest if app.loaded_profile is not None else {}
    gateway_payload = _mapping(manifest.get("gateway")) or {}
    adapters_payload = _mapping(gateway_payload.get("adapters")) or {}
    telegram_payload = _mapping(adapters_payload.get("telegram"))
    if telegram_payload is not None and telegram_payload.get("enabled") is False:
        return ()

    default_surface = str((telegram_payload or {}).get("surface") or "webhook")
    default_event_path = _normalize_path((telegram_payload or {}).get("event_path"))
    default_base_url = str((telegram_payload or {}).get("base_url") or DEFAULT_TELEGRAM_BASE_URL)
    accounts_payload = (telegram_payload or {}).get("accounts")
    if isinstance(accounts_payload, list) and accounts_payload:
        resolved: list[TelegramGatewayAccountConfig] = []
        for index, account_payload in enumerate(accounts_payload):
            account_mapping = _mapping(account_payload)
            if account_mapping is None:
                raise ValueError("gateway.adapters.telegram.accounts entries must be JSON objects")
            env_payload = _mapping(account_mapping.get("env")) or {}
            resolved.append(
                TelegramGatewayAccountConfig(
                    account_id=str(account_mapping.get("account_id") or DEFAULT_GATEWAY_ACCOUNT_ID),
                    bot_token_env_var=str(
                        env_payload.get("bot_token") or DEFAULT_TELEGRAM_BOT_TOKEN_ENV
                    ),
                    surface=str(account_mapping.get("surface") or default_surface),
                    event_path=_normalize_path(account_mapping.get("event_path") or default_event_path),
                    base_url=str(account_mapping.get("base_url") or default_base_url),
                    metadata={"manifest_index": index},
                )
            )
        return tuple(resolved)

    return (
        TelegramGatewayAccountConfig(
            surface=default_surface,
            event_path=default_event_path,
            base_url=default_base_url,
        ),
    )


def resolve_telegram_account(
    config: TelegramGatewayAccountConfig,
    *,
    environ: Mapping[str, str] | None = None,
) -> TelegramResolvedAccount:
    env = environ or os.environ
    bot_token = str(env.get(config.bot_token_env_var) or "")
    if not bot_token and config.bot_token_env_var == DEFAULT_TELEGRAM_BOT_TOKEN_ENV:
        bot_token = str(env.get(LEGACY_TELEGRAM_BOT_TOKEN_ENV) or "")
    if not bot_token:
        raise LookupError(
            f"telegram account '{config.account_id}' requires {config.bot_token_env_var}"
        )
    return TelegramResolvedAccount(
        account_id=config.account_id,
        bot_token=bot_token,
        config=config,
    )


@dataclass(slots=True)
class TelegramGatewayService:
    app: GatewayApp
    account_configs: tuple[TelegramGatewayAccountConfig, ...] = ()
    http_requester: HttpJsonRequester = _default_json_request
    environ: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    adapter: TelegramMessagingAdapter | None = None
    service_key: str = "telegram"

    def __post_init__(self) -> None:
        if not self.account_configs:
            self.account_configs = load_telegram_gateway_accounts(self.app)
        if self.adapter is None:
            self.adapter = TelegramMessagingAdapter(app=self.app)

    @property
    def event_paths(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(config.event_path for config in self.account_configs))

    @property
    def http_paths(self) -> tuple[str, ...]:
        return self.event_paths

    def has_credentials(self) -> bool:
        """Return True if at least one account can be resolved with current environment."""
        for config in self.account_configs:
            try:
                resolve_telegram_account(config, environ=self.environ)
                return True
            except (LookupError, RuntimeError):
                continue
        return False

    def describe(self) -> Mapping[str, object]:
        accounts: list[dict[str, object]] = []
        for config in self.account_configs:
            status = "configured"
            try:
                resolve_telegram_account(config, environ=self.environ)
            except LookupError:
                status = "missing_credentials"
            accounts.append(
                {
                    "account_id": config.account_id,
                    "surface": config.surface,
                    "event_path": config.event_path,
                    "bot_token_env_var": config.bot_token_env_var,
                    "credentials_status": status,
                }
            )
        return {
            "adapter_id": self.adapter.adapter_id if self.adapter is not None else "messaging.telegram",
            "profile_id": self.app.profile_id,
            "implemented_transports": ("webhook-bridge",),
            "configured_transport": self.configured_transport(),
            "event_paths": self.event_paths,
            "accounts": tuple(accounts),
        }

    def configured_transport(self) -> str:
        if not self.account_configs:
            return "webhook"
        transports = tuple(
            dict.fromkeys(_normalize_transport(config.surface) for config in self.account_configs)
        )
        if len(transports) == 1:
            return transports[0]
        raise LookupError(
            "configured Telegram accounts use multiple transport surfaces; mount distinct paths or choose one explicitly"
        )

    def handle_http_event(
        self,
        payload: Mapping[str, object],
        *,
        path: str,
    ) -> tuple[str, Mapping[str, object]]:
        try:
            result = self.dispatch_update(payload, path=path)
        except LookupError as exc:
            return "503 Service Unavailable", {"ok": False, "error": str(exc)}
        except ValueError as exc:
            return "400 Bad Request", {"ok": False, "error": str(exc)}
        except RuntimeError as exc:
            return "502 Bad Gateway", {"ok": False, "error": str(exc)}
        payload_body = dict(result.response_body)
        if result.delivery_request is not None:
            payload_body["delivery_request_path"] = result.delivery_request.get("path_label", "")
        return "200 OK", payload_body

    def dispatch_update(
        self,
        payload: Mapping[str, object],
        *,
        account_id: str | None = None,
        path: str | None = None,
    ) -> TelegramGatewayEventResult:
        if self.adapter is None:
            raise RuntimeError("telegram adapter is unavailable")
        account = self._match_account(account_id=account_id, path=path)
        exchange = self.adapter.receive_update(payload, account_id=account.account_id)
        response_body: dict[str, object] = {
            "ok": True,
            "adapter_id": self.adapter.adapter_id,
            "transport": "webhook",
            "account_id": exchange.route.inbound.account_id,
            "conversation_id": exchange.route.inbound.conversation_id,
            "session_id": exchange.route.session.session_id,
            "policy_decision": str(exchange.delivery.policy_result.decision),
            "delivery_outcome": exchange.delivery.outcome,
        }
        identity = getattr(exchange.route, "identity", None)
        if identity is not None and identity.state_id is not None:
            response_body["state_id"] = identity.state_id
        if identity is not None and identity.elephant_id is not None:
            response_body["elephant_id"] = identity.elephant_id
        if exchange.delivery.outbound is None:
            response_body["summary"] = exchange.delivery.summary
            return TelegramGatewayEventResult(
                exchange=exchange,
                response_body=response_body,
            )
        delivery_request = self._build_send_request(account, exchange.delivery.outbound)
        delivery_response = self._send_outbound(account, delivery_request)
        response_body["external_message_id"] = self._external_message_id(delivery_response)
        return TelegramGatewayEventResult(
            exchange=exchange,
            response_body=response_body,
            delivery_request=delivery_request,
            delivery_response=delivery_response,
        )

    def _match_account(
        self,
        *,
        account_id: str | None = None,
        path: str | None = None,
    ) -> TelegramResolvedAccount:
        if not self.account_configs:
            raise LookupError("no Telegram gateway accounts are configured")
        if account_id is not None:
            for config in self.account_configs:
                if config.account_id == account_id:
                    return resolve_telegram_account(config, environ=self.environ)
            raise LookupError(f"unknown Telegram gateway account: {account_id}")
        if path is not None:
            matches = [config for config in self.account_configs if config.event_path == path]
            if len(matches) == 1:
                return resolve_telegram_account(matches[0], environ=self.environ)
        if len(self.account_configs) == 1:
            return resolve_telegram_account(self.account_configs[0], environ=self.environ)
        raise LookupError(
            "could not match Telegram event to a configured gateway account; configure distinct event_path values or pass account_id explicitly"
        )

    def _build_send_request(
        self,
        account: TelegramResolvedAccount,
        outbound: GatewayOutboundMessage,
    ) -> Mapping[str, object]:
        conversation = outbound.conversation
        chat_id = conversation.parent_conversation_id or conversation.conversation_id.split(":", 1)[0]
        body: dict[str, object] = {
            "chat_id": chat_id,
            "text": outbound.body,
        }
        if conversation.thread_id is not None:
            body["message_thread_id"] = conversation.thread_id
        if outbound.reply_to_message_id is not None:
            body["reply_to_message_id"] = outbound.reply_to_message_id
        return {
            "method": "POST",
            "path": f"/bot{account.bot_token}/sendMessage",
            "path_label": "/sendMessage",
            "body": body,
        }

    def _send_outbound(
        self,
        account: TelegramResolvedAccount,
        delivery_request: Mapping[str, object],
    ) -> Mapping[str, object]:
        path = str(delivery_request.get("path") or "")
        method = str(delivery_request.get("method") or "POST")
        body = _mapping(delivery_request.get("body"))
        if not path or body is None:
            raise RuntimeError("telegram delivery request is missing a path or body payload")
        return self.http_requester(
            method,
            f"{account.config.base_url}{path}",
            body,
            {},
        )

    def _external_message_id(self, response: Mapping[str, object]) -> str:
        result = _mapping(response.get("result")) or {}
        return str(result.get("message_id") or "")

    # ── DaemonService ──────────────────────────────────────────

    async def start_daemon_task(self, *, loop: Any) -> None:
        """Telegram is webhook-only; no long-running task needed."""
        return None

    async def stop_daemon_task(self) -> None:
        """No-op for webhook-only service."""


def register_telegram_gateway_service(registry: GatewayPluginRegistry) -> GatewayPluginRegistry:
    registry.register_service(
        "telegram",
        factory=lambda app, **kwargs: TelegramGatewayService(app=app, **kwargs),
    )
    return registry


def build_telegram_gateway_service(
    *,
    profile_id: str = "you",
    provider_profile: Mapping[str, Any] | None = None,
    state_dir: str | None = None,
    environ: Mapping[str, str] | None = None,
    http_requester: HttpJsonRequester = _default_json_request,
    plugin_registry: GatewayPluginRegistry | None = None,
) -> TelegramGatewayService:
    app, _, _ = build_gateway_app(
        profile_id=profile_id,
        provider_profile=provider_profile,
        state_dir=state_dir,
        plugin_registry=plugin_registry,
    )
    return TelegramGatewayService(
        app=app,
        http_requester=http_requester,
        environ=dict(environ or os.environ),
    )


__all__ = [
    "DEFAULT_TELEGRAM_BASE_URL",
    "DEFAULT_TELEGRAM_BOT_TOKEN_ENV",
    "DEFAULT_TELEGRAM_EVENT_PATH",
    "LEGACY_TELEGRAM_BOT_TOKEN_ENV",
    "SUPPORTED_TELEGRAM_TRANSPORTS",
    "TelegramGatewayAccountConfig",
    "TelegramGatewayEventResult",
    "TelegramGatewayService",
    "TelegramResolvedAccount",
    "build_telegram_gateway_service",
    "load_telegram_gateway_accounts",
    "register_telegram_gateway_service",
    "resolve_telegram_account",
]
