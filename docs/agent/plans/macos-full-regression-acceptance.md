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
- Chat image attachment was verified through the packaged app with the native
  file picker. The attachment chip, preview, persisted attachment copy, real
  model reply, and `record_input` -> `assemble_context` -> `call_model` ->
  `emit_response` Step records were all confirmed.
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
- Voice capture and reply playback were hardened against stale asynchronous
  callbacks. Permission, recognizer, preview-recognizer, local transcription,
  system speech, and audio-player callbacks now ignore outdated capture/playback
  generations so rapid stop/start/send flows cannot mutate a newer voice turn.
- The rebuilt packaged app launched into Sleep Display with its managed API
  healthy, and the post-rebuild smoke did not produce a new macOS crash report.
- The only macOS crash report found during this pass predated the current
  packaged-app launch; the Chat, voice-timeout, Settings, attachment, Calendar,
  Diary, and Personal Model passes did not create a new crash report.
- The packaged Personal Model surface was inspected in the real app. Facts
  expand with correct/recover/delete controls, source-backed evidence now has a
  dedicated panel, and open questions expose direct Sooner, Dismiss, and Reply
  actions.
- The Personal Model Reply popover was opened and canceled from the packaged
  app without mutating question data.
- Personal Model map interaction was verified from the packaged app. Selecting
  a map dot opened the fact detail with kind, namespace, provenance, text, and
  close affordance.
- The Personal Model pass initially exposed active fact traces while the
  semantic index count was `0`; the later packaged runtime/backfill fix
  recovered semantic indexing and made source indexing quality directly
  verifiable.
- Diary was inspected in the packaged app. Markdown entries render expanded,
  the date selector changes the target date, and Write Diary queued a real
  diary job for 2026-05-30 with visible success feedback.
- Diary source linkage was inspected in storage and fixed. Conversation recall
  now exposes source episode IDs, the diary writing SOP preserves them, and the
  diary write tool falls back to the current episode/session when a model omits
  explicit source IDs.
- Paths was inspected in the packaged app. The board, path rail, board/list
  controls, step detail sheet, Activity/Learning/Properties tabs, run affordance,
  and comment composer are visible and navigable.
- Path and Flow step destructive actions now expose explicit Delete labels and
  native confirmation dialogs; cancel was verified from the packaged app without
  deleting user data.
- Skills was inspected in the packaged app. Learned skill matches, library
  counts, search, pagination state, enabled/available rows, and the detail sheet
  were verified with a `paper` search.
- Skills pending-draft review was verified against the real packaged app's
  managed API while Sleep Display remained locked. A temporary authored draft
  appeared as disabled, `pending`, and outside the prompt index; approving it
  through the operator skill control moved it to `approved`, enabled, and
  prompt-visible; disabling and deleting the exact temporary draft removed it
  from the catalog again. The release contract now also pins that Skills owns
  affinity/library/draft review presentation while Settings does not duplicate
  the Skills summary surface.
- Messaging was inspected in the packaged app. WeChat QR startup now surfaces a
  visible connection failure instead of hanging, and Feishu exposes local secure
  credential fields plus save/connect controls; live transport remains blocked
  by network/device/credential availability.
- Herd was inspected in the packaged app. Mother and baby elephant rows, runtime
  status, Codex/Gemini/Copilot/Hermes engine choices, tools, skills, prompt, and
  local CLI baby configuration tabs are editable from the native sheet.
- Usage was inspected in the packaged app. Token totals, token-flow chart,
  recent event rows, and the day/week aggregation toggle all render against real
  usage events.
- Calendar was inspected in the packaged app. Week, Month, and Year views,
  reminder rows, system Run/Pause controls, New Reminder open/cancel, and event
  detail popovers were verified without mutating reminder data.
- Calendar user reminder create, pause, delete, and cleanup were verified from
  the packaged app/API against a temporary reminder. A second temporary
  reminder exposed a false-success Run result when the cron runtime bridge was
  unavailable; the rebuilt app now renders that result as an orange unavailable
  error state instead of a green success.
- Calendar Year view accessibility was fixed and re-verified in the rebuilt app:
  non-event mini-calendar dates are no longer exposed as hundreds of disabled
  buttons, while event dates remain actionable with a full date/reminder label
  and a working detail popover.
- Learn was inspected in the packaged app. Background status cards, focused
  evolution job launchers, completed history rows, and needs-attention details
  were visible and expandable without creating a new learning job.
- Learn focused evolution was executed from the rebuilt packaged app. The Home
  Learn readiness card navigated to Learn, Skill Matching entered the running
  state, disabled duplicate launchers, streamed tool progress into storage,
  completed successfully, updated skill affinity memory, returned the UI to
  Ready, and left the worker stopped.
- The Learn run exposed and fixed a background-learning self-trigger loop:
  learning sub-agent child Episodes were closing through the canonical Episode
  state machine and enqueueing new `episode_close` learning jobs. The close path
  now suppresses learning enqueue for internal/learning-agent Episodes, and the
  rebuilt app verified that a completed manual learning job did not create a
  follow-on `episode_close` job after a wait window.
- Settings was inspected in the packaged app after a real runtime restart.
  Language, model provider, voice, memory engine, tools, history, sleep, logs,
  reset, advanced runtime, and system config rows were visible and expandable;
  reset was inspected without executing destructive data removal, and unchanged
  config state kept Save/Reset disabled.
- The app's menu bar was inspected and exercised in the real app. File > New
  chat opened a fresh conversation, Navigate jumped to Usage, Actions > Sleep
  Display entered the native sleep display and returned cleanly, and Actions >
  Reveal Database handed off to Finder.
- Restart Core was exercised from Settings. The app process stayed alive while
  the managed API child process moved from the old port to a new loopback port,
  and Settings returned to a verified runtime state.
- After the runtime restart, Chat sent a fresh real model turn through the
  packaged app. The visible activity card advanced from live to done, the model
  reply used a Personal Model fact about the user, and SQLite Step records
  confirmed `record_input`, `assemble_context`, `call_model`, and
  `emit_response` completed.
- Window behavior was checked at the enforced minimum window size, a wider
  desktop size, and native fullscreen. Home and Settings remained scrollable,
  text and controls did not incoherently overlap, and exiting fullscreen
  returned to a normal window.
- Quit cleanup was re-verified after the session: the app process and its
  managed API child process both exited, leaving no duplicate loopback API.
- The macOS packaged Python runtime exposed why Personal Model semantic search
  had stayed empty: the app bundle installed `torch 2.2.x` under Python 3.12,
  and ModernBERT loading failed through the `torch.compile`/Dynamo path. The
  rebuilt bundle now carries a Python 3.12-compatible embedding stack
  (`sentence-transformers 5.5.1`, `transformers 4.57.6`, `torch 2.6.0`,
  `torchaudio 2.6.0`, and `numpy 1.26.4`), and the embedding provider also
  avoids numpy conversion on the hot path.
- The rebuilt packaged app was launched through the real macOS shell and its
  managed API. Startup semantic backfill populated the previously empty durable
  index with 80 indexed entries: 48 Personal Model claims, 28 Episode summaries,
  and 4 Step recall documents. `/v1/internal/dashboard/evidence` reported
  `semantic_index_health.entry_count = 80`, provider
  `elephant-local-embed`, and `embedding_bootstrap_status = ready`.
- The packaged voice runtime was verified beyond import success. The FunASR
  health check loaded the local Chinese recognition model chain
  (`paraformer-zh`, `fsmn-vad`, and `ct-punc`) through the app bundle's Python
  runtime, then transcribed a generated Mandarin audio sample as
  "你好，大象，请记住我今天在回归测试语音对话。" with punctuation. The Edge
  online voice helper produced a readable MP3 reply asset that macOS audio
  tooling identified as a 24 kHz MP3.
- The real app was relaunched after the voice helper checks and was sitting in
  Sleep Display. A wrong-password unlock attempt showed the expected
  `That password does not match.` inline error, the managed API child process
  stayed healthy, semantic index health still reported 80 ready entries, and no
  newer Elephant Agent crash report appeared. Full Chat/Settings voice control
  re-inspection remains gated by the user's lock password or an explicit local
  state reset.
- Menu Refresh and Reflect were exercised from the real packaged app while the
  window remained in Sleep Display. `Command-R` refreshed dashboard state
  without creating a learning job, and the managed API stayed healthy.
  `Shift-Command-R` created one `manual` Reflect job
  (`learning-job:7ff576f0b36d4ef8a0075080a3b8f55b`), streamed tool progress,
  completed successfully, and made no duplicate durable Personal Model,
  question, or skill-affinity writes. No recursive `episode_close` learning job
  was created after the manual menu Reflect run, semantic index health remained
  ready with 80 entries, and no newer Elephant Agent crash report appeared.
- Learn Dream and Letter variants were executed through the real packaged app's
  managed API while Sleep Display remained locked. The Dream run
  (`learning-job:c2a8ba142ec541ca94332528b717bbcc`) resolved the full
  `dream,questions,skill_affinity,skill_evolution,diary` feature bundle,
  streamed tool progress, completed successfully, and wrote the 2026-05-29
  diary entry "A Quiet Page Between Threads" without duplicating Personal Model
  changes. The Letter run
  (`learning-job:9def1a3f37f843feb16ebe38ff44fcac`) completed and wrote the
  2026-05-30 onboarding letter diary entry. Only those two Learn jobs were
  created in the window, the managed API stayed healthy, semantic index health
  advanced to 82 ready entries, and no newer Elephant Agent crash report
  appeared.
- The rebuilt packaged app exposed and fixed a managed-API recall regression
  found during the voice/memory acceptance pass: `POST
  /v1/episodes/{episode_id}/recall/search` returned a 400 because the API
  adapter passed an obsolete `episode_id` field into `UnifiedRecallRequest`.
  The runtime now resolves the calling Episode's Personal Model and State scope
  before invoking unified recall, wires the durable semantic searcher into the
  API path, and returns source fields for search hits. After rebuilding and
  relaunching the real `.app`, the managed API returned hits for diary
  reflection, onboarding-letter, and voice-crash-recovery recall queries;
  `/healthz` remained healthy, semantic index health reported 86 ready entries,
  and no newer Elephant Agent crash report appeared.
- Sidebar menu command coverage was tightened and verified in the rebuilt real
  app. The app no longer relies on the inert default `SidebarCommands()` path
  for its custom sidebar; the standard View menu now exposes `Show or Hide
  Sidebar` through a command group wired to the app's sidebar notification. In
  Sleep Display, the real menu item was present, enabled, and clicked from the
  macOS menu bar; the app process stayed alive, the managed API remained
  healthy, and no newer Elephant Agent crash report appeared. Visual sidebar
  collapse/restore under unlocked content remains part of the broader design
  pass.
- Personal Model claim lifecycle was exercised through the real packaged app's
  managed API and kernel tool runtime while Sleep Display remained locked. A
  temporary `world.projects.*.status` QA claim was created with
  `tool.personal_model.update`, found through `tool.personal_model.search`,
  corrected into a superseding claim, retired, restored, and deleted. Cleanup
  deleted both the original and superseding refs, marked their Personal Model
  semantic-index entries deleted, and a recall search for the temporary marker
  returned zero hits. The app and managed API stayed alive throughout.
- A Chat/acceptance episode creation regression was fixed and verified against
  the rebuilt packaged app's managed API. `POST /v1/episodes` with
  `profile_id=you` and the macOS Chat session display name now opens an Episode
  without overwriting the existing Personal Model identity. The real managed API
  response returned Personal Model display name `You`, the SQLite
  `personal_models` row stayed `you|You` before and after the request, and
  `/healthz` remained healthy.
- Runtime Config save/restore was exercised through the real packaged app's
  managed API while Sleep Display remained locked. A temporary
  `extensions.acceptance_settings_roundtrip` marker was written through
  `/v1/operator/config`, appeared in the Settings snapshot and YAML, and was
  then restored with the original YAML byte-for-byte. The managed API remained
  healthy and no newer macOS crash report appeared.
- Path learning-memory lifecycle was verified through the rebuilt real packaged
  app's managed API while Sleep Display remained locked. A temporary Path,
  Flow step, comment, queued run, learning summary, and understanding check
  were created; the step moved to Done after the understood check, the learning
  summary wrote a `path:learning_summary:*` semantic-index row in the Personal
  Model scope with the temporary marker, and deleting the Path marked that
  semantic row `deleted` with the Path retention lifecycle metadata. The managed
  API remained healthy and no newer macOS crash report appeared.
- Diary memory lifecycle was verified through the rebuilt real packaged app's
  managed API and packaged runtime while Sleep Display remained locked. A
  temporary future-dated Diary entry was written with source episode provenance,
  appeared through the managed Diary dashboard with `source_episode_ids`, wrote
  a Personal Model-scoped `diary:*` semantic-index row, and deletion through the
  managed API removed the Diary row while marking the semantic row `deleted`.
  The managed API remained healthy and no newer macOS crash report appeared.
- Learn launcher state was hardened and rebuilt in the real packaged macOS app.
  Dream, Letter, Diary, Settings Reflect, and onboarding-letter regeneration now
  share the same active-learning gate, so existing queued/running learning jobs
  keep launchers disabled until the dashboard snapshot reports no active jobs.
  The packaged app's managed reflect snapshot showed the worker stopped, zero
  queued/running jobs, and recent Dream/Letter jobs completed. Sleep Display
  remained locked, so unlocked visual reinspection of those buttons is still a
  user-controlled gate rather than a completed UI proof.
- Home readiness card behavior was hardened and rebuilt in the real packaged
  macOS app. The readiness strip now uses an adaptive grid instead of a fixed
  four-column squeeze, surfaces status text inside each card, permits two-line
  detail text, and exposes an accessibility hint naming the owning surface each
  card opens. The packaged app launched with its managed API healthy and no
  newer crash report appeared; Sleep Display remained locked, so unlocked Home
  visual reinspection is still pending.

## Open Acceptance Matrix

| Surface | Required Proof | Status |
| --- | --- | --- |
| Home | First viewport is useful in under two seconds; readiness cards navigate to owning surfaces. | Partial; Personal Model presence, map, readiness strip, continuity context, and responsive/accessibility-hardened readiness navigation verified; unlocked Home visual reinspection still needs current evidence |
| Chat | Text, image, voice, history, queue, streaming activity, and markdown response behavior verified. | Partial; text, image attachment, history open, live activity, memory-backed real model reply, step records, managed-API recall search, and episode identity preservation verified |
| Voice | Native permissions, start/stop/cancel/send, local transcription fallback, and reply playback verified. | Partial; permission timeout, cancel, stale callback guards, packaged FunASR health, generated-audio Chinese transcription, and Edge TTS reply asset verified; live Chat send/playback UI is gated by Sleep Display unlock |
| You | Facts, questions, source evidence, correction, retire/recover/delete, and map interactions verified. | Partial; facts, evidence separation, question actions, map detail, reply cancel, durable semantic index recovery, managed-API recall query, and managed-API correction/retire/recover/delete lifecycle verified |
| Diary | Read/write Markdown diary entries and learning linkage verified. | Complete; Markdown render, date picker, write queue, source provenance, semantic indexing, managed-API read/delete, and deleted-Diary memory cleanup verified |
| Paths | Path board, step detail, comments, run, learning summaries, and trust prompts verified. | Partial; board, detail tabs, comment composer, comment API, queued run API, run affordance, safe delete confirmation, learning summary semantic indexing, understanding check, and deleted-Path memory cleanup verified |
| Skills | Search, pagination, skill detail, pending evolution drafts, and no duplicate settings summaries verified. | Partial; search, pagination state, detail sheet, enabled/available rows, learned matches, pending draft projection/approval lifecycle, and no duplicate Settings summary contract verified; unlocked pending-row visual reinspection remains gated by Sleep Display |
| Messaging | WeChat QR, Feishu/Discord/DingDing/WeCom setup controls, start/stop, and status UX verified where credentials allow. | Partial; WeChat failure UX and Feishu setup verified; live transport blocked by credentials/network/device |
| Herd | Mother and baby runtime editing, provider/local CLI babies, delegation, and expanded row editability verified. | Complete for native edit surface |
| Usage | Token trend chart and row detail verified with real usage events. | Complete |
| Calendar | Week, Month, Year views plus create/run/pause/delete job controls verified. | Complete for native controls; Week/Month/Year, create, pause, delete, event popover, system controls, and Run unavailable error UX verified |
| Learn | Reflect/dream/diary jobs, progress, summaries, and understood checks verified. | Partial; focused Skill Matching UI run, diary queue, launcher disable/re-enable, active-job launcher gating, progress/status, history, needs-attention detail, managed-API Dream execution, and managed-API Letter execution verified; unlocked Dream/Letter button state still needs UI reinspection |
| Settings | Language, voice, provider, memory, curiosity, history, sleep, logs, reset, runtime, and config editing verified. | Partial; language, provider, voice, memory, tools, history, sleep, logs, reset, runtime, config surface, and managed-API config save/restore verified; unlocked editor button/draft state covered by static contract |
| Menus | New Chat, Reflect, Refresh, Reveal Database, Restart Core, sidebar, navigation, and Sleep Display verified. | Complete for native command coverage; New Chat, Navigate, Sleep Display, Reveal Database, Restart Core, Refresh, Reflect, and the custom sidebar command were verified |
| Runtime | Managed PID ownership, stale cleanup, restart, quit cleanup, and no duplicate loopback APIs verified. | Complete |
| Design | Native IA, text fit, accessibility labels, no internal-only first-level nav, and resized/fullscreen layouts verified. | Partial; first-level IA, minimum-size, wide-window, fullscreen Home/Settings behavior, and Home readiness responsive/accessibility contract verified |

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

## Episode Identity Preservation Fix Track

- Treat `POST /v1/episodes` as an Episode-open operation when the Personal
  Model already exists.
- Do not let transient session display names such as Chat overwrite durable
  Personal Model display name, preferences, enabled capabilities, or learning
  intensity.
- Keep explicit identity changes on the identity/profile API surfaces where
  they can be audited as user-directed profile edits.

## Runtime Config Save State Fix Track

- Treat each Runtime Config save as a new operation by clearing stale success
  state before sending the write request.
- After a successful save and dashboard refresh, resync the editor draft from
  the Settings snapshot so normalized YAML does not keep the Save and Reset
  controls enabled.
- Preserve unsaved local edits when unrelated Settings refreshes arrive before
  an explicit successful save.

## Paths Safety Fix Track

- Label icon-only destructive controls as Delete Path or Delete Flow step for
  assistive technology instead of generic close controls.
- Require a native confirmation dialog before deleting a Path or Flow step.
- Keep cancel non-mutating and verify it from the packaged app before shipping.

## Path Learning Memory Fix Track

- Index Path learning summaries as Personal Model-scoped recall material
  because they are durable user-facing takeaways, not state-scoped Episode
  traces.
- Include existing Path learning summaries in startup semantic backfill so
  upgraded runtimes recover previous Path learning memory.
- When a Path or Flow step is deleted, mark the corresponding
  `path:learning_summary:*` semantic-index rows deleted so removed Paths cannot
  remain active recall material.

## Calendar Accessibility Fix Track

- Keep the Year view visually dense while avoiding hundreds of disabled
  mini-calendar day buttons in VoiceOver and keyboard navigation.
- Expose only scheduled event days as actionable controls in the Year view, with
  a full date/reminder label and the same event detail popover as the visual UI.
- Keep non-event mini-calendar dates decorative in the accessibility tree.

## Calendar Run Feedback Fix Track

- Treat a 200 response from the cron Run endpoint as a transport success only;
  parse the nested run outcome before showing user-facing success.
- Show unavailable or failed cron run outcomes with warning styling and a clear
  detail message.
- Keep successful create, pause/resume, and delete actions on the existing
  green confirmation path.

## Diary Source Linkage Fix Track

- Preserve source episode IDs emitted by conversation recall into diary writes.
- Include source provenance lines in recall summaries so the model can carry
  evidence into the diary tool call.
- Fall back to current episode/session ID in the diary write tool when the model
  omits explicit sources.
- Index Diary entries as Personal Model-scoped recall material so reflective
  daily learning can shape future help.
- When a Diary entry is deleted, mark the corresponding `diary:*`
  semantic-index rows deleted so removed reflections cannot remain active recall
  material.

## Learning Recursion Fix Track

- Keep normal user Episodes eligible for `episode_boundary_learning` on close.
- Suppress learning enqueue for internal learning-agent child Episodes in the
  canonical Episode close path, not only in the foreground kernel enqueue layer.
- Preserve internal metadata such as event type, owner scope, and context mode
  on Episodes so close-path side effects can distinguish user-facing work from
  background work.
- Verify from the packaged app that a manual Learn job completes without
  creating recursive `episode_close` jobs.

## Learn Launcher State Fix Track

- Treat queued and running learning jobs from the dashboard snapshot as active
  launch state, not only the short local HTTP request window.
- Disable Dream, Letter, Diary, Settings Reflect, and letter regeneration while
  a learning job remains active so users cannot accidentally stack duplicate
  background learning passes.
- Re-enable launchers only after the managed API reports no queued/running
  learning jobs.

## Home Readiness Navigation Fix Track

- Keep Home readiness cards readable at narrow window widths by adapting the
  grid instead of forcing four compressed columns.
- Show status text directly inside each card, not only through color.
- Expose the card detail and destination surface through tooltip and
  accessibility hints so readiness cards are clearly navigation controls.

## Skills Review Surface Contract Track

- Keep learned skill affinities, library search, pagination, and draft review on
  the primary Skills surface.
- Sort pending evolution drafts before normal enabled/available rows and expose
  explicit pending counters, review copy, and Approve affordances.
- Keep Settings focused on configuration surfaces such as Tools and Runtime
  Config instead of duplicating the Skills library or affinity summary.

## Semantic Index Recovery Fix Track

- Keep the macOS packaged embedding runtime compatible with the ModernBERT local
  embedding model on Python 3.12.
- Avoid numpy-dependent tensor conversion in the local embedding provider so
  packaged torch/numpy ABI drift cannot disable recall.
- Backfill existing Personal Model claims, closed Episode summaries, and recent
  useful Steps into the durable semantic index at runtime startup without
  blocking app launch.
- Verify from the packaged app and managed API that semantic index health is
  non-empty and ready.

## Voice Runtime Regression Track

- Keep bundled voice dependencies importable under the packaged Python runtime,
  including `funasr`, `edge_tts`, `torch`, `torchaudio`, and `numpy`.
- Verify local Chinese recognition by loading the actual FunASR model chain,
  not only by checking Python imports.
- Exercise a real audio file through the packaged transcription helper and keep
  the recognized text useful enough to send as a Chat draft.
- Verify the online reply-voice helper produces a playable audio asset, while
  preserving the app's local AVSpeech fallback path for online failures.
- Treat Sleep Display and microphone permission prompts as user-controlled
  gates; verify graceful locked/permission states without bypassing privacy.

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
