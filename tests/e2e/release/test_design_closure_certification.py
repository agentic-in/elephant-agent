from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "design-closure-certification.yml"
MAKEFILE_PATH = ROOT / "Makefile"
MACOS_APP_MODEL_PATH = ROOT / "apps" / "macos" / "Sources" / "AppModel.swift"
MACOS_VIEWS_PATH = ROOT / "apps" / "macos" / "Sources" / "Views.swift"
MACOS_SPEECH_INPUT_PATH = ROOT / "apps" / "macos" / "Sources" / "SpeechInputController.swift"
WORKFLOW_BASE_URL_PLACEHOLDER = "REPLACE_BEFORE_RUN"
CANONICAL_DESIGN_DOCS = (
    ROOT / "docs" / "system-design" / "README.md",
    ROOT / "docs" / "system-design" / "system-layer-model.md",
    ROOT / "docs" / "agent" / "plans" / "README.md",
    ROOT / "docs" / "agent" / "task-cards" / "README.md",
)
DELETED_HISTORICAL_DOCS = (
    ROOT / "docs" / "system-design" / "target-architecture.md",
    ROOT / "docs" / "system-design" / "state-graph-and-continuity-explainer.md",
    ROOT / "docs" / "system-design" / "continuity-product-model.md",
    ROOT / "docs" / "system-design" / "scope-aware-memory-recovery.md",
    ROOT / "docs" / "system-design" / "experience-system.md",
    ROOT / "docs" / "system-design" / "technical-stack-and-modules.md",
    ROOT / "docs" / "agent" / "plans" / "initial-design-closure-audit.md",
    ROOT / "docs" / "agent" / "plans" / "wave-status.md",
    ROOT / "docs" / "agent" / "plans" / "personal-ai-experience-alignment.md",
    ROOT / "docs" / "agent" / "plans" / "system-layer-design-closure-certification.md",
    ROOT / "docs" / "agent" / "plans" / "system-layer-design-closure-certification-checklist.md",
    ROOT / "docs" / "agent" / "plans" / "system-layer-release-certification.md",
    ROOT / "docs" / "agent" / "plans" / "system-layer-release-certification-checklist.md",
    ROOT / "docs" / "agent" / "plans" / "system-layer-reset-gap.md",
)

CONTRACT_MODULES = (
    "tests.e2e.release.test_release_certification.ReleaseCertificationContractsTest",
    "tests.e2e.release.test_design_closure_certification.DesignClosureContractsTest",
)

RESET_API_E2E_TARGETS = (
    "tests.e2e.api.test_api_surface.APISurfaceE2ETest.test_operator_namespace_no_longer_exposes_public_dashboard_reads",
    "tests.e2e.api.test_api_surface.APISurfaceE2ETest.test_operator_dashboard_projection_is_empty_without_runtime_state",
    "tests.e2e.api.test_api_surface.APISurfaceE2ETest.test_internal_dashboard_projection_surfaces_canonical_runtime_and_evidence",
    "tests.e2e.api.test_api_surface.APISurfaceE2ETest.test_default_provider_bad_request_hides_legacy_profile_field_names",
)

DESIGN_CLOSURE_MATRIX_TARGETS = ("tests.agent.test_system_layer_reset_matrix",)

LIVE_PROVIDER_SMOKE_TARGETS = (
    "tests.e2e.release.test_release_certification.LiveProviderCertificationSmokeTest",
    "tests.e2e.deploy.test_installed_command_smoke.InstalledCommandLiveSmokeTest",
)

INSTALLED_USER_JOURNEY_TARGETS = (
    "tests.e2e.deploy.test_installed_user_journey",
)


class DesignClosureContractsTest(unittest.TestCase):
    def test_design_closure_matrix_no_longer_tracks_deleted_voice_or_planning_modules(self) -> None:
        makefile_text = MAKEFILE_PATH.read_text(encoding="utf-8")

        self.assertNotIn("tests.e2e.voice.test_voice_preview", makefile_text)
        self.assertNotIn("tests.scenarios.planning.test_planning_scenarios", makefile_text)

    def test_design_closure_contract_lives_in_makefile_and_workflow(self) -> None:
        makefile_text = MAKEFILE_PATH.read_text(encoding="utf-8")
        workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn("design-closure:", makefile_text)
        self.assertIn("test-release-contracts", makefile_text)
        self.assertIn("test-release-e2e", makefile_text)
        self.assertIn("test-design-closure-reset-matrix", makefile_text)
        self.assertIn("web-build", makefile_text)
        self.assertIn("agent-pr-gate", makefile_text)
        self.assertIn("Run canonical system-layer reset design-closure contract", workflow_text)
        self.assertIn("Operator-managed OpenAI-compatible base URL", workflow_text)
        self.assertIn("tke/", workflow_text)

    def test_makefile_pins_design_closure_matrix(self) -> None:
        text = MAKEFILE_PATH.read_text(encoding="utf-8")

        self.assertIn("test-release-e2e", text)
        self.assertIn("test-installed-user-journey", text)
        self.assertIn("test-design-closure-reset-matrix", text)

        for target in (
            *CONTRACT_MODULES,
            *RESET_API_E2E_TARGETS,
            *INSTALLED_USER_JOURNEY_TARGETS,
            *DESIGN_CLOSURE_MATRIX_TARGETS,
        ):
            with self.subTest(target=target):
                self.assertIn(target, text)

    def test_design_closure_uses_canonical_docs_and_historical_inputs_stay_deleted(self) -> None:
        for path in CANONICAL_DESIGN_DOCS:
            with self.subTest(path=path):
                self.assertTrue(path.exists(), path)

        for path in DELETED_HISTORICAL_DOCS:
            with self.subTest(path=path):
                self.assertFalse(path.exists(), path)

    def test_design_closure_rejects_session_era_goal_or_procedure_routes(self) -> None:
        for path in (ROOT / "apps" / "api").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path):
                self.assertNotIn("/goals", text)
                self.assertNotIn("/procedure", text)

    def test_macos_primary_sidebar_keeps_runtime_internals_in_settings(self) -> None:
        app_model = MACOS_APP_MODEL_PATH.read_text(encoding="utf-8")
        views = MACOS_VIEWS_PATH.read_text(encoding="utf-8")
        primary_section = app_model.split("static let primary: [AppSection] = [", 1)[1].split("]", 1)[0]
        sidebar = views.split("struct SidebarView: View", 1)[1].split("struct SidebarCollapseButton", 1)[0]
        sidebar_footer = sidebar.split("VStack(spacing: 10) {", 1)[1].split(".padding(.bottom, 16)", 1)[0]

        self.assertNotIn(".tools", primary_section)
        self.assertNotIn("section: .provider", sidebar_footer)
        self.assertIn("case provider", views)
        self.assertIn("case tools", views)
        self.assertIn("ProviderSettingsContent()", views)
        self.assertIn("ToolsSettingsContent()", views)

    def test_macos_voice_capture_ignores_stale_permission_callbacks(self) -> None:
        speech_input = MACOS_SPEECH_INPUT_PATH.read_text(encoding="utf-8")
        views = MACOS_VIEWS_PATH.read_text(encoding="utf-8")

        self.assertIn("captureGeneration", speech_input)
        self.assertIn("permissionTimeoutTask", speech_input)
        self.assertIn("schedulePermissionTimeout(generation:", speech_input)
        self.assertIn("isActiveCapture(_ generation: Int)", speech_input)
        self.assertGreaterEqual(speech_input.count("isActiveCapture(generation) else { return }"), 3)
        self.assertIn("Microphone permission did not finish", speech_input)
        self.assertIn("lowerStatus.contains(\"permission\")", views)

    def test_workflow_keeps_live_provider_manual_and_secret_backed(self) -> None:
        text = WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn("name: Design Closure Certification", text)
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("run_live_provider", text)
        self.assertIn(WORKFLOW_BASE_URL_PLACEHOLDER, text)
        self.assertIn("ELEPHANT_LIVE_PROVIDER_BASE_URL", text)
        self.assertIn("ELEPHANT_LIVE_PROVIDER_MODEL", text)
        self.assertIn("ELEPHANT_LIVE_PROVIDER_API_KEY", text)
        self.assertIn("Build dashboard assets for installed smoke", text)
        self.assertIn("make test-live-provider-smoke", text)
        self.assertIn("make design-closure AGENT_BASE_REF=origin/main", text)
        self.assertIn("Run canonical system-layer reset design-closure contract", text)

        makefile_text = MAKEFILE_PATH.read_text(encoding="utf-8")
        self.assertIn("test-live-provider-smoke", makefile_text)
        self.assertIn("test-live-installed-smoke", makefile_text)
        self.assertIn("test-installed-user-journey", makefile_text)
        self.assertIn("test-release-e2e", makefile_text)
        self.assertIn("test-design-closure-reset-matrix", makefile_text)
        for target in (
            *CONTRACT_MODULES,
            *RESET_API_E2E_TARGETS,
            *INSTALLED_USER_JOURNEY_TARGETS,
            *DESIGN_CLOSURE_MATRIX_TARGETS,
            *LIVE_PROVIDER_SMOKE_TARGETS,
        ):
            with self.subTest(target=target):
                self.assertIn(target, makefile_text)

if __name__ == "__main__":
    unittest.main()
