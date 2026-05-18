from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest

from tests.e2e.support.installed_env import InstalledElephantEnvironment, ROOT
from tests.e2e.support.mock_provider import MockOpenAICompatibleProvider
from tests.e2e.support.processes import find_free_port, wait_for_json, wait_for_text


DASHBOARD_INDEX = ROOT / "apps" / "dashboard" / "dist" / "index.html"


def _ensure_playwright_chromium() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency contract failure
        raise AssertionError("playwright is required for the installed user journey e2e") from exc

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            browser.close()
    except Exception as exc:
        message = str(exc)
        if "Executable doesn't exist" not in message and "playwright install" not in message:
            raise
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            cwd=ROOT,
            check=True,
            text=True,
            timeout=600,
        )


def _drive_dashboard_chat(dashboard_url: str) -> None:
    _ensure_playwright_chromium()

    from playwright.sync_api import sync_playwright

    chat_url = dashboard_url.rstrip("/") + "/chat"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.goto(chat_url, wait_until="domcontentloaded")
            page.wait_for_selector("textarea", timeout=60_000)
            page.wait_for_function(
                "() => { const el = document.querySelector('textarea'); return Boolean(el && !el.disabled); }",
                timeout=60_000,
            )
            page.locator("textarea").first.fill("Reply exactly: ELEPHANT_DASHBOARD_OK")
            page.locator("textarea").first.press("Enter")
            page.wait_for_selector("text=ELEPHANT_DASHBOARD_OK", timeout=120_000)
        finally:
            browser.close()


class InstalledUserJourneyE2ETest(unittest.TestCase):
    def test_editable_install_cli_daemon_dashboard_and_mock_chat(self) -> None:
        self.assertTrue(DASHBOARD_INDEX.exists(), "dashboard assets are required; run make dashboard-build first")

        provider = MockOpenAICompatibleProvider().start()
        try:
            with InstalledElephantEnvironment() as installed:
                command_env = installed.env({"ELEPHANT_E2E_PROVIDER_API_KEY": "sk-e2e-test"})

                help_output = installed.run("--help", env=command_env)
                self.assertIn("Elephant Agent launcher", help_output.stdout)
                self.assertIn("dashboard", help_output.stdout)
                self.assertIn("wake", help_output.stdout)

                initialized = installed.run(
                    "init",
                    "--non-interactive",
                    "--provider-id",
                    "openai-compatible",
                    "--base-url",
                    provider.base_url,
                    "--model-id",
                    "openai/gpt-4o-mini",
                    "--secret-env-var",
                    "ELEPHANT_E2E_PROVIDER_API_KEY",
                    "--display-name",
                    "Installed E2E Operator",
                    env=command_env,
                    timeout=180,
                )
                self.assertIn("Your Elephant Agent has shaped", initialized.stdout)
                self.assertIn("model · openai/gpt-4o-mini", initialized.stdout)
                self.assertIn("status · ready", initialized.stdout)

                provider_status = installed.run("provider", "status", env=command_env, timeout=180)
                self.assertIn("Provider status", provider_status.stdout)
                self.assertIn("secret_status", provider_status.stdout)

                provider_models = installed.run("provider", "models", env=command_env, timeout=180)
                self.assertIn("Provider models", provider_models.stdout)
                self.assertIn("openai/gpt-4o-mini", provider_models.stdout)

                status = installed.run("status", env=command_env, timeout=180)
                self.assertIn("Elephant Agent status", status.stdout)
                self.assertIn("provider_status", status.stdout)

                created = installed.run("herd", "new", "installed-e2e", env=command_env, timeout=180)
                self.assertIn("Elephant Agent elephant", created.stdout)
                self.assertIn("installed-e2e", created.stdout)

                selected = installed.run("herd", "use", "installed-e2e", env=command_env)
                self.assertIn("installed-e2e", selected.stdout)

                wake = installed.run(
                    "wake",
                    "--elephant-id",
                    "installed-e2e",
                    "--message",
                    "Reply exactly: ELEPHANT_INSTALLED_OK",
                    env=command_env,
                    timeout=240,
                )
                self.assertIn("Elephant Agent turn", wake.stdout)
                self.assertIn("ELEPHANT_INSTALLED_OK", wake.stdout)

                facts = installed.run("facts", env=command_env)
                self.assertTrue(facts.stdout.strip())

                skills = installed.run("skills", "active", env=command_env)
                self.assertIn("Elephant Agent skills", skills.stdout)

                cron = installed.run("cron", "status", env=command_env)
                self.assertTrue(cron.stdout.strip())

                gateway = installed.run("gateway", "doctor", env=command_env)
                self.assertTrue(gateway.stdout.strip())

                port = find_free_port()
                daemon = installed.run(
                    "daemon",
                    "start",
                    "--state-dir",
                    str(installed.state_dir),
                    "--cli-state-dir",
                    str(installed.state_dir),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--log-level",
                    "DEBUG",
                    "--detach",
                    env=command_env,
                    timeout=120,
                )
                self.assertIn("Elephant daemon is now running", daemon.stdout)

                daemon_base = f"http://127.0.0.1:{port}"
                health = wait_for_json(f"{daemon_base}/healthz", timeout_seconds=45)
                self.assertEqual(health["status"], "running")

                overview = wait_for_json(f"{daemon_base}/v1/internal/dashboard/overview", timeout_seconds=45)
                self.assertIn("dashboard", overview)

                dashboard_html = wait_for_text(f"{daemon_base}/dashboard/", timeout_seconds=45)
                self.assertIn("Elephant Agent", dashboard_html)

                dashboard = installed.run(
                    "dashboard",
                    "--no-open",
                    "--skip-build",
                    env=command_env,
                    timeout=120,
                )
                dashboard_url = f"{daemon_base}/dashboard/"
                self.assertIn("Elephant Agent dashboard", dashboard.stdout)
                self.assertIn(dashboard_url, dashboard.stdout)

                _drive_dashboard_chat(dashboard_url)
        finally:
            provider.close()


if __name__ == "__main__":
    unittest.main()
