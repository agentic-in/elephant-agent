# architecture-evidence-hotspot-split Evidence Runtime Hotspot Decomposition

## Roadmap Track

[Track B: Hotspot Decomposition](../plans/architecture-scorecard-roadmap.md#track-b-hotspot-decomposition)

## Readiness

Ready after storage split ownership is clear. This card covers only
`packages/evidence/runtime.py` and focused recall/evidence tests.

## Governing ADR

[ADR-0001 Scorecard Refactor Operating Model](../adr/adr-0001-scorecard-refactor-operating-model.md)

## Owner Profile

Evidence maintainer who can reason about lexical ranking, semantic ranking,
Personal Model recall, replay projection, and embedding backfill policy.

## Suggested Branch

`vsr/architecture-evidence-hotspot-split`

## Suggested Worktree

`architecture-evidence-hotspot-split`

## Dependencies

- Read `packages/evidence/AGENTS.md`, `packages/semantic_index/AGENTS.md`, and
  `tests/unit/recall/AGENTS.md`.
- Coordinate with storage work if repository query shapes change.

## Write Scope

- Primary: `packages/evidence/runtime.py` and new
  `packages/evidence/*_runtime.py` or `packages/evidence/*_support.py` modules.
- Tests: `tests/unit/evidence/**`, `tests/unit/recall/**`, and focused
  integration tests when recall behavior is touched.

## Deliverables

- Done: scope resolution, replay projection, and embedding index policy helpers
  are extracted into `packages/evidence/runtime_scope.py`,
  `packages/evidence/runtime_replay.py`, and
  `packages/evidence/runtime_index_policy.py`.
- Remaining: split lexical/semantic ranking from `DefaultEvidenceRetriever`
  only when ranking behavior needs active work.
- Preserve public evidence runtime behavior and ranking thresholds.
- Add regression coverage before changing ranking or cache behavior.

## Validation

- `make agent-report CHANGED_FILES="packages/evidence/... tests/unit/evidence/... tests/unit/recall/..."`
- Targeted evidence/recall tests.
- `make test-integration-scenarios` when runtime behavior changes.
- `make agent-fast-gate`

## Handoff

Remaining runtime concerns are lexical/semantic ranking ownership and candidate
merge readability; no ranking threshold or cache behavior changed in the first
split.

## Guardrails

- No threshold or recall semantics changes hidden inside a split.
- Keep semantic recall cache-first.
- Do not reintroduce per-turn O(N) reindex paths.
