"""aiohttp Application for the unified Elephant daemon HTTP server."""

from __future__ import annotations

import json
import logging
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

    app.router.add_get("/healthz", _handle_healthz)
    app.router.add_get("/api/adapters", _handle_adapters_list)
    app.router.add_post("/api/adapters/{key}/start", _handle_adapter_start)
    app.router.add_post("/api/adapters/{key}/stop", _handle_adapter_stop)

    # Register HTTP routes from GatewayHttpService instances
    _register_gateway_http_routes(app, daemon)

    return app, access_log


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
