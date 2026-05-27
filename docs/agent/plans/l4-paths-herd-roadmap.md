# L4 Paths And Herd Roadmap

## Goal

Land the final Elephant Agent product shape where Mother starts from a
correctable Personal Model, designs living Paths across work and life, breaks
them into Steps, coordinates baby elephants through visible Herd assignments,
and returns to the user at Checkpoints where judgment matters.

The target is L4 personal AI for human growth: the system should not merely
execute tasks, carry context, or improve procedures. It should help the person
grow by keeping understanding, direction, evidence, questions, and agency with
the human.

## Scope

- User-facing concepts: Mother, Path, Step, Flow, Checkpoint, Herd, Baby.
- Public positioning across README, site, docs, app copy, and onboarding.
- Path and Step persistence with state-machine semantics.
- Chat-driven and board-driven Step creation, assignment, and state movement.
- Mother planning tools that can propose or apply Paths, Steps, Herd changes,
  and Checkpoints according to the user's trust mode.
- Baby execution integrated with bounded run attempts, heartbeats, cancellation,
  event logs, and resumable outputs.
- Long-running Path support through routines, watchers, and bounded runs rather
  than one endless process.

## Non-Goals

- Replacing the canonical Personal Model. Paths use understanding; they do not
  become the source of durable personal truth.
- Hiding advanced provider, tool, runtime, or cost controls. They move behind
  Settings or Advanced surfaces, but remain inspectable.
- Making babies coordinate through hidden peer-to-peer chatter by default.
  Mother remains the coherence owner.
- Treating all Paths as work projects. Software projects are one Path type, not
  the top-level product metaphor.

## Product Contract

| Concept | Product meaning | Internal owner |
| --- | --- | --- |
| Mother | The coordinating elephant that understands first, plans next, and asks when judgment matters. | Chat runtime, planning tools, Personal Model projection. |
| Path | A long-running direction across work or life. | Storage, API, macOS Paths surface, CLI/dashboard later. |
| Step | A concrete action inside a Path. | Storage, state machine, run assignment, event log. |
| Flow | The visible state board for Steps. | UI projection over Step status and ordering. |
| Checkpoint | A user judgment moment. | Approval/checkpoint queue, chat, board, inbox. |
| Herd | The available baby elephants around Mother and optionally a Path. | Herd runtime, baby registry, assignment policy. |
| Baby | A bounded helper with role, skills, model posture, and runtime limits. | Existing sub-agent runtime plus durable run records. |

## Trust Modes

Keep the user-facing product to two modes:

- **Ask First**: Mother can draft Paths, Steps, Herd assignments, and state moves,
  but asks before applying important changes or taking external action.
- **Trust Mother**: Mother can create Steps, move Flow state, and assign babies
  inside current user boundaries. Risky, destructive, identity-shaping, external,
  or costly moves still become Checkpoints.

Tool permission policy remains separate from these modes. Trust mode controls
planning and product-level orchestration posture; tool policy controls concrete
side effects.

## Flow State Machine

| User label | Internal status | Meaning |
| --- | --- | --- |
| Later | `later` | Not ready yet. |
| Next | `next` | Ready to pick up. |
| Moving | `moving` | Active human or baby work. |
| Checking | `checking` | Waiting for human judgment. |
| Done | `done` | Completed. |
| Stuck | `stuck` | Blocked or needs re-plan. |
| Dropped | `dropped` | Intentionally stopped. |

State transitions must be validated centrally so chat tools, drag-and-drop UI,
batch updates, and baby execution all share the same rules.

## Tracks

- Track A: Public Product Surfaces
  - Update README and public site to preserve the 4-level model while adding
    Mother, Paths, Steps, Checkpoints, and Herds.
  - Add docs that define product language and prevent "project/issue/lead"
    terminology from leaking into primary user-facing copy.
  - Keep providers, tools, and runtime details visible but lower-priority than
    Paths and Personal Model.

- Track B: Storage And API Contracts
  - Add durable tables or records for Paths, Steps, Step events, Checkpoints,
    Path-Herd links, run attempts, routines, and watchers.
  - Add typed repository methods and API routes for Path and Step CRUD, Flow
    moves, assignment changes, Checkpoint responses, and event listing.
  - Add state-machine validation tests before exposing drag-and-drop updates.

- Track C: Mother Planning Tools
  - Add tools for searching, planning, previewing, and applying Path changes.
  - Add proposal objects that can be rendered as one Checkpoint or applied
    directly under Trust Mother mode.
  - Make tools explain which Personal Model claims or questions shaped a Path
    proposal.

- Track D: Baby Execution And Herd Assignment
  - Extend existing sub-agent support into durable Step run attempts.
  - Add heartbeat, cancellation, retry, timeout, and resumable result contracts.
  - Keep baby-to-baby collaboration mediated through Step events and Mother
    routing by default.

- Track E: macOS Product Surfaces
  - Add Paths to the main sidebar.
  - Build Flow board, Step detail, Checkpoint list, and Path-Herd assignment UI.
  - Update onboarding so multiple babies can be selected or created up front.
  - Add the two trust modes in the chat box and onboarding posture.

- Track F: Long-Term Paths
  - Model routines and watchers as scheduled bounded runs.
  - Add resumption summaries and stale-path detection.
  - Keep long-running Paths visible without requiring one agent process to run
    forever.

## Dependencies

- Canonical system model remains `docs/system-design/system-layer-model.md`.
- Step events should reuse or align with Episode / Loop / Step trail semantics.
- Baby execution should build on existing `tool.sub_agents` support, but must not
  rely on process-local async state for durable long-term work.
- Public copy must keep the 4-level model and the Personal Model-first spine.

## Validation

- Public site and docs:
  - `make web-content-check`
  - `make web-typecheck`
  - `make web-build`
- Repo-level docs and contracts:
  - `make agent-validate`
  - `make agent-context-audit CHANGED_FILES="..."`
- Runtime implementation tracks:
  - focused unit tests for state transitions and repository methods
  - API e2e coverage for Path, Step, Checkpoint, and assignment routes
  - macOS smoke or snapshot checks once the Paths UI exists
  - sub-agent integration tests for bounded Step runs, cancellation, and resume

## Exit Criteria

- A user can ask Mother to organize a broad life or work direction into a Path.
- Mother can create or propose Steps based on trust mode.
- The user can drag Steps across Flow states and the same transition rules apply
  as chat tool updates.
- A baby can be assigned to a Step and writes durable events, result, and status.
- Long-running Paths survive app restarts and do not depend on a single endless
  agent process.
- Public README, website, docs, and app copy all use the same vocabulary:
  Mother, Path, Step, Flow, Checkpoint, Herd, Baby.
