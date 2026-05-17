"""WeCom (Enterprise WeChat) gateway service using WebSocket Bot API."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from packages.gateway_core import (
    DEFAULT_GATEWAY_ACCOUNT_ID,
    GatewayExchange,
    GatewayInboundMessage,
    GatewayOutboundMessage,
)

from apps.runtime_layout import default_cli_state_dir, default_gateway_state_dir

from .cli_control import (
    CliRuntimeFactory,
    GatewayCliBindingStore,
    GatewayCliControlService,
    load_gateway_cli_control_config,
)
from .plugins import GatewayManagedRuntime, GatewayPluginRegistry, default_gateway_runtime_path
from .runtime import WECOM_ADAPTER_ID, WecomMessagingAdapter, GatewayApp, build_gateway_app

from .wecom_support import (
    DEFAULT_WECOM_BOT_ID_ENV,
    DEFAULT_WECOM_SECRET_ENV,
    DEFAULT_WECOM_WS_URL,
    MESSAGE_DEDUP_TTL_SECONDS,
    WECOM_AVAILABLE,
    WecomGatewayAccountConfig,
    WecomGatewayEventResult,
    WecomResolvedAccount,
    _coerce_bool,
    _extract_wecom_text,
    _normalize_transport,
    check_wecom_requirements,
    load_wecom_gateway_accounts,
    resolve_wecom_account,
)

LOGGER = logging.getLogger(__name__)

# WebSocket constants
WS_PING_INTERVAL = 30  # seconds
WS_READ_TIMEOUT = 60  # seconds
HANDSHAKE_TIMEOUT = 15  # seconds
REQUEST_TIMEOUT = 15  # seconds
MAX_CONSECUTIVE_FAILURES = 3
RETRY_DELAY_SECONDS = 2
BACKOFF_DELAY_SECONDS = 30
MAX_BACKOFF_SECONDS = 300
MAX_MESSAGE_LENGTH = 4000

# WeCom Bot API commands
CMD_SUBSCRIBE = "aibot_subscribe"
CMD_MSG_CALLBACK = "aibot_msg_callback"
CMD_SEND_MSG = "aibot_send_msg"
CMD_RESPOND_MSG = "aibot_respond_msg"


class MessageDeduplicator:
    """Simple sliding-window message deduplication."""

    def __init__(self, ttl_seconds: float = MESSAGE_DEDUP_TTL_SECONDS):
        self._ttl_seconds = ttl_seconds
        self._seen: dict[str, float] = {}

    def is_duplicate(self, message_id: str) -> bool:
        now = __import__("time").time()
        # Prune expired entries
        expired = [k for k, v in self._seen.items() if now - v >= self._ttl_seconds]
        for k in expired:
            del self._seen[k]
        if message_id in self._seen:
            return True
        self._seen[message_id] = now
        return False


@dataclass(slots=True)
class WecomGatewayService:
    app: GatewayApp
    account_configs: tuple[WecomGatewayAccountConfig, ...] = ()
    environ: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    adapter: WecomMessagingAdapter | None = None
    cli_runtime_factory: CliRuntimeFactory | None = None
    cli_binding_store: GatewayCliBindingStore | None = None
    cli_control: GatewayCliControlService | None = None
    default_cli_state_dir: str | None = None
    runtime_dependency_ensurer: Callable[..., object] | None = None
    respect_enabled: bool = True
    service_key: str = "wecom"
    runtime_state_dir: Path | None = None

    # Async runtime state
    _running: bool = field(default=False, init=False)
    _session: Any = field(default=None, init=False)  # aiohttp.ClientSession
    _http_client: Any = field(default=None, init=False)  # httpx.AsyncClient
    _ws: Any = field(default=None, init=False)  # aiohttp.ClientWebSocketResponse
    _listen_task: asyncio.Task | None = field(default=None, init=False)
    _heartbeat_task: asyncio.Task | None = field(default=None, init=False)
    _pending_responses: dict[str, asyncio.Future] = field(default_factory=dict, init=False)
    _dedup: MessageDeduplicator | None = field(default=None, init=False)
    _reply_req_ids: dict[str, str] = field(default_factory=dict, init=False)
    _last_chat_req_ids: dict[str, str] = field(default_factory=dict, init=False)
    _device_id: str = field(default="", init=False)
    _resolved_bot_id: str = field(default="", init=False)
    _resolved_secret: str = field(default="", init=False)
    _resolved_ws_url: str = field(default="", init=False)
    _resolved_dm_policy: str = field(default="open", init=False)
    _resolved_group_policy: str = field(default="disabled", init=False)
    _resolved_allow_from: tuple[str, ...] = field(default=(), init=False)
    _resolved_group_allow_from: tuple[str, ...] = field(default=(), init=False)
    _daemon_task: asyncio.Task | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if not self.account_configs:
            self.account_configs = load_wecom_gateway_accounts(
                self.app,
                respect_enabled=self.respect_enabled,
            )
        if self.adapter is None:
            self.adapter = WecomMessagingAdapter(app=self.app)
        if self.cli_control is None and self.app.loaded_profile is not None:
            config = load_gateway_cli_control_config(
                self.app.loaded_profile.manifest,
                adapter_key="wecom",
                default_when_missing=True,
            )
            if config is not None:
                binding_store = self.cli_binding_store
                if binding_store is None:
                    state_root = self.app.state_dir
                    binding_path = (
                        None
                        if state_root is None
                        else os.path.join(state_root, "wecom-cli-bindings.json")
                    )
                    binding_store = GatewayCliBindingStore(
                        path=None if binding_path is None else Path(binding_path)
                    )
                self.cli_control = GatewayCliControlService(
                    config=self._resolved_cli_control_config(config),
                    app=self.app,
                    runtime_factory=self.cli_runtime_factory,
                    binding_store=binding_store,
                    surface_label="WeCom",
                    binding_subject="conversation",
                    control_config_path="gateway.adapters.wecom.control",
                )

    def _resolved_cli_control_config(self, config) -> object:
        state_dir = config.state_dir or self.default_cli_state_dir or self._inferred_cli_state_dir()
        if state_dir is None:
            state_dir = str(default_cli_state_dir(environ=self.environ))
        return type(config)(
            state_dir=state_dir,
            allow_group_chats=config.allow_group_chats,
        )

    def _inferred_cli_state_dir(self) -> str | None:
        if self.app.state_dir is None:
            return None
        return str(Path(self.app.state_dir))

    def _enabled_account_configs(self) -> tuple[WecomGatewayAccountConfig, ...]:
        return tuple(config for config in self.account_configs if config.enabled)

    def _transport_account_configs(self) -> tuple[WecomGatewayAccountConfig, ...]:
        enabled_configs = self._enabled_account_configs()
        return enabled_configs if enabled_configs else self.account_configs

    def _state_dir(self) -> str:
        if self.runtime_state_dir is not None:
            return str(self.runtime_state_dir)
        if self.app.state_dir is not None:
            return str(self.app.state_dir)
        return str(default_gateway_state_dir())

    def has_credentials(self) -> bool:
        """Return True if at least one account can be resolved with current environment."""
        for config in self.account_configs:
            try:
                resolve_wecom_account(config, environ=self.environ)
                return True
            except (LookupError, RuntimeError):
                continue
        return False

    def describe(self) -> Mapping[str, object]:
        configured_transport: str | None = None
        configured_transport_error: str | None = None
        try:
            configured_transport = self.configured_transport()
        except (LookupError, ValueError) as exc:
            configured_transport_error = str(exc)
        return {
            "adapter_id": self.adapter.adapter_id if self.adapter is not None else WECOM_ADAPTER_ID,
            "profile_id": self.app.profile_id,
            "preferred_transport": "websocket",
            "implemented_transports": ("wecom-websocket",),
            "configured_transport": configured_transport,
            "configured_transport_error": configured_transport_error,
            "sdk_dependency_status": "ready" if check_wecom_requirements() else "missing_dependencies",
            "accounts": tuple(
                {
                    "account_id": config.account_id,
                    "surface": config.surface,
                    "enabled": config.enabled,
                    "ws_url": config.ws_url,
                }
                for config in self.account_configs
            ),
            "control": self._describe_control(),
        }

    def _describe_control(self) -> Mapping[str, object]:
        if self.cli_control is None:
            return {
                "enabled": False,
                "runtime": "cli-runtime",
                "runtime_status": "disabled",
                "known_elephants": (),
            }
        return self.cli_control.describe()

    def configured_transport(self) -> str:
        return "websocket"

    def configured_runtime_target(self) -> str:
        return self.configured_transport()

    def managed_runtime(
        self,
        *,
        args: Any,
        target: str,
    ) -> GatewayManagedRuntime:
        normalized_target = _normalize_transport(target)
        state_dir = Path(args.state_dir)
        return GatewayManagedRuntime(
            service_key=self.service_key,
            runtime_id=f"{self.service_key}:{normalized_target}",
            target=normalized_target,
            label=f"WeCom {normalized_target} transport",
            pid_path=default_gateway_runtime_path(
                state_dir,
                service_key=self.service_key,
                target=normalized_target,
                suffix="pid",
            ),
            log_path=default_gateway_runtime_path(
                state_dir,
                service_key=self.service_key,
                target=normalized_target,
                suffix="log",
            ),
            record_path=default_gateway_runtime_path(
                state_dir,
                service_key=self.service_key,
                target=normalized_target,
                suffix="runtime.json",
            ),
        )

    def build_detached_runtime_command(
        self,
        *,
        args: Any,
        target: str,
    ) -> tuple[str, ...]:
        command = [
            os.sys.executable,
            "-m",
            "apps.launcher",
            "gateway",
            "wecom",
            "start",
        ]
        if getattr(args, "account_id", None):
            command.append(str(args.account_id))
        command.extend(
            [
                "--transport",
                _normalize_transport(target),
                "--state-dir",
                str(args.state_dir),
                "--cli-state-dir",
                str(args.cli_state_dir),
            ]
        )
        return tuple(command)

    def prepare_managed_runtime(self, *, action: str, target: str) -> None:
        _normalize_transport(target)
        if self.runtime_dependency_ensurer is None:
            return
        self.runtime_dependency_ensurer(reason=f"WeCom gateway {action}")

    def managed_runtime_log_hint(self, *, target: str) -> str:
        return "elephant gateway wecom logs <account-id> --follow"

    # -----------------------------------------------------------------------
    # Account resolution
    # -----------------------------------------------------------------------

    def _match_account(self, *, account_id: str | None = None) -> WecomResolvedAccount:
        if not self.account_configs:
            raise LookupError("no WeCom gateway accounts are configured")
        if account_id is not None:
            for config in self.account_configs:
                if config.account_id == account_id:
                    return resolve_wecom_account(config, environ=self.environ)
            raise LookupError(f"unknown WeCom gateway account: {account_id}")
        enabled_configs = self._enabled_account_configs()
        if not enabled_configs:
            raise LookupError("no enabled WeCom gateway accounts are configured")
        if len(enabled_configs) == 1:
            return resolve_wecom_account(enabled_configs[0], environ=self.environ)
        raise LookupError(
            "multiple enabled WeCom gateway accounts are configured; pass account_id explicitly"
        )

    # -----------------------------------------------------------------------
    # Async WebSocket lifecycle
    # -----------------------------------------------------------------------

    async def start_gateway(self, *, account_id: str | None = None) -> None:
        """Connect WebSocket and run the listen loop."""
        if not check_wecom_requirements():
            raise RuntimeError(
                "WeCom startup failed: aiohttp is required. "
                "Install it with: pip install aiohttp"
            )

        account = self._match_account(account_id=account_id)
        config = account.config

        self._resolved_bot_id = account.bot_id
        self._resolved_secret = account.secret
        self._resolved_ws_url = config.ws_url.rstrip("/")
        self._resolved_dm_policy = config.dm_policy
        self._resolved_group_policy = config.group_policy
        self._resolved_allow_from = config.allow_from
        self._resolved_group_allow_from = config.group_allow_from
        self._device_id = uuid4().hex
        self._dedup = MessageDeduplicator()
        self._pending_responses = {}
        self._reply_req_ids = {}
        self._last_chat_req_ids = {}

        import aiohttp

        self._session = aiohttp.ClientSession(trust_env=True)
        self._running = True

        LOGGER.info(
            "[%s] Starting account=%s ws_url=%s",
            self.service_key,
            _safe_id(account.account_id),
            self._resolved_ws_url,
        )

        try:
            await self._listen_loop()
        finally:
            await self.stop_gateway()

    async def stop_gateway(self) -> None:
        """Disconnect WebSocket and cleanup."""
        self._running = False

        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        self._heartbeat_task = None

        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None

        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        self._listen_task = None

        # Cancel any pending response futures
        for future in self._pending_responses.values():
            if not future.done():
                future.cancel()
        self._pending_responses.clear()

        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
        self._http_client = None

        LOGGER.info("[%s] Disconnected", self.service_key)

    async def _open_connection(self) -> None:
        """Authenticate via aibot_subscribe command."""
        import aiohttp

        assert self._session is not None

        LOGGER.info(
            "[%s] Connecting to %s ...",
            self.service_key,
            self._resolved_ws_url,
        )

        try:
            self._ws = await self._session.ws_connect(
                self._resolved_ws_url,
                heartbeat=WS_PING_INTERVAL,
                receive_timeout=WS_READ_TIMEOUT,
            )
        except Exception as exc:
            raise RuntimeError(
                f"WeCom WebSocket connection failed: {exc}"
            ) from exc

        # Send subscribe command
        req_id = self._new_req_id("subscribe")
        subscribe_payload = {
            "cmd": CMD_SUBSCRIBE,
            "headers": {"req_id": req_id},
            "body": {
                "bot_id": self._resolved_bot_id,
                "secret": self._resolved_secret,
                "device_id": self._device_id,
            },
        }

        await self._send_json(subscribe_payload)
        LOGGER.debug("[%s] Sent subscribe req_id=%s", self.service_key, req_id[:12])

        # Wait for handshake ack
        await self._wait_for_handshake(req_id)
        LOGGER.info("[%s] WebSocket authenticated successfully", self.service_key)

        # Start heartbeat task
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _wait_for_handshake(self, req_id: str) -> None:
        """Wait for subscribe ack by reading directly from the WebSocket.

        Unlike normal request/response which goes through _dispatch_payload
        (driven by _read_events), the handshake happens before _read_events
        starts, so we must read the socket ourselves here.
        """
        import aiohttp

        assert self._ws is not None

        deadline = asyncio.get_running_loop().time() + HANDSHAKE_TIMEOUT
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise RuntimeError(
                    "WeCom WebSocket handshake timed out; check bot_id and secret"
                )

            try:
                msg = await asyncio.wait_for(self._ws.receive(), timeout=remaining)
            except asyncio.TimeoutError:
                raise RuntimeError(
                    "WeCom WebSocket handshake timed out; check bot_id and secret"
                )

            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    payload = json.loads(msg.data)
                except (json.JSONDecodeError, TypeError):
                    continue

                # Skip server pings during handshake
                if payload.get("cmd") == "ping":
                    continue

                # Check if this is our subscribe response
                if self._payload_req_id(payload) == req_id:
                    errcode = payload.get("errcode", 0)
                    if errcode not in (0, None):
                        errmsg = payload.get("errmsg") or "authentication failed"
                        raise RuntimeError(
                            f"WeCom subscribe failed: {errmsg} (errcode={errcode})"
                        )
                    return

                LOGGER.debug(
                    "[%s] Ignoring pre-auth payload: cmd=%s",
                    self.service_key,
                    payload.get("cmd"),
                )

            elif msg.type in (
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.ERROR,
            ):
                raise RuntimeError(
                    "WeCom WebSocket closed during authentication"
                )

    async def _listen_loop(self) -> None:
        """Read events with automatic reconnection and exponential backoff."""
        consecutive_failures = 0
        backoff = RETRY_DELAY_SECONDS

        while self._running:
            try:
                await self._open_connection()
                consecutive_failures = 0
                backoff = RETRY_DELAY_SECONDS

                await self._read_events()

            except asyncio.CancelledError:
                break
            except Exception as exc:
                consecutive_failures += 1
                LOGGER.error(
                    "[%s] WebSocket error (%d/%d): %s",
                    self.service_key,
                    consecutive_failures,
                    MAX_CONSECUTIVE_FAILURES,
                    exc,
                )

                if not self._running:
                    break

                # Cleanup broken connection
                if self._ws and not self._ws.closed:
                    try:
                        await self._ws.close()
                    except Exception:
                        pass
                self._ws = None

                if self._heartbeat_task and not self._heartbeat_task.done():
                    self._heartbeat_task.cancel()
                    try:
                        await self._heartbeat_task
                    except asyncio.CancelledError:
                        pass
                self._heartbeat_task = None

                # Exponential backoff
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                    LOGGER.warning(
                        "[%s] Backing off for %ds after %d consecutive failures",
                        self.service_key,
                        backoff,
                        consecutive_failures,
                    )
                    consecutive_failures = 0

                await asyncio.sleep(backoff)

    async def _read_events(self) -> None:
        """Read WebSocket frames and dispatch payloads."""
        assert self._ws is not None

        async for msg in self._ws:
            if not self._running:
                break

            if msg.type == 1:  # aiohttp.WSMsgType.TEXT
                try:
                    payload = json.loads(msg.data)
                    asyncio.create_task(self._dispatch_payload_safe(payload))
                except json.JSONDecodeError:
                    LOGGER.warning("[%s] Invalid JSON frame received", self.service_key)
            elif msg.type == 8:  # aiohttp.WSMsgType.ERROR
                LOGGER.error(
                    "[%s] WebSocket error: %s",
                    self.service_key,
                    self._ws.exception(),
                )
                break
            elif msg.type in (0x100, 0x101):  # aiohttp.WSMsgType.CLOSE / CLOSING
                LOGGER.info("[%s] WebSocket closed by server", self.service_key)
                break

    async def _dispatch_payload_safe(self, payload: dict[str, Any]) -> None:
        try:
            await self._dispatch_payload(payload)
        except Exception as exc:
            LOGGER.error(
                "[%s] unhandled dispatch error: %s",
                self.service_key,
                exc,
                exc_info=True,
            )

    async def _dispatch_payload(self, payload: dict[str, Any]) -> None:
        """Route inbound payloads by cmd."""
        cmd = str(payload.get("cmd") or "").strip()
        request_id = self._payload_req_id(payload)

        # Handle pending response futures (but not for callback commands)
        if request_id and request_id in self._pending_responses and cmd not in (CMD_MSG_CALLBACK,):
            future = self._pending_responses.pop(request_id)
            if not future.done():
                future.set_result(payload)
            return

        if cmd == CMD_MSG_CALLBACK:
            await self._on_message(payload)
        elif cmd == "ping":
            LOGGER.debug("[%s] Server ping received", self.service_key)
        else:
            LOGGER.debug(
                "[%s] Unhandled cmd=%s req_id=%s",
                self.service_key,
                cmd,
                request_id[:12] if request_id else "(none)",
            )

    async def _heartbeat_loop(self) -> None:
        """Send periodic pings to keep the connection alive."""
        try:
            while self._running and self._ws and not self._ws.closed:
                await asyncio.sleep(WS_PING_INTERVAL)
                if not self._running or not self._ws or self._ws.closed:
                    break
                try:
                    await self._send_json(
                        {"cmd": "ping", "headers": {"req_id": self._new_req_id("ping")}, "body": {}}
                    )
                except Exception as exc:
                    LOGGER.debug("[%s] Heartbeat send failed: %s", self.service_key, exc)
                    break
        except asyncio.CancelledError:
            pass

    # -----------------------------------------------------------------------
    # Message processing
    # -----------------------------------------------------------------------

    async def _on_message(self, payload: dict[str, Any]) -> None:
        """Process inbound WeCom callback message."""
        body = payload.get("body")
        if not isinstance(body, dict):
            LOGGER.warning("[%s] aibot_msg_callback missing body", self.service_key)
            return

        # Extract message ID and deduplicate
        msg_id = str(body.get("msgid") or body.get("msg_id") or self._payload_req_id(payload) or "").strip()
        if msg_id and self._dedup and self._dedup.is_duplicate(msg_id):
            return

        # Extract sender info
        from_info = body.get("from") or {}
        if isinstance(from_info, dict):
            sender_id = str(from_info.get("userid") or "").strip()
        else:
            sender_id = ""

        if not sender_id:
            LOGGER.warning("[%s] aibot_msg_callback missing sender userid", self.service_key)
            return

        # Skip self-sent messages
        if sender_id == self._resolved_bot_id:
            return

        # Determine chat ID
        chat_id = str(body.get("chatid") or "").strip() or sender_id
        chat_type_raw = str(body.get("chattype") or "").strip().lower()

        # Determine chat type
        if chat_type_raw in ("group", "chatroom"):
            chat_type = "group"
        else:
            chat_type = "direct"

        # Apply DM/group policy
        if chat_type == "group":
            if self._resolved_group_policy == "disabled":
                return
            if self._resolved_group_policy == "allowlist" and chat_id not in self._resolved_group_allow_from:
                return
        elif not self._is_dm_allowed(sender_id):
            return

        # Cache reply_req_id and chat_req_id for response routing
        reply_req_id = self._payload_req_id(payload)
        if reply_req_id:
            self._reply_req_ids[msg_id] = reply_req_id
        chat_req_id = str(body.get("chat_req_id") or "").strip()
        if chat_req_id:
            self._last_chat_req_ids[chat_id] = chat_req_id

        # Extract text content
        text = _extract_wecom_text(body)
        if not text:
            return

        # Build inbound message through the adapter
        adapter = self.adapter
        if adapter is None:
            return

        inbound = adapter.normalize_event(
            {
                "message_id": msg_id,
                "msg_id": msg_id,
                "sender_id": sender_id,
                "from_userid": sender_id,
                "chat_id": chat_id,
                "chatid": chat_id,
                "chat_type": chat_type,
                "content": text,
                "transport": "websocket",
            },
            account_id=self._match_account().account_id if self.account_configs else DEFAULT_GATEWAY_ACCOUNT_ID,
            transport="websocket",
        )

        if self.cli_control is not None:
            result = self.cli_control.handle_message(inbound)
            if result.handled and result.body is not None:
                outbound = self._build_control_outbound(inbound, body=result.body, session_id=result.session_id)
                await self._send_wecom_reply(outbound)
            if result.handled:
                return

        exchange = self.app.handle_message(
            inbound,
            reply_to_message_id=inbound.reply_to_message_id or inbound.event_id,
            attachment_refs=inbound.attachment_refs,
            metadata={
                **dict(inbound.metadata),
                "delivery_surface": inbound.account.surface or "wecom-websocket",
            },
        )

        if exchange.delivery.outbound is not None:
            await self._send_wecom_reply(exchange.delivery.outbound)

    def _is_dm_allowed(self, sender_id: str) -> bool:
        if self._resolved_dm_policy == "disabled":
            return False
        if self._resolved_dm_policy == "allowlist":
            return sender_id in self._resolved_allow_from
        return True

    async def _send_wecom_reply(self, outbound: GatewayOutboundMessage) -> None:
        """Send a markdown reply via WeCom Bot API."""
        if not self._ws or self._ws.closed:
            LOGGER.warning("[%s] Cannot send reply: WebSocket not connected", self.service_key)
            return

        content = outbound.body or ""
        conversation_id = outbound.conversation_id

        # Try respond_msg first (if we have a reply_req_id for this conversation)
        reply_req_id = self._reply_req_ids.pop(outbound.reply_to_message_id or "", "")
        chat_req_id = self._last_chat_req_ids.get(conversation_id, "")

        if reply_req_id:
            body = {
                "reply_req_id": reply_req_id,
                "chat_req_id": chat_req_id,
                "msgtype": "markdown",
                "markdown": {
                    "content": content,
                },
            }
            try:
                await self._send_reply_request(reply_req_id, body, cmd=CMD_RESPOND_MSG)
                LOGGER.debug(
                    "[%s] Sent respond_msg to=%s",
                    self.service_key,
                    _safe_id(conversation_id),
                )
            except Exception as exc:
                LOGGER.error(
                    "[%s] respond_msg failed to=%s: %s",
                    self.service_key,
                    _safe_id(conversation_id),
                    exc,
                )
        else:
            # Fall back to send_msg (only works in DM, not groups)
            body = {
                "chatid": conversation_id if chat_req_id else "",
                "userid": conversation_id if not chat_req_id else "",
                "msgtype": "markdown",
                "markdown": {
                    "content": content,
                },
            }
            try:
                response = await self._send_request(CMD_SEND_MSG, body)
                ret = response.get("ret")
                if ret is not None and ret != 0:
                    errmsg = response.get("errmsg") or "unknown error"
                    LOGGER.error(
                        "[%s] send_msg error ret=%s errmsg=%s",
                        self.service_key,
                        ret,
                        errmsg,
                    )
                else:
                    LOGGER.debug(
                        "[%s] Sent send_msg to=%s",
                        self.service_key,
                        _safe_id(conversation_id),
                    )
            except Exception as exc:
                LOGGER.error(
                    "[%s] send_msg failed to=%s: %s",
                    self.service_key,
                    _safe_id(conversation_id),
                    exc,
                )

    async def _send_json(self, payload: dict[str, Any]) -> None:
        """Send raw JSON frame over WebSocket."""
        if not self._ws or self._ws.closed:
            raise RuntimeError("WebSocket is not connected")
        await self._ws.send_json(payload)

    async def _send_request(
        self,
        cmd: str,
        body: dict[str, Any],
        timeout: float = REQUEST_TIMEOUT,
    ) -> dict[str, Any]:
        """Send a command and await the response."""
        req_id = self._new_req_id(cmd)
        payload = {
            "cmd": cmd,
            "headers": {"req_id": req_id},
            "body": body,
        }

        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending_responses[req_id] = future

        try:
            await self._send_json(payload)
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            raise RuntimeError(f"WeCom request timed out: cmd={cmd}")
        finally:
            self._pending_responses.pop(req_id, None)

    async def _send_reply_request(
        self,
        reply_req_id: str,
        body: dict[str, Any],
        cmd: str = CMD_RESPOND_MSG,
        timeout: float = REQUEST_TIMEOUT,
    ) -> dict[str, Any]:
        """Send a reply frame with reply_req_id."""
        # Normalize the reply_req_id: the server echoes back the req_id from
        # headers, so we use it directly as our correlation key.
        req_id = reply_req_id
        payload = {
            "cmd": cmd,
            "headers": {"req_id": req_id},
            "body": body,
        }

        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending_responses[req_id] = future

        try:
            await self._send_json(payload)
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            raise RuntimeError(f"WeCom reply request timed out: cmd={cmd}")
        finally:
            self._pending_responses.pop(req_id, None)

    @staticmethod
    def _new_req_id(prefix: str) -> str:
        """Generate a prefixed request ID for WeCom protocol correlation."""
        return f"{prefix}-{uuid4().hex}"

    @staticmethod
    def _payload_req_id(payload: dict[str, Any]) -> str:
        """Extract req_id from WeCom protocol payload (lives in headers)."""
        headers = payload.get("headers")
        if isinstance(headers, dict):
            return str(headers.get("req_id") or "").strip()
        return ""

    def _build_control_outbound(
        self,
        inbound: GatewayInboundMessage,
        *,
        body: str,
        session_id: str | None,
    ) -> GatewayOutboundMessage:
        return GatewayOutboundMessage(
            message_id=f"wecom-control:{session_id or inbound.conversation_id}:{uuid4().hex[:12]}",
            account=inbound.account,
            conversation=inbound.conversation,
            session_id=session_id or f"control:{inbound.conversation_id}",
            body=body,
            reply_to_message_id=inbound.reply_to_message_id or inbound.event_id,
            attachment_refs=(),
            metadata={
                **dict(inbound.metadata),
                "delivery_surface": inbound.account.surface or "wecom-control",
                "runtime_surface": "cli-runtime",
            },
        )

    # ── DaemonService ──────────────────────────────────────────

    async def start_daemon_task(self, *, loop: Any) -> asyncio.Task | None:
        """Start WeCom WebSocket gateway as a daemon task in the unified event loop."""
        task = asyncio.create_task(self.start_gateway(), name="wecom-daemon")
        self._daemon_task = task
        return task

    async def stop_daemon_task(self) -> None:
        """Gracefully stop the WeCom daemon task."""
        if self._daemon_task is not None and not self._daemon_task.done():
            self._daemon_task.cancel()
            try:
                await self._daemon_task
            except asyncio.CancelledError:
                pass
        self._daemon_task = None
        await self.stop_gateway()


def _safe_id(value: str) -> str:
    """Obfuscate an ID for safe logging."""
    if not value:
        return "(empty)"
    if len(value) <= 8:
        return value[:2] + "***"
    return value[:4] + "***" + value[-4:]


def register_wecom_gateway_service(registry: GatewayPluginRegistry) -> GatewayPluginRegistry:
    from .wecom import WecomGatewayService

    registry.register_service(
        "wecom",
        factory=lambda app, **kwargs: WecomGatewayService(app=app, **kwargs),
        enabled_by_default=True,
    )
    return registry


def build_wecom_gateway_service(
    *,
    profile_id: str = "you",
    provider_profile: Mapping[str, Any] | None = None,
    state_dir: str | None = None,
    environ: Mapping[str, str] | None = None,
    plugin_registry: GatewayPluginRegistry | None = None,
) -> WecomGatewayService:
    app, _, _ = build_gateway_app(
        profile_id=profile_id,
        provider_profile=provider_profile,
        state_dir=state_dir,
        plugin_registry=plugin_registry,
    )
    return WecomGatewayService(
        app=app,
        environ=dict(environ or os.environ),
        runtime_state_dir=Path(state_dir) if state_dir is not None else None,
    )
