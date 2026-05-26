---
title: "System model"
description: "Elephant Agent's canonical model is an Understanding System: Personal Model claims, questions, episodes, Elephant State, and steps."
---

# System model

Elephant Agent is an **Understanding System**. It remembers through layers, each
with a different owner and lifetime.

## The five-layer model

```mermaid
flowchart TB
  pm["Matriarch Core / Personal Model<br/>Identity, World, Pulse, Journey<br/>facts + open questions"]
  state["Elephant State<br/>elephant identity + current context note"]
  trail["Episode / Loop / Step Trail<br/>source events, tool use, replies, updates"]
  recall["Contextual Recall<br/>current-turn support from facts and steps"]
  learning["Background Learning<br/>curiosity, diary, dream, skill matching"]

  state --> pm
  trail --> recall
  pm --> recall
  trail --> learning
  learning --> pm
  learning --> state
```

| Layer | Owns | Lifetime | Should contain |
| --- | --- | --- | --- |
| **Matriarch Core / Personal Model** | Durable understanding. | Across sessions and surfaces. | Active facts, retired/disputed claims, open questions. |
| **Elephant State** | The elephant identity and one continuation note. | Across wakes for one elephant. | `elephant_id`, name, identity text, current context note. |
| **Episode / Loop / Step Trail** | Raw lived trace and provenance. | Audit and learning history. | Inputs, replies, tool calls, tool results, updates. |
| **Contextual Recall** | Support for the current turn. | Current turn only. | Retrieved claims or Step evidence with match status. |
| **Background Learning** | Slow maintenance of understanding. | Scheduled or lifecycle-triggered. | Episode close, diary, dream, questions, and visible skill matching. |

:::note
Contextual recall is not discarded as "just recall." It is one layer of the
memory architecture. It can retrieve support, but it does not become durable
truth unless a governed update writes through the Personal Model.
:::

## Runtime flow

```mermaid
sequenceDiagram
  participant User
  participant Wake
  participant State as Elephant State
  participant PM as Personal Model
  participant Recall as Contextual Recall
  participant Trail as Episode / Steps
  participant Learn as Background Learning

  User->>Wake: elephant wake
  Wake->>State: load elephant identity + context note
  Wake->>PM: project active claims + questions
  Wake->>Recall: retrieve current-turn support when useful
  Wake->>Trail: record input, output, tools, updates
  Trail->>Learn: episode close / diary / dream
  Learn->>PM: write governed updates
  Learn->>State: refresh continuation note
```

## Claim-aware search

Personal Model search returns claims, not generic note chunks. It can use:

| Signal | Purpose |
| --- | --- |
| Topic keys | Find exact known claim slots. |
| Exact text | Respect precise names, phrases, or values. |
| Unicode lexical and CJK n-grams | Support multilingual and mixed-language matching. |
| Semantic retrieval | Recover meaning when wording changes. |
| Query variants | Let the model provide translated or paraphrased variants. |
| Diagnostics | Explain why a claim was matched, weakly matched, or not matched. |

The public search modes are `auto` for claim lookup and `inventory` for the
lens/topic map. Search returns `strong_match`, `weak_match`, or `no_match`, so
Elephant Agent can avoid inventing support when the Personal Model does not
contain reliable understanding.

## Prompt projection

The stable prompt should contain only what Elephant Agent can responsibly carry:

- elephant identity and current context note
- active Personal Model claims
- compact tool and behavior policy
- current-turn recall support only when useful

For the canonical repository design reference, see
[`docs/system-design/system-layer-model.md`](https://github.com/agentic-in/elephant-agent/blob/main/docs/system-design/system-layer-model.md).
