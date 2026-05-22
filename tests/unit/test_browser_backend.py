from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from packages.tools import browser_backend as browser_backend_module
from packages.tools.browser_backend import BrowserBackendConfig, PlaywrightBrowserBackend, _is_private_url
from packages.tools.builtins import builtin_tool_definitions
from packages.tools.handlers_network import run_browser_action
from packages.tools.runtime import ToolInvocation
from packages.tools.surfaces import BuiltinToolDependencies


class _FakeMessage:
    type = "error"
    text = "boom"


class _FakeLocator:
    def __init__(self, page: "_FakePage", selector: str) -> None:
        self.page = page
        self.selector = selector

    @property
    def first(self) -> "_FakeLocator":
        return self

    def click(self, timeout: int | None = None) -> None:
        self.page.clicked.append((self.selector, timeout))

    def fill(self, text: str, timeout: int | None = None) -> None:
        self.page.filled.append((self.selector, text, timeout))


class _FakeMouse:
    def __init__(self, page: "_FakePage") -> None:
        self.page = page

    def wheel(self, x: int, y: int) -> None:
        self.page.wheels.append((x, y))


class _FakeKeyboard:
    def __init__(self, page: "_FakePage") -> None:
        self.page = page

    def press(self, key: str) -> None:
        self.page.keys.append(key)


class _FakePage:
    def __init__(self) -> None:
        self.url = "about:blank"
        self._title = "Blank"
        self.mouse = _FakeMouse(self)
        self.keyboard = _FakeKeyboard(self)
        self.clicked: list[tuple[str, int | None]] = []
        self.filled: list[tuple[str, str, int | None]] = []
        self.wheels: list[tuple[int, int]] = []
        self.keys: list[str] = []
        self.thread_ids: list[int] = []
        self.handlers = {}

    def on(self, event: str, handler) -> None:  # type: ignore[no-untyped-def]
        self.handlers[event] = handler

    def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
        self.thread_ids.append(threading.get_ident())
        self.url = url
        self._title = "Example"

    def title(self) -> str:
        return self._title

    def locator(self, selector: str) -> _FakeLocator:
        return _FakeLocator(self, selector)

    def evaluate(self, script: str, arg=None):  # type: ignore[no-untyped-def]
        self.thread_ids.append(threading.get_ident())
        if "data-elephant-browser-ref" in script and "elementCount" in script:
            return {
                "title": self._title,
                "url": self.url,
                "text": "Welcome Sign in Email",
                "elementCount": 2,
                "elements": [
                    {"ref": "@e1", "role": "button", "label": "Sign in", "disabled": False},
                    {"ref": "@e2", "role": "input", "label": "Email", "disabled": False},
                ],
            }
        if "document.images" in script:
            return [{"index": 1, "src": "https://example.com/a.png", "alt": "A", "width": 10, "height": 20}]
        if "data-elephant-browser-annotation" in script:
            return 2
        if script == "document.title":
            return self._title
        return None

    def screenshot(self, *, path: str, full_page: bool) -> None:
        self.thread_ids.append(threading.get_ident())
        Path(path).write_bytes(b"fake-png")

    def go_back(self, *, wait_until: str, timeout: int) -> None:
        self.url = "https://example.com/back"


class _FakeContext:
    def __init__(self) -> None:
        self.pages: list[_FakePage] = []
        self.closed = False

    def new_page(self) -> _FakePage:
        page = _FakePage()
        self.pages.append(page)
        return page

    def close(self) -> None:
        self.closed = True


class _FakeBrowser:
    def __init__(self) -> None:
        self.contexts: list[_FakeContext] = []
        self.closed = False

    def new_context(self) -> _FakeContext:
        context = _FakeContext()
        self.contexts.append(context)
        return context

    def close(self) -> None:
        self.closed = True


class _FakeChromium:
    def __init__(self) -> None:
        self.browser = _FakeBrowser()
        self.fail_next_launch = False

    def launch(self, *, headless: bool) -> _FakeBrowser:
        if self.fail_next_launch:
            self.fail_next_launch = False
            raise RuntimeError("Executable doesn't exist at /tmp/ms-playwright/chromium")
        return self.browser

    def connect_over_cdp(self, cdp_url: str) -> _FakeBrowser:
        return self.browser


class _FakePlaywright:
    def __init__(self) -> None:
        self.chromium = _FakeChromium()
        self.stopped = False
        self.started_thread_id = 0

    def stop(self) -> None:
        self.stopped = True


class _FakeSyncPlaywright:
    def __init__(self) -> None:
        self.instance = _FakePlaywright()

    def __call__(self) -> "_FakeSyncPlaywright":
        return self

    def start(self) -> _FakePlaywright:
        self.instance.started_thread_id = threading.get_ident()
        return self.instance


class _FakeVisionAnalyzer:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def analyze_browser_screenshot(
        self,
        *,
        session_id: str,
        invocation_id: str,
        question: str,
        screenshot_path: Path,
        page_url: str = "",
        page_title: str = "",
        page_snapshot: str = "",
        metadata=None,  # type: ignore[no-untyped-def]
    ) -> dict[str, object]:
        self.calls.append(
            {
                "session_id": session_id,
                "invocation_id": invocation_id,
                "question": question,
                "screenshot_path": screenshot_path,
                "page_url": page_url,
                "page_title": page_title,
                "page_snapshot": page_snapshot,
                "metadata": metadata,
            }
        )
        return {"analysis": "The sign-in form is visible.", "model": "fake-vision"}


class _RecordingBackend:
    def __init__(self) -> None:
        self.action = ""
        self.vision_analyzer = None

    def backend_label(self) -> str:
        return "recording"

    def invoke(self, action: str, invocation: ToolInvocation, *, vision_analyzer=None):  # type: ignore[no-untyped-def]
        self.action = action
        self.vision_analyzer = vision_analyzer
        return {
            "execution_id": invocation.invocation_id,
            "summary": "ok",
            "outcome": "success",
            "side_effects": ("browser",),
        }


class BrowserBackendTest(unittest.TestCase):
    def _backend(self, screenshots_dir: Path | None = None) -> PlaywrightBrowserBackend:
        backend = PlaywrightBrowserBackend(
            sync_playwright=_FakeSyncPlaywright(),
            config=BrowserBackendConfig(
                headless=True,
                cloud_provider="local",
                screenshots_dir=screenshots_dir or Path(tempfile.gettempdir()) / "elephant-browser-test",
            ),
        )
        self.addCleanup(backend.close_all)
        return backend

    def _invoke(self, tool_id: str, arguments: dict[str, object]) -> ToolInvocation:
        return ToolInvocation(
            invocation_id=f"session-1:{tool_id}",
            tool_id=tool_id,
            session_id="session-1",
            arguments=arguments,
        )

    def test_navigate_returns_ref_snapshot_and_click_uses_ref(self) -> None:
        backend = self._backend()
        navigated = backend.invoke("navigate", self._invoke("tool.browser.navigate", {"url": "example.com"}))
        payload = json.loads(navigated["summary"])

        self.assertEqual(payload["url"], "https://example.com")
        self.assertIn("[@e1] button", payload["snapshot"])
        self.assertEqual(payload["element_count"], 2)

        clicked = backend.invoke("click", self._invoke("tool.browser.click", {"ref": "@e1"}))
        click_payload = json.loads(clicked["summary"])
        page = backend._sessions["session-1"].page

        self.assertTrue(click_payload["success"])
        self.assertEqual(page.clicked[-1][0], '[data-elephant-browser-ref="@e1"]')

    def test_type_images_console_and_vision_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = self._backend(Path(tmpdir))
            backend.invoke("navigate", self._invoke("tool.browser.navigate", {"url": "https://example.com"}))
            page = backend._sessions["session-1"].page
            page.handlers["console"](_FakeMessage())

            typed = backend.invoke("type", self._invoke("tool.browser.type", {"ref": "e2", "text": "a@example.com"}))
            images = backend.invoke("images", self._invoke("tool.browser.images", {}))
            console = backend.invoke("console", self._invoke("tool.browser.console", {"expression": "document.title"}))
            analyzer = _FakeVisionAnalyzer()
            vision = backend.invoke(
                "vision",
                self._invoke("tool.browser.vision", {"question": "what is visible?", "annotate": True}),
                vision_analyzer=analyzer,
            )

            self.assertEqual(json.loads(typed["summary"])["target"], '[data-elephant-browser-ref="@e2"]')
            self.assertEqual(json.loads(images["summary"])["count"], 1)
            self.assertEqual(json.loads(console["summary"])["result"], "Example")
            vision_payload = json.loads(vision["summary"])
            self.assertTrue(Path(vision_payload["screenshot_path"]).exists())
            self.assertEqual(vision_payload["annotated_ref_count"], 2)
            self.assertEqual(vision_payload["analysis"], "The sign-in form is visible.")
            self.assertTrue(vision_payload["vision_analyzer_configured"])
            self.assertEqual(vision_payload["vision_analysis"]["model"], "fake-vision")
            self.assertEqual(analyzer.calls[0]["question"], "what is visible?")
            self.assertIn("Sign in", str(analyzer.calls[0]["page_snapshot"]))

    def test_browser_vision_without_analyzer_returns_setup_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = self._backend(Path(tmpdir))
            backend.invoke("navigate", self._invoke("tool.browser.navigate", {"url": "https://example.com"}))

            vision = backend.invoke("vision", self._invoke("tool.browser.vision", {"question": "what is visible?"}))

            vision_payload = json.loads(vision["summary"])
            self.assertFalse(vision_payload["vision_analyzer_configured"])
            self.assertIn("Configure a browser vision analyzer", vision_payload["vision_setup_hint"])

    def test_browser_schema_is_ref_first_with_selector_fallback(self) -> None:
        definitions = {
            definition.tool_id: definition
            for definition in builtin_tool_definitions(
                {},
                dependencies=BuiltinToolDependencies(cwd=Path("/tmp"), browser_backend=object()),  # type: ignore[arg-type]
            )
        }

        click_schema = definitions["tool.browser.click"].schema["properties"]
        type_schema = definitions["tool.browser.type"].schema
        console_schema = definitions["tool.browser.console"].schema["properties"]

        self.assertIn("ref", click_schema)
        self.assertIn("selector", click_schema)
        self.assertEqual(tuple(type_schema["required"]), ("text",))
        self.assertIn("expression", console_schema)

    def test_browser_vision_is_unavailable_without_analyzer(self) -> None:
        definitions = {
            definition.tool_id: definition
            for definition in builtin_tool_definitions(
                {},
                dependencies=BuiltinToolDependencies(cwd=Path("/tmp"), browser_backend=object()),  # type: ignore[arg-type]
            )
        }

        self.assertTrue(definitions["tool.browser.navigate"].available)
        self.assertFalse(definitions["tool.browser.vision"].available)
        self.assertIn("vision analyzer", definitions["tool.browser.vision"].availability.reason or "")

    def test_browser_vision_is_available_with_analyzer(self) -> None:
        definitions = {
            definition.tool_id: definition
            for definition in builtin_tool_definitions(
                {},
                dependencies=BuiltinToolDependencies(
                    cwd=Path("/tmp"),
                    browser_backend=object(),  # type: ignore[arg-type]
                    browser_vision_analyzer=object(),  # type: ignore[arg-type]
                ),
            )
        }

        self.assertTrue(definitions["tool.browser.vision"].available)

    def test_remote_private_url_detection_blocks_internal_targets(self) -> None:
        self.assertTrue(_is_private_url("http://127.0.0.1:8000"))
        self.assertTrue(_is_private_url("http://localhost"))
        self.assertFalse(_is_private_url("https://example.com"))

    def test_playwright_operations_run_on_dedicated_worker_thread(self) -> None:
        backend = self._backend()
        caller_thread_ids: list[int] = []
        errors: list[BaseException] = []

        def _run_navigation() -> None:
            caller_thread_ids.append(threading.get_ident())
            try:
                backend.invoke("navigate", self._invoke("tool.browser.navigate", {"url": "example.com"}))
            except BaseException as exc:
                errors.append(exc)

        workers = [threading.Thread(target=_run_navigation) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()

        self.assertFalse(errors)
        playwright = backend._playwright
        self.assertIsNotNone(playwright)
        worker_thread_id = playwright.started_thread_id
        page = backend._sessions["session-1"].page
        self.assertNotIn(worker_thread_id, caller_thread_ids)
        self.assertEqual(set(page.thread_ids), {worker_thread_id})

    def test_missing_playwright_chromium_auto_installs_and_retries_once(self) -> None:
        sync_playwright = _FakeSyncPlaywright()
        sync_playwright.instance.chromium.fail_next_launch = True
        backend = PlaywrightBrowserBackend(
            sync_playwright=sync_playwright,
            config=BrowserBackendConfig(headless=True, cloud_provider="local"),
        )
        self.addCleanup(backend.close_all)

        with mock.patch.object(browser_backend_module, "_install_playwright_chromium") as install:
            result = backend.invoke("snapshot", self._invoke("tool.browser.snapshot", {}))

        self.assertEqual(result["outcome"], "success")
        install.assert_called_once_with(headless_only=True)

    def test_network_handler_passes_optional_vision_analyzer_to_backend(self) -> None:
        backend = _RecordingBackend()
        analyzer = _FakeVisionAnalyzer()
        result = run_browser_action(
            self._invoke("tool.browser.vision", {"question": "what is visible?"}),
            backend=backend,
            vision_analyzer=analyzer,
        )

        self.assertEqual(result["outcome"], "success")
        self.assertEqual(backend.action, "vision")
        self.assertIs(backend.vision_analyzer, analyzer)


if __name__ == "__main__":
    unittest.main()
