from __future__ import annotations

import asyncio
import threading
import time
from typing import TYPE_CHECKING

from .shell_clipboard import (
    compile_submission,
    import_system_clipboard,
    build_text_attachment,
)
from .shell_stack import (
    Application,
    BeforeInput,
    Buffer,
    BufferControl,
    CompletionsMenu,
    Condition,
    ConditionalContainer,
    Dimension,
    FileHistory,
    FormattedText,
    FormattedTextControl,
    HSplit,
    KeyBindings,
    Keys,
    Layout,
    PROMPT_TOOLKIT_AVAILABLE,
    PromptSession,
    ScrollablePane,
    Style,
    Window,
    has_completions,
    prompt_toolkit_output_without_cpr,
)
from .shell_ui import (
    BRAND_ACCENT,
    BRAND_ACCENT_STRONG,
    BRAND_DARK,
    BRAND_LIGHT,
    BRAND_MUTED,
    COMMAND_PALETTE_VISIBLE_ROWS,
    LIVE_DIFF_ADD_FG,
    LIVE_DIFF_CONTEXT_FG,
    LIVE_DIFF_FILE_FG,
    LIVE_DIFF_HUNK_FG,
    LIVE_DIFF_REMOVE_FG,
    USER_HISTORY_BG,
    USER_HISTORY_FG,
)

if TYPE_CHECKING:
    from .shell import ProductizedShell


def prompt_toolkit_loop_running() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def run_prompt_toolkit_application(application):
    if prompt_toolkit_loop_running():
        return application.run(in_thread=True)
    return application.run()


def run_prompt_toolkit_prompt(session, *args, **kwargs):
    if prompt_toolkit_loop_running():
        kwargs = dict(kwargs)
        kwargs["in_thread"] = True
    return session.prompt(*args, **kwargs)


def prompt_toolkit_composer_available(shell: ProductizedShell) -> bool:
    if not PROMPT_TOOLKIT_AVAILABLE:
        return False
    return not any(
        component is None
        for component in (
            Application,
            Buffer,
            BufferControl,
            Condition,
            BeforeInput,
            ConditionalContainer,
            CompletionsMenu,
            Dimension,
            FormattedTextControl,
            HSplit,
            Layout,
            Window,
            has_completions,
        )
    )


def shell_history(shell: ProductizedShell):
    return FileHistory(str(shell.runtime.paths.state_dir / "shell-history.txt"))


def build_prompt_buffer(shell: ProductizedShell):
    from .shell import ShellCompleter

    # Wrap the completer so completion work runs on a thread instead of
    # blocking the UI loop on every keystroke. Cheap for the shell
    # (commands are short lists) but meaningful smoothness win.
    try:
        from prompt_toolkit.completion import ThreadedCompleter

        completer = ThreadedCompleter(ShellCompleter(shell))
    except Exception:
        completer = ShellCompleter(shell)

    return Buffer(
        multiline=True,
        completer=completer,
        complete_while_typing=True,
        history=shell_history(shell),
    )


def build_input_window(shell: ProductizedShell, buffer):
    def _prompt_prefix() -> str:
        # Stateful emoji: idle path vs. active elephant while Elephant Agent is working.
        turn_active = shell._turn_started_at is not None
        streaming = bool(getattr(shell, "_streaming_response_active", False))
        return "🐘 › " if (turn_active or streaming) else "🐾 › "

    return Window(
        BufferControl(
            buffer=buffer,
            input_processors=[BeforeInput(_prompt_prefix, style="class:composer-prefix")],
            focus_on_click=True,
        ),
        wrap_lines=True,
        dont_extend_height=True,
        height=Dimension(min=1, preferred=1, max=6),
    )


def _composer_input_meta_fragments(shell: ProductizedShell, buffer):
    """Tiny right-aligned meta line under the input while multiline.

    Only rendered when there's meaningful feedback to show — keeps the
    single-line idle state completely uncluttered.
    """
    text = buffer.text or ""
    if not text:
        return []
    lines = text.count("\n") + 1
    chars = len(text)
    fragments: list[tuple[str, str]] = []
    if lines > 1:
        fragments.append(("class:status-bar-muted", f"   {lines} lines"))
        if chars >= 240:
            fragments.append(("class:status-bar-muted", f" · {chars:,} chars"))
        fragments.append(("class:status-bar-muted", "   ⌥+Enter = newline  ·  Enter = send"))
    elif chars >= 240:
        fragments.append(("class:status-bar-muted", f"   {chars:,} chars"))
    return fragments


def _ghost_hint_match(shell: ProductizedShell, text: str) -> tuple[str, str] | None:
    """Return (completion_tail, description) for the best slash-command match.

    - Only fires for buffers starting with `/` and having no space yet
      (i.e., the user is still typing the command name itself).
    - Picks the first spec whose name starts with the current prefix
      (case-insensitive). Ties broken by spec order — built-in commands
      first, then skills.
    - Returns None if the buffer already matches exactly (no completion
      to offer) or nothing starts with the prefix.
    """
    if shell is None or not text or not text.startswith("/"):
        return None
    first_line = text.split("\n", 1)[0]
    if " " in first_line:
        return None
    prefix = first_line.lower()
    candidates: list[tuple[str, str]] = []
    for spec in getattr(shell, "command_specs", ()) or ():
        candidates.append((spec.name, spec.description))
    for spec in getattr(shell, "_skill_slash_specs", ()) or ():
        candidates.append((spec.command, spec.summary))
    for name, description in candidates:
        name_lc = name.lower()
        if name_lc == prefix:
            return None
        if name_lc.startswith(prefix):
            tail = name[len(first_line) :]
            return tail, description
    return None


def _composer_ghost_fragments(shell: ProductizedShell, buffer):
    """Ghost-hint line shown below the input for slash-command guidance.

    Rendered as an extra meta row — `⇥ /status  —  where Elephant Agent stands
    right now`. Tab accepts the completion.
    """
    if _history_search_active(shell):
        return []
    match = _ghost_hint_match(shell, buffer.text or "")
    if match is None:
        return []
    tail, description = match
    if not tail and not description:
        return []
    fragments: list[tuple[str, str]] = [
        ("class:ghost-hint-prefix", "   ⇥ "),
    ]
    if tail:
        fragments.append(("class:ghost-hint-tail", tail))
    if description:
        fragments.append(("class:ghost-hint-desc", f"   — {description}"))
    return fragments


def build_input_meta_window(shell: ProductizedShell, buffer):
    try:
        from prompt_toolkit.layout import WindowAlign

        align = WindowAlign.RIGHT
    except Exception:
        align = None
    window_kwargs: dict[str, object] = {
        "content": FormattedTextControl(lambda: _composer_input_meta_fragments(shell, buffer)),
        "height": 1,
        "dont_extend_height": True,
    }
    if align is not None:
        window_kwargs["align"] = align
    return ConditionalContainer(
        content=Window(**window_kwargs),  # type: ignore[arg-type]
        filter=Condition(lambda: bool(buffer.text and ("\n" in buffer.text or len(buffer.text) >= 240))),
    )


def build_ghost_hint_window(shell: ProductizedShell, buffer):
    return ConditionalContainer(
        content=Window(
            FormattedTextControl(lambda: _composer_ghost_fragments(shell, buffer)),
            height=1,
            dont_extend_height=True,
        ),
        filter=Condition(lambda: _ghost_hint_match(shell, buffer.text or "") is not None),
    )


def _history_search_matches(shell: ProductizedShell, query: str) -> list[str]:
    """Unique history entries containing `query` (case-insensitive), newest first."""
    history_strings: list[str] = []
    try:
        history_strings = list(shell_history(shell).get_strings())
    except Exception:
        history_strings = []
    needle = query.strip().lower()
    seen: set[str] = set()
    matches: list[str] = []
    # Iterate newest-first. FileHistory preserves append order, so reverse.
    for entry in reversed(history_strings):
        if not entry or entry in seen:
            continue
        if needle and needle not in entry.lower():
            continue
        seen.add(entry)
        matches.append(entry)
    return matches


def _history_search_active(shell: ProductizedShell) -> bool:
    return bool(getattr(shell, "_history_search_active", False))


def _history_search_refresh(shell: ProductizedShell) -> None:
    query = getattr(shell, "_history_search_query", "") or ""
    matches = _history_search_matches(shell, query)
    shell._history_search_matches = matches
    if not matches:
        shell._history_search_index = 0
        return
    # Clamp index to the new result set.
    index = int(getattr(shell, "_history_search_index", 0) or 0)
    shell._history_search_index = max(0, min(index, len(matches) - 1))


def _history_search_enter(shell: ProductizedShell, buffer) -> None:
    """Enter reverse-search mode. Snapshot current buffer so Esc can restore."""
    shell._history_search_active = True
    shell._history_search_query = ""
    shell._history_search_index = 0
    shell._history_search_prior_text = buffer.text or ""
    _history_search_refresh(shell)


def _history_search_exit(shell: ProductizedShell, buffer, *, restore: bool) -> None:
    if not _history_search_active(shell):
        return
    shell._history_search_active = False
    if restore:
        buffer.text = getattr(shell, "_history_search_prior_text", "") or ""
    shell._history_search_query = ""
    shell._history_search_matches = []
    shell._history_search_index = 0


def _history_search_current_match(shell: ProductizedShell) -> str:
    matches = list(getattr(shell, "_history_search_matches", ()) or ())
    if not matches:
        return ""
    index = max(0, min(int(getattr(shell, "_history_search_index", 0) or 0), len(matches) - 1))
    return matches[index]


def _history_search_fragments(shell: ProductizedShell):
    if not _history_search_active(shell):
        return FormattedText([])
    query = str(getattr(shell, "_history_search_query", "") or "")
    matches = list(getattr(shell, "_history_search_matches", ()) or ())
    total = len(matches)
    index = int(getattr(shell, "_history_search_index", 0) or 0)
    # Compact preview — one-line match, truncated.
    preview = _history_search_current_match(shell)
    if len(preview) > 96:
        preview = preview[:95] + "…"
    fragments: list[tuple[str, str]] = [
        ("class:history-search-prefix", "🔍 search "),
        ("class:history-search-query", query or " "),
    ]
    if total:
        fragments.append(("class:history-search-meta", f"  [{index + 1}/{total}]"))
        fragments.append(("", "\n"))
        fragments.append(("class:history-search-hit", f"  → {preview}"))
    else:
        fragments.append(("class:history-search-empty", "   no match"))
    fragments.append(("", "\n"))
    fragments.append(
        ("class:history-search-hint", "   ↑/↓ cycle · Enter accept · Esc cancel"),
    )
    return FormattedText(fragments)


def build_history_search_window(shell: ProductizedShell):
    return ConditionalContainer(
        content=Window(
            FormattedTextControl(lambda: _history_search_fragments(shell)),
            wrap_lines=True,
            dont_extend_height=True,
        ),
        filter=Condition(lambda: _history_search_active(shell)),
    )


def build_command_palette(shell: ProductizedShell):
    return ConditionalContainer(
        content=CompletionsMenu(max_height=COMMAND_PALETTE_VISIBLE_ROWS, scroll_offset=1),
        filter=has_completions,
    )


def build_queue_preview_window(shell: ProductizedShell):
    return ConditionalContainer(
        content=Window(
            FormattedTextControl(lambda: shell._render_queued_followup_fragments()),
            wrap_lines=True,
            dont_extend_height=True,
        ),
        filter=Condition(lambda: bool(shell._pending_commands)),
    )


def _composer_clipboard_fragments(shell: ProductizedShell):
    attachments = tuple(getattr(shell, "_composer_paste_items", ()))
    if not attachments:
        return FormattedText([])
    fragments: list[tuple[str, str]] = [("class:clipboard-prefix", "paste ")]
    for index, attachment in enumerate(attachments):
        if index:
            fragments.append(("", " "))
        fragments.append(("class:clipboard-chip", attachment.display_label))
    return FormattedText(fragments)


def build_clipboard_preview_window(shell: ProductizedShell):
    return ConditionalContainer(
        content=Window(
            FormattedTextControl(lambda: _composer_clipboard_fragments(shell)),
            wrap_lines=True,
            dont_extend_height=True,
        ),
        filter=Condition(lambda: bool(getattr(shell, "_composer_paste_items", ()))),
    )


def build_divider_window(shell: ProductizedShell):
    return Window(
        FormattedTextControl([("class:composer-divider", shell._composer_divider())]),
        height=1,
        dont_extend_height=True,
    )


def build_status_window(shell: ProductizedShell):
    return Window(
        FormattedTextControl(lambda: shell._status_bar_fragments()),
        height=1,
        dont_extend_height=True,
    )


def _state_focus_notice_visible(shell: ProductizedShell) -> bool:
    if not shell._startup_should_surface_state_focus_notices():
        return False
    shell._sync_state_focus_runtime_notices()
    return bool(shell._state_focus_runtime_notices)


def _state_focus_notice_fragments(shell: ProductizedShell):
    if not _state_focus_notice_visible(shell):
        return FormattedText([])
    fragments: list[tuple[str, str]] = []
    for index, (title, body) in enumerate(shell._state_focus_runtime_notices):
        if index:
            fragments.append(("", "\n"))
        fragments.append(("class:state-focus-ready-title", title))
        fragments.append(("class:state-focus-ready-body", f" · {body}"))
    return FormattedText(fragments)


def build_state_focus_notice_window(shell: ProductizedShell):
    return ConditionalContainer(
        content=Window(
            FormattedTextControl(lambda: _state_focus_notice_fragments(shell)),
            wrap_lines=True,
            dont_extend_height=True,
        ),
        filter=Condition(lambda: _state_focus_notice_visible(shell)),
    )


def build_state_focus_notice_spacer(shell: ProductizedShell):
    return ConditionalContainer(
        content=Window(height=1, dont_extend_height=True),
        filter=Condition(lambda: _state_focus_notice_visible(shell)),
    )


def build_composer_body(
    shell: ProductizedShell,
    *,
    input_window,
    command_palette,
    top_windows=(),
    buffer=None,
):
    children = [
        build_state_focus_notice_window(shell),
        build_state_focus_notice_spacer(shell),
        *top_windows,
        build_status_window(shell),
        build_divider_window(shell),
        command_palette,
        build_clipboard_preview_window(shell),
        build_history_search_window(shell),
        input_window,
    ]
    if buffer is not None:
        children.append(build_ghost_hint_window(shell, buffer))
        children.append(build_input_meta_window(shell, buffer))
    children.append(build_divider_window(shell))
    body = HSplit(children)
    if top_windows and ScrollablePane is not None:
        return ScrollablePane(
            body,
            show_scrollbar=False,
            display_arrows=False,
        )
    return body


def _startup_transition_result(
    shell: ProductizedShell,
    *,
    buffer_text: str = "",
    idle_seconds: float = 0.0,
) -> str | None:
    if buffer_text.strip():
        return None
    if not shell._startup_state_focus_dispatch_ready():
        return None
    if getattr(shell, "_startup_prime_started", False):
        return None
    if not shell._startup_transcript_primed:
        ready_seen_at = getattr(shell, "_state_focus_runtime_ready_seen_at", None)
        if ready_seen_at is not None and time.monotonic() - ready_seen_at < 0.4:
            return None
        if shell._startup_user_turn_submitted and shell._pending_commands:
            return "__elephant.startup.prime__"
        if idle_seconds >= 1.5:
            return "__elephant.startup.prime__"
        return None
    if shell._pending_commands:
        return "__elephant.startup.dispatch-pending__"
    return None


def _clear_composer_paste_items(shell: ProductizedShell) -> None:
    getattr(shell, "_composer_paste_items", []).clear()


def _append_text_paste(shell: ProductizedShell, text: str) -> bool:
    attachment = build_text_attachment(text)
    if attachment is None:
        return False
    getattr(shell, "_composer_paste_items", []).append(attachment)
    return True


def _append_system_clipboard_paste(shell: ProductizedShell) -> bool:
    attachments = import_system_clipboard(storage_dir=shell.runtime.paths.state_dir / "clipboard")
    if not attachments:
        return False
    getattr(shell, "_composer_paste_items", []).extend(attachments)
    return True


def _compose_submission(shell: ProductizedShell, raw_command: str):
    attachments = tuple(getattr(shell, "_composer_paste_items", ()))
    submission = compile_submission(raw_command, attachments)
    _clear_composer_paste_items(shell)
    return submission


def read_command(shell: ProductizedShell) -> object:
    if not PROMPT_TOOLKIT_AVAILABLE:
        return input(f"{shell._composer_divider()}\n› ")
    if not prompt_toolkit_composer_available(shell):
        from .shell import ShellCompleter

        session = PromptSession(
            multiline=True,
            completer=ShellCompleter(shell),
            complete_while_typing=True,
            history=shell_history(shell),
            reserve_space_for_menu=COMMAND_PALETTE_VISIBLE_ROWS,
            output=prompt_toolkit_output_without_cpr(),
        )
        return run_prompt_toolkit_prompt(
            session,
            shell._prompt_label(),
            style=shell._prompt_style(),
            key_bindings=shell._build_key_bindings(),
            prompt_continuation=shell._prompt_continuation(),
            erase_when_done=True,
        )

    buffer = build_prompt_buffer(shell)
    application_holder: dict[str, Application] = {}
    stop_monitor = threading.Event()
    opened_at = time.monotonic()
    last_cron_check = 0.0

    def maybe_exit_for_startup_transition() -> None:
        application = application_holder.get("app")
        if application is None:
            return
        result = _startup_transition_result(
            shell,
            buffer_text=buffer.text,
            idle_seconds=max(0.0, time.monotonic() - opened_at),
        )
        if result is None:
            return
        if result == "__elephant.startup.prime__":
            if shell._startup_prime_started:
                return
            shell._startup_prime_started = True

            def _prime_in_background() -> None:
                try:
                    shell._prime_startup_transcript_if_needed()
                finally:
                    shell._startup_prime_started = False
                    try:
                        application.exit(result="__elephant.startup.prime__")
                    except Exception:
                        pass

            threading.Thread(
                target=_prime_in_background,
                name="elephant-startup-prime",
                daemon=True,
            ).start()
            application.invalidate()
            return
        try:
            application.exit(result=result)
        except Exception:
            return

    def maybe_exit_for_cron_tick() -> None:
        nonlocal last_cron_check
        application = application_holder.get("app")
        if application is None:
            return
        now = time.monotonic()
        if now - last_cron_check < 5.0:
            return
        last_cron_check = now
        if shell._startup_prime_started or not shell._startup_transcript_primed:
            return
        try:
            has_due = shell.runtime.has_due_cron_jobs(session_id=shell.session_id)
        except Exception:
            return
        if not has_due:
            return
        try:
            application.exit(result="__elephant.cron.tick__")
        except Exception:
            return

    def submit(event) -> None:
        raw_command = event.current_buffer.text
        if not raw_command.strip() and not getattr(shell, "_composer_paste_items", ()):
            return
        submission = _compose_submission(shell, raw_command)
        if not submission.command.strip():
            event.current_buffer.text = ""
            event.app.invalidate()
            return
        if shell._startup_should_hold_user_command(submission.command):
            event.current_buffer.append_to_history()
            shell._mark_startup_user_turn_submitted(submission.command)
            shell._enqueue_followup_command(submission)
            event.current_buffer.text = ""
            event.app.invalidate()
            maybe_exit_for_startup_transition()
            return
        if raw_command:
            event.current_buffer.append_to_history()
        shell._mark_startup_user_turn_submitted(submission.command)
        event.app.exit(result=submission)

    bindings = shell._build_key_bindings(submit=submit)
    input_window = build_input_window(shell, buffer)
    command_palette = build_command_palette(shell)
    queue_preview_window = build_queue_preview_window(shell)
    composer_body = build_composer_body(
        shell,
        input_window=input_window,
        command_palette=command_palette,
        top_windows=(queue_preview_window,),
        buffer=buffer,
    )
    application = Application(
        layout=Layout(composer_body, focused_element=input_window),
        key_bindings=bindings,
        style=shell._prompt_style(),
        full_screen=False,
        erase_when_done=True,
        # 0.33s tick — fast enough to feel live, slow enough to keep
        # status bar recompute + invalidate loops off the UI thread.
        refresh_interval=0.33,
        output=prompt_toolkit_output_without_cpr(),
    )
    application_holder["app"] = application

    def monitor_startup_transition() -> None:
        while not stop_monitor.is_set():
            maybe_exit_for_startup_transition()
            maybe_exit_for_cron_tick()
            if stop_monitor.wait(0.05):
                return

    threading.Thread(target=monitor_startup_transition, daemon=True).start()
    result = run_prompt_toolkit_application(application)
    stop_monitor.set()
    if result is None:
        raise EOFError
    return result


def prompt_label(shell: ProductizedShell) -> str:
    divider = shell._composer_divider()
    if not PROMPT_TOOLKIT_AVAILABLE:
        return f"{divider}\n› "
    return FormattedText(
        [
            ("class:composer-divider", f"{divider}\n"),
            ("class:composer-prefix", "› "),
        ]
    )


def prompt_continuation():
    if not PROMPT_TOOLKIT_AVAILABLE:
        return "  "
    return FormattedText([("class:composer-prefix", "  ")])


def prompt_style():
    if not PROMPT_TOOLKIT_AVAILABLE:
        return None
    return Style.from_dict(prompt_style_map())


def prompt_style_map() -> dict[str, str]:
    return {
        "": f"fg:{BRAND_LIGHT}",
        "composer-divider": f"fg:{BRAND_ACCENT}",
        "composer-prefix": f"fg:{BRAND_ACCENT_STRONG} bold",
        "queue-user": f"{USER_HISTORY_FG} bg:{USER_HISTORY_BG}",
        "clipboard-prefix": f"fg:{BRAND_MUTED}",
        "clipboard-chip": f"fg:{BRAND_ACCENT_STRONG} bold",
        "history-search-prefix": f"fg:{BRAND_ACCENT} bold",
        "history-search-query": f"fg:{BRAND_ACCENT_STRONG} bold",
        "history-search-meta": f"fg:{BRAND_MUTED}",
        "history-search-hit": f"fg:{BRAND_LIGHT}",
        "history-search-empty": f"fg:{BRAND_MUTED} italic",
        "history-search-hint": f"fg:{BRAND_MUTED}",
        "ghost-hint-prefix": f"fg:{BRAND_MUTED}",
        "ghost-hint-tail": f"fg:{BRAND_ACCENT} bold",
        "ghost-hint-desc": f"fg:{BRAND_MUTED} italic",
        "ghost-hint-prefix": f"fg:{BRAND_MUTED}",
        "ghost-hint-tail": f"fg:{BRAND_ACCENT} bold",
        "ghost-hint-desc": f"fg:{BRAND_MUTED} italic",
        "progress-title": f"fg:{BRAND_ACCENT} bold",
        "progress-active": f"fg:{BRAND_LIGHT}",
        "progress-active-marker": f"fg:{BRAND_MUTED} bold",
        "progress-active-detail": f"fg:{BRAND_LIGHT}",
        "progress-meta": f"fg:{BRAND_LIGHT}",
        "progress-tool": f"fg:{BRAND_LIGHT} bold",
        "progress-tool-rail": f"fg:{BRAND_DARK}",
        "progress-tool-emoji": f"fg:{BRAND_ACCENT}",
        "progress-tool-verb": f"fg:{BRAND_MUTED}",
        "progress-tool-label": f"fg:{BRAND_ACCENT_STRONG} bold",
        "progress-tool-gap": f"fg:{BRAND_LIGHT}",
        "progress-tool-body": f"fg:{BRAND_LIGHT}",
        "progress-tool-duration": f"fg:{BRAND_MUTED}",
        "progress-state-focus": f"fg:{BRAND_ACCENT_STRONG} bold",
        "progress-output-file": f"fg:{LIVE_DIFF_FILE_FG} bold",
        "progress-output-hunk": f"fg:{LIVE_DIFF_HUNK_FG} bold",
        "progress-output-add": f"fg:{LIVE_DIFF_ADD_FG} bold",
        "progress-output-remove": f"fg:{LIVE_DIFF_REMOVE_FG} bold",
        "progress-output-context": f"fg:{LIVE_DIFF_CONTEXT_FG}",
        "progress-output-body": f"fg:{BRAND_LIGHT}",
        "progress-queue": f"fg:{BRAND_LIGHT}",
        "progress-hint": f"fg:{BRAND_LIGHT}",
        "progress-stream": f"fg:{BRAND_ACCENT_STRONG}",
        "state-focus-ready-title": f"fg:{BRAND_ACCENT} bold",
        "state-focus-ready-body": f"fg:{BRAND_LIGHT}",
        "stream-reasoning-body": f"fg:{BRAND_MUTED}",
        "stream-response-body": f"fg:{BRAND_LIGHT}",
        "stream-response-bold": f"fg:{BRAND_LIGHT} bold",
        "stream-response-italic": f"fg:{BRAND_LIGHT} italic",
        "stream-response-bold-italic": f"fg:{BRAND_LIGHT} bold italic",
        "stream-response-code": f"fg:{BRAND_MUTED}",
        "stream-response-heading": f"fg:{BRAND_ACCENT_STRONG} bold",
        "stream-response-heading-minor": f"fg:{BRAND_LIGHT} bold",
        "stream-response-accent": f"fg:{BRAND_ACCENT}",
        "stream-response-muted": f"fg:{BRAND_MUTED}",
        "clarify-title": f"fg:{BRAND_ACCENT} bold",
        "clarify-question": f"fg:{BRAND_LIGHT} bold",
        "clarify-choice": f"fg:{BRAND_LIGHT}",
        "clarify-hint": f"fg:{BRAND_MUTED}",
        "completion-menu": "bg:#173141",
        "completion-menu.completion": f"bg:#173141 fg:{BRAND_LIGHT}",
        "completion-menu.completion.current": f"bg:#21475c fg:{BRAND_ACCENT_STRONG} bold",
        "completion-menu.meta.completion": f"bg:#173141 fg:{BRAND_MUTED}",
        "completion-menu.meta.completion.current": f"bg:#21475c fg:{BRAND_LIGHT}",
        "scrollbar.background": "bg:#173141",
        "scrollbar.button": f"bg:{BRAND_ACCENT}",
        "status-bar-edge": f"bg:#173141 fg:{BRAND_LIGHT}",
        "status-bar-model": f"bg:#173141 fg:{BRAND_ACCENT_STRONG} bold",
        "status-bar-sep": f"bg:#173141 fg:{BRAND_MUTED}",
        "status-bar-muted": f"bg:#173141 fg:{BRAND_LIGHT}",
        "status-bar-stream": f"bg:#173141 fg:{BRAND_ACCENT_STRONG} bold",
        "status-bar-level": f"bg:#173141 fg:{BRAND_ACCENT} bold",
        "status-bar-growth-bracket": f"bg:#173141 fg:{BRAND_ACCENT} bold",
        "status-bar-growth-fill": f"bg:#173141 fg:{BRAND_ACCENT_STRONG} bold",
        "status-bar-growth-empty": f"bg:#173141 fg:{BRAND_ACCENT}",
        "status-bar-good": "bg:#173141 fg:#7da27f bold",
        "status-bar-warn": f"bg:#173141 fg:{BRAND_ACCENT_STRONG} bold",
        "status-bar-critical": "bg:#173141 fg:#b85d57 bold",
    }


def _last_user_message(shell: ProductizedShell) -> str:
    """Most recent user-typed prompt in the transcript, or empty string.

    The transcript can be mutated by the dispatch thread during render
    ticks, so we copy the list under a try/except to avoid crashing on
    concurrent mutation. This is a read-only helper; if a race loses a
    message, the user gets an empty retry (visibly no-op, harmless).
    """
    transcript = getattr(shell, "transcript", None) or ()
    try:
        snapshot = list(transcript)
    except Exception:
        return ""
    for entry in reversed(snapshot):
        try:
            kind = getattr(entry, "kind", "")
            body = entry.body or ""
        except Exception:
            continue
        if kind == "user" and body.strip():
            return str(body)
    return ""


def build_key_bindings(shell: ProductizedShell | None = None, *, submit=None, allow_exit: bool = True) -> KeyBindings:
    bindings = KeyBindings()
    submit_handler = submit or (lambda event: event.current_buffer.validate_and_handle())

    # Filters for scoping bindings to history-search mode. When the shell
    # is None (tests), these evaluate false so the regular bindings apply.
    searching = Condition(lambda: shell is not None and _history_search_active(shell))
    not_searching = Condition(lambda: not (shell is not None and _history_search_active(shell)))

    @bindings.add("enter", filter=not_searching)
    def _(event) -> None:
        submit_handler(event)

    @bindings.add("enter", filter=searching)
    def _(event) -> None:
        # Accept the current match: load it into the buffer, leave search mode.
        buffer = event.current_buffer
        match = _history_search_current_match(shell) if shell is not None else ""
        if match:
            buffer.text = match
            buffer.cursor_position = len(match)
        if shell is not None:
            _history_search_exit(shell, buffer, restore=False)
        event.app.invalidate()

    @bindings.add("escape", "enter", filter=not_searching)
    def _(event) -> None:
        event.current_buffer.insert_text("\n")

    @bindings.add("escape", filter=searching)
    def _(event) -> None:
        if shell is not None:
            _history_search_exit(shell, event.current_buffer, restore=True)
        event.app.invalidate()

    # Plain Escape during an active turn → interrupt the turn. If a
    # message is already queued it drains into the next turn naturally
    # via the outer run() loop; if nothing is queued it's just a mid-turn
    # cancel (same as Ctrl+C mid-turn).
    #
    # `eager` must stay False here. Terminal escape sequences (arrow
    # keys, Alt-combinations, bracketed paste, etc.) all start with
    # \x1b, and `eager=True` would fire this handler before
    # prompt_toolkit's key parser finished matching the full sequence —
    # every arrow-key press during a turn would cancel the turn. The
    # default non-eager behaviour waits for the key-sequence timeout,
    # which is exactly what disambiguates plain Esc from compound
    # sequences.
    #
    # Guarded to `turn_active & not_searching` so Esc at the idle
    # composer stays a no-op.
    turn_active = Condition(
        lambda: shell is not None
        and (
            getattr(shell, "_turn_started_at", None) is not None
            or bool(getattr(shell, "_streaming_response_active", False))
        )
    )

    @bindings.add("escape", filter=turn_active & not_searching)
    def _(event) -> None:
        # Mark the cancel BEFORE asking the app to exit so that the
        # outer run() loop (which classifies "mid-turn vs idle" from
        # this flag) can tell Esc-cancel apart from an idle-SIGINT.
        # The turn runtime's `finally` clears `_turn_started_at`
        # before our KeyboardInterrupt reaches run(), so without this
        # flag the classifier would fall through to "idle" → raise
        # EOFError → exit the whole conversation. That's the bug the
        # user hit.
        if shell is not None:
            shell._cancel_requested = True
        # Leave the composer buffer + paste chips intact. If the user
        # typed a follow-up before pressing Esc, that text should
        # stay staged for the next turn — clearing it would throw
        # the follow-up away.
        event.app.exit(exception=KeyboardInterrupt())

    @bindings.add(Keys.BracketedPaste, filter=not_searching)
    def _(event) -> None:
        data = str(event.data or "").replace("\r\n", "\n").replace("\r", "\n")
        if shell is None or not _append_text_paste(shell, data):
            event.current_buffer.insert_text(data)
            return
        event.app.invalidate()

    @bindings.add("c-v", filter=not_searching)
    def _(event) -> None:
        if shell is None or not _append_system_clipboard_paste(shell):
            return
        event.app.invalidate()

    # ── Reverse-i-search ────────────────────────────────────────────────
    @bindings.add("c-r")
    def _(event) -> None:
        if shell is None:
            return
        if _history_search_active(shell):
            # Second Ctrl+R cycles to the next match.
            matches = list(getattr(shell, "_history_search_matches", ()) or ())
            if matches:
                idx = int(getattr(shell, "_history_search_index", 0) or 0)
                shell._history_search_index = (idx + 1) % len(matches)
        else:
            _history_search_enter(shell, event.current_buffer)
        event.app.invalidate()

    @bindings.add("up", filter=searching)
    def _(event) -> None:
        if shell is None:
            return
        matches = list(getattr(shell, "_history_search_matches", ()) or ())
        if not matches:
            return
        idx = int(getattr(shell, "_history_search_index", 0) or 0)
        shell._history_search_index = (idx + 1) % len(matches)
        event.app.invalidate()

    @bindings.add("down", filter=searching)
    def _(event) -> None:
        if shell is None:
            return
        matches = list(getattr(shell, "_history_search_matches", ()) or ())
        if not matches:
            return
        idx = int(getattr(shell, "_history_search_index", 0) or 0)
        shell._history_search_index = (idx - 1) % len(matches)
        event.app.invalidate()

    @bindings.add("backspace", filter=searching)
    def _(event) -> None:
        if shell is None:
            return
        query = str(getattr(shell, "_history_search_query", "") or "")
        shell._history_search_query = query[:-1]
        _history_search_refresh(shell)
        event.app.invalidate()

    # Any printable character while searching updates the query — route
    # it before the default "insert into buffer" handler via a catch-all
    # filter that only fires in search mode.
    @bindings.add("<any>", filter=searching)
    def _(event) -> None:
        if shell is None:
            return
        data = str(event.data or "")
        if not data or not data.isprintable() or data.startswith("\x1b"):
            return
        shell._history_search_query = str(getattr(shell, "_history_search_query", "") or "") + data
        _history_search_refresh(shell)
        event.app.invalidate()

    # ── Retry last message ──────────────────────────────────────────────
    # Up on an empty buffer pulls the last user message in for editing.
    # Alt+Up (Esc,Up) re-submits it verbatim, without giving the user a
    # chance to edit. If the composer already has text, Up falls through
    # to prompt_toolkit's default (caret moves up in multi-line buffer).
    empty_and_idle = Condition(
        lambda: shell is not None
        and not _history_search_active(shell)
        and not (shell is not None and getattr(shell, "_turn_started_at", None) is not None)
    )

    @bindings.add("up", filter=empty_and_idle)
    def _(event) -> None:
        buffer = event.current_buffer
        if buffer.text:
            # Let default Up handler move the cursor.
            buffer.cursor_up()
            return
        last = _last_user_message(shell) if shell is not None else ""
        if not last:
            return
        buffer.text = last
        buffer.cursor_position = len(last)
        event.app.invalidate()

    @bindings.add("escape", "up", filter=empty_and_idle)
    def _(event) -> None:
        # Alt+Up (or Esc,Up): re-submit the last user message verbatim.
        if shell is None:
            return
        last = _last_user_message(shell)
        if not last:
            return
        buffer = event.current_buffer
        submission = _compose_submission(shell, last)
        if not submission.command.strip():
            return
        if shell._startup_should_hold_user_command(submission.command):
            buffer.append_to_history()
            shell._mark_startup_user_turn_submitted(submission.command)
            shell._enqueue_followup_command(submission)
            buffer.text = ""
            event.app.invalidate()
            return
        buffer.append_to_history()
        shell._mark_startup_user_turn_submitted(submission.command)
        event.app.exit(result=submission)

    # ── Ghost-hint Tab accept ───────────────────────────────────────────
    # Tab on a `/foo` prefix with a matching ghost hint completes the
    # command name (without submitting). If there's no hint, Tab falls
    # through to prompt_toolkit's default (completion menu).
    @bindings.add("tab", filter=not_searching)
    def _(event) -> None:
        buffer = event.current_buffer
        match = _ghost_hint_match(shell, buffer.text or "")
        if match is None:
            # Let the regular completion menu handle it.
            from prompt_toolkit.key_binding.bindings.named_commands import menu_complete

            try:
                menu_complete(event)
            except Exception:
                buffer.insert_text("\t")
            return
        tail, _description = match
        if tail:
            buffer.insert_text(tail)
            event.app.invalidate()

    def _show_cheatsheet(event) -> None:
        """Inline keybinding reference, echoed into the transcript."""
        if shell is None:
            return
        lines = (
            "Keys",
            "  Enter               send",
            "  Esc+Enter / ⌥+Enter newline",
            "  ↑ (empty buffer)    pull last message back for editing",
            "  ⌥+↑ (empty buffer)  resend last message verbatim",
            "  Tab                 accept the ghost hint for /commands",
            "  Ctrl+V              paste from clipboard",
            "  Ctrl+R              search your history",
            "  ? (empty buffer)    show this cheatsheet · F1 works too",
            "  Ctrl+C              cancel turn · clear input · exit when idle",
            "  Esc (during turn)   interrupt · skip to next queued message",
            "  Ctrl+D              close this thread",
            "  /                   open the command palette",
            "",
            "Quick commands",
            "  /help        list every command",
            "  /status      where Elephant Agent stands right now",
            "  /recall      inspect Step/Episode recall evidence",
            "  /models      pick the model Elephant Agent reaches for",
            "  /exit        close this thread",
        )
        try:
            shell._append_entry("notice", "Cheatsheet", "\n".join(lines))
            shell._render_pending_entries()
        except Exception:
            # Help is a nice-to-have; never let it break the shell.
            pass
        event.app.invalidate()

    @bindings.add("f1", filter=not_searching)
    def _(event) -> None:
        _show_cheatsheet(event)

    @bindings.add("?", filter=not_searching)
    def _(event) -> None:
        # `?` on an empty buffer opens the cheatsheet; otherwise it's
        # literal punctuation so users can still type "wait, really?".
        buffer = event.current_buffer
        if buffer.text:
            buffer.insert_text("?")
            return
        _show_cheatsheet(event)

    if allow_exit:

        @bindings.add("c-c", filter=searching)
        def _(event) -> None:
            if shell is not None:
                _history_search_exit(shell, event.current_buffer, restore=True)
            event.app.invalidate()

        @bindings.add("c-c", filter=not_searching)
        def _(event) -> None:
            # Idle composer semantics (outside an active turn):
            #   * buffer empty + no pasted chips → exit cleanly, same
            #     as /exit or Ctrl+D. Users expect Ctrl+C to "get me
            #     out of this program" at a rest prompt.
            #   * otherwise → clear what you were typing (or the paste
            #     chips you staged) without exiting. Second Ctrl+C then
            #     exits.
            #
            # Use `event.app.exit(result=None)` rather than `raise EOFError`:
            # raising inside a key handler crashes the prompt_toolkit
            # event loop ("Unhandled exception in event loop"). The
            # caller sees a None result and raises EOFError outside the
            # loop, which run() then catches as the exit signal.
            buffer = event.current_buffer
            paste_items = tuple(getattr(shell, "_composer_paste_items", ()) or ()) if shell is not None else ()
            if buffer.text or paste_items:
                buffer.text = ""
                if shell is not None:
                    _clear_composer_paste_items(shell)
                event.app.invalidate()
                return
            if shell is not None:
                _clear_composer_paste_items(shell)
            event.app.exit(result=None)

        @bindings.add("c-d")
        def _(event) -> None:
            if shell is not None:
                _clear_composer_paste_items(shell)
            event.app.exit(result=None)
    else:

        @bindings.add("c-c", filter=searching)
        def _(event) -> None:
            if shell is not None:
                _history_search_exit(shell, event.current_buffer, restore=True)
            event.app.invalidate()

        @bindings.add("c-c", filter=not_searching)
        def _(event) -> None:
            event.current_buffer.text = ""
            if shell is not None:
                _clear_composer_paste_items(shell)
            event.app.invalidate()

        @bindings.add("c-d")
        def _(event) -> None:
            event.current_buffer.text = ""
            if shell is not None:
                _clear_composer_paste_items(shell)
            event.app.invalidate()

    return bindings
