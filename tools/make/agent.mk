##@ Agent

AGENT_PYTHON ?= $(PYTHON)

agent-help: ## Show help for agent-specific targets
	@echo "Agent commands:"
	@echo "  make agent-bootstrap"
	@echo "  make agent-validate"
	@echo "  make agent-scorecard"
	@echo "  make agent-report CHANGED_FILES=\"...\""
	@echo "  make agent-context-audit CHANGED_FILES=\"...\""
	@echo "  make agent-lint"
	@echo "  make agent-test"
	@echo "  make agent-fast-gate"
	@echo "  make agent-pr-gate"
	@echo "  make agent-commit-lint AGENT_BASE_REF=origin/main"
	@echo "  make agent-ship AGENT_COMMIT_MESSAGE='<type>(<scope>): <summary>'"
	@echo "  make agent-worktree-add WORKTREE_NAME=<name> WORKTREE_BRANCH=<branch>"
	@echo "  make agent-worktree-list"
	@echo "  make agent-worktree-remove WORKTREE_NAME=<name>"
	@echo "  make agent-wave-show WAVE=<wave-id>"
	@echo "  make agent-wave-start WAVE=<wave-id>"
	@echo "  make agent-wave-status WAVE=<wave-id>"

agent-bootstrap: ## Install local hook path and ensure worktree root exists
	@git config core.hooksPath .githooks
	@mkdir -p .githooks "$(WORKTREE_ROOT)"
	@printf '%s\n' '#!/usr/bin/env bash' 'set -euo pipefail' '' 'exec python3 tools/agent/scripts/commit_msg_lint.py message --file "$$1"' > .githooks/commit-msg
	@chmod +x .githooks/commit-msg
	@echo "Configured local core.hooksPath=.githooks"

agent-validate: ## Validate harness manifests and docs
	@"$(AGENT_PYTHON)" tools/agent/scripts/agent_gate.py validate --detail "$(AGENT_VALIDATE_DETAIL)"

agent-scorecard: ## Show harness governance scorecard
	@"$(AGENT_PYTHON)" tools/agent/scripts/agent_gate.py scorecard

AGENT_CONTEXT_DETAIL ?= compact
AGENT_REPORT_FORMAT ?= text
AGENT_REPORT_AUDIT ?=
AGENT_VALIDATE_DETAIL ?= compact

agent-report: ## Show primary surfaces and validation commands
	@"$(AGENT_PYTHON)" tools/agent/scripts/agent_gate.py report --base-ref "$(AGENT_BASE_REF)" --changed-files "$(CHANGED_FILES)" --changed-files-path "$(AGENT_CHANGED_FILES_PATH)" --context-detail "$(AGENT_CONTEXT_DETAIL)" --format "$(AGENT_REPORT_FORMAT)" $(if $(AGENT_REPORT_AUDIT),--audit)

agent-context-audit: ## Show context-map drift warnings for changed files
	@$(MAKE) agent-report CHANGED_FILES="$(CHANGED_FILES)" AGENT_CHANGED_FILES_PATH="$(AGENT_CHANGED_FILES_PATH)" AGENT_BASE_REF="$(AGENT_BASE_REF)" AGENT_REPORT_AUDIT=1

agent-lint: ## Run harness lint checks
	@"$(AGENT_PYTHON)" tools/agent/scripts/agent_gate.py lint --base-ref "$(AGENT_BASE_REF)" --changed-files "$(CHANGED_FILES)" --changed-files-path "$(AGENT_CHANGED_FILES_PATH)"

agent-test: ## Run harness regression tests
	@"$(AGENT_PYTHON)" -m unittest discover -s tests -p 'test_*.py'

agent-fast-gate: ## Run validate, lint, and tests
	@$(MAKE) agent-validate
	@$(MAKE) agent-lint CHANGED_FILES="$(CHANGED_FILES)" AGENT_CHANGED_FILES_PATH="$(AGENT_CHANGED_FILES_PATH)" AGENT_BASE_REF="$(AGENT_BASE_REF)"
	@$(MAKE) agent-test

agent-commit-lint: ## Lint commit subjects in a range
	@BASE_REF="$(AGENT_BASE_REF)"; \
	if [ -z "$$BASE_REF" ]; then \
		echo "AGENT_BASE_REF is required for commit range lint"; \
		exit 1; \
	fi; \
	"$(AGENT_PYTHON)" tools/agent/scripts/commit_msg_lint.py range --base-ref "$$BASE_REF"

agent-pr-gate: ## Reproduce the baseline PR gate locally
	@set -e; \
	BASE_REF="$(AGENT_BASE_REF)"; \
	if [ -z "$$BASE_REF" ] && git rev-parse --verify origin/main >/dev/null 2>&1; then \
		BASE_REF="origin/main"; \
	fi; \
	echo "Using AGENT_BASE_REF=$${BASE_REF:-<none>}"; \
	$(MAKE) agent-report CHANGED_FILES="$(CHANGED_FILES)" AGENT_CHANGED_FILES_PATH="$(AGENT_CHANGED_FILES_PATH)" AGENT_BASE_REF="$$BASE_REF" AGENT_REPORT_AUDIT=1; \
	$(MAKE) agent-fast-gate CHANGED_FILES="$(CHANGED_FILES)" AGENT_CHANGED_FILES_PATH="$(AGENT_CHANGED_FILES_PATH)" AGENT_BASE_REF="$$BASE_REF"; \
	if [ -n "$$BASE_REF" ]; then \
		$(MAKE) agent-commit-lint AGENT_BASE_REF="$$BASE_REF"; \
	else \
		echo "Skipping commit range lint because no base ref was found."; \
	fi

agent-ship: ## Run the PR gate, commit the current atomic change, and push the branch
	@MESSAGE="$(AGENT_COMMIT_MESSAGE)"; \
	if [ -z "$$MESSAGE" ]; then \
		echo "AGENT_COMMIT_MESSAGE is required"; \
		exit 1; \
	fi; \
	"$(AGENT_PYTHON)" tools/agent/scripts/ship.py --message "$$MESSAGE" $(if $(AGENT_BASE_REF),--base-ref "$(AGENT_BASE_REF)") $(if $(AGENT_PUSH_REMOTE),--remote "$(AGENT_PUSH_REMOTE)") $(if $(AGENT_PUSH_BRANCH),--branch "$(AGENT_PUSH_BRANCH)")

agent-worktree-add: ## Create a new worktree for a named task
	@NAME="$(WORKTREE_NAME)"; \
	BRANCH="$(WORKTREE_BRANCH)"; \
	if [ -z "$$NAME" ]; then \
		echo "WORKTREE_NAME is required"; \
		exit 1; \
	fi; \
	if [ -z "$$BRANCH" ]; then \
		BRANCH="chore/$$NAME"; \
	fi; \
	"$(AGENT_PYTHON)" tools/agent/scripts/worktree_manager.py add --name "$$NAME" --branch "$$BRANCH" --base "$(WORKTREE_BASE)" --root "$(WORKTREE_ROOT)"

agent-worktree-list: ## List active worktrees
	@"$(AGENT_PYTHON)" tools/agent/scripts/worktree_manager.py list --root "$(WORKTREE_ROOT)"

agent-worktree-remove: ## Remove an existing worktree by name
	@NAME="$(WORKTREE_NAME)"; \
	if [ -z "$$NAME" ]; then \
		echo "WORKTREE_NAME is required"; \
		exit 1; \
	fi; \
	"$(AGENT_PYTHON)" tools/agent/scripts/worktree_manager.py remove --name "$$NAME" --root "$(WORKTREE_ROOT)"

agent-wave-show: ## Show the tracks, cards, and branches for a named wave
	@WAVE_ID="$(WAVE)"; \
	if [ -z "$$WAVE_ID" ]; then \
		echo "WAVE is required"; \
		exit 1; \
	fi; \
	"$(AGENT_PYTHON)" tools/agent/scripts/wave_manager.py show --wave "$$WAVE_ID" --root "$(WORKTREE_ROOT)"

agent-wave-start: ## Create or attach the worktrees for a named wave
	@WAVE_ID="$(WAVE)"; \
	if [ -z "$$WAVE_ID" ]; then \
		echo "WAVE is required"; \
		exit 1; \
	fi; \
	"$(AGENT_PYTHON)" tools/agent/scripts/wave_manager.py start --wave "$$WAVE_ID" --root "$(WORKTREE_ROOT)" --base "$(WORKTREE_BASE)"

agent-wave-status: ## Show local worktree and remote branch status for a named wave
	@WAVE_ID="$(WAVE)"; \
	if [ -z "$$WAVE_ID" ]; then \
		echo "WAVE is required"; \
		exit 1; \
	fi; \
	"$(AGENT_PYTHON)" tools/agent/scripts/wave_manager.py status --wave "$$WAVE_ID" --root "$(WORKTREE_ROOT)"
