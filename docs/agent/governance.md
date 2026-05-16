# Governance

## Canonical Layering

The harness has four layers:

1. `AGENTS.md`
   - short entrypoint for coding agents
2. `docs/agent/**`
   - human-readable system of record
3. `tools/agent/**`, `tools/make/agent.mk`, `.github/workflows/**`
   - executable contract and guardrails
4. local `AGENTS.md` files under future hotspot directories
   - narrow supplements for non-obvious subsystems, not competing top-level contracts

Local hook files live under `.githooks/` after `make agent-bootstrap`. They are
generated local state, not a tracked source-of-truth layer.

## Source Of Truth Policy

- repo-native docs and executable rules beat chat summaries
- temporary execution notes are allowed, but only plans, ADRs, debt entries, or docs become durable contract
- if a doc and an executable rule disagree, update the repo so they converge instead of preserving both

## Durable Artifact Choice

Use:

- `docs/agent/plans/` for execution graphs
- `docs/agent/adr/` for stable structural decisions
- `docs/agent/task-cards/` for directly assignable execution units
- `docs/agent/tech-debt/` for admitted gaps
- `CHANGELOG.md` for released or release-worthy change summaries

Atomic publish flow for controlled changes:

- `make agent-ship AGENT_COMMIT_MESSAGE='...'`

Do not leave durable repo policy only in PR text, review threads, or chat.

## Main-Session Rule

When several agents are active, user-facing orchestration stays in one main
session on `main`.

- the main session owns wave launch, safe parallel track decomposition, branch
  review, cherry-pick integration, and `main` pushes
- worker sessions own only their assigned worktree branches
- the user should not need to repeat coordination instructions across worker
  sessions when the main session already holds the plan and task-card context
