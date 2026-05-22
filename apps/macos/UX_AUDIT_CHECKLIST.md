# Elephant macOS UX Audit Checklist

Use this checklist before and after screenshot-driven desktop UX work. The goal is a native Mac companion that feels personal, calm, and immediately useful.

## First Impression

- The first visible screen shows the user, the local Personal Model, and a clear chat affordance within two seconds.
- The page reads as a native macOS app, not a web dashboard or marketing page.
- The Elephant brand appears through presence, memory, copy, and motion; avoid mascot-heavy or decorative-only treatment.
- Home avoids raw runtime internals unless a blocker affects the user's next action.

## Interaction

- Every icon-only control has a forgiving hit target, hover/pressed feedback, help text, and an accessibility label.
- Primary actions are obvious without explanatory tutorial copy.
- Disabled states explain the missing requirement with help text or nearby status.
- Chat always keeps the composer visible, focused, and visually stronger than decorative empty-state content.
- Destructive or privacy-sensitive actions use native confirmation and user-facing language.

## Visual System

- Panels use 8px radii, thin separators, and quiet materials. Do not stack cards inside cards.
- Accent color is used for focus and primary action only; green means healthy/connected, orange means attention.
- Animation suggests living memory and respects Reduce Motion.
- Text fits at the minimum supported window size and does not rely on viewport-scaled typography.

## Product Language

- Home, Chat, You, Diary, Learn, and Sleep Display describe user value, not implementation plumbing.
- Provider, runtime, logs, database, worker, and diagnostics language stays in Settings unless the state blocks work.
- Questions and memory copy should feel correctable and user-owned.
- Setup copy should make a profile feel like it is forming, not like a long form is being completed.

## Validation Pass

- Inspect Home, Chat, You, Diary, Learn, Settings, and Sleep Display at the current window size.
- Repeat inspection in fullscreen.
- Verify sidebar navigation, Chat history open/close, quick prompts, composer focus, voice button, send enabled/disabled, onboarding back/next, and Sleep Display wrong-password feedback.
- Confirm Reduce Motion does not leave essential state dependent on animation.
