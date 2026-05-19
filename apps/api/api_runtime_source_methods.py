"""HTTP routing for local source imports."""

from __future__ import annotations

from urllib.parse import unquote

from .api_runtime_support import APIResponse, _jsonable, _read_json_bytes
from .source_import import load_source_import_status, run_source_import


def _dispatch_sources(self, method: str, parts: tuple[str, ...], body: bytes | None) -> APIResponse:
    normalized_method = method.upper()
    if normalized_method == "POST" and parts == ("import",):
        payload = _read_json_bytes(body)
        paths_raw = payload.get("paths")
        if not isinstance(paths_raw, list) or not paths_raw:
            raise ValueError("paths must be a non-empty array")
        paths = tuple(str(path).strip() for path in paths_raw if str(path).strip())
        result = run_source_import(
            self,
            paths=paths,
            elephant_id=str(payload.get("elephant_id") or "").strip() or None,
            mode=payload.get("mode") or "manual",
        )
        return APIResponse(201, _jsonable(result))

    if normalized_method == "GET" and len(parts) == 2 and parts[0] == "imports":
        import_id = unquote(parts[1]).strip()
        result = load_source_import_status(self, import_id)
        if result is None:
            raise KeyError(import_id)
        return APIResponse(200, _jsonable(result))

    return APIResponse(404, {"error": "not_found"})


__all__ = ["_dispatch_sources"]
