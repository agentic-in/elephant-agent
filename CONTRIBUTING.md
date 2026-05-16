# Contributing

## Start Order

1. read [AGENTS.md](AGENTS.md)
2. read [docs/agent/README.md](docs/agent/README.md)
3. run `make agent-report CHANGED_FILES="..."`
4. run the smallest relevant gate before asking for review

## Commit Contract

PR-intended commits must follow this format:

```text
<type>(<scope>): <summary>
```

Examples:

- `feat(runtime): add task scheduler skeleton`
- `docs(agent): add release model`
- `chore(harness): tighten worktree guardrails`

Rules:

- allowed types: `build`, `chore`, `ci`, `docs`, `feat`, `fix`, `perf`, `refactor`, `revert`, `test`
- scope is required
- keep the subject line to 72 characters or fewer
- do not end the subject with a period
- use one atomic change per commit
- sign PR-intended commits with `git commit -s`

Preferred scopes while the runtime is still settling:

- `agent`
- `architecture`
- `context`
- `docs`
- `harness`
- `memory`
- `planning`
- `release`
- `runtime`
- `session`
- `tests`
- `tools`

Local enforcement is installed by:

```bash
make agent-bootstrap
```

## Branch and Worktree Model

- one task or subtask per worktree
- one branch per worktree
- avoid overlapping write scopes between concurrent agents
- prefer branch names that explain intent:
  - `feat/<topic>`
  - `fix/<topic>`
  - `docs/<topic>`
  - `chore/<topic>`
  - `exp/<topic>`

Canonical commands:

```bash
make agent-worktree-add WORKTREE_NAME=harness-docs WORKTREE_BRANCH=docs/harness-docs
make agent-worktree-list
make agent-worktree-remove WORKTREE_NAME=harness-docs
make agent-wave-show WAVE=wave-0
make agent-wave-start WAVE=wave-0
make agent-wave-status WAVE=wave-0
```

The first commit on `main` must exist before worktrees can be created.

## Main-Session Orchestration

For parallel implementation waves, the repo defaults to one user-facing main
session on `main`.

That main session should:

1. choose the largest ready subset of task cards that can move in parallel without overlapping write scopes
2. create one worktree per card
3. assign one worker session per worktree, explicitly pinning the worker model to `gpt-5.4`
4. hand off assignment packets that make the write scope, validation command, and ship path explicit
5. return once those assignments are clear, or continue directly into review and integration if a finished branch is already waiting
6. review finished worker branches when resuming the main checkout
7. cherry-pick approved atomic commits into `main`
8. push `main`, clean up completed lanes, and open the next ready tracks

Worker sessions should:

- stay inside one task-card write scope
- run the repo gate in their own worktree
- ship their own branch to `origin`
- never integrate directly into `main`

## Validation Ladder

Run the smallest gate that proves the current change:

1. `make agent-validate`
2. `make agent-context-audit CHANGED_FILES="..."`
3. `make agent-lint`
4. `make agent-test`
5. `make agent-fast-gate`
6. `make agent-pr-gate`
7. `make agent-ship AGENT_COMMIT_MESSAGE='...'`

## Controlled Auto-Ship

When the current change is truly one atomic capability and the working tree only contains that scope, this is the default closeout path for both worker branches and standalone main-session changes:

```bash
make agent-ship AGENT_COMMIT_MESSAGE='docs(system-design): import provisional design baseline'
```

`agent-ship` will:

1. inspect the current working tree
2. run the repo PR gate against the active diff
3. stage all current changes
4. create a signed commit with the supplied scoped Conventional Commit subject
5. push the current branch to `origin`

Do not stop at `agent-validate`, `agent-test`, or `agent-pr-gate` alone when the
change is complete and publishable. For repo-visible completed work, close out
with `agent-ship` unless one of the exceptions below applies.

Do not use `agent-ship` when:

- the working tree contains multiple unrelated changes
- you still need to split the diff into more than one commit
- you are not ready for the branch to be published

## Long-Horizon Work

Use `docs/agent/plans/` when:

- the task spans multiple sessions
- several agents need disjoint ownership
- the dependency order matters
- the repo needs a durable execution graph that should survive chat history
- the main session needs to maximize safe parallelism without losing track ownership

Use `docs/agent/adr/` when:

- a decision changes stable repo structure, not just one execution step

Use `docs/agent/tech-debt/` when:

- a deliberate gap remains after shipping

## Pull Request Interface

Every PR should state:

- what changed
- why it changed now
- affected surfaces
- validation run
- open follow-ups or debt, if any

Use the PR template and keep the scope small enough that the reviewer can reason about the change without reconstructing hidden context.
