# Desktop App Rules

- `apps/desktop` owns the Tauri desktop shell only. Keep product logic in the Python core/API and React dashboard unless a behavior is genuinely OS-shell-specific.
- Keep OS-specific behavior behind narrow Rust helpers or commands so Windows/Linux support can add alternate implementations without changing dashboard code.
- The desktop shell may manage windows, local process lifecycle, app data paths, notifications, file/folder picking, and reveal/open actions.
- Prefer reusing `apps/dashboard/dist` for production WebView content and `apps.api` for the local core. Do not duplicate Personal Model, Episode, Step, or learning semantics in Rust.
