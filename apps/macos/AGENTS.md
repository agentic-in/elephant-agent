# Elephant macOS App Rules

- This directory owns the native macOS desktop shell only.
- Keep durable understanding logic in `packages/` and API behavior in `apps/api/`; the desktop app may orchestrate and visualize but must not redefine Personal Model truth.
- Prefer SwiftUI for product UI and small AppKit bridges for native macOS behavior such as windows, panels, menus, notifications, and reveal-in-Finder.
- The app should launch the local Python API through the existing `apps.api` entrypoint instead of embedding business logic in Swift.
- Reuse brand assets from `apps/site/static/assets` at build time rather than duplicating binary assets in source control.
- DMG-installed users must be able to open the app and get a local backend by default. When no developer repository is available, the app should bootstrap or reuse `~/.elephant/venv` through the bundled `install.sh`, then start `apps.api` from that runtime.
- The macOS app must treat the local API as a managed child process. Record the managed PID with an app-instance owner token, clean up stale managed and orphaned macOS API processes before launching a new one, and terminate it decisively on quit/restart so repeated app launches do not leave random loopback APIs behind. A stale or duplicate App instance must not remove another active instance's pidfile.

## Design North Star

- Use the installed `macos-app-design` skill for any meaningful UX/UI change in this directory.
- Treat Elephant Agent as a native macOS `library + detail` companion, not a website, dashboard, or slide-style presentation.
- The first screen should make the product feel alive within two seconds: a local Personal Model presence, a clear Chat affordance, visible memory/questions/evidence, and no marketing copy.
- Prefer Apple system components, system colors, SF Symbols, native text controls, real menu commands, and fluid window resizing before custom chrome.

## Information Architecture

- The sidebar exposes core user concerns that are frequent, user-facing, or operationally important: Home, Chat, You, Diary, Skills, Messaging, Herd, Usage, Calendar, Learn, Settings.
- Keep provider internals, tool pagination, curiosity cadence, logs, diagnostics, database paths, and runtime controls in Settings. Settings should stay real and actionable, not a museum of mock rows.
- Settings must include an editable global runtime config surface backed by `/v1/operator/config`; do not strand config changes in dashboard-only flows or terminal-only workflows.
- Dashboard route mapping for the app is intentional: `You`, `Diary`, `Chat`, `Herd`, `Skills`, `Usage`, `Messaging`, `Cron` as `Calendar`, and `Reflect/Learn` become sidebar destinations; `Models`, `Tools`, `Curiosity`, `History`, diagnostics, and low-frequency runtime controls remain expandable Settings sections.
- Home is a calm command surface, not a metric dashboard. It should answer: Is Elephant awake? What can I ask? What needs review?
- Home should expose a compact readiness strip for high-impact state: model/provider, memory/evidence, messaging, and learning. Each readiness item must be a real navigation affordance to the owning surface instead of a passive status badge.
- Home must include a Personal Model continuity strip before the detailed tables: what is alive now, how Elephant should be with the user, care/boundary context, and the next useful open question. This mirrors the dashboard home semantics without reintroducing dashboard chrome.
- Home must include dashboard-style "What I know so far" as a structured basics table, backed by PM claim topics with `user_profile` fallback, then the four lens shelves and the Personal Model map. Do not show Respond Queue or Next cards on Home.
- Home's primary identity card belongs to the user, not the Elephant state. Show the user's Personal Model name and local profile photo there; the photo is chosen during onboarding and can be changed by clicking the avatar.
- Personal Model maps must center the user or "You"; Elephant state names belong in Herd/settings, not at the center of user modeling.
- Chat is the primary working surface. Use a library/detail structure when thread context is visible: thread list on the left, conversation/editor on the right.
- Chat conversations should feel close to ChatGPT/Codex: flexible height, scrolling transcript, Markdown-rendered assistant text, a focused composer, minimal user bubbles without a `You` label, real-time tool call / tool execute trace while a loop is running, and no raw trace JSON in the conversation.
- Chat running copy should describe user-visible activity, not implementation plumbing. Prefer "tool activity" or "next step" over "tool trace" in empty waiting states.
- Chat history must be user-manageable from the thread rail. If the backend has no hard-delete endpoint, desktop-local deletion may hide a thread from the app history without deleting underlying Personal Model or episode records.
- Chat voice input should use native macOS microphone and Speech recognition permissions, transcribing directly into the composer instead of introducing a separate audio workflow.
- You is the Personal Model surface. Keep reviewed facts, open questions, and source-backed evidence visually separate. Open questions live in a dedicated Question Field with ready/asked/learned/dismissed states and direct answer/surface/dismiss actions; do not bury them inside fact cards.
- You should include a compact Personal Model map and four Personal Model partitions for Identity, World, Pulse, and Journey. PM facts live inside those partitions with pagination/disclosure and support correct, retire, recover, and delete actions.
- Diary entries must render Markdown, default expanded, and support writing for a chosen date.
- Messaging must align with dashboard IM support. WeChat uses QR start/poll; Feishu, Discord, DingDing, and WeCom expose credential configuration and start/stop controls.
- Calendar owns scheduled cron prompt jobs from the app, agents, and system learning schedules. It should expose Week, Month, and Year views before raw job rows, and keep create/run/pause/delete job controls visible beside the calendar instead of burying them below the fold. Learn owns reflect/dream/diary learning runs and their history.
- Calendar event marks should stay dense: show scheduled jobs as thin horizontal bars with small labels in the grid, and reveal schedule/detail/status in an inspector only after selection. Avoid large event cards inside day cells because cron-heavy calendars must stay readable.
- Usage should make token spend legible with charts before raw rows.
- Do not expose local source import or evidence-staging surfaces until Elephant can actually learn from them. Prefer explicit conversations, profile links, diary, and reflect jobs for current Personal Model learning.
- Herd rows default to expanded for editability, but never expose hidden metadata comments or internal scaffolding text in user-facing fields.
- Skills Library must support search and pagination so large installed skill sets remain usable without turning Settings into a long static dump.
- Skills Affinity belongs on the Skills surface only. Do not repeat affinity summaries at the bottom of Settings skill-library sections.

## Visual System

- Use restrained native materials for navigation and controls. Do not stack glass or decorative cards inside cards.
- Content surfaces should be quiet and readable: light canvas, animated low-opacity mosaic field, 8px corner radius, thin separators, generous whitespace.
- Animation should express "living memory": a slow whole-canvas mosaic shift and faint graph/network state changes. Avoid floating decorative dots, blobs, bokeh, or loud marketing gradients.
- Use one primary accent, defaulting to system blue or `ElephantTheme.accent`. Use green for healthy/connected, orange for attention/unknown.
- Brand through the Elephant presence, memory orbit, copy, and evidence model. Do not add generic hero art, mascot-heavy panels, or web landing-page sections.
- Use existing Elephant artwork sparingly. The logo can anchor identity; photographic Elephant assets should appear as a quiet contextual texture or presence cue, never as a loud marketing hero.
- Keep Home free of runtime internals. Core/provider/worker/API/database belong in Settings unless the state blocks the current user workflow.
- Text must use system scale and fit under resize. Avoid viewport-style oversized hero typography except for the Home command line.

## Mac Citizen Requirements

- Keep the standard macOS menu bar useful: App/File/Edit/View/Navigate/Actions/Window/Help plus Settings via the Settings scene and Cmd-comma behavior.
- Every primary command must exist in the menu system or toolbar: New Chat, Reflect, Refresh, Reveal Database, Restart Core.
- Toolbar actions must stay few and high-frequency. Demote secondary or diagnostic actions to Actions or Settings.
- When the sidebar is visible, sidebar visibility belongs inside the left navigation rail, directly above Settings. When the sidebar is hidden, remove the rail entirely and expose a small restore control in the titlebar cluster near the traffic-light controls.
- Preserve native window behavior: resize, fullscreen, minimize, and tabbing where possible. When using a transparent full-size titlebar, keep the main content clear of traffic-light controls and avoid leaving a narrow collapsed sidebar stub.
- Custom controls need accessibility labels and keyboard/focus behavior. Prefer system `Button`, `TextField`, `Picker`, `List`, `NavigationSplitView`, and `Settings`.
- Sidebar and icon-only controls must have forgiving hit targets, hover/pressed feedback, `help` tooltips, and accessibility labels. Users should not need to click the exact glyph.

## Validation

- Run `make macos-build` for desktop UI work. This is the canonical local app build target and prints the absolute `.app`, `.dmg`, and release artifact paths. Do not call `swift build` or `apps/macos/Scripts/build-app.sh` directly unless debugging the target itself.
- When a screenshot-driven visual change is made, open the built app and inspect Home, Chat, You, Diary, Learn, Settings at the current window size and fullscreen.
