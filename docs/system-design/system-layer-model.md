# Elephant Agent Understanding System

## Status

Canonical design reference for Elephant Agent's Personal Model, Elephant Memory Architecture, contextual recall, background learning, and proactive questions.

This document is the implementation mechanism behind the public agency-first,
L4 personal-AI positioning. It intentionally replaces the older memory-note,
component-record, and legacy layer-taxonomy design. New work must converge here
instead of preserving legacy memory surfaces.

## Principle

Elephant Agent is not a memory database. Elephant Agent is an understanding system.

```text
Personal Model = what Elephant Agent currently understands about the person
Fact           = one durable claim, with provenance (source_episode_ids)
Episode        = one conversation window and its execution trace
Step           = one atomic operation inside an episode (the canonical record)
Question       = what Elephant Agent may ask to improve future help
Elephant State      = who this Elephant Agent is and the current conversational context
```

Memory is the product capability that turns lived trace into future judgment.
It is not a single table, a free-form note sink, or a foreground write surface.
In the clean runtime, Elephant Memory Architecture is implemented by five
layers: Personal Model, Elephant State, Episode / Loop / Step Trail,
Contextual Recall, and Background Learning. Recall is the retrieval layer
inside that architecture, not the whole meaning of memory.

## Persistence Model

Canonical understanding tables. No separate provider configuration table belongs
inside the Personal Model persistence layer.

```text
PersonalModel
  ├── Facts (N)              — durable claims (4-lens, topic-keyed)
  └── OpenQuestions (N)      — proactive curiosity

State (Elephant)
  └── Episodes (N)           — conversation windows
        └── Loops (N)        — model interaction rounds
              └── Steps (N)  — atomic ops (user input, model reply, tool call, recall)

SemanticIndexEntry           — vector recall index (source: step or fact)
LearningJob                  — reflect agent task queue (trigger, features, result_json)
```

Relationships:
- `Fact.source_episode_ids` → Episode (provenance — why Elephant Agent believes it)
- `SemanticIndexEntry.source_id` → Step | Fact (what was indexed for recall)
- `LearningJob.episode_id` → Episode (what triggered the reflect)

There is no separate Evidence table, Record table, Grounding table, Memory table,
Observation table, or Reflection Proposal table. Steps ARE the evidence.
Facts carry their own provenance via `source_episode_ids`.

## System Layers

Elephant Agent exposes five product-facing memory/understanding layers:

1. `Matriarch Core / Personal Model` — durable four-lens understanding of the user.
2. `Elephant State` — this Elephant Agent's identity and one natural-language context note.
3. `Episode / Loop / Step Trail` — raw lived trace, execution structure, and provenance.
4. `Contextual Recall` — local lexical/semantic retrieval over Steps and Facts for the current turn or reflect job.
5. `Background Learning` — episode-close, manual, diary, dream, skill, and compaction learning loops.

There is no separate `Memory` table, planner layer, blocker layer, or next-step
layer. The product word "memory" maps across the five layers above.

The elephant-inspired memory model maps to runtime ownership this way:

- `Episodic Memory` lives in Episodes, Loops, and Steps.
- `Semantic Memory` lives in Personal Model claims and their topic/lens structure.
- `Social Memory` lives primarily in World claims and source Steps about people, teams, projects, and relationships.
- `Survival Memory` lives in Journey and Pulse claims about risks, repeated failures, pressure patterns, and recovery paths.
- `Matriarch Core` is the governed Personal Model plus proactive questions and background learning that turn evidence into judgment.

## Personal Model

The Personal Model is the only durable understanding layer. It is made of active claims grouped by four lenses.

### Identity

Who is this person? Durable attributes that do not change quickly.

Use Identity for name, gender, birth date, age, personality type (MBTI etc.), values, decision style, and stable self-descriptions. These rarely change.

### World

What is around this person? Their environment and relationships.

Use World for people, relationships, places, tools, projects, domains, skills, and stable context that is useful across episodes.

### Pulse

How is this person right now? Current state that changes frequently.

Use Pulse for current work focus, current life phase, recent pressure, active projects, mood patterns, and temporary priorities. Pulse changes quickly and should be corrected immediately when the user updates it.

### Journey

What has this person been through? Accumulated experience and history.

Use Journey for lessons learned, past experiences, behavioral patterns observed over time, and growth trajectory.

## Claim

A `Claim` is the smallest unit of Personal Model truth.

```text
Claim
- ref
- lens: identity | world | pulse | journey
- topic
- text
- status: active | retired | disputed
- confidence
- source: user_said | user_corrected | learned
- source_episode_ids
- created_at
- updated_at
```

Only active claims enter the stable prompt. Retired and disputed claims are available for audit but must not shape answers.

## Evidence / Provenance

Evidence is not a separate storage layer. It lives inside the entities that reference it:

- **Fact.source_episode_ids** — which episodes produced this claim
- **Step records** — the raw conversation content (user said X, model replied Y, tool returned Z)
- **SemanticIndexEntry** — vectorized chunks pointing back to steps or facts

When the user asks "why do you believe this?", Elephant Agent traces `Fact.source_episode_ids` → loads those episodes' steps → presents the relevant conversation excerpts.

There is no grounding table, no source-link table, no separate evidence store. Steps ARE the evidence.

Foreground claim writes are indexed immediately into the recall surface. This keeps `tool.personal_model.update` and current-turn recall support on the same path: a newly written claim can be retrieved without waiting for a background curate job.

## Conversation Search

`tool.conversation.search` retrieves past conversation content for the model.

Data sources (in priority order):
1. **SemanticIndexEntry** — vector similarity search over indexed step/fact chunks
2. **Steps** — scan by time range when semantic search is cold or empty
3. **Episodes** — metadata aggregation for `mode=discover`

Search does NOT read a separate "records" or "memory" table. Steps are the canonical conversation record.

## Claim-aware Search

`tool.personal_model.search` is a claim retrieval surface, not a generic vector search over old notes.

Search starts from active claims in the requested Personal Model and optional lens. It then combines several signals and ranks claims, not chunks:

1. fielded topic / claim / evidence matching,
2. Unicode lexical matching and CJK n-grams,
3. weak fuzzy matching for small spelling or character variation,
4. semantic candidates from the durable index,
5. claim confidence as a small tie-breaker,
6. lightweight polarity compatibility or conflict when the query and claim express clear preference stance.

The tool returns a `match_status`:

- `strong_match` — Elephant Agent found enough support to rely on the claim.
- `weak_match` — a relevant candidate exists but should not be over-stated.
- `no_match` — Elephant Agent should not pretend the Personal Model supports the query.

Public search modes keep the model-facing contract small:

- `auto` combines field, lexical, fuzzy, and semantic signals for claim lookup.
- `inventory` returns the lens/topic map and claim counts without claim content.

Strict lookup is expressed through `ref`, `topic`, `status`, and
`include_diagnostics`, not through extra public modes. Semantic ranking remains
an internal signal inside `auto`, and `query_variants` is the preferred way for
the model to pass translated or paraphrased forms.

Global hard-coded alias tables are not part of the design north star. Future
work may generate claim-local search aliases or English pivot text at claim
write time, but active prompt truth remains the claim itself.

Diagnostics may expose scores and signals for debugging. Diagnostics are not stable prompt truth and should not be injected by default.

## Questions

A question is a lens/topic-bound attempt to improve future help.

```text
Question
- ref
- lens
- topic
- text
- reason
- status: open | asked | answered | dismissed
- priority
- sensitivity
```

Questions exist for four reasons only:

1. `gap` — an important lens/topic has no useful claim.
2. `conflict` — evidence contradicts an active claim.
3. `stale_pulse` — a Pulse claim likely expired.
4. `adaptation` — the answer would materially improve how Elephant Agent helps.

Do not ask questions to fill a profile mechanically. Ask because the answer changes future behavior.

Product language should describe this as **proactive curiosity**, not as a question engine. Proactive means Elephant Agent actively maintains understanding at the user's chosen effort level:

- `quiet` — mostly wait and ask rarely
- `balanced` — ask at natural pauses when the answer would help
- `active` — more willing to check in and learn, while still staying optional

Silence is honored at every effort level.

## Elephant State

Elephant State is intentionally small.

```text
ElephantState
- elephant_id
- display_name
- identity_text
- current_context_note
- updated_at
```

`current_context_note` is the State-level continuation note produced by background Episode learning and copied into the next Episode's opening resume snapshot. It is not a per-turn working memory field and must not live in the cacheable frozen prefix. Live commitments belong in Episode, Step, current-turn recall, or explicit task tools when visible execution tracking is needed.

## Foreground Tools

The model-facing tool surface is intentionally small.

### `tool.personal_model.search`

Read current claims and optional evidence.

Use it when the assistant needs to answer what Elephant Agent knows, verify a current claim, inspect evidence before changing understanding, or safely determine that no active claim supports a query.

Important parameters:

- `query` — natural-language lookup text.
- `query_variants` — translated or paraphrased alternatives supplied by the model for cross-language or metaphorical lookup.
- `lens` — optional identity / world / pulse / journey filter.
- `topic` — optional stable topic key.
- `mode` — `auto` for query-driven claim lookup, or `inventory` for the
  lens/topic map.
- `include_evidence` — return evidence summaries for matched claims.
- `include_diagnostics` — return per-claim signals and no-match reasons for debugging.

The tool may return `no_match`. That is a successful safety result, not a failure.

### `tool.personal_model.update`

The only foreground write path for durable understanding.

Actions:

- `remember` — add a new active claim.
- `correct` — replace an existing claim for the same lens/topic.
- `forget` — retire a claim.
- `dispute` — mark a claim as no longer safe to rely on.

Required fields:

- `lens`
- `topic`
- `reason`

`remember` and `correct` also require `text`.

### `tool.personal_model.questions`

Manage proactive questions bound to a lens/topic.

Actions include `list`, `ask`, `answer`, and `dismiss`. Answering a question may create or correct a Personal Model claim.

## Removed Tool Concepts

The following are not part of the clean design:

- `tool.memory.note`
- `tool.memory.review`
- free-form memory notes as Personal Model truth
- source-intent routing exposed to the assistant
- component-record taxonomies as Personal Model categories
- user profile text as source of truth
- style summary as source of truth
- SkillAffinity-style hidden capability ranking as Personal Model truth

## Prompt Projection

Prompt projection has three parts.

### Stable system prefix

Contains only:

1. Elephant identity.
2. Active Personal Model claims grouped by identity, world, pulse, journey.
3. Episode opening resume snapshot, when the previous background learning pass produced one.
4. Tool policy.

It must not contain raw evidence, retired claims, semantic index rows, or free-form memory notes.

### Current-turn recall block

If the current user query needs past evidence, the runtime may inject:

```text
Current-turn recall support:
- evidence or episode summaries relevant to this query

```

This block is attached only to the current user message. It is not persisted and is not durable truth.

### Question candidates

The runtime may provide lens/topic-bound question candidates. The assistant asks at most one, only when it would improve future help.

## Background Reflect

Background reflect is a feature-composable agent system (`apps/reflect/`).

```text
Trigger fires (episode_close, manual, diary, dream, skill_review, init_profile, onboarding_letter, context_compaction)
  → resolve features for this trigger
  → compose system prompt + tools from active features
  → run sub-agent with evidence packet (steps from the episode)
  → agent calls tools directly (personal_model.update, questions, diary.write, etc.)
  → runner extracts result from agent summary + tool call history
  → persist result in learning_jobs.result_json
```

Features (atomic capabilities):
- `pm` — search + write personal model facts
- `questions` — create/settle/dismiss questions
- `recall` — optional read-only conversation recall; use only when an explicit feature set asks for additional evidence
- `diary` — write reflective daily entries
- `skill_affinity` — audit skill catalog fit and write `world.skills.affinity.*` facts
- `skill_evolution` — detect repeated workflows and create disabled, pending skill drafts for user approval
- `init_links` — read user-provided public onboarding links during init/profile learning
- `onboarding_letter` — write the first reflective welcome letter
- `compress` — check compressed content for data loss
- `dream` — run nightly PM cleanup/consolidation; this replaces the older `pm_consolidation` feature name

Compatibility aliases:
- `skills` → `skill_affinity`
- `skill_creation`, `skill_create`, `skill_optimization` → `skill_evolution`
- `profile`, `init_profile` → `init_links`, `pm`, `questions`, `skill_affinity`

Triggers map to feature sets:
- `episode_close` → pm, questions, skill_affinity (medium conservatism)
- `manual` → pm, questions, skill_affinity (low conservatism)
- `diary` → diary (creative)
- `dream` → dream, questions, skill_affinity, skill_evolution, diary (medium conservatism)
- `skill_review` → skill_evolution, skill_affinity (medium conservatism)
- `init_profile` → init_links, pm, questions, skill_affinity (low conservatism)
- `onboarding_letter` → onboarding_letter (creative)
- `context_compaction` → compress (high conservatism)

CLI: `elephant reflect run --features pm,diary --date 2026-05-12`

Most reflect features read the evidence packet and write through their governed tools directly. `skill_evolution` is the exception: it writes a disabled pending Skill draft through `tool.skill.draft`; the macOS Skills surface must approve it before normal agent loops can use it.

## Dashboard Contract

The Dashboard Personal Model page should show four cards:

- Identity
- World
- Pulse
- Journey

Each card shows active claims. Each claim supports:

- Correct
- Forget
- Why?

`Why?` traces back to source episodes via `source_episode_ids` and shows relevant steps from those episodes.

## Design North Star

Elephant Agent feels alive when it can be corrected, can explain why it believes something, and changes its next answer accordingly.

The goal is not to remember more. The goal is to understand better.
