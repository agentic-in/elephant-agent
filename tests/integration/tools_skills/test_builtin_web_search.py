from __future__ import annotations

from email.message import Message
import json
from pathlib import Path
import unittest
from unittest import mock

from packages.tools import (
    BuiltinToolDependencies,
    CallableApprovalGateway,
    InMemoryToolExecutor,
    InMemoryToolRegistry,
    ToolRuntime,
    register_builtin_tools,
)


class _FakeUrlopenResponse:
    def __init__(
        self,
        body: str,
        *,
        content_type: str = "text/html; charset=utf-8",
        url: str = "https://example.com",
    ) -> None:
        self._body = body.encode("utf-8")
        self._url = url
        self.headers = Message()
        self.headers.add_header("Content-Type", content_type)

    def __enter__(self) -> "_FakeUrlopenResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            return self._body
        return self._body[:size]

    def geturl(self) -> str:
        return self._url


class BuiltinWebSearchIntegrationTest(unittest.TestCase):
    def _make_runtime(self) -> ToolRuntime:
        runtime = ToolRuntime(
            registry=InMemoryToolRegistry(),
            executor=InMemoryToolExecutor(),
            approval_gateway=CallableApprovalGateway(lambda *_: True),
        )
        register_builtin_tools(
            runtime,
            enabled_overrides={},
            dependencies=BuiltinToolDependencies(cwd=Path("/tmp")),
        )
        return runtime

    def test_web_search_prefers_html_results_and_respects_limit(self) -> None:
        runtime = self._make_runtime()
        html = """
        <html><body>
          <div class="result">
            <h2 class="result__title">
              <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Falpha">
                Alpha <b>Result</b>
              </a>
            </h2>
            <div class="result__snippet">First result summary.</div>
          </div>
          <div class="result">
            <h2 class="result__title">
              <a class="result__a" href="https://example.com/beta">Beta Result</a>
            </h2>
            <a class="result__snippet" href="https://example.com/beta">Second result summary.</a>
          </div>
        </body></html>
        """

        with mock.patch(
            "packages.tools.handlers_network.urlopen",
            return_value=_FakeUrlopenResponse(html),
        ) as urlopen_mock:
            result = runtime.invoke(
                "tool.web.search",
                {"query": "agentic ai", "limit": 1},
                session_id="session-html",
            )

        self.assertEqual(result.outcome, "success")
        self.assertIn("search: agentic ai", result.summary)
        self.assertIn("1. Alpha Result", result.summary)
        self.assertIn("https://example.com/alpha", result.summary)
        self.assertIn("First result summary.", result.summary)
        self.assertNotIn("Beta Result", result.summary)
        self.assertEqual(urlopen_mock.call_count, 1)
        request = urlopen_mock.call_args.args[0]
        self.assertIn("html.duckduckgo.com/html/", request.full_url)

    def test_web_search_keeps_long_result_lists_readable(self) -> None:
        runtime = self._make_runtime()
        snippet = "Long paper summary sentence. " * 10
        html = (
            "<html><body>"
            + "".join(
                f"""
            <div class="result">
              <h2 class="result__title">
                <a class="result__a" href="https://example.com/paper-{index}">Paper {index}</a>
              </h2>
              <div class="result__snippet">{snippet}</div>
            </div>
            """
                for index in range(1, 7)
            )
            + "</body></html>"
        )

        with mock.patch(
            "packages.tools.handlers_network.urlopen",
            return_value=_FakeUrlopenResponse(html),
        ):
            result = runtime.invoke(
                "tool.web.search",
                {"query": "machine learning arxiv", "limit": 6},
                session_id="session-long-search",
            )

        self.assertEqual(result.outcome, "success")
        self.assertIn("1. Paper 1", result.summary)
        self.assertIn("6. Paper 6", result.summary)
        self.assertGreater(len(result.summary), 1600)

    def test_web_search_falls_back_to_instant_answer_when_html_results_are_empty(
        self,
    ) -> None:
        runtime = self._make_runtime()
        html = "<html><body><p>no direct results</p></body></html>"
        instant_answer = json.dumps(
            {
                "AbstractText": "Elephant Agent is a protective shield in Greek mythology.",
                "AbstractURL": "https://example.com/elephant",
                "RelatedTopics": [
                    {
                        "Name": "Nested",
                        "Topics": [
                            {
                                "Text": "Protective symbol",
                                "FirstURL": "https://example.com/topic",
                            }
                        ],
                    }
                ],
            }
        )

        with mock.patch(
            "packages.tools.handlers_network.urlopen",
            side_effect=[
                _FakeUrlopenResponse(html),
                _FakeUrlopenResponse(instant_answer),
            ],
        ) as urlopen_mock:
            result = runtime.invoke(
                "tool.web.search",
                {"query": "elephant"},
                session_id="session-fallback",
            )

        self.assertEqual(result.outcome, "success")
        self.assertIn("search: elephant", result.summary)
        self.assertIn(
            "Elephant Agent is a protective shield in Greek mythology. (https://example.com/elephant)",
            result.summary,
        )
        self.assertIn("Protective symbol (https://example.com/topic)", result.summary)
        self.assertEqual(urlopen_mock.call_count, 2)

    def test_web_search_tries_query_variants_after_empty_primary_results(self) -> None:
        runtime = self._make_runtime()
        empty_html = "<html><body><p>no direct results</p></body></html>"
        variant_html = """
        <html><body>
          <div class="result">
            <h2 class="result__title">
              <a class="result__a" href="https://example.com/chengdu-weather">Chengdu Weather</a>
            </h2>
            <div class="result__snippet">Current Chengdu weather.</div>
          </div>
        </body></html>
        """

        with mock.patch(
            "packages.tools.handlers_network.urlopen",
            side_effect=[
                _FakeUrlopenResponse(empty_html),
                _FakeUrlopenResponse(empty_html),
                _FakeUrlopenResponse(variant_html),
            ],
        ) as urlopen_mock:
            result = runtime.invoke(
                "tool.web.search",
                {"query": "成都今日天气", "query_variants": ["Chengdu weather today"]},
                session_id="session-variant-search",
            )

        self.assertEqual(result.outcome, "success")
        self.assertIn("search: Chengdu weather today", result.summary)
        self.assertIn("Chengdu Weather", result.summary)
        self.assertEqual(urlopen_mock.call_count, 3)

    def test_web_search_retries_cjk_query_with_region_hint(self) -> None:
        runtime = self._make_runtime()
        empty_html = "<html><body><p>no direct results</p></body></html>"
        region_html = """
        <html><body>
          <div class="result">
            <h2 class="result__title">
              <a class="result__a" href="https://example.com/cn-result">中文结果</a>
            </h2>
            <div class="result__snippet">区域搜索结果。</div>
          </div>
        </body></html>
        """

        with mock.patch(
            "packages.tools.handlers_network.urlopen",
            side_effect=[
                _FakeUrlopenResponse(empty_html),
                _FakeUrlopenResponse(region_html),
            ],
        ) as urlopen_mock:
            result = runtime.invoke(
                "tool.web.search",
                {"query": "成都今日天气"},
                session_id="session-cjk-region-search",
            )

        self.assertEqual(result.outcome, "success")
        self.assertIn("中文结果", result.summary)
        self.assertIn("kl=cn-zh", urlopen_mock.call_args_list[1].args[0].full_url)

    def test_web_extract_fetches_multiple_sources(self) -> None:
        runtime = self._make_runtime()
        alpha = "<html><head><title>Alpha Doc</title></head><body><p>First source excerpt.</p></body></html>"
        beta = "<html><head><title>Beta Doc</title></head><body><p>Second source excerpt.</p></body></html>"

        with mock.patch(
            "packages.tools.handlers_network.urlopen",
            side_effect=[
                _FakeUrlopenResponse(alpha, url="https://example.com/alpha"),
                _FakeUrlopenResponse(beta, url="https://example.com/beta"),
            ],
        ) as urlopen_mock:
            result = runtime.invoke(
                "tool.web.extract",
                {"urls": ["https://example.com/alpha", "https://example.com/beta"]},
                session_id="session-extract",
            )

        self.assertEqual(result.outcome, "success")
        self.assertIn("sources: 2", result.summary)
        self.assertIn("1. Alpha Doc", result.summary)
        self.assertIn("2. Beta Doc", result.summary)
        self.assertIn("First source excerpt.", result.summary)
        self.assertIn("Second source excerpt.", result.summary)
        self.assertEqual(urlopen_mock.call_count, 2)

    def test_web_read_preserves_full_document_text_for_runtime_budgeting(self) -> None:
        runtime = self._make_runtime()
        long_body = " ".join(("full text segment" for _ in range(300))) + " tail-marker"
        html = f"<html><head><title>Long Doc</title></head><body><p>{long_body}</p></body></html>"

        with mock.patch(
            "packages.tools.handlers_network.urlopen",
            return_value=_FakeUrlopenResponse(html, url="https://example.com/long"),
        ):
            result = runtime.invoke(
                "tool.web.read",
                {"url": "https://example.com/long"},
                session_id="session-read-long",
            )

        self.assertEqual(result.outcome, "success")
        self.assertIn("Long Doc", result.summary)
        self.assertIn("tail-marker", result.summary)
        self.assertNotIn("…", result.summary)
        self.assertGreater(len(result.summary), 3_200)

    def test_web_extract_preserves_full_source_text_for_runtime_budgeting(self) -> None:
        runtime = self._make_runtime()
        long_body = " ".join(("source text segment" for _ in range(450))) + " extract-tail-marker"
        html = f"<html><head><title>Full Source</title></head><body><p>{long_body}</p></body></html>"

        with mock.patch(
            "packages.tools.handlers_network.urlopen",
            return_value=_FakeUrlopenResponse(html, url="https://example.com/full-source"),
        ):
            result = runtime.invoke(
                "tool.web.extract",
                {"urls": ["https://example.com/full-source"]},
                session_id="session-extract-long",
            )

        self.assertEqual(result.outcome, "success")
        self.assertIn("Full Source", result.summary)
        self.assertIn("extract-tail-marker", result.summary)
        self.assertNotIn("…", result.summary)
        self.assertGreater(len(result.summary), 6_400)


if __name__ == "__main__":
    unittest.main()
