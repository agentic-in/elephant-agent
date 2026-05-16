"""DingDing gateway service using dingtalk_stream SDK."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import asyncio
import importlib.util
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

from apps.runtime_layout import default_cli_state_dir

from .cli_control import (
    CliRuntimeFactory,
    GatewayCliBindingStore,
    GatewayCliControlService,
    load_gateway_cli_control_config,
)
from .plugins import GatewayManagedRuntime, GatewayPluginRegistry, default_gateway_runtime_path
from .runtime import DINGDING_ADAPTER_ID, DingdingMessagingAdapter, GatewayApp, build_gateway_app

from .dingding_support import (
    DEFAULT_DINGDING_CLIENT_ID_ENV,
    DEFAULT_DINGDING_CLIENT_SECRET_ENV,
    DEFAULT_DINGDING_ROBOT_CODE_ENV,
    DINGTALK_STREAM_PIP_SPEC,
    SUPPORTED_DINGDING_TRANSPORTS,
    DingdingGatewayAccountConfig,
    DingdingGatewayEventResult,
    DingdingResolvedAccount,
    _dingding_chat_type,
    _dingtalk_stream_dependency_status,
    _load_dingtalk_stream_sdk,
    _normalize_transport,
    load_dingding_gateway_accounts,
    resolve_dingding_account,
)

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class DingdingGatewayService:
    app: GatewayApp
    account_configs: tuple[DingdingGatewayAccountConfig, ...] = ()
    environ: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    adapter: DingdingMessagingAdapter | None = None
    cli_runtime_factory: CliRuntimeFactory | None = None
    cli_binding_store: GatewayCliBindingStore | None = None
    cli_control: GatewayCliControlService | None = None
    default_cli_state_dir: str | None = None
    runtime_dependency_ensurer: Callable[..., object] | None = None
    respect_enabled: bool = True
    service_key: str = "dingding"
    runtime_state_dir: Path | None = None
    _outbound_drain_task: asyncio.Task | None = field(default=None, init=False, repr=False)
    _inbound_sequencer: InboundSequencer = field(default_factory=InboundSequencer, init=False, repr=False)
    _running: bool = field(default=False, init=False, repr=False)
    _daemon_task: asyncio.Task | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.account_configs:
            self.account_configs = load_dingding_gateway_accounts(
                self.app,
                respect_enabled=self.respect_enabled,
            )
        if self.adapter is None:
            self.adapter = DingdingMessagingAdapter(app=self.app)
        if self.cli_control is None and self.app.loaded_profile is not None:
            config = load_gateway_cli_control_config(
                self.app.loaded_profile.manifest,
                adapter_key="dingding",
                default_when_missing=True,
            )
            if config is not None:
                binding_store = self.cli_binding_store
                if binding_store is None:
                    state_root = self.app.state_dir
                    binding_path = (
                        None
                        if state_root is None
                        else os.path.join(state_root, "dingding-cli-bindings.json")
                    )
                    binding_store = GatewayCliBindingStore(
                        path=None if binding_path is None else Path(binding_path)
                    )
                self.cli_control = GatewayCliControlService(
                    config=self._resolved_cli_control_config(config),
                    app=self.app,
                    runtime_factory=self.cli_runtime_factory,
                    binding_store=binding_store,
                    surface_label="DingDing",
                    binding_subject="conversation",
                    control_config_path="gateway.adapters.dingding.control",
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

    def _enabled_account_configs(self) -> tuple[DingdingGatewayAccountConfig, ...]:
        return tuple(config for config in self.account_configs if config.enabled)

    def _transport_account_configs(self) -> tuple[DingdingGatewayAccountConfig, ...]:
        enabled_configs = self._enabled_account_configs()
        return enabled_configs if enabled_configs else self.account_configs

    def has_credentials(self) -> bool:
        """Return True if at least one account can be resolved with current environment."""
        for config in self.account_configs:
            try:
                resolve_dingding_account(config, environ=self.environ)
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
            "adapter_id": self.adapter.adapter_id if self.adapter is not None else DINGDING_ADAPTER_ID,
            "profile_id": self.app.profile_id,
            "preferred_transport": "stream",
            "implemented_transports": ("dingtalk-stream",),
            "configured_transport": configured_transport,
            "configured_transport_error": configured_transport_error,
            "sdk_dependency_status": _dingtalk_stream_dependency_status(),
            "accounts": tuple(
                {
                    "account_id": config.account_id,
                    "surface": config.surface,
                    "enabled": config.enabled,
                    "credentials_status": (
                        "configured"
                        if _can_resolve_account(config, environ=self.environ)
                        else "missing_credentials"
                    ),
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
            return "stream"
        transports = tuple(
            dict.fromkeys(_normalize_transport(config.surface) for config in transport_configs)
        )
        if len(transports) == 1:
            return transports[0]
        raise LookupError(
            "configured DingDing accounts use multiple transport surfaces; choose one explicitly"
        )

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
            label=f"DingDing {normalized_target} transport",
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
            "dingding",
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
        self.runtime_dependency_ensurer(reason=f"DingDing gateway {action}")

    def managed_runtime_log_hint(self, *, target: str) -> str:
        return "elephant gateway dingding logs <account-id> --follow"

    async def start_gateway(
        self,
        *,
        account_id: str | None = None,
        dingtalk_module: Any | None = None,
    ) -> object:
        dingtalk_stream = _load_dingtalk_stream_sdk(dingtalk_module)
        account = self._match_account(account_id=account_id)
        LOGGER.info("DingDing start_gateway: client_id=%s..., robot_code=%s...",
                     account.client_id[:8] if account.client_id else "(empty)",
                     account.robot_code[:8] if account.robot_code else "(empty)")

        # New SDK: DingTalkStreamClient + Credential (replaces OpenDingTalkClient)
        client_cls = getattr(dingtalk_stream, "DingTalkStreamClient", None)
        credential_cls = getattr(dingtalk_stream, "Credential", None)
        # Fallback: old SDK
        open_dingtalk_client = getattr(dingtalk_stream, "OpenDingTalkClient", None) if client_cls is None else None

        if client_cls is not None and credential_cls is not None:
            _use_new_sdk = True
        elif open_dingtalk_client is not None:
            _use_new_sdk = False
        else:
            raise RuntimeError("dingtalk_stream DingTalkStreamClient (or OpenDingTalkClient) is unavailable")

        chatbot_handler = getattr(dingtalk_stream, "ChatbotHandler", None)
        if chatbot_handler is None:
            raise RuntimeError("dingtalk_stream ChatbotHandler is unavailable")

        service = self
        adapter = self.adapter
        assert adapter is not None
        # Store handler ref so we can use its reply methods later
        handler_ref: list[object] = [None]

        class _ElephantDingdingHandler(chatbot_handler):
            async def process(self, callback: object) -> tuple:
                try:
                    data = getattr(callback, "data", None)
                    payload = _dingtalk_callback_payload(callback)
                    LOGGER.debug("DingDing callback: payload keys=%s", list(payload.keys()) if isinstance(payload, Mapping) else type(payload).__name__)
                    # Build ChatbotMessage for reply methods
                    incoming_msg = None
                    chatbot_msg_cls = getattr(dingtalk_stream, "ChatbotMessage", None)
                    if chatbot_msg_cls is not None and hasattr(chatbot_msg_cls, "from_dict"):
                        if isinstance(data, dict):
                            incoming_msg = chatbot_msg_cls.from_dict(data)
                    await service._on_dingtalk_message_safe(
                        payload,
                        account=account,
                        adapter=adapter,
                        dingtalk_module=dingtalk_stream,
                        handler=self,
                        incoming_message=incoming_msg,
                    )
                except Exception:
                    LOGGER.exception("DingDing callback processing failed")
                return (200, "OK")

        handler_instance = _ElephantDingdingHandler()
        handler_ref[0] = handler_instance

        if _use_new_sdk:
            credential = credential_cls(account.client_id, account.client_secret)
            client = client_cls(credential)
            # ChatbotMessage.TOPIC = '/v1.0/im/bot/messages/get'
            chatbot_msg_cls = getattr(dingtalk_stream, "ChatbotMessage", None)
            topic = getattr(chatbot_msg_cls, "TOPIC", "/v1.0/im/bot/messages/get") if chatbot_msg_cls else "/v1.0/im/bot/messages/get"
            client.register_callback_handler(
                topic, handler_instance,
            )
        else:
            client = open_dingtalk_client(
                account.client_id,
                account.client_secret,
            )
            client.register_callback_handler(chatbot_handler, handler_instance)

        self._running = True
        self._outbound_drain_task = asyncio.create_task(
            self._outbound_drain_loop(account=account, dingtalk_module=dingtalk_stream),
            name="dingding-outbound-drain-loop",
        )
        try:
            if _use_new_sdk:
                await client.start()
            else:
                client.start()
        finally:
            self._running = False
            if self._outbound_drain_task is not None:
                self._outbound_drain_task.cancel()
                try:
                    await self._outbound_drain_task
                except asyncio.CancelledError:
                    pass
                self._outbound_drain_task = None
        # Attach handler ref for reply usage
        client._elephant_handler = handler_instance
        client._elephant_use_new_sdk = _use_new_sdk
        return client

    def _outbound_queue(self) -> GatewayOutboundQueue:
        state_root = self.app.state_dir or self.runtime_state_dir or self._inferred_cli_state_dir()
        if state_root is None:
            raise RuntimeError("cannot resolve state dir for dingding outbound queue")
        return GatewayOutboundQueue(path=default_outbound_queue_path(state_root))

    def _inbound_sequence_key(
        self, payload: Mapping[str, object], *, account: DingdingResolvedAccount,
    ) -> str | None:
        sender_id = str(payload.get("sender_id") or "").strip()
        robot_code = str(payload.get("robot_code") or account.robot_code or "").strip()
        if not sender_id or sender_id == robot_code:
            return None
        chat_type = _dingding_chat_type(payload)
        conversation_id = str(payload.get("conversation_id") or "").strip()
        effective_conversation = conversation_id if chat_type == "group" and conversation_id else sender_id
        if not effective_conversation:
            return None
        return InboundSequencer.key_for(
            account_id=account.account_id,
            conversation_id=effective_conversation,
        )

    async def _on_dingtalk_message_safe(
        self,
        payload: Mapping[str, object],
        *,
        account: DingdingResolvedAccount,
        adapter: DingdingMessagingAdapter,
        dingtalk_module: Any,
        handler: Any | None = None,
        incoming_message: Any | None = None,
    ) -> None:
        try:
            sequence_key = self._inbound_sequence_key(payload, account=account)
            if sequence_key is None:
                await self._on_dingtalk_message(
                    payload,
                    account=account,
                    adapter=adapter,
                    dingtalk_module=dingtalk_module,
                    handler=handler,
                    incoming_message=incoming_message,
                )
            else:
                await self._inbound_sequencer.run_serialized(
                    sequence_key,
                    lambda: self._on_dingtalk_message(
                        payload,
                        account=account,
                        adapter=adapter,
                        dingtalk_module=dingtalk_module,
                        handler=handler,
                        incoming_message=incoming_message,
                    ),
                )
        except Exception as exc:
            LOGGER.error(
                "[%s] unhandled inbound error sender=%s: %s",
                self.service_key,
                str(payload.get("sender_id") or "")[:8],
                exc,
                exc_info=True,
            )

    async def _on_dingtalk_message(
        self,
        payload: Mapping[str, object],
        *,
        account: DingdingResolvedAccount,
        adapter: DingdingMessagingAdapter,
        dingtalk_module: Any,
        handler: Any | None = None,
        incoming_message: Any | None = None,
    ) -> None:
        inbound = adapter.normalize_event(
            payload,
            account_id=account.account_id,
            transport="stream",
        )
        if self.cli_control is not None:
            result = self.cli_control.handle_message(inbound)
            if result.handled and result.body is not None:
                outbound = self._build_control_outbound(inbound, body=result.body, session_id=result.session_id)
                delivery_request = adapter.build_reply_request(outbound)
                delivery_request = {**dict(delivery_request), "incoming_message": incoming_message}
                await self._send_dingtalk_reply(
                    delivery_request,
                    account=account,
                    dingtalk_module=dingtalk_module,
                    handler=handler,
                )
            if result.handled:
                return

        exchange = self.app.handle_message(
            inbound,
            reply_to_message_id=inbound.reply_to_message_id or inbound.event_id,
            attachment_refs=inbound.attachment_refs,
            metadata={
                **dict(inbound.metadata),
                "delivery_surface": inbound.account.surface or "dingding-stream",
            },
        )
        if exchange.delivery.outbound is None:
            return
        delivery_request = adapter.build_reply_request(exchange.delivery.outbound)
        delivery_request = {**dict(delivery_request), "incoming_message": incoming_message}
        await self._send_dingtalk_reply(
            delivery_request,
            account=account,
            dingtalk_module=dingtalk_module,
            handler=handler,
        )

    async def _send_dingtalk_reply(
        self,
        delivery_request: Mapping[str, object],
        *,
        account: DingdingResolvedAccount,
        dingtalk_module: Any,
        handler: Any | None = None,
    ) -> None:
        body = delivery_request.get("body")
        if not isinstance(body, Mapping):
            LOGGER.warning("DingDing reply body is not a Mapping: %s", type(body).__name__)
            return
        msg_key = str(body.get("msgKey") or "sampleText")
        msg_param = str(body.get("msgParam") or "")

        try:
            # New SDK: use session_webhook for direct reply
            if handler is not None and hasattr(handler, "reply_markdown"):
                incoming = delivery_request.get("incoming_message")
                if incoming is not None:
                    # DingTalk markdown requires non-empty title; use first line or fallback
                    raw_title = str(body.get("title") or "")
                    title = raw_title if raw_title else (msg_param.split("\n")[0][:64] if msg_param else "Reply")
                    import json as _json
                    import requests as _requests
                    webhook_url = getattr(incoming, "session_webhook", None)
                    sender_staff_id = getattr(incoming, "sender_staff_id", None)
                    if not webhook_url:
                        LOGGER.warning("DingDing session_webhook is missing; cannot reply")
                        return
                    reply_payload = {
                        "msgtype": "markdown",
                        "markdown": {
                            "title": title,
                            "text": msg_param,
                        },
                        "at": {
                            "atUserIds": [sender_staff_id] if sender_staff_id else [],
                        },
                    }
                    resp = _requests.post(
                        webhook_url,
                        headers={"Content-Type": "application/json", "Accept": "*/*"},
                        data=_json.dumps(reply_payload),
                    )
                    if resp.status_code != 200 or resp.json().get("errcode"):
                        LOGGER.error("DingDing reply failed: status=%s body=%s", resp.status_code, resp.text[:500])
                    else:
                        LOGGER.debug("DingDing reply sent successfully")
                    resp.raise_for_status()
                    return
                else:
                    LOGGER.warning("DingDing incoming_message is None; falling through to reply API")

            # Fallback: old SDK DingTalkStreamReplyApi
            reply_api = getattr(dingtalk_module, "DingTalkStreamReplyApi", None)
            robot_code = str(body.get("robotCode") or account.robot_code)
            conversation_id = str(delivery_request.get("conversation_id") or "")
            if reply_api is not None:
                reply_api(robot_code).send(
                    conversation_id,
                    msg_key,
                    msg_param,
                )
            else:
                LOGGER.warning("DingDing reply API unavailable; response not delivered")
        except Exception:
            LOGGER.exception("DingDing reply send failed")

    def _build_control_outbound(
        self,
        inbound: GatewayInboundMessage,
        *,
        body: str,
        session_id: str | None,
    ) -> GatewayOutboundMessage:
        return GatewayOutboundMessage(
            message_id=f"dingding-control:{session_id or inbound.conversation_id}:{uuid4().hex[:12]}",
            account=inbound.account,
            conversation=inbound.conversation,
            session_id=session_id or f"control:{inbound.conversation_id}",
            body=body,
            reply_to_message_id=inbound.reply_to_message_id or inbound.event_id,
            attachment_refs=(),
            metadata={
                **dict(inbound.metadata),
                "delivery_surface": inbound.account.surface or "dingding-control",
                "runtime_surface": "cli-runtime",
            },
        )

    def _match_account(
        self,
        *,
        account_id: str | None = None,
    ) -> DingdingResolvedAccount:
        if not self.account_configs:
            raise LookupError("no DingDing gateway accounts are configured")
        if account_id is not None:
            for config in self.account_configs:
                if config.account_id == account_id:
                    return resolve_dingding_account(config, environ=self.environ)
            raise LookupError(f"unknown DingDing gateway account: {account_id}")
        enabled_configs = self._enabled_account_configs()
        if not enabled_configs:
            raise LookupError("no enabled DingDing gateway accounts are configured")
        if len(enabled_configs) == 1:
            return resolve_dingding_account(enabled_configs[0], environ=self.environ)
        raise LookupError(
            "multiple enabled DingDing gateway accounts are configured; pass account_id explicitly"
        )

    # ── Outbound drain (shared queue) ─────────────────────────

    async def _outbound_drain_loop(self, *, account: DingdingResolvedAccount, dingtalk_module: Any) -> None:
        """Drain the shared outbound queue for DingDing."""
        queue = self._outbound_queue()
        await run_outbound_drain_loop(
            queue=queue,
            adapter_id=DINGDING_ADAPTER_ID,
            sender=self._send_outbound_queue_row,
            is_running=lambda: self._running,
            logger=LOGGER,
            log_label=self.service_key,
        )

    async def _send_outbound_queue_row(self, row: GatewayOutboundRow) -> None:
        """Send one queued outbound row via DingDing reply API."""
        if self.adapter is None:
            return
        try:
            account = self._match_account(account_id=row.account_id)
        except LookupError:
            LOGGER.warning("[dingding] cannot resolve account for queued row: %s", row.account_id)
            return
        outbound = GatewayOutboundMessage(
            message_id=row.row_id,
            account=GatewayAccountRef(
                adapter_id=DINGDING_ADAPTER_ID,
                account_id=row.account_id or DEFAULT_GATEWAY_ACCOUNT_ID,
                surface="stream",
            ),
            conversation=GatewayConversationRef(conversation_id=row.conversation_id),
            session_id=str(row.metadata.get("session_id") or f"outbound-queue:{row.row_id}"),
            body=row.body,
            metadata={
                **dict(row.metadata),
                "delivery_surface": "dingding-stream",
                "queue_row_id": row.row_id,
                "queue_attempts": row.attempts,
            },
        )
        delivery_request = self.adapter.build_reply_request(outbound)
        await self._send_dingtalk_reply(
            delivery_request,
            account=account,
            dingtalk_module=None,
        )

    # ── DaemonService ──────────────────────────────────────────

    async def start_daemon_task(self, *, loop: Any) -> asyncio.Task | None:
        """Start DingDing gateway as a daemon task in the unified event loop."""
        self._running = True
        task = asyncio.create_task(self.start_gateway(), name="dingding-daemon")
        self._daemon_task = task
        return task

    async def stop_daemon_task(self) -> None:
        """Gracefully stop the DingDing daemon task."""
        self._running = False
        if self._outbound_drain_task is not None and not self._outbound_drain_task.done():
            self._outbound_drain_task.cancel()
            try:
                await self._outbound_drain_task
            except asyncio.CancelledError:
                pass
            self._outbound_drain_task = None
        if self._daemon_task is not None and not self._daemon_task.done():
            self._daemon_task.cancel()
            try:
                await self._daemon_task
            except asyncio.CancelledError:
                pass
        self._daemon_task = None


def _can_resolve_account(config: DingdingGatewayAccountConfig, *, environ: Mapping[str, str]) -> bool:
    try:
        resolve_dingding_account(config, environ=environ)
        return True
    except LookupError:
        return False


def _dingtalk_callback_payload(callback: object) -> Mapping[str, object]:
    """Extract a normalized payload from a dingtalk_stream callback object."""
    headers = getattr(callback, "headers", None) or {}
    data = getattr(callback, "data", None) or {}

    if isinstance(headers, Mapping) and isinstance(data, Mapping):
        return {**dict(headers), **dict(data)}

    # New SDK: CallbackMessage with Headers object + data dict
    headers_dict: dict[str, object] = {}
    if hasattr(headers, "to_dict"):
        headers_dict = dict(headers.to_dict())
    elif hasattr(headers, "__dict__"):
        headers_dict = {k: v for k, v in vars(headers).items() if v is not None and not k.startswith("_")}

    data_dict: dict[str, object] = {}
    if isinstance(data, Mapping):
        data_dict = dict(data)

    merged = {**headers_dict, **data_dict}

    # Flatten nested text/content fields that the adapter expects
    # New SDK puts message content under data["text"] as {"content": "..."}
    if "text" in merged and isinstance(merged["text"], Mapping):
        text_content = merged["text"].get("content") or merged["text"].get("text") or ""
        merged["text_content"] = str(text_content).strip()
    if "senderId" in merged and "sender_id" not in merged:
        merged["sender_id"] = merged["senderId"]
    if "conversationId" in merged and "conversation_id" not in merged:
        merged["conversation_id"] = merged["conversationId"]
    if "conversationType" in merged and "conversation_type" not in merged:
        merged["conversation_type"] = merged["conversationType"]
    if "senderNick" in merged and "sender_nick" not in merged:
        merged["sender_nick"] = merged["senderNick"]
    if "senderStaffId" in merged and "sender_staff_id" not in merged:
        merged["sender_staff_id"] = merged["senderStaffId"]
    if "chatbotUserId" in merged and "chatbot_user_id" not in merged:
        merged["chatbot_user_id"] = merged["chatbotUserId"]
    if "robotCode" in merged and "robot_code" not in merged:
        merged["robot_code"] = merged["robotCode"]
    if "msgId" in merged and "message_id" not in merged:
        merged["message_id"] = merged["msgId"]
    if "createAt" in merged and "create_at" not in merged:
        merged["create_at"] = merged["createAt"]

    return merged


def register_dingding_gateway_service(registry: GatewayPluginRegistry) -> GatewayPluginRegistry:
    from .dingding import DingdingGatewayService

    registry.register_service(
        "dingding",
        factory=lambda app, **kwargs: DingdingGatewayService(app=app, **kwargs),
        enabled_by_default=True,
    )
    return registry


def build_dingding_gateway_service(
    *,
    profile_id: str = "you",
    provider_profile: Mapping[str, Any] | None = None,
    state_dir: str | None = None,
    environ: Mapping[str, str] | None = None,
    plugin_registry: GatewayPluginRegistry | None = None,
) -> DingdingGatewayService:
    app, _, _ = build_gateway_app(
        profile_id=profile_id,
        provider_profile=provider_profile,
        state_dir=state_dir,
        plugin_registry=plugin_registry,
    )
    return DingdingGatewayService(
        app=app,
        environ=dict(environ or os.environ),
        runtime_state_dir=Path(state_dir) if state_dir is not None else None,
    )
