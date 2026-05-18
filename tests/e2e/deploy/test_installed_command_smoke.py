from __future__ import annotations

import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time
import unittest

from tests.e2e.support.processes import find_free_port, wait_for_json

try:
    import pty
except ImportError:  # pragma: no cover - Windows fallback
    pty = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_BASE_URL_PLACEHOLDER = "REPLACE_BEFORE_RUN"


class InstalledCommandLiveSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.base_url = (os.environ.get("ELEPHANT_LIVE_PROVIDER_BASE_URL") or "").strip()
        self.model_id = (os.environ.get("ELEPHANT_LIVE_PROVIDER_MODEL") or "").strip()
        self.api_key = os.environ.get("ELEPHANT_LIVE_PROVIDER_API_KEY") or ""
        self.provider_id = (
            os.environ.get("ELEPHANT_LIVE_PROVIDER_PROVIDER_ID") or "openai-compatible"
        ).strip()
        if not self.base_url or not self.model_id or not self.api_key:
            self.skipTest(
                "installed command smoke requires ELEPHANT_LIVE_PROVIDER_BASE_URL, "
                "ELEPHANT_LIVE_PROVIDER_MODEL, and ELEPHANT_LIVE_PROVIDER_API_KEY"
            )
        self.assertTrue(
            self.base_url.startswith(("http://", "https://")),
            "installed command smoke requires an http(s) OpenAI-compatible base URL",
        )
        self.assertNotEqual(
            self.base_url,
            WORKFLOW_BASE_URL_PLACEHOLDER,
            "installed command smoke requires replacing the workflow base URL placeholder",
        )
        self.assertTrue(
            self.model_id.startswith("tke/"),
            "installed command smoke keeps the release workflow model-id prefix contract",
        )
        self.require_dashboard = os.environ.get(
            "ELEPHANT_LIVE_INSTALLED_SMOKE_REQUIRE_DASHBOARD"
        ) == "1"
        self.dashboard_index = ROOT / "apps" / "dashboard" / "dist" / "index.html"
        if self.require_dashboard:
            self.assertTrue(
                self.dashboard_index.exists(),
                "dashboard assets are required for the installed command smoke; "
                "run make dashboard-build first",
            )
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.venv_dir = self.root / "venv"
        self.home_dir = self.root / "elephant-home"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _python_bin(self) -> Path:
        if os.name == "nt":
            return self.venv_dir / "Scripts" / "python.exe"
        return self.venv_dir / "bin" / "python"

    def _elephant_bin(self) -> Path:
        if os.name == "nt":
            return self.venv_dir / "Scripts" / "elephant.exe"
        return self.venv_dir / "bin" / "elephant"

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["ELEPHANT_HOME"] = str(self.home_dir)
        env["ELEPHANT_LIVE_PROVIDER_API_KEY"] = self.api_key
        env.setdefault("TERM", "xterm-256color")
        env.setdefault("COLUMNS", "120")
        env.setdefault("LINES", "40")
        return env

    def _assert_no_secret_leak(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertNotIn(self.api_key, result.stdout)
        self.assertNotIn(self.api_key, result.stderr)

    def _run_checked(
        self,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        timeout: int = 120,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            command,
            cwd=cwd or ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            self.fail(
                "command failed: "
                + " ".join(command)
                + f"\nexit={result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        return result

    def _install_editable(self) -> None:
        self._run_checked(
            [sys.executable, "-m", "venv", str(self.venv_dir)],
            cwd=ROOT,
            timeout=120,
        )
        self._run_checked(
            [str(self._python_bin()), "-m", "pip", "install", "-e", "."],
            cwd=ROOT,
            timeout=600,
        )

    def _run_elephant(self, *args: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
        result = self._run_checked(
            [str(self._elephant_bin()), *args],
            env=self._env(),
            cwd=self.root,
            timeout=timeout,
        )
        self._assert_no_secret_leak(result)
        return result

    def _run_tui_smoke(self) -> None:
        if os.environ.get("ELEPHANT_LIVE_INSTALLED_SMOKE_SKIP_TUI") == "1":
            self.skipTest("installed TUI smoke disabled by ELEPHANT_LIVE_INSTALLED_SMOKE_SKIP_TUI")
        if pty is None:
            self.skipTest("installed TUI smoke requires a pty-capable platform")

        master_fd, slave_fd = pty.openpty()
        output = bytearray()
        process = subprocess.Popen(
            [str(self._elephant_bin())],
            cwd=self.root,
            env=self._env(),
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            text=False,
            close_fds=True,
        )
        os.close(slave_fd)
        prompt_sent = False
        exit_sent = False
        start = time.monotonic()
        deadline = start + 180
        try:
            while time.monotonic() < deadline:
                ready, _, _ = select.select([master_fd], [], [], 0.25)
                if ready:
                    try:
                        chunk = os.read(master_fd, 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    output.extend(chunk)
                if not prompt_sent and time.monotonic() - start > 4:
                    os.write(
                        master_fd,
                        "请只回复 ELEPHANT_SMOKE_OK，用于 installed TUI smoke 测试。\n".encode(
                            "utf-8"
                        ),
                    )
                    prompt_sent = True
                if b"ELEPHANT_SMOKE_OK" in output and not exit_sent:
                    os.write(master_fd, b"/exit\n")
                    exit_sent = True
                if exit_sent and process.poll() is not None:
                    break
            if b"ELEPHANT_SMOKE_OK" not in output:
                tail = output.decode("utf-8", errors="replace")[-4000:]
                self.fail(f"installed TUI smoke did not observe ELEPHANT_SMOKE_OK\n{tail}")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            os.close(master_fd)
        decoded = output.decode("utf-8", errors="replace")
        self.assertNotIn(self.api_key, decoded)

    def test_editable_install_runs_real_elephant_commands_and_tui(self) -> None:
        self._install_editable()
        self.assertTrue(self._elephant_bin().exists())

        help_output = self._run_elephant("--help")
        for command_name in ("init", "status", "provider", "herd", "wake", "skills", "gateway", "cron", "dashboard"):
            with self.subTest(command_name=command_name):
                self.assertIn(command_name, help_output.stdout)
        self.assertNotIn("chat", help_output.stdout)

        initialized = self._run_elephant(
            "init",
            "--non-interactive",
            "--provider-id",
            self.provider_id,
            "--base-url",
            self.base_url,
            "--model-id",
            self.model_id,
            "--secret-env-var",
            "ELEPHANT_LIVE_PROVIDER_API_KEY",
            "--display-name",
            "Installed Smoke Operator",
            timeout=180,
        )
        self.assertIn("Birth complete", initialized.stdout)
        self.assertIn("provider_status: ready", initialized.stdout)

        provider_status = self._run_elephant("provider", "status", timeout=180)
        self.assertIn("Provider status", provider_status.stdout)
        self.assertIn("secret_status · stored", provider_status.stdout)

        provider_models = self._run_elephant("provider", "models", timeout=180)
        self.assertIn("Provider models", provider_models.stdout)

        status = self._run_elephant("status", timeout=180)
        self.assertIn("Elephant Agent status", status.stdout)
        self.assertIn("provider_status: ready", status.stdout)

        elephant = self._run_elephant("herd", "new", "installed-smoke", timeout=180)
        self.assertIn("Elephant Agent elephant", elephant.stdout)
        self.assertIn("elephant_id: installed-smoke", elephant.stdout)

        herd = self._run_elephant("herd", timeout=120)
        self.assertIn("installed-smoke", herd.stdout)

        selected = self._run_elephant("herd", "use", "installed-smoke", timeout=120)
        self.assertIn("installed-smoke", selected.stdout)

        wake = self._run_elephant(
            "wake",
            "--elephant-id",
            "installed-smoke",
            "--message",
            "Reply exactly: ELEPHANT_SMOKE_OK",
            timeout=240,
        )
        self.assertIn("Elephant Agent turn", wake.stdout)
        self.assertIn(f"provider_id: {self.provider_id}", wake.stdout)
        self.assertIn(f"provider_model_id: {self.model_id}", wake.stdout)

        facts = self._run_elephant("facts", timeout=120)
        self.assertTrue(facts.stdout.strip())

        skills = self._run_elephant("skills", "active", timeout=120)
        self.assertIn("Elephant Agent skills", skills.stdout)

        cron = self._run_elephant("cron", "status", timeout=120)
        self.assertTrue(cron.stdout.strip())

        gateway = self._run_elephant("gateway", "doctor", timeout=120)
        self.assertTrue(gateway.stdout.strip())

        if self.dashboard_index.exists():
            daemon_port = find_free_port()
            state_dir = self.home_dir / "herd"
            try:
                daemon = self._run_elephant(
                    "daemon",
                    "start",
                    "--state-dir",
                    str(state_dir),
                    "--cli-state-dir",
                    str(state_dir),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(daemon_port),
                    "--detach",
                    timeout=120,
                )
                self.assertIn("Elephant daemon is now running", daemon.stdout)
                daemon_base = f"http://127.0.0.1:{daemon_port}"
                wait_for_json(f"{daemon_base}/healthz", timeout_seconds=45)
                dashboard = self._run_elephant("dashboard", "--no-open", "--skip-build", timeout=120)
                self.assertIn("Elephant Agent dashboard", dashboard.stdout)
                self.assertIn(f"{daemon_base}/dashboard/", dashboard.stdout)
            finally:
                self._run_checked(
                    [
                        str(self._elephant_bin()),
                        "daemon",
                        "stop",
                        "--state-dir",
                        str(state_dir),
                        "--timeout",
                        "5",
                        "--force",
                    ],
                    env=self._env(),
                    cwd=self.root,
                    timeout=30,
                )
        else:
            dashboard_help = self._run_elephant("dashboard", "--help", timeout=120)
            self.assertIn("dashboard", dashboard_help.stdout)

        self._run_tui_smoke()


if __name__ == "__main__":
    unittest.main()
