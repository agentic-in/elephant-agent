"""Shared JSON-over-HTTP execution helpers for provider adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html import unescape as html_unescape
import json
import re
import shutil
import subprocess
from typing import Any, Mapping, Protocol, runtime_checkable
from urllib import error, request

from packages.harness.retry_policy import RetryPolicy, Retryable, with_retry


DEFAULT_PROVIDER_HTTP_TIMEOUT_SECONDS = 120.0
DEFAULT_PROVIDER_HTTP_CONNECT_SECONDS = 15.0
DEFAULT_PROVIDER_STREAM_HEARTBEAT_SECONDS = 30.0
DEFAULT_PROVIDER_RETRY_POLICY = RetryPolicy(
    max_attempts=5,
    base_backoff_s=1.0,
    max_backoff_s=60.0,
    jitter_ratio=0.3,
    respect_retry_after=True,
)


class ProviderHTTPError(Exception):
    """HTTP failure from a provider call, annotated with status + headers.

    Raised instead of a plain ``RuntimeError`` so
    :func:`packages.harness.retry_policy.classify_error` can see the
    status code and ``Retry-After`` header.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        url: str | None = None,
        headers: Mapping[str, str] | None = None,
        retry_after_s: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = int(status_code)
        self.url = url
        self.headers: dict[str, str] = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
        self.retry_after_s = retry_after_s


class ProviderSSEIncompleteError(Retryable):
    """Raised after an SSE stream disconnects mid-response.

    The caller has already observed some chunks; ``partial_text`` carries
    the raw accumulated bytes so resume can re-inject them as an
    assistant prefix. The classification kind is ``sse_incomplete`` so
    the Loop parks with a network-class wait condition instead of
    retrying the generation in place.
    """

    def __init__(
        self,
        message: str,
        *,
        partial_text: str,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message, kind="sse_incomplete", cause=cause)
        self.partial_text = partial_text


@dataclass(frozen=True, slots=True)
class JSONHTTPResponse:
    status_code: int
    headers: Mapping[str, str]
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class JSONHTTPStreamChunk:
    event: str | None
    payload: Mapping[str, Any]


@runtime_checkable
class JSONHTTPTransport(Protocol):
    def post_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
    ) -> JSONHTTPResponse:
        """Send a JSON POST request and return the decoded JSON body."""

    def post_json_stream(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
    ):
        """Send a JSON POST request and yield decoded SSE payloads."""


def _text_for_partial(chunk: JSONHTTPStreamChunk) -> str:
    """Best-effort extract assistant text from a streaming chunk.

    Providers use different shapes: Anthropic puts tokens under
    ``delta.text`` inside ``content_block_delta`` events; OpenAI-
    compatible APIs put them under ``choices[0].delta.content``; Gemini
    uses ``candidates[0].content.parts[*].text``. We walk the known
    shapes and return "" when nothing matches, so partial accumulation
    is "additive best-effort" — never wrong for a provider we handle,
    merely empty for a provider we do not.
    """
    payload = chunk.payload or {}
    # Anthropic streaming: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "..."}}
    delta = payload.get("delta")
    if isinstance(delta, Mapping):
        text = delta.get("text")
        if isinstance(text, str):
            return text
    # OpenAI-compatible chat: {"choices": [{"delta": {"content": "..."}}]}
    choices = payload.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, Mapping):
                continue
            choice_delta = choice.get("delta")
            if isinstance(choice_delta, Mapping):
                content = choice_delta.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts: list[str] = []
                    for item in content:
                        if isinstance(item, Mapping) and isinstance(item.get("text"), str):
                            parts.append(item["text"])
                    if parts:
                        return "".join(parts)
    # Gemini v1beta: {"candidates": [{"content": {"parts": [{"text": "..."}]}}]}
    candidates = payload.get("candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            content = candidate.get("content")
            if isinstance(content, Mapping):
                parts = content.get("parts")
                if isinstance(parts, list):
                    texts: list[str] = []
                    for part in parts:
                        if isinstance(part, Mapping) and isinstance(part.get("text"), str):
                            texts.append(part["text"])
                    if texts:
                        return "".join(texts)
    return ""


class UrllibJSONHTTPTransport:
    """Standard-library JSON transport for deterministic local and live use."""

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_PROVIDER_HTTP_TIMEOUT_SECONDS,
        stream_timeout_seconds: float = DEFAULT_PROVIDER_STREAM_HEARTBEAT_SECONDS,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.stream_timeout_seconds = max(1.0, float(stream_timeout_seconds))
        self.retry_policy = retry_policy or DEFAULT_PROVIDER_RETRY_POLICY

    def _deadline(self, *, timeout_seconds: float) -> datetime:
        return datetime.now(timezone.utc) + timedelta(seconds=max(1.0, float(timeout_seconds)))

    def post_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
    ) -> JSONHTTPResponse:
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        request_headers = dict(headers)
        request_headers.setdefault("Content-Type", "application/json")

        def _attempt() -> JSONHTTPResponse:
            return self._post_json_once(url=url, headers=request_headers, body=body)

        return with_retry(
            _attempt,
            policy=self.retry_policy,
            deadline=self._deadline(timeout_seconds=self.timeout_seconds),
        )

    def _post_json_once(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> JSONHTTPResponse:
        http_request = request.Request(
            url,
            data=body,
            headers=dict(headers),
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                raw_body = response.read().decode("utf-8")
                parsed = json.loads(raw_body) if raw_body else {}
                if not isinstance(parsed, dict):
                    raise RuntimeError("provider response must be a JSON object")
                return JSONHTTPResponse(
                    status_code=response.status,
                    headers={str(key).lower(): str(value) for key, value in response.headers.items()},
                    payload=parsed,
                )
        except error.HTTPError as exc:  # pragma: no cover - exercised by callers
            raise self._provider_http_error(exc, url=url) from exc
        except error.URLError as exc:  # pragma: no cover - exercised by callers
            if self._should_retry_with_curl(exc):
                return self._post_json_with_curl(
                    url=url,
                    headers=dict(headers),
                    body=body,
                )
            raise ConnectionError(f"provider request failed for {url}: {exc.reason}") from exc

    def _provider_http_error(self, exc: error.HTTPError, *, url: str | None = None) -> ProviderHTTPError:
        try:
            body = exc.read().decode("utf-8", errors="replace").strip()
        except Exception:  # pragma: no cover - defensive fallback
            body = ""
        headers_obj = getattr(exc, "headers", None)
        headers_dict: dict[str, str] = {}
        retry_after_s: float | None = None
        if headers_obj is not None:
            for raw_key, raw_value in headers_obj.items():
                headers_dict[str(raw_key).lower()] = str(raw_value)
            retry_after_raw = headers_dict.get("retry-after")
            if retry_after_raw is not None:
                from packages.harness.retry_policy import parse_retry_after
                retry_after_s = parse_retry_after(retry_after_raw)
        message = self._status_error_message(
            status_code=int(exc.code),
            body=body,
            url=url or getattr(exc, "url", None),
        )
        return ProviderHTTPError(
            message,
            status_code=int(exc.code),
            url=url or getattr(exc, "url", None),
            headers=headers_dict,
            retry_after_s=retry_after_s,
        )

    def _error_message(self, exc: error.HTTPError, *, url: str | None = None) -> str:
        try:
            body = exc.read().decode("utf-8", errors="replace").strip()
        except Exception:  # pragma: no cover - defensive fallback
            body = ""
        return self._status_error_message(
            status_code=int(exc.code),
            body=body,
            url=url or getattr(exc, "url", None),
        )

    def _status_error_message(
        self,
        *,
        status_code: int,
        body: str,
        url: str | None = None,
    ) -> str:
        detail = self._summarize_error_body(body)
        hint = self._provider_error_hint(status_code=status_code, url=url)
        parts = [f"provider request failed with status {status_code}."]
        if detail:
            parts.append(detail)
        if hint:
            parts.append(hint)
        return " ".join(part.strip() for part in parts if part.strip()).strip()

    def _summarize_error_body(self, body: str) -> str:
        trimmed = body.strip()
        if not trimmed:
            return ""
        try:
            parsed = json.loads(trimmed)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, Mapping):
            for path in (
                ("error", "message"),
                ("message",),
                ("error",),
                ("detail",),
            ):
                value: Any = parsed
                for key in path:
                    if not isinstance(value, Mapping):
                        value = None
                        break
                    value = value.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()[:200]
        lowered = trimmed.lower()
        if "<html" in lowered or "<body" in lowered:
            without_scripts = re.sub(r"(?is)<(script|style)\b.*?>.*?</\1>", " ", trimmed)
            text = re.sub(r"(?is)<[^>]+>", " ", without_scripts)
            text = re.sub(r"\s+", " ", html_unescape(text)).strip()
            if text:
                return f"Upstream returned an HTML error page instead of JSON: {text[:160]}"
            return "Upstream returned an HTML error page instead of JSON."
        return trimmed[:200]

    def _provider_error_hint(self, *, status_code: int, url: str | None) -> str:
        if status_code not in {401, 403}:
            return ""
        normalized_url = str(url or "").strip().lower()
        if "chatgpt.com/backend-api/codex" in normalized_url:
            return (
                "For openai-codex this can mean the session token is invalid, or that Elephant Agent is hitting the "
                "wrong Codex backend path. Verify the provider is using `/responses` on `chatgpt.com/backend-api/codex`, "
                "then re-authenticate Codex only if the endpoint is already correct."
            )
        return ""

    def _should_retry_with_curl(self, exc: error.URLError) -> bool:
        reason_text = str(exc.reason)
        retryable_tls_fragments = (
            "WRONG_VERSION_NUMBER",
            "UNEXPECTED_EOF_WHILE_READING",
        )
        return any(fragment in reason_text for fragment in retryable_tls_fragments)

    def _post_json_with_curl(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> JSONHTTPResponse:
        curl = shutil.which("curl")
        if curl is None:
            raise RuntimeError(
                f"provider request failed for {url}: curl is unavailable for TLS fallback"
            )
        status_marker = "__ELEPHANT_STATUS__:"
        max_time = max(1, int(round(self.timeout_seconds)))
        connect_timeout = max(1, min(10, max_time))
        command = [
            curl,
            "--silent",
            "--show-error",
            "--location",
            "--connect-timeout",
            str(connect_timeout),
            "--max-time",
            str(max_time),
            "--request",
            "POST",
            url,
            "--data-binary",
            "@-",
            "--write-out",
            f"\n{status_marker}%{{http_code}}",
        ]
        for key, value in headers.items():
            command.extend(["--header", f"{key}: {value}"])
        result = subprocess.run(
            command,
            input=body,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"provider request failed for {url}: {stderr or 'curl fallback failed'}")
        raw_output = result.stdout.decode("utf-8", errors="replace")
        raw_body, separator, raw_status = raw_output.rpartition(f"\n{status_marker}")
        if not separator:
            raise RuntimeError(f"provider request failed for {url}: curl fallback missing status marker")
        try:
            status_code = int(raw_status.strip())
        except ValueError as exc:  # pragma: no cover - defensive fallback
            raise RuntimeError(f"provider request failed for {url}: invalid curl status marker") from exc
        payload = json.loads(raw_body) if raw_body else {}
        if not isinstance(payload, dict):
            raise RuntimeError("provider response must be a JSON object")
        if status_code >= 400:
            raise RuntimeError(
                self._status_error_message(
                    status_code=status_code,
                    body=raw_body,
                    url=url,
                )
            )
        return JSONHTTPResponse(
            status_code=status_code,
            headers={},
            payload=payload,
        )

    def _post_json_stream_with_curl(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
    ):
        curl = shutil.which("curl")
        if curl is None:
            raise RuntimeError(
                f"provider request failed for {url}: curl is unavailable for TLS fallback"
            )
        status_marker = "__ELEPHANT_STATUS__:"
        max_time = max(1, int(round(self.stream_timeout_seconds)))
        connect_timeout = max(1, min(10, max_time))
        command = [
            curl,
            "--silent",
            "--show-error",
            "--location",
            "--connect-timeout",
            str(connect_timeout),
            "--max-time",
            str(max_time),
            "--request",
            "POST",
            url,
            "--data-binary",
            "@-",
            "--write-out",
            f"\n{status_marker}%{{http_code}}",
        ]
        for key, value in headers.items():
            command.extend(["--header", f"{key}: {value}"])
        result = subprocess.run(
            command,
            input=body,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"provider request failed for {url}: {stderr or 'curl fallback failed'}")
        raw_output = result.stdout.decode("utf-8", errors="replace")
        raw_body, separator, raw_status = raw_output.rpartition(f"\n{status_marker}")
        if not separator:
            raise RuntimeError(f"provider request failed for {url}: curl fallback missing status marker")
        try:
            status_code = int(raw_status.strip())
        except ValueError as exc:  # pragma: no cover - defensive fallback
            raise RuntimeError(f"provider request failed for {url}: invalid curl status marker") from exc
        if status_code >= 400:
            raise RuntimeError(
                self._status_error_message(
                    status_code=status_code,
                    body=raw_body,
                    url=url,
                )
            )
        yield from self._stream_chunks_from_text(raw_body)

    def _stream_chunks_from_text(self, raw_body: str):
        event_name: str | None = None
        data_lines: list[str] = []
        saw_sse = False

        def emit_chunk():
            raw_payload = "\n".join(data_lines)
            if raw_payload.strip() == "[DONE]":
                return None
            parsed = json.loads(raw_payload) if raw_payload else {}
            if not isinstance(parsed, dict):
                raise RuntimeError("provider stream response must contain JSON object payloads")
            return JSONHTTPStreamChunk(
                event=event_name,
                payload={str(key): value for key, value in parsed.items()},
            )

        for line in raw_body.splitlines():
            if not line:
                if not data_lines:
                    event_name = None
                    continue
                chunk = emit_chunk()
                data_lines = []
                event_name = None
                if chunk is None:
                    return
                yield chunk
                continue
            if line.startswith("event:"):
                saw_sse = True
                event_name = line[6:].strip() or None
                continue
            if line.startswith("data:"):
                saw_sse = True
                data_lines.append(line[5:].lstrip())
        if data_lines:
            chunk = emit_chunk()
            if chunk is not None:
                yield chunk
            return
        if not saw_sse and raw_body.strip():
            parsed = json.loads(raw_body)
            if not isinstance(parsed, dict):
                raise RuntimeError("provider stream response must be a JSON object or SSE stream")
            yield JSONHTTPStreamChunk(
                event=None,
                payload={str(key): value for key, value in parsed.items()},
            )

    def post_json_stream(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
    ):
        """Retry before the first chunk; surface partial text after.

        If the connection fails before we see any SSE data, we retry via
        ``with_retry`` — the generation hasn't started on the provider
        side (or at least no tokens have been delivered), so we can
        reissue safely. Once we have yielded at least one chunk, a
        mid-stream disconnect becomes a :class:`ProviderSSEIncompleteError`
        carrying the accumulated text so the caller can persist it as
        ``partial_assistant`` on the LoopState.
        """
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        request_headers = dict(headers)
        request_headers.setdefault("Content-Type", "application/json")
        request_headers.setdefault("Accept", "text/event-stream")

        def _open_and_peek() -> tuple[Any, JSONHTTPStreamChunk | None]:
            """Open the stream and pull the first chunk synchronously.

            Pulling the first chunk here means the retry wrapper catches
            *connection-time* failures, not iteration failures. Once the
            first chunk is in hand the stream is committed — further
            failures surface as SSE-incomplete in the outer loop.
            """
            generator = self._post_json_stream_once(url=url, headers=request_headers, body=body)
            try:
                first_chunk = next(generator)
            except StopIteration:
                first_chunk = None
            return generator, first_chunk

        generator, first_chunk = with_retry(
            _open_and_peek,
            policy=self.retry_policy,
            deadline=self._deadline(timeout_seconds=self.stream_timeout_seconds),
        )

        accumulated: list[str] = []
        if first_chunk is not None:
            text = _text_for_partial(first_chunk)
            if text:
                accumulated.append(text)
            yield first_chunk
        try:
            for chunk in generator:
                text = _text_for_partial(chunk)
                if text:
                    accumulated.append(text)
                yield chunk
        except ProviderHTTPError as exc:
            raise ProviderSSEIncompleteError(
                f"sse stream ended mid-response: http {exc.status_code}",
                partial_text="".join(accumulated),
                cause=exc,
            )
        except (ConnectionError, error.URLError) as exc:
            raise ProviderSSEIncompleteError(
                f"sse stream disconnected: {exc}",
                partial_text="".join(accumulated),
                cause=exc,
            )

    def _post_json_stream_once(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
    ):
        http_request = request.Request(
            url,
            data=body,
            headers=dict(headers),
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=self.stream_timeout_seconds) as response:
                event_name: str | None = None
                data_lines: list[str] = []
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if not line:
                        if not data_lines:
                            event_name = None
                            continue
                        raw_payload = "\n".join(data_lines)
                        data_lines = []
                        if raw_payload.strip() == "[DONE]":
                            return
                        parsed = json.loads(raw_payload) if raw_payload else {}
                        if isinstance(parsed, dict):
                            yield JSONHTTPStreamChunk(
                                event=event_name,
                                payload={str(key): value for key, value in parsed.items()},
                            )
                        event_name = None
                        continue
                    if line.startswith("event:"):
                        event_name = line[6:].strip() or None
                        continue
                    if line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
        except error.HTTPError as exc:  # pragma: no cover - exercised by callers
            raise self._provider_http_error(exc, url=url) from exc
        except error.URLError as exc:  # pragma: no cover - exercised by callers
            if self._should_retry_with_curl(exc):
                yield from self._post_json_stream_with_curl(
                    url=url,
                    headers=dict(headers),
                    body=body,
                )
                return
            raise ConnectionError(f"provider stream failed for {url}: {exc.reason}") from exc
