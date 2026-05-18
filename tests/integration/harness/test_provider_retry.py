"""Integration tests for provider retry + SSE partial recovery (Phase 1)."""

from __future__ import annotations

from io import BytesIO
from typing import Any
import unittest
from unittest import mock
from urllib import error, request as urllib_request

from packages.models.providers.http import (
    JSONHTTPStreamChunk,
    ProviderHTTPError,
    ProviderSSEIncompleteError,
    UrllibJSONHTTPTransport,
)


def _http_error(
    status: int,
    *,
    body: bytes = b"",
    headers: dict | None = None,
    url: str = "http://provider",
) -> error.HTTPError:
    hdrs = headers or {}
    return error.HTTPError(url, status, "err", hdrs, BytesIO(body))


class _FakeResponse:
    """Minimal fill-in for urllib's response so _post_json_once parses OK."""

    def __init__(self, *, status: int, body: bytes, headers: dict | None = None, lines: list[bytes] | None = None):
        self.status = status
        self._body = body
        self._lines = lines or []
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body

    def __iter__(self):
        for line in self._lines:
            yield line


class ProviderRetryTest(unittest.TestCase):
    def test_post_json_retries_429_honouring_retry_after(self) -> None:
        transport = UrllibJSONHTTPTransport()
        attempts: list[int] = []
        sleeps: list[float] = []
        timeouts: list[float] = []

        def fake_urlopen(req, *, timeout):
            attempts.append(1)
            timeouts.append(timeout)
            if len(attempts) < 3:
                raise _http_error(429, headers={"Retry-After": "2"})
            return _FakeResponse(status=200, body=b'{"ok": true}', headers={"content-type": "application/json"})

        with mock.patch("time.sleep", side_effect=sleeps.append), mock.patch.object(
            urllib_request, "urlopen", side_effect=fake_urlopen
        ):
            response = transport.post_json(
                url="http://provider/v1/messages",
                headers={"Authorization": "Bearer x"},
                payload={"model": "stub"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.payload, {"ok": True})
        self.assertEqual(len(attempts), 3)
        # Retry-After: 2 pins each backoff to ~2s, overriding exponential backoff.
        self.assertEqual(len(sleeps), 2)
        for sleep_seconds in sleeps:
            self.assertAlmostEqual(sleep_seconds, 2.0, places=2)
        self.assertEqual(timeouts, [transport.timeout_seconds] * 3)

    def test_post_json_permanent_4xx_raises_provider_http_error(self) -> None:
        transport = UrllibJSONHTTPTransport()
        attempts: list[int] = []

        def fake_urlopen(req, *, timeout):
            attempts.append(1)
            raise _http_error(403, headers={}, body=b'{"error": "nope"}')

        with mock.patch("time.sleep"), mock.patch.object(
            urllib_request, "urlopen", side_effect=fake_urlopen
        ):
            with self.assertRaises(ProviderHTTPError) as ctx:
                transport.post_json(
                    url="http://provider/v1/messages",
                    headers={},
                    payload={},
                )
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(len(attempts), 1)

    def test_post_json_stream_retries_before_first_chunk(self) -> None:
        transport = UrllibJSONHTTPTransport()
        attempts: list[int] = []
        timeouts: list[float] = []

        stream_lines = [
            b"event: content_block_delta\n",
            b'data: {"delta": {"type": "text_delta", "text": "Hello "}}\n',
            b"\n",
            b'data: {"delta": {"type": "text_delta", "text": "world"}}\n',
            b"\n",
            b"data: [DONE]\n",
            b"\n",
        ]

        def fake_urlopen(req, *, timeout):
            attempts.append(1)
            timeouts.append(timeout)
            if len(attempts) < 2:
                # Connection refused before any bytes arrive -> retry path.
                raise error.URLError("connection refused")
            return _FakeResponse(status=200, body=b"", lines=stream_lines)

        chunks: list[JSONHTTPStreamChunk] = []
        with mock.patch("time.sleep"), mock.patch.object(
            urllib_request, "urlopen", side_effect=fake_urlopen
        ):
            for chunk in transport.post_json_stream(
                url="http://provider/v1/messages/stream",
                headers={},
                payload={},
            ):
                chunks.append(chunk)
        self.assertGreaterEqual(len(attempts), 2)
        self.assertEqual(timeouts, [transport.stream_timeout_seconds] * len(timeouts))
        texts = [chunk.payload.get("delta", {}).get("text", "") for chunk in chunks]
        self.assertEqual("".join(texts), "Hello world")

    def test_post_json_stream_mid_stream_disconnect_yields_partial(self) -> None:
        transport = UrllibJSONHTTPTransport()

        class _FlakyResponse(_FakeResponse):
            def __iter__(self):
                yield b"event: content_block_delta\n"
                yield b'data: {"delta": {"type": "text_delta", "text": "Half "}}\n'
                yield b"\n"
                yield b'data: {"delta": {"type": "text_delta", "text": "an answer"}}\n'
                yield b"\n"
                raise error.URLError("connection reset by peer")

        flaky = _FlakyResponse(status=200, body=b"")

        def fake_urlopen(req, *, timeout):
            return flaky

        chunks: list[JSONHTTPStreamChunk] = []
        with mock.patch("time.sleep"), mock.patch.object(
            urllib_request, "urlopen", side_effect=fake_urlopen
        ):
            with self.assertRaises(ProviderSSEIncompleteError) as ctx:
                for chunk in transport.post_json_stream(
                    url="http://provider/v1/messages/stream",
                    headers={},
                    payload={},
                ):
                    chunks.append(chunk)
        # Should have yielded both chunks before the disconnect.
        self.assertEqual(len(chunks), 2)
        self.assertEqual(ctx.exception.partial_text, "Half an answer")
        self.assertEqual(ctx.exception.kind, "sse_incomplete")


if __name__ == "__main__":
    unittest.main()
