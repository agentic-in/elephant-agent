---
title: "CLI reference"
description: "The public CLI stays intentionally direct while still exposing skills, gateway, and the local dashboard inspection surface."
---

# CLI reference

## Core commands

| Command | What it does |
| --- | --- |
| `elephant` | Shows the branded landing and next-step guidance. |
| `elephant init` | Runs first-use onboarding, provider setup, creates the first elephant, and surfaces the Feishu IM handoff before `wake` opens. |
| `elephant status` | Checks whether the active local install is ready. |
| `elephant provider` | Configures or inspects the active provider, dialogue model, reasoning effort, context window, and embedding readiness. |
| `elephant provider embeddings status` | Shows the active embedding provider selection, including local-default fallback versus a configured OpenAI-compatible override. |
| `elephant provider embeddings local` | Switches semantic retrieval back to the local Elephant Agent embedding default. |
| `elephant provider embeddings openai-compatible --base-url <url> --model <id> --dimensions <n>` | Persists one active OpenAI-compatible embedding override with an encrypted local API key. |
| `elephant herd new [name]` | Creates a named Elephant Agent elephant, prompting only for any missing name. |
| `elephant herd` | Lists known herd. |
| `elephant herd current` | Shows which elephant `wake` will reopen by default. |
| `elephant herd use <name>` | Selects one elephant as the current `wake` target. |
| `elephant herd delete <name>` | Deletes one elephant. |
| `elephant herd delete --all` | Deletes every elephant. |
| `elephant wake` | Opens the main conversational surface. |
| `elephant wake --elephant-id <name>` | Opens one specific elephant directly. |
| `elephant wake --message "..."` | Runs a single turn without staying in the TUI. |
| `elephant skills` | Lists the visible skill catalog outside `wake`, with subcommands for `active`, `search`, `view`, `enable`, `disable`, and `install`. |
| `elephant gateway setup` | Opens IM setup and writes the selected adapter's wiring. Elephant routing is bound later with `/elephant create <name>` from the messaging surface. |
| `elephant gateway doctor` | Runs whole-surface readiness checks across configured IM providers and accounts. |
| `elephant gateway describe` | Prints the resolved IM provider and account wiring as JSON. |
| `elephant gateway feishu start --transport long-connection --detach` | Starts the Feishu long-connection bridge in the background and returns immediately. |
| `elephant gateway feishu status` | Shows the Feishu runtime status, account posture, PID activity, and runtime record paths. |
| `elephant gateway feishu stop --force` | Gracefully stops the configured Feishu runtime, with `--force` available when needed. |
| `elephant gateway feishu restart` | Restarts the configured Feishu runtime in the background. |
| `elephant gateway feishu logs ops-feishu --follow` | Tails one Feishu account log and keeps streaming new output. |
| `elephant gateway discord setup --account-id ops-discord --bot-token-env-var ELEPHANT_DISCORD_BOT_TOKEN` | Adds or updates one Discord account configuration. |
| `elephant daemon start` | Starts the unified local daemon that serves IM adapters, cron, learning, and the dashboard HTTP surface. |
| `elephant dashboard` | Opens the daemon-served dashboard when frontend assets are built and the local daemon is running. |
| `elephant upgrade` | Backs up state, stops managed gateway/cron runtimes, upgrades the package, bootstraps storage, and restarts prior runtimes. |

## Installers

| Command | When to use it |
| --- | --- |
| `curl -fsSL https://elephant.agentic-in.ai/install.sh | bash` | Public install on macOS/Linux using the latest published dev package. |
| `curl -fsSL https://elephant.agentic-in.ai/install.sh | bash -s -- --channel stable` | Public install pinned to the latest stable package. |
| `elephant upgrade --channel stable` | Graceful in-place upgrade to the stable package stream. |
| `bash scripts/install.sh` | Repo-local install from a checkout. |
| `bash scripts/install.sh upgrade` | Rewrites the checkout-bound launcher. |
| `bash scripts/install.sh health` | Runs health through the checkout-bound launcher. |

## In-session control surfaces

Inside `wake`, these slash commands stay available without leaving the
conversation:

- `/status`
- `/recall`
- `/tools`
- `/skills`
- `/gateway`
- `/cron`
- `/providers`
- `/models`
- `/clear`
- `/exit`

`/skills` now fronts discoverable skill packages inside the conversation, and
matching skill packages also register dynamic slash commands such as
`/apple-notes ...`. Outside `wake`, `elephant skills` mirrors the same skill
inventory and install surface without opening the shell first.

Inside `wake`, `/recall` inspects understanding and recall, while the local
Dashboard is the place to inspect Personal Model claims, provenance, questions,
and corrections in one view.
`/providers` and `/models` keep provider
posture, dialogue model choice, and embedding readiness close at hand.

Embedding management stays under `/providers`, for example:
`/providers embeddings status`,
`/providers embeddings local`, and
`/providers embeddings openai-compatible <base_url> <model_id> <dimensions> [api_key]`.

The built-in runtime already exposes this curated tool catalog:
<!-- BEGIN:GENERATED_BUILTIN_TOOL_SUMMARY -->
- `terminal`: `tool.terminal.exec`
- `process`: `tool.process.manage`
- `file`: `tool.file.read`, `tool.file.write`, `tool.file.patch`, `tool.file.search`
- `web`: `tool.web.search`, `tool.web.read`, `tool.web.extract`
- `browser`: `tool.browser.navigate`, `tool.browser.snapshot`, `tool.browser.click`, `tool.browser.type`, `tool.browser.scroll`, `tool.browser.back`, `tool.browser.press`, `tool.browser.images`, `tool.browser.vision`, `tool.browser.console`
- `clarify`: `tool.clarify`
- `cron`: `tool.cron.manage`
- `code_execution`: `tool.code.execute`
- `personal_model`: `tool.personal_model.search`, `tool.personal_model.update`, `tool.personal_model.questions`
- `messaging`: `tool.message.send`
- `todo`: `tool.todo.manage`
- `skills`: `tool.skill.list`, `tool.skill.view`, `tool.skill.manage`
- `sub_agents`: `tool.sub_agents`
<!-- END:GENERATED_BUILTIN_TOOL_SUMMARY -->

The wider extension surface still includes built-in skills, authored skills,
and recurring cron jobs on top of the built-in tools. The `personal_model`
family is the durable understanding surface: search returns active claims with
match status, update changes one lens/topic claim, and questions manage useful
future prompts.

## Local dashboard

`elephant dashboard` is the private local web surface. It reads live
`elephant.sqlite3` state through page-specific internal dashboard routes such as
`/v1/internal/dashboard/overview`, `/v1/internal/dashboard/runtime`, and
`/v1/internal/dashboard/tools`, then launches the React app under `apps/dashboard/`
when the current install includes those frontend assets.

That means:

- PyPI installs launch from the prebuilt dashboard assets shipped in the wheel,
  without requiring Node.js or npm at runtime
- repo checkouts can launch it directly after installing dashboard dependencies
- `elephant dashboard` runs one frontend build check before launch so the checkout
  is current; use `--skip-build` only when you are iterating and already know
  the frontend compiles
- `elephant dashboard` starts a fresh local API by default and shifts to the next
  free API/UI port when older dashboard processes are still running; use
  `--reuse-api` when you intentionally want to attach to an existing healthy API
- `elephant dashboard` opens the default browser automatically; use `--no-open`
  when you only want the URL printed in the terminal
- frontend-only dashboard launches with `npm --prefix apps/dashboard run dev`
  auto-start or reuse the local Elephant Agent API against `~/.elephant/herd/elephant.sqlite3`
  unless `VITE_ELEPHANT_API_BASE_URL` or `ELEPHANT_DASHBOARD_API_DATABASE` is set
  explicitly
- installs that do not include `apps/dashboard` assets stay truthful by printing
  launch guidance instead of pretending the web surface exists

## Runtime paths

By default, Elephant Agent uses:

- `ELEPHANT_HOME=$HOME/.elephant`
- `ELEPHANT_HERD_DIR=$ELEPHANT_HOME/herd`
- `ELEPHANT_CRON_DIR=$ELEPHANT_HOME/cron`
- `ELEPHANT_PAIRING_DIR=$ELEPHANT_HOME/pairing`
- `ELEPHANT_SKILLS_DIR=$ELEPHANT_HOME/skills`
- `ELEPHANT_BUILTIN_SKILLS_DIR=$ELEPHANT_SKILLS_DIR/builtin`
- `ELEPHANT_INSTALLED_SKILLS_DIR=$ELEPHANT_SKILLS_DIR/installed`
- `ELEPHANT_AUTHORED_SKILLS_DIR=$ELEPHANT_SKILLS_DIR/authored`

The messaging gateway shares `ELEPHANT_HERD_DIR`, so CLI and gateway state live in
one runtime database.
