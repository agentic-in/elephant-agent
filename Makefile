.PHONY: help lint preview \
	site-help site-install site-dev site-preview site-build site-typecheck site-content-check \
	dashboard-help dashboard-install dashboard-dev dashboard-build dashboard-typecheck \
	pipeline-help web-install web-build web-typecheck web-content-check \
	macos-help macos-build macos-build-all macos-release-latest \
	test-e2e test-gateway-e2e-smoke test-installed-user-journey test-release-e2e test-release-contracts test-release-scenarios test-integration-scenarios test-design-closure-reset-matrix test-install-surfaces test-live-installed-smoke test-live-provider-smoke \
	package-build package-provenance package-verify build-and-test e2e release design-closure

PYTHON ?= python3
CHANGED_FILES ?=
AGENT_CHANGED_FILES_PATH ?=
AGENT_BASE_REF ?=
WORKTREE_NAME ?=
WORKTREE_BRANCH ?=
WORKTREE_BASE ?= main
WORKTREE_ROOT ?= .worktrees
MACOS_TARGET ?=
MACOS_TARGETS ?= aarch64-apple-darwin x86_64-apple-darwin
MACOS_APP_VERSION ?=
MACOS_APP_BUILD_NUMBER ?=
MACOS_SIGNING_IDENTITY ?= -
MACOS_NOTARIZE ?=
MACOS_ASSET_DIR ?=
MACOS_BUNDLE_RUNTIME ?= auto
MACOS_RUNTIME_PYTHON_VERSION ?= 3.12
MACOS_RUNTIME_PYTHON ?=
MACOS_RELEASE_TAG ?= latest
MACOS_RELEASE_TITLE ?= Elephant Agent latest
RESET_API_E2E_TARGETS = \
	tests.e2e.api.test_api_surface_dashboard.APISurfaceDashboardE2ETest.test_operator_namespace_no_longer_exposes_public_dashboard_reads \
	tests.e2e.api.test_api_surface_dashboard.APISurfaceDashboardE2ETest.test_operator_dashboard_projection_is_empty_without_runtime_state \
	tests.e2e.api.test_api_surface_dashboard.APISurfaceDashboardE2ETest.test_internal_dashboard_projection_surfaces_canonical_runtime_and_evidence \
	tests.e2e.api.test_api_surface_providers.APISurfaceProviderE2ETest.test_default_provider_bad_request_hides_legacy_profile_field_names
GATEWAY_E2E_SMOKE_TARGETS = \
	tests.e2e.gateway.test_gateway_adapter.GatewayAdapterE2ETests.test_gateway_state_dir_uses_shared_runtime_database \
	tests.e2e.gateway.test_gateway_adapter.GatewayAdapterE2ETests.test_gateway_chat_runtime_exposes_model_tools_and_skills \
	tests.e2e.gateway.test_gateway_adapter_discord_runtime.GatewayAdapterDiscordRuntimeE2ETests.test_discord_service_dispatch_event_delivers_dm_reply_with_mentions_suppressed \
	tests.e2e.gateway.test_gateway_adapter_feishu_runtime.GatewayAdapterFeishuRuntimeE2ETests.test_feishu_gateway_service_uses_manifest_account_and_dispatches_reply \
	tests.e2e.gateway.test_gateway_adapter_feishu_async_runtime.GatewayAdapterFeishuAsyncRuntimeE2ETests.test_feishu_async_long_connection_runs_different_conversations_in_parallel \
	tests.e2e.gateway.test_gateway_adapter_feishu_control.GatewayAdapterFeishuControlE2ETests.test_feishu_control_bridge_binds_conversation_to_selected_elephant \
	tests.e2e.gateway.test_gateway_adapter_telegram.GatewayAdapterTelegramE2ETests.test_telegram_private_update_reuses_identity_mapping_across_restart

help: agent-help site-help dashboard-help pipeline-help

lint: ## Run repository lint checks
	@$(MAKE) agent-lint CHANGED_FILES="$(CHANGED_FILES)" AGENT_CHANGED_FILES_PATH="$(AGENT_CHANGED_FILES_PATH)" AGENT_BASE_REF="$(AGENT_BASE_REF)"

site-help:
	@echo "Site commands:"
	@echo "  make site-install"
	@echo "  make site-dev"
	@echo "  make preview [PORT=4180]"
	@echo "  make site-build"
	@echo "  make site-typecheck"
	@echo "  make site-content-check"

site-install:
	@cd apps/site && npm ci

site-dev:
	@cd apps/site && npm start

preview: site-preview

site-preview:
	@bash apps/site/preview.sh

site-build:
	@bash apps/site/build.sh

site-typecheck:
	@cd apps/site && npm run ci:check

site-content-check:
	@cd apps/site && npm run check:content

dashboard-help:
	@echo "Dashboard commands:"
	@echo "  make dashboard-install"
	@echo "  make dashboard-dev"
	@echo "  make dashboard-build"
	@echo "  make dashboard-typecheck"

dashboard-install:
	@cd apps/dashboard && npm ci

dashboard-dev:
	@cd apps/dashboard && npm run dev

dashboard-build:
	@cd apps/dashboard && npm run build

dashboard-typecheck:
	@cd apps/dashboard && npm run typecheck

pipeline-help:
	@echo "Pipeline commands:"
	@echo "  make web-install"
	@echo "  make web-typecheck"
	@echo "  make web-build"
	@echo "  make web-content-check"
	@echo "  make macos-build [MACOS_TARGET=aarch64-apple-darwin|x86_64-apple-darwin]"
	@echo "  make macos-build-all"
	@echo "  make macos-release-latest [MACOS_RELEASE_TAG=latest]"
	@echo "  make build-and-test [AGENT_BASE_REF=<ref>]"
	@echo "  make e2e"
	@echo "  make test-gateway-e2e-smoke"
	@echo "  make test-live-provider-smoke"
	@echo "  make release [AGENT_BASE_REF=<ref>]"
	@echo "  make design-closure [AGENT_BASE_REF=<ref>]"
	@echo "  make package-build"
	@echo "  make package-provenance"
	@echo "  make package-verify"

web-install: site-install dashboard-install

web-typecheck: site-typecheck dashboard-typecheck

web-build: site-build dashboard-build

web-content-check: site-content-check

macos-help:
	@echo "macOS commands:"
	@echo "  make macos-build  # canonical local app build; prints absolute output paths"
	@echo "  make macos-build MACOS_TARGET=aarch64-apple-darwin"
	@echo "  make macos-build MACOS_TARGET=x86_64-apple-darwin"
	@echo "  make macos-build-all"
	@echo "  make macos-release-latest"
	@echo "  MACOS_BUNDLE_RUNTIME=auto|1|0"
	@echo "  MACOS_RUNTIME_PYTHON=/path/to/python3.12"
	@echo ""
	@echo "Signing/notarization variables:"
	@echo "  MACOS_SIGNING_IDENTITY=-     # local default; ad-hoc sign for privacy-sensitive flows"
	@echo "  MACOS_SIGNING_IDENTITY=none  # skip codesign for packaging-only debugging"
	@echo "  MACOS_SIGNING_IDENTITY='Developer ID Application: ...'"
	@echo "  MACOS_NOTARIZE=1 APPLE_ID=... APPLE_PASSWORD=... APPLE_TEAM_ID=..."

macos-build:
	@echo "==> Building macOS app via make macos-build"
	@env \
		MACOS_TARGET="$(MACOS_TARGET)" \
		MACOS_APP_VERSION="$(MACOS_APP_VERSION)" \
		MACOS_APP_BUILD_NUMBER="$(MACOS_APP_BUILD_NUMBER)" \
		MACOS_SIGNING_IDENTITY="$(MACOS_SIGNING_IDENTITY)" \
		MACOS_NOTARIZE="$(MACOS_NOTARIZE)" \
		MACOS_ASSET_DIR="$(MACOS_ASSET_DIR)" \
		MACOS_BUNDLE_RUNTIME="$(MACOS_BUNDLE_RUNTIME)" \
		MACOS_RUNTIME_PYTHON_VERSION="$(MACOS_RUNTIME_PYTHON_VERSION)" \
		MACOS_RUNTIME_PYTHON="$(MACOS_RUNTIME_PYTHON)" \
		bash apps/macos/Scripts/build-app.sh

macos-build-all:
	@for target in $(MACOS_TARGETS); do \
		echo "==> Building macOS $$target"; \
		$(MAKE) macos-build \
			MACOS_TARGET="$$target" \
			MACOS_APP_VERSION="$(MACOS_APP_VERSION)" \
			MACOS_APP_BUILD_NUMBER="$(MACOS_APP_BUILD_NUMBER)" \
			MACOS_SIGNING_IDENTITY="$(MACOS_SIGNING_IDENTITY)" \
			MACOS_NOTARIZE="$(MACOS_NOTARIZE)" \
			MACOS_ASSET_DIR="$(MACOS_ASSET_DIR)" \
			MACOS_BUNDLE_RUNTIME="$(MACOS_BUNDLE_RUNTIME)" \
			MACOS_RUNTIME_PYTHON_VERSION="$(MACOS_RUNTIME_PYTHON_VERSION)" \
			MACOS_RUNTIME_PYTHON="$(MACOS_RUNTIME_PYTHON)"; \
	done

macos-release-latest: macos-build-all
	@env \
		MACOS_ASSET_DIR="$(MACOS_ASSET_DIR)" \
		MACOS_RELEASE_TAG="$(MACOS_RELEASE_TAG)" \
		MACOS_RELEASE_TITLE="$(MACOS_RELEASE_TITLE)" \
		MACOS_RELEASE_VERSION="$(MACOS_APP_VERSION)" \
		bash apps/macos/Scripts/release-latest.sh

test-e2e:
	@"$(PYTHON)" -m unittest \
		tests.e2e.api.test_api_surface \
		tests.e2e.api.test_api_surface_dashboard \
		tests.e2e.api.test_api_surface_dashboard_ops \
		tests.e2e.api.test_api_surface_providers \
		tests.e2e.cli.test_cli_surface \
		tests.e2e.cli.test_cli_surface_facts \
		tests.e2e.cli.test_cli_surface_herd \
		tests.e2e.cli.test_cli_surface_provider \
		tests.e2e.cli.test_cli_surface_skills \
		tests.e2e.deploy.test_editable_install \
		tests.e2e.deploy.test_installed_user_journey \
		tests.e2e.deploy.test_installed_command_smoke \
		tests.e2e.deploy.test_install_distribution \
		tests.e2e.deploy.test_preview_deploy \
		tests.e2e.deploy.test_runtime_topology \
		tests.e2e.gateway.test_gateway_adapter \
		tests.e2e.gateway.test_gateway_adapter_chat_webhook \
		tests.e2e.gateway.test_gateway_adapter_cli_surface \
		tests.e2e.gateway.test_gateway_adapter_discord \
		tests.e2e.gateway.test_gateway_adapter_discord_runtime \
		tests.e2e.gateway.test_gateway_adapter_feishu_async_runtime \
		tests.e2e.gateway.test_gateway_adapter_feishu_control \
		tests.e2e.gateway.test_gateway_adapter_feishu_events \
		tests.e2e.gateway.test_gateway_adapter_feishu_runtime \
		tests.e2e.gateway.test_gateway_adapter_feishu_long_connection \
		tests.e2e.gateway.test_gateway_adapter_feishu_setup \
		tests.e2e.gateway.test_gateway_adapter_services \
		tests.e2e.gateway.test_gateway_adapter_telegram \
		tests.e2e.gateway.test_gateway_adapter_weixin_wecom

test-gateway-e2e-smoke:
	@"$(PYTHON)" -m unittest \
		$(GATEWAY_E2E_SMOKE_TARGETS)

test-installed-user-journey: dashboard-build
	@"$(PYTHON)" -m unittest \
		tests.e2e.deploy.test_installed_user_journey

test-release-e2e:
	@"$(PYTHON)" -m unittest \
		$(RESET_API_E2E_TARGETS)

test-release-contracts:
	@"$(PYTHON)" -m unittest \
		tests.e2e.release.test_release_certification.ReleaseCertificationContractsTest \
		tests.e2e.release.test_design_closure_certification.DesignClosureContractsTest

test-release-scenarios:
	@"$(PYTHON)" -m unittest \
		tests.scenarios.context.test_context_scenarios \
		tests.unit.recall.test_recall_scenarios \
		tests.scenarios.continuity.test_continuity_scenarios

test-integration-scenarios:
	@"$(PYTHON)" -m unittest \
		tests.integration.kernel.test_turn_lifecycle \
		tests.integration.models_auth \
		tests.integration.storage_system_layers.test_repository \
		tests.integration.tools_skills.test_tools_and_skills_runtime \
		tests.integration.security_observability \
		tests.scenarios.context.test_context_scenarios \
		tests.unit.recall.test_recall_scenarios \
		tests.scenarios.continuity.test_continuity_scenarios \
		tests.scenarios.companion.test_companion_scenarios

test-design-closure-reset-matrix:
	@"$(PYTHON)" -m unittest \
		tests.agent.test_system_layer_reset_matrix

test-install-surfaces:
	@"$(PYTHON)" -m unittest \
		tests.e2e.deploy.test_public_install_script \
		tests.e2e.deploy.test_install_distribution

test-live-installed-smoke:
	@"$(PYTHON)" -m unittest \
		tests.e2e.deploy.test_installed_command_smoke.InstalledCommandLiveSmokeTest

test-live-provider-smoke:
	@"$(PYTHON)" -m unittest \
		tests.e2e.release.test_release_certification.LiveProviderCertificationSmokeTest
	@ELEPHANT_LIVE_INSTALLED_SMOKE_REQUIRE_DASHBOARD=1 "$(MAKE)" test-live-installed-smoke

package-build:
	@$(MAKE) dashboard-install
	@$(MAKE) dashboard-build
	@rm -rf dist
	@uv build
	@ls -la dist/

package-provenance:
	@"$(PYTHON)" tools/release/provenance.py --dist-dir dist

package-verify:
	@if unzip -l dist/*.whl | grep -q "apps/site/node_modules"; then \
		echo "::error::site node_modules leaked into the Python wheel"; \
		exit 1; \
	fi
	@if ! unzip -l dist/*.whl | grep -q "packages/storage/schema.sql"; then \
		echo "::error::clean storage schema is missing from the wheel"; \
		exit 1; \
	fi
	@if unzip -l dist/*.whl | grep -q "packages/storage/migrations/"; then \
		echo "::error::legacy storage migrations leaked into the wheel"; \
		exit 1; \
	fi
	@if ! unzip -l dist/*.whl | grep -q "apps/dashboard/dist/index.html"; then \
		echo "::error::dashboard frontend assets are missing from the wheel"; \
		exit 1; \
	fi
	@uvx twine check dist/*.whl dist/*.tar.gz
	@$(MAKE) package-provenance
	@test -s dist/elephant-agent-provenance.json
	@test -s dist/SHA256SUMS
	@$(MAKE) test-install-surfaces

build-and-test:
	@$(MAKE) agent-validate
	@$(MAKE) agent-lint CHANGED_FILES="$(CHANGED_FILES)" AGENT_CHANGED_FILES_PATH="$(AGENT_CHANGED_FILES_PATH)" AGENT_BASE_REF="$(AGENT_BASE_REF)"
	@$(MAKE) agent-test
	@$(MAKE) web-typecheck
	@$(MAKE) web-build

e2e: web-build
	@$(MAKE) test-e2e

release:
	@$(MAKE) test-release-contracts
	@$(MAKE) test-release-e2e
	@$(MAKE) test-release-scenarios
	@$(MAKE) web-build
	@$(MAKE) package-build
	@$(MAKE) package-verify
	@$(MAKE) agent-pr-gate CHANGED_FILES="$(CHANGED_FILES)" AGENT_CHANGED_FILES_PATH="$(AGENT_CHANGED_FILES_PATH)" AGENT_BASE_REF="$(AGENT_BASE_REF)"

design-closure:
	@$(MAKE) test-release-contracts
	@$(MAKE) test-release-e2e
	@$(MAKE) test-design-closure-reset-matrix
	@$(MAKE) web-build
	@$(MAKE) agent-pr-gate CHANGED_FILES="$(CHANGED_FILES)" AGENT_CHANGED_FILES_PATH="$(AGENT_CHANGED_FILES_PATH)" AGENT_BASE_REF="$(AGENT_BASE_REF)"

include tools/make/agent.mk
