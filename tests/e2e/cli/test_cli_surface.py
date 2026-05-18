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
                    if prompt_text.startswith("Open the wake surface proactively before the user sends a new message."):
                        content = "startup-reply:I already have the current work in view. What should I call you?"
                    elif prompt_head == "search xunzhuo liu":
                        content = (
                            "<minimax:tool_call>\n"
                            "<invoke name=\"tool.web.search\">\n"
                            "<parameter name=\"query\">xunzhuo liu</parameter>\n"
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
                    elif prompt_text.startswith("Continue the same Elephant Agent turn."):
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
                                "choices": [{"delta": {"role": "assistant", "content": chunk}}],
                            }
                            self.wfile.write(f"data: {json.dumps(event)}\n\n".encode("utf-8"))
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
                        self.wfile.write(f"data: {json.dumps(final_event)}\n\n".encode("utf-8"))
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


class CliSurfaceE2ETest(unittest.TestCase):
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

    def _run_launcher(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
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
        renderer = _render_final_visible_terminal if final_screen else _render_visible_terminal
        return renderer(output)

    def test_setup_and_grow_cli_flow(self) -> None:
        overview = self._run()
        self.assertIn("Elephant Agent CLI", overview.stdout)
        self.assertIn("personal-model-first AI", overview.stdout)
        self.assertIn("Model what matters", overview.stdout)
        self.assertIn("elephant init", overview.stdout)
        self.assertIn("elephant wake", overview.stdout)
        self.assertIn("• herd", overview.stdout)
        self.assertIn("• status", overview.stdout)
        self.assertIn("• skills", overview.stdout)
        self.assertIn("• gateway", overview.stdout)
        self.assertIn("• dashboard", overview.stdout)
        self.assertNotIn("elephant chat", overview.stdout)
        self.assertNotIn("elephant providers", overview.stdout)
        self.assertNotIn("state_dir", overview.stdout)
        self.assertNotIn("profile_dir", overview.stdout)

        blocked = self._run("wake", "--message", "hello", check=False)
        self.assertEqual(blocked.returncode, 1)
        self.assertIn("Wake blocked", blocked.stdout)
        self.assertIn("elephant init", blocked.stdout)

        setup = self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "demo",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )
        self.assertIn("Elephant Agent init", setup.stdout)
        self.assertIn("Your Elephant Agent has shaped", setup.stdout)
        self.assertIn("Demo is awake", setup.stdout)
        self.assertIn("elephant · demo", setup.stdout)
        self.assertIn("status · ready", setup.stdout)
        self.assertIn("elephant wake", setup.stdout)
        self.assertIn("elephant herd new <name>", setup.stdout)
        self.assertIn("elephant gateway setup", setup.stdout)
        self.assertIn("elephant gateway doctor", setup.stdout)

        health = self._run("status")
        self.assertIn("Elephant Agent status", health.stdout)
        self.assertIn("provider_status · ready", health.stdout)
        self.assertIn("security_status · ready", health.stdout)
        self.assertIn("active_provider_model · openai/gpt-4o-mini", health.stdout)
        self.assertRegex(health.stdout, rf"active_provider_embedding_bootstrap · {EMBEDDING_BOOTSTRAP_STATUS_PATTERN}")
        self.assertRegex(health.stdout, rf"active_provider_embedding_ready · {EMBEDDING_BOOTSTRAP_READY_PATTERN}")
        self.assertNotIn("state_focus_mode", health.stdout)

        turn = self._run("wake", "--message", "Who are you?")
        self.assertIn("Elephant Agent turn", turn.stdout)
        self.assertIn("live-chat:Who are you?", turn.stdout)
        self.assertIn("cache_hit_rate · 28.6% (2/7 input tokens cached)", turn.stdout)
        self.assertIsNotNone(self.stub.last_payload)
        system_prompt = str(self.stub.last_payload["messages"][0]["content"])  # type: ignore[index]
        self.assertIn("### Who you are", system_prompt)
        self.assertIn("You are Demo", system_prompt)
        self.assertIn("### Your own voice", system_prompt)
        self.assertIn("### What I know so far", system_prompt)
        self.assertIn("### Understanding tools", system_prompt)
        self.assertIn("Use `tool.personal_model.search`", system_prompt)
        self.assertIn("Use `tool.conversation.search`", system_prompt)
        self.assertIn("### Runtime paths", system_prompt)
        self.assertNotIn("### Episode resume", system_prompt)
        self.assertNotIn("sub-agent child Episode opened", system_prompt)
        self.assertNotIn("OpenAI-compatible provider adapter", system_prompt)
        self.assertNotIn("Never claim to be Claude Code", system_prompt)
        self.assertNotIn("generic provider shell", turn.stdout)

    def test_born_persists_runtime_secret_file_for_future_surfaces(self) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "demo",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--secret-env-var",
            "ELEPHANT_OPENROUTER_API_KEY",
        )

        secret_path = runtime_local_secret_env_path(self.state_dir)
        self.assertTrue(secret_path.exists())
        payload = json.loads(secret_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["ELEPHANT_OPENROUTER_API_KEY"], "sk-cli-test-123")

    def test_init_surfaces_embedding_bootstrap_without_exposing_state_focus_mode(self) -> None:
        setup = self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "demo",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )
        self.assertRegex(setup.stdout, rf"embedding_bootstrap_status · {EMBEDDING_BOOTSTRAP_STATUS_PATTERN}")
        self.assertRegex(setup.stdout, rf"embedding_bootstrap_ready · {EMBEDDING_BOOTSTRAP_READY_PATTERN}")
        self.assertNotIn("state_focus_mode", setup.stdout)

        config = load_global_config(global_config_path_for_state_dir(self.state_dir), state_dir=self.state_dir)
        self.assertEqual(config["models"]["provider"]["default_model"], "openai/gpt-4o-mini")

        health = self._run("status")
        self.assertRegex(health.stdout, rf"active_provider_embedding_bootstrap · {EMBEDDING_BOOTSTRAP_STATUS_PATTERN}")
        self.assertNotIn("state_focus_mode", health.stdout)

    def test_provider_embeddings_switch_between_local_default_and_configured_override(self) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "demo",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )

        initial = self._run("provider", "embeddings", "status")
        self.assertIn("Embedding provider status", initial.stdout)
        self.assertIn("source · local-default", initial.stdout)

        configured = self._run(
            "provider",
            "embeddings",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model",
            "text-embedding-3-large",
            "--dimensions",
            "1536",
            "--api-key",
            "sk-cli-test-123",
        )
        self.assertIn("Embedding provider updated", configured.stdout)
        self.assertIn("source · configured", configured.stdout)
        self.assertIn("provider_id · openai-compatible-embed", configured.stdout)

        runtime = CliRuntime.create(state_dir=self.state_dir)
        summary = dict(runtime.embedding_provider_summary())
        self.assertEqual(summary["source"], "configured")
        self.assertEqual(summary["model_id"], "text-embedding-3-large")
        self.assertEqual(summary["dimensions"], 1536)
        self.assertEqual(summary["secret_status"], "stored")

        reverted = self._run("provider", "embeddings", "local")
        self.assertIn("Embedding provider updated", reverted.stdout)
        self.assertIn("source · local-default", reverted.stdout)
        self.assertRegex(reverted.stdout, rf"embedding_bootstrap_status · {EMBEDDING_BOOTSTRAP_STATUS_PATTERN}")
        self.assertRegex(reverted.stdout, rf"embedding_bootstrap_ready · {EMBEDDING_BOOTSTRAP_READY_PATTERN}")

        refreshed = CliRuntime.create(state_dir=self.state_dir)
        refreshed_summary = dict(refreshed.embedding_provider_summary())
        self.assertEqual(refreshed_summary["source"], "local-default")
        self.assertIn(refreshed_summary["embedding_bootstrap_status"], EMBEDDING_BOOTSTRAP_STATUSES)

    def test_setup_hands_off_to_wake_surface(self) -> None:
        setup = self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "aeon",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )
        setup_contains = (
            "Elephant Agent init",
            "Your Elephant Agent has shaped",
            "Aeon is awake",
            "elephant wake",
        )
        for needle in setup_contains:
            self.assertIn(needle, setup.stdout)
        for needle in ("Welcome back !", "Gateway setup"):
            self.assertNotIn(needle, setup.stdout)

        runtime = CliRuntime.create(state_dir=self.state_dir)
        state = runtime.state_for_elephant("aeon")
        self.assertIsNotNone(state)
        assert state is not None
        manifest_expectations = (
            (state.elephant_name, "Aeon"),
            (state.identity_mode, "companion"),
            (state.initiative, "gentle"),
            (state.working_style, "companion"),
        )
        for observed, expected in manifest_expectations:
            self.assertEqual(observed, expected)
        self.assertFalse((self.profile_dir / "ELEPHANT.md").exists())
        born_elephant = self._run("herd")
        self.assertIn("aeon · current · latest", born_elephant.stdout)

    def test_interactive_wake_help_surfaces_shell_commands(self) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "aeon",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )
        shell = self._run_in_tty(
            "/help\n/exit\n",
            "wake",
            initial_delay=4.0,
        )
        shell_contains = (
            "Elephant Agent",
            "Your elephant still knows the path.",
            "Personal Model first. Curious by design.",
            "What I know",
            "Skills for you",
            "Command palette",
            "/tools  - govern built-ins and manifest-backed tools",
            "/skills  - discover, inspect, and govern skill packages",
            "/cron  - govern built-in scheduled jobs",
            "Use /skills to inspect installed skills",
            "Elephant management stays in the CLI: elephant herd new <name>",
            "Tip: type / and keep typing to open the command palette.",
            "Elephant Agent stays by your side.",
        )
        for needle in shell_contains:
            self.assertIn(needle, shell)
        shell_absent = (
            "/resume latest|<elephant-id>|<session-id>",
            "/profile",
            "/activity",
            "/audit",
            "/frozen",
            "/whoami",
            "Welcome back !",
            "startup-reply:I already have the current work in view. What should I call you?",
            "I'll get a little grounding from you first",
            "What Work Are You In Right Now?",
            "Required",
            "Good To Have Today",
            "legacy first-work prompt copy",
            "🧠 Persistent memory · long-horizon decisions · long context",
            "assistant_display_name:",
            "opening_profile_gap:",
            "current_work_summary:",
            "Open the wake surface proactively before the user sends a new message.",
        )
        for needle in shell_absent:
            self.assertNotIn(needle, shell)
        self.assertNotIn("Start with the person", shell)
        self.assertNotIn("This Episode", shell)

    def test_launcher_help_lists_gateway_skills_and_dashboard(self) -> None:
        help_output = self._run_launcher("--help")
        self.assertIn("Elephant Agent launcher", help_output.stdout)
        self.assertIn("Elephant Agent is personal-model-first AI", help_output.stdout)
        self.assertEqual(help_output.stdout.count("Elephant Agent is personal-model-first AI"), 1)
        self.assertIn("Warm, steady ways back to the elephant that remembers your path.", help_output.stdout)
        self.assertIn("🐘 Model what matters · 👂 Ask gently · 🐾 Follow the path", help_output.stdout)
        self.assertIn("Commands", help_output.stdout)
        expected_order = [
            "• init",
            "• wake",
            "• dashboard",
            "• herd",
            "• provider",
            "• facts",
            "• reflect",
            "• skills",
            "• gateway",
            "• cron",
            "• status",
        ]
        positions = [help_output.stdout.index(entry) for entry in expected_order]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("• •", help_output.stdout)
        self.assertNotIn("Usage:", help_output.stdout)

    def test_launcher_no_args_prints_single_root_cli_surface(self) -> None:
        overview = self._run_launcher()
        self.assertNotIn("Welcome", overview.stdout)
        self.assertIn("Elephant Agent CLI", overview.stdout)
        self.assertIn("🐘 Model what matters · 👂 Ask gently · 🐾 Follow the path", overview.stdout)
        self.assertIn("Elephant Agent is personal-model-first AI", overview.stdout)
        self.assertEqual(overview.stdout.count("Elephant Agent is personal-model-first AI"), 1)
        self.assertIn("elephant init", overview.stdout)
        self.assertNotIn("• •", overview.stdout)
        self.assertNotIn("Usage:", overview.stdout)

    def test_launcher_rejects_removed_health_alias(self) -> None:
        result = self._run_launcher("health", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("No such command 'health'", result.stderr)
        self.assertNotIn("health", result.stdout)

    def test_launcher_skills_surface_views_local_skill(self) -> None:
        viewed = self._run_launcher("skills", "view", "search-skill")
        self.assertIn("Elephant Agent skills", viewed.stdout)
        self.assertIn("Detail for Search Skill.", viewed.stdout)
        self.assertIn("skill_id · search-skill", viewed.stdout)
        self.assertIn("Search before editing.", viewed.stdout)

    def test_launcher_dashboard_guides_to_daemon_surface(self) -> None:
        dashboard = self._run_launcher("dashboard", "--no-open", "--skip-build", check=False)
        self.assertEqual(dashboard.returncode, 1)
        self.assertIn("Elephant Agent dashboard", dashboard.stdout)
        self.assertTrue(
            "dashboard frontend assets are not available" in dashboard.stdout
            or "dashboard is served by the Elephant daemon" in dashboard.stdout
        )
        self.assertNotIn("api_url · http://127.0.0.1:8000", dashboard.stdout)
        self.assertNotIn("ui_url · http://127.0.0.1:4174", dashboard.stdout)

    def test_grow_shell_rejects_removed_profile_command(self) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "seed",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )

        shell = self._run_in_tty(
            "/profile user set Preferred name: Bit\n/exit\n",
            "wake",
            enable_animation=True,
        )

        self.assertIn("Unknown command", shell)
        self.assertIn("/profile", shell)
        self.assertIn("Elephant Agent stays by your side.", shell)
        self.assertNotIn(f"live-chat:can you read {self.web_stub.url}?", shell)
        self.assertNotIn("<minimax:tool_call>", shell)
        self.assertNotIn("<invoke name=", shell)
        self.assertNotIn("Grow context", shell)
        self.assertNotIn("Runtime stages", shell)
        self.assertNotIn("Running a shared-runtime turn", shell)
        self.assertNotIn("/set-provider", shell)
        self.assertNotIn("/wake", shell)
        self.assertNotIn("/doctor", shell)

    def test_grow_shell_prioritizes_opening_reply_before_early_input(self) -> None:
        if not INTERACTIVE_STACK_AVAILABLE:
            self.skipTest("prompt_toolkit + rich are required for queued grow input")
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "queue",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )

        shell = self._run_in_tty(
            "slow first turn\n",
            "wake",
            followup_text="queued while growing\n/exit\n",
            followup_delay=0.2,
            enable_animation=True,
        )

        self.assertIn("Bring whatever you want to work on; I will adapt from here.", shell)
        self.assertIn("closing elephant queue", shell)
        self.assertIn("Elephant Agent stays by your side.", shell)
        self.assertNotIn("live-chat:slow first turn", shell)
        self.assertNotIn("live-chat:queued while growing", shell)

    def test_wake_turn_updates_growth_after_first_turn(self) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "seed",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )

        turn = self._run(
            "wake",
            "--message",
            "hello there",
        )
        runtime = CliRuntime.create(state_dir=self.state_dir)
        seed_session = runtime.latest_session_for_elephant("seed")
        self.assertIsNotNone(seed_session)
        assert seed_session is not None
        growth = runtime.inspect_growth(session_id=seed_session.episode_id)

        self.assertIn("live-chat:hello there", turn.stdout)
        self.assertGreaterEqual(growth.level, 1)
        self.assertGreaterEqual(growth.state.growth_score, 40)
        self.assertGreaterEqual(growth.progress_percent, 0)
        self.assertGreaterEqual(growth.score_to_next_level, 0)
        self.assertEqual(growth.state.total_experiences, 1)
        self.assertEqual(growth.state.promoted_experiences, 0)

    def test_wake_turn_levels_up_growth_on_second_turn(self) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "seed",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )

        self._run(
            "wake",
            "--message",
            "hello there",
        )
        second_turn = self._run(
            "wake",
            "--message",
            "second turn",
        )
        runtime = CliRuntime.create(state_dir=self.state_dir)
        seed_session = runtime.latest_session_for_elephant("seed")
        self.assertIsNotNone(seed_session)
        assert seed_session is not None
        growth = runtime.inspect_growth(session_id=seed_session.episode_id)
        history_messages = json.loads(runtime.snapshot_path.read_text(encoding="utf-8"))["session_context_epoch"][
            "history_messages"
        ]
        self.assertIsNotNone(seed_session.parent_episode_id)
        assert seed_session.parent_episode_id is not None
        parent = runtime.inspect_session(seed_session.parent_episode_id)

        self.assertIn("live-chat:second turn", second_turn.stdout)
        self.assertIn(seed_session.episode_id, runtime.session_ids_for_elephant("seed"))
        self.assertEqual(parent.status, "closed")
        self.assertIsNotNone(parent.parent_episode_id)
        self.assertEqual(parent.metadata.get("closed_reason"), "wake_boundary")
        self.assertFalse(any(message["content"] == "hello there" for message in history_messages))
        self.assertTrue(any("second turn" in message["content"] for message in history_messages))
        self.assertGreaterEqual(growth.level, 1)
        self.assertGreaterEqual(growth.state.growth_score, 100)
        self.assertGreaterEqual(growth.progress_percent, 0)
        self.assertGreaterEqual(growth.score_to_next_level, 0)
        self.assertGreaterEqual(growth.state.total_experiences, 2)
        self.assertEqual(growth.state.promoted_experiences, 0)

    def test_wake_turn_persists_growth_history_across_runtime_reloads(self) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "seed",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )

        self._run(
            "wake",
            "--message",
            "hello there",
        )
        self._run(
            "wake",
            "--message",
            "second turn",
        )
        runtime = CliRuntime.create(state_dir=self.state_dir)
        seed_session = runtime.latest_session_for_elephant("seed")
        self.assertIsNotNone(seed_session)
        assert seed_session is not None
        growth = runtime.inspect_growth(session_id=seed_session.episode_id)

        self.assertGreaterEqual(growth.level, 1)
        self.assertGreaterEqual(growth.state.total_dialogues, 2)
        self.assertGreaterEqual(growth.state.total_experiences, 2)
        self.assertGreater(growth.state.total_tokens, 0)

    def test_wake_interactive_entry_opens_single_herd_directly(self) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "seed",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )

        shell = self._run_in_tty(
            "",
            "wake",
            followup_text="/exit\n",
        )
        self.assertIn("Elephant Agent", shell)
        self.assertIn("What I know", shell)
        self.assertIn("Skills for you", shell)
        self.assertNotIn("This Episode", shell)
        self.assertNotIn("Choose elephant", shell)

    def test_interactive_grow_prompts_for_elephant_when_multiple_exist(self) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "seed",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )
        self._run("herd", "new", "alpha")
        self._run("herd", "new", "beta")

        shell = self._run_in_tty(
            "beta\n",
            "wake",
            followup_text="/exit\n",
        )
        self.assertIn("Choose elephant", shell)
        self.assertIn("Elephant Agent", shell)
        self.assertNotIn("This Episode", shell)
        self.assertIn("Beta", shell)

    def test_grow_debug_mode_surfaces_debug_elephant_context(self) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "seed",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )
        self._run("herd", "new", "debug")

        shell = self._run_in_tty(
            "who are you in debug\n/exit\n",
            "wake",
            "--elephant-id",
            "debug",
            "--debug",
        )
        self.assertIn("Debug", shell)
        self.assertIn("closing elephant debug", shell)
        self.assertIn("Bring whatever you want to work on; I will adapt from here.", shell)
        self.assertIn("Elephant Agent stays by your side.", shell)

    def test_non_interactive_elephant_creates_state_without_activity_command(self) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "seed",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )

        created = self._run(
            "herd",
            "new",
            "mission",
        )
        self.assertIn("state_id · state:mission", created.stdout)
        self.assertIn("personal_model_id · you", created.stdout)
        self.assertNotIn("active_goal", created.stdout)

    def test_elephant_name_is_required_and_elephants_delete_clears_named_or_all_elephants(self) -> None:
        missing_name = self._run("herd", "new", check=False)
        self.assertEqual(missing_name.returncode, 1)
        self.assertIn("Elephant blocked", missing_name.stdout)
        self.assertIn("elephant init", missing_name.stdout)

        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "seed",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )
        self._run("herd", "new", "alpha")
        self._run("herd", "new", "beta")
        prompted_elephant = self._run_in_tty(
            "Nova\n",
            "herd",
            "new",
            followup_text="/exit\n",
        )
        self.assertIn("Let's bring another elephant online.", prompted_elephant)
        self.assertIn("Elephant Agent", prompted_elephant)
        self.assertIn("Nova", prompted_elephant)

        herd = self._run("herd")
        self.assertIn("Elephant Agent herd", herd.stdout)
        self.assertIn("Available herd", herd.stdout)
        self.assertIn("alpha · latest", herd.stdout)
        self.assertIn("beta · latest", herd.stdout)
        self.assertIn("nova · current · latest", herd.stdout)
        self.assertIn("elephant herd use <name>", herd.stdout)
        self.assertIn("elephant herd delete <name>", herd.stdout)

        retired = self._run("herd", "delete", "alpha")
        self.assertIn("Elephant retired", retired.stdout)
        self.assertIn("Retired now", retired.stdout)
        self.assertIn("elephant_id · alpha", retired.stdout)

        herd_after_one = self._run("herd")
        self.assertNotIn("alpha · latest", herd_after_one.stdout)
        self.assertIn("beta · latest", herd_after_one.stdout)

        retired_all = self._run("herd", "delete", "--all")
        self.assertIn("All herd retired", retired_all.stdout)
        self.assertIn("deleted_elephants · 3", retired_all.stdout)

        herd_after_all = self._run("herd")
        self.assertIn("Current state", herd_after_all.stdout)
        self.assertIn("No herd yet.", herd_after_all.stdout)

    def test_elephants_use_selects_current_elephant_for_bare_wake(self) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "seed",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )
        self._run("herd", "new", "atlas")

        runtime = CliRuntime.create(state_dir=self.state_dir)
        latest = runtime.latest_session_for_elephant("atlas")
        assert latest is not None
        selected = self._run("herd", "use", "atlas")
        self.assertIn("Elephant selected", selected.stdout)
        self.assertIn("elephant_id · atlas", selected.stdout)
        self.assertIn("state_id · state:atlas", selected.stdout)

        current_state = runtime.repository.current_state()
        self.assertIsNotNone(current_state)
        self.assertEqual(current_state.elephant_id, "atlas")

        current = self._run("herd", "current")
        self.assertIn("Current elephant", current.stdout)
        self.assertIn("elephant_id · atlas", current.stdout)
        self.assertIn("state_id · state:atlas", current.stdout)

        self._run("wake", "--message", "Who are you?")

        current_after_wake = self._run("herd", "current")
        self.assertIn("elephant_id · atlas", current_after_wake.stdout)

    def test_elephant_message_provider_failure_renders_recovery_card(self) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "seed",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )
        self.stub.fail_chat = True

        failed = self._run(
            "herd",
            "new",
            "provider-fail",
            "--message",
            "hello from the failure path",
            check=False,
        )

        self.assertEqual(failed.returncode, 1)
        self.assertIn("Elephant Agent elephant", failed.stdout)
        self.assertIn("state_id · state:provider-fail", failed.stdout)
        self.assertIn("personal_model_id · you", failed.stdout)
        self.assertIn("A new elephant is ready.", failed.stdout)
        self.assertIn("elephant wake --elephant-id provider-fail", failed.stdout)
        self.assertNotIn("Traceback", failed.stderr)

    def test_elephant_create_persists_canonical_state_under_default_personal_model(self) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "seed",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )

        created = self._run("herd", "new", "atlas")
        self.assertIn("state_id · state:atlas", created.stdout)
        self.assertIn("personal_model_id · you", created.stdout)

        runtime = CliRuntime.create(state_dir=self.state_dir)
        elephant_state = runtime.repository.load_state("state:atlas")
        self.assertIsNotNone(elephant_state)
        self.assertEqual(elephant_state.elephant_id, "atlas")
        self.assertEqual(elephant_state.personal_model_id, "you")

    def test_elephant_create_uses_canonical_episode_storage_only(self) -> None:
        state_dir = self.root / "canonical-state"
        profile_dir = self.root / "canonical-profile"
        profile_dir.mkdir()
        (profile_dir / "profile.json").write_text(
            json.dumps(
                {
                    "profile_id": "profile-companion",
                    "display_name": "Elephant Agent",
                    "mode": "companion",
                    "preferences": ["tone:steady"],
                    "enabled_capabilities": ["cli.primary"],
                }
            ),
            encoding="utf-8",
        )
        database_path = state_dir / "elephant.sqlite3"
        RuntimeStorageRepository(database_path).bootstrap()

        runtime = CliRuntime.create(state_dir=state_dir)
        session = runtime.create_elephant(elephant_id="atlas", session_id="session-atlas")

        self.assertEqual(session.elephant_id, "atlas")
        with sqlite3.connect(database_path) as connection:
            row = connection.execute(
                "SELECT state_id, personal_model_id FROM episodes WHERE episode_id = ?",
                ("session-atlas",),
            ).fetchone()
            table_names = {
                str(table_row[0])
                for table_row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }

        self.assertNotIn("sessions", table_names)
        self.assertIsNotNone(row)
        self.assertEqual(tuple(row), ("state:atlas", "you"))

    def test_elephant_delete_removes_elephant_state_and_preserves_personal_model(self) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "seed",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )
        self._run("herd", "new", "atlas")

        runtime = CliRuntime.create(state_dir=self.state_dir)
        self.assertIsNotNone(runtime.repository.load_state("state:atlas"))

        retired = self._run("herd", "delete", "atlas")
        self.assertIn("Elephant retired", retired.stdout)
        self.assertIn("personal_model_facts · preserved", retired.stdout)

        refreshed = CliRuntime.create(state_dir=self.state_dir)
        self.assertIsNone(refreshed.repository.load_state("state:atlas"))
        self.assertIsNotNone(refreshed.repository.load_personal_model("you"))

    def test_facts_cli_lists_and_deletes_personal_model_facts(self) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "seed",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )

        runtime = CliRuntime.create(state_dir=self.state_dir)
        session = runtime.latest_session_for_elephant("seed")
        self.assertIsNotNone(session)
        assert session is not None
        listed = self._run("facts")
        self.assertIn("Elephant Agent understanding", listed.stdout)
        self.assertIn("facts ·", listed.stdout)
        self.assertIn("status_breakdown", listed.stdout)

        fact_id = "fact:stale-preference"
        runtime.repository.upsert_personal_model_fact(
            Fact(
                fact_id=fact_id,
                personal_model_id=session.personal_model_id,
                lens="identity",
                text="cleanup stale preference",
                confidence=0.7,
                committed_at=datetime.now(timezone.utc),
                source="user_explicit",
                source_episode_ids=(session.episode_id,),
                metadata={"topic": "identity.style.preference.cleanup"},
            )
        )
        populated = self._run("facts")
        self.assertIn(fact_id, populated.stdout)
        self.assertIn("cleanup stale preference", populated.stdout)

        deleted = self._run("facts", "delete", fact_id, "--reason", "cleanup stale preference")
        self.assertIn("cleanup stale preference", deleted.stdout)

        refreshed = CliRuntime.create(state_dir=self.state_dir)
        facts = refreshed.repository.list_personal_model_facts(personal_model_id=session.personal_model_id, status=("deleted",))
        entry = next((fact for fact in facts if fact.fact_id == fact_id), None)
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.status, "deleted")

        visible = self._run("facts")
        self.assertNotIn(fact_id, visible.stdout)
        self.assertNotIn("status=deleted", visible.stdout)

    def test_runtime_skill_install_persists_provenance_and_distinguishes_refresh_from_migration(self) -> None:
        runtime = CliRuntime.create(state_dir=self.state_dir)
        session = runtime.create_elephant(elephant_id="atlas")
        github_dir = self.root / "remote-github"
        github_dir.mkdir()
        (github_dir / "SKILL.md").write_text(
            "\n".join(
                [
                    "---",
                    "name: Search Skill",
                    "skill_id: search-skill",
                    "description: GitHub packaged search skill.",
                    "---",
                    "",
                    "# Search Skill",
                    "",
                    "Use GitHub search guidance.",
                ]
            ),
            encoding="utf-8",
        )
        clawhub_dir = self.root / "remote-clawhub"
        clawhub_dir.mkdir()
        (clawhub_dir / "SKILL.md").write_text(
            "\n".join(
                [
                    "---",
                    "name: Search Skill",
                    "skill_id: search-skill",
                    "description: ClawHub packaged search skill.",
                    "---",
                    "",
                    "# Search Skill",
                    "",
                    "Use ClawHub search guidance.",
                ]
            ),
            encoding="utf-8",
        )

        with mock.patch.object(
            runtime.skill_search_hub,
            "fetch",
            side_effect=[
                FetchedSkillBundle(
                    skill_id="search-skill",
                    source_id="github",
                    source_label="GitHub",
                    reference="github:openai/skills/search-skill",
                    install_reference="github:openai/skills/search-skill",
                    package_path=str(github_dir),
                    trust_level="trusted",
                    metadata={
                        "canonical_id": "openai/skills/search-skill",
                        "repo_url": "https://github.com/openai/skills",
                    },
                ),
                FetchedSkillBundle(
                    skill_id="search-skill",
                    source_id="skills-sh",
                    source_label="Skills.sh",
                    reference="skills-sh:openai/skills/search-skill",
                    install_reference="github:openai/skills/search-skill",
                    package_path=str(github_dir),
                    trust_level="trusted",
                    metadata={
                        "canonical_id": "openai/skills/search-skill",
                        "detail_url": "https://skills.sh/openai/skills/search-skill",
                        "repo_url": "https://github.com/openai/skills",
                    },
                ),
                FetchedSkillBundle(
                    skill_id="search-skill",
                    source_id="clawhub",
                    source_label="ClawHub",
                    reference="clawhub:search-skill",
                    install_reference="clawhub:search-skill",
                    package_path=str(clawhub_dir),
                    trust_level="community",
                    metadata={
                        "canonical_id": "search-skill",
                        "detail_url": "https://clawhub.ai/skills/search-skill",
                        "version": "2.0.0",
                    },
                ),
            ],
        ):
            installed = runtime.install_skill_source(
                "github:openai/skills/search-skill",
                session_id=session.episode_id,
            )
            refreshed = runtime.install_skill_source(
                "skills-sh:openai/skills/search-skill",
                session_id=session.episode_id,
            )
            migrated = runtime.install_skill_source(
                "clawhub:search-skill",
                session_id=session.episode_id,
            )

        inspected = runtime.inspect_skill("search-skill", session_id=session.episode_id)

        self.assertEqual(installed.metadata.get("install_action"), "install")
        self.assertEqual(installed.metadata.get("source_id"), "github")
        self.assertEqual(refreshed.metadata.get("install_action"), "refresh")
        self.assertEqual(refreshed.metadata.get("source_id"), "skills-sh")
        self.assertEqual(migrated.metadata.get("install_action"), "migrate")
        self.assertEqual(migrated.metadata.get("install_requester"), "operator")
        self.assertEqual(
            migrated.metadata.get("previous_install_reference"),
            "github:openai/skills/search-skill",
        )
        self.assertEqual(inspected.metadata.get("source_id"), "clawhub")
        self.assertEqual(inspected.metadata.get("trust_level"), "community")
        self.assertEqual(inspected.metadata.get("install_reference"), "clawhub:search-skill")
        self.assertEqual(inspected.metadata.get("install_action"), "migrate")
        self.assertEqual(inspected.metadata.get("install_requester"), "operator")
        self.assertEqual(inspected.metadata.get("source_version"), "2.0.0")
        self.assertEqual(
            Path(inspected.entry_path).resolve(),
            (self.root / "skills" / "installed" / "clawhub" / "search-skill" / "SKILL.md").resolve(),
        )
        self.assertFalse((self.root / "skills" / "installed" / "github" / "search-skill").resolve().exists())

    def test_noninteractive_grow_surfaces_skill_management_guidance(self) -> None:
        self._run(
            "init",
            "--non-interactive",
            "--elephant-name",
            "aeon",
            "--provider-id",
            "openai-compatible",
            "--base-url",
            self.stub.openai_base_url,
            "--model-id",
            "openai/gpt-4o-mini",
            "--api-key",
            "sk-cli-test-123",
        )

        searched_skills = self._run("wake", "--message", "search skills for bounded retrieval")
        installed_skill = self._run("wake", "--message", "install skill search-skill")
        listed_skills = self._run("wake", "--message", "what skills do you have?")

        self.assertIn(
            "execution · Use /skills search bounded retrieval",
            searched_skills.stdout,
        )
        self.assertIn(
            "execution · Use /skills install search-skill",
            installed_skill.stdout,
        )
        self.assertIn(
            "execution · I have built-in skill packages like Apple Notes",
            listed_skills.stdout,
        )


if __name__ == "__main__":
    unittest.main()
