# architecture-runtime-stability Runtime Performance And Stability

## Roadmap Track

[Track C: Runtime Performance And Stability](../plans/architecture-scorecard-roadmap.md#track-c-runtime-performance-and-stability)

## Readiness

In progress. Episode close side-effect failures are now observable: exit-summary
indexing and learning-job enqueue failures log warnings with regression coverage
instead of being silently swallowed. Kernel lifecycle step and exit-summary
indexing failures are also logged with coverage. The latest stability pass also
makes kernel generation-context Personal Model fact load failures, daemon status
describe failures, proactive-ask state/profile fallback failures, and gateway
cron fan-out delivery failures observable while preserving best-effort behavior.
The scorecard also reports silent broad exception debt so this family can be
driven down incrementally. The 2026-05-25 observability pass drove that
executable debt to zero while preserving best-effort fallback behavior.

## Governing ADR

[ADR-0001 Scorecard Refactor Operating Model](../adr/adr-0001-scorecard-refactor-operating-model.md)

## Owner Profile

Runtime maintainer who can reason about kernel, storage, evidence, gateway
async lifecycle, and streaming observer behavior.

## Suggested Branch

`vsr/architecture-runtime-stability`

## Suggested Worktree

`architecture-runtime-stability`

## Dependencies

- Read the nearest `AGENTS.md` for each touched package or app.
- Start with one risk family: SQLite transaction/lock policy, semantic cache
  miss/backfill, gateway async lifecycle, streaming observer locks, or broad
  silent exception handling.

## Write Scope

- One risk family only.
- Likely targets: `packages/storage/**`, `packages/evidence/**`,
  `packages/kernel/**`, `apps/gateway/**`, or matching tests.
- Do not combine runtime stability work with hotspot decomposition unless the
  stability fix requires a small local extraction.

## Deliverables

- Done for Episode close side effects: convert silent indexing/enqueue failures
  into warning logs.
- Done for Episode close side effects: add focused regression coverage that
  would fail on the old silent behavior.
- Done for kernel lifecycle indexing: log step and exit-summary indexing
  failures with focused regression coverage.
- Done for generation context: log committed and dynamic Personal Model fact
  load failures while allowing prompt construction to continue.
- Done for daemon status surfaces: log registry service-key and adapter
  describe failures while keeping `/status` and dashboard snapshots resilient.
- Done for proactive ask fallback paths: log state/profile load failures before
  falling back to session binding or environment timezone.
- Done for gateway cron fan-out: log adapter delivery callback failures and
  continue delivery to other configured callbacks.
- Done for API startup/config: log embedding steady-state, built-in cron
  bootstrap, and proactive-ask config persistence failures.
- Done for API episode queries: log direct and legacy fallback repository query
  failures.
- Done for evidence indexing: log embedding, document construction, contract
  import, and semantic-index write failures in summary indexing.
- Done for context resource paths: log projection token fallback, embedding
  cache/backfill failures, provider summary fallback, and reflect compression
  fallback.
- Done for harness observability: add `Silent broad exception debt` to
  `make agent-scorecard`; first measured baseline was 235 and is now 0.
- Done for broad fallback observability: API, CLI, gateway, context, evidence,
  Reflect, model, skill, tool, embedding, and understanding fallback paths now
  log or narrow exceptions instead of silently swallowing broad failures.
- Continue converting one risk family at a time into explicit policy,
  logging/telemetry, timeout, or bounded query behavior.
- Update the scorecard evidence and any debt entry created by the branch.

## Validation

- `make agent-report CHANGED_FILES="packages/... apps/gateway/... tests/..."`
- Targeted unit or integration tests for the selected risk.
- `make test-integration-scenarios` for kernel, storage, context, or evidence
  changes.
- `make agent-fast-gate`

## Handoff

Name the next unaddressed runtime risk and whether it should run in parallel or
wait for this branch.

## Guardrails

- Failures should become observable without making best-effort paths brittle.
- Keep hot paths bounded.
- Avoid global cache or async lifecycle changes without regression tests.
