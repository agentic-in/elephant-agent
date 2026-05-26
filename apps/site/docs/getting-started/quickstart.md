---
title: "Quickstart"
description: "Start with the macOS desktop app, or use CLI + Dashboard for Linux, cloud, SSH, and terminal-first setups."
---

# Quickstart

Use the macOS desktop app when you can. Use CLI + Dashboard when you are on
Linux, cloud, SSH, or a terminal-first macOS setup.

Elephant Agent's product position is agency-first: it should help you do more
without thinking less. The Personal Model is how the product keeps judgment,
evidence, questions, and growth close to the person.

## Path overview

```mermaid
flowchart LR
  start["Start"] --> desktop["macOS desktop app"]
  start --> cli["CLI + Dashboard"]
  desktop --> app_setup["create first elephant"]
  app_setup --> app_wake["Wake"]
  cli --> init["elephant init"]
  init --> status["elephant status"]
  status --> wake["elephant wake"]
  wake --> dashboard["elephant dashboard"]
```

## macOS desktop app

| Step | Action | Done when... |
| --- | --- | --- |
| Download | Get the latest build from [GitHub Releases](https://github.com/agentic-in/elephant-agent/releases/latest). | `Elephant Agent.app` is installed locally. |
| Create | Open the app and create your first elephant. | The app has a local elephant to return to. |
| Configure | Choose provider, model, embedding posture, and curiosity effort. | Wake and Personal Model are ready. |
| Continue | Open **Wake**. | You are back in the same conversation path. |

The desktop app is the primary surface for Wake, Personal Model, providers,
skills, tools, herd, messaging, reminders, usage, and settings.

## CLI + Dashboard

| Step | Command | Done when... |
| --- | --- | --- |
| Install | `curl -fsSL https://elephant.agentic-in.ai/install.sh \| bash` | `elephant` is on your `PATH`. |
| Initialize | `elephant init` | Your first elephant and provider posture exist. |
| Check readiness | `elephant status` | Provider and embedding readiness are clear. |
| Continue | `elephant wake` | You are in the durable chat surface. |
| Inspect | `elephant dashboard` | You can inspect Personal Model, questions, evidence, and runtime state. |

:::tip
After the first CLI setup, `elephant wake` is the normal daily terminal
entrypoint.
:::

### 1. Run init

```bash
elephant init
```

`init` is the first-use setup flow. It:

- binds the local identity
- lets you choose a personality preset
- grows the first elephant with a clean Personal Model
- captures the active provider configuration before real conversations begin
- prepares the first named elephant so `wake` is the natural next step
- surfaces the IM handoff so `elephant gateway setup` can open the IM chooser without leaving the main setup flow

### 2. Confirm readiness

```bash
elephant status
```

Use `status` before the first durable conversation. It tells you whether the
active provider and local runtime posture are ready to go.

### 3. Enter `wake`

```bash
elephant wake
```

`wake` is the main conversational surface. That is where continuity stays
alive and your elephant keeps learning.

For remote or cloud use:

```bash
elephant dashboard --no-open
```

That prints the local Dashboard URL without trying to open a browser on the
remote machine.

## Optional next steps

| If you want to... | Run | Read |
| --- | --- | --- |
| Inspect what Elephant Agent understands | `elephant dashboard` | [Dashboard](../user-interface/dashboard.md) |
| Wire a messaging app | `elephant gateway setup` | [Messaging](../capacities/messaging.md) |
| Install or inspect skills | `elephant skills` or `/skills` | [Skills](../capacities/skills.md) |
| Choose a provider or model | `elephant provider` or `/providers` | [Providers and models](./providers.md) |

### Wire IM

```bash
elephant gateway setup
```

Use this entrypoint when you want to choose an IM surface, configure it, or
inspect IM readiness without remembering the provider-specific setup commands.

## 4. Create another elephant only when you need one

```bash
elephant herd new nova
```

Each elephant is an isolated Elephant Agent individual with its own continuity line,
personality drift, and future `wake` history.

:::warning
Do not create a new elephant for every task. Create one when you want a separate
continuity line.
:::

## Optional: non-interactive setup

For scripted setup, you can preconfigure the provider path directly:

```bash
elephant init --non-interactive \
  --elephant-name nova \
  --provider-id openai-compatible
```

For deeper provider setup, continue with
[Providers and models](./providers.md).
