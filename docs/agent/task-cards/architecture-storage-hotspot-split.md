# architecture-storage-hotspot-split Storage Hotspot Decomposition

## Roadmap Track

[Track B: Hotspot Decomposition](../plans/architecture-scorecard-roadmap.md#track-b-hotspot-decomposition)

## Readiness

Ready after the scorecard baseline. This card covers only
`packages/storage/repository_system_methods.py` and the tests needed to preserve
repository behavior.

## Governing ADR

[ADR-0001 Scorecard Refactor Operating Model](../adr/adr-0001-scorecard-refactor-operating-model.md)

## Owner Profile

Storage maintainer comfortable with SQLite repository methods, schema bootstrap,
Personal Model/State records, Episode/Loop/Step rows, learning jobs, and loop
checkpoints.

## Suggested Branch

`vsr/architecture-storage-hotspot-split`

## Suggested Worktree

`architecture-storage-hotspot-split`

## Dependencies

- Read `packages/storage/AGENTS.md`, `packages/contracts/AGENTS.md`, and
  `tests/integration/storage_system_layers/AGENTS.md` if present.
- Do not change `schema.sql` or migration behavior without a separate ADR.

## Write Scope

- Primary: `packages/storage/repository_system_methods.py` and new
  `packages/storage/repository_*_methods.py` modules.
- Tests: `tests/integration/storage_system_layers/**` and focused unit tests.
- Do not mix evidence/runtime, provider adapter, or CLI refactors into this
  branch.

## Deliverables

- Extract one cohesive entity family: PersonalModel/State, Episode/Loop/Step,
  LearningJob, or checkpoints.
- Keep `RuntimeStorageRepository` public methods compatible.
- Preserve schema bootstrap and release package verification behavior.
- Remove the split portion from the hotspot allowlist only when the original
  file falls below the limit.

## Validation

- `make agent-report CHANGED_FILES="packages/storage/... tests/integration/storage_system_layers/..."`
- Targeted storage tests for the extracted family.
- `make test-integration-scenarios`
- `make agent-fast-gate`

## Handoff

Completed 2026-05-24:

- `packages/storage/repository_learning_methods.py` owns learning-job methods.
- `packages/storage/repository_loop_checkpoint_methods.py` owns loop-checkpoint
  serialization, migration, and repository methods.
- `packages/storage/repository_system_methods.py` is now below the Python line
  limit and no longer needs a line-limit allowlist entry.

Remaining extraction is optional until another cohesive repository family
becomes a hotspot. Keep PersonalModel/State and Episode/Loop/Step together
unless their change cadence diverges.

## Guardrails

- Behavior-preserving refactor only.
- No schema or data-loss behavior changes.
- Keep repository method names stable until compatibility tests say otherwise.
