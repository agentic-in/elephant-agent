# Apps

Runnable product and operator surfaces live here.

Current surfaces:

- `cli/`
  - primary user-facing runtime surface
- `api/`
  - programmatic and remote orchestration surface
- `gateway/`
  - messaging ingress and delivery process
- `dashboard/`
  - operator web UI for state, provider, trace, and Personal Model inspection
- `site/`
  - public website, docs, and release-facing web surface
- `macos/`
  - native desktop shell and platform packaging
- `reflect/`
  - compatibility import facade for the package-owned Reflect runner and
    feature composition
- `learning_agents/`
  - backward-compatible background learning worker shim

Top-level app support modules such as `apps/daemon.py`,
`apps/daemon_tasks.py`, `apps/cron_scheduler_command.py`, `apps/launcher.py`,
`apps/learning_worker_runtime.py`, `apps/cli_runtime_bridge.py`,
`apps/provider_runtime.py`, and
`apps/runtime_layout.py` exist to wire process entrypoints, scheduling loops,
worker lifecycles, and shared app lifecycle. When that shared behavior becomes
product logic instead of app plumbing, move it into `packages/`.

Working rules:

- app code should compose packages; it should not become the source of truth for core cognition
- keep transport, rendering, and process lifecycle here
- move reusable logic down into `packages/` before it becomes shared across apps
- add or update a local `AGENTS.md` when an app surface gains non-obvious invariants
