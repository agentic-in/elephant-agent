# Testing Strategy

## Validation Ladder

Run the smallest gate that proves the current change:

1. `make agent-validate`
   - manifest, doc, and contract integrity
2. `make agent-context-audit CHANGED_FILES="..."`
   - context-map drift prompt for changed files
3. `make agent-lint`
   - structure checks plus Python compile smoke for harness scripts and tests, with targeted frontend typecheck for touched `apps/dashboard/**` and `apps/site/**` surfaces
4. `make agent-test`
   - harness regression tests
5. `make agent-fast-gate`
   - validate + lint + tests
6. `make agent-pr-gate`
   - report + fast gate + commit-range lint when a base ref exists

## Product And Pipeline Entry Points

The repo now exposes reproducible top-level pipeline targets in `Makefile` so local
validation and GitHub Actions share the same contract:

- `make build-and-test`
  - root CI contract: harness validation + lint + full Python test discovery + site/dashboard typecheck and build
- `make e2e`
  - deterministic e2e matrix for API, CLI, deploy, gateway, and voice surfaces
- `make test-live-provider-smoke`
  - optional secret-backed live smoke for release/design-closure dispatches; it
    runs both the runtime module provider smoke and a real editable install of
    the installed `elephant` command
- `make release`
  - deterministic release certification, package build/verification, install-surface validation, and final repo gate
- `make design-closure`
  - stronger design-closure certification across contract, integration, scenario, and repo-gate surfaces

## Current Scope

The repo currently validates both the harness and the product-facing runtime surfaces:

- commit message rules
- task-surface resolution
- manifest coherence
- CI and hook wiring
- public docs/site build
- operator dashboard build
- deterministic e2e and release certification contracts
- optional installed-command live smoke: when
  `ELEPHANT_LIVE_PROVIDER_BASE_URL`, `ELEPHANT_LIVE_PROVIDER_MODEL`, and
  `ELEPHANT_LIVE_PROVIDER_API_KEY` are set, the workflow creates a fresh venv,
  runs `pip install -e .`, exercises installed `elephant` subcommands, and drives
  the TUI through a pty; without those env vars the test skips

As product code lands, extend the matrix instead of bypassing it.

## Done Criteria

A change is not done when the first gate fails. Fix the issue and rerun the smallest applicable gate until the active surface is green.
