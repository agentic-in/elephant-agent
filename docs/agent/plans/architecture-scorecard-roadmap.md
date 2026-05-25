# Full-System Architecture Scorecard Roadmap

## Goal

Establish a durable, repo-native architecture scorecard for Elephant Agent and
turn it into an optimization roadmap that can move the whole system toward
100/100 quality without relying on chat history.

This plan is the evaluation and prioritization entrypoint. The existing
[Architecture And Harness Cleanup Roadmap](architecture-harness-cleanup.md)
remains the active execution roadmap for architecture and harness cleanup
tracks. When this scorecard identifies a concrete cleanup item that already
belongs to that roadmap, update the cleanup roadmap instead of creating a
competing execution plan.

## Scope

- Product apps: `apps/cli`, `apps/api`, `apps/gateway`, `apps/dashboard`,
  `apps/site`, `apps/macos`, `apps/reflect`, and compatibility shims.
- Runtime packages: all `packages/**`, including contracts, kernel, state,
  evidence, context, semantic index, storage, models, tools, skills, gateway,
  security, observability, and learning packages.
- Validation and delivery: `tests/**`, `deploy/**`, `.github/**`, `Makefile`,
  `pyproject.toml`, install, packaging, and release workflows.
- Agent harness: `AGENTS.md`, `docs/agent/**`, `tools/agent/**`, and
  `tools/make/agent.mk`.
- Generated/build artifacts are not scored as source, but release packaging
  must keep proving they do not leak inappropriate content into shipped
  artifacts.

## Non-Goals

- Do not redesign the product outside the canonical Understanding System in
  `docs/system-design/system-layer-model.md`.
- Do not introduce breaking CLI, HTTP `/v1`, package export, or storage-schema
  changes in the first scorecard pass.
- Do not combine unrelated hotspot refactors in one PR. Each implementation
  pass should own one score dimension or one hotspot family.
- Do not replace targeted validation with broad formatting churn.

## Baseline Facts

Last baseline inspection: 2026-05-24.

- `make agent-validate` passed with `Checks: 220`, `Errors: 0`.
- `make agent-lint` passed with `Status: ok`.
- `make agent-scorecard` reported 3 read-first entries, 21 required paths,
  14 skills, 14 task surfaces, and 24 context-map surfaces.
- Representative `make agent-report` for this scorecard route resolved
  `docs/agent/plans/architecture-scorecard-roadmap.md` to `agent-text` with
  validation `make agent-test` and `make agent-validate`.
- The repo has a strong intended architecture: apps compose packages,
  packages integrate through contracts and capabilities, and product design
  converges on the Personal-Model-first Understanding System.
- No tracked non-generated source Python file is currently above the
  1000-line ceiling. The largest tracked source file is
  `packages/operator/wizard.py` at the 1000-line ceiling; several runtime and
  gateway modules remain just below it.
- App-to-app imports are concentrated around gateway and shared app support:
  gateway cron/control modules still import `apps.cli.runtime`; API and cron
  command paths still cross into gateway runtime/cron support; API and CLI
  still share `apps.provider_runtime`.
- Storage has a clean schema and bootstrap guardrails, but current upgrade
  posture intentionally auto-drops legacy tables and resets same-version schema
  drift instead of maintaining general migrations.
- The agent harness is materially stronger than average: changed-file routing,
  local `AGENTS.md` discovery, task matrix, context map, validation ladder,
  worktree/wave commands, line-limit scanning, and release gates are all
  executable.

## Current Progress

Completed P0 alignment on 2026-05-24:

- Created this full-system scorecard entrypoint and linked it from
  `docs/agent/plans/README.md`.
- Updated `docs/system-design/system-layer-model.md` so
  `tool.personal_model.search` exposes the current public modes,
  `auto` and `inventory`; stricter lookup now routes through `ref`, `topic`,
  `status`, and diagnostics instead of obsolete public modes.
- Updated `apps/README.md` to list current app surfaces, including dashboard,
  macOS, reflect, and the learning-agent shim.
- Updated `docs/agent/repo-map.md` so the known-hotspot inventory reflects the
  current largest e2e, CLI, API, gateway, storage, evidence, and provider files.
- Marked the completed Understanding legacy cleanup debt as closed in
  `docs/agent/tech-debt/`.
- Added ADR-0001 and directly assignable task cards for the remaining
  architecture scorecard tracks so follow-up branches can move toward 100/100
  without overlapping write scopes.
- Added `apps/README.md` to the context-map and task-matrix app-scaffold
  routing so the harness no longer reports it as an uncovered surface.
- Extended the release model with storage reset versus migration policy,
  release-note triggers, package verification invariants, macOS signing posture,
  and provenance ADR boundaries.
- Added release-contract coverage so the release model's upgrade and artifact
  policy cannot silently drift out of the release certification suite.
- Added an executable app-to-app import boundary guard: the current coupling is
  explicitly allowlisted, and new production app cross-imports fail validation
  unless moved below `packages/` or registered as debt.
- Split the hotspot roadmap into branch-sized task cards for CLI, storage,
  evidence, provider adapter, and gateway e2e decomposition.
- Added a tool-schema regression so the system design cannot drift back to the
  obsolete `exact` / `semantic` / `verify` Personal Model search modes.
- Made Episode close side-effect failures observable by logging failed summary
  indexing and learning enqueue attempts, with focused regression coverage.
- Extended `make agent-scorecard` to report line-limit and app-boundary
  allowlist debt counts, making two 100/100 blockers visible in the harness.
- Removed one app-boundary debt item by making `apps.learning_agents` a pure
  compatibility shim over `apps.learning_worker_runtime`; app import boundary
  allowlist debt is now 60.
- Made kernel lifecycle step and exit-summary indexing failures observable with
  warning logs and regression coverage.
- Removed the duplicate legacy `/skills` shell command implementation from
  `apps/cli/shell_methods_commands.py`; that file is now below the line limit
  and line-limit allowlist debt is now 9.
- Removed stale line-limit allowlist debt for the deleted
  `packages/learning/personal_model_evolution.py`; line-limit allowlist debt is
  now 8.
- Split prompt history/style support out of `apps/cli/shell_composer.py` into
  `apps/cli/shell_composer_support.py`; `shell_composer.py` is now 954 lines
  and line-limit allowlist debt is now 7.
- Split response parsing, streaming, usage, embedding extraction, and tool-call
  compatibility out of `packages/models/providers/openai_compatible.py`; that
  provider adapter is now 759 lines and line-limit allowlist debt is now 6.
- Split skill hub, authored skill, growth inspection, and skill-source install
  methods out of `apps/cli/runtime_extensions_surface.py`; that runtime surface
  is now 793 lines and line-limit allowlist debt is now 5.
- Restored the additive `CliRuntime.create(profile_dir=...)` compatibility hook
  covered by `tests/unit/cli/test_runtime_extensions.py`.
- Split gateway argparse construction out of
  `apps/gateway/gateway_main_impl.py` into
  `apps/gateway/gateway_main_argparse.py`; `gateway_main_impl.py` is now 923
  lines, and line-limit allowlist debt is now 4.
- Fixed gateway setup auto-start to use the managed restart path with an
  injected service, matching the detached runtime contract covered by
  `tests/unit/gateway/test_main.py`.
- Split evidence retrieval scope helpers, Step replay projection, and embedding
  index policy helpers out of `packages/evidence/runtime.py`; that runtime file
  is now 970 lines, and line-limit allowlist debt is now 3.
- Split learning-job and loop-checkpoint repository method families out of
  `packages/storage/repository_system_methods.py`; the canonical system-method
  file is now 907 lines, the new focused modules are 447 and 501 lines, and
  line-limit allowlist debt is now 2.
- Split shared console config helpers and gateway operator helpers out of
  `apps/api/api_runtime_console_ops.py`; the console ops file is now 820
  lines, the gateway helper module is 954 lines, and line-limit allowlist debt
  is now 1.
- Split `apps/cli/cli_main_impl.py` by init prompt, init runtime/bootstrap,
  provider/herd command, and facts/reflect/wake command families; the CLI main
  file is now 759 lines and line-limit allowlist debt is now 0.
- Added route-status compatibility in the kernel so legacy `active` route status
  maps to the canonical open Episode contract instead of failing off-path
  learning runs.
- Moved shared Typer command execution from the CLI app into
  `packages.operator.typer_support`, with a CLI compatibility re-export; app
  import boundary allowlist debt is now 56.
- Removed the stale API console `apps.gateway` boundary allowlist entry after
  gateway operator helpers moved into their own module; app import boundary
  allowlist debt is now 55.
- Moved shared terminal stack, terminal UI, and wizard primitives from
  `apps.cli` into `packages.operator`, preserving the old CLI import paths as
  module aliases so existing monkeypatch-based compatibility tests still patch
  the owning module; gateway setup/runtime modules now consume these package
  ports directly, and app import boundary allowlist debt is now 39.
- Removed stale gateway `apps.cli.runtime` imports left behind by previous file
  splits and moved the gateway wizard banner mark to the package-level terminal
  UI port; app import boundary allowlist debt is now 31.
- Moved proactive ask tick evaluation and configured IM adapter inventory into
  `packages.gateway_core`, preserving `apps.gateway.proactive_ask_job` as a
  compatibility module alias; API and daemon cron paths now use the package
  port, and app import boundary allowlist debt is now 28.
- Moved the Reflect feature registry and feature contract fragments into
  `packages.reflect.features`, preserving `apps.reflect.features` as a
  compatibility module alias; API learning job summaries now resolve features
  through the package port, and app import boundary allowlist debt is now 26.
- Made the executable app-boundary guard match the documented exit criteria by
  excluding documented top-level composition/support sources
  (`apps/daemon.py`, `apps/daemon_http.py`, `apps/dashboard_static_server.py`,
  and `apps/launcher.py`) from debt accounting, with regression coverage; app
  import boundary allowlist debt is now 18.
- Moved shared CLI/dashboard terminal card rendering into
  `packages.operator.cli_cards`; `apps.dashboard_command` now uses the package
  renderer directly, and app import boundary allowlist debt is now 17.
- Moved the Reflect runner, evidence packet builder, prompt fragments, and
  context-compression helpers into `packages.reflect`, preserving
  `apps.reflect.*` as compatibility module aliases so existing monkeypatch
  tests still patch the owning module; app import boundary allowlist debt is
  now 14.
- Removed the gateway setup wizard's static `apps.cli.runtime` dependency by
  replacing it with a narrow runtime protocol and explicit factory hook; app
  import boundary allowlist debt is now 13.
- Modeled the standalone cron scheduler command and daemon task scheduler as
  documented top-level composition/support sources in the executable
  app-boundary guard, with regression coverage; app import boundary allowlist
  debt is now 8.
- Modeled the learning worker runtime as a documented top-level worker process
  support source, moved cron delivery eligibility into `packages.gateway_core`,
  and routed API manual cron delivery through the daemon bridge instead of
  importing gateway cron internals; app import boundary allowlist debt is now
  6.
- Routed API proactive-ask execution through the daemon bridge instead of
  importing gateway runtime internals; app import boundary allowlist debt is
  now 5.
- Routed CLI birth IM onboarding through the gateway command boundary with
  additive prompt/skip options instead of importing gateway internals; app
  import boundary allowlist debt is now 4.
- Routed API manual cron execution through the daemon bridge instead of
  constructing `CliRuntime`; app import boundary allowlist debt is now 3.
- Removed the gateway cron service's static CLI runtime import by adding a
  runtime factory protocol and injecting it from the standalone cron command;
  app import boundary allowlist debt is now 2.
- Routed API Reflect context compression runtime construction through the
  daemon bridge instead of importing `CliRuntime`; app import boundary allowlist
  debt is now 1.
- Moved API Weixin QR bootstrap and account persistence helpers into
  `packages.gateway_core.weixin_bootstrap`, so the dashboard gateway surface no
  longer imports `apps.gateway.weixin_support`.
- Split the API gateway dashboard catalog and Weixin QR helpers out of
  `apps/api/api_runtime_gateway_ops.py` on 2026-05-25; the main gateway ops
  module is now 931 lines and stays below the line-limit gate.
- Added the additive `Episode.session_id` compatibility alias so older
  CLI/API-facing session surfaces continue to resolve to the canonical
  `episode_id`.
- Fixed a wake/herd stability race where hidden learning/sub-agent episodes
  could mask the latest user-visible elephant session.
- Prevented background learning and sub-agent turns from stealing the
  foreground `current_state` binding while still resolving their explicit
  state for kernel execution.
- Made the local install script default to the standard venv+pip path, with
  `ELEPHANT_INSTALL_USE_UV=1` as explicit opt-in, after the opportunistic uv
  path proved capable of hanging release smoke validation.
- Added a 300 second diagnostic timeout to the install distribution smoke so
  release verification fails with command context instead of hanging silently.
- Fixed current CLI cognition regressions so lightweight repository doubles no
  longer need `load_state`, continuity reengagement remains a gentle
  relationship-preserving prompt, and canonical relationship projections keep
  identity-derived initiative expectations visible.
- Verified the current broad gate set: `make agent-fast-gate`,
  `make test-integration-scenarios`, and full `make test-e2e` all pass on
  2026-05-24. Full e2e ran 148 tests in 1120.069 seconds with 2 environment
  skips.
- Verified this app-boundary/runtime-cognition increment with
  `make agent-fast-gate` on 2026-05-25.
- Verified the app-boundary allowlist cleanup with `make agent-scorecard` on
  2026-05-25: line-limit allowlist debt is 0 and app-boundary allowlist debt is
  0.
- Verified the runtime-observability increment with targeted daemon,
  gateway-cron, proactive-ask, API/gateway, and agent-gate tests on 2026-05-25.
- Added `docs/agent/runtime-resource-ownership.md` on 2026-05-25 so memory and
  compute budget ownership has one agent-facing source of truth.
- Verified the kernel generation-context observability increment with targeted
  unit tests and `make test-integration-scenarios` on 2026-05-25.
- Added an executable `Silent broad exception debt` scorecard metric on
  2026-05-25 and reduced it from 235 to 0 by making API, CLI, gateway,
  evidence, context, Reflect, model, skill, tool, understanding, and embedding
  fallback paths observable while preserving best-effort behavior.
- Added `tools/agent/public-contracts.yaml` on 2026-05-25 and made
  `agent_gate.py` validate public HTTP route anchors, CLI/shell/gateway command
  anchors, package root `__all__` exports, storage schema ownership, release
  contracts, dashboard/site/macOS/gateway surface validation contracts, and
  tool-schema anchors. `make agent-scorecard` now reports public contract
  inventory debt, currently 0.
- Verified the public-contract increment with `python3 -m unittest
  tests.agent.test_agent_gate`, `make agent-validate`, `make agent-scorecard`,
  `make agent-lint`, `make agent-fast-gate`, and `make agent-context-audit` on
  2026-05-25.
- Split the harness gate itself on 2026-05-25: public contract inventory
  validation/rendering now lives in
  `tools/agent/scripts/agent_public_contracts.py`, scorecard scanners now live
  in `tools/agent/scripts/agent_scorecard_scans.py`, and
  `tools/agent/scripts/agent_gate.py` is down to 920 lines while preserving the
  existing import/re-export test surface.
- Added
  [ADR-0002 Release Artifact Provenance](../adr/adr-0002-release-artifact-provenance.md)
  on 2026-05-25, linked it from the release model, anchored it in the public
  contract inventory, and added release certification assertions for provenance
  boundaries.
- Added `tools/release/provenance.py` and `make package-provenance` on
  2026-05-25 so `make package-verify` writes Python artifact provenance and
  SHA256 checksums. The PyPI workflow now uploads only wheel/sdist artifacts to
  PyPI while attaching provenance files to GitHub releases.
- Added `apps/api/api_runtime_routes.py` on 2026-05-25 as the declared `/v1`
  route-family inventory, wired top-level HTTP dispatch through those
  constants, and moved public-contract route anchors to that declaration.
- Added runtime resource contracts to `tools/agent/public-contracts.yaml` on
  2026-05-25 so prefix cache, projection compaction, embedding cache/backfill,
  tool result pruning, loop checkpoint resume, and background learning owners
  are validated against their implementation and regression-test anchors.
- Added `make test-gateway-e2e-smoke` on 2026-05-25 as a fast cross-adapter
  gateway route/control smoke target, documented it in the gateway e2e rules,
  and anchored it in the public surface contract inventory.
- Split the first gateway e2e slices on 2026-05-25:
  `gateway_adapter_test_base.py` now owns the shared fixture and route/control
  helper methods,
  `test_gateway_adapter_telegram.py` owns Telegram identity/thread and resume
  coverage, and `test_gateway_adapter_cli_surface.py` owns low-coupling
  gateway CLI/parser surface tests. The largest gateway e2e file dropped from
  6850 to 6310 lines without reducing smoke coverage.
- Split the Feishu control bridge e2e slice on 2026-05-25 into
  `test_gateway_adapter_feishu_control.py`, moved the smoke target to the new
  suite, and anchored the suite in the public surface contract inventory. The
  largest gateway e2e file is now 5382 lines without reducing route-control
  smoke coverage.
- Split the Feishu long-connection and async lifecycle e2e slice on
  2026-05-25 into `test_gateway_adapter_feishu_long_connection.py`, then split
  async queue/concurrency/failure/recovery coverage into
  `test_gateway_adapter_feishu_async_runtime.py`. The async parallelism smoke
  target now lives in the async runtime suite, and both suites are anchored in
  the public surface contract inventory.
- Split the Feishu event, webhook, and runtime routing e2e slice on
  2026-05-25 into `test_gateway_adapter_feishu_events.py`, then split service
  delivery/web-app/runtime dedupe coverage into
  `test_gateway_adapter_feishu_runtime.py`. The Feishu manifest-account smoke
  target now lives in the runtime suite, and both suites are anchored in the
  public surface contract inventory.
- Split the CLI shell tool-progress regression slice on 2026-05-25 into
  `tests/unit/cli/test_shell_tool_progress.py`, moved shared shell fixtures to
  `tests/unit/cli/shell_test_support.py`, and reconciled stale shell UI/state
  assertions with the current contract. The remaining `test_shell.py` file is
  now 3331 lines; the 153 remaining tests pass when run in four chunks, while
  the monolithic process still hits the local long-test limit around 200
  seconds.
- Split the CLI shell startup/pending-entry regression slice on 2026-05-25 into
  `tests/unit/cli/test_shell_startup_entry.py`. The remaining `test_shell.py`
  file is now 2709 lines and its 120 tests pass as a single process in about
  167 seconds.
- Split the CLI shell visual-layout regression slice on 2026-05-25 into
  `tests/unit/cli/test_shell_visual_layout.py`, covering history-row width,
  growth-row styling, elephant mark layout, and shell-frame branding. The
  remaining `test_shell.py` file is now 2524 lines, and the combined 120 tests
  pass in about 157 seconds.
- Split the CLI shell status/banner regression slice on 2026-05-25 into
  `tests/unit/cli/test_shell_status_banner.py`, covering Personal Model banner
  rendering, skill affinity summaries, frozen-state status, status bar usage,
  growth progress, and diff palette assertions. The remaining `test_shell.py`
  file is now 1950 lines, and the combined 107 tests pass in about 152
  seconds.
- Split the CLI shell progress-frame regression slice on 2026-05-25 into
  `tests/unit/cli/test_shell_progress_frame.py`, covering live tool activity,
  streaming response, reasoning, context compaction, and recall frame
  rendering. Then moved the remaining startup/state-focus transition tests into
  `tests/unit/cli/test_shell_startup_entry.py`.
- Split the CLI shell command-surface regression slice on 2026-05-25 into
  `tests/unit/cli/test_shell_command_surface.py`, covering command palette,
  learning notices, conversational surface routing, skill search/enable/install,
  growth panel filtering, web-read interception, provider/model wizard cancel,
  prompt style, live composer, and command palette height behavior. The
  remaining `test_shell.py` file is now 954 lines, the command-surface slice is
  873 lines, and the two modules pass together as 61 tests in about 114
  seconds.
- Split the CLI shell startup state-focus regression slice on 2026-05-25 into
  `tests/unit/cli/test_shell_startup_state_focus.py`, covering opener prompts,
  state-focus onboarding, startup notices, transition timing, queued first-turn
  gates, constructor deferral, and startup prime sentinel behavior. The
  remaining `test_shell_startup_entry.py` file is now 549 lines, the
  state-focus slice is 631 lines, and the two modules pass together as 48 tests
  in about 84 seconds.
- Split the CLI e2e surface on 2026-05-25 into
  `tests/e2e/cli/cli_surface_test_base.py`,
  `test_cli_surface_provider.py`, `test_cli_surface_herd.py`,
  `test_cli_surface_facts.py`, and `test_cli_surface_skills.py`. The main
  `test_cli_surface.py` file is now 563 lines, the split modules are wired into
  `make test-e2e` and the public surface contract inventory, and the combined
  CLI e2e slice passes as 29 tests in about 451 seconds.
- Split the OpenAI-compatible provider integration suite on 2026-05-25 into
  `tests/integration/models_auth/openai_compatible_provider_test_base.py`,
  `test_openai_compatible_provider_reasoning.py`,
  `test_openai_compatible_provider_responses.py`, and
  `test_openai_compatible_provider_http_fallback.py`. The main
  `test_openai_compatible_provider.py` file is now 461 lines, and the combined
  provider integration slice passes as 28 tests in about 12 seconds.
- Split the broader models/auth integration suite on 2026-05-25 into
  `tests/integration/models_auth/test_models_auth_discovery.py`, covering
  environment/provider discovery, Codex/Copilot API listing, live catalog
  fallback, Ollama show metadata, models.dev fallback, Claude Code credentials,
  Copilot ACP process discovery, and compatible endpoint profile inputs. The
  remaining `test_models_auth_integration.py` file is now 889 lines, the
  discovery slice is 659 lines, and the full `tests.integration.models_auth`
  package passes as 72 tests in about 34 seconds.
- Split the tools/skills integration suite on 2026-05-25 so
  `tests/integration/tools_skills/test_tools_and_skills_runtime.py` now focuses
  on tool runtime, approval, manifest, and MCP registration behavior, while
  `tests/integration/tools_skills/test_skills_runtime.py` owns skill loader,
  scope/dependency, SkillHub, provenance, and builtin catalog coverage. The
  split files are 699 and 900 lines, and the combined slice passes as 26 tests.
- Split the Personal Model lifecycle unit suite on 2026-05-25 so
  `tests/unit/test_personal_model_lifecycle.py` now focuses on index failure
  logging, time-range parsing, conversation discovery, and conversation recall
  filtering, while `tests/unit/test_personal_model_update_lifecycle.py` owns
  claim update/delete/protection/audit/search diagnostics/question/skill
  optimization lifecycle coverage. The split files are 612 and 896 lines, and
  the combined slice passes as 34 tests.
- Split the CLI wizard menu and text-prompt unit slice on 2026-05-25 into
  `tests/unit/cli/test_main_wizard_menu.py`.
- Split the CLI main setup/growth flow unit slice on 2026-05-25 into
  `tests/unit/cli/test_main_setup_flow.py`, covering init setup, birth wizard,
  elephant creation, interactive shell handoff, and growth-session resolution.
  The remaining `test_main_wizard.py` file is now 384 lines and focuses on
  parser/provider/herd/facts/brain routing; the setup-flow slice is 871 lines,
  and the three wizard modules pass together as 57 tests in about 26 seconds.
- Split the CLI runtime cognition skill slice on 2026-05-25 into
  `tests/unit/cli/test_runtime_cognition_skills.py`, covering skill index,
  disclosure reasons, skill catalog steady-up behavior, shelf reuse, skill-hub
  listing, source search, remote-source inspect, and builtin skill inspect.
- Split the CLI runtime cognition recall/continuity/opening slice on
  2026-05-25 into `tests/unit/cli/test_runtime_cognition_recall.py`, covering
  durable recall recovery, continuity guidance, embedding steady-up, surfaced
  notes, workspace rule discovery, explain-next-step persistence/growth,
  startup opening replies, next-episode continuation, and state-focus runtime
  status. The remaining `test_runtime_cognition.py` file is now 750 lines, the
  recall slice is 584 lines, and the four cognition modules pass together as 54
  tests in about 132 seconds.
- Split the Discord setup, runtime, delivery, and SDK dispatch e2e slice on
  2026-05-25 into `test_gateway_adapter_discord.py`, then split Discord
  dispatch/runtime/delivery formatting coverage into
  `test_gateway_adapter_discord_runtime.py`. The Discord smoke target now points
  at the runtime slice, both suites are anchored in the public surface contract
  inventory, the setup suite is 675 lines, the runtime suite is 933 lines, and
  the two modules pass together as 22 tests in about 47 seconds.
- Added `make agent-public-contracts-docs` on 2026-05-25 so
  `docs/agent/public-contracts.md` is generated from
  `tools/agent/public-contracts.yaml`; `make agent-validate` now fails when the
  generated public contract document is stale.
- Added `docs/agent/compatibility-lifecycle.md` and a
  `compatibility_contracts` public-contract section on 2026-05-25 so CLI,
  gateway, Reflect, learning-agent, Episode, storage-status, and kernel
  compaction shims have explicit owner, doc, and regression-test anchors.
- Added GitHub artifact attestation to `.github/workflows/pypi-publish.yml` on
  2026-05-25 with `actions/attest@v4` and `subject-checksums:
  dist/SHA256SUMS`; the release model, provenance ADR, release/deploy tests,
  and public contract inventory now assert that publish boundary.
- Added SQLite locking/integrity resource ownership on 2026-05-25 so the
  repository connection contract for foreign keys, WAL journaling, and busy
  timeout is documented, public-contract anchored, and covered by storage
  integration tests.
- Anchored the storage `SCHEMA_VERSION = 1` declaration in
  `tools/agent/public-contracts.yaml` on 2026-05-25 so any future version bump
  fails public-contract validation until the release/migration policy is
  updated.
- Split the API provider/default-provider/transport e2e slice on 2026-05-25
  into `test_api_surface_providers.py`, moved shared API e2e fixtures into
  `api_surface_test_base.py`, registered the focused suite in `make test-e2e`,
  moved the release-smoke provider bad-request assertion to the new suite, and
  anchored both API e2e surfaces in the public contract inventory. The remaining
  mixed API e2e file is now 1630 lines.
- Split the API internal dashboard/operator/control e2e slice on 2026-05-25
  into `test_api_surface_dashboard.py`, moved the release-smoke dashboard
  assertions to the focused suite, registered it in `make test-e2e`, and
  anchored it in the public contract inventory. The core
  `test_api_surface.py` file is now 486 lines.
- Split the API dashboard ops e2e slice on 2026-05-25 into
  `tests/e2e/api/test_api_surface_dashboard_ops.py`, covering gateway card
  configuration, MCP server/tool management, external skill shelves, operator
  MCP discovery, durable-state preservation after Episode delete, and growth
  lane exclusion. The remaining dashboard e2e file is now 914 lines, the ops
  slice is 501 lines, and the two modules pass together as 12 tests in about 25
  seconds.
- Split the CLI main wizard/parser/setup unit-test slice on 2026-05-25 into
  `tests/unit/cli/test_main_wizard.py`, leaving
  `tests/unit/cli/test_main.py` focused on init/status/question copy and doctor
  behavior. The core `test_main.py` file is now 338 lines, and the combined 77
  tests pass in about 25 seconds.
- Split the CLI runtime cognition operator/profile/elephant lifecycle unit-test
  slice on 2026-05-25 into
  `tests/unit/cli/test_runtime_cognition_operator.py`, with shared runtime
  construction in `tests/unit/cli/runtime_cognition_test_base.py`. The core
  `test_runtime_cognition.py` file is now 1498 lines, and the combined 54 tests
  pass in about 85 seconds.
- Split the built-in tools file/terminal/process/code-execution unit-test slice
  on 2026-05-25 into `tests/unit/test_builtin_tools_file_code.py`, with shared
  runtime construction in `tests/unit/builtin_tools_test_support.py`. The core
  `test_builtin_tools_v2.py` file is now 927 lines, and the combined 52 tests
  pass in about 17 seconds.
- Split the Weixin/WeCom gateway control and same-conversation serialization
  e2e slice on 2026-05-25 into
  `tests/e2e/gateway/test_gateway_adapter_weixin_wecom.py`, registered it in
  `make test-e2e`, and anchored it in the public surface contract inventory.
  The remaining mixed gateway e2e file is now 1388 lines.
- Split the chat-bot identity and webhook delivery e2e slice on 2026-05-25
  into `tests/e2e/gateway/test_gateway_adapter_chat_webhook.py`, registered
  all focused gateway e2e modules in `make test-e2e`, and anchored the new
  surface in the public contract inventory. The remaining mixed gateway e2e
  file is now 1213 lines.
- Split the Telegram service dispatch and cross-adapter web-app mounting e2e
  slice on 2026-05-25 into
  `tests/e2e/gateway/test_gateway_adapter_services.py`, registered it in
  `make test-e2e`, and anchored the new surface in the public contract
  inventory. The remaining mixed gateway e2e file is now 1077 lines.
- Split the Feishu setup CLI/runtime e2e slice on 2026-05-25 into
  `tests/e2e/gateway/test_gateway_adapter_feishu_setup.py`, registered it in
  `make test-e2e`, anchored the new surface in the public contract inventory,
  and cleaned the remaining gateway main-suite imports. The remaining mixed
  gateway e2e file is now 429 lines.

## Scorecard

Overall score: **96/100**. This is an architecture and maintainability score,
not a product-market or feature-value score. The score is rounded from the
equal-weight average of the ten dimensions below.

| Dimension | Score | Evidence | Main Deductions | 100/100 Target |
| --- | ---: | --- | --- | --- |
| System completeness | 88 | Core layers, apps, tests, deploy, release, docs, and harness all exist. Current app surfaces are listed in app and repo docs, core public contracts have an executable inventory, compatibility shims now have lifecycle and regression anchors, and dashboard/site/macOS/gateway surface validation anchors are checked by the same contract file. | Some app surfaces are still thinner or less indexed in tests and release gates than runtime reality, especially background workers and visual/runtime proof for the desktop shell. | Every product path has an owner doc, local rules, tests, release gate, dashboard/operator story, and public-contract entry where applicable. |
| Maintainability, iteration, extensibility | 99 | Clear package map and local AGENTS exist, new app-to-app imports are blocked without allowlist debt, public interface and compatibility ownership are now machine-checkable, the Typer runner plus shared terminal stack, terminal UI, wizard primitives, terminal cards, gateway banner rendering, proactive ask evaluation, cron delivery visibility, Reflect feature registry, Reflect runner/evidence/prompt/compression support, and gateway setup/runtime binding are now app-neutral, bridge-backed, or protocol-shaped; daemon CLI-runtime construction also goes through the root app-support bridge, every tracked non-generated Python source file is now at or below the 1000-line ceiling, the harness gate is split into focused public-contract and scorecard-scanner helpers, the gateway e2e suite now has focused CLI, Telegram, Discord, Feishu setup/event/runtime/control/long-connection/async-runtime, Weixin/WeCom route-control, chat-bot/webhook, and service-mount modules wired into full e2e coverage, the API e2e suite now has focused dashboard/operator and provider/default-provider/transport modules with shared fixtures, CLI e2e now has focused provider/bootstrap, herd, facts, and skills modules with shared process fixtures, OpenAI-compatible provider integration tests now separate request/core chat coverage from reasoning, Responses API, and HTTP fallback coverage, CLI main unit tests now separate init/status copy, wizard menu/text-prompt behavior, and wizard/parser/setup behavior, CLI runtime cognition tests now separate operator/profile/elephant lifecycle, skill-catalog/source, and remaining context/continuity cognition coverage, built-in tool tests now separate file/terminal/process/code execution coverage from schema/PM/skill/sub-agent/domain-tool coverage, and the CLI shell suite now has shared fixtures plus focused tool-progress, startup-entry/state-focus, visual-layout, status-banner, and progress-frame modules. | Near-ceiling runtime files, monkey-patched compatibility classes, root app-support bridges, and remaining runtime/sub-agent ownership seams still raise change cost. | Hotspots are split behind narrow owned services; app-neutral shared logic lives below app surfaces; line-limit, app-boundary, and public-contract debt stay at zero. |
| API stability and consistency | 97 | CLI, programmatic API, capability protocols, package roots, and clean schema are present. The public Personal Model search modes now align with the tool schema and have regression coverage, ADR-0001 blocks first-wave breaking changes, `Episode.session_id` preserves legacy session callers, legacy `active` route status maps to canonical open Episodes, API cron/proactive ask/Reflect helpers now use package-owned ports or daemon bridge contracts, app-boundary drift has an executable guard with zero allowlist debt, `apps/api/api_runtime_routes.py` now declares top-level `/v1` route families used by dispatch, `tools/agent/public-contracts.yaml` validates public HTTP route anchors, CLI/shell/gateway commands, package exports, compatibility surfaces, storage schema, release contracts, surface contracts, and tool-schema anchors, and `docs/agent/public-contracts.md` is generated from that inventory with freshness enforced by `make agent-validate`. | HTTP dispatch is still hand-rolled below the route-family layer, and routes are declared but not generated from a full request/response schema. | CLI/HTTP/tool/package/storage interfaces have one declared contract each, compatibility tests, and generated docs where practical. |
| Performance, usability, stability | 92 | Bounded query work has already improved in storage, recall, dashboard, and lifecycle paths; SQLite runtime connections now have an explicit, tested foreign-key/WAL/busy-timeout contract; Episode close and kernel lifecycle side-effect failures now log warnings instead of disappearing silently; daemon status/registry describe failures, proactive-ask state/profile fallback failures, gateway cron fan-out delivery failures, API startup/config and episode-query fallbacks, evidence indexing fallbacks, context projection/cache/backfill fallbacks, context compression fallback, kernel generation-context PM fact load failures, API/CLI/gateway operator fallback failures, observer failures, provider discovery fallbacks, and skill/tool/runtime fallback paths are observable; background sub-agent turns no longer steal foreground state; gateway setup auto-start now goes through managed restart service injection; CLI cognition regressions around lightweight repository doubles and continuity projection are covered; focused gateway and shell suites now avoid the worst local long-test process limits; full e2e and integration scenarios pass. | Gateway async code, streaming observer locks, remaining large e2e tests, and mixed thread/async execution remain risk areas. | Hot paths have bounded repository queries, explicit timeout policy, observable failures, and focused regression tests. |
| Memory and compute management | 90 | Context budgets, embedding cache/backfill, tool-result pruning, loop checkpoints, token telemetry, and package-owned Reflect context compression exist; `runtime-resource-ownership.md` names the owners, persistence boundaries, budget invariants, and validation suites for prefix cache, compaction, embedding cache, tool result pruning, checkpoints, and background learning work; `tools/agent/public-contracts.yaml` now validates those resource owners against implementation and regression-test anchors; Personal Model fact load failures, projection embedding cache/backfill failures, provider projection-summary fallback, local embedding steady-worker failure, and reflect compression fallback are logged without blocking generation. | Some cache and compaction implementation ownership is still split between kernel, CLI, API, and gateway support, and deeper budget invariants are test-backed but not yet generated from a runtime resource schema. | One documented and executable ownership model for prefix cache, compaction, embedding cache, tool budgets, and checkpoint resume. |
| Release and upgrade completeness | 98 | CI runs build/test/e2e; package verify checks wheel leaks; PyPI and macOS workflows exist; the release model now states reset/migration, release-note, package-verification, macOS-signing, provenance, and GitHub attestation boundaries, with release-contract coverage; ADR-0002 defines Python artifact provenance, GitHub artifact attestation, and macOS signing-mode boundaries; `make package-verify` emits `dist/elephant-agent-provenance.json` and `dist/SHA256SUMS`; the PyPI workflow uploads only wheel/sdist artifacts to PyPI, attaches provenance files to GitHub releases, and generates an `actions/attest@v4` attestation from `dist/SHA256SUMS`; public-contract validation anchors the storage schema SQL, schema version declaration, release model, provenance ADR, publish attestation, release workflow, install distribution smoke, dashboard/site build gates, macOS latest-release workflow, and gateway adapter e2e suite; the local install script defaults to the reliable pip path and install smoke has a diagnostic timeout. | Schema upgrade posture is intentionally reset oriented until a real schema bump appears, and SBOM or external transparency-log verification remains future work. | Release candidates have deterministic migration policy, artifact provenance/signing, changelog discipline, and install rollback notes. |
| Bottlenecks and bug risk | 97 | Large e2e and runtime files still expose blast radius, but two concrete race/hang classes are covered by tests or timeouts, the scorecard now reports silent broad exception debt and public contract inventory debt, both currently 0, the gateway adapter suite has a fast cross-adapter smoke target for route/control regression triage, the gateway e2e split extracted a shared fixture plus focused CLI surface, Telegram, Discord, Feishu setup/event/runtime/control/long-connection/async-runtime, Weixin/WeCom, chat-bot/webhook, and service-mount modules that are all wired into `make test-e2e`, API dashboard/operator and provider/default-provider/transport slices now run independently and remain in the e2e/release smoke paths, CLI provider/bootstrap, herd, facts, and skills e2e slices now run independently and remain wired into full e2e, the CLI shell tool-progress, startup-entry/state-focus, visual-layout, status-banner, and progress-frame slices now run independently, stale shell UI/state assertions were reconciled with the current contract, and the remaining shell main suite now runs as one process inside the local long-test envelope. | Global caches, dynamic method assignment, shell subprocesses, and near-ceiling runtime surfaces create hidden failure modes even though focused gateway, API, and shell slices are now explicit. | Bottlenecks are tracked by owner, reduced by hotspot refactors, and guarded by tests that fail loudly on regressions. |
| System debt management | 99 | The completed legacy cleanup debt is marked closed, active gaps are tracked in this scorecard roadmap, compatibility shims have a removal lifecycle, and line-limit/app-boundary/silent-exception/public-contract debt counts are visible in `make agent-scorecard`; all four currently report 0. | Some architectural gaps still only live in this scorecard until split into implementation branches, and root app-support bridges still need package-port follow-up. | Every accepted gap has an owner, close condition, risk, validation command, and link from the active roadmap. |
| Repo harness and coding-agent friendliness | 100 | Agent report, context map, task matrix, public-contract inventory, generated public-contract docs, validation ladder, worktree and wave flows are executable. The repo map now names the current largest hotspots and harness contract files, active task cards define branch-sized follow-up work, `apps/README.md` is routed, app-boundary drift is guarded with an empty allowlist, documented top-level app composition sources including daemon/cron/worker/runtime bridges are modeled explicitly, scorecard debt counts include line-limit, app-boundary, silent broad exception, and public contract metrics, dashboard/site/macOS/gateway surface gates are anchored in the inventory, generated contract-doc freshness is enforced by `make agent-validate`, gateway-to-CLI UI/runtime coupling was retired behind package or app-support ports with compatibility tests, and the harness gate itself is split into focused helper modules without changing its public command surface. | Route-schema codegen and deeper product-specific worker lanes still require maintainer judgment, but the repo harness itself now exposes enough context, ownership, and validation to be agent-friendly without manual archaeology. | A new coding agent can pick a task, get exact context, avoid unrelated files, and validate without manual repo archaeology. |
| Documentation freshness and clarity | 99 | README, system design, repo map, testing strategy, release model, plans, ADRs, task cards, generated public-contract docs, compatibility lifecycle docs, and local rules exist. The plans index, apps inventory, search-mode docs, hotspot inventory, runtime resource ownership, compatibility shim lifecycle, context map, task matrix, public-contract inventory, surface validation anchors, reflect/operator/gateway-core ownership docs, app-support bridge docs, runtime-observability progress, executable silent-exception metric, executable public-contract metric, generated contract-doc freshness check, and debt register now align with current public surfaces; scorecard progress reflects the 2026-05-25 zero-debt observability and public-contract passes; search-mode drift is tested. | Remaining drift checks are concentrated in macOS/release provenance depth and visual/runtime proof depth for non-core surfaces. | Docs have one consistent source of truth per concept, current app inventory, and drift checks for public interfaces. |

## P0 Alignment Items

These should be fixed before deeper refactors because they reduce ambiguity for
every later contributor or agent.

| Item | Blast Radius | Target | Validation |
| --- | --- | --- | --- |
| Document scorecard entrypoint and roadmap relationship. | `docs/agent/plans/**` | Done: this file and the plans index make the scorecard discoverable without forking the existing cleanup roadmap. | `make agent-validate`, `make agent-test` |
| Fix `tool.personal_model.search` mode drift. | `docs/system-design/**`, tool docs/tests if needed | Done: the system design now describes the current public enum, `auto` and `inventory`, and maps stricter lookup to parameters instead of obsolete modes. | `make agent-report CHANGED_FILES="docs/system-design/system-layer-model.md"`, `make agent-validate`, targeted tool tests |
| Update app inventory and hotspot docs. | `apps/README.md`, `docs/agent/repo-map.md` | Done: app surfaces are listed in `apps/README.md`, and the repo map names current app/test/package hotspots. Keep both current as ownership changes. | `make agent-validate` |
| Reconcile active debt status. | `docs/agent/tech-debt/**`, active plans | Done: the completed Understanding cleanup is marked closed; new gaps should become new debt entries or task cards. | `make agent-validate`, `make agent-context-audit CHANGED_FILES="docs/agent/tech-debt/..."` |
| Inventory public contracts. | `tools/agent/public-contracts.yaml`, `tools/agent/scripts/agent_gate.py`, public interface owners | Done: public HTTP route anchors, CLI/shell/gateway commands, package exports, storage schema, release contracts, dashboard/site/macOS/gateway surface validation contracts, and tool schemas are now validated by the harness and reported in `make agent-scorecard`. | `make agent-scorecard`, `make agent-validate`, `python3 -m unittest tests.agent.test_agent_gate` |

## P1 Architecture Tracks

The active branch-sized cards for these tracks are listed in
[task-cards/README.md](../task-cards/README.md). They are governed by
[ADR-0001 Scorecard Refactor Operating Model](../adr/adr-0001-scorecard-refactor-operating-model.md).

### Track A: API And App Boundary Stabilization

Goal: reduce app-to-app imports and make shared runtime surfaces app-neutral.

Task card:
[architecture-api-app-boundary.md](../task-cards/architecture-api-app-boundary.md).

Initial write scopes:

- Move shared provider runtime helpers from `apps.provider_runtime*` into an
  app-neutral package or clearly documented app support layer.
- Done: replace gateway imports of `apps.cli.shell` and `apps.cli.wizard`
  with narrower `packages.operator` ports while keeping CLI compatibility
  aliases.
- Done: remove stale gateway `apps.cli.runtime` imports and route gateway
  wizard banner rendering through the package-level terminal UI port.
- Done: move proactive ask tick evaluation and adapter inventory into
  `packages.gateway_core`.
- Done: move Reflect feature resolution into `packages.reflect.features`.
- Done: move shared CLI/dashboard terminal card rendering into
  `packages.operator.cli_cards`.
- Done: move Reflect runner, evidence packets, prompt fragments, and context
  compression into `packages.reflect` with `apps.reflect.*` compatibility
  aliases.
- Done: replace the gateway setup wizard's static CLI runtime import with a
  narrow protocol and explicit factory hook.
- Done: model documented top-level app composition sources as harness-level
  source exceptions with tests instead of allowlist debt.
- Done: extend composition-source modeling to the standalone cron scheduler
  command, daemon task scheduler, and learning worker runtime, reducing tracked
  app-boundary allowlist debt to 7.
- Done: move cron delivery eligibility into `packages.gateway_core` and route
  API manual cron delivery through the daemon bridge, reducing tracked
  app-boundary allowlist debt to 6.
- Done: route API proactive-ask execution through the daemon bridge, reducing
  tracked app-boundary allowlist debt to 5.
- Done: route CLI birth IM onboarding through the gateway command boundary,
  reducing tracked app-boundary allowlist debt to 4.
- Done: route API manual cron execution through the daemon bridge, reducing
  tracked app-boundary allowlist debt to 3.
- Done: inject the gateway cron runtime factory from the top-level cron command,
  reducing tracked app-boundary allowlist debt to 2.
- Done: route API Reflect context compression runtime construction through the
  daemon bridge, reducing tracked app-boundary allowlist debt to 1.
- Done: route gateway CLI control's default runtime construction through the
  root app-support bridge, reducing tracked app-boundary allowlist debt to 0.
- Replace root app-support runtime bridges with package-owned runtime/sub-agent
  ports where practical.

Validation:

- `make agent-report CHANGED_FILES="apps/gateway/... apps/cli/... apps/api/... packages/..."`
- `make agent-fast-gate`
- `make test-e2e` when CLI, API, or gateway behavior changes.

### Track B: Hotspot Decomposition

Goal: make large files reviewable without changing public behavior.

Task cards:
[architecture-cli-hotspot-split.md](../task-cards/architecture-cli-hotspot-split.md),
[architecture-storage-hotspot-split.md](../task-cards/architecture-storage-hotspot-split.md),
[architecture-evidence-hotspot-split.md](../task-cards/architecture-evidence-hotspot-split.md),
[architecture-provider-hotspot-split.md](../task-cards/architecture-provider-hotspot-split.md),
and [architecture-gateway-e2e-split.md](../task-cards/architecture-gateway-e2e-split.md).

Priority order:

1. Keep `apps/cli/cli_main_impl.py` split by command family; the main Typer
   registration file is below the line limit, and future work should reduce the
   compatibility delegation layer only after tests stop patching private
   helpers. The shell regression suite now has separate tool-progress,
   startup-entry/state-focus, visual-layout, status-banner, and progress-frame
   modules plus shared shell fixtures. The CLI e2e surface now has separate
   provider/bootstrap, herd, facts, and skills modules. Runtime cognition now
   has a separate skill-catalog/source slice, so the next CLI cleanup should
   focus on the remaining context/continuity cognition coverage or wizard
   private patch points before removing CLI private-helper delegation layers.
2. Continue the storage repository split only when another cohesive family
   becomes a hotspot; LearningJob and checkpoint methods now live in focused
   modules, while the remaining system-method file is below the line limit.
3. Split `packages/evidence/runtime.py` into scope resolution, lexical
   ranking, semantic ranking, replay projection, and backfill policy.
4. Continue the first provider split by separating request shaping from
   `packages/models/providers/openai_compatible.py`; response parsing,
   streaming, embedding extraction, usage parsing, and tool-call compatibility
   now live in `packages/models/providers/openai_compatible_response_parsing.py`.
5. Continue splitting `tests/e2e/gateway/test_gateway_adapter.py` into
   adapter-specific and shared route-control suites. Shared fixture, CLI
   surface, Telegram, Discord, Feishu setup, Feishu event/runtime, Feishu
   control, Feishu long-connection/async-runtime, Weixin/WeCom,
   chat-bot/webhook, and service-mount slices are already separate.
6. Continue splitting API e2e by public route family only when a new route
   family becomes large. The core `tests/e2e/api/test_api_surface.py` suite is
   now 486 lines; dashboard/operator coverage lives in
   `tests/e2e/api/test_api_surface_dashboard.py`, provider
   onboarding/default-provider/transport coverage lives in
   `tests/e2e/api/test_api_surface_providers.py`, and shared fixtures live in
   `tests/e2e/api/api_surface_test_base.py`.

Validation:

- Behavior-preserving refactors start with targeted tests for the touched file.
- Each split must run `make agent-lint`; runtime splits also run
  `make agent-fast-gate`.
- Gateway/API/CLI splits run targeted e2e before broad e2e.

### Track C: Runtime Performance And Stability

Goal: keep hot paths bounded and failure modes observable.

Task card:
[architecture-runtime-stability.md](../task-cards/architecture-runtime-stability.md).

Initial checks:

- Audit SQLite write transactions and retry policy around WAL and busy timeout.
- Add explicit owners for streaming observer state and gateway async lifecycle.
- In progress: replace broad silent exception handling with logged or
  telemetry-backed best-effort failures where behavior must continue. Done
  families now include Episode close/kernel lifecycle indexing, kernel
  generation-context PM fact loading, daemon status describe paths,
  proactive-ask state/profile fallback, gateway cron fan-out delivery, API
  startup/config and episode-query fallbacks, evidence semantic summary indexing, context
  projection cache/backfill, and context compression fallback.
- Keep semantic recall cache-first and prove no per-turn O(N) reindex path
  returns.
- Extend regression coverage around loop checkpoint resume, tool parallelism,
  and context overflow retry.

Validation:

- `make test-integration-scenarios`
- `make test-release-scenarios`
- Targeted gateway and kernel unit tests.

### Track D: Release, Upgrade, And Artifact Integrity

Goal: make release confidence explicit beyond current green CI.

Task card:
[architecture-release-upgrade.md](../task-cards/architecture-release-upgrade.md).

Initial checks:

- Document the storage upgrade posture: clean reset, supported schema version,
  and when a real migration is required.
- Add release note and changelog expectations for public API or storage changes.
- Keep package verification checking for node_modules, legacy migrations,
  schema SQL, and dashboard assets.
- Decide whether artifact signing/provenance belongs in the next release track
  or an ADR.

Validation:

- `make package-verify`
- `make release`
- release workflow dry-run or contract tests where available.

### Track E: Frontend, Desktop, Gateway Adapter Coverage

Goal: bring non-core surfaces into the same scorecard discipline without
letting them block core cleanup sequencing.

Task card:
[architecture-surface-coverage.md](../task-cards/architecture-surface-coverage.md).

Initial checks:

- Dashboard: route lazy loading, bundle chunking, API contract assumptions, and
  visual regression readiness.
- Site: generated SkillHub drift, docs freshness, install page consistency.
- macOS: build path, runtime packaging, release-latest workflow, signing and
  notarization documentation.
- Gateway adapters: per-platform async lifecycle, credential handling,
  delivery queue behavior, and command-control consistency.

Validation:

- `make web-content-check`
- `make web-typecheck`
- `make web-build`
- `make macos-build` for macOS changes.
- gateway targeted e2e for adapter changes.

## Dependencies

- The canonical product design remains
  `docs/system-design/system-layer-model.md`; this scorecard measures
  implementation convergence, not a competing design.
- The executable harness contract remains `tools/agent/**`,
  `tools/make/agent.mk`, and CI workflows.
- Concrete cleanup implementation should update
  [Architecture And Harness Cleanup Roadmap](architecture-harness-cleanup.md)
  when the work belongs to its tracks.
- Breaking public API or schema changes require an ADR or explicit tech-debt
  entry before implementation.
- Parallel work must use disjoint worktree scopes; the broadest safe split is
  one track per worktree.

## Validation Matrix

Use the smallest proof that matches the touched surface:

| Surface | Minimum Gate | Broader Gate |
| --- | --- | --- |
| Scorecard/plans/agent text | `make agent-validate`, `make agent-test` | `make agent-fast-gate` |
| Harness executable rules | `make agent-fast-gate` | `make agent-pr-gate` |
| Kernel/state/evidence/context/storage | targeted unit/integration tests | `make test-integration-scenarios` |
| CLI/API/gateway | targeted unit/e2e tests | `make test-e2e` |
| Frontend | `make web-content-check`, `make web-typecheck` | `make web-build` |
| Release/package/install | `make package-verify` | `make release` |
| macOS | `make macos-build` | release-latest workflow/contracts |

## Exit Criteria

This scorecard has two finish lines:

- 90+ milestone: overall score reaches 90+ without any dimension below 85, and
  all P0 ambiguity has been eliminated.
- 100/100 completion: every dimension reaches 100, the line-limit allowlist has
  no unjustified production exceptions, public contracts have compatibility
  tests and one source of truth, and release/upgrade/artifact provenance is
  deterministic.

The final 100/100 state also requires:

- App-to-app imports are restricted to thin launchers or documented support
  modules; shared runtime behavior lives in packages or app-neutral support.
- Docs, repo map, context map, task matrix, and release model agree on current
  surfaces.
- A new coding agent can run `make agent-report CHANGED_FILES="..."`, read the
  emitted context, make a bounded change, validate it, and ship without a manual
  repo tour.
