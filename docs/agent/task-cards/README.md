# Task Cards

Use this directory for directly assignable implementation units linked to an
active roadmap or execution plan.

## How To Use This Directory

1. choose a ready track from an active plan under [../plans/](../plans/README.md)
2. read the governing ADR for the track when one exists
3. assign the matching task cards to disjoint worktrees and branches when the
   write scopes safely allow parallelism
4. ship each branch through the repo-native validation and commit path
5. integrate one completed card at a time into `main`

## Active Architecture Scorecard Cards

- [API And App Boundary Stabilization](architecture-api-app-boundary.md)
- [CLI Hotspot Decomposition](architecture-cli-hotspot-split.md)
- [Storage Hotspot Decomposition](architecture-storage-hotspot-split.md)
- [Evidence Runtime Hotspot Decomposition](architecture-evidence-hotspot-split.md)
- [Provider Adapter Hotspot Decomposition](architecture-provider-hotspot-split.md)
- [Gateway E2E Suite Decomposition](architecture-gateway-e2e-split.md)
- [Runtime Performance And Stability](architecture-runtime-stability.md)
- [Release Upgrade And Artifact Integrity](architecture-release-upgrade.md)
- [Frontend Desktop And Gateway Coverage](architecture-surface-coverage.md)
