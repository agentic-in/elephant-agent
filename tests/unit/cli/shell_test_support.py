from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest

from apps.cli.runtime import CliRuntime
from apps.cli.shell import Console, ProductizedShell


class StubConsole:
    def __init__(self, width: int) -> None:
        self.width = width
        self.size = type("Size", (), {"width": width})()


class CaptureConsole(StubConsole):
    def __init__(self, width: int) -> None:
        super().__init__(width)
        self.printed: list[str] = []
        self.clear_calls: list[bool] = []

    def clear(self, home: bool = False) -> None:
        self.clear_calls.append(home)

    def print(self, renderable="") -> None:
        if hasattr(renderable, "plain"):
            self.printed.append(renderable.plain)
        elif hasattr(renderable, "__rich_console__"):
            console = Console(width=self.width, record=True, force_terminal=True)
            console.print(renderable)
            self.printed.append(console.export_text(styles=False).rstrip())
        else:
            self.printed.append(str(renderable))


class WebPageStubServer:
    def __init__(self) -> None:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/"

    def start(self) -> "WebPageStubServer":
        self._thread.start()
        return self

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                body = (
                    "<html><head><title>Atlas Journal</title></head>"
                    "<body><main><h1>Atlas Journal</h1>"
                    "<p>This page explains the durable elephant continuity loop.</p>"
                    "</main></body></html>"
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                return

        return Handler


class ShellTestBase(unittest.TestCase):
    def _make_shell(
        self,
        *,
        opened: str = "Shaped new",
        user_profile_text: str | None = None,
        prime_transcript: bool = False,
    ) -> ProductizedShell:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        root = Path(tmpdir.name)
        state_dir = root / "state"
        profile_dir = root / "profile"
        profile_dir.mkdir()
        (root / "profile.json").write_text(
            json.dumps(
                {
                    "profile_id": "profile-companion",
                    "display_name": "Elephant Agent",
                    "mode": "companion",
                }
            ),
            encoding="utf-8",
        )
        runtime = CliRuntime.create(state_dir=state_dir)
        runtime.update_identity_state(
            profile_id="profile-companion",
            elephant_identity_text="Stay durable.",
        )
        session = runtime.create_elephant(elephant_id="atlas")
        if user_profile_text is not None:
            runtime.update_user_state(profile_id=session.personal_model_id, text=user_profile_text)
        shell = ProductizedShell(runtime, session_id=session.session_id, opened=opened)
        if prime_transcript:
            shell._prime_transcript()
        return shell

    def _make_shell_without_identity_update(self) -> ProductizedShell:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        root = Path(tmpdir.name)
        profile_dir = root / "profile"
        profile_dir.mkdir()
        (root / "profile.json").write_text(
            json.dumps(
                {
                    "profile_id": "profile-companion",
                    "display_name": "Elephant Agent",
                    "mode": "companion",
                }
            ),
            encoding="utf-8",
        )
        runtime = CliRuntime.create(state_dir=root / "state")
        session = runtime.create_elephant(elephant_id="atlas")
        return ProductizedShell(runtime, session_id=session.episode_id, opened="Shaped new")
