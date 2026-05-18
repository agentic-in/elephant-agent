from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
DELETED_RELEASE_RUNBOOK_PATHS = (
    ROOT / "docs" / "agent" / "plans" / "system-layer-release-certification.md",
    ROOT / "docs" / "agent" / "plans" / "system-layer-release-certification-checklist.md",
)
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "release-certification.yml"
MAKEFILE_PATH = ROOT / "Makefile"
WORKFLOW_BASE_URL_PLACEHOLDER = "REPLACE_BEFORE_RUN"
DASHBOARD_PACKAGE_PATH = ROOT / "apps" / "dashboard" / "package.json"

RESET_API_E2E_TARGETS = (
    "tests.e2e.api.test_api_surface.APISurfaceE2ETest.test_operator_namespace_no_longer_exposes_public_dashboard_reads",
    "tests.e2e.api.test_api_surface.APISurfaceE2ETest.test_operator_dashboard_projection_is_empty_without_runtime_state",
    "tests.e2e.api.test_api_surface.APISurfaceE2ETest.test_internal_dashboard_projection_surfaces_canonical_runtime_and_evidence",
    "tests.e2e.api.test_api_surface.APISurfaceE2ETest.test_default_provider_bad_request_hides_legacy_profile_field_names",
)

DETERMINISTIC_SCENARIO_MODULES = (
    "tests.scenarios.context.test_context_scenarios",
    "tests.unit.recall.test_recall_scenarios",
    "tests.scenarios.continuity.test_continuity_scenarios",
)

INSTALL_SURFACE_MODULES = (
    "tests.e2e.deploy.test_public_install_script",
    "tests.e2e.deploy.test_install_distribution",
    "tests.e2e.deploy.test_installed_user_journey",
)

LIVE_PROVIDER_SMOKE_TARGETS = (
    "tests.e2e.release.test_release_certification.LiveProviderCertificationSmokeTest",
    "tests.e2e.deploy.test_installed_command_smoke.InstalledCommandLiveSmokeTest",
)

DASHBOARD_UI_PROOF_PATHS = (
    "apps/api/api_runtime_console.py",
    "apps/api/api_runtime_http_methods.py",
    "apps/api/api_runtime_impl.py",
    "apps/api/__main__.py",
    "apps/dashboard/scripts/serve-with-api.mjs",
    "apps/dashboard/src/app/router.tsx",
    "apps/dashboard/src/lib/dashboardApi.ts",
    "apps/dashboard/src/hooks/useOperatorConsole.ts",
    "apps/dashboard/src/shell/DashboardShell.tsx",
    "apps/dashboard/src/lib/dashboardNavigation.ts",
    "apps/dashboard/src/routes/shared/RoutePageHeader.tsx",
    "apps/dashboard/src/routes/console/ConsolePages.tsx",
    "apps/dashboard/src/components/primitives/Primitives.module.css",
)

DASHBOARD_BRAND_ASSET_PATHS = (
    "apps/dashboard/src/assets/brand/elephant-logo.png",
)

PUBLIC_SURFACE_PROOF_PATHS = (
    "apps/site/docs/reference/cli.md",
    "apps/dashboard/src/lib/dashboardNavigation.ts",
    "apps/dashboard/src/routes/console/ConsolePages.tsx",
    "apps/api/api_runtime_internal_methods.py",
    "apps/api/api_runtime_http_methods.py",
)

PUBLIC_SURFACE_REJECTED_MARKERS = (
    "/v1/operator/console",
    "operator console",
    "session, goal, or activity" + " graphs",
    "elephant-owned memory surfaces",
    "strong/weak routing",
    "Intent mode",
    "state_focus_mode",
)


def _target_path(target: str) -> Path:
    parts = target.split(".")
    for index in range(len(parts), 0, -1):
        candidate = ROOT / ("/".join(parts[:index]) + ".py")
        if candidate.exists():
            return candidate
    return ROOT / (target.replace(".", "/") + ".py")


class ReleaseCertificationContractsTest(unittest.TestCase):
    def test_release_modules_exist(self) -> None:
        for target in (
            *RESET_API_E2E_TARGETS,
            *DETERMINISTIC_SCENARIO_MODULES,
            *INSTALL_SURFACE_MODULES,
            *LIVE_PROVIDER_SMOKE_TARGETS,
        ):
            with self.subTest(target=target):
                self.assertTrue(_target_path(target).exists(), target)

    def test_release_matrix_no_longer_tracks_deleted_voice_or_planning_modules(self) -> None:
        makefile_text = MAKEFILE_PATH.read_text(encoding="utf-8")

        self.assertNotIn("tests.e2e.voice.test_voice_preview", makefile_text)
        self.assertNotIn("tests.scenarios.planning.test_planning_scenarios", makefile_text)
        self.assertFalse(_target_path("tests.e2e.voice.test_voice_preview").exists())
        self.assertFalse(_target_path("tests.scenarios.planning.test_planning_scenarios").exists())

    def test_standalone_release_runbooks_stay_deleted(self) -> None:
        for path in DELETED_RELEASE_RUNBOOK_PATHS:
            with self.subTest(path=path):
                self.assertFalse(path.exists(), path)

    def test_release_contract_rejects_session_era_goal_or_procedure_routes(self) -> None:
        for path in (ROOT / "apps" / "api").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path):
                self.assertNotIn("/goals", text)
                self.assertNotIn("/procedure", text)

    def test_makefile_pins_release_matrix_and_install_contract(self) -> None:
        text = MAKEFILE_PATH.read_text(encoding="utf-8")

        self.assertIn("release:", text)
        self.assertIn("test-release-contracts", text)
        self.assertIn("test-release-e2e", text)
        self.assertIn("test-release-scenarios", text)
        self.assertIn("web-build", text)
        self.assertIn("package-build", text)
        self.assertIn("package-verify", text)
        self.assertIn("agent-pr-gate", text)
        self.assertIn("test-live-provider-smoke", text)
        self.assertIn("test-live-installed-smoke", text)
        self.assertIn("test-installed-user-journey", text)

        for target in RESET_API_E2E_TARGETS:
            with self.subTest(target=target):
                self.assertIn(target, text)
        for target in DETERMINISTIC_SCENARIO_MODULES:
            with self.subTest(target=target):
                self.assertIn(target, text)
        for target in INSTALL_SURFACE_MODULES:
            with self.subTest(target=target):
                self.assertIn(target, text)

    def test_workflow_keeps_live_provider_manual_and_secret_backed(self) -> None:
        text = WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn("name: Release Certification", text)
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("run_live_provider", text)
        self.assertIn(WORKFLOW_BASE_URL_PLACEHOLDER, text)
        self.assertIn("ELEPHANT_LIVE_PROVIDER_BASE_URL", text)
        self.assertIn("ELEPHANT_LIVE_PROVIDER_MODEL", text)
        self.assertIn("ELEPHANT_LIVE_PROVIDER_API_KEY", text)
        self.assertIn("Build dashboard assets for installed smoke", text)
        self.assertIn("make test-live-provider-smoke", text)
        self.assertIn("make release AGENT_BASE_REF=\"$BASE_REF\"", text)
        self.assertIn("Run canonical system-layer reset release contract", text)

        makefile_text = MAKEFILE_PATH.read_text(encoding="utf-8")
        self.assertIn("test-live-provider-smoke", makefile_text)
        self.assertIn("test-live-installed-smoke", makefile_text)
        self.assertIn("test-release-e2e", makefile_text)
        self.assertIn("test-release-scenarios", makefile_text)
        self.assertIn("package-build", makefile_text)
        self.assertIn("package-verify", makefile_text)
        self.assertIn("test-install-surfaces", makefile_text)
        self.assertIn("packages/storage/schema.sql", makefile_text)
        self.assertIn("legacy storage migrations leaked into the wheel", makefile_text)
        self.assertIn("apps/dashboard/dist/index.html", makefile_text)

        for target in RESET_API_E2E_TARGETS:
            with self.subTest(target=target):
                self.assertIn(target, makefile_text)
        for target in DETERMINISTIC_SCENARIO_MODULES:
            with self.subTest(target=target):
                self.assertIn(target, makefile_text)
        for target in LIVE_PROVIDER_SMOKE_TARGETS:
            with self.subTest(target=target):
                self.assertIn(target, makefile_text)


class DashboardRefactorCertificationContractsTest(unittest.TestCase):
    def test_dashboard_inspection_surface_stays_implemented(self) -> None:
        for path in DASHBOARD_UI_PROOF_PATHS:
            with self.subTest(path=path):
                self.assertTrue((ROOT / path).exists(), path)

        dashboard_api = (ROOT / "apps" / "dashboard" / "src" / "lib" / "dashboardApi.ts").read_text(
            encoding="utf-8"
        )
        cli_doc = (ROOT / "apps" / "site" / "docs" / "reference" / "cli.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("/v1/internal/dashboard", dashboard_api)
        self.assertIn("/v1/internal/dashboard", cli_doc)

        for path in DASHBOARD_BRAND_ASSET_PATHS:
            with self.subTest(path=path):
                self.assertTrue((ROOT / path).exists(), path)

    def test_dashboard_package_keeps_real_data_scripts_only(self) -> None:
        package = json.loads(DASHBOARD_PACKAGE_PATH.read_text(encoding="utf-8"))

        self.assertIn("dev", package["scripts"])
        self.assertIn("build", package["scripts"])
        self.assertNotIn("capture:refactor-screenshots", package["scripts"])
        self.assertNotIn("preview", package["scripts"])

    def test_release_plan_no_longer_depends_on_deleted_dashboard_design_doc(self) -> None:
        self.assertFalse((ROOT / "docs" / "system-design" / "operator-dashboard-surface.md").exists())

    def test_makefile_pins_reset_package_verification_contract(self) -> None:
        text = MAKEFILE_PATH.read_text(encoding="utf-8")

        self.assertIn("packages/storage/schema.sql", text)
        self.assertIn("packages/storage/migrations/", text)
        self.assertIn("apps/dashboard/dist/index.html", text)
        self.assertIn("apps/site/node_modules", text)
        self.assertIn("twine check dist/*", text)
        self.assertIn("test-install-surfaces", text)
        for module_name in INSTALL_SURFACE_MODULES:
            with self.subTest(module=module_name):
                self.assertIn(module_name, text)

    def test_public_proof_files_reject_deleted_surface_wording(self) -> None:
        cli_doc = (ROOT / "apps" / "site" / "docs" / "reference" / "cli.md").read_text(encoding="utf-8")
        self.assertIn("/v1/internal/dashboard", cli_doc)

        for path in PUBLIC_SURFACE_PROOF_PATHS:
            surface_text = (ROOT / path).read_text(encoding="utf-8")
            for marker in PUBLIC_SURFACE_REJECTED_MARKERS:
                with self.subTest(path=path, marker=marker):
                    self.assertNotIn(marker, surface_text)


class LiveProviderCertificationSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.base_url = os.environ.get("ELEPHANT_LIVE_PROVIDER_BASE_URL")
        self.model_id = os.environ.get("ELEPHANT_LIVE_PROVIDER_MODEL")
        self.api_key = os.environ.get("ELEPHANT_LIVE_PROVIDER_API_KEY")
        self.provider_id = os.environ.get(
            "ELEPHANT_LIVE_PROVIDER_PROVIDER_ID",
            "openai-compatible",
        )
        self.base_url = self.base_url.strip() if self.base_url is not None else None
        if not self.base_url or not self.model_id or not self.api_key:
            self.skipTest(
                "live provider smoke requires ELEPHANT_LIVE_PROVIDER_BASE_URL, "
                "ELEPHANT_LIVE_PROVIDER_MODEL, and ELEPHANT_LIVE_PROVIDER_API_KEY"
            )
        self.assertTrue(
            self.base_url.startswith(("http://", "https://")),
            "live certification requires an operator-managed OpenAI-compatible base URL",
        )
        self.assertNotEqual(
            self.base_url,
            WORKFLOW_BASE_URL_PLACEHOLDER,
            "live certification requires replacing the workflow base URL placeholder",
        )
        self.assertTrue(
            self.model_id.startswith("tke/"),
            "live certification only permits model ids prefixed with 'tke/'",
        )
        self.tempdir = tempfile.TemporaryDirectory()
        self.home = Path(self.tempdir.name) / "elephant-home"
        self.profile_manifest = self.home / "profile" / "profile.json"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["ELEPHANT_HOME"] = str(self.home)
        return env

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "apps.launcher", *args],
            cwd=ROOT,
            env=self._env(),
            text=True,
            capture_output=True,
            check=True,
        )

    def test_live_provider_flow_uses_env_backed_secret_reference(self) -> None:
        born = self._run(
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
            "Release Captain",
        )
        self.assertIn("Birth complete", born.stdout)
        self.assertIn("active_provider_id: openai-compatible", born.stdout)
        self.assertIn("provider_status: ready", born.stdout)
        self.assertNotIn(self.api_key, born.stdout)
        self.assertNotIn(self.api_key, born.stderr)

        manifest = json.loads(self.profile_manifest.read_text(encoding="utf-8"))
        provider_profile = manifest["provider_profile"]
        self.assertEqual(provider_profile["provider_id"], "openai-compatible")
        self.assertEqual(provider_profile["base_url"], self.base_url)
        self.assertEqual(provider_profile["default_model"], self.model_id)
        metadata = provider_profile["secret_references"][0]["metadata"]
        self.assertEqual(metadata["env_var"], "ELEPHANT_LIVE_PROVIDER_API_KEY")
        self.assertNotIn(self.api_key, self.profile_manifest.read_text(encoding="utf-8"))

        health = self._run("status")
        self.assertIn("Elephant Agent status", health.stdout)
        self.assertIn("provider_status: ready", health.stdout)
        self.assertIn("active_provider_id: openai-compatible", health.stdout)
        self.assertNotIn(self.api_key, health.stdout)
        self.assertNotIn(self.api_key, health.stderr)

        elephant = self._run(
            "elephant",
            "release-certification",
        )
        self.assertIn("Elephant Agent elephant", elephant.stdout)
        self.assertIn("elephant_id: release-certification", elephant.stdout)

        first_grow = self._run(
            "wake",
            "--elephant-id",
            "release-certification",
            "--message",
            "Reply exactly: provider-ready",
        )
        self.assertIn("Elephant Agent turn", first_grow.stdout)
        self.assertIn("provider_id: openai-compatible", first_grow.stdout)
        self.assertIn(f"provider_model_id: {self.model_id}", first_grow.stdout)
        self.assertNotIn(self.api_key, first_grow.stdout)
        self.assertNotIn(self.api_key, first_grow.stderr)

        second_grow = self._run(
            "wake",
            "--elephant-id",
            "release-certification",
            "--message",
            "Reply exactly: release-ready",
        )
        self.assertIn("Elephant Agent turn", second_grow.stdout)
        self.assertIn("execution:", second_grow.stdout)
        self.assertNotIn(self.api_key, second_grow.stdout)
        self.assertNotIn(self.api_key, second_grow.stderr)

        state_path = self.home / "state" / "elephant.sqlite3"
        if state_path.exists():
            self.assertNotIn(self.api_key, state_path.read_text(encoding="utf-8", errors="ignore"))


if __name__ == "__main__":
    unittest.main()
