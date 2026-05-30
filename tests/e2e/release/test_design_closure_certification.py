from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "design-closure-certification.yml"
MAKEFILE_PATH = ROOT / "Makefile"
MACOS_APP_MODEL_PATH = ROOT / "apps" / "macos" / "Sources" / "AppModel.swift"
MACOS_API_CLIENT_PATH = ROOT / "apps" / "macos" / "Sources" / "APIClient.swift"
MACOS_DESIGN_SYSTEM_PATH = ROOT / "apps" / "macos" / "Sources" / "DesignSystem.swift"
MACOS_VIEWS_PATH = ROOT / "apps" / "macos" / "Sources" / "Views.swift"
MACOS_SLEEP_DISPLAY_PATH = ROOT / "apps" / "macos" / "Sources" / "SleepDisplayView.swift"
MACOS_SPEECH_INPUT_PATH = ROOT / "apps" / "macos" / "Sources" / "SpeechInputController.swift"
MACOS_SPEECH_OUTPUT_PATH = ROOT / "apps" / "macos" / "Sources" / "LocalSpeechOutputController.swift"
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
    "tests.e2e.api.test_api_surface_dashboard.APISurfaceDashboardE2ETest.test_operator_namespace_no_longer_exposes_public_dashboard_reads",
    "tests.e2e.api.test_api_surface_dashboard.APISurfaceDashboardE2ETest.test_operator_dashboard_projection_is_empty_without_runtime_state",
    "tests.e2e.api.test_api_surface_dashboard.APISurfaceDashboardE2ETest.test_internal_dashboard_projection_surfaces_canonical_runtime_and_evidence",
    "tests.e2e.api.test_api_surface_providers.APISurfaceProviderE2ETest.test_default_provider_bad_request_hides_legacy_profile_field_names",
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

    def test_macos_sidebar_menu_command_controls_custom_sidebar(self) -> None:
        app = (ROOT / "apps" / "macos" / "Sources" / "ElephantAgentMacApp.swift").read_text(encoding="utf-8")

        self.assertNotIn("SidebarCommands()", app)
        self.assertIn("CommandGroup(replacing: .sidebar)", app)
        self.assertIn("model.text(.toggleSidebar)", app)
        self.assertIn("NotificationCenter.default.post(name: .elephantToggleSidebar", app)
        self.assertIn('.keyboardShortcut("s", modifiers: [.command, .option])', app)

    def test_macos_home_readiness_cards_are_responsive_navigation_controls(self) -> None:
        views = MACOS_VIEWS_PATH.read_text(encoding="utf-8")
        strip = views.split("struct HomeReadinessStrip: View", 1)[1].split("struct HomeContinuityPanel", 1)[0]
        button = views.split("private struct HomeReadinessButton: View", 1)[1].split("struct HomeContinuityPanel", 1)[0]

        self.assertIn("GridItem(.adaptive(minimum: 238), spacing: 10)", strip)
        self.assertIn("HomeReadinessButton(item: providerItem)", strip)
        self.assertIn("target: .settings", strip)
        self.assertIn("target: .you", strip)
        self.assertIn("target: .messaging", strip)
        self.assertIn("target: .learn", strip)
        self.assertIn("model.selectedSection = item.target", button)
        self.assertIn("Text(item.status)", button)
        self.assertIn(".lineLimit(2)", button)
        self.assertIn(".frame(maxWidth: .infinity, minHeight: 74", button)
        self.assertIn(".help(\"\\(item.title): \\(item.status). \\(item.detail). \\(navigationHint)\")", button)
        self.assertIn(".accessibilityLabel(\"\\(item.title), \\(item.status). \\(item.detail)\")", button)
        self.assertIn(".accessibilityHint(navigationHint)", button)
        self.assertIn("item.target.title(language: model.appLanguage)", button)

    def test_macos_sleep_display_hides_app_content_and_avoids_orb_decoration(self) -> None:
        views = MACOS_VIEWS_PATH.read_text(encoding="utf-8")
        sleep_display = MACOS_SLEEP_DISPLAY_PATH.read_text(encoding="utf-8")
        root_view = views.split("struct RootView: View", 1)[1].split("struct OnboardingLetterToast", 1)[0]

        self.assertIn(".allowsHitTesting(!model.isSleepDisplayPresented && !model.showingOnboarding)", root_view)
        self.assertIn(".accessibilityHidden(model.isSleepDisplayPresented || model.showingOnboarding)", root_view)
        self.assertIn("if model.isSleepDisplayPresented && !model.showingOnboarding", root_view)
        self.assertIn("SleepDisplayView()", root_view)

        self.assertIn("SleepVideoBackdrop(paused: reduceMotion)", sleep_display)
        self.assertIn('Bundle.main.url(forResource: "baby-el", withExtension: "mp4")', sleep_display)
        self.assertIn("SecureField(model.text(.sleepPasswordPlaceholder)", sleep_display)
        self.assertIn("model.verifySleepUnlock()", sleep_display)
        self.assertIn(".accessibilityLabel(model.text(.sleepPasswordPlaceholder))", sleep_display)
        self.assertIn(".accessibilityHint(model.text(.sleepLockSubtitle))", sleep_display)
        self.assertIn(".accessibilityElement(children: .contain)", sleep_display)
        self.assertIn("SleepAmbientCanvas", sleep_display)
        self.assertIn("drawWaveLines", sleep_display)
        self.assertNotIn("drawOrbs", sleep_display)
        self.assertNotIn("Path(ellipseIn:", sleep_display)

    def test_macos_runtime_config_save_resets_clean_draft_state(self) -> None:
        views = MACOS_VIEWS_PATH.read_text(encoding="utf-8")
        app_model = MACOS_APP_MODEL_PATH.read_text(encoding="utf-8")
        runtime_config = views.split("struct RuntimeConfigSettingsContent: View", 1)[1].split("struct OperatorItemGroup", 1)[0]
        save_global_config = app_model.split("func saveGlobalConfig(yamlText: String) async", 1)[1].split("func surfaceQuestionSooner", 1)[0]

        self.assertIn("@State private var loadedYaml", runtime_config)
        self.assertIn("syncDraftFromSnapshot()", runtime_config)
        self.assertIn(".onChange(of: model.configActionResult)", runtime_config)
        self.assertIn("if !result.isEmpty", runtime_config)
        self.assertIn("loadedYaml = model.snapshot.settingsYaml", runtime_config)
        self.assertIn("draft != loadedYaml", runtime_config)
        self.assertIn('configActionResult = ""', save_global_config)
        self.assertIn('configActionResult = "Config saved."', save_global_config)

    def test_macos_skills_surface_owns_drafts_and_settings_stays_deduplicated(self) -> None:
        app_model = MACOS_APP_MODEL_PATH.read_text(encoding="utf-8")
        api_client = MACOS_API_CLIENT_PATH.read_text(encoding="utf-8")
        views = MACOS_VIEWS_PATH.read_text(encoding="utf-8")
        skills_view = views.split("struct SkillsView: View", 1)[1].split("struct ToolsView: View", 1)[0]
        settings_view = views.split("struct SettingsView: View", 1)[1].split("private struct SettingsLockedView", 1)[0]
        catalog = views.split("private struct OperatorCatalogContent: View", 1)[1].split("private struct OperatorCatalogLogo", 1)[0]
        row = views.split("private struct OperatorCatalogRow: View", 1)[1].split("private struct OperatorItemDetailSheet", 1)[0]
        detail = views.split("private struct OperatorItemDetailSheet: View", 1)[1].split("private struct OperatorDetailBlock", 1)[0]

        self.assertIn("var sourceKind: String", app_model)
        self.assertIn("var reviewStatus: String", app_model)
        self.assertIn("var promptIndexVisible: Bool", app_model)
        self.assertIn('sourceKind: string(row["sourceKind"] ?? row["source_kind"] ?? metadata["source_kind"])', api_client)
        self.assertIn('reviewStatus: string(row["reviewStatus"] ?? row["review_status"] ?? metadata["review_status"])', api_client)
        self.assertIn('promptIndexVisible: bool(row["promptIndexVisible"] ?? row["prompt_index_visible"], fallback: false)', api_client)

        self.assertIn('en: "Drafts"', skills_view)
        self.assertIn("private var pendingDrafts", skills_view)
        self.assertIn("SkillAffinityPanel()", skills_view)
        self.assertIn("SkillLibraryPanel()", skills_view)

        self.assertIn('if kind == "skills", pendingDraftCount > 0', catalog)
        self.assertIn("items.filter(isPendingDraft).count", catalog)
        self.assertIn("return leftPending && !rightPending", catalog)
        self.assertIn("private func isPendingDraft", catalog)
        self.assertIn('item.reviewStatus.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == "pending"', catalog)

        self.assertIn("private var isEvolutionDraft", row)
        self.assertIn('normalizedReviewStatus == "pending"', row)
        self.assertIn('en: "pending"', row)
        self.assertIn('en: "Approve"', row)
        self.assertIn('return "sparkles"', row)

        self.assertIn('en: "Skill Evolution"', detail)
        self.assertIn('en: "Prompt visible"', detail)
        self.assertIn('en: "Review"', detail)
        self.assertIn("Approve this skill to make it available for future prompts.", detail)
        self.assertIn('en: "pending review"', detail)

        self.assertNotIn("SkillsSettingsContent()", settings_view)
        self.assertNotIn("paneBinding(.skills)", settings_view)
        self.assertIn("ToolsSettingsContent()", settings_view)
        self.assertIn("RuntimeConfigSettingsContent()", settings_view)

    def test_macos_voice_capture_ignores_stale_permission_callbacks(self) -> None:
        speech_input = MACOS_SPEECH_INPUT_PATH.read_text(encoding="utf-8")
        speech_output = MACOS_SPEECH_OUTPUT_PATH.read_text(encoding="utf-8")
        views = MACOS_VIEWS_PATH.read_text(encoding="utf-8")

        self.assertIn("captureGeneration", speech_input)
        self.assertIn("permissionTimeoutTask", speech_input)
        self.assertIn("schedulePermissionTimeout(generation:", speech_input)
        self.assertIn("isActiveCapture(_ generation: Int)", speech_input)
        self.assertIn("startAppleRecording(locale: locale, statusNotice: statusNotice, generation: generation)", speech_input)
        self.assertIn("startLocalRecording(previewLocale: locale, generation: generation)", speech_input)
        self.assertIn("startApplePreviewRecognition(locale: $0, generation: generation)", speech_input)
        self.assertIn("startFunASRTranscription(generation: generation)", speech_input)
        self.assertIn("finishAppleRecognition(generation: generation)", speech_input)
        self.assertGreaterEqual(speech_input.count("isActiveCapture(generation) else { return }"), 8)
        self.assertIn("Microphone permission did not finish", speech_input)
        self.assertIn("lowerStatus.contains(\"permission\")", views)
        self.assertIn("MacPrivacySettings.openVoiceRecognition(statusText: statusText)", views)
        self.assertIn("MacPrivacySettings.openMicrophone()", views)
        self.assertIn("MacPrivacySettings.openSpeechRecognition()", views)
        self.assertIn("x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone", views)
        self.assertIn("x-apple.systempreferences:com.apple.preference.security?Privacy_SpeechRecognition", views)
        self.assertIn("permissionRecoveryAction", views)
        self.assertIn("showsPermissionRecoveryAction", views)
        self.assertIn('en: "Open Privacy Settings"', views)
        self.assertIn('en: "Microphone Settings"', views)
        self.assertIn('en: "Speech Settings"', views)
        self.assertIn("activeSystemUtterance", speech_output)
        self.assertIn("guard self?.activeSystemUtterance === utterance else { return }", speech_output)
        self.assertIn("guard self?.audioPlayer === player else { return }", speech_output)

    def test_macos_diary_entries_surface_source_provenance(self) -> None:
        app_model = MACOS_APP_MODEL_PATH.read_text(encoding="utf-8")
        api_client = MACOS_API_CLIENT_PATH.read_text(encoding="utf-8")
        views = MACOS_VIEWS_PATH.read_text(encoding="utf-8")
        diary_entry = app_model.split("struct DiaryEntry: Identifiable, Equatable", 1)[1].split("struct ProviderOption", 1)[0]
        diary_parser = api_client.split("snapshot.diaryEntries = entries.prefix", 1)[1].split("return snapshot", 1)[0]
        diary_panel = views.split("struct DiaryPanel: View", 1)[1].split("struct DiaryView: View", 1)[0]

        self.assertIn("sourceEpisodeIDs: [String]", diary_entry)
        self.assertIn("var sourceCount: Int", diary_entry)
        self.assertIn('row["source_episode_ids"]', diary_parser)
        self.assertIn('row["sourceEpisodeIds"]', diary_parser)
        self.assertIn('row["sourceEpisodeIDs"]', diary_parser)
        self.assertIn("entry.sourceCount > 0", diary_panel)
        self.assertIn('systemImage: "link"', diary_panel)
        self.assertIn("Source Episodes", diary_panel)

    def test_macos_learning_launchers_follow_active_job_state(self) -> None:
        app_model = MACOS_APP_MODEL_PATH.read_text(encoding="utf-8")
        design_system = MACOS_DESIGN_SYSTEM_PATH.read_text(encoding="utf-8")
        views = MACOS_VIEWS_PATH.read_text(encoding="utf-8")
        learn_view = views.split("struct LearnView: View", 1)[1].split("struct LearningJobSection", 1)[0]
        diary_view = views.split("struct DiaryView: View", 1)[1].split("struct DiaryStepButton", 1)[0]
        reflect_settings = views.split("struct ReflectSettingsContent: View", 1)[1].split("struct RuntimeSettingsContent", 1)[0]

        self.assertIn("var isActive: Bool", app_model)
        self.assertIn("var activeLearningJobCount: Int", app_model)
        self.assertIn("var hasActiveLearningJobs: Bool", app_model)
        self.assertIn("var learningLaunchDisabled: Bool", app_model)
        self.assertGreaterEqual(app_model.count("guard !learningLaunchDisabled else { return }"), 4)
        self.assertIn("var actionDisabled = false", design_system)
        self.assertGreaterEqual(design_system.count(".disabled(actionDisabled)"), 2)
        self.assertIn("let launchDisabled = model.learningLaunchDisabled", learn_view)
        self.assertIn("actionDisabled: launchDisabled", learn_view)
        self.assertIn("LearnActionButton(action: action, disabled: launchDisabled)", learn_view)
        self.assertIn("if model.learningLaunchDisabled", learn_view)
        self.assertIn("let writeDisabled = model.learningLaunchDisabled", diary_view)
        self.assertIn("actionDisabled: writeDisabled", diary_view)
        self.assertIn("model.hasActiveLearningJobs", diary_view)
        self.assertIn(".disabled(model.learningLaunchDisabled)", reflect_settings)

    def test_macos_you_surface_separates_evidence_and_question_actions(self) -> None:
        views = MACOS_VIEWS_PATH.read_text(encoding="utf-8")
        you_view = views.split("struct YouView: View", 1)[1].split("private func localizedYouText", 1)[0]
        question_row = views.split("struct QuestionLedgerRow: View", 1)[1].split("struct QuestionReplyPopover", 1)[0]

        self.assertIn("PersonalModelEvidencePanel()", you_view)
        self.assertIn("struct PersonalModelEvidencePanel", views)
        self.assertIn("Source-backed evidence", views)
        self.assertIn("model.snapshot.semanticEntries", views)
        self.assertIn("EvidenceTraceRow", views)

        self.assertIn("QuestionActionPillButton", question_row)
        self.assertIn("model.surfaceQuestionSooner(question)", question_row)
        self.assertIn("model.dismissQuestion(question)", question_row)
        self.assertIn("accessibilityLabel(replyText)", question_row)
        self.assertIn("help: surfaceHelpText", question_row)
        self.assertIn("help: dismissHelpText", question_row)

    def test_macos_paths_destructive_actions_are_confirmed_and_labeled(self) -> None:
        views = MACOS_VIEWS_PATH.read_text(encoding="utf-8")

        self.assertIn("deletePathTitle", views)
        self.assertIn("accessibilityLabel(deletePathTitle)", views)
        self.assertIn("confirmationDialog(deletePathTitle", views)
        self.assertIn("Button(deletePathTitle, role: .destructive", views)

        self.assertIn("deleteStepTitle", views)
        self.assertGreaterEqual(views.count("accessibilityLabel(deleteStepTitle)"), 2)
        self.assertGreaterEqual(views.count("confirmationDialog(deleteStepTitle"), 2)
        self.assertGreaterEqual(views.count("Button(deleteStepTitle, role: .destructive"), 2)

    def test_macos_paths_learning_summaries_expose_understanding_closure(self) -> None:
        app_model = MACOS_APP_MODEL_PATH.read_text(encoding="utf-8")
        api_client = MACOS_API_CLIENT_PATH.read_text(encoding="utf-8")
        views = MACOS_VIEWS_PATH.read_text(encoding="utf-8")
        learning_tab = views.split("private struct PathStepLearningTab: View", 1)[1].split("private struct PathStepPropertiesTab", 1)[0]
        properties_tab = views.split("private struct PathStepPropertiesTab: View", 1)[1].split("private struct PathReadonlyField", 1)[0]
        review_panel = views.split("private struct PathUnderstandingReviewPanel: View", 1)[1].split("private struct PathUnderstandingCheckButton", 1)[0]
        check_button = views.split("private struct PathUnderstandingCheckButton: View", 1)[1].split("private struct PathAssigneePicker", 1)[0]
        summary_panel = views.split("private struct LearningSummaryPanel: View", 1)[1].split("private struct PathSummaryCoreRow", 1)[0]

        self.assertIn("LearningSummaryPanel(summary: summary)", learning_tab)
        self.assertIn("Run the step or attach a summary before closing understanding.", learning_tab)
        self.assertIn("PathUnderstandingReviewPanel(step: step)", properties_tab)

        self.assertIn('step.status == "checking" || summary != nil', review_panel)
        self.assertIn("Understanding check will unlock after the summary is attached.", review_panel)
        self.assertIn("Task { await model.markLearningSummary(summary, understood: true) }", review_panel)
        self.assertIn('summary.check?.status != "understood"', review_panel)

        self.assertIn("Task { await model.markLearningSummary(summary, understood: true) }", summary_panel)
        self.assertIn("PathUnderstandingCheckButton(", summary_panel)
        self.assertIn("Marks this learning summary as understood.", check_button)
        self.assertIn(".disabled(understood)", check_button)
        self.assertIn('accessibilityValue(understood ? localizedYouText(model.appLanguage, en: "Understood"', check_button)

        self.assertIn("func markLearningSummary(_ summary: LearningSummaryItem, understood: Bool) async", app_model)
        self.assertIn("try await client.markUnderstanding", app_model)
        self.assertIn('pathActionResult = understood ? "Understanding checked" : "Marked for clarification"', app_model)
        self.assertIn("func markUnderstanding(", api_client)
        self.assertIn('path: "/v1/paths/\\(Self.pathSegment(pathID))/steps/\\(Self.pathSegment(stepID))/understanding-check"', api_client)
        self.assertIn('"summary_id": summaryID', api_client)
        self.assertIn('"status": understood ? "understood" : "needs_clarification"', api_client)
        self.assertIn('row["understanding_check"]', api_client)
        self.assertIn("UnderstandingCheckItem", api_client)

    def test_macos_messaging_surface_exposes_all_gateway_setup_paths(self) -> None:
        app_model = MACOS_APP_MODEL_PATH.read_text(encoding="utf-8")
        api_client = MACOS_API_CLIENT_PATH.read_text(encoding="utf-8")
        views = MACOS_VIEWS_PATH.read_text(encoding="utf-8")
        messaging_view = views.split("struct MessagingView: View", 1)[1].split("struct GatewayServiceCard", 1)[0]
        gateway_card = views.split("struct GatewayServiceCard: View", 1)[1].split("private struct MessagingServiceActionButton", 1)[0]
        logo_spec = views.split("private struct GatewayLogoSpec", 1)[1].split("struct GatewaySecretEditor", 1)[0]
        secret_editor = views.split("struct GatewaySecretEditor: View", 1)[1].split("struct WeixinQRPanel", 1)[0]
        weixin_panel = views.split("struct WeixinQRPanel: View", 1)[1].split("struct GatewayQRMatrixView", 1)[0]

        self.assertIn("snapshot.gatewayItems = gatewayServices.compactMap", api_client)
        self.assertIn('let id = string(row["service"] ?? row["id"] ?? row["key"])', api_client)
        self.assertIn('row["secretFields"]', api_client)

        self.assertIn('en: "Services"', messaging_view)
        self.assertIn('en: "Configured"', messaging_view)
        self.assertIn('en: "Running"', messaging_view)
        self.assertIn("GatewayServiceCard(service: service)", messaging_view)
        self.assertIn("Configure accounts, connect chat services, and scan WeChat QR", messaging_view)

        self.assertIn('if service.id == "weixin"', gateway_card)
        self.assertIn("WeixinQRPanel(service: service)", gateway_card)
        self.assertIn("GatewaySecretEditor(service: service)", gateway_card)
        self.assertIn("MessagingServiceActionButton(", gateway_card)
        self.assertIn("await model.configureGatewayService(service)", gateway_card)
        self.assertIn('await model.runGatewayAction(service: service, action: service.running ? "restart" : "start")', gateway_card)

        for service in ("wechat", "weixin", "feishu", "discord", "ding", "wecom"):
            with self.subTest(service=service):
                self.assertIn(service, logo_spec.lower())

        self.assertIn("SecureField(", secret_editor)
        self.assertIn("gatewaySecretDrafts[service.id]", secret_editor)
        self.assertIn("model.startWeixinQR()", weixin_panel)
        self.assertIn("GatewayQRMatrixView(matrix: model.gatewayQR.matrix)", weixin_panel)
        self.assertIn("Checking automatically", weixin_panel)
        self.assertIn("expired", weixin_panel)
        self.assertIn("failed", weixin_panel)

        self.assertIn("func runGatewayAction(service: GatewayServiceItem, action: String) async", app_model)
        self.assertIn("func configureGatewayService(_ service: GatewayServiceItem) async", app_model)
        self.assertIn("func startWeixinQR() async", app_model)
        self.assertIn("gatewayActionFailed = true", app_model)

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
