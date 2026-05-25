# architecture-release-upgrade Release Upgrade And Artifact Integrity

## Roadmap Track

[Track D: Release, Upgrade, And Artifact Integrity](../plans/architecture-scorecard-roadmap.md#track-d-release-upgrade-and-artifact-integrity)

## Readiness

In progress. The release model now documents clean-reset versus migration
boundaries, public-contract release-note triggers, package verification
invariants, macOS signing posture, and Python artifact provenance. Public
storage migration behavior or stronger signing/attestation changes still need
follow-up implementation behind the existing ADR boundary.

## Governing ADR

[ADR-0001 Scorecard Refactor Operating Model](../adr/adr-0001-scorecard-refactor-operating-model.md)

## Owner Profile

Release maintainer who can inspect CI, package verification, install paths,
storage reset posture, and changelog expectations together.

## Suggested Branch

`vsr/architecture-release-upgrade`

## Suggested Worktree

`architecture-release-upgrade`

## Dependencies

- Read `docs/agent/release-model.md`, `deploy/AGENTS.md`, and release workflow
  files before changing release behavior.
- Inspect package verification before changing packaging contents.

## Write Scope

- Primary: `docs/agent/release-model.md`, `CHANGELOG.md`, release docs, package
  verification docs/tests, `.github/workflows/**`, `install.sh`, or release
  tests.
- Do not change storage schema or migration behavior in this card without a new
  ADR.

## Deliverables

- Done: document clean-reset versus migration boundaries and when real
  migrations are required.
- Done: define release note/changelog expectations for public API, storage, CLI,
  and package export changes.
- Done: preserve package verification expectations for generated-artifact leaks.
- Done: add release-contract coverage that fails if the release model loses the
  upgrade, release-note, artifact-integrity, macOS-signing, or provenance
  policy sections.
- Done: add ADR-0002 and a release provenance generator so package
  verification writes `dist/elephant-agent-provenance.json` and
  `dist/SHA256SUMS`; publish workflows upload only wheel/sdist to PyPI and
  attach the provenance files to GitHub releases.

## Validation

- `make agent-report CHANGED_FILES="docs/agent/release-model.md .github/... install.sh tests/e2e/release/..."`
- `make package-verify` when packaging checks change.
- `make release` or a documented narrower release dry-run when release behavior
  changes.
- `make agent-fast-gate`

## Handoff

Remaining stronger signing/attestation work should extend ADR-0002 before
changing publish workflows again.

## Guardrails

- No silent broadening of packaged artifacts.
- No undocumented storage reset or migration behavior.
- Keep release policy and executable checks aligned.
