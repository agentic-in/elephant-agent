# Release Model

## Current Posture

The repo now has staged release automation around the current runtime surface:

1. `make build-and-test` powers the default push/PR CI contract in `.github/workflows/ci.yml`
2. `make agent-lint` powers the lightweight harness lint contract in `.github/workflows/agent-lint.yml`
3. `make e2e` remains the local deterministic e2e matrix for explicit release
   or regression checks, including the installed CLI + daemon dashboard user
   journey
4. `make release` powers deterministic release certification when run by maintainers
5. `make design-closure` preserves the stronger operator-managed design-closure certification path
6. `make test-live-provider-smoke` is the optional secret-backed installed
   command smoke for release/design-closure workflow dispatches
7. `.github/workflows/pypi-publish.yml` is the publish path for packaged Python artifacts and release assets

## What Counts As Release-Ready Today

- build-and-test is green on the candidate diff
- deterministic e2e has been run when the candidate touches app, deploy, gateway, or release behavior
- release certification is green for publish candidates
- packaged artifacts build cleanly and pass install-surface verification
- the manual live-provider smoke has been run when certifying a configured
  operator provider or installed-command regression
- changelog and user-facing install paths remain understandable
- any remaining gap is recorded in `docs/agent/tech-debt/`

## Storage Upgrade Policy

The current storage posture is a clean-schema reset model, not a general
migration system:

- `packages/storage/schema.sql` is the shipped schema source of truth.
- `packages/storage/repository_support.py` owns the active `SCHEMA_VERSION`.
- Bootstrap may drop legacy reset-era tables and may reset same-version schema
  drift when the database advertises the current clean schema version but no
  longer matches the clean schema contract.
- Bootstrap must reject newer schema versions instead of guessing a downgrade.
- `packages/storage/migrations/` must not ship in the wheel unless a future ADR
  deliberately introduces a supported migration system.

A real migration is required before changing release behavior when a release
must preserve user data across an incompatible `schema.sql` or
`SCHEMA_VERSION` change. That migration decision must land as an ADR or a
tech-debt entry with compatibility tests before the schema change ships.

## Release Notes And Changelog Policy

Release candidates need a user-facing note when they change any of these public
contracts:

- CLI commands, flags, config paths, or installed `elephant` behavior.
- HTTP `/v1` routes, payloads, status codes, or streaming behavior.
- Tool schemas, capability protocols, package root exports, or storage schema.
- Install, PyPI, macOS, daemon, gateway, dashboard, or site delivery paths.

The note should state the affected surface, compatibility impact, validation
run, and rollback or reset guidance when applicable. Breaking changes require a
prior ADR or explicit tech-debt entry, plus compatibility or migration tests.

## Artifact Integrity Policy

Python package verification must keep proving:

- generated web dependencies such as `node_modules` do not leak into wheels
- `packages/storage/schema.sql` is present
- legacy storage migrations do not leak into wheels
- built dashboard assets are present when the wheel is produced
- `twine check` and installed-surface verification pass
- `dist/elephant-agent-provenance.json` and `dist/SHA256SUMS` are generated
  for Python package artifacts
- the PyPI publish workflow generates a GitHub artifact attestation with
  `actions/attest@v4` using `dist/SHA256SUMS` as the subject checksum file

macOS latest-release artifacts must state whether they are Developer ID
notarized or ad-hoc signed. Ad-hoc signed artifacts are acceptable for CI or
explicit workflow-dispatch testing, but not as the smooth general-user release
path.

Artifact signing and provenance for Python release assets is governed by
[ADR-0002 Release Artifact Provenance](adr/adr-0002-release-artifact-provenance.md).
Official release notes must record the commit SHA, workflow or command source,
package version, validation output, checksum location, and GitHub attestation
source for published Python artifacts.

## Future Extension Points

- prerelease channels for unstable runtime surfaces
- automated changelog or release-note generation
- SBOM attestations or external transparency-log verification once publish
  targets are fully locked
