from __future__ import annotations

import io
import ssl
import subprocess
import unittest
from unittest import mock
from urllib import error

from packages.models.providers.http import (
    DEFAULT_PROVIDER_HTTP_TIMEOUT_SECONDS,
    DEFAULT_PROVIDER_STREAM_HEARTBEAT_SECONDS,
    UrllibJSONHTTPTransport,
)


class UrllibJSONHTTPTransportFallbackTests(unittest.TestCase):
    def test_default_timeouts_bound_stalled_model_responses(self) -> None:
        transport = UrllibJSONHTTPTransport()

        self.assertEqual(
            transport.timeout_seconds, DEFAULT_PROVIDER_HTTP_TIMEOUT_SECONDS
        )
        self.assertEqual(transport.timeout_seconds, 120.0)
        self.assertEqual(
            transport.stream_timeout_seconds, DEFAULT_PROVIDER_STREAM_HEARTBEAT_SECONDS
        )
        self.assertEqual(transport.stream_timeout_seconds, 21_600.0)

    def test_html_http_errors_are_summarized_with_codex_reauth_hint(self) -> None:
        transport = UrllibJSONHTTPTransport()
        exc = error.HTTPError(
            url="https://chatgpt.com/backend-api/codex/v1/responses",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=io.BytesIO(
                b"<html><head><title>Forbidden</title></head><body><h1>Forbidden</h1><p>Access denied.</p></body></html>"
            ),
        )

        message = transport._error_message(
            exc, url="https://chatgpt.com/backend-api/codex/v1/responses"
        )
        exc.close()

        self.assertIn("provider request failed with status 403.", message)
        self.assertIn("HTML error page instead of JSON", message)
        self.assertIn("wrong Codex backend path", message)
        self.assertIn("/responses", message)
        self.assertNotIn("<html>", message)

    def test_retries_with_curl_on_tls_version_mismatch(self) -> None:
        transport = UrllibJSONHTTPTransport()
        completed = subprocess.CompletedProcess(
            args=["curl"],
            returncode=0,
            stdout=b'{"id":"chatcmpl-fallback","choices":[{"message":{"content":"ok"}}]}\n__ELEPHANT_STATUS__:200',
            stderr=b"",
        )
        with (
            mock.patch(
                "packages.models.providers.http.request.urlopen",
                side_effect=error.URLError(ssl.SSLError("WRONG_VERSION_NUMBER")),
            ),
            mock.patch(
                "packages.models.providers.http.shutil.which",
                return_value="/usr/bin/curl",
            ),
            mock.patch(
                "packages.models.providers.http.subprocess.run", return_value=completed
            ) as run,
        ):
            response = transport.post_json(
                url="https://example.test/v1/chat/completions",
                headers={"Authorization": "Bearer sk-test"},
                payload={
                    "model": "demo",
                    "messages": [{"role": "user", "content": "hello"}],
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.payload["id"], "chatcmpl-fallback")
        self.assertEqual(response.payload["choices"][0]["message"]["content"], "ok")
        command = run.call_args.args[0]
        self.assertIn("--write-out", command)
        self.assertIn("--max-time", command)
        self.assertEqual(command[command.index("--max-time") + 1], "120")
        self.assertIn("https://example.test/v1/chat/completions", command)

    def test_retries_with_curl_on_tls_unexpected_eof(self) -> None:
        transport = UrllibJSONHTTPTransport()

        self.assertTrue(
            transport._should_retry_with_curl(
                error.URLError(ssl.SSLError("UNEXPECTED_EOF_WHILE_READING"))
            )
        )

    def test_stream_retries_with_curl_on_tls_unexpected_eof(self) -> None:
        transport = UrllibJSONHTTPTransport()
        completed = subprocess.CompletedProcess(
            args=["curl"],
            returncode=0,
            stdout=(
                b"event: response.output_text.delta\n"
                b'data: {"delta":"hello"}\n\n'
                b"event: response.completed\n"
                b'data: {"response":{"id":"resp-fallback","output_text":"hello"}}\n\n'
                b"data: [DONE]\n\n"
                b"__ELEPHANT_STATUS__:200"
            ),
            stderr=b"",
        )
        with (
            mock.patch(
                "packages.models.providers.http.request.urlopen",
                side_effect=error.URLError(
                    ssl.SSLError("UNEXPECTED_EOF_WHILE_READING")
                ),
            ),
            mock.patch(
                "packages.models.providers.http.shutil.which",
                return_value="/usr/bin/curl",
            ),
            mock.patch(
                "packages.models.providers.http.subprocess.run", return_value=completed
            ) as run,
        ):
            chunks = tuple(
                transport.post_json_stream(
                    url="https://api.githubcopilot.com/v1/responses",
                    headers={"Authorization": "Bearer ghu-test"},
                    payload={"model": "gpt-5.4", "input": [], "stream": True},
                )
            )

        self.assertEqual(
            [chunk.event for chunk in chunks],
            ["response.output_text.delta", "response.completed"],
        )
        self.assertEqual(chunks[0].payload["delta"], "hello")
        command = run.call_args.args[0]
        self.assertIn("--write-out", command)
        self.assertIn("--max-time", command)
        self.assertEqual(command[command.index("--max-time") + 1], "21600")
        self.assertIn("https://api.githubcopilot.com/v1/responses", command)


if __name__ == "__main__":
    unittest.main()
