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

## Infrastructure Packages

| Package | Purpose | Entry Module |
|---------|---------|-------------|
| `packages/models` | Model provider adapters (OpenAI, Anthropic, etc.). | `models/__init__.py` |
| `packages/auth` | Authentication and provider credential management. | `auth/__init__.py` |
| `packages/embeddings` | Vector embedding providers. | `embeddings/__init__.py` |
| `packages/capabilities` | Inter-package capability contracts. | `capabilities/__init__.py` |
| `packages/gateway_core` | Message routing primitives. | `gateway_core/__init__.py` |
| `packages/cron` | Scheduled task execution. | `cron/__init__.py` |
| `packages/harness` | Test harness utilities. | `harness/__init__.py` |
| `packages/operator` | Daemon/service management. | `operator/__init__.py` |
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
| `apps/reflect` | Feature-composable background reflect agents. | evidence, tools, storage |
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

## Authoritative Design

The canonical system design lives at `docs/system-design/system-layer-model.md`. All code must converge to it — not to patterns found in surrounding code.

## Known Hotspots

- `apps/cli/cli_main_impl.py` — CLI shell orchestration (large, complex)
- `apps/cli/shell_composer.py` — shell prompt assembly
- `packages/evidence/runtime.py` — evidence runtime (large)
- `packages/kernel/runtime_impl.py` — kernel runtime implementation
- `packages/storage/repository_system_methods.py` — repository methods (large)
- `packages/models/providers/openai_compatible.py` — provider adapter (large)

Hotspot files have line-limit allowlisting in `agent_gate.py`. Changes to hotspots must read the nearest local `AGENTS.md` first.
