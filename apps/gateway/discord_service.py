from __future__ import annotations

from .discord_support import *  # noqa: F401,F403
from .discord_transport import DiscordPyDeliveryTransport

@dataclass(slots=True)
class DiscordGatewayService:
    app: GatewayApp
    account_configs: tuple[DiscordGatewayAccountConfig, ...] = ()
    environ: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    adapter: DiscordMessagingAdapter | None = None
    cli_runtime_factory: CliRuntimeFactory | None = None
    cli_binding_store: GatewayCliBindingStore | None = None
    cli_control: GatewayCliControlService | None = None
    default_cli_state_dir: str | None = None
    runtime_dependency_ensurer: Callable[..., object] | None = None
    respect_enabled: bool = True
    service_key: str = "discord"
    runtime_state_dir: Path | None = None
    _outbound_drain_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _outbound_drain_stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.account_configs:
            self.account_configs = load_discord_gateway_accounts(
                self.app,
                respect_enabled=self.respect_enabled,
                include_disabled=True,
            )
        if self.adapter is None:
            self.adapter = DiscordMessagingAdapter(app=self.app)
        if self.cli_control is None and self.app.loaded_profile is not None:
            config = load_gateway_cli_control_config(
                self.app.loaded_profile.manifest,
                adapter_key="discord",
                default_when_missing=True,
            )
            if config is not None:
                binding_store = self.cli_binding_store
                if binding_store is None:
                    state_root = self.app.state_dir
                    binding_path = (
                        None
                        if state_root is None
                        else os.path.join(state_root, "discord-cli-bindings.json")
                    )
                    binding_store = GatewayCliBindingStore(
                        path=None if binding_path is None else Path(binding_path)
                    )
                self.cli_control = GatewayCliControlService(
                    config=self._resolved_cli_control_config(config),
                    app=self.app,
                    runtime_factory=self.cli_runtime_factory,
                    binding_store=binding_store,
                    surface_label="Discord",
                    binding_subject="channel",
                    control_config_path="gateway.adapters.discord.control",
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

    def _enabled_account_configs(self) -> tuple[DiscordGatewayAccountConfig, ...]:
        return tuple(config for config in self.account_configs if config.enabled)

    def _transport_account_configs(self) -> tuple[DiscordGatewayAccountConfig, ...]:
        enabled_configs = self._enabled_account_configs()
        return enabled_configs if enabled_configs else self.account_configs

    def _describe_accounts(self) -> tuple[tuple[dict[str, object], ...], dict[str, object]]:
        accounts: list[dict[str, object]] = []
        configured_account_ids: list[str] = []
        enabled_account_ids: list[str] = []
        disabled_account_ids: list[str] = []
        runnable_account_ids: list[str] = []
        blocked_account_ids: list[str] = []
        for config in self.account_configs:
            configured_account_ids.append(config.account_id)
            credentials_status = "configured"
            credentials_error: str | None = None
            try:
                resolve_discord_account(config, environ=self.environ)
            except LookupError as exc:
                credentials_status = "missing_credentials"
                credentials_error = str(exc)
            if config.enabled:
                enabled_account_ids.append(config.account_id)
                if credentials_status == "configured":
                    runnable_account_ids.append(config.account_id)
                    startup_status = "ready"
                else:
                    blocked_account_ids.append(config.account_id)
                    startup_status = "blocked"
            else:
                disabled_account_ids.append(config.account_id)
                startup_status = "disabled"
            payload = {
                "account_id": config.account_id,
                "surface": config.surface,
                "enabled": config.enabled,
                "bot_token_env_var": config.bot_token_env_var,
                "credentials_status": credentials_status,
                "startup_status": startup_status,
                "allow_guild_ids": config.allow_guild_ids,
                "allow_channel_ids": config.allow_channel_ids,
                "runtime_metadata": dict(config.runtime_metadata),
            }
            if credentials_error is not None:
                payload["credentials_error"] = credentials_error
            accounts.append(payload)
        service_status = "unconfigured"
        if accounts:
            if not enabled_account_ids:
                service_status = "disabled"
            elif blocked_account_ids and runnable_account_ids:
                service_status = "degraded"
            elif blocked_account_ids:
                service_status = "blocked"
            else:
                service_status = "ready"
        return tuple(accounts), {
            "service_status": service_status,
            "configured_accounts": len(configured_account_ids),
            "enabled_accounts": len(enabled_account_ids),
            "disabled_accounts": len(disabled_account_ids),
            "runnable_accounts": len(runnable_account_ids),
            "blocked_accounts": len(blocked_account_ids),
            "configured_account_ids": tuple(configured_account_ids),
            "enabled_account_ids": tuple(enabled_account_ids),
            "disabled_account_ids": tuple(disabled_account_ids),
            "runnable_account_ids": tuple(runnable_account_ids),
            "blocked_account_ids": tuple(blocked_account_ids),
        }

    def describe(self) -> Mapping[str, object]:
        accounts, account_status = self._describe_accounts()
        configured_transport: str | None = None
        configured_transport_error: str | None = None
        try:
            configured_transport = self.configured_transport()
        except (LookupError, ValueError) as exc:
            configured_transport_error = str(exc)
        return {
            "adapter_id": self.adapter.adapter_id if self.adapter is not None else DISCORD_ADAPTER_ID,
            "profile_id": self.app.profile_id,
            "preferred_transport": "gateway",
            "implemented_transports": ("discord.py-gateway",),
            "configured_transport": configured_transport,
            "configured_transport_error": configured_transport_error,
            "sdk_dependency_status": _discord_py_dependency_status(),
            "required_intents": REQUIRED_DISCORD_INTENTS,
            "privileged_intents": PRIVILEGED_DISCORD_INTENTS,
            "mention_policy": "suppress-all",
            "accounts": accounts,
            "account_status": account_status,
            "control": self._describe_control(),
            "runtime": self._describe_runtime(
                configured_transport=configured_transport,
                configured_transport_error=configured_transport_error,
            ),
        }

    def _describe_runtime(
        self,
        *,
        configured_transport: str | None,
        configured_transport_error: str | None,
    ) -> Mapping[str, object]:
        payload: dict[str, object] = {
            "enabled": True,
            "runtime": "managed-service",
        }
        if configured_transport_error is not None:
            payload["runtime_status"] = "unavailable"
            payload["runtime_error"] = configured_transport_error
            return payload
        if configured_transport is None or self.runtime_state_dir is None:
            payload["runtime_status"] = "configured"
            if configured_transport is not None:
                payload["target"] = configured_transport
            return payload
        pid_path = default_gateway_runtime_path(
            self.runtime_state_dir,
            service_key=self.service_key,
            target=configured_transport,
            suffix="pid",
        )
        log_path = default_gateway_runtime_path(
            self.runtime_state_dir,
            service_key=self.service_key,
            target=configured_transport,
            suffix="log",
        )
        record_path = default_gateway_runtime_path(
            self.runtime_state_dir,
            service_key=self.service_key,
            target=configured_transport,
            suffix="runtime.json",
        )
        state = _managed_runtime_state(pid_path=pid_path, record_path=record_path)
        record = dict(state.get("record") or {})
        payload.update(
            {
                "target": configured_transport,
                "runtime_status": state["runtime_status"],
                "recorded_status": state["recorded_status"],
                "pid": state["pid"],
                "pid_active": bool(state["pid_active"]),
                "stale_pid_file": bool(state["stale_pid"]),
                "pid_file": str(pid_path),
                "log_file": str(log_path),
                "record_file": str(record_path),
                "started_at": _optional_text(record.get("started_at")),
                "stopped_at": _optional_text(record.get("stopped_at")),
                "last_exit_code": _coerce_int(record.get("last_exit_code")),
                "last_error": _optional_text(record.get("last_error")),
            }
        )
        return payload

    def _describe_control(self) -> Mapping[str, object]:
        if self.cli_control is None:
            return {
                "enabled": False,
                "runtime": "cli-runtime",
                "runtime_status": "disabled",
                "known_elephants": (),
            }
        return self.cli_control.describe()

    async def dispatch_event(
        self,
        payload: Mapping[str, object],
        *,
        account_id: str | None = None,
        transport: str = "gateway",
        delivery_transport: DiscordDeliveryTransport | None = None,
    ) -> DiscordGatewayEventResult:
        if self.adapter is None:
            raise RuntimeError("discord adapter is unavailable")
        account = self._match_account(account_id=account_id)
        if not self._payload_allowed(payload, account=account):
            return DiscordGatewayEventResult(
                exchange=None,
                response_body={
                    "ok": True,
                    "adapter_id": self.adapter.adapter_id,
                    "transport": transport,
                    "account_id": account.account_id,
                    "conversation_id": str(payload.get("channel_id") or ""),
                    "delivery_outcome": "ignored",
                    "summary": "ignored_by_allowlist",
                },
            )
        inbound = self.adapter.normalize_event(
            payload,
            account_id=account.account_id,
            transport=transport,
        )
        if self.cli_control is not None:
            control_result = self.cli_control.handle_message(inbound)
            if control_result.handled:
                return await self._dispatch_cli_control(
                    inbound,
                    result=control_result,
                    account=account,
                    transport=transport,
                    delivery_transport=delivery_transport,
                )
        exchange = self.app.handle_message(
            inbound,
            reply_to_message_id=inbound.reply_to_message_id or inbound.event_id,
            attachment_refs=inbound.attachment_refs,
            metadata={
                **dict(inbound.metadata),
                "delivery_surface": inbound.account.surface or f"discord-{transport}",
            },
        )
        response_body: dict[str, object] = {
            "ok": True,
            "adapter_id": self.adapter.adapter_id,
            "transport": transport,
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
            return DiscordGatewayEventResult(
                exchange=exchange,
                response_body=response_body,
            )
        if delivery_transport is None:
            raise RuntimeError("discord delivery transport is unavailable")
        delivery_request = self.adapter.build_reply_request(exchange.delivery.outbound)
        delivery_response = await delivery_transport.send_request(
            delivery_request,
            account=account,
        )
        response_body["external_message_id"] = self._external_message_id(delivery_response)
        return DiscordGatewayEventResult(
            exchange=exchange,
            response_body=response_body,
            delivery_request=delivery_request,
            delivery_response=delivery_response,
        )

    async def _dispatch_cli_control(
        self,
        inbound: GatewayInboundMessage,
        *,
        result,
        account: DiscordResolvedAccount,
        transport: str,
        delivery_transport: DiscordDeliveryTransport | None,
    ) -> DiscordGatewayEventResult:
        response_body: dict[str, object] = {
            "ok": True,
            "adapter_id": self.adapter.adapter_id if self.adapter is not None else DISCORD_ADAPTER_ID,
            "transport": transport,
            "account_id": inbound.account_id,
            "conversation_id": inbound.conversation_id,
            "control_mode": "cli-runtime",
            "delivery_outcome": "ignored" if result.body is None else "delivered",
            "summary": result.summary or "",
        }
        if result.elephant_id is not None:
            response_body["elephant_id"] = result.elephant_id
        if result.session_id is not None:
            response_body["session_id"] = result.session_id
        if result.body is None:
            return DiscordGatewayEventResult(exchange=None, response_body=response_body)
        if delivery_transport is None:
            raise RuntimeError("discord delivery transport is unavailable")
        assert self.adapter is not None
        outbound = self._build_control_outbound(inbound, body=result.body, session_id=result.session_id)
        delivery_request = self.adapter.build_reply_request(outbound)
        delivery_response = await delivery_transport.send_request(
            delivery_request,
            account=account,
        )
        response_body["external_message_id"] = self._external_message_id(delivery_response)
        return DiscordGatewayEventResult(
            exchange=None,
            response_body=response_body,
            delivery_request=delivery_request,
            delivery_response=delivery_response,
        )

    def _build_control_outbound(
        self,
        inbound: GatewayInboundMessage,
        *,
        body: str,
        session_id: str | None,
    ) -> GatewayOutboundMessage:
        return GatewayOutboundMessage(
            message_id=f"discord-control:{session_id or inbound.conversation_id}:{uuid4().hex[:12]}",
            account=inbound.account,
            conversation=inbound.conversation,
            session_id=session_id or f"control:{inbound.conversation_id}",
            body=body,
            reply_to_message_id=inbound.reply_to_message_id or inbound.event_id,
            attachment_refs=(),
            metadata={
                **dict(inbound.metadata),
                "delivery_surface": inbound.account.surface or "discord-control",
                "runtime_surface": "cli-runtime",
            },
        )

    def configured_transport(self) -> str:
        transport_configs = self._transport_account_configs()
        if not transport_configs:
            return "gateway"
        transports = tuple(
            dict.fromkeys(_normalize_transport(config.surface) for config in transport_configs)
        )
        if len(transports) == 1:
            return transports[0]
        raise LookupError(
            "configured Discord accounts use multiple transport surfaces; choose one explicitly"
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
            label=f"Discord {normalized_target} transport",
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
            "discord",
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
        self.runtime_dependency_ensurer(reason=f"Discord gateway {action}")

    def managed_runtime_log_hint(self, *, target: str) -> str:
        return "elephant gateway discord logs <account-id> --follow"

    async def start_gateway(
        self,
        *,
        account_id: str | None = None,
        discord_module: Any | None = None,
        client_factory: DiscordClientFactory = _default_discord_client_factory,
        delivery_transport_factory: DiscordDeliveryTransportFactory = _default_discord_delivery_transport_factory,
    ) -> tuple[object, ...]:
        discord = _load_discord_sdk(discord_module)
        accounts, blocked_accounts = self._resolved_accounts_for_start(account_id=account_id)
        if not accounts:
            if account_id is not None:
                raise LookupError(f"unknown or unrunnable Discord gateway account: {account_id}")
            if blocked_accounts:
                blocked_summary = "; ".join(
                    f"{account_label}: {error}" for account_label, error in blocked_accounts
                )
                raise LookupError(
                    "no enabled Discord gateway accounts are runnable; " + blocked_summary
                )
            raise LookupError("no enabled Discord gateway accounts are configured")
        for account_label, error in blocked_accounts:
            print(
                f"Skipping Discord account '{account_label}': {error}",
                file=os.sys.stderr,
            )
        # Kick off the shared-queue drain in a background thread so cron / CLI
        # 'message' rows land via this process's own REST send while the async
        # gateway loop runs. The thread exits when stop_outbound_drain is called.
        self.start_outbound_drain()
        try:
            results = await asyncio.gather(
                *(
                    self._start_gateway_account_supervised(
                        account,
                        discord_module=discord,
                        client_factory=client_factory,
                        delivery_transport_factory=delivery_transport_factory,
                    )
                    for account in accounts
                )
            )
        finally:
            self.stop_outbound_drain()
        clients = tuple(result for result in results if not isinstance(result, Exception))
        if clients:
            return clients
        first_error = next((result for result in results if isinstance(result, Exception)), None)
        if first_error is not None:
            raise RuntimeError(f"failed to start any Discord gateway accounts: {first_error}")
        return ()

    async def _start_gateway_account_supervised(
        self,
        account: DiscordResolvedAccount,
        *,
        discord_module: Any,
        client_factory: DiscordClientFactory,
        delivery_transport_factory: DiscordDeliveryTransportFactory,
    ) -> object | Exception:
        try:
            return await self._start_gateway_account(
                account,
                discord_module=discord_module,
                client_factory=client_factory,
                delivery_transport_factory=delivery_transport_factory,
            )
        except Exception as exc:
            print(
                f"Discord gateway account '{account.account_id}' stopped with error: {exc}",
                file=os.sys.stderr,
            )
            return exc

    async def _start_gateway_account(
        self,
        account: DiscordResolvedAccount,
        *,
        discord_module: Any,
        client_factory: DiscordClientFactory,
        delivery_transport_factory: DiscordDeliveryTransportFactory,
    ) -> object:
        client = client_factory(discord_module, _discord_intents(discord_module))
        delivery_transport = delivery_transport_factory(client, discord_module)
        queue: asyncio.Queue[Mapping[str, object] | None] = asyncio.Queue()
        worker = asyncio.create_task(
            self._drain_gateway_queue(
                queue,
                account=account,
                delivery_transport=delivery_transport,
            )
        )

        async def on_message(message: object) -> None:
            if self.should_ignore_sdk_message(
                message,
                self_user_id=self._client_self_user_id(client),
            ):
                return
            payload = self.sdk_message_payload(message)
            if not self._payload_allowed(payload, account=account):
                return
            await queue.put(payload)

        event = getattr(client, "event", None)
        if callable(event):
            event(on_message)
        else:
            setattr(client, "on_message", on_message)

        start = getattr(client, "start", None)
        if not callable(start):
            raise RuntimeError("discord gateway client does not expose start()")
        try:
            await _maybe_await(start(account.bot_token))
        finally:
            await queue.join()
            await queue.put(None)
            await worker
            close = getattr(client, "close", None)
            if callable(close):
                await _maybe_await(close())
        return client

    async def _drain_gateway_queue(
        self,
        queue: "asyncio.Queue[Mapping[str, object] | None]",
        *,
        account: DiscordResolvedAccount,
        delivery_transport: DiscordDeliveryTransport,
    ) -> None:
        while True:
            payload = await queue.get()
            try:
                if payload is None:
                    return
                await self.dispatch_event(
                    payload,
                    account_id=account.account_id,
                    transport="gateway",
                    delivery_transport=delivery_transport,
                )
            except Exception as exc:
                print(
                    f"Discord gateway dispatch failed for account '{account.account_id}': {exc}",
                    file=os.sys.stderr,
                )
            finally:
                queue.task_done()

    def sdk_message_payload(self, message: object) -> Mapping[str, object]:
        author = getattr(message, "author", None)
        if author is None or getattr(author, "id", None) is None:
            raise ValueError("discord SDK message requires an author with id")
        channel = getattr(message, "channel", None)
        if channel is None or getattr(channel, "id", None) is None:
            raise ValueError("discord SDK message requires a channel with id")
        guild = getattr(message, "guild", None)
        parent = getattr(channel, "parent", None)
        attachments = []
        for attachment in tuple(getattr(message, "attachments", ()) or ()):
            attachments.append(
                {
                    "id": str(getattr(attachment, "id", "")),
                    "filename": str(getattr(attachment, "filename", "")),
                    "content_type": str(getattr(attachment, "content_type", "")),
                    "url": str(getattr(attachment, "url", "")),
                }
            )
        payload: dict[str, object] = {
            "id": str(getattr(message, "id", "")),
            "channel_id": str(getattr(channel, "id", "")),
            "guild_id": (
                str(getattr(guild, "id", ""))
                if guild is not None and getattr(guild, "id", None) is not None
                else None
            ),
            "content": str(getattr(message, "content", "") or ""),
            "author": {
                "id": str(getattr(author, "id", "")),
                "username": str(getattr(author, "name", "") or getattr(author, "username", "")),
                "global_name": str(getattr(author, "global_name", "")),
                "bot": bool(getattr(author, "bot", False)),
            },
            "attachments": attachments,
        }
        nickname = getattr(author, "nick", None)
        if nickname is not None:
            payload["member"] = {"nick": str(nickname)}
        reference = getattr(message, "reference", None)
        if reference is not None and getattr(reference, "message_id", None) is not None:
            payload["message_reference"] = {
                "message_id": str(getattr(reference, "message_id")),
                "channel_id": str(getattr(reference, "channel_id", getattr(channel, "id", ""))),
                "guild_id": (
                    str(getattr(reference, "guild_id"))
                    if getattr(reference, "guild_id", None) is not None
                    else None
                ),
            }
        if parent is not None and getattr(parent, "id", None) is not None:
            payload["parent_id"] = str(getattr(parent, "id"))
            payload["thread_id"] = str(getattr(channel, "id"))
            payload["chat_type"] = "topic"
        elif guild is not None:
            payload["chat_type"] = "channel"
        else:
            payload["chat_type"] = "direct"
        return payload

    def should_ignore_sdk_message(self, message: object, *, self_user_id: str | None = None) -> bool:
        author = getattr(message, "author", None)
        if author is None:
            return True
        author_id = getattr(author, "id", None)
        if self_user_id is not None and author_id is not None and str(author_id) == str(self_user_id):
            return True
        if bool(getattr(author, "bot", False)):
            return True
        message_type = getattr(message, "type", None)
        if message_type is None:
            return False
        message_type_name = str(getattr(message_type, "name", message_type)).lower()
        return message_type_name not in {"default", "reply"}

    def _match_account(
        self,
        *,
        account_id: str | None = None,
    ) -> DiscordResolvedAccount:
        if not self.account_configs:
            raise LookupError("no Discord gateway accounts are configured")
        if account_id is not None:
            for config in self.account_configs:
                if config.account_id == account_id:
                    return resolve_discord_account(config, environ=self.environ)
            raise LookupError(f"unknown Discord gateway account: {account_id}")
        enabled_configs = self._enabled_account_configs()
        if not enabled_configs:
            raise LookupError("no enabled Discord gateway accounts are configured")
        if len(enabled_configs) == 1:
            return resolve_discord_account(enabled_configs[0], environ=self.environ)
        raise LookupError(
            "multiple enabled Discord gateway accounts are configured; pass account_id explicitly"
        )

    def _resolved_accounts_for_start(
        self,
        *,
        account_id: str | None = None,
    ) -> tuple[tuple[DiscordResolvedAccount, ...], tuple[tuple[str, str], ...]]:
        if account_id is not None:
            return ((self._match_account(account_id=account_id),), ())
        enabled_configs = self._enabled_account_configs()
        if not enabled_configs:
            return (), ()
        resolved: list[DiscordResolvedAccount] = []
        blocked: list[tuple[str, str]] = []
        for config in enabled_configs:
            try:
                resolved.append(resolve_discord_account(config, environ=self.environ))
            except LookupError as exc:
                blocked.append((config.account_id, str(exc)))
        return tuple(resolved), tuple(blocked)

    def _resolved_accounts(
        self,
        *,
        account_id: str | None = None,
    ) -> tuple[DiscordResolvedAccount, ...]:
        accounts, _ = self._resolved_accounts_for_start(account_id=account_id)
        return accounts

    def _payload_allowed(
        self,
        payload: Mapping[str, object],
        *,
        account: DiscordResolvedAccount,
    ) -> bool:
        guild_id = str(payload.get("guild_id") or "").strip()
        channel_id = str(payload.get("channel_id") or "").strip()
        parent_id = str(payload.get("parent_id") or "").strip()
        allowed_guild_ids = account.config.allow_guild_ids
        if guild_id and allowed_guild_ids and guild_id not in allowed_guild_ids:
            return False
        allowed_channel_ids = account.config.allow_channel_ids
        if allowed_channel_ids and channel_id not in allowed_channel_ids:
            if not parent_id or parent_id not in allowed_channel_ids:
                return False
        return True

    def _client_self_user_id(self, client: object) -> str | None:
        user = getattr(client, "user", None)
        if user is None or getattr(user, "id", None) is None:
            return None
        return str(getattr(user, "id"))

    def _external_message_id(self, response: Mapping[str, object]) -> str:
        return str(response.get("id") or "")

    def deliver_cron_result(self, job, execution) -> None:
        """Enqueue a cron execution result for delivery by the live discord gateway process.

        Like weixin and feishu, discord cron delivery is now decoupled from the scheduler:
        the scheduler writes a row to the shared outbound queue, and the live discord
        gateway process polls the queue and sends each row through the same REST send
        path a normal reply uses.
        """
        from packages.cron import CronJob, CronJobExecution

        if getattr(job, "action_kind", "") == "learning":
            return
        summary = str(getattr(execution, "summary", "") or "").strip()
        if not summary or summary == "[SILENT]":
            return
        identity_store = self.app.core.dependencies.identity_store
        records = resolve_cron_identity_records(
            identity_store=identity_store,
            adapter_id=DISCORD_ADAPTER_ID,
            elephant_id=job.elephant_id,
        )
        if not records:
            return
        record = records[0]
        self._outbound_queue().enqueue(
            adapter_id=DISCORD_ADAPTER_ID,
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

    def _outbound_queue(self) -> GatewayOutboundQueue:
        state_root = self.app.state_dir or self.runtime_state_dir
        if state_root is None:
            raise RuntimeError("cannot resolve state dir for discord outbound queue")
        return GatewayOutboundQueue(path=default_outbound_queue_path(state_root))

    def start_outbound_drain(self) -> threading.Thread:
        """Start the shared-queue drain worker if it is not already running."""
        if self._outbound_drain_thread is not None and self._outbound_drain_thread.is_alive():
            return self._outbound_drain_thread
        self._outbound_drain_stop.clear()
        queue = self._outbound_queue()
        self._outbound_drain_thread = run_outbound_drain_thread(
            queue=queue,
            adapter_id=DISCORD_ADAPTER_ID,
            sender=self._send_outbound_queue_row,
            is_running=lambda: not self._outbound_drain_stop.is_set(),
            logger=LOGGER,
            log_label=self.service_key,
        )
        return self._outbound_drain_thread

    def stop_outbound_drain(self) -> None:
        self._outbound_drain_stop.set()
        thread = self._outbound_drain_thread
        self._outbound_drain_thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)

    def _send_outbound_queue_row(self, row: GatewayOutboundRow) -> None:
        """Send one queued outbound row via the Discord REST API.

        Uses the same ``_discord_rest_send_message`` helper a cron direct-send used
        to call — the queue just adds durability/retry/ownership around it.
        """
        try:
            account = self._match_account(account_id=row.account_id)
        except LookupError as error:
            raise RuntimeError(
                f"cannot resolve discord account for queued row: {row.account_id}"
            ) from error
        _discord_rest_send_message(
            channel_id=row.conversation_id,
            content=row.body,
            bot_token=account.bot_token,
        )


def _discord_rest_send_message(
    *,
    channel_id: str,
    content: str,
    bot_token: str,
) -> None:
    """Send a message to a Discord channel using the REST API (sync, no discord.py needed)."""
    import json as _json
    from urllib.request import Request, urlopen

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    payload = _json.dumps({"content": content}).encode("utf-8")
    request = Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        response.read()
