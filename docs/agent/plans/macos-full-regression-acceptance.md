# macOS Full Regression Acceptance

Status: Active

## Goal

Prove the real Elephant Agent macOS app is a first-class personal AI companion:
native-feeling, reliable across user journeys, backed by a real model, and
showing Personal Model memory as correctable evidence rather than hidden state.

## Acceptance Scope

- Build and launch the packaged `.app` through `make macos-build`.
- Use the real managed API child process started by the app.
- Use the configured real model provider for at least one Chat turn.
- Inspect the actual SwiftUI app, not only API fixtures or screenshots.
- Cover Home, Chat, voice input/replies, You, Diary, Paths, Skills, Messaging,
  Herd, Usage, Calendar, Learn, Settings, Sleep Display, menu commands, and
  managed runtime lifecycle.
- Confirm Personal Model facts, questions, evidence, Diary, Episode, Loop, and
  Step records remain visible, useful, and correctable from the app.
- Fix any P0/P1 crash, data loss, unusable flow, or obvious IA/design violation
  found during acceptance before calling the surface done.

## Non-Goals

- Do not move durable Personal Model, Episode, Loop, Step, provider, or storage
  logic into Swift.
- Do not replace the local API with app-embedded business logic.
- Do not certify unavailable third-party credentials as working; mark those
  flows as blocked-by-credential while still validating the app controls,
  copy, and state transitions available without secrets.
- Do not call the whole macOS app accepted from one narrow smoke test.

## Work Tracks

- Runtime lifecycle: launch, stale cleanup, restart, quit cleanup, process
  ownership, local API health, and duplicate loopback prevention.
- Primary UX: Home, Chat, You, Diary, Paths, Skills, Messaging, Herd, Usage,
  Calendar, Learn, and Settings.
- Memory quality: fact visibility, source evidence, open questions, corrections,
  Diary learning, semantic recall, and context carried into model replies.
- Model-backed interaction: real provider chat, tool activity rendering,
  streaming response behavior, and provider failure UX.
- Native macOS: menu commands, keyboard shortcuts, resize/fullscreen, Sleep
  Display, accessibility labels, focus, and text fitting.
- Design closure: primary navigation IA, visual hierarchy, card discipline,
  language labels, and Settings ownership for internal/low-frequency controls.

## Dependencies

- A packaged macOS app build from this repository.
- The user's configured local Elephant state directory and database.
- At least one configured provider capable of serving a real model turn.
- Optional external credentials for messaging services; missing credentials
  limit only live transport certification, not UI/control certification.

## Current Evidence

- `make macos-build` succeeded for the local arm64 packaged app on
  2026-05-30.
- The packaged app launched and started its own managed `apps.api` child
  process.
- Launch cleanup removed an older DMG-started macOS API process before the new
  app continued.
- Home showed the user identity, Personal Model map, readiness strip, and
  continuity context on first unlock.
- Chat sent a real model turn through the UI using the configured provider and
  rendered tool activity as a user-facing activity card.
- SQLite Step records confirmed `record_input`, context assembly, model call,
  reflection, state write, and response emission for the real UI turn.
- The primary sidebar now exposes only user-facing work surfaces: Home, Chat,
  Personal Model, Paths, Diary, Skills, Messaging, Herd, Usage, Calendar,
  Learn, and Settings.
- Provider and Tools configuration now live under Settings and both expandable
  rows were verified in the packaged app.
- No new macOS crash report was produced during the post-fix packaged app
  launch and Settings navigation pass.
- Voice input was exercised from the packaged app. When the system microphone
  permission request did not return a prompt, the overlay now times out to a
  clear `Voice unavailable` state with System Settings guidance instead of
  remaining in a misleading empty capture state.
- Voice cancel was verified after the timeout state; the overlay dismissed, no
  late permission callback restarted capture, and no new macOS crash report was
  produced.
- The packaged Personal Model surface was inspected in the real app. Facts
  expand with correct/recover/delete controls, source-backed evidence now has a
  dedicated panel, and open questions expose direct Sooner, Dismiss, and Reply
  actions.
- The Personal Model Reply popover was opened and canceled from the packaged
  app without mutating question data.
- The current local state exposes Personal Model fact traces, but the semantic
  index count is `0`, so source indexing quality remains an acceptance follow-up.
- Diary was inspected in the packaged app. Markdown entries render expanded,
  the date selector changes the target date, and Write Diary queued a real
  diary job for 2026-05-30 with visible success feedback.
- Paths was inspected in the packaged app. The board, path rail, board/list
  controls, step detail sheet, Activity/Learning/Properties tabs, run affordance,
  and comment composer are visible and navigable.
- Path and Flow step destructive actions now expose explicit Delete labels and
  native confirmation dialogs; cancel was verified from the packaged app without
  deleting user data.
- Skills was inspected in the packaged app. Learned skill matches, library
  counts, search, pagination state, enabled/available rows, and the detail sheet
  were verified with a `paper` search.

## Open Acceptance Matrix

| Surface | Required Proof | Status |
| --- | --- | --- |
| Home | First viewport is useful in under two seconds; readiness cards navigate to owning surfaces. | Partial |
| Chat | Text, image, voice, history, queue, streaming activity, and markdown response behavior verified. | Partial |
| Voice | Native permissions, start/stop/cancel/send, local transcription fallback, and reply playback verified. | Partial; permission timeout and cancel verified |
| You | Facts, questions, source evidence, correction, retire/recover/delete, and map interactions verified. | Partial; facts, evidence separation, question actions, and reply cancel verified; semantic index is empty |
| Diary | Read/write Markdown diary entries and learning linkage verified. | Partial; Markdown render, date picker, and write queue verified |
| Paths | Path board, step detail, comments, run, learning summaries, and trust prompts verified. | Partial; board, detail tabs, comment composer, run affordance, and safe delete confirmation verified |
| Skills | Search, pagination, skill detail, pending evolution drafts, and no duplicate settings summaries verified. | Partial; search, pagination state, detail sheet, enabled/available rows, and learned matches verified |
| Messaging | WeChat QR, Feishu/Discord/DingDing/WeCom setup controls, start/stop, and status UX verified where credentials allow. | Not complete |
| Herd | Mother and baby runtime editing, provider/local CLI babies, delegation, and expanded row editability verified. | Not complete |
| Usage | Token trend chart and row detail verified with real usage events. | Not complete |
| Calendar | Week, Month, Year views plus create/run/pause/delete job controls verified. | Not complete |
| Learn | Reflect/dream/diary jobs, progress, summaries, and understood checks verified. | Not complete |
| Settings | Language, voice, provider, memory, curiosity, history, sleep, logs, reset, runtime, and config editing verified. | Partial; provider and tools rows verified |
| Menus | New Chat, Reflect, Refresh, Reveal Database, Restart Core, sidebar, navigation, and Sleep Display verified. | Not complete |
| Runtime | Managed PID ownership, stale cleanup, restart, quit cleanup, and no duplicate loopback APIs verified. | Partial |
| Design | Native IA, text fit, accessibility labels, no internal-only first-level nav, and resized/fullscreen layouts verified. | Partial; first-level IA verified |

## First Fix Track

- Keep primary sidebar focused on user-facing work surfaces.
- Move provider configuration into Settings.
- Keep tool catalog access out of the primary sidebar.
- Use "Learn" as the user-facing sidebar label for background learning instead
  of exposing mechanism-heavy wording.

## Personal Model Fix Track

- Keep reviewed facts, source-backed evidence, and open questions as visually
  separate Personal Model regions.
- Show source/evidence counts and fact trace rows before the question field.
- Expose direct Sooner, Dismiss, and Reply actions for actionable open
  questions, with native tooltips and accessibility labels.

## Paths Safety Fix Track

- Label icon-only destructive controls as Delete Path or Delete Flow step for
  assistive technology instead of generic close controls.
- Require a native confirmation dialog before deleting a Path or Flow step.
- Keep cancel non-mutating and verify it from the packaged app before shipping.

## Exit Criteria

- Every row in the acceptance matrix is `Complete` or explicitly marked with a
  credential/device blocker and a verified graceful UX state.
- No known P0/P1 macOS crash, app-launch failure, runtime ownership defect,
  inaccessible main flow, or first-level IA violation remains.
- A real model-backed Chat turn and a memory-backed follow-up are verified from
  the packaged app UI.
- `make macos-build` and the relevant repo gate pass after any code/docs
  changes.
- All repo-visible fixes are shipped through `make agent-ship ...` unless the
  diff must intentionally remain split for follow-up work.

## Validation Ladder

- `make agent-report CHANGED_FILES="..."`
- targeted unit/e2e checks for touched contracts
- `make macos-build`
- `make agent-fast-gate`
- `make agent-ship AGENT_COMMIT_MESSAGE='fix(macos): ...'` when the diff is one
  controlled atomic unit
