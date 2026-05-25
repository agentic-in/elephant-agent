# Architecture And Harness Cleanup Roadmap

## Goal

Keep Elephant Agent clean enough that coding agents can understand the active
architecture from repo-native context, make bounded changes, and validate them
without rediscovering the same structure each session.

## Scope

- runtime package boundaries under `apps/`, `packages/`, and `tests/`
- executable harness routing in `tools/agent/**` and `tools/make/agent.mk`
- generated public-site projections that are validated by repo gates
- docs that describe current package ownership and active cleanup tracks

## Non-Goals

- product architecture redesign outside the canonical Understanding System
- compatibility with removed memory/profile/session storage shapes
- large feature work that should be split into task cards first
- unreviewed formatting churn across unrelated modules

## Current Completed Work

- `packages.reflect` package exports now match `__all__`.
- reflect trajectory loading uses repository-level Episode filtering when
  available and keeps a fallback for narrow test doubles.
- `RuntimeStorageRepository.list_episodes` supports optional
  `personal_model_id`, `status`, `limit`, and `newest_first` filters.
- package-level docs list current modules and local package rules for
  `reflect` and `observability`.
- `agent-report` / `agent-pr-gate` can see dirty and untracked files while a
  base ref is set, so local gates report the real active change surface.
- Python line-limit full scans avoid local generated runtime trees such as
  `.build`, `dist`, and `node_modules`.
- SkillHub generated site content has been resynced to the canonical built-in
  skill catalog.
- Site content generation now has a no-side-effect drift check, and the site
  frontend gate runs it before TypeScript validation.
- Unified recall fallback now uses bounded, state-scoped Step queries backed by
  clean-schema indexes instead of scanning all historical Steps.
- Kernel-facing evidence retrieval and CLI scoped recall now load Step evidence
  by scoped Episode instead of scanning the global Step store on hot paths.
- Episode and State repository queries support `elephant_id` filters, and the
  clean-schema bootstrap idempotently backfills runtime indexes for existing
  v1 databases.
- Reflect dashboard learning rows now lazy-load only Episodes referenced by
  bounded learning jobs instead of scanning all historical Episodes.
- CLI recent-session listing uses repository-level `limit/newest_first`
  Episode queries before falling back to legacy in-memory sorting.
- CLI Elephant-scoped session lookup now uses bounded `elephant_id` and
  `state_id` Episode queries instead of scanning every historical session for
  common `latest_session_for_elephant` and `session_ids_for_elephant` calls.
- State resolution and Elephant identity sync now use bounded `elephant_id` /
  `state_anchor` State queries backed by clean-schema indexes instead of
  scanning every State row in shared CLI/API/gateway paths.
- Duplicate API/CLI State lookup helpers now call the same bounded
  `list_states(elephant_id=...)` / `list_states(personal_model_id=...)`
  repository surface before falling back to older broad test doubles.
- Gateway runtime and command-control state lookups now use the bounded
  Elephant State query for exact Elephant IDs before falling back to broader
  display-name enumeration.
- Loop repository queries now support bounded state/model/status/trigger
  filters, and loop checkpoint supervisor scans use those durable columns
  before applying heartbeat metadata filtering.
- App Episode lifecycle startup now resolves existing Elephant States through
  bounded `elephant_id/status` queries instead of scanning every active State.
- Dashboard routes are lazy-loaded and the Vite production bundle separates
  React, graph, and provider-icon dependencies so release builds avoid the
  previous oversized single JavaScript chunk.
- Dashboard and site favicon/logo PNG assets are sized for their actual UI
  usage instead of shipping 1024px source images into every production build.
- Dashboard diary/reflect internal triggers share one latest-episode resolver
  that uses bounded `limit=1/newest_first` Episode queries before falling back
  to older narrow test doubles.
- Kernel gateway idle reuse now asks storage for newest open Episode
  candidates instead of reversing every Episode in a State, and Episode close
  learning jobs fetch only the latest Loop for the closing Episode.
- Clean-schema and bootstrap index coverage now includes
  `episodes(state_id,status,started_at)` and existing `loops(episode_id,started_at)`
  backfill so lifecycle queries are physically supported.
- API continuity inspection now resolves the latest Episode with bounded
  `state_id/limit=1/newest_first` lookup instead of enumerating every Episode
  in the State.
- Reflect tool-trajectory extraction now loads Step rows once per Episode and
  groups them by Loop, preserving Loop order while avoiding per-Loop Step
  queries when the repository supports `episode_id` Step filtering.
- API dashboard runtime/chat trace builders now load Step rows once per
  Episode and group by Loop, avoiding per-Loop Step queries for recent trace
  projections.

## Tracks

- Track A: Harness Context And Gates
  - Write scope: `tools/agent/**`, `tools/make/agent.mk`,
    `tests/agent/**`, `.github/workflows/**`, `docs/agent/**`.
  - Improve changed-file routing, context-pack precision, gate diagnostics,
    and generated-artifact checks.
  - Validation: `make agent-fast-gate`, then `make agent-pr-gate`.

- Track B: Runtime Package Boundaries
  - Write scope: one package subtree at a time under `packages/**`, plus
    matching tests and local `AGENTS.md`.
  - Reduce cross-package private imports, keep storage/query work bounded,
    and prefer protocol or contract seams over broad app reach-through.
  - Validation: `make agent-fast-gate` plus the package-specific integration
    or scenario target from `make agent-report`.

- Track C: Generated Public Surfaces
  - Write scope: `packages/skills/**`, `apps/site/scripts/**`,
    `apps/site/src/generated/**`, `apps/site/docs/skillhub/**`, and matching
    site pages.
  - Keep generated SkillHub content reproducible and remove stale generated
    pages when catalog entries disappear.
  - Validation: `make web-content-check`, `make web-typecheck`,
    `make web-build`, `make test-integration-scenarios`.

- Track D: Legacy Surface Removal
  - Write scope: one legacy surface at a time, with matching docs/tests.
  - Remove no-op compatibility paths only when tests prove the current clean
    contract, and record any deliberate remaining gap in
    `docs/agent/tech-debt/`.
  - Validation: `make test-integration-scenarios`,
    `make test-release-scenarios`, plus targeted unit tests.

- Track E: Performance, Memory, And Stability
  - Write scope: the owning runtime package plus focused regression tests.
  - Move hot-path filtering and limits into storage/query layers, avoid
    unbounded in-memory scans, and keep background jobs idempotent and bounded.
  - Validation: targeted unit/integration tests first, then
    `make agent-fast-gate`.

## Dependencies

- Architecture must continue to converge on
  `docs/system-design/system-layer-model.md`.
- Each track should run `make agent-report CHANGED_FILES="..."` before edits so
  local context and validation stay explicit.
- Parallel work should use separate worktrees with disjoint write scopes.
- If two tracks overlap, Track A owns harness contract changes before worker
  tracks depend on them.

## Validation

Minimum validation for roadmap-level cleanup:

- `make agent-context-audit CHANGED_FILES="..."`
- `make agent-fast-gate`
- `make agent-pr-gate`
- `make web-content-check`

When touched surfaces require it:

- `make test-integration-scenarios`
- `make test-release-scenarios`
- `make web-typecheck`
- `make web-build`

## Exit Criteria

- `agent-report` gives enough context for the active change without a manual
  repo tour.
- Changed files route to specific surfaces with no audit warnings.
- Public docs and generated site content match canonical package/catalog
  sources.
- Removed legacy paths are either deleted or documented in tech debt with a
  bounded close condition.
- Performance-sensitive background learning and recall code avoids unbounded
  scans when a repository-level filter is available.
- Final diffs can be split into atomic commits with clear validation evidence.
