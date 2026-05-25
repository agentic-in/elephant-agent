# ADR-0002 Release Artifact Provenance

Status: Proposed

## Context

Release certification already checks package contents, install surfaces, macOS
signing posture, and live-provider smoke paths. The remaining ambiguity is how
official artifacts prove where they came from before the project adopts a
broader SBOM and external transparency-log verification stack.

The active roadmap is
[architecture-scorecard-roadmap.md](../plans/architecture-scorecard-roadmap.md),
with the release track in
[architecture-release-upgrade.md](../task-cards/architecture-release-upgrade.md).

## Decision

- Official Python package artifacts must be produced by the release workflow or
  by a maintainer-run command whose commit SHA, version, build command, and
  validation output are recorded in the release note.
- Python release artifacts must pass `twine check`, install-surface
  verification, and checksum generation before publication. The release note
  must include the commit SHA, workflow or command source, package version, and
  checksum location.
- The PyPI publish workflow must generate a GitHub artifact attestation for the
  Python release artifacts with `actions/attest@v4` and
  `subject-checksums: dist/SHA256SUMS`. The workflow must keep `id-token`,
  `attestations`, and `artifact-metadata` write permissions explicit because
  they are part of the provenance boundary.
- Official macOS latest artifacts must declare their signing mode. Developer ID
  notarization is the default general-user path; ad-hoc signed artifacts are
  limited to CI, explicit workflow-dispatch testing, or emergency maintainer
  builds that clearly state the Gatekeeper tradeoff.
- Local ad-hoc artifacts are not official releases unless the release note
  explicitly records the local build provenance and why workflow publication was
  bypassed.
- Future SBOM, external transparency-log, or repository-attestation work should
  extend this ADR instead of changing publish workflows silently.

## Consequences

This makes provenance release-blocking at the documentation and certification
level and adds a GitHub/Sigstore-backed attestation to the publish workflow. It
also keeps the upgrade path open: SBOM and transparency-log verification can be
added without changing the current public CLI, HTTP, tool, package, or storage
contracts.
