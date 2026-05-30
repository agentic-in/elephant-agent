# Local Tool Approval Surface

Status: open.

## Current State

The tool runtime has approval classes and a `SecurityApprovalGateway`, but the
packaged macOS Chat path can still execute high-risk local tools without a
first-class Elephant approval surface. Real packaged-app probes showed a model
could write a temporary Desktop file after the tool root policy allowed the
current-user path, and could use terminal-based local automation to create a
temporary Apple Notes note. No macOS Files & Folders, Automation, or Notes prompt
appeared in that environment.

The app now exposes Settings links to the relevant macOS privacy pages, which
helps permission recovery and preflight readiness. That does not replace a
product-owned approval step because tools can run inside already-allowed local
execution contexts.

## Target

Risky local side effects should pause behind an explicit in-app approval flow:

- file writes, patches, destructive file operations, terminal execution, code
  execution, and external app automation are classified before execution;
- the Chat UI explains the action, path or app target, scope, and expected
  result in user language;
- the user can approve once, deny, or cancel the turn without losing the
  transcript;
- approved and denied decisions are recorded in Episode / Loop / Step evidence;
- path access is scoped to the task or user-selected folders rather than broad
  home-directory assumptions where possible.

## Why The Gap Remains

The existing security policy can classify risky tools, but the macOS product
does not yet have a resumable approval sheet, stream protocol, and user decision
handler wired into the managed API path. Turning on deferred approvals without
that surface would block useful tools instead of producing a good user
experience.

## What Would Close It

- Wire the app/API runtime to `SecurityApprovalGateway` for risky local tools.
- Add a Chat approval card or sheet that can approve, deny, or cancel deferred
  tool calls and resume the active loop.
- Narrow default local roots or require explicit task-scoped folder selection
  for user-visible file writes.
- Normalize model-provided `~` and user-home paths against the actual current
  OS user before tool authorization.
- Keep raw local implementation details collapsed or redacted in normal Chat
  cards while preserving audit evidence.

## Risks

- A model can perform local writes or app automation after a user asks for a
  broad action, without the product making the exact side effect explicit.
- macOS privacy prompts are not a sufficient safety boundary because already
  authorized helper contexts and terminal automation can bypass a visible prompt.
- Incorrect home-path guesses can produce confusing failures before the tool
  root policy rejects them.
- External app automation cleanup can be unreliable, leaving user-visible probe
  artifacts behind when an AppleEvent times out.
