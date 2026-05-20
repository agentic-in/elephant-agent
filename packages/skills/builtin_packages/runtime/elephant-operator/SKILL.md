---
name: Elephant Operator
skill_id: elephant-operator
description: Safely inspect and operate the current Elephant Agent runtime through governed operator tools.
version: 1.0.0
source_kind: elephant-builtin
default_enabled: true
include_in_overlay: false
aliases: ["operator", "runtime operator", "elephant self-management", "self management", "runtime health"]
trigger_phrases: ["inspect elephant runtime", "check elephant health", "what model are you using", "switch elephant model", "restart elephant daemon"]
keywords: ["operator", "runtime", "health", "provider", "model", "daemon", "skills", "tools"]
category: runtime
---

# Elephant Operator

Use this built-in skill when the user asks Elephant Agent to inspect or safely operate its own runtime.

## Core Rules

- Start with `tool.operator.inspect` for runtime, provider/model, daemon, skill, tool, or security questions.
- Treat `probe=false` results as lightweight or cached state; use `probe=true` only when the user asks for a deeper health check or the cached state is insufficient.
- Do not perform mutating self-management from skill text. Use `tool.operator.manage` only through the runtime tool layer.
- For every mutating request, use `phase=plan` first and explain expected changes, risk, confirmation requirement, and rollback before any apply step.
- Use `phase=apply` only after explicit user confirmation and only with the plan id returned by the plan step.
- After an apply step, inspect again or rely on the returned verification receipt before claiming the action succeeded.
- Never expose raw secrets, tokens, API keys, passwords, credential material, or unredacted auth headers.
- If an action is unsupported or unavailable on the current surface, say that plainly and report the structured error code or hint.

## Default Wording

- For status: state the current status, data freshness, and the relevant issue codes.
- For provider/model: distinguish session-scoped model choice from persistent provider defaults.
- For daemon/service: state whether the process is running, stale, misconfigured, or unknown before suggesting restart or repair.
- For tools/skills: distinguish read-only visibility from operator-only mutation.
- For changes: summarize the plan first, then ask for confirmation instead of applying immediately.
