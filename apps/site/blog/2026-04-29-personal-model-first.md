---
slug: personal-ai-you-create
title: "Personal-Model-First: Why Elephant Agent Self-Evolves Around You"
authors: [elephant-team]
tags: [elephant, personal-ai, personal-model, curiosity, continuity, open-source]
description: "Memory is the beginning. Personal AI should self-evolve around a correctable Personal Model, user-paced curiosity, and background reflect."
image: /assets/blog/1.png
hide_table_of_contents: false
---

# Personal-Model-First: Why Elephant Agent Self-Evolves Around You

<div className="blog-figure">
  <img src="/assets/blog/1.png" alt="Elephant Agent blog cover" />
</div>

Elephants never forget, but the interesting part is not storage.

An elephant does not remember like a hard drive. It remembers like a living
being. Its memory is social, emotional, spatial, survival-aware, and practical.
It recognizes members of the herd by sight and smell. It remembers danger cues.
It returns to important places long after the last visit. It carries the
difference between a safe path, a risky signal, a trusted companion, and a dry
season that should not be repeated.

Older matriarchs make this visible. A remembered drought is not a line in a
database; it is judgment the herd can move with. Elephants can recognize other
animals and humans after years apart. Their hippocampus links emotion to
long-term memory. Their cerebral cortex supports problem solving, cooperation,
tool use, and quantity tracking. They communicate across distance, comfort each
other, protect the young, and respond to loss with a tenderness that makes
memory feel close to care.

That is the inspiration for Elephant Agent: not an AI with more memory, but an
AI whose memory can turn lived context into better judgment.

The first wave of personal agents is learning two useful things. Memory matters.
Skills matter. A personal AI should be able to recall what happened, and it
should become more capable over time.

But neither is the center.

Raw recall answers: what can be retrieved from the past?

Skills answer: what can the agent do?

Personal AI needs a third object at the center: what does the agent currently
understand about the person, and how can that understanding be corrected,
deepened, or questioned?

Elephant Agent is built around that object. We call it the **Personal Model**.

<!-- truncate -->

## Memory Becomes Understanding

If a personal AI stores every transcript, it still may not understand you.

It may retrieve the wrong old snippet. It may over-trust something you have
changed your mind about. It may treat a joke, a temporary mood, or a stale
project as durable truth. It may remember a sentence without understanding why
that sentence should matter tomorrow.

Skill evolution has a similar limit. An agent can learn useful procedures,
install better tools, and automate more surfaces. That is valuable. But a
personal agent that evolves capabilities without evolving understanding becomes
capability-first: better at acting, not necessarily better at helping *you*.

Elephant Agent makes a different bet:

> **Personal AI should evolve around a correctable Personal Model first. Memory,
> skills, tools, models, cron, messaging, and UI should orbit that model.**

This is the difference between a recall layer and an understanding system.

Raw recall retrieves. Elephant Memory Architecture decides what should become
a claim, what should stay evidence, what should expire, what should be asked,
and what should be safe to use in the next answer.

In other words, memory is not downgraded to recall. Recall is one layer inside
the system. Elephant Agent treats memory as a full architecture for turning
experience into judgment.

## The Personal Model

The Personal Model is not a hidden profile. It is not a longer prompt. It is
not a vector database with a nicer name.

<div className="blog-figure">
  <img src="/assets/blog/2.png" alt="The Personal Model diagram" />
</div>

It is the explicit, inspectable center of Elephant Agent's continuity: active
claims, open questions, status, confidence, and provenance. Each claim belongs
to one of four lenses.

**Identity** asks: who is this person?

It carries durable self-description: name, language, values, boundaries,
decision style, stable preferences, communication taste, and the kind of help
that usually lands well. Identity changes slowly. When it is wrong, correction
matters more than accumulation.

**World** asks: what and who surrounds them?

It carries people, teams, projects, repositories, tools, places, vocabulary,
obligations, recurring meetings, domains, and stable constraints. World is how
Elephant Agent stops treating every request as if it arrived from nowhere.

**Pulse** asks: what is alive right now?

It carries current focus, open decisions, active pressure, recent blockers,
temporary priorities, and mood or energy patterns when the user has made them
relevant. Pulse is deliberately fresh. A stale Pulse claim should be easy to
replace.

**Journey** asks: what has the path already taught?

It carries lessons learned, repeated risks, recovery patterns, past decisions,
direction changes, and long-running growth. Journey is how Elephant Agent helps
without making you pay the same explanation tax after every reset.

The durable unit is a claim, not a transcript sentence. A claim has a lens,
topic, text, status, confidence, and source episode provenance. Only active
claims enter the stable prompt. Retired and disputed claims remain inspectable,
but they do not shape future answers.

Within a lens, Elephant Agent uses **facets** as stable topic keys. A facet is
not a survey field; it is the naming layer that keeps one claim attached to the
right slice of understanding, such as `world.skills.affinity.python`,
`pulse.current_focus`, or `journey.lessons.debugging`. This lets search and
correction operate on claims instead of ambiguous profile blobs.

This is intentionally smaller than a profile and deeper than a chat log.

The elephant-inspired memory model maps onto the runtime as five layers:

- **Episodic memory** lives in Episodes, Loops, and Steps: what happened, when,
  and through which operation.
- **Semantic memory** lives in typed Personal Model claims: durable principles,
  preferences, lessons, and context.
- **Social memory** lives in World claims and supporting Steps: people, teams,
  projects, collaborators, and relationship context.
- **Survival memory** lives in Pulse and Journey claims: risks, repeated
  failures, pressure patterns, and recovery paths.
- **Matriarch Core** is the Personal Model plus curiosity and background
  learning: the place where evidence becomes judgment.

## Curiosity Is the Learning Loop

<div className="blog-figure">
  <img src="/assets/blog/6.png" alt="Proactive curiosity at the user's pace" />
</div>

Most memory systems are passive. They wait for the user to say something, then
try to store or retrieve it.

Elephant Agent needs a more living behavior: it should notice when its
understanding is missing, conflicted, stale, or too vague to help.

That is what we mean by **proactive curiosity**.

Curiosity is not interrogation. It is not a survey. It is not hidden profiling.
It is a bounded maintenance loop for the Personal Model. Elephant Agent may ask
one useful question when the answer would change future help.

Questions are typed. Each one has a lens, topic, reason, priority, sensitivity,
and lifecycle: open, asked, answered, dismissed. A question exists for one of
four reasons:

- a **gap** where important understanding is missing,
- a **conflict** where evidence no longer agrees,
- a **stale Pulse** where current context likely expired,
- an **adaptation** where one answer would materially improve help.

The user chooses the effort level: quiet, balanced, or active. Silence is
honored at every level. When a question is answered, the answer can become a
Personal Model claim through the same update path as any explicit correction.

This is why curiosity is central to the product. Personal AI should not only
remember what was said. It should maintain the relationship between what it
believes and what would help next.

## From Philosophy to Runtime

The architecture is designed to protect that distinction.

<div className="blog-figure">
  <img src="/assets/blog/3.png" alt="Elephant Memory Architecture diagram" />
</div>

**Matriarch Core / Personal Model** is the durable understanding layer. It owns
Identity, World, Pulse, Journey, and open questions. If something should shape
future answers, it belongs here, with provenance and a repair path.

**Elephant State** is intentionally small. It identifies the active elephant and
keeps one natural-language context note: where this elephant should resume.

**Episode / Loop / Step Trail** is the lived trace. An Episode is one runtime
window. A Loop is one model interaction round. A Step is one atomic event:
input, reply, tool call, tool result, recall support, or Personal Model update.
Steps are evidence. They are not automatically truth.

**Contextual Recall** is the retrieval layer of Elephant Memory Architecture.
It finds supporting material for the current turn or a reflect job. It can
search Personal Model facts and conversation Steps, but retrieved material is
support. It does not become a durable claim unless a foreground update or
background learning job writes it through the Personal Model.

**Background Learning** lets Elephant Agent learn after the turn. Episode close,
manual reflect, diary, dream, and context-compaction triggers compose specific
features and tools. A reflect agent receives an evidence packet, calls allowed
Personal Model, question, diary, or skill tools, and writes its result into the
learning job record.

The important design rule is simple:

> Prompt text is a projection of state. It is not the owner of truth.

## Claim-Aware Recall

This is where Elephant Agent differs from generic vector memory.

When Elephant Agent searches its Personal Model, it is not searching a pile of
notes. It is searching active claims. The retrieval unit is the claim, and the
claim has a lens, topic, status, confidence, and evidence trail.

<div className="blog-figure">
  <img src="/assets/blog/10.png" alt="Claim-aware recall separates Personal Model claims from supporting evidence and returns strong, weak, or no match" />
</div>

Search combines several signals:

- topic keys and topic prefixes,
- exact claim text and source-support matches,
- Unicode lexical matching and CJK n-grams,
- weak fuzzy matching for spelling or character variation,
- semantic candidates from the durable index,
- translated or paraphrased `query_variants` supplied by the model,
- freshness signals for claims that should decay.

The result includes a match status:

- `strong_match` means the agent can rely on the claim.
- `weak_match` means something is relevant but should not be overstated.
- `no_match` means the Personal Model does not support the answer.

`no_match` is not a failure. It is a safety behavior.

Without this, memory systems drift. A nearest neighbor becomes a belief. A
similar old sentence becomes personalization. A stale fact becomes confidence.
Elephant Agent keeps the boundary visible: recall can support the current turn,
but durable understanding stays in claims.

## Multilingual, Hybrid, Time-Aware Search

> Good personal memory is not just semantic similarity. It is judgment.

People do not remember by asking one database for the nearest sentence. We
remember through a richer judgment: what was said, who said it, whether it is
still true, whether the wording changed, whether it happened recently, whether
it belongs to a stable identity or a temporary mood, and whether the memory is a
belief or only a clue.

Elephant Agent brings that judgment into recall search.

**The algorithm is multilingual** because real personal context is multilingual.
One person may explain a project in English, correct a preference in Chinese,
name a file in code, and later ask for the thread in a mix of all three.
Elephant Agent does not depend on one brittle keyword form. It can follow
meaning across mixed wording, translated variants, and language boundaries
without turning language matching into a hidden alias table.

<div className="blog-figure">
  <img src="/assets/blog/9.png" alt="Multilingual hybrid time-aware search turns language, evidence, and time into the right memory with the right confidence" />
</div>

**It is hybrid** because no single signal deserves to be trusted alone.
Semantic search is good at meaning, but weak at exact commitments. Keyword and
BM25-style signals are good at names, dates, tools, and concrete phrases, but
brittle when the wording shifts. Topic structure is good at narrowing the
Personal Model, but it should not make an irrelevant claim look relevant.
Elephant Agent fuses these signals so recall can stay both flexible and
grounded.

**It is time-aware** because personal truth has different half-lives. *I was
tired this week* should not age like a birth date. *This project is active*
should not age like a permanent preference. A phrase like *last night* or
*recently* is not decorative text; it changes what kind of memory should be
searched and how much recency should matter.

The result is not a longer archive. It is a better way to decide whether the
agent has found **a durable claim**, **a weak clue**, **a conversation trail**,
or **a visible gap** where it should not pretend to know.

This is the practical bridge between elephant memory and personal AI:

> recover the right path, in the right language, at the right moment, with the
> right level of certainty.

## Local Semantic Recall

The local embedding path exists to support that boundary without turning
personal context into a remote analytics stream.

<div className="blog-figure">
  <img src="/assets/blog/4.png" alt="Contextual Recall diagram" />
</div>

Elephant Agent's default embedding provider is `elephant-local-embed`, backed
by `elephant-embeddings-v1-text-small`. The runtime loads the model from the
local Elephant Agent model root with sentence-transformers and
`local_files_only=True`. If the local model root is not ready, the provider
reports health as pending or downloading instead of silently falling back to a
remote path.

The embedding model supports three online dimensions:

- **64d** for fast everyday recall,
- **256d** as the balanced default,
- **768d** for deeper semantic search.

The implementation uses normalized embeddings and a Matryoshka-style truncation
path: a larger source representation can be truncated to the selected online
dimension and normalized again. That lets one compact local model support
different latency and depth postures.

The semantic index has two parts. Metadata rows live in SQLite as
`SemanticIndexEntry`: owner scope, source item, provider, model, dimensions,
content hash, status, and provenance pointers. Vectors live behind a
`sqlite-vec` backend when available. If vector indexing is degraded, the
metadata still records the state, and lexical search can continue to help.

That gives Elephant Agent a practical local recall stack:

1. foreground claim writes are indexed immediately,
2. Step and Fact chunks can be embedded locally,
3. vector search is fused with lexical and keyword signals,
4. matches point back to their source items,
5. recall support remains support, not truth.

This is the technical reason the product can say "correctable understanding"
instead of "memory." The system can show what it found, what it believes, and
where the two differ.


## Background Learning

<div className="blog-figure">
  <img src="/assets/blog/7.png" alt="Background learning updates the Personal Model through governed evidence" />
</div>

Foreground conversation should help now. It should not stop every few turns to
perform maintenance on the user's entire understanding graph.

Elephant Agent moves that work into feature-composable background learning.

Different triggers activate different feature sets:

- Episode close can run Personal Model, question, and skill maintenance.
- Manual reflect can add recall support.
- Diary writes a reflective entry for a day.
- Dream can combine broader question, skill, and diary maintenance.
- Context compaction checks compressed material without turning it into prompt
  truth.

Each reflect job receives an evidence packet built from active Personal Model
anchors, Episode summaries, and conversation turns. The reflect agent is given
only the tools its features allow. It writes facts, questions, diary entries,
or skill notes through the same governed surfaces as the foreground agent. The
job result records what happened.

There is no hidden "memory proposal" layer in the clean design. Steps are the
evidence. Facts are the durable understanding. Learning jobs are the lifecycle
that decides when evidence should change understanding.

## The Operator Surface

<div className="blog-figure">
  <img src="/assets/blog/8.png" alt="Elephant Agent surfaces orbit the Personal Model" />
</div>

Elephant Agent is not only a paper architecture. It has to be lived through
ordinary surfaces.

The CLI creates and wakes an elephant. The chat TUI is the fast daily path. The
Dashboard shows Personal Model claims, questions, evidence, jobs, providers,
logs, and herd state. Messaging bridges let the same elephant meet you outside
the terminal. Cron jobs let background work happen on a schedule. Tools and
skills remain visible capabilities rather than hidden personality changes.

This is also why the project is open source. If an AI is going to grow an
understanding of you, the persistence model, learning jobs, question lifecycle,
local inference path, and repair operations should be inspectable.

## The Core Bet

<div className="blog-figure">
  <img src="/assets/blog/5.png" alt="The Core Bet illustration" />
</div>

The next generation of personal AI will not be won by the agent with the
longest transcript or the largest skill shelf.

It will be won by the agent that can maintain a living, correctable model of
the person it helps.

Elephant Agent is our first version of that bet:

> **Personal-Model-first. Self-evolving through curiosity and reflect. Correctable as it grows.**

Memory helps. Skills help. But personal AI starts when the system can ask:
what do I understand, why do I believe it, what is missing, and how should this
change the next answer?

## What Comes Next

The next step is to make that understanding deeper, safer, and more capable
without losing the center.

We want background learning to do more than notice skill matching. When the
same useful pattern appears across real work, Elephant Agent should be able to
propose a new skill or improve an existing one, with the evidence visible and
the final shape still yours to accept.

We also want the security boundary to become as inspectable as memory itself:
stronger coding sandbox isolation, clearer tool access control, safer
background jobs, and better audit trails for how a recalled claim becomes a
model decision or a tool action.

And we want the whole stack to learn together. Personal AI should not optimize
memory, routing, inference, and training as separate islands. The path is
**agent → router → inference → train**: vLLM Semantic Router can help choose the
right model, privacy posture, jailbreak/tool-risk boundary, and collaboration
shape; vLLM inference can expose the latency and KV-cache signals that make
long-running agents practical; RL post-training can reward the behaviors that
matter here: asking at the right time, refusing weak memory, preserving
corrections, and choosing the right capability only when it truly fits.

[Star us on GitHub](https://github.com/agentic-in/elephant-agent)

[Get started in 60 seconds](/docs/getting-started/quickstart/)

---

*Elephant Agent is developed by [Agentic Intelligence Lab](https://github.com/agentic-in), with collaborators at MBZUAI, McGill University, and Mila. The project is open source under the Apache 2.0 license.*
