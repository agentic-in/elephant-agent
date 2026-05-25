# Reflect Package

This package owns deterministic signal extraction, review lifecycles, and
feature-composed runner support for background reflection.

## Own Here

- tool-trajectory signal extraction from Episodes, Loops, and Steps
- optimization candidate aggregation and review metadata
- reflect feature registry, feature dependency rules, and tool/SOP contracts
- reflect runner orchestration, progress observation, and result payloads
- context-compression helpers shared by CLI and API surfaces
- evidence packets and prompt fragments for background reflection features
- package-level public exports for reflect helpers

## Do Not Own Here

- app-level compatibility import shims
- durable Personal Model schema changes
- skill package authoring internals beyond approved candidate application
- storage backend implementation details

Keep repository access bounded and filter at the storage layer when the
repository port supports it. Preserve fallback behavior for lightweight test
doubles and future repository adapters.
