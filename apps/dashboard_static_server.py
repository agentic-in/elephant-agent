"""Serve the packaged dashboard frontend and local API from one WSGI process."""

from __future__ import annotations

from argparse import ArgumentParser
import errno
import mimetypes
from pathlib import Path
from socketserver import ThreadingMixIn
import sys
from typing import Any, Mapping
from wsgiref.simple_server import WSGIServer, make_server

from apps.api import create_app
from packages.runtime_layout import default_cli_state_dir


class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


def _read_file(path: Path) -> bytes:
    return path.read_bytes()


def _headers_for(path: Path, *, content_length: int) -> list[tuple[str, str]]:
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return [
        ("Content-Type", content_type),
        ("Content-Length", str(content_length)),
        (
            "Cache-Control",
            "no-cache" if path.name == "index.html" else "public, max-age=31536000, immutable",
        ),
    ]


def _static_target(static_dir: Path, path: str) -> Path:
    relative = path.lstrip("/") or "index.html"
    candidate = (static_dir / relative).resolve()
    static_root = static_dir.resolve()
    if static_root not in candidate.parents and candidate != static_root:
        return static_root / "index.html"
    if candidate.is_file():
        return candidate
    return static_root / "index.html"


class DashboardStaticApp:
    def __init__(self, *, database_path: Path, static_dir: Path) -> None:
        self.api_app = create_app(database_path=database_path)
        self.static_dir = static_dir

    def __call__(self, environ: Mapping[str, Any], start_response: Any) -> list[bytes]:
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        path = str(environ.get("PATH_INFO", "/"))
        if path == "/healthz" or path.startswith("/v1/"):
            return self.api_app(environ, start_response)
        if method not in {"GET", "HEAD"}:
            start_response("405 ERROR", [("Content-Type", "text/plain; charset=utf-8")])
            return [b"method not allowed"]
        target = _static_target(self.static_dir, path)
        if not target.is_file():
            start_response("404 ERROR", [("Content-Type", "text/plain; charset=utf-8")])
            return [b"dashboard assets not found"]
        payload = _read_file(target)
        start_response("200 OK", _headers_for(target, content_length=len(payload)))
        return [] if method == "HEAD" else [payload]


def main() -> int:
    parser = ArgumentParser(description="Run the packaged Elephant Agent dashboard and API locally.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4174)
    parser.add_argument(
        "--database",
        default=str(default_cli_state_dir() / "elephant.sqlite3"),
        help="SQLite database path for CLI session state.",
    )
    parser.add_argument("--static-dir", type=Path, required=True)
    args = parser.parse_args()

    app = DashboardStaticApp(database_path=Path(args.database), static_dir=args.static_dir)
    try:
        with make_server(args.host, args.port, app, server_class=ThreadingWSGIServer) as server:
            print(f"Serving Elephant Agent dashboard on http://{args.host}:{args.port}")
            server.serve_forever()
    except KeyboardInterrupt:
        return 0
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            print(
                f"Elephant Agent dashboard could not bind http://{args.host}:{args.port}; the address is already in use.",
                file=sys.stderr,
            )
            return 1
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
