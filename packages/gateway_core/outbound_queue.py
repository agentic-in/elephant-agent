"""Cross-process outbound queue shared by cron scheduler and gateway adapters.

## Why this exists

Normal IM conversation replies travel inside a single gateway process: the live
adapter receives an inbound event, routes it through the kernel, and calls its own
``_send_ilink_message`` / ``build_reply_request`` / equivalent using the same
long-lived aiohttp session and authenticated token. The cron scheduler runs in a
**separate** process; it used to try to open its own aiohttp session and send
directly, which means every cron tick paid the cost of:

- re-doing token/credential resolution outside the adapter's resolver
- re-opening TLS/DNS from a process that may not share the gateway's keepalive
- silently racing the gateway's own token refresh / session-expired retries
- losing messages when the gateway is restarting (no retry semantics)

Instead, cron (and anything else that is "outside the IM process but wants to
speak through it") writes an outbound row to this on-disk queue, and the gateway
polls the queue during its normal event loop and calls its own send path — the
same code a user-reply would use. This way "internal caller → IM receiver" has
exactly one delivery implementation per adapter.

## Semantics

- JSON array on disk, written atomically.
- Rows identify the target adapter (``adapter_id``), the conversation, and the
  body. Everything else is free-form ``metadata`` for the adapter.
- A consumer calls ``claim(adapter_id)`` to pick up pending rows; that bumps the
  attempt count and marks them ``in_flight``.
- On success, the consumer calls ``complete(row_id)`` which removes the row.
- On failure, the consumer calls ``release(row_id, error)`` which returns the row
  to ``pending`` with an updated ``last_error`` and a short backoff.
- A row that exceeds ``max_attempts`` is dropped with its error recorded in the
  telemetry side-channel.

File format (minimal, no schema framework — parsed with plain json):

```json
[
  {
    "row_id": "outbound:abcdef",
    "adapter_id": "messaging.weixin",
    "account_id": "ed533afea8d0@im.bot",
    "conversation_id": "o9cq808bF5i4u98yTubqNrgwSP6k@im.wechat",
    "body": "hi",
    "metadata": {"cron_job_id": "cron:cf35d36050"},
    "status": "pending",
    "attempts": 0,
    "created_at": "2026-04-30T21:02:00+08:00",
    "available_at": "2026-04-30T21:02:00+08:00",
    "last_error": null
  }
]
```
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

try:
    import fcntl
except ModuleNotFoundError:  # pragma: no cover - Windows fallback
    fcntl = None


DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_RETRY_DELAY_SECONDS = 15.0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@dataclass(frozen=True, slots=True)
class GatewayOutboundRow:
    """One pending cross-process outbound message.

    Rows are adapter-agnostic: anything a gateway adapter needs to actually send
    goes into ``metadata``. Required fields only identify *where* the message
    needs to land.
    """

    row_id: str
    adapter_id: str
    account_id: str
    conversation_id: str
    body: str
    metadata: Mapping[str, Any]
    status: str  # pending | in_flight
    attempts: int
    created_at: datetime
    available_at: datetime
    last_error: str | None = None


@dataclass(slots=True)
class GatewayOutboundQueue:
    """File-backed queue shared by adapters across processes.

    Concurrency model: each mutating method acquires a POSIX flock on a sibling
    ``.lock`` file, so multiple writers (scheduler) and readers (gateway) can
    coexist. Non-POSIX platforms (Windows) degrade to best-effort semantics —
    the queue is intended for single-host setups anyway.
    """

    path: Path
    lock_path: Path | None = None
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        if self.lock_path is None:
            self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(
        self,
        *,
        adapter_id: str,
        account_id: str,
        conversation_id: str,
        body: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> GatewayOutboundRow:
        now = _utc_now()
        row = GatewayOutboundRow(
            row_id=f"outbound:{uuid4().hex[:12]}",
            adapter_id=str(adapter_id),
            account_id=str(account_id),
            conversation_id=str(conversation_id),
            body=str(body),
            metadata=dict(metadata or {}),
            status="pending",
            attempts=0,
            created_at=now,
            available_at=now,
        )
        with self._lock():
            rows = self._load_rows()
            rows.append(row)
            self._write_rows(rows)
        return row

    def claim(
        self,
        *,
        adapter_id: str,
        limit: int = 10,
        now: datetime | None = None,
    ) -> tuple[GatewayOutboundRow, ...]:
        """Atomically mark up to ``limit`` pending rows as ``in_flight``.

        Rows with ``available_at`` in the future (backoff) are skipped.
        """
        current = now or _utc_now()
        claimed: list[GatewayOutboundRow] = []
        with self._lock():
            rows = self._load_rows()
            changed = False
            for index, row in enumerate(rows):
                if len(claimed) >= limit:
                    break
                if row.adapter_id != adapter_id:
                    continue
                if row.status != "pending":
                    continue
                if row.available_at > current:
                    continue
                updated = replace(
                    row,
                    status="in_flight",
                    attempts=row.attempts + 1,
                )
                rows[index] = updated
                claimed.append(updated)
                changed = True
            if changed:
                self._write_rows(rows)
        return tuple(claimed)

    def complete(self, row_id: str) -> None:
        with self._lock():
            rows = self._load_rows()
            remaining = [row for row in rows if row.row_id != row_id]
            if len(remaining) != len(rows):
                self._write_rows(remaining)

    def release(self, row_id: str, *, error: str | None = None) -> GatewayOutboundRow | None:
        """Return an in-flight row to pending, or drop it if attempts exhausted.

        Returns the final state of the row (pending again, or ``None`` if dropped).
        """
        now = _utc_now()
        with self._lock():
            rows = self._load_rows()
            result: GatewayOutboundRow | None = None
            changed = False
            next_rows: list[GatewayOutboundRow] = []
            for row in rows:
                if row.row_id != row_id:
                    next_rows.append(row)
                    continue
                if row.attempts >= self.max_attempts:
                    # drop
                    changed = True
                    continue
                updated = replace(
                    row,
                    status="pending",
                    available_at=now + timedelta(seconds=self.retry_delay_seconds),
                    last_error=(error or row.last_error),
                )
                next_rows.append(updated)
                result = updated
                changed = True
            if changed:
                self._write_rows(next_rows)
            return result

    def list_rows(
        self,
        *,
        adapter_id: str | None = None,
    ) -> tuple[GatewayOutboundRow, ...]:
        with self._lock():
            rows = self._load_rows()
        if adapter_id is None:
            return tuple(rows)
        return tuple(row for row in rows if row.adapter_id == adapter_id)

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    def _load_rows(self) -> list[GatewayOutboundRow]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Corrupt or unreadable queue file — treat as empty. We do not
            # try to repair it here; the gateway operator can inspect it.
            return []
        if not isinstance(raw, list):
            return []
        rows: list[GatewayOutboundRow] = []
        for entry in raw:
            if not isinstance(entry, Mapping):
                continue
            try:
                rows.append(_row_from_payload(entry))
            except (KeyError, TypeError, ValueError):
                # Skip malformed rows but keep the rest.
                continue
        return rows

    def _write_rows(self, rows: list[GatewayOutboundRow]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps([_row_payload(row) for row in rows], indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp_path.replace(self.path)

    @contextmanager
    def _lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.lock_path.open("a+", encoding="utf-8")
        try:
            if fcntl is not None:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    try:
                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                    except OSError:
                        pass
        finally:
            stream.close()


def _row_payload(row: GatewayOutboundRow) -> dict[str, Any]:
    payload = asdict(row)
    payload["created_at"] = _iso(row.created_at)
    payload["available_at"] = _iso(row.available_at)
    payload["metadata"] = dict(row.metadata)
    return payload


def _row_from_payload(payload: Mapping[str, Any]) -> GatewayOutboundRow:
    created_at = _parse_datetime(str(payload.get("created_at") or "")) or _utc_now()
    available_at = _parse_datetime(str(payload.get("available_at") or "")) or created_at
    return GatewayOutboundRow(
        row_id=str(payload["row_id"]),
        adapter_id=str(payload["adapter_id"]),
        account_id=str(payload["account_id"]),
        conversation_id=str(payload["conversation_id"]),
        body=str(payload.get("body") or ""),
        metadata=dict(payload.get("metadata") or {}),
        status=str(payload.get("status") or "pending"),
        attempts=int(payload.get("attempts") or 0),
        created_at=created_at,
        available_at=available_at,
        last_error=(str(payload["last_error"]) if payload.get("last_error") not in (None, "") else None),
    )


__all__ = [
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_RETRY_DELAY_SECONDS",
    "GatewayOutboundQueue",
    "GatewayOutboundRow",
    "default_outbound_queue_path",
]


def default_outbound_queue_path(state_dir: Path | str) -> Path:
    """Canonical queue-file location for a given gateway state dir.

    Every adapter in every process must agree on this path or rows written by
    the scheduler (or the CLI ``message`` command) won't be visible to the
    gateway that actually sends them. Keeping the canonical path in one place
    stops that kind of drift.
    """
    return Path(state_dir) / "gateway-outbound-queue.json"
