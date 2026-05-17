"""Operator dashboard launcher — opens the daemon's built-in dashboard."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any
import urllib.error
import urllib.request
import webbrowser

import typer

from apps.cli.cli_main_support import CliCardSection, _print_cli_card
from apps.cli.typer_support import run_typer_app


REPO_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_APP_DIR = REPO_ROOT / "apps" / "dashboard"
DASHBOARD_DIST_DIR = DASHBOARD_APP_DIR / "dist"
DASHBOARD_DIST_INDEX = DASHBOARD_DIST_DIR / "index.html"

DAEMON_PROBE_TIMEOUT_SECONDS = 2.0
DASHBOARD_API_PROBE_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True, slots=True)
class DashboardLaunchPlan:
    state_dir: Path


def _try_daemon_dashboard_url(plan: DashboardLaunchPlan) -> str | None:
    """If the daemon is running with a dashboard, return its URL.

    Checks the daemon runtime record for host/port, then probes
    ``/healthz`` and ``/v1/internal/dashboard/overview`` to confirm
    the dashboard API is actually serving.

    Returns *None* if the daemon is not running or the dashboard
    is not available.
    """
    from apps.daemon_command import _daemon_record_path, _load_record

    record_path = _daemon_record_path(plan.state_dir)
    if not record_path.exists():
        return None
    record = _load_record(record_path) or {}
    port = record.get("port")
    if port is None:
        return None
    host = record.get("host", "0.0.0.0")
    addr = host if host != "0.0.0.0" else "127.0.0.1"

    # Probe healthz first
    try:
        healthz_url = f"http://{addr}:{port}/healthz"
        req = urllib.request.Request(healthz_url, method="GET")
        with urllib.request.urlopen(req, timeout=DAEMON_PROBE_TIMEOUT_SECONDS) as resp:
            if resp.status != 200:
                return None
    except Exception:
        return None

    # Probe dashboard API
    try:
        dashboard_url = f"http://{addr}:{port}/v1/internal/dashboard/overview"
        req = urllib.request.Request(dashboard_url, headers={"Accept": "application/json"}, method="GET")
        with urllib.request.urlopen(req, timeout=DASHBOARD_API_PROBE_TIMEOUT_SECONDS) as resp:
            if resp.status != 200:
                return None
            payload = json.loads(resp.read().decode("utf-8"))
            if not isinstance(payload, Mapping) or not isinstance(payload.get("dashboard"), Mapping):
                return None
    except Exception:
        return None

    return f"http://{addr}:{port}/dashboard/"


def _ensure_frontend_dist(*, skip_build: bool = False, rebuild: bool = False) -> bool:
    """Ensure the dashboard ``dist/`` directory exists.

    Returns *True* if dist is available (already present or freshly built).
    Returns *False* if dist is missing and cannot be built.
    """
    if rebuild and DASHBOARD_DIST_DIR.is_dir():
        shutil.rmtree(DASHBOARD_DIST_DIR)

    if DASHBOARD_DIST_INDEX.is_file():
        return True

    if skip_build:
        return False

    npm_available = shutil.which("npm") is not None
    node_modules = DASHBOARD_APP_DIR / "node_modules"
    has_deps = node_modules.exists()

    if not npm_available:
        return False

    if not has_deps:
        _print_cli_card(
            "Elephant Agent dashboard",
            "Dashboard frontend dependencies are not installed.",
            sections=(
                CliCardSection("Next step", (
                    "Install dependencies first:",
                    "  cd apps/dashboard && npm install",
                    "Then run this command again.",
                )),
            ),
        )
        return False

    _print_cli_card(
        "Elephant Agent dashboard",
        "Building dashboard frontend…",
        sections=(),
    )
    result = subprocess.run(
        ["npm", "--prefix", str(DASHBOARD_APP_DIR), "run", "build"],
        cwd=REPO_ROOT,
        text=True,
    )
    if result.returncode != 0:
        _print_cli_card(
            "Elephant Agent dashboard",
            "Frontend build failed.",
            sections=(CliCardSection("Detail", ("Check the build output above for errors.",)),),
        )
        return False

    return DASHBOARD_DIST_INDEX.is_file()


def _run_dashboard(
    plan: DashboardLaunchPlan,
    *,
    open_browser: bool,
    skip_build: bool = False,
    rebuild: bool = False,
) -> int:
    # ── Ensure the frontend is built ──
    if not _ensure_frontend_dist(skip_build=skip_build, rebuild=rebuild):
        if not DASHBOARD_DIST_INDEX.is_file():
            _print_cli_card(
                "Elephant Agent dashboard",
                "Dashboard frontend assets are not available.",
                sections=(
                    CliCardSection(
                        "Next step",
                        (
                            "Build the dashboard frontend:",
                            "  cd apps/dashboard && npm install && npm run build",
                            "Then start (or restart) the daemon:",
                            "  elephant daemon start",
                        ),
                    ),
                ),
            )
            return 1
    # ── Daemon is required: dashboard is served by the daemon ──
    daemon_dashboard_url = _try_daemon_dashboard_url(plan)
    if daemon_dashboard_url is not None:
        _print_cli_card(
            "Elephant Agent dashboard",
            "Daemon is running — opening the built-in dashboard.",
            sections=(CliCardSection("Endpoints", (f"dashboard_url · {daemon_dashboard_url}",)),),
        )
        if open_browser:
            opened = webbrowser.open(daemon_dashboard_url)
            if not opened:
                print(f"Elephant Agent dashboard URL: {daemon_dashboard_url}")
        else:
            print(f"Elephant Agent dashboard URL: {daemon_dashboard_url}")
        return 0

    # Daemon is not running — guide the user to start it.
    _print_cli_card(
        "Elephant Agent dashboard",
        "The dashboard is served by the Elephant daemon.",
        sections=(
            CliCardSection(
                "Status",
                ("daemon · not running", "frontend · built ✓"),
            ),
            CliCardSection(
                "Next step",
                (
                    "Start the daemon:",
                    "  elephant daemon start",
                ),
            ),
            CliCardSection(
                "Rebuild frontend",
                (
                    "If you changed the frontend code:",
                    "  elephant dashboard --rebuild",
                ),
            ),
        ),
    )
    return 1


def build_typer_app(
    *,
    default_state_dir: Path | None = None,
) -> typer.Typer:
    app = typer.Typer(
        name="elephant dashboard",
        help="Open the operator dashboard (requires a running daemon).",
        no_args_is_help=False,
        rich_markup_mode="rich",
        add_completion=False,
    )

    @app.callback(invoke_without_command=True)
    def main_callback(
        state_dir: Path = typer.Option(default_state_dir, "--state-dir", hidden=True),
        open_browser: bool = typer.Option(True, "--open/--no-open", help="Open the dashboard URL in the default browser."),
        skip_build: bool = typer.Option(False, "--skip-build", help="Skip the frontend build check."),
        rebuild: bool = typer.Option(False, "--rebuild", help="Force rebuild the frontend assets."),
    ) -> None:
        plan = DashboardLaunchPlan(state_dir=state_dir)
        raise typer.Exit(_run_dashboard(plan, open_browser=bool(open_browser), skip_build=bool(skip_build), rebuild=bool(rebuild)))

    return app


def command_main(
    argv: list[str] | None = None,
    *,
    default_state_dir: Path | None = None,
) -> int:
    return run_typer_app(
        build_typer_app(default_state_dir=default_state_dir),
        argv,
        prog_name="elephant dashboard",
    )


__all__ = ["command_main", "build_typer_app"]
