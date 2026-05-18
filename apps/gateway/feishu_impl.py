"""Feishu gateway implementation assembled from support and store modules."""


from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
import importlib.util
import json
import logging
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
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
    default_outbound_queue_path,
    resolve_cron_identity_records,
    run_outbound_drain_thread,
)

from apps.provider_runtime import secret_reference_from_payload
from apps.runtime_layout import default_cli_state_dir
from packages.auth import AuthProfile, EnvironmentSecretStore, ProfileCredentialResolver, SecretReference
from packages.cron import CronJob, CronJobExecution

from .cli_control import (
    CliRuntimeFactory,
    FeishuCliBindingStore,
    FeishuCliControlService,
    load_feishu_cli_control_config,
)
from .plugins import GatewayManagedRuntime, GatewayPluginRegistry, default_gateway_runtime_path
from .runtime import (
    FEISHU_ADAPTER_ID,
    FeishuMessagingAdapter,
    GatewayApp,
    build_gateway_app,
)

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
DEFAULT_FEISHU_ASYNC_REQUEUE_DELAY_SECONDS = 0.01
DEFAULT_FEISHU_PLACEHOLDER_BODY = "已收到，正在处理中..."
DEFAULT_FEISHU_FAILURE_BODY = "处理失败，请稍后重试。"

HttpJsonRequester = Callable[[str, str, Mapping[str, object], Mapping[str, str]], Mapping[str, object]]
FeishuWSClientFactory = Callable[[Any, str, str, object, object | None], object]

from .feishu_accounts import *  # noqa: F401,F403
from .feishu_dispatch import FeishuDispatchMixin
from .feishu_stores import *  # noqa: F401,F403
from .feishu_support import *  # noqa: F401,F403

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class FeishuGatewayService(FeishuDispatchMixin):
    app: GatewayApp
    account_configs: tuple[FeishuGatewayAccountConfig, ...] = ()
    http_requester: HttpJsonRequester = _default_json_request
    environ: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    adapter: FeishuMessagingAdapter | None = None
    cli_runtime_factory: CliRuntimeFactory | None = None
    cli_binding_store: FeishuCliBindingStore | None = None
    cli_control: FeishuCliControlService | None = None
    inbound_event_store: FeishuInboundEventStore | None = None
    async_job_store: FeishuAsyncJobStore | None = None
    default_cli_state_dir: str | None = None
    runtime_dependency_ensurer: Callable[..., object] | None = None
    respect_enabled: bool = True
    service_key: str = "feishu"
    async_worker_count: int = DEFAULT_FEISHU_ASYNC_WORKER_COUNT
    async_placeholder_body: str = DEFAULT_FEISHU_PLACEHOLDER_BODY
    async_failure_body: str = DEFAULT_FEISHU_FAILURE_BODY
    _token_cache: dict[str, _FeishuTokenCacheEntry] = field(
        init=False,
        default_factory=dict,
        repr=False,
    )
    _async_queue: queue.Queue[str | None] = field(
        init=False,
        default_factory=queue.Queue,
        repr=False,
    )
    _async_workers_started: bool = field(default=False, init=False, repr=False)
    _async_workers: list[threading.Thread] = field(default_factory=list, init=False, repr=False)
    _async_stop_event: threading.Event = field(
        default_factory=threading.Event,
        init=False,
        repr=False,
    )
    _async_worker_lock: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
    )
    _async_schedule_lock: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
    )
    _outbound_drain_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _outbound_drain_stop: threading.Event = field(
        default_factory=threading.Event,
        init=False,
        repr=False,
    )
    _daemon_task: asyncio.Task | None = field(default=None, init=False, repr=False)
    _daemon_bridge_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _scheduled_job_keys: set[str] = field(default_factory=set, init=False, repr=False)
    _conversation_locks: dict[str, threading.Lock] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _conversation_locks_guard: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if not self.account_configs:
            self.account_configs = load_feishu_gateway_accounts(
                self.app,
                respect_enabled=self.respect_enabled,
            )
        if self.inbound_event_store is None:
            state_root = self.app.state_dir
            dedupe_path = (
                None
                if state_root is None
                else os.path.join(state_root, "feishu-inbound-events.json")
            )
            self.inbound_event_store = FeishuInboundEventStore(
                path=None if dedupe_path is None else Path(dedupe_path)
            )
        if self.async_job_store is None:
            state_root = self.app.state_dir
            async_jobs_path = (
                None if state_root is None else os.path.join(state_root, "feishu-async-jobs.json")
            )
            self.async_job_store = FeishuAsyncJobStore(
                path=None if async_jobs_path is None else Path(async_jobs_path)
            )
        if self.adapter is None:
            self.adapter = FeishuMessagingAdapter(app=self.app)
        if self.cli_control is None and self.app.loaded_profile is not None:
            config = load_feishu_cli_control_config(self.app.loaded_profile.manifest)
            if config is not None:
                binding_store = self.cli_binding_store
                if binding_store is None:
                    state_root = self.app.state_dir
                    binding_path = (
                        None
                        if state_root is None
                        else os.path.join(state_root, "feishu-cli-bindings.json")
                    )
                    binding_store = FeishuCliBindingStore(
                        path=None if binding_path is None else Path(binding_path)
                    )
                self.cli_control = FeishuCliControlService(
                    config=self._resolved_cli_control_config(config),
                    app=self.app,
                    runtime_factory=self.cli_runtime_factory,
                    binding_store=binding_store,
                )

    def _resolved_cli_control_config(self, config):
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

    def _async_summary(self) -> Mapping[str, object]:
        if self.async_job_store is None:
            return {
                "queue_depth": 0,
                "running_jobs": 0,
                "recent_failures": (),
            }
        return self.async_job_store.summary()

    def _ensure_async_workers(self) -> None:
        with self._async_worker_lock:
            if self._async_workers_started:
                return
            worker_count = max(int(self.async_worker_count or 0), 1)
            self._async_stop_event.clear()
            self._async_workers = []
            for index in range(worker_count):
                worker = threading.Thread(
                    target=self._async_worker_loop,
                    name=f"feishu-async-worker-{index + 1}",
                    daemon=True,
                )
                worker.start()
                self._async_workers.append(worker)
            self._async_workers_started = True
            self._recover_async_jobs()

    def shutdown_async_processing(self, *, timeout: float = 1.0) -> None:
        with self._async_worker_lock:
            if not self._async_workers_started:
                return
            self._async_stop_event.set()
            for _ in self._async_workers:
                self._async_queue.put(None)
            for worker in self._async_workers:
                worker.join(timeout=timeout)
            self._async_workers = []
            self._async_workers_started = False
            with self._async_schedule_lock:
                self._scheduled_job_keys.clear()

    def _recover_async_jobs(self) -> None:
        assert self.async_job_store is not None
        for job_key, _ in self.async_job_store.incomplete_records():
            self._schedule_async_job(job_key)

    def _schedule_async_job(self, job_key: str) -> bool:
        with self._async_schedule_lock:
            if job_key in self._scheduled_job_keys:
                return False
            self._scheduled_job_keys.add(job_key)
        self._async_queue.put(job_key)
        return True

    def _conversation_lock(self, account_id: str, conversation_id: str) -> threading.Lock:
        key = f"{account_id}:{conversation_id}"
        with self._conversation_locks_guard:
            lock = self._conversation_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._conversation_locks[key] = lock
            return lock

    def _async_worker_loop(self) -> None:
        while not self._async_stop_event.is_set():
            job_key = self._async_queue.get()
            if job_key is None:
                self._async_queue.task_done()
                break
            try:
                self._run_async_job(job_key)
            except Exception:
                LOGGER.exception("Feishu async worker crashed for job=%s", job_key)
            finally:
                with self._async_schedule_lock:
                    self._scheduled_job_keys.discard(job_key)
                self._async_queue.task_done()

    def _run_async_job(self, job_key: str) -> None:
        assert self.async_job_store is not None
        record = self.async_job_store.get(job_key)
        if record is None or record.status in {"completed", "failed"}:
            return
        try:
            account = self._match_account(record.payload, account_id=record.account_id)
            assert self.adapter is not None
            inbound = self.adapter.normalize_event(
                record.payload,
                account_id=record.account_id,
                transport=record.transport,
            )
        except Exception as exc:
            failure_summary = str(exc).strip() or exc.__class__.__name__
            LOGGER.exception(
                "Feishu async job could not be reconstructed for account=%s conversation=%s",
                record.account_id,
                record.conversation_id,
            )
            self.async_job_store.fail(
                job_key,
                failure_summary=failure_summary,
                response_body={
                    **self._base_response_body(transport=record.transport),
                    "account_id": record.account_id,
                    "conversation_id": record.conversation_id,
                    "delivery_outcome": "failed",
                    "async_job_status": "failed",
                    "summary": failure_summary,
                },
            )
            return
        if self.async_job_store.has_earlier_incomplete_for_conversation(job_key):
            if not self._async_stop_event.wait(DEFAULT_FEISHU_ASYNC_REQUEUE_DELAY_SECONDS):
                self._async_queue.put(job_key)
            return
        running_record = self.async_job_store.mark_running(job_key)
        if running_record is not None:
            record = running_record
        if not record.placeholder_sent and not inbound.sender.is_bot:
            try:
                self._send_placeholder_notice(job_key, account=account, inbound=inbound)
            except Exception:
                LOGGER.exception(
                    "Feishu async placeholder send failed for account=%s conversation=%s",
                    inbound.account_id,
                    inbound.conversation_id,
                )
        conversation_lock = self._conversation_lock(record.account_id, record.conversation_id)
        with conversation_lock:
            try:
                self.process_accepted_event(job_key, account=account, inbound=inbound)
            except Exception as exc:
                self._handle_async_job_failure(job_key, account=account, inbound=inbound, exc=exc)

    def _handle_async_job_failure(
        self,
        job_key: str,
        *,
        account: FeishuResolvedAccount,
        inbound: GatewayInboundMessage,
        exc: Exception,
    ) -> None:
        assert self.async_job_store is not None
        failure_summary = str(exc).strip() or exc.__class__.__name__
        LOGGER.exception(
            "Feishu async job failed for account=%s conversation=%s message=%s",
            inbound.account_id,
            inbound.conversation_id,
            inbound.event_id,
        )
        failure_response = {
            **self._base_response_body(transport="long-connection"),
            "account_id": inbound.account_id,
            "conversation_id": inbound.conversation_id,
            "delivery_outcome": "failed",
            "async_job_status": "failed",
            "summary": failure_summary,
        }
        try:
            self._send_failure_notice(account=account, inbound=inbound)
        except Exception:
            LOGGER.exception(
                "Feishu async failure notice send failed for account=%s conversation=%s",
                inbound.account_id,
                inbound.conversation_id,
            )
        self.async_job_store.fail(
            job_key,
            failure_summary=failure_summary,
            response_body=failure_response,
        )

    def _build_async_notice_outbound(
        self,
        inbound: GatewayInboundMessage,
        *,
        body: str,
        kind: str,
    ) -> GatewayOutboundMessage:
        return GatewayOutboundMessage(
            message_id=f"feishu-{kind}:{inbound.conversation_id}:{uuid4().hex[:12]}",
            account=inbound.account,
            conversation=inbound.conversation,
            session_id=f"{kind}:{inbound.conversation_id}",
            body=body,
            reply_to_message_id=inbound.event_id,
            attachment_refs=(),
            metadata={
                **dict(inbound.metadata),
                "delivery_surface": inbound.account.surface or f"feishu-{kind}",
                "runtime_surface": kind,
            },
        )

    def _send_placeholder_notice(
        self,
        job_key: str,
        *,
        account: FeishuResolvedAccount,
        inbound: GatewayInboundMessage,
    ) -> None:
        assert self.adapter is not None
        assert self.async_job_store is not None
        outbound = self._build_async_notice_outbound(
            inbound,
            body=self.async_placeholder_body,
            kind="async-placeholder",
        )
        delivery_request = self.adapter.build_reply_request(outbound)
        delivery_response = self._send_outbound(account, outbound, delivery_request)
        self.async_job_store.mark_placeholder_sent(
            job_key,
            placeholder_message_id=self._external_message_id(delivery_response),
        )

    def _send_failure_notice(
        self,
        *,
        account: FeishuResolvedAccount,
        inbound: GatewayInboundMessage,
    ) -> None:
        assert self.adapter is not None
        outbound = self._build_async_notice_outbound(
            inbound,
            body=self.async_failure_body,
            kind="async-failure",
        )
        delivery_request = self.adapter.build_reply_request(outbound)
        self._send_outbound(account, outbound, delivery_request)

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
        try:
            result = self.dispatch_event(payload, transport="webhook")
        except LookupError as exc:
            return "503 Service Unavailable", {"ok": False, "error": str(exc)}
        except ValueError as exc:
            return "400 Bad Request", {"ok": False, "error": str(exc)}
        except RuntimeError as exc:
            return "502 Bad Gateway", {"ok": False, "error": str(exc)}
        payload_body = dict(result.response_body)
        if result.delivery_request is not None:
            payload_body["delivery_request_path"] = result.delivery_request.get("path", "")
        return "200 OK", payload_body

    def has_credentials(self) -> bool:
        """Return True if at least one account can be resolved with current environment."""
        for config in self.account_configs:
            try:
                resolve_feishu_account(config, environ=self.environ)
                return True
            except (LookupError, RuntimeError):
                continue
        return False

    def describe(self) -> Mapping[str, object]:
        async_summary = self._async_summary()
        accounts: list[dict[str, object]] = []
        for config in self.account_configs:
            status = "configured"
            resolved_app_id: str | None = None
            try:
                resolved = resolve_feishu_account(config, environ=self.environ)
                resolved_app_id = resolved.app_id
            except LookupError:
                status = "missing_credentials"
            accounts.append(
                {
                    "account_id": config.account_id,
                    "surface": config.surface,
                    "event_path": config.event_path,
                    "app_id_env_var": config.app_id_env_var,
                    "app_secret_env_var": config.app_secret_env_var,
                    "credential_env_vars": _credential_env_vars(config),
                    "secret_reference_ids": tuple(
                        reference.reference_id for reference in config.secret_references
                    ),
                    "credentials_source": (
                        "secret_references" if config.secret_references else "environment"
                    ),
                    "credentials_status": status,
                    "resolved_app_id": resolved_app_id,
                }
            )
        configured_transport: str | None = None
        configured_transport_error: str | None = None
        try:
            configured_transport = self.configured_transport()
        except (LookupError, ValueError) as exc:
            configured_transport_error = str(exc)
        return {
            "adapter_id": FEISHU_ADAPTER_ID,
            "profile_id": self.app.profile_id,
            "preferred_transport": "long-connection",
            "implemented_transports": (
                "python-sdk-long-connection",
            ),
            "configured_transport": configured_transport,
            "configured_transport_error": configured_transport_error,
            "sdk_dependency_status": _lark_sdk_dependency_status(),
            "event_paths": self.event_paths,
            "accounts": tuple(accounts),
            "async_delivery_enabled": True,
            "queue_depth": async_summary.get("queue_depth", 0),
            "running_jobs": async_summary.get("running_jobs", 0),
            "worker_count": max(int(self.async_worker_count or 0), 1),
            "recent_failures": async_summary.get("recent_failures", ()),
            "control": (
                self.cli_control.describe()
                if self.cli_control is not None
                else {"enabled": True, "runtime": "cli-runtime", "runtime_status": "unavailable"}
            ),
        }

    def configured_transport(self) -> str:
        if not self.account_configs:
            return "long-connection"
        transports = tuple(
            dict.fromkeys(_normalize_transport(config.surface) for config in self.account_configs)
        )
        if len(transports) == 1:
            return transports[0]
        raise LookupError(
            "configured Feishu accounts use multiple transport surfaces; align their configured surfaces before starting the provider"
        )

    def configured_runtime_target(self) -> str:
        return self.configured_transport()

    def managed_runtime(
        self,
        *,
        args: Any,
        target: str,
    ) -> GatewayManagedRuntime:
        normalized_target = _normalize_configured_transport(target)
        state_dir = Path(args.state_dir)
        return GatewayManagedRuntime(
            service_key=self.service_key,
            runtime_id=f"{self.service_key}:{normalized_target}",
            target=normalized_target,
            label=f"Feishu {normalized_target} transport",
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
            "feishu",
            "start",
        ]
        if args.account_id:
            command.append(str(args.account_id))
        command.extend(
            [
                "--transport",
                _normalize_configured_transport(target),
                "--state-dir",
                str(args.state_dir),
                "--cli-state-dir",
                str(args.cli_state_dir),
                "--host",
                str(args.host),
                "--port",
                str(args.port),
            ]
        )
        return tuple(command)

    def prepare_managed_runtime(self, *, action: str, target: str) -> None:
        if _normalize_configured_transport(target) != "long-connection":
            return
        if self.runtime_dependency_ensurer is None:
            return
        self.runtime_dependency_ensurer(
            reason=f"Feishu long-connection {action}",
        )

    def managed_runtime_log_hint(self, *, target: str) -> str:
        return "elephant gateway feishu logs <account-id> --follow"

    def _match_account(
        self,
        payload: Mapping[str, object],
        *,
        account_id: str | None = None,
    ) -> FeishuResolvedAccount:
        if not self.account_configs:
            raise LookupError("no Feishu gateway accounts are configured")
        if account_id is not None:
            for config in self.account_configs:
                if config.account_id == account_id:
                    return resolve_feishu_account(config, environ=self.environ)
            raise LookupError(f"unknown Feishu gateway account: {account_id}")

        header_payload = _mapping(payload.get("header")) or {}
        event_app_id = str(header_payload.get("app_id") or "")
        if event_app_id:
            matches: list[FeishuResolvedAccount] = []
            for config in self.account_configs:
                try:
                    resolved = resolve_feishu_account(config, environ=self.environ)
                except LookupError:
                    continue
                if resolved.app_id == event_app_id:
                    matches.append(resolved)
            if len(matches) == 1:
                return matches[0]

        if len(self.account_configs) == 1:
            return resolve_feishu_account(self.account_configs[0], environ=self.environ)
        raise LookupError("could not match Feishu event to a configured gateway account")

    def _tenant_access_token(self, account: FeishuResolvedAccount) -> str:
        cached = self._token_cache.get(account.account_id)
        now = time.time()
        if cached is not None and cached.expires_at - 60 > now:
            return cached.token
        response = self.http_requester(
            "POST",
            f"{account.config.base_url}{account.config.token_path}",
            {
                "app_id": account.app_id,
                "app_secret": account.app_secret,
            },
            {},
        )
        token = str(response.get("tenant_access_token") or "")
        if not token:
            raise RuntimeError("feishu token response did not include tenant_access_token")
        expires_in = int(response.get("expire", 7200) or 7200)
        self._token_cache[account.account_id] = _FeishuTokenCacheEntry(
            token=token,
            expires_at=now + expires_in,
        )
        return token

    def deliver_cron_result(self, job: CronJob, execution: CronJobExecution) -> None:
        """Enqueue a cron execution result for delivery by the live feishu gateway process.

        Like weixin, feishu cron delivery is now decoupled from the scheduler: the
        scheduler writes a row to the shared outbound queue, and the live feishu
        gateway process (HTTP callback server or long-connection) polls the queue
        and sends each row through its own ``_send_outbound`` path — the same path
        a normal conversation reply travels. That means cron output and normal
        replies now use exactly one delivery implementation (token refresh, retry,
        account resolution all in one place).

        When a job was created without a bound elephant (``job.elephant_id is None``), we fall
        back to the sole feishu identity if exactly one is registered. See
        ``resolve_cron_identity_records``.
        """
        if job.action_kind == "learning":
            return
        summary = execution.summary.strip()
        if not summary or summary == "[SILENT]":
            return
        identity_store = self.app.core.dependencies.identity_store
        records = resolve_cron_identity_records(
            identity_store=identity_store,
            adapter_id=FEISHU_ADAPTER_ID,
            elephant_id=job.elephant_id,
        )
        if not records:
            if not job.elephant_id:
                # Only warn when we have Feishu identities but cannot disambiguate — if
                # there are zero Feishu identities, the scheduler's fan-out simply asked
                # the wrong adapter, which is expected noise.
                any_feishu = any(
                    r.key.adapter_id == FEISHU_ADAPTER_ID
                    for r in identity_store.list_records()
                )
                if any_feishu:
                    LOGGER.warning(
                        "cron delivery: skipping job=%s — no job.elephant_id and multiple feishu herd",
                        job.job_id,
                    )
            return
        record = records[0]
        queue = self._outbound_queue()
        queue.enqueue(
            adapter_id=FEISHU_ADAPTER_ID,
            account_id=record.key.account_id,
            conversation_id=record.key.conversation_id,
            body=execution.summary,
            metadata={
                "cron_job_id": job.job_id,
                "cron_job_name": job.name,
                "runtime_surface": "cron-scheduler",
                "enqueued_via": "deliver_cron_result",
                "feishu_session_id": record.session_id,
            },
        )

    def _outbound_queue(self) -> GatewayOutboundQueue:
        """Return the canonical outbound queue for this gateway state dir."""
        state_root = self.app.state_dir or self.runtime_state_dir or self._inferred_cli_state_dir()
        if state_root is None:
            raise RuntimeError("cannot resolve state dir for feishu outbound queue")
        return GatewayOutboundQueue(path=default_outbound_queue_path(state_root))

    def start_outbound_drain(self) -> threading.Thread:
        """Start the shared-queue drain worker if it is not already running.

        Exposed on the service so every feishu entry point (HTTP callback server,
        long-connection) can call it just before entering its primary blocking
        loop. Idempotent: if the thread is already alive, returns it unchanged.
        """
        if self._outbound_drain_thread is not None and self._outbound_drain_thread.is_alive():
            return self._outbound_drain_thread
        self._outbound_drain_stop.clear()
        queue = self._outbound_queue()
        self._outbound_drain_thread = run_outbound_drain_thread(
            queue=queue,
            adapter_id=FEISHU_ADAPTER_ID,
            sender=self._send_outbound_queue_row,
            is_running=lambda: not self._outbound_drain_stop.is_set(),
            logger=LOGGER,
            log_label=self.service_key,
        )
        return self._outbound_drain_thread

    def stop_outbound_drain(self) -> None:
        """Signal the drain and idle-proactive workers to exit on their next loop."""
        self._outbound_drain_stop.set()
        thread = self._outbound_drain_thread
        self._outbound_drain_thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)

    def _send_outbound_queue_row(self, row: GatewayOutboundRow) -> None:
        """Send one queued outbound row through the adapter's normal send path."""
        try:
            account = self._resolve_account_by_id(row.account_id)
        except LookupError as error:
            raise RuntimeError(
                f"cannot resolve feishu account for queued row: {row.account_id}"
            ) from error
        if self.adapter is None:
            self._ensure_runtime_dependencies()
        assert self.adapter is not None
        outbound = GatewayOutboundMessage(
            message_id=row.row_id,
            account=GatewayAccountRef(
                adapter_id=FEISHU_ADAPTER_ID,
                account_id=row.account_id,
                surface=account.config.surface,
            ),
            conversation=GatewayConversationRef(conversation_id=row.conversation_id),
            session_id=str(row.metadata.get("feishu_session_id") or f"outbound-queue:{row.row_id}"),
            body=row.body,
            metadata={
                **dict(row.metadata),
                "delivery_surface": str(row.metadata.get("delivery_surface") or account.config.surface or "feishu"),
                "queue_row_id": row.row_id,
                "queue_attempts": row.attempts,
            },
        )
        delivery_request = self.adapter.build_reply_request(outbound)
        self._send_outbound(account, outbound, delivery_request)

    def _resolve_account_by_id(self, account_id: str) -> "FeishuResolvedAccount":
        """Resolve a Feishu account by its account_id."""
        for config in self.account_configs:
            if config.account_id == account_id:
                return resolve_feishu_account(config, environ=self.environ)
        # Fall back to the single configured account if only one exists.
        if len(self.account_configs) == 1:
            return resolve_feishu_account(self.account_configs[0], environ=self.environ)
        raise LookupError(f"no Feishu account config for account_id={account_id}")

    def _send_outbound(
        self,
        account: FeishuResolvedAccount,
        outbound: GatewayOutboundMessage,
        delivery_request: Mapping[str, object],
    ) -> Mapping[str, object]:
        path = str(delivery_request.get("path") or "")
        method = str(delivery_request.get("method") or "POST")
        body = _mapping(delivery_request.get("body"))
        if not path or body is None:
            raise RuntimeError("feishu delivery request is missing a path or body payload")
        token = self._tenant_access_token(account)
        return self.http_requester(
            method,
            f"{account.config.base_url}{path}",
            body,
            {"Authorization": f"Bearer {token}"},
        )

    # ── DaemonService ──────────────────────────────────────────

    async def start_daemon_task(self, *, loop: Any) -> asyncio.Task | None:
        """Start Feishu gateway as a daemon task.

        Since lark.ws.Client.start() is synchronous and blocking, we run it
        in a bridge thread. The daemon task monitors the bridge thread's health.
        """
        import asyncio as _asyncio

        # Start the outbound drain thread (same as standalone mode)
        self.start_outbound_drain()

        # Start async workers for background processing
        self._ensure_async_workers()

        # Start long-connection in a bridge thread
        stop_event = threading.Event()

        def _run_long_connection() -> None:
            try:
                self.start_long_connection()
            except Exception as exc:
                LOGGER.error("[feishu] long-connection bridge thread failed: %s", exc)

        bridge = threading.Thread(
            target=_run_long_connection,
            name="feishu-long-connection-bridge",
            daemon=True,
        )
        bridge.start()
        self._daemon_bridge_thread = bridge

        # Return a monitoring task that watches the bridge thread
        async def _monitor() -> None:
            while bridge.is_alive() and not stop_event.is_set():
                await _asyncio.sleep(1.0)

        task = _asyncio.create_task(_monitor(), name="feishu-daemon-monitor")
        self._daemon_task = task
        return task

    async def stop_daemon_task(self) -> None:
        """Gracefully stop the Feishu daemon task."""
        self.stop_outbound_drain()
        self.shutdown_async_processing()

        if self._daemon_task is not None and not self._daemon_task.done():
            self._daemon_task.cancel()
            try:
                await self._daemon_task
            except asyncio.CancelledError:
                pass
        self._daemon_task = None

def register_feishu_gateway_service(registry: GatewayPluginRegistry) -> GatewayPluginRegistry:
    registry.register_service(
        "feishu",
        factory=lambda app, **kwargs: FeishuGatewayService(app=app, **kwargs),
        enabled_by_default=True,
    )
    return registry

def build_feishu_gateway_service(
    *,
    profile_id: str = "you",
    provider_profile: Mapping[str, Any] | None = None,
    state_dir: str | None = None,
    default_cli_state_dir: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    http_requester: HttpJsonRequester = _default_json_request,
    plugin_registry: GatewayPluginRegistry | None = None,
) -> FeishuGatewayService:
    app, _, _ = build_gateway_app(
        profile_id=profile_id,
        provider_profile=provider_profile,
        state_dir=state_dir,
        plugin_registry=plugin_registry,
    )
    return FeishuGatewayService(
        app=app,
        http_requester=http_requester,
        environ=dict(environ or os.environ),
        default_cli_state_dir=(
            None if default_cli_state_dir is None else str(Path(default_cli_state_dir))
        ),
    )

def create_gateway_web_app(service: FeishuGatewayService):
    return create_gateway_http_app(service, app=service.app)



__all__ = [
    "DEFAULT_FEISHU_APP_ID_ENV",
    "DEFAULT_FEISHU_APP_SECRET_ENV",
    "LEGACY_FEISHU_APP_ID_ENV",
    "LEGACY_FEISHU_APP_SECRET_ENV",
    "DEFAULT_FEISHU_EVENT_PATH",
    "DEFAULT_FEISHU_BASE_URL",
    "DEFAULT_FEISHU_TOKEN_PATH",
    "SUPPORTED_FEISHU_TRANSPORTS",
    "FeishuGatewayAccountConfig",
    "FeishuGatewayEventResult",
    "FeishuGatewayService",
    "FeishuResolvedAccount",
    "build_feishu_gateway_service",
    "create_gateway_web_app",
    "load_feishu_gateway_accounts",
    "register_feishu_gateway_service",
    "resolve_feishu_account",
]
