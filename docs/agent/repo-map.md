# Repo Map

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                         apps/                            │
│  cli    api    gateway    dashboard    site    macos     │
└──────┬───┬───────┬──────────┬─────────┬────────┬───────┘
       │   │       │          │         │        │
       ▼   ▼       ▼          │         │        ▼
┌──────────────────────────────┼─────────┼─────────────────┐
│              packages/       │         │                  │
│                              │         │                  │
│  ┌─────────┐  ┌─────────┐   │         │  ┌───────────┐  │
│  │ kernel  │  │ context │   │         │  │ learning  │  │
│  │ state   │  │ sem_idx │   │         │  │ curiosity │  │
│  │ evidence│  └─────────┘   │         │  │ growth    │  │
│  └────┬────┘                │         │  │ experience│  │
│       │                     │         │  │ continuity│  │
│       ▼                     │         │  │ understand│  │
│  ┌──────────────────────────┤         │  └───────────┘  │
│  │  contracts  capabilities │         │                  │
│  └──────────────────────────┤         │  ┌───────────┐  │
│       │                     │         │  │   infra   │  │
│       ▼                     │         │  │ storage   │  │
│  ┌──────────┐  ┌─────────┐ │         │  │ models    │  │
│  │  tools   │  │  skills │ │         │  │ auth      │  │
│  └──────────┘  └─────────┘ │         │  │ embeddings│  │
│                             │         │  │ telemetry │  │
│                             │         │  │ observab. │  │
└─────────────────────────────┘         │  └───────────┘  │
                                        │                  │
                              build only ▼                  │
                           ┌──────────────┐                │
                           │  site/dash   │                │
                           │  (frontend)  │                │
                           └──────────────┘                │
```

Direction: apps → packages (never reversed). Packages integrate through `contracts/` and `capabilities/`.

## Core Packages

| Package | Purpose | Entry Module | Depends On |
|---------|---------|-------------|------------|
| `packages/contracts` | Shared records, schemas, IDs. Dependency-free foundation. | `contracts/inventory.py` | (none) |
| `packages/kernel` | Runtime lifecycle: Source event ingestion, State resolution, Episode/Loop/Step, persistence, reflection triggers. | `kernel/runtime.py` | contracts, state, evidence, context, tools, storage |
| `packages/state` | Elephant State management, canonical projection, policy. | `state/canonical.py` | contracts, storage |
| `packages/evidence` | Unified recall, reflection, semantic indexing, personal model learning support. | `evidence/runtime.py` | contracts, storage, embeddings, semantic_index |
| `packages/storage` | SQLite persistence, migrations, repository pattern. | `storage/repository.py` | contracts |

## Context & Assembly

| Package | Purpose | Entry Module | Depends On |
|---------|---------|-------------|------------|
| `packages/context` | Context window assembly for generation prompts. | `context/__init__.py` | contracts, state, evidence |
| `packages/semantic_index` | Vector embedding search and indexing. | `semantic_index/__init__.py` | contracts, embeddings |

## Feature Packages

| Package | Purpose | Entry Module | Depends On |
|---------|---------|-------------|------------|
| `packages/tools` | Tool registration and execution runtime. | `tools/__init__.py` | contracts, capabilities |
| `packages/skills` | Skill packages and crystallization. | `skills/__init__.py` | contracts, capabilities |
| `packages/curiosity` | Proactive question generation. | `curiosity/__init__.py` | contracts, evidence |
| `packages/growth` | Personal model evolution. | `growth/__init__.py` | contracts, evidence, state |
| `packages/understanding` | Comprehension and reasoning. | `understanding/__init__.py` | contracts |
| `packages/experience` | Experience tracking and trajectory. | `experience/__init__.py` | contracts, storage |
| `packages/continuity` | Session continuity and resume. | `continuity/__init__.py` | contracts, state, storage |
| `packages/reflect` | Reflect runner, evidence packets, prompt fragments, context compression, deterministic trajectory signals, feature registry, and skill optimization candidate lifecycle for background agents. | `reflect/__init__.py`, `reflect/runner.py`, `reflect/context_compression.py`, `reflect/features/` | storage port, skills surface |

## Infrastructure Packages

| Package | Purpose | Entry Module |
|---------|---------|-------------|
| `packages/models` | Model provider adapters (OpenAI, Anthropic, etc.). | `models/__init__.py` |
| `packages/auth` | Authentication and provider credential management. | `auth/__init__.py` |
| `packages/embeddings` | Vector embedding providers. | `embeddings/__init__.py` |
| `packages/capabilities` | Inter-package capability contracts. | `capabilities/__init__.py` |
| `packages/gateway_core` | Message routing primitives, delivery-agnostic proactive ask, and cron delivery eligibility. | `gateway_core/__init__.py` |
| `packages/cron` | Scheduled task execution. | `cron/__init__.py` |
| `packages/harness` | Test harness utilities. | `harness/__init__.py` |
| `packages/observability` | OpenTelemetry setup, structured logs, traces, and metrics instrumentation. | `observability/__init__.py` |
| `packages/operator` | App-neutral operator support: daemon/service management, Typer command execution, terminal stack/UI primitives, terminal cards, and wizard helpers. | `operator/__init__.py`, `operator/typer_support.py`, `operator/shell_stack.py`, `operator/shell_ui.py`, `operator/cli_cards.py`, `operator/wizard.py` |
| `packages/security` | Security policies and sandboxing. | `security/__init__.py` |
| `packages/telemetry` | Observability and metrics. | `telemetry/__init__.py` |

## Apps

| App | Purpose | Packages Consumed |
|-----|---------|-------------------|
| `apps/cli` | CLI-first user interface (largest app). | kernel, state, evidence, context, tools, skills, models, storage, telemetry |
| `apps/api` | REST API service. | kernel, state, evidence, auth, storage |
| `apps/gateway` | Message gateway (Discord, DingTalk, Lark, etc.). | kernel, gateway_core, auth, models |
| `apps/dashboard` | Web UI for state inspection. | (frontend, calls API) |
| `apps/site` | Documentation site. | (frontend, static build) |
| `apps/macos` | Native macOS desktop shell and platform packaging. | (SwiftUI/AppKit shell, starts and calls API) |
| `apps/reflect` | Backward-compatible import facade for package-owned Reflect runner and features. | reflect |
| `apps/learning_agents` | Backward-compatible background learning worker shim. | reflect, storage |

## Tests

| Layer | Directory | Purpose |
|-------|-----------|---------|
| Unit | `tests/unit/` | Isolated package logic. |
| Integration | `tests/integration/` | Cross-package interactions. |
| Scenarios | `tests/scenarios/` | Business-logic narratives. |
| E2E | `tests/e2e/` | Full-stack app surface tests. |
| Agent | `tests/agent/` | Harness contract tests. |

## Deploy

| Directory | Purpose |
|-----------|---------|
| `deploy/docker/` | Container packaging. |
| `deploy/systemd/` | Systemd service units. |
| `deploy/cloud/` | Cloud deployment configs. |

## Agent Harness

| File | Purpose |
|------|---------|
| `tools/agent/repo-manifest.yaml` | Required repo paths, read-first docs, and canonical agent commands. |
| `tools/agent/task-matrix.yaml` | Changed-file to skill and validation routing. |
| `tools/agent/skill-registry.yaml` | Agent skill inventory and required context surfaces. |
| `tools/agent/context-map.yaml` | Surface ownership map used by reports and context audits. |
| `tools/agent/public-contracts.yaml` | Executable inventory for public HTTP routes, CLI commands, shell commands, gateway commands, package exports, storage schema, release contracts, surface validation contracts, and tool schemas. |
| `tools/agent/structure-rules.yaml` | Directory structure contract. |

## Authoritative Design

The canonical system design lives at `docs/system-design/system-layer-model.md`. All code must converge to it — not to patterns found in surrounding code.

Runtime budget ownership for prefix cache, projection compaction, embedding
backfill, tool result pruning, loop checkpoints, and background learning lives
in `docs/agent/runtime-resource-ownership.md`.

## Known Hotspots

- `tests/e2e/api/test_api_surface.py` — public API e2e suite; internal
  dashboard/operator coverage lives in `tests/e2e/api/test_api_surface_dashboard.py`,
  dashboard gateway/MCP/skill shelf/operator discovery coverage lives in
  `tests/e2e/api/test_api_surface_dashboard_ops.py`,
  provider onboarding/default-provider/transport coverage lives in
  `tests/e2e/api/test_api_surface_providers.py`, and shared fixtures live in
  `tests/e2e/api/api_surface_test_base.py`
- `tests/e2e/gateway/test_gateway_adapter.py` — core gateway e2e adapter suite; CLI,
  Telegram, Discord setup/describe, Discord runtime/delivery
  (`test_gateway_adapter_discord_runtime.py`), Feishu setup, Feishu event
  formatting, Feishu runtime delivery (`test_gateway_adapter_feishu_runtime.py`),
  Feishu control, Feishu long-connection bootstrap/status, and Feishu async
  runtime (`test_gateway_adapter_feishu_async_runtime.py`) slices are separate suites;
  Weixin/WeCom control and
  serialization coverage lives in
  `tests/e2e/gateway/test_gateway_adapter_weixin_wecom.py`, chat-bot identity
  plus webhook delivery coverage lives in
  `tests/e2e/gateway/test_gateway_adapter_chat_webhook.py`; Telegram service
  dispatch and cross-adapter web-app mounting coverage lives in
  `tests/e2e/gateway/test_gateway_adapter_services.py`
- `tests/unit/cli/test_shell.py` — large CLI shell regression suite; tool
  progress coverage lives in `tests/unit/cli/test_shell_tool_progress.py`, and
  startup/pending-entry coverage lives in
  `tests/unit/cli/test_shell_startup_entry.py`; opener, state-focus onboarding,
  startup notices, transition timing, queued first-turn gates, and startup prime
  sentinel coverage lives in `tests/unit/cli/test_shell_startup_state_focus.py`;
  visual-layout coverage lives in `tests/unit/cli/test_shell_visual_layout.py`;
  status/banner coverage lives in `tests/unit/cli/test_shell_status_banner.py`;
  progress-frame coverage
  lives in `tests/unit/cli/test_shell_progress_frame.py`; command palette,
  learning notices, conversational command routing, skill search/enable/install,
  provider/model wizard cancel, prompt style, live composer, and command palette
  height coverage lives in `tests/unit/cli/test_shell_command_surface.py`
- `tests/unit/cli/test_runtime_cognition.py` — broad CLI runtime cognition
  suite now focused on context projection, frozen snapshot, and compaction
  behavior; durable recall, continuity, workspace rule discovery, opening reply,
  next-episode continuation, and state-focus runtime status coverage lives in
  `tests/unit/cli/test_runtime_cognition_recall.py`; operator/profile/elephant
  lifecycle coverage lives in `tests/unit/cli/test_runtime_cognition_operator.py`,
  with shared fixtures in `tests/unit/cli/runtime_cognition_test_base.py`; skill
  catalog, source search, shelf reuse, and builtin skill inspect coverage lives
  in `tests/unit/cli/test_runtime_cognition_skills.py`
- `tests/unit/test_builtin_tools_v2.py` — broad built-in tool contract suite
  covering model-visible schemas, PM tools, skills, sub-agents, diary, todo,
  messaging, and clarify behavior; file/terminal/process/code-execution
  coverage lives in `tests/unit/test_builtin_tools_file_code.py`, with shared
  fixtures in `tests/unit/builtin_tools_test_support.py`
- `tests/e2e/cli/test_cli_surface.py` — CLI e2e setup, launcher, wake/grow,
  and shell-entry proving surface; provider/bootstrap, herd management, facts,
  and skills coverage lives in focused sibling modules with shared fixtures in
  `tests/e2e/cli/cli_surface_test_base.py`
- `tests/integration/models_auth/test_openai_compatible_provider.py` —
  OpenAI-compatible provider request/core chat coverage; reasoning, Responses
  API, and HTTP fallback coverage lives in focused sibling modules with shared
  fixtures in
  `tests/integration/models_auth/openai_compatible_provider_test_base.py`
- `tests/integration/models_auth/test_models_auth_integration.py` —
  models/auth core runtime, secret/profile, model request, MCP tool request, and
  auth persistence coverage; environment/provider discovery, Codex/Copilot API
  list behavior, live catalog fallback, Ollama metadata, models.dev fallback,
  Claude Code credentials, Copilot ACP process, and compatible endpoint profile
  input coverage lives in
  `tests/integration/models_auth/test_models_auth_discovery.py`
- `tests/integration/tools_skills/test_tools_and_skills_runtime.py` — tool
  runtime, approval, manifest, and MCP registration integration coverage;
  skill loader, scope/dependency, SkillHub, provenance, and builtin catalog
  coverage lives in `tests/integration/tools_skills/test_skills_runtime.py`
- `tests/unit/cli/test_main_wizard.py` — parser/setup/herd/facts/brain,
  elephant creation, and growth-session unit suite split from
  `tests/unit/cli/test_main.py`; init setup, birth wizard, elephant creation,
  interactive shell handoff, and growth-session resolution coverage lives in
  `tests/unit/cli/test_main_setup_flow.py`; wizard menu and text-prompt coverage
  lives in `tests/unit/cli/test_main_wizard_menu.py`
- `apps/cli/cli_main_impl.py` — CLI registration/orchestration entrypoint
  below the line limit but still a compatibility patch-point surface
- `apps/api/api_runtime_console_ops.py` — API console command orchestration
- `apps/api/api_runtime_gateway_ops.py` — API dashboard gateway orchestration;
  static service catalog and Weixin QR helpers live in focused sibling modules
- `apps/gateway/gateway_main_impl.py` — gateway lifecycle and adapter orchestration
- `apps/cli/shell_composer.py` — shell prompt assembly
- `packages/evidence/runtime.py` — evidence runtime
- `packages/kernel/runtime_impl.py` — kernel runtime implementation
- `packages/storage/repository_system_methods.py` — repository method
  coordination
- `packages/models/providers/openai_compatible.py` — provider adapter; response
  parsing has moved to a focused support module, but request shaping and
  transport/auth lifecycle tests still make this a high-blast-radius surface
- `tools/agent/scripts/agent_gate.py` — harness command entrypoint; public
  contract rendering/validation lives in `agent_public_contracts.py`, and
  reset/app-boundary/silent-exception scorecard scanning lives in
  `agent_scorecard_scans.py`

No Python line-limit allowlist entries remain, but these files are still the
highest blast-radius places to touch. Changes to hotspots must read the nearest
local `AGENTS.md` first, keep refactors behavior-preserving unless a task card
says otherwise, and run the targeted suite before broad gates.
