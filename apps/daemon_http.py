"""aiohttp Application for the unified Elephant daemon HTTP server."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("elephant.daemon")


def create_daemon_aiohttp_app(*, daemon: Any):
    """Build an ``aiohttp.web.Application`` for the daemon.

    Routes:
        GET  /healthz          → daemon + service health
        POST {event_path}      → gateway HTTP event handler
        GET  /api/adapters     → list adapters and their statuses
        POST /api/adapters/{key}/start → dynamically start an adapter
        POST /api/adapters/{key}/stop  → dynamically stop an adapter
        ANY  /v1/{path:.*}     → Dashboard API (dispatch bridge)
        GET  /dashboard/{path:.*} → Dashboard static assets
        GET  /                  → SPA fallback (index.html)

    Returns:
        ``(app, access_log)`` tuple for use with ``AppRunner``.
    """
    try:
        from aiohttp import web
    except ImportError as exc:
        raise ImportError("aiohttp is required for the daemon HTTP server") from exc

    app = web.Application()
    app["daemon"] = daemon

    # Enable access logging for request-level observability
    access_log = logging.getLogger("aiohttp.access")

    # ── Daemon management routes ──
    app.router.add_get("/healthz", _handle_healthz)
    app.router.add_get("/api/adapters", _handle_adapters_list)
    app.router.add_post("/api/adapters/{key}/start", _handle_adapter_start)
    app.router.add_post("/api/adapters/{key}/stop", _handle_adapter_stop)

    # Register HTTP routes from GatewayHttpService instances
    _register_gateway_http_routes(app, daemon)

    # ── Dashboard API bridge (dispatch → aiohttp) ──
    api_app = getattr(daemon, "_dashboard_api_app", None)
    if api_app is not None:
        app.router.add_route("*", "/v1/{path:.*}", _handle_dashboard_api)
        logger.info("dashboard API bridge enabled at /v1/")

    # ── Dashboard static assets ──
    static_dir = _resolve_dashboard_static_dir(daemon)
    if static_dir is not None:
        # Serve at /dashboard/… so the URL is /dashboard/assets/…, /dashboard/favicon.png, etc.
        app.router.add_get("/dashboard/{path:.*}", _handle_dashboard_static)
        # Also serve /assets/… and /favicon.png from the dist root so that
        # HTML references using absolute paths (e.g. <script src="/assets/…">)
        # resolve correctly even when the SPA is served under /dashboard/.
        app.router.add_get("/assets/{path:.*}", _handle_dashboard_assets)
        app.router.add_get("/favicon.png", _handle_dashboard_favicon)
        app.router.add_get("/", _handle_dashboard_spa_fallback)
        app["dashboard_static_dir"] = static_dir
        logger.info("dashboard static assets served from %s", static_dir)

    return app, access_log


# ── Dashboard API Bridge ──────────────────────────────────────────


async def _handle_dashboard_api(request: Any) -> Any:
    """Bridge aiohttp requests to ElephantAPIApp.dispatch().

    The API app's ``dispatch(method, path, body) -> APIResponse`` method
    is framework-agnostic — it accepts plain ``str``/``bytes`` and returns
    a dataclass with ``status_code``, ``payload``, and ``headers``.  We
    adapt the aiohttp request to that interface and convert the response
    back to an aiohttp ``web.Response``.
    """
    from aiohttp import web

    daemon = request.app["daemon"]
    api_app = getattr(daemon, "_dashboard_api_app", None)
    if api_app is None:
        return web.json_response({"error": "dashboard API not available"}, status=503)

    method = request.method
    # dispatch() expects paths like /v1/providers/... but the route
    # capture group only contains the part after /v1/.
    sub_path = request.match_info.get("path", "")
    path_info = "/v1/" + sub_path if sub_path else "/v1/"

    body = await request.read()
    body_bytes = body if body else None

    try:
        response = api_app.dispatch(method, path_info, body_bytes)
    except Exception as exc:
        logger.error("dashboard API dispatch failed: %s", exc, exc_info=True)
        return web.json_response({"error": "internal_error", "detail": str(exc)}, status=500)

    # Build aiohttp response from APIResponse
    resp = web.json_response(response.payload, status=response.status_code)
    for header_name, header_value in response.headers:
        if header_name.lower() != "content-type":
            resp.headers[header_name] = header_value
    return resp


# ── Dashboard Static Assets ───────────────────────────────────────


def _resolve_dashboard_static_dir(daemon: Any) -> Path | None:
    """Locate the dashboard ``dist/`` directory.

    Checks (in order):
      1. ``apps/dashboard/dist/`` relative to the repo root (dev checkout).
      2. ``<install_root>/dashboard/dist/`` (installed package).

    Returns *None* when no static assets are found (non-fatal — the
    dashboard is an optional surface).
    """
    # Dev checkout: apps/dashboard/dist/
    repo_root = Path(__file__).resolve().parents[1]
    dev_dist = repo_root / "apps" / "dashboard" / "dist"
    if (dev_dist / "index.html").is_file():
        return dev_dist

    # Installed package: <install_root>/dashboard/dist/
    try:
        from packages.runtime_layout import infer_install_root_from_state_dir
        install_root = infer_install_root_from_state_dir(daemon.cli_state_dir)
        installed_dist = install_root / "dashboard" / "dist"
        if (installed_dist / "index.html").is_file():
            return installed_dist
    except Exception:
        pass

    return None


async def _handle_dashboard_static(request: Any) -> Any:
    """Serve a dashboard static asset file."""
    from aiohttp import web

    static_dir: Path | None = request.app.get("dashboard_static_dir")
    if static_dir is None:
        return web.json_response({"error": "dashboard assets not available"}, status=404)

    relative = request.match_info.get("path", "index.html") or "index.html"
    candidate = (static_dir / relative).resolve()

    # Path traversal protection
    if static_dir.resolve() not in candidate.parents and candidate != static_dir.resolve():
        candidate = static_dir / "index.html"

    if not candidate.is_file():
        # SPA fallback: serve index.html for unknown routes
        candidate = static_dir / "index.html"

    if not candidate.is_file():
        return web.json_response({"error": "dashboard assets not found"}, status=404)

    return web.FileResponse(candidate)


async def _handle_dashboard_assets(request: Any) -> Any:
    """Serve files from the ``assets/`` subdirectory of the dashboard dist."""
    from aiohttp import web

    static_dir: Path | None = request.app.get("dashboard_static_dir")
    if static_dir is None:
        return web.json_response({"error": "dashboard assets not available"}, status=404)

    relative = request.match_info.get("path", "")
    if not relative:
        return web.json_response({"error": "not found"}, status=404)

    candidate = (static_dir / "assets" / relative).resolve()

    # Path traversal protection
    assets_dir = (static_dir / "assets").resolve()
    if assets_dir not in candidate.parents and candidate != assets_dir:
        return web.json_response({"error": "not found"}, status=404)

    if not candidate.is_file():
        return web.json_response({"error": "not found"}, status=404)

    return web.FileResponse(candidate)


async def _handle_dashboard_favicon(request: Any) -> Any:
    """Serve ``favicon.png`` from the dashboard dist root."""
    from aiohttp import web

    static_dir: Path | None = request.app.get("dashboard_static_dir")
    if static_dir is None:
        return web.json_response({"error": "dashboard assets not available"}, status=404)

    favicon = static_dir / "favicon.png"
    if not favicon.is_file():
        return web.json_response({"error": "favicon not found"}, status=404)

    return web.FileResponse(favicon)


async def _handle_dashboard_spa_fallback(request: Any) -> Any:
    """Serve ``index.html`` for the root path (SPA entry point)."""
    from aiohttp import web

    static_dir: Path | None = request.app.get("dashboard_static_dir")
    if static_dir is None:
        return web.json_response({"error": "dashboard assets not available"}, status=404)

    index = static_dir / "index.html"
    if not index.is_file():
        return web.json_response({"error": "dashboard assets not found"}, status=404)

    return web.FileResponse(index)


def _register_gateway_http_routes(app: Any, daemon: Any) -> None:
    """Register POST routes for all GatewayHttpService instances."""
    from apps.gateway.plugins import GatewayHttpService

    for key, service in daemon._http_services.items():
        if not isinstance(service, GatewayHttpService):
            continue
        http_paths = service.http_paths
        for path in http_paths:
            register_event_route(app, path, service, key)


def register_event_route(app: Any, path: str, service: Any, service_key: str) -> None:
    """Register a single POST route for a gateway HTTP service.

    Public API so that ``ServiceDaemon._register_http_routes_for_service`` can
    add routes for dynamically started adapters.
    """
    from aiohttp import web

    async def handler(request: Any) -> Any:
        """Handle an incoming HTTP event and dispatch to the gateway service."""
        # Check if the service has been stopped
        daemon = request.app.get("daemon")
        if daemon is not None:
            status = daemon._service_statuses.get(service_key)
            if status is not None and status.status in ("stopped", "skipped"):
                return web.json_response(
                    {"ok": False, "error": "service stopped"},
                    status=503,
                )

        try:
            payload = await request.json()
        except Exception:
            return web.json_response(
                {"ok": False, "error": "invalid JSON body"},
                status=400,
            )

        try:
            status_text, response_body = service.handle_http_event(
                payload,
                path=path,
            )
        except Exception as exc:
            logger.error("HTTP event handler failed for %s: %s", service_key, exc)
            return web.json_response(
                {"ok": False, "error": str(exc)},
                status=500,
            )

        # Parse HTTP status code from status_text (e.g. "200 OK" → 200)
        status_code = 200
        if isinstance(status_text, str):
            parts = status_text.split(" ", 1)
            try:
                status_code = int(parts[0])
            except (ValueError, IndexError):
                pass

        return web.json_response(response_body, status=status_code)

    # Normalize path: ensure it starts with /
    normalized_path = path if path.startswith("/") else f"/{path}"
    app.router.add_post(normalized_path, handler)
    logger.info("registered POST %s → %s", normalized_path, service_key)


# ── API Handlers ─────────────────────────────────────────────────


async def _handle_healthz(request: Any) -> Any:
    """Return daemon health status."""
    from aiohttp import web

    daemon = request.app["daemon"]
    status = daemon.get_status()

    # Determine overall HTTP status code
    http_status = 200 if status["status"] == "running" else 503

    return web.json_response(status, status=http_status)


async def _handle_adapters_list(request: Any) -> Any:
    """GET /api/adapters — List all adapters and their statuses."""
    from aiohttp import web

    daemon = request.app["daemon"]
    status = daemon.get_status()
    return web.json_response(status.get("services", {}))


async def _handle_adapter_start(request: Any) -> Any:
    """POST /api/adapters/{key}/start — Dynamically start an adapter."""
    from aiohttp import web

    daemon = request.app["daemon"]
    key = request.match_info["key"]
    result = await daemon.start_adapter(key)

    status_code = 200
    if result.get("status") == "skipped":
        status_code = 403
    elif result.get("status") == "error":
        status_code = 500

    return web.json_response(result, status=status_code)


async def _handle_adapter_stop(request: Any) -> Any:
    """POST /api/adapters/{key}/stop — Dynamically stop an adapter."""
    from aiohttp import web

    daemon = request.app["daemon"]
    key = request.match_info["key"]
    result = await daemon.stop_adapter(key)
    return web.json_response(result, status=200)
