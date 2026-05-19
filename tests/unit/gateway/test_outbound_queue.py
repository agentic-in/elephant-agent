"""Tests for `GatewayOutboundQueue` — the cross-process cron → IM delivery pipe.

The queue exists so cron (a separate process) and the live gateway share one
delivery implementation. Key properties we test:

- enqueue → claim sees the row
- claim leaves the row visible as ``in_flight`` but excludes it from future claims
- complete removes the row
- release returns the row to ``pending`` with a backoff and an error message
- release dropped after ``max_attempts``
- adapter filtering only claims rows for the asked adapter
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from packages.gateway_core import GatewayOutboundQueue


def _utc(year: int = 2030, month: int = 1, day: int = 1, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


class GatewayOutboundQueueTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path("/tmp/test-outbound-queue")
        self.tmp.mkdir(parents=True, exist_ok=True)
        # Each test uses its own file so we don't cross-contaminate.
        self.path = self.tmp / f"queue-{self._testMethodName}.json"
        self.lock_path = self.tmp / f"queue-{self._testMethodName}.lock"
        if self.path.exists():
            self.path.unlink()
        if self.lock_path.exists():
            self.lock_path.unlink()
        self.queue = GatewayOutboundQueue(
            path=self.path,
            lock_path=self.lock_path,
            max_attempts=3,
            retry_delay_seconds=10.0,
        )

    def tearDown(self) -> None:
        if self.path.exists():
            self.path.unlink()
        if self.lock_path.exists():
            self.lock_path.unlink()

    def test_enqueue_then_claim_then_complete_empties_queue(self) -> None:
        row = self.queue.enqueue(
            adapter_id="messaging.weixin",
            account_id="acct",
            conversation_id="conv",
            body="hi",
            metadata={"cron_job_id": "cron:abc"},
        )
        self.assertEqual(row.status, "pending")
        self.assertEqual(row.attempts, 0)

        claimed = self.queue.claim(adapter_id="messaging.weixin")
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0].row_id, row.row_id)
        self.assertEqual(claimed[0].status, "in_flight")
        self.assertEqual(claimed[0].attempts, 1)

        # Second claim sees nothing because the row is in_flight.
        self.assertEqual(self.queue.claim(adapter_id="messaging.weixin"), ())

        self.queue.complete(row.row_id)
        self.assertEqual(self.queue.list_rows(), ())

    def test_claim_filters_by_adapter(self) -> None:
        self.queue.enqueue(
            adapter_id="messaging.weixin",
            account_id="a",
            conversation_id="c1",
            body="w",
        )
        self.queue.enqueue(
            adapter_id="messaging.feishu",
            account_id="a",
            conversation_id="c2",
            body="f",
        )

        weixin = self.queue.claim(adapter_id="messaging.weixin")
        self.assertEqual(len(weixin), 1)
        self.assertEqual(weixin[0].adapter_id, "messaging.weixin")

        feishu = self.queue.claim(adapter_id="messaging.feishu")
        self.assertEqual(len(feishu), 1)
        self.assertEqual(feishu[0].adapter_id, "messaging.feishu")

    def test_release_returns_row_to_pending_with_backoff(self) -> None:
        row = self.queue.enqueue(
            adapter_id="messaging.weixin",
            account_id="a",
            conversation_id="c",
            body="x",
        )
        self.queue.claim(adapter_id="messaging.weixin")
        released = self.queue.release(row.row_id, error="boom")
        self.assertIsNotNone(released)
        assert released is not None  # for mypy
        self.assertEqual(released.status, "pending")
        self.assertEqual(released.last_error, "boom")
        # Backoff prevents immediate re-claim.
        before_backoff = self.queue.claim(
            adapter_id="messaging.weixin",
            now=released.available_at - timedelta(seconds=1),
        )
        self.assertEqual(before_backoff, ())
        # After backoff elapses, the row is claimable again with incremented attempts.
        after_backoff = self.queue.claim(
            adapter_id="messaging.weixin",
            now=released.available_at + timedelta(seconds=1),
        )
        self.assertEqual(len(after_backoff), 1)
        self.assertEqual(after_backoff[0].attempts, 2)

    def test_release_drops_after_max_attempts(self) -> None:
        # max_attempts=3 in setUp — fail it 3 times and then release drops.
        row = self.queue.enqueue(
            adapter_id="messaging.weixin",
            account_id="a",
            conversation_id="c",
            body="x",
        )
        for expected_attempts in (1, 2, 3):
            claimed = self.queue.claim(
                adapter_id="messaging.weixin",
                now=_utc() + timedelta(seconds=expected_attempts * 20),
            )
            self.assertEqual(claimed[0].attempts, expected_attempts)
            released = self.queue.release(row.row_id, error=f"attempt {expected_attempts}")
            if expected_attempts < 3:
                self.assertIsNotNone(released)
            else:
                # Third failure: max_attempts reached, row should be dropped.
                self.assertIsNone(released)
        self.assertEqual(self.queue.list_rows(), ())

    def test_enqueue_survives_process_restart(self) -> None:
        self.queue.enqueue(
            adapter_id="messaging.weixin",
            account_id="a",
            conversation_id="c",
            body="hello",
            metadata={"cron_job_id": "cron:x"},
        )
        # Simulate a new process reading the same file.
        fresh = GatewayOutboundQueue(path=self.path, lock_path=self.lock_path)
        rows = fresh.list_rows(adapter_id="messaging.weixin")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].body, "hello")
        self.assertEqual(rows[0].metadata["cron_job_id"], "cron:x")


if __name__ == "__main__":
    unittest.main()
