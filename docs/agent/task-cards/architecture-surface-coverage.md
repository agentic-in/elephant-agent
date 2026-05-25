# architecture-surface-coverage Frontend Desktop And Gateway Coverage

## Roadmap Track

[Track E: Frontend, Desktop, Gateway Adapter Coverage](../plans/architecture-scorecard-roadmap.md#track-e-frontend-desktop-gateway-adapter-coverage)

## Readiness

Ready for a coverage-inventory branch that brings dashboard, site, macOS, and
gateway adapters into the same scorecard discipline without blocking core
runtime cleanup.

## Governing ADR

[ADR-0001 Scorecard Refactor Operating Model](../adr/adr-0001-scorecard-refactor-operating-model.md)

## Owner Profile

Surface maintainer who can inspect frontend build/typecheck, native macOS build
paths, API e2e coverage, and gateway adapter e2e coverage.

## Suggested Branch

`vsr/architecture-surface-coverage`

## Suggested Worktree

`architecture-surface-coverage`

## Dependencies

- Read `apps/dashboard/AGENTS.md`, `apps/site/AGENTS.md`,
  `apps/macos/AGENTS.md`, `apps/gateway/AGENTS.md`, and matching test
  `AGENTS.md` files.

## Write Scope

- Primary: `apps/dashboard/**`, `apps/site/**`, `apps/macos/**`,
  `apps/gateway/**`, `tests/e2e/api/**`, `tests/e2e/gateway/**`, and docs that
  describe their validation.
- Do not change core runtime behavior in this card.

## Deliverables

- Inventory current build/typecheck/e2e coverage for dashboard, site, macOS,
  API surfaces, and gateway adapters.
- Keep focused API e2e suites registered in `make test-e2e` and release-smoke
  targets when public-provider or route contracts move.
- Add the smallest missing validation hook or documentation update that removes
  an ambiguity from the scorecard.
- Update the scorecard evidence for non-core surface coverage.

## Validation

- `make web-content-check`
- `make web-typecheck`
- `make web-build` when frontend code changes.
- `make macos-build` when macOS code changes.
- Targeted API or gateway e2e when route/provider/adapter behavior changes.
- `make agent-fast-gate`

## Handoff

List surfaces still lacking build, typecheck, e2e, or release proof and assign
the next safe branch.

## Guardrails

- Keep this card coverage-focused.
- Do not let non-core surface cleanup preempt core runtime/API/storage risks.
- Avoid frontend or macOS changes without the matching build gate.
