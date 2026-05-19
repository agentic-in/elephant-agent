"""Unit tests for the long-horizon retry policy."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
import unittest
from urllib import error as urllib_error

from packages.contracts.runtime import RetryState
from packages.harness.retry_policy import (
    RetryDecision,
    RetryPolicy,
    Retryable,
    classify_error,
    parse_retry_after,
    with_retry,
)


def _fixed_clock(start: datetime):
    current = {"now": start}

    def _clock() -> datetime:
        return current["now"]

    def _advance(seconds: float) -> None:
        current["now"] = current["now"] + timedelta(seconds=seconds)

    return _clock, _advance


def _http_error(status: int, *, headers: dict | None = None) -> urllib_error.HTTPError:
    return urllib_error.HTTPError("http://provider", status, "err", headers or {}, BytesIO(b""))


class ClassifyErrorTest(unittest.TestCase):
    def test_network_errors_classify_as_network(self) -> None:
        for exc in (
            ConnectionError("broken"),
            TimeoutError("slow"),
            urllib_error.URLError("dns"),
        ):
            self.assertEqual(classify_error(exc), "network", msg=str(exc))

    def test_http_429_separates_from_5xx(self) -> None:
        self.assertEqual(classify_error(_http_error(429)), "http_429")
        self.assertEqual(classify_error(_http_error(503)), "http_5xx")
        self.assertEqual(classify_error(_http_error(500)), "http_5xx")
        self.assertEqual(classify_error(_http_error(504)), "http_5xx")

    def test_http_permanent_4xx_not_retryable(self) -> None:
        self.assertEqual(classify_error(_http_error(400)), "http_4xx_permanent")
        self.assertEqual(classify_error(_http_error(401)), "http_4xx_permanent")
        self.assertEqual(classify_error(_http_error(403)), "http_4xx_permanent")
        self.assertEqual(classify_error(_http_error(404)), "http_4xx_permanent")

    def test_http_408_and_425_treated_as_retryable(self) -> None:
        self.assertEqual(classify_error(_http_error(408)), "http_5xx")
        self.assertEqual(classify_error(_http_error(425)), "http_5xx")

    def test_retryable_wrapper_carries_explicit_kind(self) -> None:
        self.assertEqual(classify_error(Retryable("x", kind="tool_transient")), "tool_transient")
        self.assertEqual(classify_error(Retryable("y", kind="sse_incomplete")), "sse_incomplete")

    def test_unknown_defaults(self) -> None:
        self.assertEqual(classify_error(ValueError("not a retry target")), "unknown")


class ParseRetryAfterTest(unittest.TestCase):
    def test_integer_seconds(self) -> None:
        self.assertEqual(parse_retry_after("5"), 5.0)
        self.assertEqual(parse_retry_after("0"), 0.0)
        self.assertEqual(parse_retry_after("0.5"), 0.5)

    def test_negative_clamps_to_zero(self) -> None:
        self.assertEqual(parse_retry_after("-5"), 0.0)

    def test_http_date_returns_delta(self) -> None:
        now = datetime(2026, 5, 3, 10, tzinfo=timezone.utc)
        # 60 seconds ahead
        delta = parse_retry_after("Sun, 03 May 2026 10:01:00 GMT", now=now)
        self.assertIsNotNone(delta)
        self.assertAlmostEqual(delta, 60.0, places=1)

    def test_http_date_in_the_past_clamps_to_zero(self) -> None:
        now = datetime(2026, 5, 3, 10, tzinfo=timezone.utc)
        delta = parse_retry_after("Sun, 03 May 2026 09:00:00 GMT", now=now)
        self.assertEqual(delta, 0.0)

    def test_empty_or_garbage(self) -> None:
        self.assertIsNone(parse_retry_after(None))
        self.assertIsNone(parse_retry_after(""))
        self.assertIsNone(parse_retry_after("totally bogus"))


class WithRetryTest(unittest.TestCase):
    def test_retries_then_succeeds_on_network_error(self) -> None:
        sleeps: list[float] = []
        attempts: list[int] = []

        def flaky() -> str:
            attempts.append(1)
            if len(attempts) < 3:
                raise ConnectionError("boom")
            return "ok"

        result = with_retry(
            flaky,
            policy=RetryPolicy(max_attempts=5, base_backoff_s=1.0, max_backoff_s=10.0, jitter_ratio=0),
            sleeper=sleeps.append,
        )
        self.assertEqual(result, "ok")
        self.assertEqual(len(attempts), 3)
        # Attempts 1 and 2 triggered backoffs of ~1s and ~2s respectively.
        self.assertEqual(len(sleeps), 2)
        self.assertAlmostEqual(sleeps[0], 1.0, places=2)
        self.assertAlmostEqual(sleeps[1], 2.0, places=2)

    def test_permanent_4xx_not_retried(self) -> None:
        attempts: list[int] = []

        def broken() -> None:
            attempts.append(1)
            raise _http_error(403)

        with self.assertRaises(urllib_error.HTTPError):
            with_retry(broken, policy=RetryPolicy(max_attempts=3), sleeper=lambda s: None)
        self.assertEqual(len(attempts), 1)

    def test_max_attempts_exhausted_raises(self) -> None:
        attempts: list[int] = []

        def always_bad() -> None:
            attempts.append(1)
            raise ConnectionError("always")

        with self.assertRaises(ConnectionError):
            with_retry(
                always_bad,
                policy=RetryPolicy(max_attempts=3, base_backoff_s=0, max_backoff_s=0, jitter_ratio=0),
                sleeper=lambda s: None,
            )
        self.assertEqual(len(attempts), 3)

    def test_retry_after_pinning_overrides_backoff(self) -> None:
        sleeps: list[float] = []
        attempts: list[int] = []

        class RateLimited(Exception):
            def __init__(self):
                super().__init__("rate limited")
                self.code = 429
                self.retry_after_s = 7.0

        def flaky() -> str:
            attempts.append(1)
            if len(attempts) < 2:
                raise RateLimited()
            return "ok"

        result = with_retry(
            flaky,
            policy=RetryPolicy(max_attempts=3, base_backoff_s=1.0, max_backoff_s=60.0, jitter_ratio=0),
            sleeper=sleeps.append,
        )
        self.assertEqual(result, "ok")
        self.assertAlmostEqual(sleeps[0], 7.0, places=2)

    def test_retry_after_header_string_respected(self) -> None:
        sleeps: list[float] = []
        attempts: list[int] = []

        def flaky():
            attempts.append(1)
            if len(attempts) < 2:
                raise _http_error(429, headers={"Retry-After": "4"})
            return "ok"

        result = with_retry(
            flaky,
            policy=RetryPolicy(max_attempts=3, base_backoff_s=1.0, max_backoff_s=60.0, jitter_ratio=0),
            sleeper=sleeps.append,
        )
        self.assertEqual(result, "ok")
        self.assertAlmostEqual(sleeps[0], 4.0, places=2)

    def test_on_retry_hook_receives_decision(self) -> None:
        decisions: list[RetryDecision] = []
        attempts: list[int] = []
        now = datetime(2026, 5, 3, 10, tzinfo=timezone.utc)
        clock, _advance = _fixed_clock(now)

        def flaky() -> str:
            attempts.append(1)
            if len(attempts) < 2:
                raise ConnectionError("once")
            return "ok"

        with_retry(
            flaky,
            policy=RetryPolicy(max_attempts=3, base_backoff_s=2.0, max_backoff_s=10.0, jitter_ratio=0),
            on_retry=decisions.append,
            sleeper=lambda s: None,
            clock=clock,
        )
        self.assertEqual(len(decisions), 1)
        d = decisions[0]
        self.assertEqual(d.kind, "network")
        self.assertAlmostEqual(d.sleep_seconds, 2.0, places=2)
        self.assertEqual(d.next_retry_at, now + timedelta(seconds=2))

    def test_deadline_aborts_before_another_attempt(self) -> None:
        attempts: list[int] = []
        now = datetime(2026, 5, 3, 10, tzinfo=timezone.utc)
        clock, advance = _fixed_clock(now)

        def sleeper(seconds: float) -> None:
            advance(seconds)

        def always_bad() -> None:
            attempts.append(1)
            raise ConnectionError("bad")

        with self.assertRaises(ConnectionError):
            with_retry(
                always_bad,
                policy=RetryPolicy(
                    max_attempts=10,
                    base_backoff_s=5.0,
                    max_backoff_s=60.0,
                    jitter_ratio=0,
                ),
                deadline=now + timedelta(seconds=3),
                sleeper=sleeper,
                clock=clock,
            )
        # first attempt at T+0, sleep clamped to remaining 3s would wake at T+3
        # but the next attempt's exception triggers a new backoff (10s, base*2)
        # and the remaining budget is 0, so the second exception re-raises.
        self.assertEqual(len(attempts), 2)

    def test_initial_state_continues_attempt_counter(self) -> None:
        attempts: list[int] = []

        def flaky() -> str:
            attempts.append(1)
            if len(attempts) < 2:
                raise ConnectionError("once more")
            return "ok"

        result = with_retry(
            flaky,
            policy=RetryPolicy(max_attempts=4, base_backoff_s=0.0, max_backoff_s=0.0, jitter_ratio=0),
            sleeper=lambda s: None,
            initial_state=RetryState(attempt=2, idempotency_key="loop:call:0"),
        )
        self.assertEqual(result, "ok")
        # attempt-1 fails, attempt-2 succeeds (wrapper starts at initial.attempt+1).
        self.assertEqual(len(attempts), 2)


if __name__ == "__main__":
    unittest.main()
