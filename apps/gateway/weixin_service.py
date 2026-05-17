"""WeChat (Weixin) gateway service using iLink Bot API long-polling."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path
import threading
from typing import Any
from uuid import uuid4

from packages.gateway_core import (
    DEFAULT_GATEWAY_ACCOUNT_ID,
    GatewayAccountRef,
    GatewayConversationRef,
    GatewayExchange,
    GatewayInboundMessage,
    GatewayOutboundMessage,
    GatewayOutboundQueue,
    GatewayOutboundRow,
    InboundSequencer,
    default_outbound_queue_path,
    resolve_cron_identity_records,
    run_outbound_drain_loop,
)

from apps.runtime_layout import default_cli_state_dir, default_gateway_state_dir

from .cli_control import (
    CliRuntimeFactory,
    GatewayCliBindingStore,
    GatewayCliControlService,
    load_gateway_cli_control_config,
)
from .plugins import GatewayManagedRuntime, GatewayPluginRegistry, default_gateway_runtime_path
from .runtime import (
    WEIXIN_ADAPTER_ID,
    WeixinMessagingAdapter,
    GatewayApp,
    build_gateway_app,
)

from .weixin_support import (
    ILINK_BASE_URL,
    WEIXIN_CDN_BASE_URL,
    AIOHTTP_AVAILABLE,
    ContextTokenStore,
    TypingTicketCache,
    WeixinGatewayAccountConfig,
    WeixinGatewayEventResult,
    WeixinResolvedAccount,
    _coerce_bool,
    _extract_text,
    _guess_chat_type,
    _load_sync_buf,
    _save_sync_buf,
    _normalize_markdown_blocks,
    _normalize_transport,
    _safe_id,
    _split_text_for_weixin_delivery,
    check_weixin_requirements,
    load_weixin_account,
    load_weixin_gateway_accounts,
    resolve_weixin_account,
    save_weixin_account,
    # iLink API helpers
    _api_post,
    _get_updates,
    _send_message as _ilink_send_message,
    _send_typing,
    _get_config,
    EP_SEND_MESSAGE,
    LONG_POLL_TIMEOUT_MS,
    API_TIMEOUT_MS,
    SESSION_EXPIRED_ERRCODE,
    MAX_CONSECUTIVE_FAILURES,
    RETRY_DELAY_SECONDS,
    BACKOFF_DELAY_SECONDS,
    MESSAGE_DEDUP_TTL_SECONDS,
    ITEM_TEXT,
    MSG_TYPE_BOT,
    MSG_STATE_FINISH,
    TYPING_START,
    TYPING_STOP,
    _make_ssl_connector,
    _headers,
    _json_dumps,
    _base_info,
    _random_wechat_uin,
)

LOGGER = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 4000


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
class WeixinGatewayService:
    app: GatewayApp
    account_configs: tuple[WeixinGatewayAccountConfig, ...] = ()
    environ: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    adapter: WeixinMessagingAdapter | None = None
    cli_runtime_factory: CliRuntimeFactory | None = None
    cli_binding_store: GatewayCliBindingStore | None = None
    cli_control: GatewayCliControlService | None = None
    default_cli_state_dir: str | None = None
    runtime_dependency_ensurer: Callable[..., object] | None = None
    respect_enabled: bool = True
    service_key: str = "weixin"
    runtime_state_dir: Path | None = None

    # Async runtime state
    _running: bool = field(default=False, init=False)
    _poll_session: Any = field(default=None, init=False)  # aiohttp.ClientSession
    _send_session: Any = field(default=None, init=False)  # aiohttp.ClientSession
    _poll_task: asyncio.Task | None = field(default=None, init=False)
    _outbound_drain_task: asyncio.Task | None = field(default=None, init=False)
    _token_store: ContextTokenStore | None = field(default=None, init=False)
    _typing_cache: TypingTicketCache | None = field(default=None, init=False)
    _dedup: MessageDeduplicator | None = field(default=None, init=False)
    _inbound_sequencer: InboundSequencer = field(default_factory=InboundSequencer, init=False)
    _resolved_account_id: str = field(default="", init=False)
    _resolved_token: str = field(default="", init=False)
    _resolved_base_url: str = field(default="", init=False)
    _resolved_cdn_base_url: str = field(default="", init=False)
    _resolved_dm_policy: str = field(default="open", init=False)
    _resolved_group_policy: str = field(default="disabled", init=False)
    _resolved_allow_from: tuple[str, ...] = field(default=(), init=False)
    _resolved_group_allow_from: tuple[str, ...] = field(default=(), init=False)
    _split_multiline_messages: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not self.account_configs:
            self.account_configs = load_weixin_gateway_accounts(
                self.app,
                respect_enabled=self.respect_enabled,
            )
        if self.adapter is None:
            self.adapter = WeixinMessagingAdapter(app=self.app)
        if self.cli_control is None and self.app.loaded_profile is not None:
            config = load_gateway_cli_control_config(
                self.app.loaded_profile.manifest,
                adapter_key="weixin",
                default_when_missing=True,
            )
            if config is not None:
                binding_store = self.cli_binding_store
                if binding_store is None:
                    state_root = self.app.state_dir
                    binding_path = (
                        None
                        if state_root is None
                        else os.path.join(state_root, "weixin-cli-bindings.json")
                    )
                    binding_store = GatewayCliBindingStore(
                        path=None if binding_path is None else Path(binding_path)
                    )
                self.cli_control = GatewayCliControlService(
                    config=self._resolved_cli_control_config(config),
                    app=self.app,
                    runtime_factory=self.cli_runtime_factory,
                    binding_store=binding_store,
                    surface_label="WeChat",
                    binding_subject="conversation",
                    control_config_path="gateway.adapters.weixin.control",
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

    def _enabled_account_configs(self) -> tuple[WeixinGatewayAccountConfig, ...]:
        return tuple(config for config in self.account_configs if config.enabled)

    def _transport_account_configs(self) -> tuple[WeixinGatewayAccountConfig, ...]:
        enabled_configs = self._enabled_account_configs()
        return enabled_configs if enabled_configs else self.account_configs

    def _state_dir(self) -> str:
        if self.runtime_state_dir is not None:
            return str(self.runtime_state_dir)
        if self.app.state_dir is not None:
            return str(self.app.state_dir)
        return str(default_gateway_state_dir())

    def describe(self) -> Mapping[str, object]:
        configured_transport: str | None = None
        configured_transport_error: str | None = None
        try:
            configured_transport = self.configured_transport()
        except (LookupError, ValueError) as exc:
            configured_transport_error = str(exc)
        return {
            "adapter_id": self.adapter.adapter_id if self.adapter is not None else WEIXIN_ADAPTER_ID,
            "profile_id": self.app.profile_id,
            "preferred_transport": "ilink",
            "implemented_transports": ("weixin-ilink",),
            "configured_transport": configured_transport,
            "configured_transport_error": configured_transport_error,
            "sdk_dependency_status": "ready" if check_weixin_requirements() else "missing_dependencies",
            "accounts": tuple(
                {
                    "account_id": config.account_id,
                    "surface": config.surface,
                    "enabled": config.enabled,
                    "base_url": config.base_url,
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
        transport_configs = self._transport_account_configs()
        if not transport_configs:
            return "ilink"
        transports = tuple(
            dict.fromkeys(_normalize_transport(config.surface) for config in transport_configs)
        )
        if len(transports) == 1:
            return transports[0]
        raise LookupError(
            "configured WeChat accounts use multiple transport surfaces; choose one explicitly"
        )

    @property
    def event_paths(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(config.event_path for config in self.account_configs))

    @property
    def http_paths(self) -> tuple[str, ...]:
        return self.event_paths

    def handle_http_event(
        self,
        payload: Mapping[str, object],
        *,
        path: str,
    ) -> tuple[str, Mapping[str, object]]:
        # iLink mode does not use HTTP callbacks.
        return "501 Not Implemented", {"ok": False, "error": "iLink transport does not use HTTP callbacks"}

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
            label=f"WeChat {normalized_target} transport",
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
            "weixin",
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
        self.runtime_dependency_ensurer(reason=f"WeChat gateway {action}")

    def managed_runtime_log_hint(self, *, target: str) -> str:
        return "elephant gateway weixin logs <account-id> --follow"

    # -----------------------------------------------------------------------
    # Async long-polling lifecycle
    # -----------------------------------------------------------------------

    def _resolve_credentials(self, account_id: str | None = None) -> WeixinResolvedAccount:
        if not self.account_configs:
            raise LookupError("no WeChat gateway accounts are configured")
        if account_id is not None:
            for config in self.account_configs:
                if config.account_id == account_id:
                    return resolve_weixin_account(config)
            raise LookupError(f"unknown WeChat gateway account: {account_id}")
        enabled_configs = self._enabled_account_configs()
        if not enabled_configs:
            raise LookupError("no enabled WeChat gateway accounts are configured")
        if len(enabled_configs) == 1:
            return resolve_weixin_account(enabled_configs[0])
        raise LookupError(
            "multiple enabled WeChat gateway accounts are configured; pass account_id explicitly"
        )

    async def start_gateway(self, account_id: str | None = None) -> None:
        """Connect and start the long-polling loop."""
        if not check_weixin_requirements():
            raise RuntimeError(
                "Weixin startup failed: aiohttp and cryptography are required. "
                "Install them with: pip install aiohttp cryptography"
            )

        account = self._resolve_credentials(account_id)
        config = account.config
        state_dir = self._state_dir()

        # Try to load saved credentials if token not in config
        resolved_token = config.token
        resolved_base_url = config.base_url
        if not resolved_token and config.account_id:
            saved = load_weixin_account(state_dir, config.account_id)
            if saved:
                resolved_token = str(saved.get("token") or "")
                if not config.base_url or config.base_url == ILINK_BASE_URL:
                    resolved_base_url = str(saved.get("base_url") or ILINK_BASE_URL)

        if not resolved_token:
            raise RuntimeError(
                "Weixin startup failed: token is required. "
                "Run 'elephant gateway weixin setup' to scan QR code and obtain credentials."
            )
        if not config.account_id or config.account_id == DEFAULT_GATEWAY_ACCOUNT_ID:
            raise RuntimeError(
                "Weixin startup failed: account_id is required. "
                "Run 'elephant gateway weixin setup' to obtain credentials."
            )

        self._resolved_account_id = config.account_id
        self._resolved_token = resolved_token
        self._resolved_base_url = resolved_base_url.rstrip("/")
        self._resolved_cdn_base_url = config.cdn_base_url.rstrip("/")
        self._resolved_dm_policy = config.dm_policy
        self._resolved_group_policy = config.group_policy
        self._resolved_allow_from = config.allow_from
        self._resolved_group_allow_from = config.group_allow_from
        self._split_multiline_messages = config.split_multiline_messages

        self._token_store = ContextTokenStore(state_dir)
        self._token_store.restore(self._resolved_account_id)
        self._typing_cache = TypingTicketCache()
        self._dedup = MessageDeduplicator()

        import aiohttp

        self._poll_session = aiohttp.ClientSession(trust_env=True, connector=_make_ssl_connector())
        self._send_session = aiohttp.ClientSession(trust_env=True, connector=_make_ssl_connector())
        self._running = True

        LOGGER.info(
            "[%s] Connected account=%s base=%s",
            self.service_key,
            _safe_id(self._resolved_account_id),
            self._resolved_base_url,
        )

        try:
            # Run the iLink long-poll, the cross-process outbound queue drainer,
            # and the idle curiosity scanner concurrently. The drainer lets cron
            # and proactive idle asks enqueue messages that this live gateway sends
            # via its own iLink session.
            poll_task = asyncio.create_task(self._poll_loop(), name="weixin-poll-loop")
            drain_task = asyncio.create_task(self._outbound_drain_loop(), name="weixin-outbound-drain-loop")
            self._poll_task = poll_task
            self._outbound_drain_task = drain_task
            try:
                done, pending = await asyncio.wait(
                    {poll_task, drain_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                for task in pending:
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                for task in done:
                    # Surface the first failure so the runtime record reflects it.
                    exc = task.exception()
                    if exc is not None:
                        raise exc
            finally:
                self._poll_task = None
                self._outbound_drain_task = None
        finally:
            await self.stop_gateway()

    async def stop_gateway(self) -> None:
        """Stop the long-polling loop and cleanup."""
        self._running = False
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        self._poll_task = None
        if self._outbound_drain_task and not self._outbound_drain_task.done():
            self._outbound_drain_task.cancel()
            try:
                await self._outbound_drain_task
            except asyncio.CancelledError:
                pass
        self._outbound_drain_task = None
        if self._poll_session and not self._poll_session.closed:
            await self._poll_session.close()
        self._poll_session = None
        if self._send_session and not self._send_session.closed:
            await self._send_session.close()
        self._send_session = None
        LOGGER.info("[%s] Disconnected", self.service_key)

    async def _outbound_drain_loop(self) -> None:
        """Drain the shared outbound queue, sending each row via ``_send_ilink_message``.

        Uses the shared ``run_outbound_drain_loop`` helper so the reliability
        semantics (claim / complete / release / backoff) match every other
        adapter's drain loop exactly. The adapter-specific part is just a
        sender callable that wraps ``_send_ilink_message``.
        """
        queue = _outbound_queue_for_state_dir(self._state_dir())
        await run_outbound_drain_loop(
            queue=queue,
            adapter_id=WEIXIN_ADAPTER_ID,
            sender=self._send_outbound_queue_row,
            is_running=lambda: self._running,
            logger=LOGGER,
            log_label=self.service_key,
        )

    async def _send_outbound_queue_row(self, row: GatewayOutboundRow) -> None:
        """Send one queued outbound row through the live iLink session.

        Uses ``_send_ilink_message`` — the same code path as a normal conversation
        reply — so queued messages and interactive replies share one delivery
        implementation (token freshness, chunk splitting, retry semantics).
        """
        surface = str(row.metadata.get("runtime_surface") or "weixin-ilink")
        outbound = GatewayOutboundMessage(
            message_id=row.row_id,
            account=GatewayAccountRef(
                adapter_id=WEIXIN_ADAPTER_ID,
                account_id=row.account_id or self._resolved_account_id,
                surface="ilink",
            ),
            conversation=GatewayConversationRef(conversation_id=row.conversation_id),
            session_id=str(row.metadata.get("session_id") or f"outbound-queue:{row.row_id}"),
            body=row.body,
            metadata={
                **dict(row.metadata),
                "delivery_surface": surface,
                "queue_row_id": row.row_id,
                "queue_attempts": row.attempts,
            },
        )
        await self._send_ilink_message(outbound)

    async def _poll_loop(self) -> None:
        assert self._poll_session is not None
        state_dir = self._state_dir()
        sync_buf = _load_sync_buf(state_dir, self._resolved_account_id)
        timeout_ms = LONG_POLL_TIMEOUT_MS
        consecutive_failures = 0

        while self._running:
            try:
                response = await _get_updates(
                    self._poll_session,
                    base_url=self._resolved_base_url,
                    token=self._resolved_token,
                    sync_buf=sync_buf,
                    timeout_ms=timeout_ms,
                )
                suggested_timeout = response.get("longpolling_timeout_ms")
                if isinstance(suggested_timeout, int) and suggested_timeout > 0:
                    timeout_ms = suggested_timeout

                ret = response.get("ret", 0)
                errcode = response.get("errcode", 0)
                if ret not in (0, None) or errcode not in (0, None):
                    if ret == SESSION_EXPIRED_ERRCODE or errcode == SESSION_EXPIRED_ERRCODE:
                        LOGGER.error("[%s] Session expired; pausing for 10 minutes", self.service_key)
                        await asyncio.sleep(600)
                        consecutive_failures = 0
                        continue
                    consecutive_failures += 1
                    LOGGER.warning(
                        "[%s] getUpdates failed ret=%s errcode=%s errmsg=%s (%d/%d)",
                        self.service_key,
                        ret,
                        errcode,
                        response.get("errmsg", ""),
                        consecutive_failures,
                        MAX_CONSECUTIVE_FAILURES,
                    )
                    await asyncio.sleep(
                        BACKOFF_DELAY_SECONDS if consecutive_failures >= MAX_CONSECUTIVE_FAILURES
                        else RETRY_DELAY_SECONDS
                    )
                    if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        consecutive_failures = 0
                    continue

                consecutive_failures = 0
                new_sync_buf = str(response.get("get_updates_buf") or "")
                if new_sync_buf:
                    sync_buf = new_sync_buf
                    _save_sync_buf(state_dir, self._resolved_account_id, sync_buf)

                for message in response.get("msgs") or []:
                    asyncio.create_task(self._process_message_safe(message))
            except asyncio.CancelledError:
                break
            except Exception as exc:
                consecutive_failures += 1
                LOGGER.error(
                    "[%s] poll error (%d/%d): %s",
                    self.service_key,
                    consecutive_failures,
                    MAX_CONSECUTIVE_FAILURES,
                    exc,
                )
                await asyncio.sleep(
                    BACKOFF_DELAY_SECONDS if consecutive_failures >= MAX_CONSECUTIVE_FAILURES
                    else RETRY_DELAY_SECONDS
                )
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    consecutive_failures = 0

    async def _process_message_safe(self, message: dict[str, Any]) -> None:
        try:
            sequence_key = self._inbound_sequence_key(message)
            if sequence_key is None:
                await self._process_message(message)
            else:
                await self._inbound_sequencer.run_serialized(
                    sequence_key,
                    lambda: self._process_message(message),
                )
        except Exception as exc:
            LOGGER.error(
                "[%s] unhandled inbound error from=%s: %s",
                self.service_key,
                _safe_id(message.get("from_user_id")),
                exc,
                exc_info=True,
            )

    def _inbound_sequence_key(self, message: dict[str, Any]) -> str | None:
        sender_id = str(message.get("from_user_id") or "").strip()
        if not sender_id or sender_id == self._resolved_account_id:
            return None
        chat_type, effective_chat_id = _guess_chat_type(message, self._resolved_account_id)
        conversation_id = effective_chat_id if chat_type == "group" and effective_chat_id else sender_id
        if not conversation_id:
            return None
        return InboundSequencer.key_for(
            account_id=self._resolved_account_id,
            conversation_id=conversation_id,
        )

    async def _process_message(self, message: dict[str, Any]) -> None:
        sender_id = str(message.get("from_user_id") or "").strip()
        if not sender_id:
            return
        if sender_id == self._resolved_account_id:
            return

        message_id = str(message.get("message_id") or "").strip()
        if message_id and self._dedup and self._dedup.is_duplicate(message_id):
            return

        chat_type, effective_chat_id = _guess_chat_type(message, self._resolved_account_id)
        if chat_type == "group":
            if self._resolved_group_policy == "disabled":
                return
            if self._resolved_group_policy == "allowlist" and effective_chat_id not in self._resolved_group_allow_from:
                return
        elif not self._is_dm_allowed(sender_id):
            return

        # Update context token
        context_token = str(message.get("context_token") or "").strip()
        if context_token and self._token_store:
            self._token_store.set(self._resolved_account_id, sender_id, context_token)

        # Fetch typing ticket in background
        asyncio.create_task(self._maybe_fetch_typing_ticket(sender_id, context_token or None))

        # Extract text
        item_list = message.get("item_list") or []
        text = _extract_text(item_list)

        if not text:
            return

        # Build inbound message through the adapter
        adapter = self.adapter
        if adapter is None:
            return

        inbound = adapter.normalize_event(
            {
                "message_id": message_id,
                "from_wxid": sender_id,
                "content": text,
                "room": effective_chat_id if chat_type == "group" else "",
                "chat_type": chat_type,
                "transport": "ilink",
            },
            account_id=self._resolved_account_id,
            transport="ilink",
        )

        if self.cli_control is not None:
            result = self.cli_control.handle_message(inbound)
            if result.handled and result.body is not None:
                outbound = self._build_control_outbound(inbound, body=result.body, session_id=result.session_id)
                await self._send_ilink_message(outbound)
            if result.handled:
                return

        exchange = self.app.handle_message(
            inbound,
            reply_to_message_id=inbound.reply_to_message_id or inbound.event_id,
            attachment_refs=inbound.attachment_refs,
            metadata={
                **dict(inbound.metadata),
                "delivery_surface": inbound.account.surface or "weixin-ilink",
            },
        )

        if exchange.delivery.outbound is not None:
            await self._send_ilink_message(exchange.delivery.outbound)

    def _is_dm_allowed(self, sender_id: str) -> bool:
        if self._resolved_dm_policy == "disabled":
            return False
        if self._resolved_dm_policy == "allowlist":
            return sender_id in self._resolved_allow_from
        return True

    async def _maybe_fetch_typing_ticket(self, user_id: str, context_token: str | None) -> None:
        if not self._poll_session or not self._resolved_token:
            return
        if self._typing_cache and self._typing_cache.get(user_id):
            return
        try:
            response = await _get_config(
                self._poll_session,
                base_url=self._resolved_base_url,
                token=self._resolved_token,
                user_id=user_id,
                context_token=context_token,
            )
            typing_ticket = str(response.get("typing_ticket") or "")
            if typing_ticket and self._typing_cache:
                self._typing_cache.set(user_id, typing_ticket)
        except Exception as exc:
            LOGGER.debug("[%s] getConfig failed for %s: %s", self.service_key, _safe_id(user_id), exc)

    async def _send_ilink_message(self, outbound: GatewayOutboundMessage) -> None:
        """Send a reply via iLink sendmessage API."""
        if not self._send_session or not self._resolved_token:
            return

        content = _normalize_markdown_blocks(outbound.body)
        chat_id = outbound.conversation_id
        context_token = (
            self._token_store.get(self._resolved_account_id, chat_id)
            if self._token_store
            else None
        )

        chunks = _split_text_for_weixin_delivery(
            content, MAX_MESSAGE_LENGTH, self._split_multiline_messages
        )
        chunks = [c for c in chunks if c and c.strip()]

        for idx, chunk in enumerate(chunks):
            client_id = f"elephant-weixin-{uuid4().hex}"
            retried_without_token = False
            for attempt in range(3):
                try:
                    resp = await _ilink_send_message(
                        self._send_session,
                        base_url=self._resolved_base_url,
                        token=self._resolved_token,
                        to=chat_id,
                        text=chunk,
                        context_token=context_token,
                        client_id=client_id,
                    )
                    # Check for session-expired error
                    if resp and isinstance(resp, dict):
                        ret = resp.get("ret")
                        errcode = resp.get("errcode")
                        if (ret is not None and ret not in (0,)) or (errcode is not None and errcode not in (0,)):
                            is_session_expired = (
                                ret == SESSION_EXPIRED_ERRCODE
                                or errcode == SESSION_EXPIRED_ERRCODE
                            )
                            if is_session_expired and not retried_without_token and context_token:
                                retried_without_token = True
                                context_token = None
                                if self._token_store:
                                    self._token_store._cache.pop(
                                        self._token_store._key(self._resolved_account_id, chat_id), None
                                    )
                                LOGGER.warning(
                                    "[%s] session expired for %s; retrying without context_token",
                                    self.service_key, _safe_id(chat_id),
                                )
                                continue
                            errmsg = resp.get("errmsg") or resp.get("msg") or "unknown error"
                            raise RuntimeError(
                                f"iLink sendmessage error: ret={ret} errcode={errcode} errmsg={errmsg}"
                            )
                    break
                except Exception as exc:
                    if attempt >= 2:
                        LOGGER.error(
                            "[%s] send failed to=%s after 3 attempts: %s",
                            self.service_key, _safe_id(chat_id), exc,
                        )
                        raise
                    await asyncio.sleep(1.0 * (attempt + 1))

            # Inter-chunk delay
            if idx < len(chunks) - 1:
                await asyncio.sleep(0.35)

    def _build_control_outbound(
        self,
        inbound: GatewayInboundMessage,
        *,
        body: str,
        session_id: str | None,
    ) -> GatewayOutboundMessage:
        return GatewayOutboundMessage(
            message_id=f"weixin-control:{session_id or inbound.conversation_id}:{uuid4().hex[:12]}",
            account=inbound.account,
            conversation=inbound.conversation,
            session_id=session_id or f"control:{inbound.conversation_id}",
            body=body,
            reply_to_message_id=inbound.reply_to_message_id or inbound.event_id,
            attachment_refs=(),
            metadata={
                **dict(inbound.metadata),
                "delivery_surface": inbound.account.surface or "weixin-control",
                "runtime_surface": "cli-runtime",
            },
        )

    # -----------------------------------------------------------------------
    # HTTP callback interface (not used in iLink mode)
    # -----------------------------------------------------------------------

    def deliver_cron_result(self, job, execution) -> None:
        """Enqueue a cron execution result for delivery by the live weixin gateway process.

        Architecture note: this method runs **in the cron scheduler process**, not in
        the gateway process. Rather than open its own iLink session (which used to
        cause token state drift, DNS races, and silent losses when the gateway was
        restarting), we write the outbound to a shared on-disk queue that the live
        weixin gateway polls and drains via its normal ``_send_ilink_message`` path.
        This means cron replies and normal-conversation replies now use exactly one
        delivery implementation.

        When a job was created without a bound elephant (``job.elephant_id is None``) — e.g. via
        an older IM path or the dashboard's POST /operator/cron without an ``elephant_id`` —
        we fall back to the sole weixin conversation if (and only if) exactly one
        weixin identity is registered.
        """
        if getattr(job, "action_kind", "") == "learning":
            return
        summary = str(getattr(execution, "summary", "") or "").strip()
        if not summary or summary == "[SILENT]":
            return
        identity_store = self.app.core.dependencies.identity_store
        records = resolve_cron_identity_records(
            identity_store=identity_store,
            adapter_id=WEIXIN_ADAPTER_ID,
            elephant_id=job.elephant_id,
        )
        if not records:
            if not job.elephant_id:
                # Only warn when we have weixin identities but cannot disambiguate — if
                # there are zero weixin identities, the scheduler's fan-out simply asked
                # the wrong adapter, which is expected noise.
                any_weixin = any(
                    r.key.adapter_id == WEIXIN_ADAPTER_ID
                    for r in identity_store.list_records()
                )
                if any_weixin:
                    LOGGER.warning(
                        "cron delivery: skipping job=%s — no job.elephant_id and multiple weixin herd",
                        job.job_id,
                    )
            return
        record = records[0]
        queue = _outbound_queue_for_state_dir(self._state_dir())
        queue.enqueue(
            adapter_id=WEIXIN_ADAPTER_ID,
            account_id=record.key.account_id,
            conversation_id=record.key.conversation_id,
            body=execution.summary,
            metadata={
                "cron_job_id": job.job_id,
                "cron_job_name": job.name,
                "runtime_surface": "cron-scheduler",
                "enqueued_via": "deliver_cron_result",
            },
        )

    def handle_callback(
        self,
        payload: Mapping[str, object],
        *,
        account_id: str | None = None,
    ) -> WeixinGatewayEventResult:
        raise RuntimeError("iLink transport does not support HTTP callbacks; use start_gateway() instead")


def _outbound_queue_for_state_dir(state_dir: str) -> GatewayOutboundQueue:
    """Return the canonical outbound queue for gateway cross-process delivery.

    Thin wrapper over the package-level ``default_outbound_queue_path`` so every
    process sharing that state directory (scheduler enqueues, gateway drains,
    CLI ``message`` enqueues) hits the same rows.
    """
    return GatewayOutboundQueue(path=default_outbound_queue_path(state_dir))


def register_weixin_gateway_service(registry: GatewayPluginRegistry) -> GatewayPluginRegistry:
    from .weixin import WeixinGatewayService

    registry.register_service(
        "weixin",
        factory=lambda app, **kwargs: WeixinGatewayService(app=app, **kwargs),
        enabled_by_default=True,
    )
    return registry


def build_weixin_gateway_service(
    *,
    profile_id: str = "you",
    provider_profile: Mapping[str, Any] | None = None,
    state_dir: str | None = None,
    environ: Mapping[str, str] | None = None,
    plugin_registry: GatewayPluginRegistry | None = None,
) -> WeixinGatewayService:
    app, _, _ = build_gateway_app(
        profile_id=profile_id,
        provider_profile=provider_profile,
        state_dir=state_dir,
        plugin_registry=plugin_registry,
    )
    return WeixinGatewayService(
        app=app,
        environ=dict(environ or os.environ),
        runtime_state_dir=Path(state_dir) if state_dir is not None else None,
    )
