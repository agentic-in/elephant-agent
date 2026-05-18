from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from apps import dashboard_command
from apps.daemon_command import _daemon_record_path


class _FakeResponse:
    def __init__(self, payload: dict[str, object], *, status: int = 200) -> None:
        self._payload = payload
        self.status = status

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class DashboardCommandTest(unittest.TestCase):
    def test_try_daemon_dashboard_url_requires_health_and_dashboard_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            state_dir = Path(tempdir) / "herd"
            state_dir.mkdir()
            _daemon_record_path(state_dir).write_text(
                json.dumps({"host": "0.0.0.0", "port": 9876}),
                encoding="utf-8",
            )

            with mock.patch.object(
                dashboard_command.urllib.request,
                "urlopen",
                side_effect=[
                    _FakeResponse({"status": "running"}),
                    _FakeResponse({"dashboard": {}}),
                ],
            ) as urlopen:
                url = dashboard_command._try_daemon_dashboard_url(
                    dashboard_command.DashboardLaunchPlan(state_dir=state_dir),
                )

        self.assertEqual(url, "http://127.0.0.1:9876/dashboard/")
        self.assertEqual(urlopen.call_count, 2)

    def test_try_daemon_dashboard_url_returns_none_without_record(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            url = dashboard_command._try_daemon_dashboard_url(
                dashboard_command.DashboardLaunchPlan(state_dir=Path(tempdir) / "missing"),
            )

        self.assertIsNone(url)

    def test_try_daemon_dashboard_url_rejects_non_dashboard_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            state_dir = Path(tempdir) / "herd"
            state_dir.mkdir()
            _daemon_record_path(state_dir).write_text(
                json.dumps({"host": "127.0.0.1", "port": 9877}),
                encoding="utf-8",
            )

            with mock.patch.object(
                dashboard_command.urllib.request,
                "urlopen",
                side_effect=[
                    _FakeResponse({"status": "running"}),
                    _FakeResponse({"not_dashboard": {}}),
                ],
            ):
                url = dashboard_command._try_daemon_dashboard_url(
                    dashboard_command.DashboardLaunchPlan(state_dir=state_dir),
                )

        self.assertIsNone(url)

    def test_ensure_frontend_dist_uses_existing_dashboard_build(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            dist_dir = Path(tempdir) / "dist"
            index = dist_dir / "index.html"
            dist_dir.mkdir()
            index.write_text("<html></html>", encoding="utf-8")

            with (
                mock.patch.object(dashboard_command, "DASHBOARD_DIST_DIR", dist_dir),
                mock.patch.object(dashboard_command, "DASHBOARD_DIST_INDEX", index),
            ):
                self.assertTrue(dashboard_command._ensure_frontend_dist(skip_build=True))

    def test_ensure_frontend_dist_skip_build_reports_missing_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            dist_dir = Path(tempdir) / "dist"
            index = dist_dir / "index.html"

            with (
                mock.patch.object(dashboard_command, "DASHBOARD_DIST_DIR", dist_dir),
                mock.patch.object(dashboard_command, "DASHBOARD_DIST_INDEX", index),
            ):
                self.assertFalse(dashboard_command._ensure_frontend_dist(skip_build=True))

    def test_ensure_frontend_dist_builds_when_dependencies_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            app_dir = root / "dashboard"
            dist_dir = app_dir / "dist"
            index = dist_dir / "index.html"
            (app_dir / "node_modules").mkdir(parents=True)

            def fake_build(*_args: object, **_kwargs: object) -> mock.Mock:
                dist_dir.mkdir()
                index.write_text("<html></html>", encoding="utf-8")
                return mock.Mock(returncode=0)

            with (
                mock.patch.object(dashboard_command, "DASHBOARD_APP_DIR", app_dir),
                mock.patch.object(dashboard_command, "DASHBOARD_DIST_DIR", dist_dir),
                mock.patch.object(dashboard_command, "DASHBOARD_DIST_INDEX", index),
                mock.patch.object(dashboard_command.shutil, "which", return_value="/usr/bin/npm"),
                mock.patch.object(dashboard_command.subprocess, "run", side_effect=fake_build) as run,
                mock.patch.object(dashboard_command, "_print_cli_card"),
            ):
                self.assertTrue(dashboard_command._ensure_frontend_dist())

        run.assert_called_once()

    def test_run_dashboard_opens_daemon_dashboard_when_available(self) -> None:
        plan = dashboard_command.DashboardLaunchPlan(state_dir=Path("/tmp/elephant-herd"))

        with (
            mock.patch.object(dashboard_command, "_ensure_frontend_dist", return_value=True),
            mock.patch.object(
                dashboard_command,
                "_try_daemon_dashboard_url",
                return_value="http://127.0.0.1:8900/dashboard/",
            ),
            mock.patch.object(dashboard_command.webbrowser, "open", return_value=True) as open_browser,
            mock.patch.object(dashboard_command, "_print_cli_card"),
        ):
            result = dashboard_command._run_dashboard(plan, open_browser=True)

        self.assertEqual(result, 0)
        open_browser.assert_called_once_with("http://127.0.0.1:8900/dashboard/")

    def test_run_dashboard_guides_user_when_daemon_is_not_running(self) -> None:
        plan = dashboard_command.DashboardLaunchPlan(state_dir=Path("/tmp/elephant-herd"))

        with (
            mock.patch.object(dashboard_command, "_ensure_frontend_dist", return_value=True),
            mock.patch.object(dashboard_command, "_try_daemon_dashboard_url", return_value=None),
            mock.patch.object(dashboard_command, "_print_cli_card") as print_card,
        ):
            result = dashboard_command._run_dashboard(plan, open_browser=False)

        self.assertEqual(result, 1)
        self.assertEqual(print_card.call_args.args[0], "Elephant Agent dashboard")
        self.assertIn("served by the Elephant daemon", print_card.call_args.args[1])

    def test_run_dashboard_does_not_probe_daemon_without_frontend_assets(self) -> None:
        plan = dashboard_command.DashboardLaunchPlan(state_dir=Path("/tmp/elephant-herd"))

        with (
            mock.patch.object(dashboard_command, "DASHBOARD_DIST_INDEX", Path("/tmp/missing-dashboard-index.html")),
            mock.patch.object(dashboard_command, "_ensure_frontend_dist", return_value=False),
            mock.patch.object(dashboard_command, "_try_daemon_dashboard_url") as probe,
            mock.patch.object(dashboard_command, "_print_cli_card") as print_card,
        ):
            result = dashboard_command._run_dashboard(plan, open_browser=False)

        self.assertEqual(result, 1)
        probe.assert_not_called()
        self.assertIn("assets are not available", print_card.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
