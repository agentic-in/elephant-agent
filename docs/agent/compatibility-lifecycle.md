# Compatibility Lifecycle

Compatibility shims are temporary public-contract surfaces. They preserve
imports, command behavior, or data names while canonical ownership moves into a
package or a narrower app-neutral port.

## Current Policy

- Keep every compatibility surface thin: delegate to the canonical owner and do
  not add new behavior in the shim.
- Add the surface to `tools/agent/public-contracts.yaml` when tests, user
  scripts, or package users still import it directly.
- Keep at least one compatibility regression test or release smoke path linked
  from the public contract inventory.
- Do not remove a compatibility surface in the same change that introduces the
  canonical replacement. Removal needs an ADR or tech-debt entry that states the
  affected import, replacement path, validation command, and migration window.
- Do not add new app-to-app imports to support compatibility. Move shared
  behavior below `packages/`, then preserve the old import as a shim only when
  needed.

## Compatibility Surface Classes

| Class | Example | Canonical Owner | Removal Gate |
| --- | --- | --- | --- |
| Module alias | `apps.cli.wizard` | `packages.operator.wizard` | tests stop patching or importing the old path |
| App facade | `apps.reflect.*` | `packages.reflect.*` | reflect tests and callers use package imports |
| Data alias | `Episode.session_id` | `Episode.episode_id` | public CLI/API callers no longer require the alias |
| Value mapping | `active` episode status | `open` episode status | storage/API compatibility tests no longer cover the legacy value |
| API stub | kernel compaction no-op | CLI/package reflect compression | no callers expect the old hook to exist |

## Required Exit Record

Before removing a compatibility surface, create or update an ADR or tech-debt
entry with:

- canonical replacement path
- caller inventory or search evidence
- validation command that proves removal is safe
- migration or deprecation note when the surface is user-visible

If any of those items cannot be completed, keep the shim and treat it as active
debt in the scorecard roadmap.
