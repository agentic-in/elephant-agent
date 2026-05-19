"""Inbound-event and async-job stores for the Feishu gateway."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4


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

from .feishu_support import *  # noqa: F401,F403


@dataclass(slots=True)
class FeishuInboundEventStore:
    path: Path | None = None
    retention_seconds: int = DEFAULT_FEISHU_INBOUND_EVENT_RETENTION_SECONDS
    max_records: int = DEFAULT_FEISHU_INBOUND_EVENT_MAX_RECORDS
    _records: dict[str, FeishuInboundEventRecord] = field(default_factory=dict, init=False, repr=False)
    _aliases: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    _inflight: set[str] = field(default_factory=set, init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    def __post_init__(self) -> None:
        with self._lock:
            self._records = self._load()
            self._prune()

    def begin(
        self,
        *,
        account_id: str,
        event_id: str | None,
        message_id: str | None,
    ) -> tuple[str, FeishuInboundEventRecord | None]:
        with self._lock:
            aliases = self._alias_keys(
                account_id=account_id,
                event_id=event_id,
                message_id=message_id,
            )
            self._prune()
            for alias in aliases:
                canonical_key = self._aliases.get(alias)
                if canonical_key is None:
                    continue
                record = self._records.get(canonical_key)
                if record is not None:
                    return "duplicate", record
            if any(alias in self._inflight for alias in aliases):
                return "inflight", None
            self._inflight.update(aliases)
            return "fresh", None

    def commit(
        self,
        *,
        account_id: str,
        event_id: str | None,
        message_id: str | None,
        response_body: Mapping[str, object],
    ) -> FeishuInboundEventRecord:
        with self._lock:
            aliases = self._alias_keys(
                account_id=account_id,
                event_id=event_id,
                message_id=message_id,
            )
            recorded_at = time.time()
            canonical_key = aliases[0] if aliases else f"{account_id}:unknown:{recorded_at:.6f}"
            record = FeishuInboundEventRecord(
                account_id=account_id,
                event_id=event_id,
                message_id=message_id,
                response_body=dict(response_body),
                recorded_at=recorded_at,
            )
            self._records[canonical_key] = record
            for alias in aliases:
                self._inflight.discard(alias)
            self._prune()
            self._persist()
            return record

    def abort(
        self,
        *,
        account_id: str,
        event_id: str | None,
        message_id: str | None,
    ) -> None:
        with self._lock:
            for alias in self._alias_keys(
                account_id=account_id,
                event_id=event_id,
                message_id=message_id,
            ):
                self._inflight.discard(alias)

    def _alias_keys(
        self,
        *,
        account_id: str,
        event_id: str | None,
        message_id: str | None,
    ) -> tuple[str, ...]:
        aliases: list[str] = []
        if message_id:
            aliases.append(f"{account_id}:message:{message_id}")
        if event_id:
            aliases.append(f"{account_id}:event:{event_id}")
        return tuple(dict.fromkeys(aliases))

    def _load(self) -> dict[str, FeishuInboundEventRecord]:
        if self.path is None or not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        items = payload.get("records")
        if not isinstance(items, list):
            return {}
        loaded: dict[str, FeishuInboundEventRecord] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            response_body = _mapping(item.get("response_body"))
            if response_body is None:
                continue
            account_id = _optional_text(item.get("account_id"))
            event_id = _optional_text(item.get("event_id"))
            message_id = _optional_text(item.get("message_id"))
            if account_id is None:
                continue
            aliases = self._alias_keys(
                account_id=account_id,
                event_id=event_id,
                message_id=message_id,
            )
            if not aliases:
                continue
            recorded_at = float(item.get("recorded_at") or 0.0)
            record = FeishuInboundEventRecord(
                account_id=account_id,
                event_id=event_id,
                message_id=message_id,
                response_body=dict(response_body),
                recorded_at=recorded_at,
            )
            loaded[aliases[0]] = record
        return loaded

    def _prune(self) -> None:
        cutoff = time.time() - max(self.retention_seconds, 0)
        kept = [(key, record) for key, record in self._records.items() if record.recorded_at >= cutoff]
        kept.sort(key=lambda item: item[1].recorded_at, reverse=True)
        if self.max_records > 0:
            kept = kept[: self.max_records]
        self._records = dict(kept)
        aliases: dict[str, str] = {}
        for canonical_key, record in self._records.items():
            for alias in self._alias_keys(
                account_id=record.account_id,
                event_id=record.event_id,
                message_id=record.message_id,
            ):
                aliases[alias] = canonical_key
        self._aliases = aliases

    def _persist(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "records": [
                {
                    "account_id": record.account_id,
                    "event_id": record.event_id,
                    "message_id": record.message_id,
                    "response_body": dict(record.response_body),
                    "recorded_at": record.recorded_at,
                }
                for _, record in sorted(
                    self._records.items(),
                    key=lambda item: item[1].recorded_at,
                    reverse=True,
                )
            ]
        }
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


@dataclass(frozen=True, slots=True)
class FeishuAsyncJobRecord:
    account_id: str
    conversation_id: str
    event_id: str | None
    message_id: str | None
    transport: str
    payload: Mapping[str, object]
    status: str
    placeholder_sent: bool
    placeholder_message_id: str | None
    response_body: Mapping[str, object] | None
    external_message_id: str | None
    failure_summary: str | None
    retry_count: int
    created_at: float
    updated_at: float
    started_at: float | None = None
    completed_at: float | None = None
    failed_at: float | None = None


@dataclass(slots=True)
class FeishuAsyncJobStore:
    path: Path | None = None
    retention_seconds: int = DEFAULT_FEISHU_ASYNC_JOB_RETENTION_SECONDS
    max_records: int = DEFAULT_FEISHU_ASYNC_JOB_MAX_RECORDS
    _records: dict[str, FeishuAsyncJobRecord] = field(default_factory=dict, init=False, repr=False)
    _aliases: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    def __post_init__(self) -> None:
        with self._lock:
            self._records = self._load()
            self._prune()

    def create_or_get(
        self,
        *,
        account_id: str,
        conversation_id: str,
        event_id: str | None,
        message_id: str | None,
        payload: Mapping[str, object],
        transport: str,
    ) -> tuple[str, FeishuAsyncJobRecord, bool]:
        with self._lock:
            aliases = self._alias_keys(
                account_id=account_id,
                event_id=event_id,
                message_id=message_id,
            )
            self._prune()
            for alias in aliases:
                canonical_key = self._aliases.get(alias)
                if canonical_key is None:
                    continue
                record = self._records.get(canonical_key)
                if record is not None:
                    return canonical_key, record, False
            now = time.time()
            canonical_key = aliases[0] if aliases else f"{account_id}:job:{uuid4().hex}"
            record = FeishuAsyncJobRecord(
                account_id=account_id,
                conversation_id=conversation_id,
                event_id=event_id,
                message_id=message_id,
                transport=transport,
                payload=dict(payload),
                status="queued",
                placeholder_sent=False,
                placeholder_message_id=None,
                response_body=None,
                external_message_id=None,
                failure_summary=None,
                retry_count=0,
                created_at=now,
                updated_at=now,
            )
            self._records[canonical_key] = record
            self._prune()
            self._persist()
            return canonical_key, record, True

    def get(self, key: str) -> FeishuAsyncJobRecord | None:
        with self._lock:
            self._prune()
            return self._records.get(key)

    def mark_running(self, key: str) -> FeishuAsyncJobRecord | None:
        with self._lock:
            record = self._records.get(key)
            if record is None:
                return None
            now = time.time()
            updated = replace(
                record,
                status="running",
                retry_count=record.retry_count + 1,
                started_at=now,
                updated_at=now,
                failed_at=None,
                failure_summary=None,
            )
            self._records[key] = updated
            self._prune()
            self._persist()
            return updated

    def has_earlier_incomplete_for_conversation(self, key: str) -> bool:
        with self._lock:
            record = self._records.get(key)
            if record is None:
                return False
            for other_key, other in self._records.items():
                if other_key == key:
                    continue
                if other.account_id != record.account_id or other.conversation_id != record.conversation_id:
                    continue
                if other.status in {"completed", "failed"}:
                    continue
                if other.created_at < record.created_at:
                    return True
                if other.created_at == record.created_at and other_key < key:
                    return True
            return False

    def mark_placeholder_sent(
        self,
        key: str,
        *,
        placeholder_message_id: str | None,
    ) -> FeishuAsyncJobRecord | None:
        with self._lock:
            record = self._records.get(key)
            if record is None:
                return None
            now = time.time()
            updated = replace(
                record,
                placeholder_sent=True,
                placeholder_message_id=placeholder_message_id,
                updated_at=now,
            )
            self._records[key] = updated
            self._prune()
            self._persist()
            return updated

    def complete(
        self,
        key: str,
        *,
        response_body: Mapping[str, object],
        external_message_id: str | None,
    ) -> FeishuAsyncJobRecord | None:
        with self._lock:
            record = self._records.get(key)
            if record is None:
                return None
            now = time.time()
            updated = replace(
                record,
                status="completed",
                response_body=dict(response_body),
                external_message_id=external_message_id,
                updated_at=now,
                completed_at=now,
                failed_at=None,
                failure_summary=None,
            )
            self._records[key] = updated
            self._prune()
            self._persist()
            return updated

    def fail(
        self,
        key: str,
        *,
        failure_summary: str,
        response_body: Mapping[str, object] | None = None,
    ) -> FeishuAsyncJobRecord | None:
        with self._lock:
            record = self._records.get(key)
            if record is None:
                return None
            now = time.time()
            updated = replace(
                record,
                status="failed",
                response_body=None if response_body is None else dict(response_body),
                failure_summary=failure_summary,
                external_message_id=None,
                updated_at=now,
                failed_at=now,
            )
            self._records[key] = updated
            self._prune()
            self._persist()
            return updated

    def incomplete_records(self) -> tuple[tuple[str, FeishuAsyncJobRecord], ...]:
        with self._lock:
            self._prune()
            items = [(key, record) for key, record in self._records.items() if record.status in {"queued", "running"}]
        items.sort(key=lambda item: (item[1].created_at, item[0]))
        return tuple(items)

    def summary(self, *, failure_limit: int = DEFAULT_FEISHU_ASYNC_FAILURE_HISTORY) -> Mapping[str, object]:
        with self._lock:
            self._prune()
            queue_depth = 0
            running_jobs = 0
            failures: list[dict[str, object]] = []
            for record in self._records.values():
                if record.status == "queued":
                    queue_depth += 1
                elif record.status == "running":
                    running_jobs += 1
                elif record.status == "failed":
                    failures.append(
                        {
                            "account_id": record.account_id,
                            "conversation_id": record.conversation_id,
                            "event_id": record.event_id,
                            "message_id": record.message_id,
                            "failure_summary": record.failure_summary,
                            "failed_at": record.failed_at,
                        }
                    )
        failures.sort(key=lambda item: float(item.get("failed_at") or 0.0), reverse=True)
        return {
            "queue_depth": queue_depth,
            "running_jobs": running_jobs,
            "recent_failures": tuple(failures[: max(failure_limit, 0)]),
        }

    def _alias_keys(
        self,
        *,
        account_id: str,
        event_id: str | None,
        message_id: str | None,
    ) -> tuple[str, ...]:
        aliases: list[str] = []
        if message_id:
            aliases.append(f"{account_id}:message:{message_id}")
        if event_id:
            aliases.append(f"{account_id}:event:{event_id}")
        return tuple(dict.fromkeys(aliases))

    def _load(self) -> dict[str, FeishuAsyncJobRecord]:
        if self.path is None or not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        items = payload.get("records")
        if not isinstance(items, list):
            return {}
        loaded: dict[str, FeishuAsyncJobRecord] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            payload_mapping = _mapping(item.get("payload"))
            account_id = _optional_text(item.get("account_id"))
            conversation_id = _optional_text(item.get("conversation_id"))
            transport = _optional_text(item.get("transport"))
            if payload_mapping is None or account_id is None or conversation_id is None or transport is None:
                continue
            event_id = _optional_text(item.get("event_id"))
            message_id = _optional_text(item.get("message_id"))
            aliases = self._alias_keys(
                account_id=account_id,
                event_id=event_id,
                message_id=message_id,
            )
            canonical_key = aliases[0] if aliases else _optional_text(item.get("canonical_key"))
            if canonical_key is None:
                continue
            response_body = _mapping(item.get("response_body"))
            loaded[canonical_key] = FeishuAsyncJobRecord(
                account_id=account_id,
                conversation_id=conversation_id,
                event_id=event_id,
                message_id=message_id,
                transport=transport,
                payload=dict(payload_mapping),
                status=str(item.get("status") or "queued"),
                placeholder_sent=bool(item.get("placeholder_sent", False)),
                placeholder_message_id=_optional_text(item.get("placeholder_message_id")),
                response_body=None if response_body is None else dict(response_body),
                external_message_id=_optional_text(item.get("external_message_id")),
                failure_summary=_optional_text(item.get("failure_summary")),
                retry_count=int(item.get("retry_count") or 0),
                created_at=float(item.get("created_at") or 0.0),
                updated_at=float(item.get("updated_at") or 0.0),
                started_at=(None if item.get("started_at") is None else float(item.get("started_at"))),
                completed_at=(None if item.get("completed_at") is None else float(item.get("completed_at"))),
                failed_at=(None if item.get("failed_at") is None else float(item.get("failed_at"))),
            )
        return loaded

    def _prune(self) -> None:
        cutoff = time.time() - max(self.retention_seconds, 0)
        kept = [(key, record) for key, record in self._records.items() if record.updated_at >= cutoff]
        kept.sort(key=lambda item: item[1].updated_at, reverse=True)
        if self.max_records > 0:
            kept = kept[: self.max_records]
        self._records = dict(kept)
        aliases: dict[str, str] = {}
        for canonical_key, record in self._records.items():
            for alias in self._alias_keys(
                account_id=record.account_id,
                event_id=record.event_id,
                message_id=record.message_id,
            ):
                aliases[alias] = canonical_key
        self._aliases = aliases

    def _persist(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "records": [
                {
                    "canonical_key": canonical_key,
                    "account_id": record.account_id,
                    "conversation_id": record.conversation_id,
                    "event_id": record.event_id,
                    "message_id": record.message_id,
                    "transport": record.transport,
                    "payload": dict(record.payload),
                    "status": record.status,
                    "placeholder_sent": record.placeholder_sent,
                    "placeholder_message_id": record.placeholder_message_id,
                    "response_body": (None if record.response_body is None else dict(record.response_body)),
                    "external_message_id": record.external_message_id,
                    "failure_summary": record.failure_summary,
                    "retry_count": record.retry_count,
                    "created_at": record.created_at,
                    "updated_at": record.updated_at,
                    "started_at": record.started_at,
                    "completed_at": record.completed_at,
                    "failed_at": record.failed_at,
                }
                for canonical_key, record in sorted(
                    self._records.items(),
                    key=lambda item: item[1].updated_at,
                    reverse=True,
                )
            ]
        }
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


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
    "FeishuInboundEventStore",
    "FeishuAsyncJobRecord",
    "FeishuAsyncJobStore",
]
