"""Playwright-backed browser runtime for built-in browser tools."""

from __future__ import annotations

import atexit
import base64
from collections.abc import Callable, Mapping
from concurrent.futures import Future
from dataclasses import dataclass, field
import ipaddress
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from packages.contracts.runtime import ExecutionResult

from .browser_providers import (
    BrowserUseProvider,
    BrowserbaseProvider,
    CloudBrowserProvider,
    CloudBrowserSession,
    FirecrawlProvider,
    _http_json,
)
from .browser_scripts import ANNOTATE_JS, CLEAR_ANNOTATIONS_JS, IMAGES_JS, SNAPSHOT_JS
from .runtime import ToolInvocation
from .surfaces import BrowserToolBackend, BrowserVisionAnalyzer

_DEFAULT_NAVIGATION_TIMEOUT_MS = 30_000
_DEFAULT_ACTION_TIMEOUT_MS = 10_000
_SNAPSHOT_COMPACT_LIMIT = 4_000
_SNAPSHOT_FULL_LIMIT = 24_000
_MAX_REF_ELEMENTS = 120
_MAX_IMAGES = 80
_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{10,}|xox[baprs]-[A-Za-z0-9-]{10,}|gh[pousr]_[A-Za-z0-9_]{10,}|AKIA[0-9A-Z]{16})"
)


def create_browser_backend(*, headless: bool = True) -> tuple[BrowserToolBackend | None, str | None]:
    """Create the configured browser backend.

    The legacy factory name below is kept for existing CLI/API callers. Runtime
    selection is environment driven: Camofox REST when configured, otherwise a
    Playwright backend that can launch local Chromium, connect to CDP, or create
    a Browser Use/Browserbase/Firecrawl cloud session.
    """

    return create_playwright_browser_backend(headless=headless)


def create_playwright_browser_backend(*, headless: bool = True) -> tuple[BrowserToolBackend | None, str | None]:
    config = BrowserBackendConfig.from_env(headless=headless)
    if config.camofox_url:
        return (CamofoxBrowserBackend(config=config), None)
    try:
        from playwright.sync_api import sync_playwright  # type: ignore import-not-found
    except Exception as exc:  # pragma: no cover - import availability depends on operator env
        return (None, f"Browser tools require the optional 'playwright' package: {exc}")
    try:
        backend = PlaywrightBrowserBackend(sync_playwright=sync_playwright, config=config)
    except Exception as exc:  # pragma: no cover - launch availability depends on operator env
        return (None, f"Browser backend could not start: {exc}")
    return (backend, None)


@dataclass(frozen=True, slots=True)
class BrowserBackendConfig:
    headless: bool = True
    cdp_url: str = ""
    cloud_provider: str = ""
    camofox_url: str = ""
    allow_private_urls: bool = False
    screenshots_dir: Path = field(default_factory=lambda: Path(tempfile.gettempdir()) / "elephant-browser-screenshots")

    @classmethod
    def from_env(cls, *, headless: bool = True) -> "BrowserBackendConfig":
        provider = _first_env("ELEPHANT_BROWSER_CLOUD_PROVIDER", "BROWSER_CLOUD_PROVIDER", "BROWSER_PROVIDER")
        return cls(
            headless=_env_bool("ELEPHANT_BROWSER_HEADLESS", default=headless),
            cdp_url=_first_env("ELEPHANT_BROWSER_CDP_URL", "BROWSER_CDP_URL"),
            cloud_provider=provider.strip().lower(),
            camofox_url=_first_env("ELEPHANT_BROWSER_CAMOFOX_URL", "CAMOFOX_URL").rstrip("/"),
            allow_private_urls=_env_bool("ELEPHANT_BROWSER_ALLOW_PRIVATE_URLS", "BROWSER_ALLOW_PRIVATE_URLS", default=False),
            screenshots_dir=Path(
                _first_env("ELEPHANT_BROWSER_SCREENSHOTS_DIR")
                or (Path.home() / ".elephant" / "cache" / "browser-screenshots")
            ),
        )


@dataclass(slots=True)
class BrowserSession:
    session_key: str
    page: Any
    context: Any | None = None
    browser: Any | None = None
    provider: CloudBrowserProvider | None = None
    provider_session: CloudBrowserSession | None = None
    close_browser: bool = False
    refs: dict[str, str] = field(default_factory=dict)
    console_messages: list[str] = field(default_factory=list)
    js_errors: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)


@dataclass(slots=True)
class PlaywrightBrowserBackend(BrowserToolBackend):
    sync_playwright: Any
    config: BrowserBackendConfig = field(default_factory=BrowserBackendConfig)
    _playwright: Any | None = None
    _local_browser: Any | None = None
    _sessions: dict[str, BrowserSession] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)
    _worker_lock: threading.Lock = field(default_factory=threading.Lock)
    _worker_ready: threading.Event = field(default_factory=threading.Event)
    _worker_queue: queue.Queue[tuple[Future[Any], Callable[[], Any]] | None] | None = None
    _worker_thread: threading.Thread | None = None
    _worker_error: BaseException | None = None
    _closed: bool = False

    def __post_init__(self) -> None:
        atexit.register(self.close_all)

    def backend_label(self) -> str:
        provider = self._configured_cloud_provider()
        if self.config.cdp_url:
            return "playwright-cdp"
        if provider is not None:
            return f"playwright-{provider.name}"
        return "playwright-local"

    def invoke(
        self,
        action: str,
        invocation: ToolInvocation,
        *,
        vision_analyzer: BrowserVisionAnalyzer | None = None,
    ) -> Mapping[str, Any] | ExecutionResult:
        return self._run_on_worker(lambda: self._invoke_on_worker(action, invocation, vision_analyzer=vision_analyzer))

    def _invoke_on_worker(
        self,
        action: str,
        invocation: ToolInvocation,
        *,
        vision_analyzer: BrowserVisionAnalyzer | None = None,
    ) -> Mapping[str, Any] | ExecutionResult:
        session = self._session_for(invocation.session_id)
        session.last_activity = time.time()
        if action == "navigate":
            return self._navigate(session, invocation)
        if action == "snapshot":
            return self._summary(invocation, self._snapshot_payload(session, full=_bool_arg(invocation, "full")))
        if action == "click":
            target = self._target_selector(session, invocation, require=True)
            session.page.locator(target).first.click(timeout=_DEFAULT_ACTION_TIMEOUT_MS)
            return self._summary(invocation, {"success": True, "clicked": target, **self._page_identity(session)})
        if action == "type":
            target = self._target_selector(session, invocation, require=True)
            if "text" not in invocation.arguments:
                raise ValueError("tool.browser.type requires a 'text' argument")
            text = str(invocation.arguments.get("text") or "")
            locator = session.page.locator(target).first
            locator.click(timeout=_DEFAULT_ACTION_TIMEOUT_MS)
            locator.fill(text, timeout=_DEFAULT_ACTION_TIMEOUT_MS)
            return self._summary(invocation, {"success": True, "typed": text, "target": target})
        if action == "scroll":
            direction = str(invocation.arguments.get("direction") or "").strip().lower()
            amount = _int_arg(invocation, "amount", default=500)
            if direction == "up":
                amount = -abs(amount)
            elif direction == "down":
                amount = abs(amount)
            session.page.mouse.wheel(0, amount)
            return self._summary(invocation, {"success": True, "scrolled_px": amount, **self._page_identity(session)})
        if action == "back":
            session.page.go_back(wait_until="domcontentloaded", timeout=_DEFAULT_NAVIGATION_TIMEOUT_MS)
            return self._summary(invocation, {"success": True, **self._page_identity(session)})
        if action == "press":
            key = str(invocation.arguments.get("key") or "").strip()
            if not key:
                raise ValueError("tool.browser.press requires a 'key' argument")
            session.page.keyboard.press(key)
            return self._summary(invocation, {"success": True, "pressed": key, **self._page_identity(session)})
        if action == "images":
            records = session.page.evaluate(IMAGES_JS, {"maxImages": _MAX_IMAGES})
            return self._summary(invocation, {"success": True, "images": records or [], "count": len(records or [])})
        if action == "vision":
            return self._vision(session, invocation, vision_analyzer=vision_analyzer)
        if action == "console":
            return self._console(session, invocation)
        raise ValueError(f"unsupported browser action: {action}")

    def close_all(self) -> None:
        with self._worker_lock:
            if self._closed:
                return
            self._closed = True
            worker_queue = self._worker_queue
            worker_thread = self._worker_thread
        if worker_queue is None or worker_thread is None:
            return
        if threading.current_thread() is worker_thread:
            self._close_all_on_worker()
            return
        cleanup: Future[Any] = Future()
        worker_queue.put((cleanup, self._close_all_on_worker))
        try:
            cleanup.result(timeout=10)
        finally:
            worker_queue.put(None)
            worker_thread.join(timeout=10)

    def _run_on_worker(self, work: Callable[[], Any]) -> Any:
        if self._worker_thread is not None and threading.current_thread() is self._worker_thread:
            return work()
        worker_queue = self._ensure_worker()
        future: Future[Any] = Future()
        worker_queue.put((future, work))
        return future.result()

    def _ensure_worker(self) -> queue.Queue[tuple[Future[Any], Callable[[], Any]] | None]:
        with self._worker_lock:
            if self._closed:
                raise RuntimeError("browser backend is closed")
            if self._worker_queue is not None and self._worker_thread is not None and self._worker_thread.is_alive():
                return self._worker_queue
            self._worker_ready = threading.Event()
            self._worker_error = None
            self._worker_queue = queue.Queue()
            self._worker_thread = threading.Thread(
                target=self._worker_main,
                name="elephant-browser-playwright",
                daemon=True,
            )
            self._worker_thread.start()
            worker_queue = self._worker_queue
        if not self._worker_ready.wait(timeout=10):
            raise RuntimeError("browser backend worker did not start")
        if self._worker_error is not None:
            raise RuntimeError(f"browser backend could not start: {self._worker_error}") from self._worker_error
        return worker_queue

    def _worker_main(self) -> None:
        try:
            self._playwright = self.sync_playwright().start()
        except BaseException as exc:
            self._worker_error = exc
            self._worker_ready.set()
            return
        self._worker_ready.set()
        try:
            while self._worker_queue is not None:
                item = self._worker_queue.get()
                if item is None:
                    return
                future, work = item
                if not future.set_running_or_notify_cancel():
                    continue
                try:
                    future.set_result(work())
                except BaseException as exc:
                    future.set_exception(exc)
        finally:
            self._close_all_on_worker()

    def _close_all_on_worker(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            self._close_session(session)
        if self._local_browser is not None:
            try:
                self._local_browser.close()
            except Exception:
                pass
            self._local_browser = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    def _session_for(self, session_key: str) -> BrowserSession:
        with self._lock:
            existing = self._sessions.get(session_key)
            if existing is not None:
                return existing
            created = self._create_session(session_key)
            self._sessions[session_key] = created
            return created

    def _create_session(self, session_key: str) -> BrowserSession:
        if self._playwright is None:
            raise RuntimeError("Playwright is not started")
        provider = self._configured_cloud_provider()
        provider_session: CloudBrowserSession | None = None
        browser: Any | None = None
        close_browser = False
        if self.config.cdp_url:
            browser = self._playwright.chromium.connect_over_cdp(self.config.cdp_url)
            close_browser = True
        elif provider is not None:
            provider_session = provider.create_session(session_key)
            browser = self._playwright.chromium.connect_over_cdp(provider_session.cdp_url)
            close_browser = True
        else:
            if self._local_browser is None:
                self._local_browser = self._launch_local_chromium()
            browser = self._local_browser
        context = browser.contexts[0] if getattr(browser, "contexts", None) else browser.new_context()
        page = context.pages[0] if getattr(context, "pages", None) else context.new_page()
        session = BrowserSession(
            session_key=session_key,
            page=page,
            context=context,
            browser=browser,
            provider=provider,
            provider_session=provider_session,
            close_browser=close_browser,
        )
        self._attach_observers(session)
        return session

    def _launch_local_chromium(self) -> Any:
        if self._playwright is None:
            raise RuntimeError("Playwright is not started")
        try:
            return self._playwright.chromium.launch(headless=self.config.headless)
        except Exception as exc:
            if not _should_auto_install_playwright_browser(exc):
                raise
            _install_playwright_chromium(headless_only=self.config.headless)
            return self._playwright.chromium.launch(headless=self.config.headless)

    def _configured_cloud_provider(self) -> CloudBrowserProvider | None:
        providers: dict[str, CloudBrowserProvider] = {
            "browser-use": BrowserUseProvider(),
            "browserbase": BrowserbaseProvider(),
            "firecrawl": FirecrawlProvider(),
        }
        if self.config.cloud_provider in {"", "local", "none"}:
            if self.config.cloud_provider in {"local", "none"}:
                return None
            for key in ("browser-use", "browserbase", "firecrawl"):
                provider = providers[key]
                if provider.is_configured():
                    return provider
            return None
        provider = providers.get(self.config.cloud_provider)
        if provider is None:
            raise RuntimeError(f"unsupported browser cloud provider: {self.config.cloud_provider}")
        if not provider.is_configured():
            raise RuntimeError(f"browser cloud provider is not configured: {self.config.cloud_provider}")
        return provider

    def _attach_observers(self, session: BrowserSession) -> None:
        def _console(message: Any) -> None:
            try:
                message_type = str(getattr(message, "type", "log"))
                text = str(getattr(message, "text", message))
            except Exception:
                message_type = "log"
                text = str(message)
            session.console_messages.append(f"{message_type}: {text}")
            del session.console_messages[:-80]

        def _page_error(error: Any) -> None:
            session.js_errors.append(str(error))
            del session.js_errors[:-80]

        try:
            session.page.on("console", _console)
            session.page.on("pageerror", _page_error)
        except Exception:
            pass

    def _navigate(self, session: BrowserSession, invocation: ToolInvocation) -> Mapping[str, Any]:
        url = _normalized_url(str(invocation.arguments.get("url") or ""))
        if not url:
            raise ValueError("tool.browser.navigate requires a 'url' argument")
        self._guard_url(url)
        session.page.goto(url, wait_until="domcontentloaded", timeout=_DEFAULT_NAVIGATION_TIMEOUT_MS)
        final_url = str(getattr(session.page, "url", url) or url)
        if final_url and final_url != url:
            self._guard_url(final_url)
        snapshot = self._snapshot_payload(session, full=False)
        payload: dict[str, Any] = {
            "success": True,
            "url": final_url,
            "title": snapshot.get("title", ""),
            "backend": self.backend_label(),
            "snapshot": snapshot.get("snapshot", ""),
            "element_count": snapshot.get("element_count", 0),
        }
        if session.provider_session is not None:
            payload["cloud_provider"] = session.provider_session.provider_name
            payload["cloud_features"] = dict(session.provider_session.features)
        return self._summary(invocation, payload)

    def _snapshot_payload(self, session: BrowserSession, *, full: bool) -> dict[str, Any]:
        data = session.page.evaluate(
            SNAPSHOT_JS,
            {
                "full": full,
                "compactLimit": _SNAPSHOT_COMPACT_LIMIT,
                "fullLimit": _SNAPSHOT_FULL_LIMIT,
                "maxElements": _MAX_REF_ELEMENTS,
            },
        ) or {}
        elements = tuple(data.get("elements") or ())
        session.refs = {
            str(element.get("ref")): _ref_selector(str(element.get("ref")))
            for element in elements
            if element.get("ref")
        }
        lines = self._format_snapshot(data)
        return {
            "success": True,
            "title": str(data.get("title") or ""),
            "url": str(data.get("url") or ""),
            "snapshot": lines,
            "element_count": int(data.get("elementCount") or len(elements)),
        }

    def _format_snapshot(self, data: Mapping[str, Any]) -> str:
        lines: list[str] = []
        title = str(data.get("title") or "").strip()
        url = str(data.get("url") or "").strip()
        if title:
            lines.append(title)
        if url:
            lines.append(f"source: {url}")
        elements = data.get("elements") or ()
        if elements:
            lines.append("interactive elements:")
            for element in elements:
                if not isinstance(element, Mapping):
                    continue
                ref = str(element.get("ref") or "")
                role = str(element.get("role") or element.get("tag") or "element")
                label = str(element.get("label") or "").strip()
                disabled = " disabled" if element.get("disabled") else ""
                href = str(element.get("href") or "").strip()
                suffix = f" href={href}" if href else ""
                lines.append(f"- [{ref}] {role}{disabled} \"{label}\"{suffix}")
        text = str(data.get("text") or "").strip()
        if text:
            lines.append("page text:")
            lines.append(text)
        return "\n".join(lines).strip() or "browser page is ready"

    def _target_selector(self, session: BrowserSession, invocation: ToolInvocation, *, require: bool) -> str:
        ref = str(invocation.arguments.get("ref") or "").strip()
        selector = str(invocation.arguments.get("selector") or "").strip()
        if ref:
            if not ref.startswith("@"):
                ref = f"@{ref}"
            return session.refs.get(ref) or _ref_selector(ref)
        if selector:
            return selector
        if require:
            raise ValueError("browser action requires either a 'ref' or 'selector' argument")
        return ""

    def _vision(
        self,
        session: BrowserSession,
        invocation: ToolInvocation,
        *,
        vision_analyzer: BrowserVisionAnalyzer | None = None,
    ) -> Mapping[str, Any]:
        prompt = str(invocation.arguments.get("question") or invocation.arguments.get("prompt") or "").strip()
        annotate = _bool_arg(invocation, "annotate")
        self.config.screenshots_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = self.config.screenshots_dir / f"browser_screenshot_{uuid4().hex}.png"
        annotations = 0
        try:
            if annotate:
                annotations = int(session.page.evaluate(ANNOTATE_JS) or 0)
            session.page.screenshot(path=str(screenshot_path), full_page=True)
        finally:
            if annotate:
                try:
                    session.page.evaluate(CLEAR_ANNOTATIONS_JS)
                except Exception:
                    pass
        snapshot = self._snapshot_payload(session, full=False)
        page_identity = self._page_identity(session)
        payload = {
            "success": True,
            "analysis": "Screenshot captured. A multimodal analyzer is not configured on this backend.",
            "question": prompt,
            "screenshot_path": str(screenshot_path),
            "annotated_ref_count": annotations,
            "snapshot": snapshot.get("snapshot", ""),
            **page_identity,
        }
        _apply_vision_analysis(
            payload,
            vision_analyzer,
            session_id=invocation.session_id,
            invocation_id=invocation.invocation_id,
            question=prompt,
            screenshot_path=screenshot_path,
            page_url=str(page_identity.get("url") or snapshot.get("url") or ""),
            page_title=str(page_identity.get("title") or snapshot.get("title") or ""),
            page_snapshot=str(snapshot.get("snapshot") or ""),
            metadata={
                "backend": self.backend_label(),
                "annotated_ref_count": annotations,
                "element_count": snapshot.get("element_count", 0),
            },
        )
        return self._summary(invocation, payload, artifacts=(str(screenshot_path),))

    def _console(self, session: BrowserSession, invocation: ToolInvocation) -> Mapping[str, Any]:
        expression = invocation.arguments.get("expression")
        if expression is not None and str(expression).strip():
            result = session.page.evaluate(str(expression))
            payload = {"success": True, "result": result, "result_type": type(result).__name__}
            return self._summary(invocation, payload)
        payload = {
            "success": True,
            "console_messages": tuple(session.console_messages),
            "js_errors": tuple(session.js_errors),
            "total_messages": len(session.console_messages),
            "total_errors": len(session.js_errors),
        }
        if _bool_arg(invocation, "clear"):
            session.console_messages.clear()
            session.js_errors.clear()
        return self._summary(invocation, payload)

    def _guard_url(self, url: str) -> None:
        if _SECRET_RE.search(url):
            raise ValueError("blocked browser navigation: URL appears to contain an API key or token")
        if not self.config.allow_private_urls and not self._is_local_backend() and _is_private_url(url):
            raise ValueError("blocked browser navigation: private/internal URLs are disabled for remote browser backends")

    def _is_local_backend(self) -> bool:
        return not self.config.cdp_url and self._configured_cloud_provider() is None

    def _page_identity(self, session: BrowserSession) -> dict[str, str]:
        title = ""
        url = ""
        try:
            title = str(session.page.title() or "")
        except Exception:
            pass
        try:
            url = str(getattr(session.page, "url", "") or "")
        except Exception:
            pass
        return {"title": title, "url": url}

    def _summary(
        self,
        invocation: ToolInvocation,
        payload: Mapping[str, Any],
        *,
        artifacts: tuple[str, ...] = (),
    ) -> Mapping[str, Any]:
        return {
            "execution_id": invocation.invocation_id,
            "summary": json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            "outcome": "success" if payload.get("success", True) else "error",
            "produced_artifact_ids": artifacts,
            "side_effects": ("browser",),
        }

    def _close_session(self, session: BrowserSession) -> None:
        if session.provider is not None and session.provider_session is not None:
            try:
                session.provider.close_session(session.provider_session.session_id)
            except Exception:
                pass
        if session.context is not None:
            try:
                session.context.close()
            except Exception:
                pass
        if session.close_browser and session.browser is not None:
            try:
                session.browser.close()
            except Exception:
                pass


@dataclass(slots=True)
class CamofoxBrowserBackend(BrowserToolBackend):
    config: BrowserBackendConfig
    _sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def __post_init__(self) -> None:
        atexit.register(self.close_all)

    def backend_label(self) -> str:
        return "camofox-rest"

    def invoke(
        self,
        action: str,
        invocation: ToolInvocation,
        *,
        vision_analyzer: BrowserVisionAnalyzer | None = None,
    ) -> Mapping[str, Any] | ExecutionResult:
        if action == "navigate":
            return self._navigate(invocation)
        session = self._require_session(invocation.session_id)
        if action == "snapshot":
            return self._summary(invocation, self._snapshot_payload(session))
        if action == "click":
            ref = _ref_arg(invocation)
            payload = self._post(f"/tabs/{session['tab_id']}/click", {"userId": session["user_id"], "ref": ref.lstrip("@")})
            return self._summary(invocation, {"success": True, "clicked": ref, **payload})
        if action == "type":
            ref = _ref_arg(invocation)
            text = str(invocation.arguments.get("text") or "")
            payload = self._post(
                f"/tabs/{session['tab_id']}/type",
                {"userId": session["user_id"], "ref": ref.lstrip("@"), "text": text},
            )
            return self._summary(invocation, {"success": True, "typed": text, **payload})
        if action == "scroll":
            direction = str(invocation.arguments.get("direction") or "down").strip().lower()
            payload = self._post(
                f"/tabs/{session['tab_id']}/scroll",
                {"userId": session["user_id"], "direction": direction},
            )
            return self._summary(invocation, {"success": True, "scrolled": direction, **payload})
        if action == "back":
            payload = self._post(f"/tabs/{session['tab_id']}/back", {"userId": session["user_id"]})
            return self._summary(invocation, {"success": True, **payload})
        if action == "press":
            key = str(invocation.arguments.get("key") or "").strip()
            if not key:
                raise ValueError("tool.browser.press requires a 'key' argument")
            payload = self._post(f"/tabs/{session['tab_id']}/press", {"userId": session["user_id"], "key": key})
            return self._summary(invocation, {"success": True, "pressed": key, **payload})
        if action == "images":
            snapshot = self._snapshot_payload(session).get("snapshot", "")
            images = _images_from_snapshot(str(snapshot))
            return self._summary(invocation, {"success": True, "images": images, "count": len(images)})
        if action == "vision":
            return self._vision(session, invocation, vision_analyzer=vision_analyzer)
        if action == "console":
            return self._summary(
                invocation,
                {
                    "success": True,
                    "console_messages": (),
                    "js_errors": (),
                    "note": "Camofox REST mode does not expose console buffers through this backend.",
                },
            )
        raise ValueError(f"unsupported browser action: {action}")

    def close_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            try:
                self._delete(f"/sessions/{session['user_id']}")
            except Exception:
                pass

    def _navigate(self, invocation: ToolInvocation) -> Mapping[str, Any]:
        url = _normalized_url(str(invocation.arguments.get("url") or ""))
        if not url:
            raise ValueError("tool.browser.navigate requires a 'url' argument")
        if _SECRET_RE.search(url):
            raise ValueError("blocked browser navigation: URL appears to contain an API key or token")
        session = self._session_for(invocation.session_id, url=url)
        if session.get("navigated"):
            payload = self._post(f"/tabs/{session['tab_id']}/navigate", {"userId": session["user_id"], "url": url}, timeout=60)
        else:
            payload = {"url": url}
            session["navigated"] = True
        snapshot = self._snapshot_payload(session)
        return self._summary(
            invocation,
            {
                "success": True,
                "url": payload.get("url", url),
                "title": payload.get("title", ""),
                "backend": self.backend_label(),
                "snapshot": snapshot.get("snapshot", ""),
                "element_count": snapshot.get("element_count", 0),
            },
        )

    def _session_for(self, session_key: str, *, url: str = "about:blank") -> dict[str, Any]:
        with self._lock:
            existing = self._sessions.get(session_key)
            if existing is not None:
                return existing
            user_id = f"elephant_{uuid4().hex[:12]}"
            created = self._post("/tabs", {"userId": user_id, "sessionKey": session_key[:48], "url": url}, timeout=60)
            session = {"session_key": session_key, "user_id": user_id, "tab_id": created.get("tabId")}
            if not session["tab_id"]:
                raise RuntimeError("Camofox did not return a tabId")
            self._sessions[session_key] = session
            return session

    def _require_session(self, session_key: str) -> dict[str, Any]:
        session = self._sessions.get(session_key)
        if session is None:
            raise RuntimeError("No browser session. Call tool.browser.navigate first.")
        return session

    def _snapshot_payload(self, session: Mapping[str, Any]) -> dict[str, Any]:
        data = self._get(f"/tabs/{session['tab_id']}/snapshot", params={"userId": session["user_id"]})
        snapshot = str(data.get("snapshot") or "")
        if len(snapshot) > _SNAPSHOT_FULL_LIMIT:
            snapshot = snapshot[:_SNAPSHOT_FULL_LIMIT] + f"\n[... {len(snapshot) - _SNAPSHOT_FULL_LIMIT} chars truncated]"
        return {"success": True, "snapshot": snapshot, "element_count": int(data.get("refsCount") or 0)}

    def _vision(
        self,
        session: Mapping[str, Any],
        invocation: ToolInvocation,
        *,
        vision_analyzer: BrowserVisionAnalyzer | None = None,
    ) -> Mapping[str, Any]:
        response = self._get_bytes(f"/tabs/{session['tab_id']}/screenshot", params={"userId": session["user_id"]})
        self.config.screenshots_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = self.config.screenshots_dir / f"browser_screenshot_{uuid4().hex}.png"
        screenshot_path.write_bytes(response)
        question = str(invocation.arguments.get("question") or invocation.arguments.get("prompt") or "")
        snapshot = self._snapshot_payload(session)
        payload = {
            "success": True,
            "analysis": "Screenshot captured through Camofox. A multimodal analyzer is not configured on this backend.",
            "screenshot_path": str(screenshot_path),
            "question": question,
            "snapshot": snapshot.get("snapshot", ""),
            "image_base64_sha_hint": base64.b64encode(response[:12]).decode("ascii"),
        }
        _apply_vision_analysis(
            payload,
            vision_analyzer,
            session_id=invocation.session_id,
            invocation_id=invocation.invocation_id,
            question=question,
            screenshot_path=screenshot_path,
            page_snapshot=str(snapshot.get("snapshot") or ""),
            metadata={
                "backend": self.backend_label(),
                "element_count": snapshot.get("element_count", 0),
                "tab_id": str(session.get("tab_id") or ""),
            },
        )
        return self._summary(
            invocation,
            payload,
            artifacts=(str(screenshot_path),),
        )

    def _get(self, path: str, *, params: Mapping[str, Any] | None = None, timeout: int = 30) -> dict[str, Any]:
        url = self.config.camofox_url + path
        if params:
            query = "&".join(f"{key}={value}" for key, value in params.items())
            url = f"{url}?{query}"
        return _http_json("GET", url, timeout=timeout)

    def _get_bytes(self, path: str, *, params: Mapping[str, Any] | None = None, timeout: int = 30) -> bytes:
        url = self.config.camofox_url + path
        if params:
            query = "&".join(f"{key}={value}" for key, value in params.items())
            url = f"{url}?{query}"
        request = Request(url, method="GET")
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - operator-configured local browser endpoint
            return response.read()

    def _post(self, path: str, payload: Mapping[str, Any], *, timeout: int = 30) -> dict[str, Any]:
        return _http_json(
            "POST",
            self.config.camofox_url + path,
            headers={"Content-Type": "application/json"},
            payload=payload,
            timeout=timeout,
        )

    def _delete(self, path: str) -> dict[str, Any]:
        return _http_json("DELETE", self.config.camofox_url + path, tolerate_http_errors=True)

    def _summary(
        self,
        invocation: ToolInvocation,
        payload: Mapping[str, Any],
        *,
        artifacts: tuple[str, ...] = (),
    ) -> Mapping[str, Any]:
        return {
            "execution_id": invocation.invocation_id,
            "summary": json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            "outcome": "success" if payload.get("success", True) else "error",
            "produced_artifact_ids": artifacts,
            "side_effects": ("browser",),
        }


def _normalized_url(value: str) -> str:
    url = value.strip()
    if not url:
        return ""
    if "://" not in url:
        url = f"https://{url}"
    return url


def _first_env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value is not None and value.strip():
            return value.strip()
    return ""


def _env_bool(*names: str, default: bool) -> bool:
    raw = _first_env(*names)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _should_auto_install_playwright_browser(error: BaseException) -> bool:
    if not _env_bool("ELEPHANT_BROWSER_AUTO_INSTALL", "PLAYWRIGHT_BROWSER_AUTO_INSTALL", default=True):
        return False
    message = str(error).lower()
    return "executable doesn't exist" in message or "playwright install" in message or "browserType.launch" in message


def _install_playwright_chromium(*, headless_only: bool = True) -> None:
    command = [sys.executable, "-m", "playwright", "install"]
    if headless_only:
        command.append("--only-shell")
    command.append("chromium")
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=300,
        )
    except Exception as exc:
        install_hint = "python -m playwright install --only-shell chromium" if headless_only else "python -m playwright install chromium"
        raise RuntimeError(
            "Playwright is installed, but Chromium is missing and automatic installation failed. "
            f"Run `{install_hint}` or set ELEPHANT_BROWSER_CDP_URL/CAMOFOX_URL."
        ) from exc


def _bool_arg(invocation: ToolInvocation, name: str) -> bool:
    value = invocation.arguments.get(name)
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _int_arg(invocation: ToolInvocation, name: str, *, default: int) -> int:
    try:
        return int(invocation.arguments.get(name) or default)
    except (TypeError, ValueError):
        return default


def _ref_arg(invocation: ToolInvocation) -> str:
    ref = str(invocation.arguments.get("ref") or "").strip()
    if not ref:
        raise ValueError("browser action requires a 'ref' argument in Camofox mode")
    return ref if ref.startswith("@") else f"@{ref}"


def _ref_selector(ref: str) -> str:
    safe_ref = ref.replace("\\", "\\\\").replace('"', '\\"')
    return f'[data-elephant-browser-ref="{safe_ref}"]'


def _is_private_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return True
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast


def _images_from_snapshot(snapshot: str) -> list[dict[str, str]]:
    images: list[dict[str, str]] = []
    for line in snapshot.splitlines():
        stripped = line.strip()
        if " img " not in f" {stripped} " and not stripped.startswith("img "):
            continue
        match = re.search(r'img\s+"([^"]*)"', stripped)
        if match:
            images.append({"src": "", "alt": match.group(1)})
    return images


def _apply_vision_analysis(
    payload: dict[str, Any],
    analyzer: BrowserVisionAnalyzer | None,
    *,
    session_id: str,
    invocation_id: str,
    question: str,
    screenshot_path: Path,
    page_url: str = "",
    page_title: str = "",
    page_snapshot: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> None:
    if analyzer is None:
        payload["vision_analyzer_configured"] = False
        payload["vision_setup_hint"] = "Configure a browser vision analyzer before using tool.browser.vision for visual analysis."
        return
    result = analyzer.analyze_browser_screenshot(
        session_id=session_id,
        invocation_id=invocation_id,
        question=question,
        screenshot_path=screenshot_path,
        page_url=page_url,
        page_title=page_title,
        page_snapshot=page_snapshot,
        metadata=metadata,
    )
    payload["vision_analyzer_configured"] = True
    if isinstance(result, str):
        payload["analysis"] = result
        return
    result_payload = dict(result)
    payload["vision_analysis"] = result_payload
    analysis = result_payload.get("analysis") or result_payload.get("summary") or result_payload.get("text")
    if analysis is None:
        analysis = json.dumps(result_payload, ensure_ascii=False, default=str)
    payload["analysis"] = str(analysis)


__all__ = [
    "BrowserBackendConfig",
    "BrowserbaseProvider",
    "BrowserUseProvider",
    "CamofoxBrowserBackend",
    "CloudBrowserProvider",
    "FirecrawlProvider",
    "PlaywrightBrowserBackend",
    "create_browser_backend",
    "create_playwright_browser_backend",
]
