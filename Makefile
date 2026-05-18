.PHONY: help lint preview \
	site-help site-install site-dev site-preview site-build site-typecheck \
	dashboard-help dashboard-install dashboard-dev dashboard-build dashboard-typecheck \
	pipeline-help web-install web-build web-typecheck \
	test-e2e test-installed-user-journey test-release-e2e test-release-contracts test-release-scenarios test-integration-scenarios test-design-closure-reset-matrix test-install-surfaces test-live-installed-smoke test-live-provider-smoke \
	package-build package-verify build-and-test e2e release design-closure

PYTHON ?= python3
CHANGED_FILES ?=
AGENT_CHANGED_FILES_PATH ?=
AGENT_BASE_REF ?=
WORKTREE_NAME ?=
WORKTREE_BRANCH ?=
WORKTREE_BASE ?= main
WORKTREE_ROOT ?= .worktrees
RESET_API_E2E_TARGETS = \
	tests.e2e.api.test_api_surface.APISurfaceE2ETest.test_operator_namespace_no_longer_exposes_public_dashboard_reads \
	tests.e2e.api.test_api_surface.APISurfaceE2ETest.test_operator_dashboard_projection_is_empty_without_runtime_state \
	tests.e2e.api.test_api_surface.APISurfaceE2ETest.test_internal_dashboard_projection_surfaces_canonical_runtime_and_evidence \
	tests.e2e.api.test_api_surface.APISurfaceE2ETest.test_default_provider_bad_request_hides_legacy_profile_field_names

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
	@cd apps/site && npm run typecheck

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
	@echo "  make build-and-test [AGENT_BASE_REF=<ref>]"
	@echo "  make e2e"
	@echo "  make test-live-provider-smoke"
	@echo "  make release [AGENT_BASE_REF=<ref>]"
	@echo "  make design-closure [AGENT_BASE_REF=<ref>]"
	@echo "  make package-build"
	@echo "  make package-verify"

web-install: site-install dashboard-install

web-typecheck: site-typecheck dashboard-typecheck

web-build: site-build dashboard-build

test-e2e:
	@"$(PYTHON)" -m unittest \
		tests.e2e.api.test_api_surface \
		tests.e2e.cli.test_cli_surface \
		tests.e2e.deploy.test_editable_install \
		tests.e2e.deploy.test_installed_user_journey \
		tests.e2e.deploy.test_installed_command_smoke \
		tests.e2e.deploy.test_install_distribution \
		tests.e2e.deploy.test_preview_deploy \
		tests.e2e.deploy.test_runtime_topology \
		tests.e2e.gateway.test_gateway_adapter

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
	@uvx twine check dist/*
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
