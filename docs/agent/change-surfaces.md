# Change Surfaces

`make agent-report` routes work through a small set of named surfaces.

## `repo-docs`

Use for:

- `README.md`
- `CONTRIBUTING.md`
- `CHANGELOG.md`
- `docs/README.md`
- system-design docs under `docs/system-design/**`
- paper sources and compiled paper artifacts under `docs/paper/**`

Default validation:

- `make agent-validate`

## `agent-text`

Use for:

- `AGENTS.md`
- `docs/agent/**`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.github/ISSUE_TEMPLATE/**`
- `.github/copilot-instructions.md`

Default validation:

- `make agent-validate`
- `make agent-test`

## `agent-exec`

Use for:

- `tools/agent/**`
- `tools/make/agent.mk`
- `.claude/**` cleanup or ignore-policy changes
- `.githooks/**` cleanup or local hook bootstrap changes

Default validation:

- `make agent-fast-gate`

## `release-ops`

Use for:

- `.github/workflows/**`
- `install.sh`
- release-facing templates and automation
- `.github/*.md`

Default validation:

- `make agent-validate`
- `make agent-test`

## `app-scaffold`

Use for:

- `apps/**`
- `packages/**`
- `tests/**`
- `deploy/**`
- `netlify.toml`
- `pyproject.toml`
- `scripts/install.sh`

Default validation:

- `make agent-fast-gate`

When product runtime surfaces exist, this surface should gain more specific local `AGENTS.md` files and feature gates.
