# Understanding Legacy Design Cleanup

## Current State

The product source of truth is the Personal-Model-first Understanding System:
Personal Model Facts and Questions, Elephant State, Episodes / Loops / Steps,
SemanticIndexEntry, and LearningJob.

The legacy implementation exposed or referenced older memory surfaces:

- support records: `Record`, `Grounding`, `MemoryEntry`, `ReflectionProposal`
- intermediate learning rows: `Observation`
- profile-shaped user and relationship records
- structured-turn `MemoryRecord` evidence copies
- no-op repository methods for removed tables

These objects make the architecture look like it has multiple owners for
conversation history, evidence, and durable understanding.

## Decisions From Alignment

- `tool.personal_model.search` keeping `mode=auto|inventory` is intentional.
  Inventory is the claim/topic map and should remain model-visible.
- Personal Model facets should be documented as the topic-key naming layer under
  the four lenses. Facets reduce drift; they are not a profile survey.
- `tool.conversation.search` should search history through Step and Episode
  material, with SemanticIndexEntry as the retrieval index. It should not search
  `MemoryRecord`.
- Skill affinities are valid Personal Model facts under
  `world.skills.affinity.*`. Dashboard may project them separately because they
  are inspectable facts, not hidden skill rankings.
- Elephant voice ownership must be file-first. `ELEPHANT.md` is the authored
  source of the elephant's own voice; State owns structured runtime continuity
  and may cache the latest text, but it must not be the authoritative editor
  surface for the voice paragraph. Episode-open prompt assembly reads
  `ELEPHANT.md`, strips framework metadata, and freezes that snapshot for the
  Episode. Edits during an Episode take effect on the next Episode unless the
  operator explicitly refreshes by starting a new Episode.

## Target

There is one history/evidence owner:

- user input, assistant replies, tool calls, tool results, and recall support are
  Steps;
- Episode summaries support time-window discovery;
- SemanticIndexEntry indexes Step, Episode, and Fact text;
- Fact provenance points to source Episode ids, then back to Steps.

There is one durable understanding owner:

- active, retired, disputed, or deleted Personal Model Facts;
- proactive Questions bound to a lens/topic.

There is no compatibility requirement for legacy memory, record, grounding,
observation, proposal, user-card, or relationship-memory shapes.

## Cleanup Todo

- [x] Remove silent legacy write paths that appear to succeed but persist
  nothing.
- [x] Remove legacy support contracts from the public contract surface:
  `Record`, `Grounding`, `MemoryEntry`, `ReflectionProposal`, and
  `Observation`.
- [x] Remove `MemoryRecord` structured-turn evidence generation and make Step
  records sufficient for recall, audit, and background learning packets.
- [x] Slim repository and dashboard/API projections so removed tables and empty
  evidence slots disappear.
- [x] Document facets in README / Blog / Paper-facing system docs.
- [x] Remove `MemoryCapability` / `MemoryRuntime` from the kernel dependency
  graph; kernel recall should request Step / Episode / SemanticIndex evidence
  directly.
- [x] Replace `RecallEvidence.memory_id`, `ContextBundle.memory_ids`, and
  loop `active_memory_ids` with Step / Episode / SemanticIndex provenance.
- [x] Remove `UserProfileProjection` and `RelationshipProjection` as durable
  Personal Model owners; derive optional rendered views from PM facts and State.
- [x] Shrink root `__init__.py` exports so package roots expose only current
  README / Blog / Paper / system-design contracts.
- [x] Auto-drop old local storage tables during bootstrap because
  backward-compatible migration is out of scope.
- [x] Auto-reset same-version local storage schema drift, including old
  SemanticIndex columns such as `source_record_id`, instead of adding reader
  compatibility aliases.
- [x] Remove dashboard/operator `memoryLayers`, `DashboardMemoryLayer`,
  `MemoryGraphPage`, and `memory-graph` section names from the public surface.
- [x] Rename release/scenario/test tracks from `tests.unit.memory` and
  `tests/scenarios/memory` to recall-focused fixtures.
- [x] Rename prompt/runtime helper wording from memory capability/tool labels to
  recall and understanding labels.
- [x] Ensure Episode close paths, including CLI `/clear`, pass the semantic
  summary indexer so closed Episode summaries join Step and Fact recall
  indexing without a second evidence owner.
- [x] Rename remaining public/test `source record` wording to source item /
  Step/Episode/Fact provenance so SemanticIndex no longer reads as Record-based.
- [x] Replace the legacy mixed identity ownership path where prompt text came
  from `State.elephant_identity_text` while dashboard showed `ELEPHANT.md`.
  Runtime context now overlays `LoadedProfile` with the authored file before
  prompt-contract assembly.
- [x] Fix old API/dashboard Episodes that carried `state_id=state:<elephant>`
  but an empty `elephant_id`; context assembly now resolves the elephant id from
  either field before reading `ELEPHANT.md`.
- [x] Auto-refresh the exact old generated identity seed when encountered so
  legacy bland defaults pick up the livelier initial elephant voice without
  overwriting custom-authored files.
- [x] Verify episode identity, compress/reflect, and frozen-prefix behavior:
  identity prompt text comes from the authored `ELEPHANT.md` snapshot at Episode
  open, high-usage compress writes a reference summary back into the frozen
  prefix while keeping the recent tail, and episode-open prefix freezing now
  starts before the first user loop.
- [x] Remove pre-close learning scheduling from `/clear`, `/exit`, gateway
  `/clear`, and gateway idle-close paths so the unified Episode close path owns
  the `episode_close` reflect job instead of being hidden by an earlier
  `clear` / `exit` job deduped on the same Episode.
- [x] Review the final public contract surface against README / Blog / Paper /
  system-design commitments and confirm no legacy design remains exposed.

## Current Public-Contract Review Findings

Status: final clean is complete for the prioritized kernel, provenance,
projection-owner, root-export, storage reset, same-version schema drift reset,
recall/API, CLI slash-command, dashboard/operator, scenario, test-contract, and
file-authored elephant identity items.

Final review result:

- `KernelDependencies` depends on `recall`, not `memory`; kernel callers pass
  Step / Episode / SemanticIndex-backed recall evidence, not memory objects.
- `RecallEvidence` provenance is Step / Episode / SemanticIndex / Fact
  provenance. `memory_id`, `memory_ids`, and `active_memory_ids` are removed
  from the current apps/packages Python contract.
- `UserProfileProjection` and `RelationshipProjection` are not durable owners.
  Runtime user/relationship views are derived from active PM facts and State.
- CLI/API inspection uses recall evidence surfaces (`/recall`,
  `/episodes/{id}/recall`, `/episodes/{id}/recall/evidence`,
  `/episodes/{id}/recall/search`) and no longer exposes memory mutation
  endpoints.
- Local storage bootstrap automatically drops old legacy tables when found; the
  clean schema is no longer blocked by `canonical_user_cards`,
  `canonical_relationship_memories`, or `memory_entries`.
- Local storage bootstrap also resets same-version schema drift to the current
  clean schema. The dashboard failure caused by
  `semantic_index_entries.source_record_id` is fixed by rebuilding storage with
  `source_id`, not by teaching readers a second column name.
- Step indexing runs when `KernelStepRecorder.record(...)` persists each Step;
  Fact indexing runs immediately after successful `tool.personal_model.update`
  writes; Episode summary indexing runs through the unified close path, including
  shell exit and `/clear`.
- Episode system prefixes freeze at episode open, including runtime path context
  and the sanitized `ELEPHANT.md` voice snapshot. Later turns append
  role-preserved history outside the frozen prefix. High-usage compress replaces
  older history with an Episode resume reference summary in the frozen prefix and
  preserves the recent tail for the next loop.
- Root package exports expose current public contracts only; internal builders,
  projections, persistence helpers, and removed memory facades are not exported
  from package roots.
- Dashboard/operator surfaces no longer expose `memoryLayers` or memory graph
  route names. The root visual page is the Personal Model map over the
  `personal-models` dashboard section.
- Release scenario fixtures are recall fixtures, not a hidden `packages/memory`
  package contract.
- The only remaining exact legacy table names in production Python are the
  bootstrap drop-list entries that remove those tables from local databases.

## Implementation Notes

The cleanup now removes root contract exports for `Record`, `Grounding`,
`MemoryEntry`, `ReflectionProposal`, and `Observation`; removes the no-op
repository methods; stops reconciliation from creating structured-turn memory
evidence; deletes the unused legacy evidence helper modules; removes old user
card and relationship-memory tables from the clean SQLite schema; and removes
dashboard/API empty slots and fallback rendering for records, groundings,
memory entries, observations, reflection proposals, and component records.

Runtime recall candidates are `RecallEvidence` backed by Steps, Episodes,
Facts, or SemanticIndex entries, so the adapter surface no longer reads like a
second persistent evidence owner. Conversation search keeps searching history,
but it does so through Step/Episode/SemanticIndex provenance rather than a
duplicate MemoryRecord path.

The final sweep also removed internal compatibility names that made the code
look like it still had a record-backed side path: context assembly uses
`recall_items`, operator surfaces use `evidence_items`, dashboard trace helpers
read source payloads from Step payload refs, the runtime persistence Step action
is `write_state`, and `KernelOutcome` no longer exposes memory aliases.

The final public contract review is clean against the README / Blog / Paper /
system-design commitments:

- public `packages.contracts.__all__` exposes PersonalModel, State, Episode,
  Loop, Step, SemanticIndexEntry, Fact, OpenQuestion, provider config, and
  active provider selection only;
- `tool.conversation.search` reaches history through Step / Episode recall and
  SemanticIndexEntry metadata; Step sources are indexed as `step:{step_id}`, not
  `record:{step_id}`;
- `tool.personal_model.search` keeps `mode=auto|inventory`; facets are documented
  as topic-key naming under the four lenses;
- embedding query vectors are computed at search time only. They are used for
  ranking and are not themselves persisted as history;
- reconciliation now emits runtime reconciliation signals and durable events
  only, with no structured-turn evidence side path;
- legacy table names appear only in the automatic bootstrap drop list and
  forbidden-schema tests.

Validation used for the final review:

- `python -m py_compile` over changed apps/packages/tests Python files passed.
- `pytest tests/unit/contracts/test_contract_inventory.py tests/unit/contracts/test_canonical_bundles.py tests/integration/storage_system_layers/test_schema.py tests/integration/storage_system_layers/test_repository.py tests/integration/kernel/test_turn_lifecycle.py tests/integration/harness/test_reflection_offpath.py tests/unit/context/test_context_runtime.py tests/unit/cli/test_runtime_cognition.py tests/unit/cli/test_runtime_turns.py tests/unit/kernel/test_context_compaction.py tests/unit/kernel/test_generation_context_projection.py tests/unit/kernel/test_runtime_support_budgets.py tests/unit/profile/test_state_exports.py tests/unit/profile/test_canonical_state.py tests/unit/personal_state/test_api_state_runtime.py tests/unit/recall/test_recall_scenarios.py tests/scenarios/continuity/test_continuity_scenarios.py tests/agent/test_system_layer_reset_matrix.py tests/e2e/api/test_api_surface.py::APISurfaceE2ETest::test_internal_dashboard_projection_surfaces_canonical_runtime_and_evidence tests/e2e/api/test_api_surface.py::APISurfaceE2ETest::test_operator_dashboard_projection_is_empty_without_runtime_state -q`
  passed: 154 tests, 75 subtests.
- `pytest tests/unit/cli/test_runtime_cognition.py::CliRuntimeCognitionTest::test_start_fresh_episode_indexes_closed_episode_summary tests/unit/evidence/test_episode_summary_indexer.py tests/integration/semantic_index/test_unified_recall_end_to_end.py tests/unit/test_personal_model_lifecycle.py tests/integration/storage_system_layers/test_schema.py -q`
  passed: 46 tests, 14 subtests.
- `npm --prefix apps/dashboard run typecheck` passed.
- Local dashboard verification passed after bootstrap reset:
  `GET /v1/internal/dashboard/personal-models` returned 200 through both
  `127.0.0.1:4174` and `127.0.0.1:8000`.
- `git diff --check` passed.
- `rg` public-contract review over apps/packages Python found no current
  `MemoryRecord`, `StructuredTurnRecord`, `MemoryRuntime`, `MemoryOperator`,
  `MemoryCapability`, memory governance endpoints, memory provenance fields, or
  user/relationship projection owners. The only hit is `memory_entries` in the
  bootstrap legacy-table drop list.

## Risk

The remaining risk is naming that uses the product word "memory" generically in
marketing/docs or built frontend artifacts. That is not a second durable design:
the implementation owner is PM facts, State, Episodes, Steps, SemanticIndex, and
LearningJob.
