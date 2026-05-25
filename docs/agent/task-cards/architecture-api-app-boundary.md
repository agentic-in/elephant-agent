# architecture-api-app-boundary API And App Boundary Stabilization

## Roadmap Track

[Track A: API And App Boundary Stabilization](../plans/architecture-scorecard-roadmap.md#track-a-api-and-app-boundary-stabilization)

## Readiness

In progress. The current production app-to-app import inventory is now guarded
by the harness: the allowlist is empty, documented top-level app-support
composition sources are explicit source exceptions, and new cross-app imports
fail validation unless moved below `packages/` or registered as debt. Shared
terminal stack, terminal UI, and wizard primitives now live in
`packages.operator`, with old CLI module names preserved as compatibility
aliases; stale gateway runtime imports, wizard banner coupling, proactive ask
package ownership, Reflect feature registry ownership, Reflect runner/evidence
and context-compression ownership, shared terminal card rendering, and gateway
setup runtime binding have also been
cleaned up. The harness now treats the intentionally thin launcher dispatcher
and documented top-level daemon/dashboard/cron/worker composition modules as
explicit source exceptions rather than debt. Cron delivery visibility now lives
in `packages.gateway_core`, and the API manual-run path gets gateway delivery
and proactive-ask execution through the daemon bridge instead of importing
gateway runtime internals, bringing the app-boundary allowlist down to 5
entries. The CLI birth flow now invokes gateway setup through the gateway
command boundary instead of importing gateway internals directly, bringing the
allowlist down to 4 entries. API manual cron execution now also uses the
daemon bridge instead of constructing `CliRuntime`, bringing the allowlist down
to 3 entries. Gateway cron scheduling now receives its runtime through an
injected factory from the top-level cron command instead of importing
`CliRuntime`, bringing the allowlist down to 2 entries. API Reflect context
compression now receives its runtime through the daemon bridge instead of
constructing `CliRuntime`, bringing the allowlist down to 1 entry. Gateway CLI
control now uses the root app-support runtime bridge instead of importing
`apps.cli.runtime` directly, bringing the allowlist down to 0 entries. Breaking
CLI, HTTP, package
export, tool schema, or storage changes
are blocked until a follow-up ADR or tech-debt entry exists.

## Governing ADR

[ADR-0001 Scorecard Refactor Operating Model](../adr/adr-0001-scorecard-refactor-operating-model.md)

## Owner Profile

Runtime/app-boundary maintainer who can read CLI, API, gateway, and package
ports together without changing public behavior.

## Suggested Branch

`vsr/architecture-api-app-boundary`

## Suggested Worktree

`architecture-api-app-boundary`

## Dependencies

- Read `apps/AGENTS.md`, `apps/cli/AGENTS.md`, `apps/api/AGENTS.md`,
  `apps/gateway/AGENTS.md`, and `packages/AGENTS.md`.
- Confirm current app-to-app imports with `rg -n '^from apps\\.|^import apps\\.' apps packages`.

## Write Scope

- Primary: `apps/gateway/**`, `apps/api/**`, `apps/cli/**`,
  `apps/provider_runtime*.py`, `apps/runtime_layout.py`.
- Optional app-neutral extraction target: `packages/**`, only when the target
  package already owns the concept or the branch adds a narrow support module.
- Do not touch hotspot internals merely to reformat them.

## Deliverables

- Done: document and guard the current app-to-app import inventory.
- Done: move shared CLI terminal and wizard primitives behind package-level
  ports used by gateway setup/runtime code.
- Done: remove stale gateway runtime imports and move gateway wizard banner
  rendering to the package-level terminal UI port.
- Done: move proactive ask tick evaluation and adapter inventory into
  `packages.gateway_core` with the old gateway module kept as an alias.
- Done: move Reflect feature resolution into `packages.reflect.features` with
  the old reflect module kept as an alias.
- Done: move Reflect runner, evidence packets, prompt fragments, and context
  compression into `packages.reflect` with the old reflect modules kept as
  aliases.
- Done: move shared CLI/dashboard terminal card rendering into
  `packages.operator.cli_cards`.
- Done: remove the gateway setup wizard's static CLI runtime import by using a
  narrow protocol and explicit factory hook.
- Done: model documented top-level app composition sources, including daemon
  task scheduling, the standalone cron scheduler command, and the learning
  worker runtime, as source exceptions in the executable app-boundary guard,
  with regression coverage.
- Done: move cron delivery eligibility into `packages.gateway_core` and route
  API manual cron delivery through the daemon bridge instead of importing
  `apps.gateway.cron_service`.
- Done: route API proactive-ask execution through the daemon bridge instead of
  importing `apps.gateway.runtime`.
- Done: route CLI birth IM onboarding through `python -m apps.gateway setup`
  with additive prompt/skip options instead of importing `apps.gateway.__main__`.
- Done: route API manual cron execution through the daemon bridge instead of
  importing `apps.cli.runtime`.
- Done: remove the gateway cron service's static CLI runtime import by adding a
  runtime factory protocol and injecting it from the standalone cron command.
- Done: route API Reflect context compression runtime construction through the
  daemon bridge instead of importing `apps.cli.runtime`.
- Done: route gateway CLI control's default runtime construction through the
  root app-support bridge instead of importing `apps.cli.runtime`.
- Done: move API Weixin QR bootstrap and account persistence helpers into
  `packages.gateway_core.weixin_bootstrap` instead of importing
  `apps.gateway.weixin_support`.
- Done: split API dashboard gateway service catalog and Weixin QR operations
  into focused modules so `api_runtime_gateway_ops.py` remains below the
  line-limit gate.
- Remove one app-to-app dependency family or introduce the app-neutral port that
  makes the next removal mechanical.
- Add or update compatibility tests around the moved boundary.
- Update the scorecard row if the boundary score changes.

## Validation

- `make agent-report CHANGED_FILES="apps/gateway/... apps/api/... apps/cli/... packages/..."`
- `make agent-fast-gate`
- `make test-e2e` when CLI, API, or gateway behavior changes.

## Handoff

The executable app-to-app allowlist is now empty. Remaining boundary work is
architectural, not harness debt: continue replacing root app-support bridges
with package-owned runtime/sub-agent ports where practical.

## Guardrails

- No breaking public contracts.
- No new app-to-app imports outside launchers, compatibility shims, or tests.
- Keep moved behavior covered before deleting the old import path.
