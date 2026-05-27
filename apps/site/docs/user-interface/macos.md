---
title: "macOS app"
description: "Use the macOS desktop app as the primary Elephant Agent workspace for Chat / Wake, Paths, Personal Model, Herd, skills, messaging, calendar, usage, and settings."
---

# macOS app

The macOS app is the recommended Elephant Agent surface. It keeps the daily
conversation and the inspection surfaces in one local workspace instead of
forcing you to switch between a chat window, config files, and a separate
dashboard. The long-term product shape is Mother in chat, Paths for ongoing
life and work arcs, and inspectable settings for the model and runtime posture.

## What the app owns

| Area | Use it for | Product boundary |
| --- | --- | --- |
| **Home** | Start from what Mother understands and what is alive now. | The person comes before any Step or delegation. |
| **Chat / Wake** | Talk to Mother and continue the same elephant. | New work should resume from the same path, not a blank prompt. |
| **Paths** | See ongoing directions, Steps, Flow state, and Checkpoints. | A Path can be work, health, learning, habits, recovery, or any long-running arc. |
| **Personal Model / You** | Inspect Identity, World, Pulse, and Journey claims. | Claims stay correctable and evidence-backed. |
| **Herd** | Manage Mother and baby elephants. | Babies do bounded work; Mother keeps the Path coherent. |
| **Skills** | Inspect and enable workflow packages. | Skills help Mother and the Herd move Steps. |
| **Messaging** | Configure IM surfaces when you want them. | Messaging extends one elephant; it does not create a second memory. |
| **Calendar / Reminders** | Keep routines, reminders, and scheduled Path work visible. | Recurring work should remain inspectable and pausable. |
| **Usage** | Review token flow and runtime cost. | Usage is a ledger, not a quality score. |
| **Settings** | Choose providers, tools, advanced runtime posture, and app preferences. | Advanced controls stay visible without becoming the product center. |

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
3. Use Chat / Wake for the actual conversation.
4. Use Paths when a direction needs Steps, Flow state, or Checkpoints.
5. Inspect or correct Personal Model claims when something feels stale.
6. Adjust providers, skills, tools, messaging, reminders, and usage from visible
   app surfaces instead of hiding them in prompt text.

The app and CLI both operate on local Elephant Agent state. They are two
surfaces over the same Personal Model, herd, episodes, and runtime posture.
