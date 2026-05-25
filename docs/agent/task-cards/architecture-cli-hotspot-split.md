# architecture-cli-hotspot-split CLI Hotspot Decomposition

## Roadmap Track

[Track B: Hotspot Decomposition](../plans/architecture-scorecard-roadmap.md#track-b-hotspot-decomposition)

## Readiness

Ready for the first behavior-preserving hotspot split. This card covers only the
CLI orchestration hotspot; later cards should cover storage, evidence,
providers, and gateway e2e suites.

## Governing ADR

[ADR-0001 Scorecard Refactor Operating Model](../adr/adr-0001-scorecard-refactor-operating-model.md)

## Owner Profile

CLI maintainer comfortable with command dispatch, provider setup, shell runtime
construction, and existing unit/e2e CLI coverage.

## Suggested Branch

`vsr/architecture-cli-hotspot-split`

## Suggested Worktree

`architecture-cli-hotspot-split`

## Dependencies

- Read `apps/cli/AGENTS.md` and `tests/unit/AGENTS.md`.
- Inspect `apps/cli/cli_main_impl.py` call graph before moving code.

## Write Scope

- Primary: `apps/cli/cli_main_impl.py` and new `apps/cli/cli_main_*.py`
  helper modules.
- Tests: targeted `tests/unit/cli/**` updates only when needed.
- Do not mix provider adapter, storage, evidence, or gateway e2e splits into
  this branch.

## Deliverables

- Extract one cohesive command family or setup family out of
  `cli_main_impl.py`.
- Keep imports and public CLI behavior compatible.
- Preserve or improve targeted unit coverage.
- Update `docs/agent/repo-map.md` and the scorecard only if the hotspot status
  materially changes.

## Validation

- `make agent-report CHANGED_FILES="apps/cli/... tests/unit/cli/..."`
- Targeted CLI unit tests for the moved command family.
- `make agent-fast-gate`

## Handoff

Completed 2026-05-24:

- `apps/cli/cli_main_init_prompts.py` owns init prompt copy, choices, and
  question helpers.
- `apps/cli/cli_main_init_runtime.py` owns interactive init runtime and
  bootstrap persistence.
- `apps/cli/cli_main_provider_herd_commands.py` owns init/provider/herd command
  runners.
- `apps/cli/cli_main_learning_commands.py` owns facts, reflect, wake stream,
  and root help command helpers.
- `apps/cli/cli_main_impl.py` now stays focused on Typer registration and
  `main()`, with a small compatibility delegation layer for existing private
  helper patch points.

Completed 2026-05-25:

- `tests/unit/cli/shell_test_support.py` owns shared shell test fixtures,
  capture console rendering, and local web-page stub helpers.
- `tests/unit/cli/test_shell_tool_progress.py` owns tool progress, stream-text,
  and tooltrace rendering coverage.
- `tests/unit/cli/test_shell_startup_entry.py` owns startup, pending-entry,
  opener, shell entry, state-focus notice, and startup transition coverage.
- `tests/unit/cli/test_shell_visual_layout.py` owns history-row width,
  growth-row styling, elephant mark layout, and shell-frame branding coverage.
- `tests/unit/cli/test_shell_status_banner.py` owns Personal Model banner,
  skill-affinity, frozen-state status, status-bar usage, growth progress, and
  diff palette coverage.
- `tests/unit/cli/test_shell_progress_frame.py` owns live turn progress-frame
  coverage for tool activity, streaming response, reasoning, compaction, and
  recall rendering.
- Current shell UI/state contract drift was reconciled in the remaining
  `test_shell.py` tests so the suite can be validated in smaller chunks.
- `tests/e2e/cli/cli_surface_test_base.py` owns shared CLI e2e process,
  provider stub, web stub, TTY runner, and terminal rendering fixtures.
- `tests/e2e/cli/test_cli_surface_provider.py` owns provider bootstrap,
  persisted secret, and embedding provider CLI coverage.
- `tests/e2e/cli/test_cli_surface_herd.py` owns herd create/list/use/current,
  delete, canonical state, and provider-failure recovery coverage.
- `tests/e2e/cli/test_cli_surface_facts.py` owns personal-model facts list and
  delete coverage.
- `tests/e2e/cli/test_cli_surface_skills.py` owns launcher skill view,
  runtime skill install provenance, and non-interactive skill guidance coverage.
- `tests/unit/cli/test_main_wizard.py` owns wizard, parser, interactive setup,
  and growth-session selection coverage. Wizard menu and text-prompt coverage
  lives in `tests/unit/cli/test_main_wizard_menu.py`.
  `tests/unit/cli/test_main.py` is now a focused init/status/question-copy
  suite.
- `tests/unit/cli/runtime_cognition_test_base.py` owns shared runtime-cognition
  fixture construction.
- `tests/unit/cli/test_runtime_cognition_operator.py` owns operator profile,
  personal model update, elephant lifecycle, and checkpoint surface coverage.
- `tests/unit/cli/test_runtime_cognition_skills.py` owns skill index,
  disclosure reason, catalog steady-up, shelf reuse, skill-hub listing, source
  search, remote-source inspect, and builtin skill inspect coverage.

Remaining work is no longer line-limit-driven for `cli_main_impl.py`, the main
shell regression file, the main CLI e2e surface, the wizard menu slice, or the
runtime-cognition skill slice. The next cleanup should split another
context/continuity family from `tests/unit/cli/test_runtime_cognition.py`, or
reduce the remaining setup private-helper patch points in
`tests/unit/cli/test_main_wizard.py`, before removing CLI private-helper
delegation layers.

## Guardrails

- Behavior-preserving refactor only.
- No broad formatting churn.
- Do not reduce CLI command coverage.
