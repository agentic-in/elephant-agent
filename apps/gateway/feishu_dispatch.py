"""Dispatch and delivery mixin for the Feishu gateway service."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from packages.gateway_core import (
    GatewayExchange,
    GatewayInboundMessage,
    GatewayOutboundMessage,
)

from .feishu_accounts import FeishuResolvedAccount, _feishu_event_identifiers
from .feishu_stores import FeishuAsyncJobStore, FeishuInboundEventStore
from .feishu_support import (
    FeishuGatewayEventResult,
    FeishuWSClientFactory,
    _default_ws_client_factory,
    _lark_event_payload,
    _lark_log_level,
    _load_lark_sdk,
    _mapping,
    _normalize_transport,
    _optional_text,
)
from .runtime import FEISHU_ADAPTER_ID


class FeishuDispatchMixin:
    def accept_long_connection_event(
        self,
        payload: Mapping[str, object],
        *,
        account_id: str | None = None,
    ) -> FeishuGatewayEventResult:
        challenge = payload.get("challenge")
        if challenge is not None and payload.get("event") is None:
            return FeishuGatewayEventResult(
                exchange=None,
                response_body={"ok": True, "challenge": str(challenge)},
            )

        account = self._match_account(payload, account_id=account_id)
        transport = "long-connection"
        response_body = self._base_response_body(transport=transport)
        assert self.adapter is not None
        assert isinstance(self.async_job_store, FeishuAsyncJobStore)
        inbound = self.adapter.normalize_event(
            payload,
            account_id=account.account_id,
            transport=transport,
        )
        raw_event_id, raw_message_id = _feishu_event_identifiers(payload)
        job_key, record, created = self.async_job_store.create_or_get(
            account_id=inbound.account_id,
            conversation_id=inbound.conversation_id,
            event_id=raw_event_id or inbound.metadata.get("event_id") or inbound.event_id,
            message_id=raw_message_id or _optional_text(inbound.metadata.get("message_id")),
            payload=payload,
            transport=transport,
        )
        if not created:
            if record.status == "completed" and record.response_body is not None:
                return self._duplicate_event_result(
                    inbound,
                    transport=transport,
                    response_body=record.response_body,
                )
            if record.status == "failed":
                return self._failed_duplicate_event_result(
                    inbound,
                    transport=transport,
                    failure_summary=record.failure_summary,
                )
            self._ensure_async_workers()
            self._schedule_async_job(job_key)
            return self._async_duplicate_event_result(
                inbound,
                transport=transport,
                status=record.status,
            )
        self._ensure_async_workers()
        self._schedule_async_job(job_key)
        response_body.update(
            {
                "account_id": inbound.account_id,
                "conversation_id": inbound.conversation_id,
                "delivery_outcome": "queued",
                "async_job_status": "queued",
                "summary": "Feishu event accepted and queued for async processing.",
            }
        )
        return FeishuGatewayEventResult(exchange=None, response_body=response_body)

    def process_accepted_event(
        self,
        job_key: str,
        *,
        account: FeishuResolvedAccount | None = None,
        inbound: GatewayInboundMessage | None = None,
    ) -> FeishuGatewayEventResult:
        assert isinstance(self.async_job_store, FeishuAsyncJobStore)
        assert isinstance(self.inbound_event_store, FeishuInboundEventStore)
        record = self.async_job_store.get(job_key)
        if record is None:
            raise LookupError(f"unknown Feishu async job: {job_key}")
        if record.status == "completed" and record.response_body is not None:
            return FeishuGatewayEventResult(exchange=None, response_body=record.response_body)
        account = account or self._match_account(record.payload, account_id=record.account_id)
        assert self.adapter is not None
        inbound = inbound or self.adapter.normalize_event(
            record.payload,
            account_id=record.account_id,
            transport=record.transport,
        )
        response_body = self._base_response_body(transport=record.transport)
        if self.cli_control is not None:
            control_result = self.cli_control.handle_message(inbound)
            if control_result.handled:
                result = self._dispatch_cli_control(
                    inbound,
                    result=control_result,
                    account=account,
                    transport=record.transport,
                    response_body=response_body,
                )
            else:
                result = self._dispatch_shared_runtime(
                    inbound,
                    account=account,
                    transport=record.transport,
                    response_body=response_body,
                )
        else:
            result = self._dispatch_shared_runtime(
                inbound,
                account=account,
                transport=record.transport,
                response_body=response_body,
            )
        external_message_id = _optional_text(result.response_body.get("external_message_id"))
        self.async_job_store.complete(
            job_key,
            response_body=result.response_body,
            external_message_id=external_message_id,
        )
        self.inbound_event_store.commit(
            account_id=inbound.account_id,
            event_id=record.event_id or inbound.event_id,
            message_id=record.message_id or _optional_text(inbound.metadata.get("message_id")),
            response_body=result.response_body,
        )
        return result

    def dispatch_event(
        self,
        payload: Mapping[str, object],
        *,
        account_id: str | None = None,
        transport: str | None = None,
    ) -> FeishuGatewayEventResult:
        challenge = payload.get("challenge")
        if challenge is not None and payload.get("event") is None:
            return FeishuGatewayEventResult(
                exchange=None,
                response_body={"ok": True, "challenge": str(challenge)},
            )

        account = self._match_account(payload, account_id=account_id)
        resolved_transport = _normalize_transport(transport or account.config.surface)
        response_body = self._base_response_body(transport=resolved_transport)
        assert self.adapter is not None
        assert isinstance(self.inbound_event_store, FeishuInboundEventStore)
        inbound = self.adapter.normalize_event(
            payload,
            account_id=account.account_id,
            transport=resolved_transport,
        )
        raw_event_id, raw_message_id = _feishu_event_identifiers(payload)
        dedupe_status, prior_record = self.inbound_event_store.begin(
            account_id=inbound.account_id,
            event_id=raw_event_id or inbound.event_id,
            message_id=raw_message_id or _optional_text(inbound.metadata.get("message_id")),
        )
        if dedupe_status == "duplicate" and prior_record is not None:
            return self._duplicate_event_result(
                inbound,
                transport=resolved_transport,
                response_body=prior_record.response_body,
            )
        if dedupe_status == "inflight":
            return self._inflight_duplicate_event_result(
                inbound,
                transport=resolved_transport,
            )
        try:
            if self.cli_control is not None:
                control_result = self.cli_control.handle_message(inbound)
                if control_result.handled:
                    result = self._dispatch_cli_control(
                        inbound,
                        result=control_result,
                        account=account,
                        transport=resolved_transport,
                        response_body=response_body,
                    )
                else:
                    result = self._dispatch_shared_runtime(
                        inbound,
                        account=account,
                        transport=resolved_transport,
                        response_body=response_body,
                    )
            else:
                result = self._dispatch_shared_runtime(
                    inbound,
                    account=account,
                    transport=resolved_transport,
                    response_body=response_body,
                )
        except Exception:
            self.inbound_event_store.abort(
                account_id=inbound.account_id,
                event_id=raw_event_id or inbound.event_id,
                message_id=raw_message_id or _optional_text(inbound.metadata.get("message_id")),
            )
            raise
        self.inbound_event_store.commit(
            account_id=inbound.account_id,
            event_id=raw_event_id or inbound.event_id,
            message_id=raw_message_id or _optional_text(inbound.metadata.get("message_id")),
            response_body=result.response_body,
        )
        return result

    def _base_response_body(self, *, transport: str) -> dict[str, object]:
        return {
            "ok": True,
            "adapter_id": FEISHU_ADAPTER_ID,
            "transport": transport,
        }

    def _dispatch_cli_control(
        self,
        inbound: GatewayInboundMessage,
        *,
        result,
        account: FeishuResolvedAccount,
        transport: str,
        response_body: Mapping[str, object],
    ) -> FeishuGatewayEventResult:
        enriched_response = {
            **dict(response_body),
            "account_id": inbound.account_id,
            "conversation_id": inbound.conversation_id,
            "control_mode": "cli-runtime",
            "delivery_outcome": "ignored" if result.body is None else "delivered",
            "summary": result.summary or "",
        }
        if result.elephant_id is not None:
            enriched_response["elephant_id"] = result.elephant_id
        if result.session_id is not None:
            enriched_response["session_id"] = result.session_id
        if result.body is None:
            return FeishuGatewayEventResult(exchange=None, response_body=enriched_response)
        outbound = self._build_control_outbound(inbound, body=result.body, session_id=result.session_id)
        return self._deliver_outbound_result(
            account,
            outbound,
            exchange=None,
            response_body=enriched_response,
        )

    def _dispatch_shared_runtime(
        self,
        inbound: GatewayInboundMessage,
        *,
        account: FeishuResolvedAccount,
        transport: str,
        response_body: Mapping[str, object],
    ) -> FeishuGatewayEventResult:
        exchange = self.app.handle_message(
            inbound,
            reply_to_message_id=inbound.reply_to_message_id or inbound.event_id,
            attachment_refs=inbound.attachment_refs,
            metadata={
                **dict(inbound.metadata),
                "delivery_surface": inbound.account.surface or f"feishu-{transport}",
            },
        )
        enriched_response = {
            **dict(response_body),
            "account_id": exchange.route.inbound.account_id,
            "conversation_id": exchange.route.inbound.conversation_id,
            "session_id": exchange.route.session.session_id,
            "policy_decision": str(exchange.delivery.policy_result.decision),
            "delivery_outcome": exchange.delivery.outcome,
        }
        identity = getattr(exchange.route, "identity", None)
        if identity is not None and identity.state_id is not None:
            enriched_response["state_id"] = identity.state_id
        if identity is not None and identity.elephant_id is not None:
            enriched_response["elephant_id"] = identity.elephant_id
        if exchange.delivery.outbound is None:
            enriched_response["summary"] = exchange.delivery.summary
            return FeishuGatewayEventResult(exchange=exchange, response_body=enriched_response)
        return self._deliver_outbound_result(
            account,
            exchange.delivery.outbound,
            exchange=exchange,
            response_body=enriched_response,
        )

    def _deliver_outbound_result(
        self,
        account: FeishuResolvedAccount,
        outbound: GatewayOutboundMessage,
        *,
        exchange: GatewayExchange | None,
        response_body: Mapping[str, object],
    ) -> FeishuGatewayEventResult:
        assert self.adapter is not None
        delivery_request = self.adapter.build_reply_request(outbound)
        delivery_response = self._send_outbound(account, outbound, delivery_request)
        enriched_response = {
            **dict(response_body),
            "external_message_id": self._external_message_id(delivery_response),
        }
        return FeishuGatewayEventResult(
            exchange=exchange,
            response_body=enriched_response,
            delivery_request=delivery_request,
            delivery_response=delivery_response,
        )

    def _duplicate_event_result(
        self,
        inbound: GatewayInboundMessage,
        *,
        transport: str,
        response_body: Mapping[str, object],
    ) -> FeishuGatewayEventResult:
        duplicate_response = dict(response_body)
        previous_outcome = _optional_text(duplicate_response.get("delivery_outcome"))
        if previous_outcome is not None:
            duplicate_response["initial_delivery_outcome"] = previous_outcome
        duplicate_response["ok"] = True
        duplicate_response["adapter_id"] = FEISHU_ADAPTER_ID
        duplicate_response["transport"] = transport
        duplicate_response["account_id"] = inbound.account_id
        duplicate_response["conversation_id"] = inbound.conversation_id
        duplicate_response["delivery_outcome"] = "deduplicated"
        duplicate_response["duplicate_event"] = True
        duplicate_response["duplicate_handling"] = "replayed-no-delivery"
        duplicate_response["summary"] = "Duplicate Feishu event ignored; the original event was already processed."
        return FeishuGatewayEventResult(exchange=None, response_body=duplicate_response)

    def _inflight_duplicate_event_result(
        self,
        inbound: GatewayInboundMessage,
        *,
        transport: str,
    ) -> FeishuGatewayEventResult:
        response_body = self._base_response_body(transport=transport)
        response_body.update(
            {
                "account_id": inbound.account_id,
                "conversation_id": inbound.conversation_id,
                "delivery_outcome": "deduplicating",
                "duplicate_event": True,
                "duplicate_handling": "inflight",
                "summary": "Duplicate Feishu event is already being processed.",
            }
        )
        return FeishuGatewayEventResult(exchange=None, response_body=response_body)

    def _async_duplicate_event_result(
        self,
        inbound: GatewayInboundMessage,
        *,
        transport: str,
        status: str,
    ) -> FeishuGatewayEventResult:
        response_body = self._base_response_body(transport=transport)
        summary = {
            "queued": "Duplicate Feishu event is queued for async processing.",
            "running": "Duplicate Feishu event is already being processed asynchronously.",
        }.get(status, "Duplicate Feishu event is already being handled asynchronously.")
        delivery_outcome = "processing" if status == "running" else "queued"
        response_body.update(
            {
                "account_id": inbound.account_id,
                "conversation_id": inbound.conversation_id,
                "delivery_outcome": delivery_outcome,
                "async_job_status": status,
                "duplicate_event": True,
                "duplicate_handling": status,
                "summary": summary,
            }
        )
        return FeishuGatewayEventResult(exchange=None, response_body=response_body)

    def _failed_duplicate_event_result(
        self,
        inbound: GatewayInboundMessage,
        *,
        transport: str,
        failure_summary: str | None,
    ) -> FeishuGatewayEventResult:
        response_body = self._base_response_body(transport=transport)
        response_body.update(
            {
                "account_id": inbound.account_id,
                "conversation_id": inbound.conversation_id,
                "delivery_outcome": "failed",
                "async_job_status": "failed",
                "duplicate_event": True,
                "duplicate_handling": "failed",
                "summary": failure_summary or "Feishu event previously failed and will not auto-retry.",
            }
        )
        return FeishuGatewayEventResult(exchange=None, response_body=response_body)

    def _external_message_id(self, response: Mapping[str, object]) -> str:
        data = _mapping(response.get("data")) or {}
        return str(data.get("message_id") or "")

    def build_long_connection_client(
        self,
        *,
        account_id: str | None = None,
        lark_module: Any | None = None,
        client_factory: FeishuWSClientFactory = _default_ws_client_factory,
        log_level: str = "INFO",
    ) -> object:
        if account_id is None and len(self.account_configs) != 1:
            raise LookupError(
                "long-connection mode requires an explicit account id when multiple Feishu accounts are configured"
            )
        account = self._match_account({}, account_id=account_id)
        self._ensure_async_workers()
        lark = _load_lark_sdk(lark_module)
        handler = self._build_long_connection_handler(
            account=account,
            lark_module=lark,
            log_level=log_level,
        )
        return client_factory(
            lark,
            account.app_id,
            account.app_secret,
            handler,
            _lark_log_level(lark, log_level),
        )

    def start_long_connection(
        self,
        *,
        account_id: str | None = None,
        lark_module: Any | None = None,
        client_factory: FeishuWSClientFactory = _default_ws_client_factory,
        log_level: str = "INFO",
    ) -> object:
        client = self.build_long_connection_client(
            account_id=account_id,
            lark_module=lark_module,
            client_factory=client_factory,
            log_level=log_level,
        )
        start = getattr(client, "start", None)
        if not callable(start):
            raise RuntimeError("feishu long-connection client does not expose start()")
        start()
        return client

    def _build_control_outbound(
        self,
        inbound: GatewayInboundMessage,
        *,
        body: str,
        session_id: str | None,
    ) -> GatewayOutboundMessage:
        return GatewayOutboundMessage(
            message_id=f"feishu-control:{session_id or inbound.conversation_id}:{uuid4().hex[:12]}",
            account=inbound.account,
            conversation=inbound.conversation,
            session_id=session_id or f"control:{inbound.conversation_id}",
            body=body,
            reply_to_message_id=inbound.reply_to_message_id or inbound.event_id,
            attachment_refs=(),
            metadata={
                **dict(inbound.metadata),
                "delivery_surface": inbound.account.surface or "feishu-control",
                "runtime_surface": "cli-runtime",
            },
        )

    def _build_long_connection_handler(
        self,
        *,
        account: FeishuResolvedAccount,
        lark_module: Any,
        log_level: str,
    ) -> object:
        dispatcher = getattr(lark_module, "EventDispatcherHandler", None)
        if dispatcher is None or not hasattr(dispatcher, "builder"):
            raise RuntimeError("lark_oapi EventDispatcherHandler builder is unavailable")

        def _handle_message(event: object) -> None:
            payload = _lark_event_payload(event, lark_module=lark_module)
            self.accept_long_connection_event(
                payload,
                account_id=account.account_id,
            )

        builder = dispatcher.builder("", "", _lark_log_level(lark_module, log_level))
        builder = builder.register_p2_im_message_receive_v1(_handle_message)
        return builder.build()
