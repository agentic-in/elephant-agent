# Runtime Resource Ownership

This document is the agent-facing ownership map for memory, context, cache, and
compute-budget behavior. It does not replace the product model in
`docs/system-design/system-layer-model.md`; it names which runtime layer owns the
engineering budget for each resource.

## Ownership Table

| Resource | Owning Layer | Budget Invariant | Persistence Boundary | Primary Validation |
| --- | --- | --- | --- | --- |
| Provider prefix cache | `packages/kernel/generation_context.py` and provider adapters | Cacheable prompt prefix must stay byte-stable within an Episode unless durable Personal Model or Episode-open resume inputs change. | In-process `_prefix_cache`; safe to drop on process restart. | `tests/unit/test_prefix_cache.py`, `tests/unit/kernel/test_generation_context_projection.py` |
| Projection compaction | `packages/context/**`, invoked by `packages/kernel/context_compaction.py` | Compaction is a retry/overflow control, not a hidden truth store. It must preserve source refs and record a Step when it changes the prompt projection. | Context packets and Step metadata; not a new storage table. | `tests/unit/kernel/test_context_compaction.py`, `tests/unit/context/test_context_projection.py` |
| Embedding cache and backfill | `packages/embeddings/**`, `packages/context/projection.py`, `packages/evidence/**` | Foreground turns must prefer cached vectors and queue misses; they must not synchronously reindex all history. | SQLite-backed semantic index plus embedding cache metadata. | `tests/unit/context/test_context_projection.py`, `tests/unit/embeddings/test_runtime.py`, semantic-index integration tests |
| Tool result pruning | `packages/tools/**`, shell/API presentation layers | Tool outputs shown to the model must be bounded and summarized before they can dominate the next prompt. Raw payloads belong in tool artifacts or refs. | Tool artifacts and Step payload refs; not unbounded conversation text. | `tests/unit/test_builtin_tools_v2.py`, `tests/unit/cli/test_shell.py` |
| Loop checkpoint resume | `packages/kernel/loop_checkpoint_support.py`, storage checkpoint methods | A paused loop must resume from durable checkpoints instead of replaying or recomputing previous tool work. | Loop checkpoint tables and Step rows. | `tests/unit/kernel/test_loop_checkpoint_v2.py`, `tests/integration/storage_system_layers/test_loop_checkpoint_hardening.py` |
| Background learning work | `packages/reflect/**`, `apps/learning_worker_runtime.py`, cron/gateway bridges | Background work must be idempotent, observable, and bounded away from foreground turn latency. | Learning job tables, Episode/Step evidence, Personal Model tools. | `tests/integration/storage_system_layers/test_learning_jobs.py`, Reflect integration tests |
| SQLite locking and integrity | `packages/storage/repository_bootstrap_methods.py` | Runtime SQLite connections must enable foreign keys, WAL journaling, and a busy timeout so concurrent foreground/background work fails less often under writer contention. | SQLite connection PRAGMAs; no new schema table. | `tests/integration/storage_system_layers/test_schema.py` |

## Cross-Layer Rules

- Kernel owns turn-level budgeting. App surfaces may request a mode, but they
  must not fork prompt-cache, compaction, or checkpoint semantics.
- Context and evidence layers own retrieval budgets. They may enqueue embedding
  backfill, but foreground retrieval must remain cache-first and bounded.
- Storage owns durability and schema shape. Runtime layers should not add new
  cache tables without updating release and schema posture.
- Apps own operator presentation and lifecycle wiring only. If a cache or
  budget rule must be reused by CLI, API, gateway, or background workers, move it
  to a package or define a narrow app-support bridge.
- Best-effort background paths may continue after failures only when the failure
  is logged, counted, or surfaced through status metadata.

## Change Checklist

Before changing any owner above:

1. Run `make agent-report CHANGED_FILES="..."` and read the nearest
   `AGENTS.md`.
2. Identify whether the change affects foreground turn latency, durable schema,
   prompt bytes, or background-only work.
3. Add or update a focused regression test for the touched budget invariant.
4. For schema, release, or public API changes, update the scorecard roadmap or a
   tech-debt/ADR entry before shipping.
