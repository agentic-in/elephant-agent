# Agent Docs Index

This directory is the human-readable system of record for the `elephant` harness.

`AGENTS.md` is the short entrypoint. Detailed rules, collaboration patterns, and validation policy live here.

## Start Here

- [governance.md](governance.md)
  - harness layering and source-of-truth policy
- [repo-map.md](repo-map.md)
  - current directory layout and where future code should land
- [change-surfaces.md](change-surfaces.md)
  - change taxonomy used by `make agent-report`
- [testing-strategy.md](testing-strategy.md)
  - validation ladder and expected gates
- [feature-complete-checklist.md](feature-complete-checklist.md)
  - done criteria for changes that should be considered complete

## Governance And Planning

- [architecture-guardrails.md](architecture-guardrails.md)
  - file-shape, layering, and anti-sprawl rules
- [worktree-parallelism.md](worktree-parallelism.md)
  - multi-worktree and multi-agent operating model
- [release-model.md](release-model.md)
  - how to think about preview, release, and post-release follow-up before the product stack is finalized
- [plans/README.md](plans/README.md)
  - execution-plan policy for long-horizon work; currently reset for new plans
    derived from the canonical system layer model
- [task-cards/README.md](task-cards/README.md)
  - directly assignable execution-unit policy; currently reset for new task
    cards derived from future plans and ADRs
- [tech-debt/README.md](tech-debt/README.md)
  - debt entry policy; currently reset with no active entries
- [adr/README.md](adr/README.md)
  - architectural decision record index and usage policy; currently reset for
    new ADRs derived from the canonical system layer model

## Executable Contract

- [../../tools/agent/repo-manifest.yaml](../../tools/agent/repo-manifest.yaml)
- [../../tools/agent/task-matrix.yaml](../../tools/agent/task-matrix.yaml)
- [../../tools/agent/skill-registry.yaml](../../tools/agent/skill-registry.yaml)
- [../../tools/agent/structure-rules.yaml](../../tools/agent/structure-rules.yaml)
- [../../tools/agent/wave-registry.yaml](../../tools/agent/wave-registry.yaml)
- [../../tools/make/agent.mk](../../tools/make/agent.mk)

Runtime entrypoints:

- `make agent-bootstrap`
- `make agent-validate`
- `make agent-scorecard`
- `make agent-report CHANGED_FILES="..."`
- `make agent-context-audit CHANGED_FILES="..."`
- `make agent-lint`
- `make agent-test`
- `make agent-pr-gate`
- `make agent-ship AGENT_COMMIT_MESSAGE="..."`
- `make test-live-provider-smoke`
- `make agent-wave-show WAVE=<wave-id>`
- `make agent-wave-start WAVE=<wave-id>`
- `make agent-wave-status WAVE=<wave-id>`

## Contributor Interface

- [../../AGENTS.md](../../AGENTS.md)
- [../../README.md](../../README.md)
- [../../CONTRIBUTING.md](../../CONTRIBUTING.md)
- [../../CHANGELOG.md](../../CHANGELOG.md)
- [../../.github/PULL_REQUEST_TEMPLATE.md](../../.github/PULL_REQUEST_TEMPLATE.md)
- [../../.github/ISSUE_TEMPLATE/001_feature_request.yaml](../../.github/ISSUE_TEMPLATE/001_feature_request.yaml)
- [../../.github/ISSUE_TEMPLATE/002_bug_report.yaml](../../.github/ISSUE_TEMPLATE/002_bug_report.yaml)
- [../../.github/ISSUE_TEMPLATE/config.yml](../../.github/ISSUE_TEMPLATE/config.yml)
- [../../.github/copilot-instructions.md](../../.github/copilot-instructions.md)
