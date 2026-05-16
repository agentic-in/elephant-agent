# Elephant Agent Entry

This is the short entrypoint for coding agents. The detailed human-readable system of record lives in [docs/agent/README.md](docs/agent/README.md). The executable rule layer lives in [tools/agent/repo-manifest.yaml](tools/agent/repo-manifest.yaml), [tools/agent/task-matrix.yaml](tools/agent/task-matrix.yaml), [tools/agent/skill-registry.yaml](tools/agent/skill-registry.yaml), [tools/agent/context-map.yaml](tools/agent/context-map.yaml), [tools/agent/structure-rules.yaml](tools/agent/structure-rules.yaml), and [tools/make/agent.mk](tools/make/agent.mk).

## Product North Star

Elephant Agent is a Personal-Model-first (PM-first) evolving personal AI agent. Public and technical changes should converge on the canonical Understanding System in [docs/system-design/system-layer-model.md](docs/system-design/system-layer-model.md): Personal Model facts and questions, Elephant State, Episodes, Loops, Steps, semantic recall, and background learning jobs.

## Read First

1. [docs/agent/README.md](docs/agent/README.md)
2. [docs/agent/repo-map.md](docs/agent/repo-map.md)
3. [docs/agent/context-management.md](docs/agent/context-management.md)
4. [docs/agent/change-surfaces.md](docs/agent/change-surfaces.md)
5. `make agent-report CHANGED_FILES="..."`

## Non-Negotiable Rules

- Treat `AGENTS.md` as the entrypoint, `docs/agent/**` as the human-readable system of record, and `tools/agent/**` plus `tools/make/agent.mk` and CI workflows as the executable contract.
- Run `make agent-report CHANGED_FILES="..."` before non-trivial edits so the active change surfaces and validation ladder stay explicit.
- Use Conventional Commits for PR-intended history and sign commits with `git commit -s`.
- Keep commits atomic: one behavior change, one harness surface, or one documentable unit per commit.
- Commit subjects must use a scoped Conventional Commit: `<type>(<scope>): <summary>`.
- When repo-visible changes are complete and the working tree still contains one controlled atomic unit, do not stop at validation only; default to the repo-native ship path so the gate, commit, and push sequence stays uniform: `make agent-ship AGENT_COMMIT_MESSAGE='...'`.
- Only leave changes unshipped when the user explicitly asks to defer publish, the working tree still needs to be split into multiple commits, or a blocking validation failure still needs resolution.
- Use `docs/agent/plans/` for multi-session or multi-agent work instead of leaving the execution graph only in chat.
- If architecture and implementation still diverge after a change, add or update an entry under `docs/agent/tech-debt/`.
- Use dedicated worktrees for parallel agent or contributor work; do not multiplex unrelated changes through one dirty checkout.
- In multi-agent waves, keep one user-facing main session on `main` as the integration captain; worker sessions must stay subordinate, each bound to one worktree, one branch, and one task card.
- When the main session decomposes work for worker lanes, prefer the broadest safe parallel split across ready tracks with disjoint write scopes; do not serialize independent tracks without a dependency or hotspot reason.
- Unless a stronger repo-local rule overrides it, worker lanes must be created with an explicit model pin of `gpt-5.4`; do not leave worker model selection implicit.
- Main-session wave launch does not require a persistent follow-up session. After opening the ready parallel lanes and handing off clear assignment packets, the main session may return and resume review or integration later.
- Add a local `AGENTS.md` before a subdirectory becomes a hotspot with non-obvious rules.

## Canonical Commands

- `make agent-bootstrap`
- `make agent-validate`
- `make agent-scorecard`
- `make agent-report CHANGED_FILES="..."`
- `make agent-context-audit CHANGED_FILES="..."`
- `make agent-lint`
- `make agent-test`
- `make agent-fast-gate`
- `make agent-pr-gate`
- `make agent-ship AGENT_COMMIT_MESSAGE=<type>(<scope>):\ <summary>`
- `make agent-worktree-add WORKTREE_NAME=<name> WORKTREE_BRANCH=<branch>`
- `make agent-worktree-list`
- `make agent-worktree-remove WORKTREE_NAME=<name>`
- `make agent-wave-show WAVE=<wave-id>`
- `make agent-wave-start WAVE=<wave-id>`
- `make agent-wave-status WAVE=<wave-id>`

## Rule Layers

- entry and navigation: [docs/agent/README.md](docs/agent/README.md), [docs/agent/governance.md](docs/agent/governance.md)
- architecture and boundaries: [docs/agent/architecture-guardrails.md](docs/agent/architecture-guardrails.md), [docs/agent/repo-map.md](docs/agent/repo-map.md)
- testing and done criteria: [docs/agent/testing-strategy.md](docs/agent/testing-strategy.md), [docs/agent/feature-complete-checklist.md](docs/agent/feature-complete-checklist.md)
- parallel execution: [docs/agent/worktree-parallelism.md](docs/agent/worktree-parallelism.md)
- release model: [docs/agent/release-model.md](docs/agent/release-model.md)
- executable contract: [tools/agent/repo-manifest.yaml](tools/agent/repo-manifest.yaml), [tools/agent/task-matrix.yaml](tools/agent/task-matrix.yaml), [tools/agent/skill-registry.yaml](tools/agent/skill-registry.yaml), [tools/agent/structure-rules.yaml](tools/agent/structure-rules.yaml)
