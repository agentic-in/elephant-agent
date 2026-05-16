# Context Management

This document defines how the harness exposes the minimum useful context for a task instead of forcing agents to read the entire `docs/agent/` tree.

## Why This Exists

- `AGENTS.md` should stay short and navigational.
- `docs/agent/*` should stay canonical, but the set is large enough that agents need a task-first read path.
- `make agent-report CHANGED_FILES="..."` should resolve not only validation, but also the minimum context pack for the task.

## Disclosure Layers

- `L0` entrypoint
  - `AGENTS.md`
  - `docs/agent/README.md`
- `L1` task contract
  - resolved primary skill from `tools/agent/skill-registry.yaml`
  - loop mode and execution-plan guidance for the active task
  - the `read_first` docs referenced by the matched skill
- `L2` surface context
  - impacted code partitions from `surface_paths` in `tools/agent/context-map.yaml`
  - only docs for the impacted surfaces from `surfaces` in `tools/agent/context-map.yaml`
  - resolved by matching changed file paths to surface zones
- `L3` hotspot supplements
  - nearest local `AGENTS.md` files for changed hotspot trees
- `L4` durable loop context
  - execution plans, ADRs, and tech debt only when the task needs resumable or unresolved context

## Context Pack Flow

1. Resolve changed files through `make agent-report CHANGED_FILES="..."` so the harness can emit the active skill, surfaces, and validation commands.
2. Match changed files to task rules from `tools/agent/task-matrix.yaml` to find the primary skill.
3. Pull the skill `read_first` references from `tools/agent/skill-registry.yaml`.
4. Match changed files to `surface_paths` and add surface-specific docs from `tools/agent/context-map.yaml`.
5. Add nearest local `AGENTS.md` files for hotspot paths when applicable.
6. Add resume references (plans, debt) only when the task becomes long-horizon or unresolved.

## Source of Truth

- Human-readable policy: this document and `docs/agent/`
- Surface routing and code partitions: `tools/agent/context-map.yaml`
- Skill ownership: `tools/agent/skill-registry.yaml`
- Task classification: `tools/agent/task-matrix.yaml`
- Runtime assembly: `tools/agent/scripts/agent_gate.py`
- Validation: `make agent-validate`

## Default Budget

- The default `agent-report` output stays compact.
- Prioritize: Start Here → Primary skill → Smallest useful Must Read set → Surfaces.
- Full surface details and resume references are available through `--context-detail full` or `--format json`.
- Execution-plan resume references belong in the output only when the resolved task still needs long-horizon loop state.
- Debt registers and index-style docs should not be injected unless the current task actually needs them.

## Maintenance Rules

- Do not duplicate full guidance into the context map; point to the canonical doc or local `AGENTS.md`.
- Keep code partition patterns in `surface_paths`; do not hard-code a second surface-to-path map in scripts.
- Keep the context pack task-first and minimal; if a reference is almost always skipped, remove it.
- When a new surface, skill, or local rule is added, update `tools/agent/context-map.yaml` in the same change.
- If the context pack and the canonical docs disagree, fix the canonical doc and the context map together.
- Run `make agent-report AGENT_REPORT_AUDIT=1 CHANGED_FILES="..."` after completing a task to detect surface gaps; if the audit reports drift, update the context map before shipping.
