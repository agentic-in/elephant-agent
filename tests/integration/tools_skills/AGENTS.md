# Tools And Skills Integration Tests

Use this directory for end-to-end coverage of the tool/skill runtime boundary.

Rules:

- exercise the public package APIs, not private helper internals
- cover registry, loader, scope, dependency, and execution wiring together
- keep fixtures JSON-shaped so the loader stays stdlib-only
- do not add app-level process assumptions here
