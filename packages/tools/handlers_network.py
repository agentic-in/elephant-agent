"""Networked and interactive built-in tool handlers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
import json
from typing import Any
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse
from urllib.request import Request, urlopen

from packages.contracts.runtime import ExecutionResult

from .handler_support import (
    coerce_choices,
    coerce_int,
    normalized_url,
    optional_string,
    tool_summary,
    truncate,
)
from .runtime import ToolInvocation
from .surfaces import (
    BrowserToolBackend,
    BrowserVisionAnalyzer,
    ClarifySurface,
    MessageDeliverySurface,
)

_WEB_SEARCH_SUMMARY_LIMIT = 4_800


def run_message_send(
    invocation: ToolInvocation,
    *,
    surface: MessageDeliverySurface | None,
) -> Mapping[str, Any] | ExecutionResult:
    if surface is None:
        raise RuntimeError("message delivery is not configured on this Elephant Agent surface")
    body = str(invocation.arguments.get("body") or "").strip()
    if not body:
        raise ValueError("tool.message.send requires a 'body' argument")
    metadata_payload = invocation.arguments.get("metadata")
    metadata = (
        {str(key): str(value) for key, value in metadata_payload.items()}
        if isinstance(metadata_payload, Mapping)
        else None
    )
    return surface.send_message(
        session_id=invocation.session_id,
        body=body,
        target=optional_string(invocation.arguments.get("target")),
        metadata=metadata,
    )


def run_browser_action(
    invocation: ToolInvocation,
    *,
    backend: BrowserToolBackend | None,
    vision_analyzer: BrowserVisionAnalyzer | None = None,
) -> Mapping[str, Any] | ExecutionResult:
    if backend is None:
        raise RuntimeError("browser backend is not configured on this Elephant Agent surface")
    action = invocation.tool_id.removeprefix("tool.browser.")
    return backend.invoke(action, invocation, vision_analyzer=vision_analyzer)


def run_clarify(
    invocation: ToolInvocation,
    *,
    surface: ClarifySurface | None,
) -> Mapping[str, Any] | ExecutionResult:
    question = str(invocation.arguments.get("question") or "").strip()
    if not question:
        raise ValueError("tool.clarify requires a 'question' argument")
    choices = coerce_choices(invocation.arguments.get("choices"))
    mode = str(invocation.arguments.get("mode") or ("choice" if choices else "open")).strip().lower()
    user_response = str(
        invocation.arguments.get("user_response")
        or invocation.arguments.get("answer")
        or invocation.arguments.get("response")
        or ""
    ).strip()
    if user_response:
        return ExecutionResult(
            execution_id=invocation.invocation_id,
            episode_id=invocation.session_id,
            outcome="success",
            summary="\n".join(
                [
                    f"question: {question}",
                    f"mode: {mode}",
                    f"user_response: {user_response}",
                ]
            ),
            side_effects=("clarify",),
        )
    if surface is not None:
        return surface.request_clarification(
            session_id=invocation.session_id,
            question=question,
            mode=mode,
            choices=choices,
        )
    lines = [f"question: {question}", f"mode: {mode}"]
    if choices:
        lines.append("choices:")
        lines.extend(f"- {choice}" for choice in choices)
    return {
        "execution_id": invocation.invocation_id,
        "summary": "\n".join(lines),
        "outcome": "needs_input",
        "side_effects": ("clarify",),
    }


def run_web_search(invocation: ToolInvocation, *, user_agent: str) -> Mapping[str, Any]:
    query = str(invocation.arguments.get("query") or "").strip()
    if not query:
        raise ValueError("tool.web.search requires a 'query' argument")
    limit = max(1, min(coerce_int(invocation.arguments.get("limit"), default=5), 8))
    search_error: Exception | None = None
    query_candidates = _web_search_query_candidates(query, invocation.arguments.get("query_variants"))
    for candidate in query_candidates:
        try:
            results = _run_duckduckgo_html_search(candidate, user_agent=user_agent, limit=limit)
        except Exception as error:  # pragma: no cover - exercised through fallback behavior
            search_error = error
            results = ()
        if not results and _contains_cjk(candidate):
            try:
                results = _run_duckduckgo_html_search(candidate, user_agent=user_agent, limit=limit, region="cn-zh")
            except Exception as error:  # pragma: no cover - exercised through fallback behavior
                search_error = error
                results = ()
        if results:
            return tool_summary(
                invocation,
                _format_web_search_summary(query=candidate, results=results),
                side_effects=("web", "search"),
            )
    fallback_lines: tuple[str, ...] = ()
    fallback_query = query
    for candidate in query_candidates:
        try:
            fallback_lines = _run_duckduckgo_instant_answer(candidate, user_agent=user_agent, limit=limit)
        except Exception as error:
            if search_error is not None:
                raise RuntimeError(
                    f"web search failed after HTML and fallback attempts: {search_error}; {error}"
                ) from error
            raise
        if fallback_lines:
            fallback_query = candidate
            break
    if search_error is not None and not fallback_lines:
        raise RuntimeError(f"web search failed: {search_error}") from search_error
    summary_lines = (
        [f"search: {fallback_query}", *fallback_lines] if fallback_lines else [f"no web results for query: {query}"]
    )
    return tool_summary(
        invocation,
        truncate("\n".join(summary_lines), limit=_WEB_SEARCH_SUMMARY_LIMIT),
        side_effects=("web", "search"),
    )


def run_web_read(invocation: ToolInvocation, *, user_agent: str) -> Mapping[str, Any]:
    url = normalized_url(str(invocation.arguments.get("url") or "").strip())
    if url is None:
        raise ValueError("tool.web.read requires a valid 'url' argument")
    resolved_url, title, content = _fetch_web_document(url, user_agent=user_agent)
    lines: list[str] = []
    if title:
        lines.append(title)
    if content:
        lines.append(content)
    lines.append(f"source: {resolved_url}")
    return tool_summary(
        invocation,
        "\n".join(lines),
        side_effects=("web", "read"),
    )


def run_web_extract(invocation: ToolInvocation, *, user_agent: str) -> Mapping[str, Any]:
    urls = _coerce_url_list(invocation.arguments.get("urls"))
    if not urls:
        raise ValueError("tool.web.extract requires a non-empty 'urls' argument")
    max_urls = max(1, min(coerce_int(invocation.arguments.get("max_urls"), default=len(urls)), 5))
    attempted = min(len(urls), max_urls)
    summaries: list[str] = []
    failures: list[str] = []
    successes = 0
    for index, url in enumerate(urls[:max_urls], start=1):
        try:
            resolved_url, title, content = _fetch_web_document(url, user_agent=user_agent)
        except Exception as error:  # pragma: no cover - exercised by integration failure paths
            failures.append(f"{index}. {url} | error: {error}")
            continue
        successes += 1
        summaries.append(f"{index}. {title or resolved_url}")
        summaries.append(f"   {resolved_url}")
        if content:
            summaries.append(f"   {content}")
    if failures:
        summaries.append("failures:")
        summaries.extend(f"  - {item}" for item in failures)
    if successes == 0:
        raise RuntimeError("web extract failed for every URL")
    summaries.insert(0, f"sources: {successes}/{attempted}")
    return tool_summary(
        invocation,
        "\n".join(summaries),
        side_effects=("web", "extract"),
    )


@dataclass(frozen=True, slots=True)
class _WebSearchResult:
    title: str
    url: str
    snippet: str = ""


def _run_duckduckgo_html_search(
    query: str,
    *,
    user_agent: str,
    limit: int,
    region: str = "",
) -> tuple[_WebSearchResult, ...]:
    region_part = f"&kl={quote_plus(region)}" if region else ""
    request = Request(
        f"https://html.duckduckgo.com/html/?q={quote_plus(query)}{region_part}",
        headers={
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urlopen(request, timeout=20) as response:  # noqa: S310
        payload = response.read().decode("utf-8", errors="replace")
    parser = _DuckDuckGoSearchResultsParser(limit=limit)
    parser.feed(payload)
    parser.close()
    return parser.results


def _web_search_query_candidates(query: str, raw_variants: object) -> tuple[str, ...]:
    values = [query]
    if isinstance(raw_variants, str):
        values.extend(part.strip() for part in raw_variants.replace("\n", ",").split(","))
    elif isinstance(raw_variants, list | tuple):
        values.extend(str(item).strip() for item in raw_variants)
    candidates: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(value.split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        candidates.append(normalized)
        if len(candidates) >= 4:
            break
    return tuple(candidates)


def _contains_cjk(value: str) -> bool:
    return any("\u3400" <= char <= "\u9fff" or "\uf900" <= char <= "\ufaff" for char in value)


def _run_duckduckgo_instant_answer(
    query: str,
    *,
    user_agent: str,
    limit: int,
) -> tuple[str, ...]:
    request = Request(
        f"https://api.duckduckgo.com/?q={quote_plus(query)}&format=json&no_html=1&skip_disambig=1",
        headers={"User-Agent": user_agent},
    )
    with urlopen(request, timeout=20) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    lines: list[str] = []
    abstract = str(payload.get("AbstractText") or "").strip()
    abstract_url = str(payload.get("AbstractURL") or "").strip()
    if abstract:
        lines.append(abstract if not abstract_url else f"{abstract} ({abstract_url})")
    answer = str(payload.get("Answer") or "").strip()
    if answer and answer not in lines:
        lines.append(answer)
    related = payload.get("RelatedTopics")
    if isinstance(related, list):
        for item in _iter_duckduckgo_related_topics(related):
            text = str(item.get("Text") or "").strip()
            url = str(item.get("FirstURL") or "").strip()
            if text:
                lines.append(text if not url else f"{text} ({url})")
            if len(lines) >= max(3, limit):
                break
    return tuple(lines)


def _iter_duckduckgo_related_topics(topics: list[Any]) -> tuple[Mapping[str, Any], ...]:
    flattened: list[Mapping[str, Any]] = []
    for item in topics:
        if not isinstance(item, Mapping):
            continue
        nested = item.get("Topics")
        if isinstance(nested, list):
            flattened.extend(_iter_duckduckgo_related_topics(nested))
            continue
        flattened.append(item)
    return tuple(flattened)


def _format_web_search_summary(
    *,
    query: str,
    results: tuple[_WebSearchResult, ...],
) -> str:
    lines = [f"search: {query}"]
    for index, result in enumerate(results, start=1):
        lines.append(f"{index}. {result.title}")
        lines.append(f"   {result.url}")
        if result.snippet:
            lines.append(f"   {result.snippet}")
    return truncate("\n".join(lines), limit=_WEB_SEARCH_SUMMARY_LIMIT)


def _unwrap_duckduckgo_result_url(raw_url: str | None) -> str | None:
    candidate = optional_string(raw_url)
    if candidate is None:
        return None
    if candidate.startswith("//"):
        candidate = f"https:{candidate}"
    elif candidate.startswith("/"):
        candidate = urljoin("https://duckduckgo.com", candidate)
    parsed = urlparse(candidate)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        redirect = parse_qs(parsed.query).get("uddg", ())
        if redirect:
            return normalized_url(redirect[0])
    return normalized_url(candidate)


def _coerce_url_list(value: Any) -> tuple[str, ...]:
    candidates: list[str] = []
    if isinstance(value, list | tuple):
        candidates = [str(item).strip() for item in value]
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            candidates = []
        else:
            try:
                decoded = json.loads(raw)
            except json.JSONDecodeError:
                candidates = [part.strip() for part in raw.splitlines() if part.strip()]
            else:
                if isinstance(decoded, list | tuple):
                    candidates = [str(item).strip() for item in decoded]
                else:
                    candidates = [str(decoded).strip()]
    normalized: list[str] = []
    for candidate in candidates:
        url = normalized_url(candidate)
        if url is None or url in normalized:
            continue
        normalized.append(url)
    return tuple(normalized)


def _fetch_web_document(url: str, *, user_agent: str) -> tuple[str, str, str]:
    request = Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,text/plain,application/json;q=0.9,*/*;q=0.8",
        },
    )
    with urlopen(request, timeout=20) as response:  # noqa: S310
        payload = response.read()
        content_type = response.headers.get_content_type()
        charset = response.headers.get_content_charset() or "utf-8"
        resolved_url = response.geturl()
    title, content = _extract_web_text(payload, content_type=content_type, charset=charset)
    return resolved_url, title, content


def _extract_web_text(payload: bytes, *, content_type: str, charset: str) -> tuple[str, str]:
    decoded = payload.decode(charset, errors="replace")
    if content_type in {"text/html", "application/xhtml+xml"} or content_type.endswith("+html"):
        parser = _HTMLTextExtractor()
        parser.feed(decoded)
        parser.close()
        return parser.title, parser.text
    return "", _compact_text(decoded)


def _compact_text(value: str) -> str:
    return " ".join(unescape(value).split())


class _DuckDuckGoSearchResultsParser(HTMLParser):
    def __init__(self, *, limit: int) -> None:
        super().__init__()
        self._limit = limit
        self._results: list[_WebSearchResult] = []
        self._current_url: str | None = None
        self._current_title_parts: list[str] = []
        self._current_snippet_parts: list[str] = []
        self._capture_title = False
        self._capture_snippet = False
        self._snippet_depth = 0

    @property
    def results(self) -> tuple[_WebSearchResult, ...]:
        return tuple(self._results[: self._limit])

    def close(self) -> None:
        self._flush_current()
        super().close()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if len(self._results) >= self._limit:
            return
        attr_map = {key: value or "" for key, value in attrs}
        classes = {part for part in attr_map.get("class", "").split() if part}
        if tag == "a" and {"result__a", "result-link"} & classes:
            self._flush_current()
            resolved_url = _unwrap_duckduckgo_result_url(attr_map.get("href"))
            if resolved_url is None:
                return
            self._current_url = resolved_url
            self._current_title_parts = []
            self._current_snippet_parts = []
            self._capture_title = True
            self._capture_snippet = False
            self._snippet_depth = 0
            return
        if self._capture_snippet:
            self._snippet_depth += 1
            return
        if self._current_url is not None and {"result__snippet", "result-snippet"} & classes:
            self._capture_snippet = True
            self._snippet_depth = 1

    def handle_endtag(self, tag: str) -> None:
        if self._capture_title and tag == "a":
            self._capture_title = False
            return
        if self._capture_snippet:
            self._snippet_depth -= 1
            if self._snippet_depth <= 0:
                self._capture_snippet = False
                self._snippet_depth = 0

    def handle_data(self, data: str) -> None:
        text = _compact_text(data)
        if not text or self._current_url is None:
            return
        if self._capture_title:
            self._current_title_parts.append(text)
        elif self._capture_snippet:
            self._current_snippet_parts.append(text)

    def _flush_current(self) -> None:
        if self._current_url is None:
            return
        title = " ".join(self._current_title_parts).strip()
        snippet = " ".join(self._current_snippet_parts).strip()
        if title and all(existing.url != self._current_url for existing in self._results):
            self._results.append(_WebSearchResult(title=title, url=self._current_url, snippet=snippet))
        self._current_url = None
        self._current_title_parts = []
        self._current_snippet_parts = []
        self._capture_title = False
        self._capture_snippet = False
        self._snippet_depth = 0


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._blocked_depth = 0
        self._in_title = False
        self._title_parts: list[str] = []
        self._text_parts: list[str] = []

    @property
    def title(self) -> str:
        return " ".join(self._title_parts).strip()

    @property
    def text(self) -> str:
        return " ".join(self._text_parts).strip()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:  # noqa: ARG002
        if tag in {"script", "style", "noscript"}:
            self._blocked_depth += 1
            return
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._blocked_depth > 0:
            self._blocked_depth -= 1
            return
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._blocked_depth > 0:
            return
        text = _compact_text(data)
        if not text:
            return
        if self._in_title:
            self._title_parts.append(text)
        else:
            self._text_parts.append(text)


__all__ = [
    "run_browser_action",
    "run_clarify",
    "run_message_send",
    "run_web_extract",
    "run_web_read",
    "run_web_search",
]
