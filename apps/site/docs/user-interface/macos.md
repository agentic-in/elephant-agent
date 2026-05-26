---
title: "macOS app"
description: "Use the macOS desktop app as the primary Elephant Agent workspace for Wake, Personal Model, providers, skills, tools, herd, messaging, reminders, usage, and settings."
---

# macOS app

The macOS app is the recommended Elephant Agent surface. It keeps the daily
conversation and the inspection surfaces in one local workspace instead of
forcing you to switch between a chat window, config files, and a separate
dashboard.

## What the app owns

| Area | Use it for | Product boundary |
| --- | --- | --- |
| **Home** | Start from the Personal Model map, current context, and the next useful question. | The person comes before task delegation. |
| **Wake** | Continue the same elephant. | New work should resume from the same path, not a blank prompt. |
| **Personal Model** | Inspect Identity, World, Pulse, and Journey claims. | Claims stay correctable and evidence-backed. |
| **Providers** | Choose model, reasoning, and embedding posture. | Provider choice changes how Elephant Agent thinks, not what is true. |
| **Skills** | Inspect and enable workflow packages. | Skills are visible capabilities around the Personal Model. |
| **Tools** | Inspect browser, filesystem, MCP, and operator actions. | Tool use stays explicit and recorded. |
| **Herd** | Manage named elephants and local baby agents. | Each elephant is a separate continuity line. |
| **Messaging** | Configure IM surfaces when you want them. | Messaging extends one elephant; it does not create a second memory. |
| **Calendar / Reminders** | Keep scheduled work visible. | Recurring work should remain inspectable and pausable. |
| **Usage** | Review token flow and runtime cost. | Usage is a ledger, not a quality score. |

## When to use the CLI instead

Use CLI + Dashboard when you are on Linux, cloud, SSH, or a terminal-first
workflow. The CLI path is fully supported, but it is not the default product
shape for a macOS user who wants one local workspace.

| Need | Better surface |
| --- | --- |
| Full local desktop workspace | macOS app |
| Remote Linux or cloud machine | CLI + Dashboard |
| SSH-only machine | CLI + `elephant dashboard --no-open` |
| Scripted setup or automation | CLI |

## Daily loop

1. Open the app.
2. Check Home if you need orientation.
3. Use Wake for the actual conversation.
4. Inspect or correct Personal Model claims when something feels stale.
5. Adjust providers, skills, tools, messaging, reminders, and usage from their
   visible app surfaces instead of hiding them in prompt text.

The app and CLI both operate on local Elephant Agent state. They are two
surfaces over the same Personal Model, herd, episodes, and runtime posture.
