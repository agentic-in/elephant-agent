# Local Tool Approval Surface

Status: partially mitigated.

## Current State

The tool runtime has approval classes and a `SecurityApprovalGateway`. Earlier
packaged-app probes showed why the Chat path needed a first-class Elephant
approval surface: a model could write a temporary Desktop file after the tool
root policy allowed the current-user path, and could use terminal-based local
automation to create a temporary Apple Notes note. No macOS Files & Folders,
Automation, or Notes prompt appeared in that environment.

The app now exposes Settings links to the relevant macOS privacy pages, which
helps permission recovery and preflight readiness. That does not replace a
product-owned approval step because tools can run inside already-allowed local
execution contexts.

The managed API Chat path now routes the riskiest local tools through the
existing security approval policy with auto-approval disabled. File writes,
patches, terminal execution, process control, code execution, and local-write
MCP tools return `approval.deferred` before execution, and the macOS Chat tool
activity row shows a visible needs-approval state. This prevents silent host
mutation. Deferred tool calls now retain a one-time approval token scoped to the
originating Episode; the native Chat activity row exposes Approve once and Deny;
approving resumes the exact paused invocation; denying records a blocked result
without executing the handler.

The current packaged-app regression probe launched the rebuilt macOS app and
used its own managed API to defer both a file write and a terminal command. The
file write did not create the target before approval, Approve once resumed that
exact invocation and wrote the expected content, Deny blocked the terminal
invocation without creating its target file, pending approvals were cleared, and
`/healthz` stayed healthy.

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

The basic pause/resume decision loop is now wired, but this is still tracked as
partially mitigated rather than closed because approval decisions are not yet
durably reflected as first-class Episode / Loop / Step evidence, the UI is an
inline card rather than a full review sheet for complex actions, and broad local
root assumptions still need tightening.

## What Would Close It

- Wire the app/API runtime to `SecurityApprovalGateway` for risky local tools.
  Done for fail-closed deferral and approve-once/deny decisions.
- Add a Chat approval card or sheet that can approve, deny, or cancel deferred
  tool calls and resume the active loop. The inline card is done; a richer sheet
  is still useful for multi-file or external-app actions.
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
