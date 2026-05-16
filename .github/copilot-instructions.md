# GitHub Copilot Instructions

This repository uses an agent harness. Treat code suggestions and review comments as changes to that harness, not as isolated edits.

## Source Of Truth Order

Follow the repository rule layers in this order:

1. `AGENTS.md`
2. `docs/agent/README.md`
3. relevant docs under `docs/agent/*`
4. executable rule sources under `tools/agent/*`, `tools/make/agent.mk`, `.githooks/*`, and `.github/workflows/*`
5. nearest local `AGENTS.md` for hotspot directories

Interpret them this way:

- `AGENTS.md` is the short entrypoint and command index.
- `docs/agent/*` is the human-readable system of record.
- manifests, scripts, Make targets, hooks, and workflows are the executable contract.
- local `AGENTS.md` files are narrow supplements for specific directories.

Do not invent a second source of truth in suggestions or reviews.

## Review Priorities

When reviewing a change, first check whether it follows the harness:

- the change resolves through the correct `make agent-report` surface
- docs, templates, workflows, Make targets, and executable rules stay aligned
- contributor-facing files such as `README.md`, `CONTRIBUTING.md`, `.github/PULL_REQUEST_TEMPLATE.md`, issue templates, and this file stay aligned with the canonical harness
- repeated governance requirements are enforced mechanically when practical

Then review the implementation for bugs, regressions, missing validation, security issues, and maintainability risks.

## Harness-Specific Checks

- For harness changes, verify alignment with `docs/agent/governance.md`, `docs/agent/testing-strategy.md`, `docs/agent/feature-complete-checklist.md`, `tools/agent/repo-manifest.yaml`, `tools/agent/task-matrix.yaml`, `tools/agent/skill-registry.yaml`, and `tools/agent/context-map.yaml`.
- For hotspot changes, verify the nearest local `AGENTS.md` was respected.
- For long-horizon work, verify active execution state lives under `docs/agent/plans/*.md`.
- For unresolved architecture or implementation gaps, verify the gap is promoted to `docs/agent/tech-debt/`.
- For durable governance or architecture decisions, verify an ADR under `docs/agent/adr/` is used when needed.

## Validation Expectations

Review changes against `docs/agent/testing-strategy.md`.

Flag missing validation when:

- CI, release, hooks, or contributor-interface changes do not run `make agent-validate` and `make agent-test`
- product behavior changes do not use the relevant top-level Make target
- template or documentation changes drift away from the canonical harness entrypoints

## Review Output Style

Prioritize concrete findings about:

1. bugs or behavioral regressions
2. harness violations or source-of-truth drift
3. missing validation
4. architecture, modularity, or hotspot ownership issues

Keep findings file-specific and actionable. If there are no findings, say so briefly and note any residual validation risk.
