"""Cloud browser provider adapters for browser tools."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(slots=True)
class CloudBrowserSession:
    provider_name: str
    session_id: str
    cdp_url: str
    headers: dict[str, str] = field(default_factory=dict)
    features: Mapping[str, object] = field(default_factory=dict)


class CloudBrowserProvider:
    name = "cloud"

    def is_configured(self) -> bool:
        raise NotImplementedError

    def create_session(self, task_id: str) -> CloudBrowserSession:
        raise NotImplementedError

    def close_session(self, session_id: str) -> None:
        raise NotImplementedError


class BrowserUseProvider(CloudBrowserProvider):
    name = "browser-use"

    def is_configured(self) -> bool:
        return bool(os.environ.get("BROWSER_USE_API_KEY"))

    def create_session(self, task_id: str) -> CloudBrowserSession:
        api_key = os.environ.get("BROWSER_USE_API_KEY", "")
        response = _http_json(
            "POST",
            os.environ.get("BROWSER_USE_API_URL", "https://api.browser-use.com/api/v3").rstrip("/") + "/browsers",
            headers={"X-Browser-Use-API-Key": api_key, "Content-Type": "application/json"},
            payload={"timeout": int(os.environ.get("BROWSER_USE_TIMEOUT_MINUTES", "5"))},
        )
        session_id = str(response.get("id") or "")
        cdp_url = str(response.get("cdpUrl") or response.get("connectUrl") or "")
        if not session_id or not cdp_url:
            raise RuntimeError("Browser Use did not return a usable session id and CDP URL")
        return CloudBrowserSession(
            provider_name=self.name,
            session_id=session_id,
            cdp_url=cdp_url,
            features={"browser_use": True, "task_id": task_id},
        )

    def close_session(self, session_id: str) -> None:
        api_key = os.environ.get("BROWSER_USE_API_KEY", "")
        _http_json(
            "PATCH",
            os.environ.get("BROWSER_USE_API_URL", "https://api.browser-use.com/api/v3").rstrip()
            + f"/browsers/{session_id}",
            headers={"X-Browser-Use-API-Key": api_key, "Content-Type": "application/json"},
            payload={"action": "stop"},
            tolerate_http_errors=True,
        )


class BrowserbaseProvider(CloudBrowserProvider):
    name = "browserbase"

    def is_configured(self) -> bool:
        return bool(os.environ.get("BROWSERBASE_API_KEY") and os.environ.get("BROWSERBASE_PROJECT_ID"))

    def create_session(self, task_id: str) -> CloudBrowserSession:
        api_key = os.environ.get("BROWSERBASE_API_KEY", "")
        project_id = os.environ.get("BROWSERBASE_PROJECT_ID", "")
        body: dict[str, object] = {"projectId": project_id}
        if _env_bool("BROWSERBASE_KEEP_ALIVE", default=True):
            body["keepAlive"] = True
        if _env_bool("BROWSERBASE_PROXIES", default=True):
            body["proxies"] = True
        if _env_bool("BROWSERBASE_ADVANCED_STEALTH", default=False):
            body["browserSettings"] = {"advancedStealth": True}
        if os.environ.get("BROWSERBASE_SESSION_TIMEOUT"):
            body["timeout"] = int(os.environ["BROWSERBASE_SESSION_TIMEOUT"])
        response = _http_json(
            "POST",
            os.environ.get("BROWSERBASE_BASE_URL", "https://api.browserbase.com").rstrip("/") + "/v1/sessions",
            headers={"X-BB-API-Key": api_key, "Content-Type": "application/json"},
            payload=body,
        )
        session_id = str(response.get("id") or "")
        cdp_url = str(response.get("connectUrl") or "")
        if not session_id or not cdp_url:
            raise RuntimeError("Browserbase did not return a usable session id and CDP URL")
        return CloudBrowserSession(
            provider_name=self.name,
            session_id=session_id,
            cdp_url=cdp_url,
            features={"browserbase": True, "task_id": task_id},
        )

    def close_session(self, session_id: str) -> None:
        api_key = os.environ.get("BROWSERBASE_API_KEY", "")
        project_id = os.environ.get("BROWSERBASE_PROJECT_ID", "")
        _http_json(
            "POST",
            os.environ.get("BROWSERBASE_BASE_URL", "https://api.browserbase.com").rstrip()
            + f"/v1/sessions/{session_id}",
            headers={"X-BB-API-Key": api_key, "Content-Type": "application/json"},
            payload={"projectId": project_id, "status": "REQUEST_RELEASE"},
            tolerate_http_errors=True,
        )


class FirecrawlProvider(CloudBrowserProvider):
    name = "firecrawl"

    def is_configured(self) -> bool:
        return bool(os.environ.get("FIRECRAWL_API_KEY"))

    def create_session(self, task_id: str) -> CloudBrowserSession:
        response = _http_json(
            "POST",
            os.environ.get("FIRECRAWL_API_URL", "https://api.firecrawl.dev").rstrip("/") + "/v2/browser",
            headers={"Authorization": f"Bearer {os.environ.get('FIRECRAWL_API_KEY', '')}", "Content-Type": "application/json"},
            payload={"ttl": int(os.environ.get("FIRECRAWL_BROWSER_TTL", "300"))},
        )
        session_id = str(response.get("id") or "")
        cdp_url = str(response.get("cdpUrl") or "")
        if not session_id or not cdp_url:
            raise RuntimeError("Firecrawl did not return a usable session id and CDP URL")
        return CloudBrowserSession(
            provider_name=self.name,
            session_id=session_id,
            cdp_url=cdp_url,
            features={"firecrawl": True, "task_id": task_id},
        )

    def close_session(self, session_id: str) -> None:
        _http_json(
            "DELETE",
            os.environ.get("FIRECRAWL_API_URL", "https://api.firecrawl.dev").rstrip() + f"/v2/browser/{session_id}",
            headers={"Authorization": f"Bearer {os.environ.get('FIRECRAWL_API_KEY', '')}"},
            tolerate_http_errors=True,
        )


def _http_json(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    payload: Mapping[str, Any] | None = None,
    timeout: int = 30,
    tolerate_http_errors: bool = False,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, headers=dict(headers or {}), method=method)
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - browser provider endpoint is operator configured
            data = response.read()
    except HTTPError as error:
        if tolerate_http_errors:
            return {"ok": False, "status": error.code, "body": error.read().decode("utf-8", errors="replace")}
        raise RuntimeError(f"browser provider request failed: HTTP {error.code} {error.read().decode('utf-8', errors='replace')}") from error
    except URLError as error:
        if tolerate_http_errors:
            return {"ok": False, "error": str(error)}
        raise RuntimeError(f"browser provider request failed: {error}") from error
    if not data:
        return {}
    return json.loads(data.decode("utf-8"))


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


class TencentCloudBrowserProvider(CloudBrowserProvider):
    """Cloud browser via Tencent Cloud Agent Runtime (E2B browser-v1 template).

    Creates a dedicated browser sandbox instance with Chromium pre-installed.
    The browser is controlled via CDP (Chrome DevTools Protocol) over HTTPS.
    """

    name = "tencent-cloud"

    def __init__(self, *, template: str = "browser-v1", domain: str = "", api_key: str = ""):
        self._template = template or "browser-v1"
        self._domain = domain
        self._api_key = api_key
        self._sandboxes: dict[str, Any] = {}  # session_id -> Sandbox

    def is_configured(self) -> bool:
        return bool(self._api_key or os.environ.get("E2B_API_KEY"))

    def create_session(self, task_id: str) -> CloudBrowserSession:
        if self._domain:
            os.environ["E2B_DOMAIN"] = self._domain
        if self._api_key:
            os.environ["E2B_API_KEY"] = self._api_key

        from e2b import Sandbox  # type: ignore[import-not-found]

        sandbox = Sandbox(template=self._template)
        token = str(sandbox._envd_access_token or "")
        cdp_url = f"https://{sandbox.get_host(9000)}/cdp?access_token={token}"

        self._sandboxes[sandbox.sandbox_id] = sandbox

        return CloudBrowserSession(
            provider_name=self.name,
            session_id=sandbox.sandbox_id,
            cdp_url=cdp_url,
            headers={"X-Access-Token": token} if token else {},
            features={"sandbox_id": sandbox.sandbox_id, "template": self._template},
        )

    def close_session(self, session_id: str) -> None:
        sandbox = self._sandboxes.pop(session_id, None)
        if sandbox is not None:
            try:
                sandbox.kill()
            except Exception:
                pass


__all__ = [
    "BrowserUseProvider",
    "BrowserbaseProvider",
    "CloudBrowserProvider",
    "CloudBrowserSession",
    "FirecrawlProvider",
    "TencentCloudBrowserProvider",
    "_http_json",
]
