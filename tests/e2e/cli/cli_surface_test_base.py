from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from apps.provider_runtime import runtime_local_secret_env_path
from pathlib import Path
import pty
import re
import select
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from apps.cli.runtime import CliRuntime
from packages.contracts import Fact
from packages.runtime_config import global_config_path_for_state_dir, load_global_config
from packages.storage import RuntimeStorageRepository
from packages.skills import FetchedSkillBundle

ROOT = Path(__file__).resolve().parents[3]
CSI_PATTERN = re.compile(r"\x1b\[([0-9;?]*)([ -/]*)([@-~])")
EMBEDDING_BOOTSTRAP_STATUS_PATTERN = r"(ready|pending|downloading|failed)"
EMBEDDING_BOOTSTRAP_READY_PATTERN = r"(ready|steadying|orienting|attention-needed)"
EMBEDDING_BOOTSTRAP_STATUSES = {"ready", "pending", "downloading", "failed"}

try:
    import prompt_toolkit  # noqa: F401
    import rich  # noqa: F401

    INTERACTIVE_STACK_AVAILABLE = True
except ModuleNotFoundError:
    INTERACTIVE_STACK_AVAILABLE = False


def _render_visible_terminal(output: str) -> str:
    lines = [""]
    row = 0
    col = 0
    index = 0

    def ensure_row(target: int) -> None:
        while len(lines) <= target:
            lines.append("")

    while index < len(output):
        char = output[index]
        if char == "\x1b":
            match = CSI_PATTERN.match(output, index)
            if match is None:
                index += 1
                continue
            params, _, command = match.groups()
            if command == "A":
                amount = int(params or "1")
                row = max(0, row - amount)
                col = min(col, len(lines[row]))
            elif command == "K":
                ensure_row(row)
                lines[row] = lines[row][:col]
            index = match.end()
            continue
        if char == "\r":
            col = 0
            index += 1
            continue
        if char == "\n":
            row += 1
            ensure_row(row)
            col = 0
            index += 1
            continue
        ensure_row(row)
        current = lines[row]
        if col >= len(current):
            current = current + (" " * (col - len(current))) + char
        else:
            current = current[:col] + char + current[col + 1 :]
        lines[row] = current
        col += 1
        index += 1
    return "\n".join(line.rstrip() for line in lines)


def _render_final_visible_terminal(output: str) -> str:
    lines = [""]
    row = 0
    col = 0
    index = 0

    def ensure_row(target: int) -> None:
        while len(lines) <= target:
            lines.append("")

    while index < len(output):
        char = output[index]
        if char == "\x1b":
            match = CSI_PATTERN.match(output, index)
            if match is None:
                index += 1
                continue
            params, _, command = match.groups()
            if command == "A":
                amount = int(params or "1")
                row = max(0, row - amount)
                col = min(col, len(lines[row]))
            elif command == "H" or command == "f":
                if not params:
                    row = 0
                    col = 0
                else:
                    row_param, _, col_param = params.partition(";")
                    row = max(0, int(row_param or "1") - 1)
                    col = max(0, int(col_param or "1") - 1)
                    ensure_row(row)
            elif command == "J" and params in {"", "2", "3"}:
                lines = [""]
                row = 0
                col = 0
            elif command == "K":
                ensure_row(row)
                lines[row] = lines[row][:col]
            index = match.end()
            continue
        if char == "\r":
            col = 0
            index += 1
            continue
        if char == "\n":
            row += 1
            ensure_row(row)
            col = 0
            index += 1
            continue
        ensure_row(row)
        current = lines[row]
        if col >= len(current):
            current = current + (" " * (col - len(current))) + char
        else:
            current = current[:col] + char + current[col + 1 :]
        lines[row] = current
        col += 1
        index += 1
    return "\n".join(line.rstrip() for line in lines)


class _ProviderStubServer:
    def __init__(self) -> None:
        self.last_payload: dict[str, object] | None = None
        self.payloads: list[dict[str, object]] = []
        self.last_path: str | None = None
        self.fail_chat = False
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def openai_base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    def start(self) -> "_ProviderStubServer":
        self._thread.start()
        return self

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path != "/v1/models":
                    self.send_response(404)
                    self.end_headers()
                    return
                response = {
                    "object": "list",
                    "data": [
                        {
                            "id": "openai/gpt-4o-mini",
                            "context_window": 128000,
                            "max_output_tokens": 16384,
                        },
                        {
                            "id": "openai/gpt-4.1-mini",
                            "context_window": 1047576,
                            "max_output_tokens": 32768,
                        },
                    ],
                }
                encoded = json.dumps(response).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def do_POST(self) -> None:  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                payload = json.loads(body.decode("utf-8"))
                outer.last_payload = payload
                outer.payloads.append(payload)
                outer.last_path = self.path
                if self.path == "/v1/chat/completions":
                    if outer.fail_chat:
                        response = {
                            "error": {
                                "message": "stub provider is unavailable",
                                "type": "server_error",
                            }
                        }
                        encoded = json.dumps(response).encode("utf-8")
                        self.send_response(503)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(encoded)))
                        self.end_headers()
                        self.wfile.write(encoded)
                        return
                    prompt_text = str(payload["messages"][-1]["content"])
                    prompt_head = prompt_text.splitlines()[0].strip()
                    if prompt_text.startswith(
                        "Open the wake surface proactively before the user sends a new message."
                    ):
                        content = "startup-reply:I already have the current work in view. What should I call you?"
                    elif prompt_head == "search xunzhuo liu":
                        content = (
                            "<minimax:tool_call>\n"
                            '<invoke name="tool.web.search">\n'
                            '<parameter name="query">xunzhuo liu</parameter>\n'
                            "</invoke>\n"
                            "</minimax:tool_call>"
                        )
                    elif prompt_head == "install skill search-skill":
                        content = "Use /skills install search-skill to load that package for this elephant."
                    elif prompt_head == "what skills do you have?":
                        content = "I have built-in skill packages like Apple Notes, Arxiv, GIF Search, and more. Use /skills to inspect or install them."
                    elif prompt_head == "search skills for bounded retrieval":
                        content = "Use /skills search bounded retrieval to inspect installable skill packages."
                    elif prompt_text == "slow first turn":
                        time.sleep(1.0)
                        content = "live-chat:slow first turn"
                    elif prompt_text.startswith(
                        "Continue the same Elephant Agent turn."
                    ):
                        if "tool: tool.web.search" in prompt_text:
                            content = "I searched the web and found relevant results for Xunzhuo Liu."
                        else:
                            content = "I continued the same Elephant Agent turn with the tool results."
                    else:
                        content = f"live-chat:{prompt_text}"
                    if payload.get("stream"):
                        midpoint = max(1, len(content) // 2)
                        chunks = (content[:midpoint], content[midpoint:])
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream")
                        self.send_header("Cache-Control", "no-cache")
                        self.end_headers()
                        for chunk in chunks:
                            if not chunk:
                                continue
                            event = {
                                "id": "chatcmpl-stub",
                                "model": payload["model"],
                                "choices": [
                                    {"delta": {"role": "assistant", "content": chunk}}
                                ],
                            }
                            self.wfile.write(
                                f"data: {json.dumps(event)}\n\n".encode("utf-8")
                            )
                            self.wfile.flush()
                        final_event = {
                            "id": "chatcmpl-stub",
                            "model": payload["model"],
                            "choices": [{"delta": {}, "finish_reason": "stop"}],
                            "usage": {
                                "prompt_tokens": 7,
                                "completion_tokens": 3,
                                "total_tokens": 10,
                                "prompt_tokens_details": {"cached_tokens": 2},
                            },
                        }
                        self.wfile.write(
                            f"data: {json.dumps(final_event)}\n\n".encode("utf-8")
                        )
                        self.wfile.write(b"data: [DONE]\n\n")
                        self.wfile.flush()
                        return
                    response = {
                        "id": "chatcmpl-stub",
                        "model": payload["model"],
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": content,
                                }
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 7,
                            "completion_tokens": 3,
                            "total_tokens": 10,
                            "prompt_tokens_details": {"cached_tokens": 2},
                        },
                    }
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                encoded = json.dumps(response).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format: str, *args: object) -> None:
                return

        return Handler


class _WebPageStubServer:
    def __init__(self) -> None:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/"

    def start(self) -> "_WebPageStubServer":
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
                    "<html><head><title>Liuxunzhuo</title></head>"
                    "<body><main><p>Readable web page content for Elephant Agent fetch testing.</p></main></body></html>"
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                return

        return Handler


class CliSurfaceE2ETestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.stub = _ProviderStubServer().start()
        self.web_stub = _WebPageStubServer().start()
        self.root = Path(self.tempdir.name)
        self.state_dir = self.root / "state"
        self.profile_dir = self.root / "profile"
        self.skill_root = self.root / "skills"
        self.profile_dir.mkdir()
        self.skill_root.mkdir()
        self._previous_secret = os.environ.get("ELEPHANT_OPENROUTER_API_KEY")
        self._previous_skill_paths = os.environ.get("ELEPHANT_SKILL_PATHS")
        os.environ["ELEPHANT_OPENROUTER_API_KEY"] = "sk-cli-test-123"
        os.environ["ELEPHANT_SKILL_PATHS"] = str(self.skill_root)
        (self.profile_dir / "profile.json").write_text(
            json.dumps(
                {
                    "profile_id": "profile-companion",
                    "display_name": "Elephant Agent",
                    "mode": "companion",
                    "preferences": ["tone:steady", "verbosity:concise"],
                    "enabled_capabilities": ["cli.primary"],
                }
            ),
            encoding="utf-8",
        )
        runtime = CliRuntime.create(state_dir=self.state_dir)
        runtime.update_identity_state(
            profile_id="profile-companion",
            elephant_identity_text="Be steady, precise, and durable.",
        )
        search_skill = self.skill_root / "search-skill"
        search_skill.mkdir()
        (search_skill / "SKILL.md").write_text(
            "\n".join(
                [
                    "---",
                    "name: Search Skill",
                    "description: Helps search code and notes with bounded retrieval.",
                    "---",
                    "",
                    "# Search Skill",
                    "",
                    "Search before editing.",
                ]
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        if self._previous_secret is None:
            os.environ.pop("ELEPHANT_OPENROUTER_API_KEY", None)
        else:
            os.environ["ELEPHANT_OPENROUTER_API_KEY"] = self._previous_secret
        if self._previous_skill_paths is None:
            os.environ.pop("ELEPHANT_SKILL_PATHS", None)
        else:
            os.environ["ELEPHANT_SKILL_PATHS"] = self._previous_skill_paths
        self.web_stub.close()
        self.stub.close()
        self.tempdir.cleanup()

    def _command(self, *args: str) -> list[str]:
        return [
            sys.executable,
            "-m",
            "apps.cli",
            "--state-dir",
            str(self.state_dir),
            *args,
        ]

    def _launcher_command(self, *args: str) -> list[str]:
        return [
            sys.executable,
            "-m",
            "apps.launcher",
            *args,
        ]

    def _launcher_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["ELEPHANT_HOME"] = str(self.root)
        env["ELEPHANT_HERD_DIR"] = str(self.state_dir)
        env["ELEPHANT_PROFILE_DIR"] = str(self.profile_dir)
        return env

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self._command(*args),
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=check,
        )

    def _run_launcher(
        self, *args: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self._launcher_command(*args),
            cwd=ROOT,
            env=self._launcher_env(),
            text=True,
            capture_output=True,
            check=check,
        )

    def _run_in_tty(
        self,
        input_text: str,
        *args: str,
        followup_text: str | None = None,
        followup_delay: float = 0.5,
        initial_delay: float = 0.3,
        enable_animation: bool = False,
        final_screen: bool = False,
    ) -> str:
        master_fd, slave_fd = pty.openpty()
        if not input_text.endswith("\n"):
            input_text = f"{input_text}\n"
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        if enable_animation:
            env.pop("ELEPHANT_NO_ANIMATION", None)
        else:
            env["ELEPHANT_NO_ANIMATION"] = "1"
        env["ELEPHANT_NO_WIZARD_DIALOGS"] = "1"
        process = subprocess.Popen(
            self._command(*args),
            cwd=ROOT,
            env=env,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            text=False,
        )
        os.close(slave_fd)
        try:
            time.sleep(initial_delay)
            os.write(master_fd, input_text.encode("utf-8"))
            if followup_text is not None:
                time.sleep(followup_delay)
                os.write(master_fd, followup_text.encode("utf-8"))
            chunks: list[bytes] = []
            while True:
                ready, _, _ = select.select([master_fd], [], [], 0.2)
                if ready:
                    try:
                        chunk = os.read(master_fd, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    chunks.append(chunk)
                if process.poll() is not None and not ready:
                    break
            process.wait(timeout=10)
        finally:
            os.close(master_fd)
        output = b"".join(chunks).decode("utf-8", errors="replace")
        if process.returncode != 0:
            self.fail(f"tty command exited with code {process.returncode}\n{output}")
        renderer = (
            _render_final_visible_terminal if final_screen else _render_visible_terminal
        )
        return renderer(output)
