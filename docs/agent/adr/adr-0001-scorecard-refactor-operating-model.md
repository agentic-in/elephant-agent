# ADR-0001 Scorecard Refactor Operating Model

Status: Proposed

## Context

The full-system architecture scorecard currently identifies the repo as a
healthy but not yet 100/100 system. The remaining work spans app boundaries,
hotspot decomposition, runtime stability, release posture, and non-core surface
coverage. Those tracks are coupled enough that broad unsupervised refactors
could accidentally change public CLI, HTTP, tool, package, or storage behavior.

The active roadmap is
[architecture-scorecard-roadmap.md](../plans/architecture-scorecard-roadmap.md).
It measures convergence toward the canonical Understanding System in
[system-layer-model.md](../../system-design/system-layer-model.md).

## Decision

- Use the full-system scorecard as the durable scoring and prioritization
  entrypoint for 100/100 architecture work.
- Keep first-wave improvements non-breaking. CLI commands, HTTP `/v1` routes,
  tool schemas, package root exports, and storage schema changes require a
  follow-up ADR or explicit tech-debt entry before any breaking adjustment.
- Treat apps as runnable surfaces. Shared product/runtime logic should move to
  packages or to documented app-neutral support ports. New app-to-app imports
  are allowed only for thin launchers, compatibility shims, tests, or an
  explicitly registered boundary-debt allowlist entry.
- Split hotspots behavior-preservingly, one hotspot family per branch. A branch
  may move code behind narrower modules, but it must keep public behavior and
  targeted tests stable unless a task card explicitly says otherwise.
- Stabilize runtime and release paths with observable failures, compatibility
  tests, and documented upgrade/provenance policy before changing public
  contracts.
- Use task cards as the assignable unit. Each card must name its write scope,
  validation, dependencies, and handoff; parallel cards must avoid overlapping
  writes unless the integration captain explicitly serializes them.

## Consequences

This slows down sweeping cleanup, but it keeps the route to 100/100 reviewable.
It also gives future agents a stable rule: improve one score dimension or one
hotspot family per branch, validate through repo-native gates, and create a new
ADR before changing public contracts.
