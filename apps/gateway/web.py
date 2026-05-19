"""Generic WSGI app for one or more gateway HTTP services."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
from typing import Any

from .plugins import GatewayHttpService


def _json_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")


def _normalize_services(
    services: GatewayHttpService | Sequence[GatewayHttpService] | Mapping[str, GatewayHttpService],
) -> dict[str, GatewayHttpService]:
    if isinstance(services, Mapping):
        return {str(key): value for key, value in services.items()}
    if isinstance(services, Sequence) and not isinstance(services, (str, bytes, bytearray)):
        return {
            str(getattr(service, "service_key", f"service-{index}")): service for index, service in enumerate(services)
        }
    service = services
    return {str(getattr(service, "service_key", "service")): service}


def _infer_gateway_app(
    services: Mapping[str, GatewayHttpService],
    *,
    app: Any | None,
) -> Any | None:
    if app is not None:
        return app
    for service in services.values():
        candidate = getattr(service, "app", None)
        if candidate is not None:
            return candidate
    return None


def create_gateway_web_app(
    services: GatewayHttpService | Sequence[GatewayHttpService] | Mapping[str, GatewayHttpService],
    *,
    app: Any | None = None,
):
    service_map = _normalize_services(services)
    gateway_app = _infer_gateway_app(service_map, app=app)
    route_map: dict[str, GatewayHttpService] = {}
    for service in service_map.values():
        for path in service.http_paths:
            if path in route_map:
                raise ValueError(f"duplicate gateway HTTP path registered: {path}")
            route_map[path] = service

    def application(environ: Mapping[str, object], start_response: Callable[..., object]):
        path = str(environ.get("PATH_INFO") or "/")
        method = str(environ.get("REQUEST_METHOD") or "GET").upper()
        if method == "GET" and path == "/healthz":
            payload: dict[str, object] = {
                "ok": True,
                "services": {key: dict(service.describe()) for key, service in service_map.items()},
            }
            if gateway_app is not None and hasattr(gateway_app, "setup_summary"):
                payload["gateway"] = gateway_app.setup_summary()
            if len(service_map) == 1:
                key, service = next(iter(service_map.items()))
                payload[key] = dict(service.describe())
            body = _json_bytes(payload)
            start_response(
                "200 OK",
                [
                    ("Content-Type", "application/json; charset=utf-8"),
                    ("Content-Length", str(len(body))),
                ],
            )
            return [body]
        if method == "POST" and path in route_map:
            try:
                content_length = int(str(environ.get("CONTENT_LENGTH") or "0") or "0")
            except ValueError:
                content_length = 0
            stream = environ.get("wsgi.input")
            if stream is None or not hasattr(stream, "read"):
                payload = {"ok": False, "error": "missing request body stream"}
                body = _json_bytes(payload)
                start_response(
                    "400 Bad Request",
                    [
                        ("Content-Type", "application/json; charset=utf-8"),
                        ("Content-Length", str(len(body))),
                    ],
                )
                return [body]
            raw = stream.read(content_length) if content_length > 0 else stream.read()
            try:
                parsed = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                payload = {"ok": False, "error": "request body must be valid JSON"}
                body = _json_bytes(payload)
                start_response(
                    "400 Bad Request",
                    [
                        ("Content-Type", "application/json; charset=utf-8"),
                        ("Content-Length", str(len(body))),
                    ],
                )
                return [body]
            if not isinstance(parsed, dict):
                payload = {"ok": False, "error": "request body must be a JSON object"}
                body = _json_bytes(payload)
                start_response(
                    "400 Bad Request",
                    [
                        ("Content-Type", "application/json; charset=utf-8"),
                        ("Content-Length", str(len(body))),
                    ],
                )
                return [body]
            status, payload = route_map[path].handle_http_event(parsed, path=path)
            body = _json_bytes(payload)
            start_response(
                status,
                [
                    ("Content-Type", "application/json; charset=utf-8"),
                    ("Content-Length", str(len(body))),
                ],
            )
            return [body]
        payload = {
            "ok": False,
            "error": "not found",
            "available_paths": ("/healthz", *tuple(route_map.keys())),
        }
        body = _json_bytes(payload)
        start_response(
            "404 Not Found",
            [
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", str(len(body))),
            ],
        )
        return [body]

    return application


__all__ = ["create_gateway_web_app"]
