# Operator Package

This package owns service and daemon management primitives.

## Own Here

- operator runtime helpers
- procedure projections for local service management
- daemon/service state abstractions
- shared terminal card rendering for app command surfaces
- app-neutral terminal stack, terminal UI, and wizard primitives reused by
  CLI and gateway surfaces

## Do Not Own Here

- user-facing CLI command formatting or command-specific copy
- deploy-specific unit files
- kernel turn execution
- provider credential storage

Keep operator code reusable by CLI, API, and deployment surfaces.
