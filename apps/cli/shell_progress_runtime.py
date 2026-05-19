"""Progress window construction and runtime helpers for the shell."""

from __future__ import annotations

import re
import threading
import time
from typing import TYPE_CHECKING

from packages.kernel.runtime import KernelOutcome
from packages.tools import ToolLifecycleEvent

from .shell_stack import (
    Application,
    Condition,
    ConditionalContainer,
    FormattedText,
    FormattedTextControl,
    Layout,
    Live,
    Text,
    Window,
)
from .shell_ui import (
    BRAND_LIGHT,
    LIVE_DIFF_ADD_FG,
    LIVE_DIFF_CONTEXT_FG,
    LIVE_DIFF_FILE_FG,
    LIVE_DIFF_HUNK_FG,
    LIVE_DIFF_REMOVE_FG,
    QUEUE_PREVIEW_INSET,
    strip_markdown_bold,
)
from .shell_clarify import (
    build_clarify_window,
    route_clarify_answer,
    set_clarify_invalidator,
)
from .shell_composer import _compose_submission, run_prompt_toolkit_application

if TYPE_CHECKING:
    from .shell import ProductizedShell


_STREAM_TOOL_BLOCK_PATTERNS = (
    re.compile(
        r"<(?:[\w.-]+:)?tool_call\b[^>]*>.*?</(?:[\w.-]+:)?tool_call\s*>",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"<(?:[\w.-]+:)?invoke\b[^>]*>.*?</(?:[\w.-]+:)?invoke\s*>",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"<(?:[\w.-]+:)?parameter\b[^>]*>.*?</(?:[\w.-]+:)?parameter\s*>",
        re.IGNORECASE | re.DOTALL,
    ),
)
_STREAM_TOOL_TAG_PATTERN = re.compile(
    r"</?(?:[\w.-]+:)?(?:tool_call|invoke|parameter)\b[^>]*>",
    re.IGNORECASE,
)
_STREAM_OPEN_TOOL_TAG_PATTERN = re.compile(
    r"<(?:[\w.-]+:)?(?:tool_call|invoke|parameter)\b[^>]*>",
    re.IGNORECASE,
)


from .shell_progress_support import (
    _VisibleToolEvent,
    animations_enabled,
    live_tool_feed_lines,
    loop_context_progress_line,
    recall_progress_line,
    turn_state_focus_progress_line,
    turn_phase,
    turn_title,
)
from .shell_progress_trace import (
    _stream_display_parts,
    _stream_response_fragments,
    anchored_tool_progress_items,
    render_tool_frame,
    render_turn_frame,
)


def _slow_op_hint_fragments(shell: ProductizedShell) -> list[tuple[str, str]]:
    """Telegraph long-running turns so the user knows we're still working.

    Thresholds:
      * >20s  without stream bytes → "⏳ still orienting — I'm on it, just
        taking a moment."
      * >60s                       → "⏳ this is taking longer than usual
        — hit Ctrl+C to stop or keep waiting."
    Once stream bytes arrive, the hint disappears (we have live output
    to show instead).
    """
    started_at = getattr(shell, "_turn_started_at", None)
    if started_at is None:
        return []
    streaming = bool(getattr(shell, "_streaming_response_active", False))
    if streaming:
        return []
    elapsed = max(0.0, time.monotonic() - float(started_at))
    if elapsed < 20.0:
        return []
    if elapsed >= 60.0:
        body = "⏳ this is taking longer than usual — hit Ctrl+C to stop or keep waiting."
    else:
        body = "⏳ still orienting — I'm on it, just taking a moment."
    return [("class:progress-hint", body)]


def render_turn_progress_fragments(
    shell: ProductizedShell,
    *,
    prompt: str,
    tick: int,
    tool_event: ToolLifecycleEvent | None = None,
    tool_events: tuple[ToolLifecycleEvent, ...] = (),
    kernel_stage_events: tuple[dict[str, object], ...] = (),
    queued_count: int = 0,
    stream_text: str = "",
    tool_event_holder=None,
    tool_event_lock=None,
) -> FormattedText:
    marker, _phase_label, phase_detail = turn_phase(tick)
    title_glyph, title_copy = turn_title(tick)
    fragments: list[tuple[str, str]] = [
        ("class:progress-title", f"{title_glyph} {title_copy}\n"),
        ("class:progress-active-marker", marker),
        ("class:progress-active-detail", f" {phase_detail}"),
    ]
    fragments.append(("", "\n"))
    fragments.extend(
        render_live_tool_line_fragments(turn_state_focus_progress_line(kernel_stage_events=kernel_stage_events))
    )
    context_line = loop_context_progress_line(kernel_stage_events=kernel_stage_events)
    if context_line.startswith("┊ 🧩 context") and ("projection" in context_line or "compressing" in context_line):
        fragments.extend(
            render_live_tool_line_fragments(
                context_line,
                leading_newline=True,
            )
        )
    recall_line = recall_progress_line(kernel_stage_events=kernel_stage_events)
    if recall_line:
        fragments.extend(
            render_live_tool_line_fragments(
                recall_line,
                leading_newline=True,
            )
        )
    if queued_count:
        label = "message" if queued_count == 1 else "messages"
        fragments.append(("class:progress-queue", f"\nqueued scrolls · {queued_count} {label}"))
    slow_op_hint = _slow_op_hint_fragments(shell)
    if slow_op_hint:
        fragments.append(("", "\n"))
        fragments.extend(slow_op_hint)

    # Render tool lines with stream text anchored to the matching tool event when
    # possible, while preserving the full merged tool rail from transcript + live events.
    if tool_event_holder is not None and tool_event_lock is not None:
        visible_events = visible_tool_events(tool_event_holder, tool_event_lock)
        stable_stream_anchors = stream_anchor_events(tool_event_holder, tool_event_lock)
        for item_kind, item_text in anchored_tool_progress_items(
            shell,
            visible_events=visible_events,
            stream_text=stream_text,
            stream_anchor_events=stable_stream_anchors,
        ):
            if item_kind == "stream":
                stream_fragments = _stream_response_fragments(item_text)
                if stream_fragments:
                    fragments.append(("", "\n"))
                    fragments.extend(stream_fragments)
            else:
                fragments.extend(render_live_tool_line_fragments(item_text, leading_newline=True))
    else:
        stream_fragments = _stream_response_fragments(stream_text)
        if stream_fragments:
            fragments.append(("", "\n"))
            fragments.extend(stream_fragments)
        for live_line in live_tool_feed_lines(shell, tool_event=tool_event, tool_events=tool_events):
            fragments.extend(render_live_tool_line_fragments(live_line, leading_newline=True))

    fragments.append(("", "\n"))
    return FormattedText(fragments)


def render_stream_response_fragments(
    shell: ProductizedShell,
    *,
    stream_text: str,
) -> FormattedText:
    del shell
    fragments = _stream_response_fragments(stream_text)
    if not fragments:
        return FormattedText([])
    return FormattedText(fragments)


def build_turn_progress_window(
    shell: ProductizedShell,
    *,
    prompt: str,
    started_at: float,
    tool_event_holder,
    tool_event_lock,
    kernel_stage_holder,
    kernel_stage_lock,
    stream_holder,
    stream_lock,
):
    return Window(
        FormattedTextControl(
            lambda: render_turn_progress_fragments(
                shell,
                prompt=prompt,
                tick=int(max(0.0, time.monotonic() - started_at) / 0.08),
                tool_event=latest_tool_event(tool_event_holder, tool_event_lock),
                tool_events=visible_tool_events(tool_event_holder, tool_event_lock),
                kernel_stage_events=visible_kernel_stage_events(kernel_stage_holder, kernel_stage_lock),
                queued_count=len(shell._pending_commands),
                stream_text=latest_stream_text(stream_holder, stream_lock),
                tool_event_holder=tool_event_holder,
                tool_event_lock=tool_event_lock,
            )
        ),
        wrap_lines=True,
        dont_extend_height=True,
    )


def build_stream_response_window(shell: ProductizedShell, *, stream_holder, stream_lock):
    # Stream text is rendered inside render_turn_progress_fragments before tool lines.
    # This hidden container keeps the layout factory shape simple.
    return ConditionalContainer(
        content=Window(
            FormattedTextControl(lambda: FormattedText([])),
            wrap_lines=True,
            dont_extend_height=True,
        ),
        filter=Condition(lambda: False),  # Always hidden
    )


def set_streaming_response_active(shell: ProductizedShell, active: bool) -> None:
    shell._streaming_response_active = active


def render_tool_output_fragments(line: str, *, leading_newline: bool = False) -> list[tuple[str, str]]:
    fragments: list[tuple[str, str]] = []
    if leading_newline:
        fragments.append(("", "\n"))
    style = "class:progress-output-body"
    if line.startswith("a/") and " → b/" in line:
        style = "class:progress-output-file"
    elif line.startswith("@@"):
        style = "class:progress-output-hunk"
    elif line.startswith("+"):
        style = "class:progress-output-add"
    elif line.startswith("-"):
        style = "class:progress-output-remove"
    elif line.startswith(" ") or (line.startswith("… omitted ") and "diff line(s)" in line):
        style = "class:progress-output-context"
    fragments.append((style, line))
    return fragments


def render_tool_output_text(line: str) -> Text:
    style = BRAND_LIGHT
    if line.startswith("a/") and " → b/" in line:
        style = f"bold {LIVE_DIFF_FILE_FG}"
    elif line.startswith("@@"):
        style = f"bold {LIVE_DIFF_HUNK_FG}"
    elif line.startswith("+"):
        style = f"bold {LIVE_DIFF_ADD_FG}"
    elif line.startswith("-"):
        style = f"bold {LIVE_DIFF_REMOVE_FG}"
    elif line.startswith(" ") or line.startswith("… "):
        style = LIVE_DIFF_CONTEXT_FG
    return Text(line, style=style)


def render_live_tool_line_fragments(line: str, *, leading_newline: bool = False) -> list[tuple[str, str]]:
    if line.startswith("┊ "):
        from .shell_progress_trace import render_tool_trace_fragments

        return render_tool_trace_fragments(line, leading_newline=leading_newline)
    return render_tool_output_fragments(line, leading_newline=leading_newline)


def render_live_tool_line_text(line: str) -> Text:
    if line.startswith("┊ "):
        from .shell_progress_trace import render_tool_trace_text

        return render_tool_trace_text(line)
    return render_tool_output_text(line)


def render_queued_followup_fragments(shell: ProductizedShell) -> FormattedText:
    fragments: list[tuple[str, str]] = []
    for command in shell._pending_commands:
        preview_text = command.display_command or command.command
        lines = strip_markdown_bold(preview_text).splitlines() or [""]
        for index, line in enumerate(lines):
            prefix = "› " if index == 0 else "  "
            fragments.append(("", " " * QUEUE_PREVIEW_INSET))
            fragments.append(("class:queue-user", shell._pad_queue_preview_line(f"{prefix}{line}")))
            fragments.append(("", "\n"))
    if fragments:
        fragments.pop()
    return FormattedText(fragments)


def queued_turn_input_supported(shell: ProductizedShell) -> bool:
    return shell._prompt_toolkit_composer_available()


def resolve_turn_outcome(holder: dict[str, object]) -> KernelOutcome:
    error = holder.get("error")
    if isinstance(error, Exception):
        raise error
    outcome = holder.get("outcome")
    if not isinstance(outcome, KernelOutcome):
        raise RuntimeError("turn completed without a kernel outcome")
    return outcome


def run_turn_with_queued_input(
    shell: ProductizedShell,
    prompt: str,
    *,
    event_payload: dict[str, str] | None = None,
) -> KernelOutcome:
    holder: dict[str, object] = {}
    stream_holder, stream_lock, stream_observer = stream_text_tracker()
    started_at = time.monotonic()
    shell._turn_started_at = started_at
    shell._turn_tool_events = []
    shell._cancel_requested = False
    set_streaming_response_active(shell, False)
    application_holder: dict[str, Application] = {}

    def invalidate_application() -> None:
        application = application_holder.get("app")
        if application is None:
            return
        try:
            application.invalidate()
        except Exception:
            return

    def raw_stream_observer(delta: str) -> None:
        stream_observer(delta)
        stream_active = bool(latest_stream_text(stream_holder, stream_lock).strip())
        set_streaming_response_active(shell, stream_active)
        invalidate_application()

    def reset_stream_for_tool_event(event: ToolLifecycleEvent) -> None:
        if event.phase != "requested":
            return
        preserved_response = retain_stream_response_only(stream_holder, stream_lock)
        set_streaming_response_active(shell, bool(preserved_response.strip()))
        invalidate_application()

    tool_event_holder, tool_event_lock, tool_observer = tool_event_tracker(
        shell._record_tool_event_trace,
        reset_stream_for_tool_event,
        lambda _event: invalidate_application(),
        stream_holder=stream_holder,
        stream_lock=stream_lock,
    )
    kernel_stage_holder, kernel_stage_lock, kernel_observer = kernel_event_tracker(
        shell._record_kernel_event_trace, lambda _event: invalidate_application()
    )
    previous_clarify_surface = shell.runtime.clarify_surface
    shell.runtime.set_clarify_surface(shell._interactive_clarify_surface())
    unsubscribe = shell.runtime.tool_runtime.subscribe(tool_observer)
    shell.runtime.set_model_stream_observer(raw_stream_observer)
    shell.runtime.set_kernel_event_observer(kernel_observer)

    def worker() -> None:
        try:
            holder["outcome"] = shell.runtime.explain_next_step(
                session_id=shell.session_id,
                prompt=prompt,
                event_payload=event_payload,
            )
        except Exception as error:  # pragma: no cover - surfaced below
            holder["error"] = error

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    buffer = shell._build_prompt_buffer()
    input_window = shell._build_input_window(buffer)
    command_palette = shell._build_command_palette()

    def submit(event) -> None:
        raw_command = event.current_buffer.text
        if not raw_command.strip() and not getattr(shell, "_composer_paste_items", ()):
            return
        if route_clarify_answer(shell, raw_command):
            event.current_buffer.append_to_history()
            event.current_buffer.text = ""
            event.app.invalidate()
            return
        submission = _compose_submission(shell, raw_command)
        if not submission.command.strip():
            event.current_buffer.text = ""
            event.app.invalidate()
            return
        event.current_buffer.append_to_history()
        event.current_buffer.text = ""
        shell._enqueue_followup_command(submission)
        event.app.invalidate()

    progress_window = build_turn_progress_window(
        shell,
        prompt=prompt,
        started_at=started_at,
        tool_event_holder=tool_event_holder,
        tool_event_lock=tool_event_lock,
        kernel_stage_holder=kernel_stage_holder,
        kernel_stage_lock=kernel_stage_lock,
        stream_holder=stream_holder,
        stream_lock=stream_lock,
    )
    stream_response_window = build_stream_response_window(
        shell,
        stream_holder=stream_holder,
        stream_lock=stream_lock,
    )
    composer_body = shell._build_composer_body(
        input_window=input_window,
        command_palette=command_palette,
        top_windows=(
            progress_window,
            stream_response_window,
            build_clarify_window(shell),
            shell._build_queue_preview_window(),
        ),
        buffer=buffer,
    )
    application = Application(
        layout=Layout(composer_body, focused_element=input_window),
        key_bindings=shell._build_key_bindings(submit=submit, allow_exit=False),
        style=shell._prompt_style(),
        full_screen=False,
        # Wipe the entire rendered block (stream text + composer chrome)
        # when the turn Application exits. Without this the prompt_toolkit
        # redraw leaves the composer prompt printed below the response as
        # scrollback junk — every completed turn drops an orphan "🐘 ›"
        # into the transcript. The final assistant entry is committed
        # via `_append_outcome` → `_render_pending_entries` afterwards,
        # so the user still sees the response in scrollback; just
        # rendered by the transcript pipeline, not by the live chrome.
        erase_when_done=True,
        refresh_interval=0.08,
    )
    application_holder["app"] = application
    set_clarify_invalidator(shell, invalidate_application)

    def exit_when_complete() -> None:
        thread.join()
        final_kernel_stages = visible_kernel_stage_events(kernel_stage_holder, kernel_stage_lock)
        remember_context_compaction_frame(
            shell,
            prompt=prompt,
            tick=int(max(0.0, time.monotonic() - started_at) / 0.08),
            kernel_stage_events=final_kernel_stages,
        )
        clear_tool_event_feed(tool_event_holder, tool_event_lock)
        clear_kernel_stage_events(kernel_stage_holder, kernel_stage_lock)
        reset_stream_text(stream_holder, stream_lock)
        set_streaming_response_active(shell, False)
        try:
            application.exit(result=True)
        except Exception:  # pragma: no cover - defensive cross-thread exit
            return

    threading.Thread(target=exit_when_complete, daemon=True).start()
    try:
        run_prompt_toolkit_application(application)
    except KeyboardInterrupt:
        shell._cancel_requested = True
        raise
    finally:
        shell._last_turn_elapsed_seconds = max(0, round(time.monotonic() - started_at))
        shell._turn_started_at = None
        shell.runtime.set_model_stream_observer(None)
        shell.runtime.set_kernel_event_observer(None)
        set_clarify_invalidator(shell, None)
        set_streaming_response_active(shell, False)
        unsubscribe()
        shell.runtime.set_clarify_surface(previous_clarify_surface)
    return resolve_turn_outcome(holder)


def run_turn_with_progress(
    shell: ProductizedShell,
    prompt: str,
    *,
    event_payload: dict[str, str] | None = None,
) -> KernelOutcome:
    if not animations_enabled():
        _tool_event_holder, _tool_event_lock, tool_observer = tool_event_tracker(shell._record_tool_event_trace)
        unsubscribe = shell.runtime.tool_runtime.subscribe(tool_observer)
        shell.runtime.set_model_stream_observer(lambda _delta: None)
        shell.runtime.set_kernel_event_observer(shell._record_kernel_event_trace)
        started_at = time.monotonic()
        shell._turn_started_at = started_at
        shell._turn_tool_events = []
        shell._cancel_requested = False
        try:
            return shell.runtime.explain_next_step(
                session_id=shell.session_id,
                prompt=prompt,
                event_payload=event_payload,
            )
        finally:
            shell._last_turn_elapsed_seconds = max(0, round(time.monotonic() - started_at))
            shell._turn_started_at = None
            shell.runtime.set_model_stream_observer(None)
            shell.runtime.set_kernel_event_observer(None)
            unsubscribe()
    if queued_turn_input_supported(shell):
        return run_turn_with_queued_input(shell, prompt, event_payload=event_payload)

    holder: dict[str, object] = {}
    stream_holder, stream_lock, stream_observer = stream_text_tracker()

    def collapse_stream_reasoning_for_requested_tool(event: ToolLifecycleEvent) -> None:
        if event.phase == "requested":
            retain_stream_response_only(stream_holder, stream_lock)

    tool_event_holder, tool_event_lock, tool_observer = tool_event_tracker(
        shell._record_tool_event_trace,
        collapse_stream_reasoning_for_requested_tool,
        stream_holder=stream_holder,
        stream_lock=stream_lock,
    )
    kernel_stage_holder, kernel_stage_lock, kernel_observer = kernel_event_tracker(shell._record_kernel_event_trace)
    unsubscribe = shell.runtime.tool_runtime.subscribe(tool_observer)
    shell.runtime.set_model_stream_observer(stream_observer)
    shell.runtime.set_kernel_event_observer(kernel_observer)
    started_at = time.monotonic()
    shell._turn_started_at = started_at
    shell._turn_tool_events = []
    shell._cancel_requested = False

    def worker() -> None:
        try:
            holder["outcome"] = shell.runtime.explain_next_step(
                session_id=shell.session_id,
                prompt=prompt,
                event_payload=event_payload,
            )
        except Exception as error:  # pragma: no cover - surfaced below
            holder["error"] = error

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    tick = 0
    try:
        with Live(
            render_turn_frame(
                shell,
                prompt=prompt,
                tick=tick,
                tool_events=visible_tool_events(tool_event_holder, tool_event_lock),
                kernel_stage_events=visible_kernel_stage_events(kernel_stage_holder, kernel_stage_lock),
                stream_text=latest_stream_text(stream_holder, stream_lock),
                tool_event_holder=tool_event_holder,
                tool_event_lock=tool_event_lock,
            ),
            console=shell.console,
            refresh_per_second=18,
            transient=True,
        ) as live:
            while thread.is_alive():
                live.update(
                    render_turn_frame(
                        shell,
                        prompt=prompt,
                        tick=tick,
                        tool_event=latest_tool_event(tool_event_holder, tool_event_lock),
                        tool_events=visible_tool_events(tool_event_holder, tool_event_lock),
                        kernel_stage_events=visible_kernel_stage_events(kernel_stage_holder, kernel_stage_lock),
                        stream_text=latest_stream_text(stream_holder, stream_lock),
                        tool_event_holder=tool_event_holder,
                        tool_event_lock=tool_event_lock,
                    ),
                    refresh=True,
                )
                time.sleep(0.08)
                tick += 1
            thread.join(timeout=0.1)
            final_tool_events = visible_tool_events(tool_event_holder, tool_event_lock)
            final_kernel_stages = visible_kernel_stage_events(kernel_stage_holder, kernel_stage_lock)
            remember_context_compaction_frame(
                shell,
                prompt=prompt,
                tick=tick,
                kernel_stage_events=final_kernel_stages,
            )
            live.update(
                render_turn_frame(
                    shell,
                    prompt=prompt,
                    tick=tick,
                    tool_event=latest_tool_event(tool_event_holder, tool_event_lock),
                    tool_events=final_tool_events,
                    kernel_stage_events=final_kernel_stages,
                    stream_text="",
                    tool_event_holder=tool_event_holder,
                    tool_event_lock=tool_event_lock,
                ),
                refresh=True,
            )
            if final_tool_events:
                time.sleep(0.18)
    except KeyboardInterrupt:
        # Give the phase pip a chance to show "⏹ cancelling" before the
        # interrupt bubbles up to run(). The render thread reads this
        # flag on its next tick; the status bar refresher picks it up
        # within ~0.5s.
        shell._cancel_requested = True
        raise
    finally:
        shell._last_turn_elapsed_seconds = max(0, round(time.monotonic() - started_at))
        shell._turn_started_at = None
        shell.runtime.set_model_stream_observer(None)
        shell.runtime.set_kernel_event_observer(None)
        unsubscribe()
    return resolve_turn_outcome(holder)


def run_tool_with_progress(shell: ProductizedShell, tool_id: str, arguments: dict[str, str]):
    shell.runtime.prepare_session_surface(shell.session_id)
    tool_runtime = shell.runtime.tool_runtime
    if not animations_enabled():
        _tool_event_holder, _tool_event_lock, tool_observer = tool_event_tracker(shell._record_tool_event_trace)
        unsubscribe = tool_runtime.subscribe(tool_observer)
        try:
            return tool_runtime.invoke(
                tool_id,
                arguments,
                session_id=shell.session_id,
                requester="operator",
            )
        finally:
            unsubscribe()

    holder: dict[str, object] = {}
    tool_event_holder, tool_event_lock, tool_observer = tool_event_tracker(shell._record_tool_event_trace)
    unsubscribe = tool_runtime.subscribe(tool_observer)

    def worker() -> None:
        try:
            holder["result"] = tool_runtime.invoke(
                tool_id,
                arguments,
                session_id=shell.session_id,
                requester="operator",
            )
        except Exception as error:  # pragma: no cover - surfaced below
            holder["error"] = error

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    tick = 0
    try:
        with Live(
            render_tool_frame(
                shell,
                tool_id=tool_id,
                tick=tick,
                tool_events=visible_tool_events(tool_event_holder, tool_event_lock),
            ),
            console=shell.console,
            refresh_per_second=18,
            transient=True,
        ) as live:
            while thread.is_alive():
                live.update(
                    render_tool_frame(
                        shell,
                        tool_id=tool_id,
                        tick=tick,
                        tool_event=latest_tool_event(tool_event_holder, tool_event_lock),
                        tool_events=visible_tool_events(tool_event_holder, tool_event_lock),
                    ),
                    refresh=True,
                )
                time.sleep(0.08)
                tick += 1
            thread.join(timeout=0.1)
            final_tool_events = visible_tool_events(tool_event_holder, tool_event_lock)
            live.update(
                render_tool_frame(
                    shell,
                    tool_id=tool_id,
                    tick=tick,
                    tool_event=latest_tool_event(tool_event_holder, tool_event_lock),
                    tool_events=final_tool_events,
                ),
                refresh=True,
            )
            if final_tool_events:
                time.sleep(0.14)
    except KeyboardInterrupt:
        shell._cancel_requested = True
        raise
    finally:
        unsubscribe()
    error = holder.get("error")
    if isinstance(error, Exception):
        raise error
    result = holder.get("result")
    if result is None:
        raise RuntimeError("tool call completed without a result")
    return result


def tool_event_tracker(*extra_observers, stream_holder=None, stream_lock=None):
    holder: dict[str, object] = {
        "latest": None,
        "feed": [],
        "stream_snapshots": {},
        "stream_anchors": [],
    }
    lock = threading.Lock()

    def observer(event: ToolLifecycleEvent) -> None:
        now = time.monotonic()
        with lock:
            holder["latest"] = event
            feed = [
                item for item in holder.get("feed", []) if isinstance(item, _VisibleToolEvent) and item.expires_at > now
            ]
            snapshots = {
                key: value
                for key, value in holder.get("stream_snapshots", {}).items()
                if isinstance(key, str) and isinstance(value, str)
            }
            anchors = [
                item
                for item in holder.get("stream_anchors", [])
                if isinstance(item, _VisibleToolEvent) and item.stream_text
            ]
            invocation_id = event.invocation.invocation_id
            captured_stream_text = snapshots.get(invocation_id, "")
            if event.phase == "requested" and stream_holder is not None and stream_lock is not None:
                captured_stream_text = response_only_stream_text(latest_stream_text(stream_holder, stream_lock))
                if captured_stream_text:
                    snapshots[invocation_id] = captured_stream_text
                else:
                    snapshots.pop(invocation_id, None)
            visible_event = _VisibleToolEvent(
                event=event,
                expires_at=now + _tool_event_hold_seconds(event.phase),
                stream_text=captured_stream_text,
            )
            feed.append(visible_event)
            feed = feed[-6:]
            holder["feed"] = feed
            if event.phase == "requested" and captured_stream_text:
                anchors.append(visible_event)
            holder["stream_anchors"] = anchors[-24:]
            active_invocation_ids = {
                item.event.invocation.invocation_id for item in feed if isinstance(item, _VisibleToolEvent)
            }
            holder["stream_snapshots"] = {
                key: value for key, value in snapshots.items() if key in active_invocation_ids
            }
        for extra_observer in extra_observers:
            try:
                extra_observer(event)
            except Exception:
                continue

    return holder, lock, observer


def latest_tool_event(holder, lock) -> ToolLifecycleEvent | None:
    with lock:
        return holder.get("latest")


def visible_tool_events(holder, lock) -> tuple[_VisibleToolEvent, ...]:
    now = time.monotonic()
    with lock:
        feed = [
            item for item in holder.get("feed", []) if isinstance(item, _VisibleToolEvent) and item.expires_at > now
        ]
        holder["feed"] = feed
        return tuple(feed)


def clear_tool_event_feed(holder, lock) -> None:
    with lock:
        holder["latest"] = None
        holder["feed"] = []
        holder["stream_snapshots"] = {}
        holder["stream_anchors"] = []


def stream_anchor_events(holder, lock) -> tuple[_VisibleToolEvent, ...]:
    with lock:
        anchors = [
            item
            for item in holder.get("stream_anchors", [])
            if isinstance(item, _VisibleToolEvent) and item.stream_text
        ]
        holder["stream_anchors"] = anchors
        return tuple(anchors)


def kernel_event_tracker(*extra_observers):
    holder: dict[str, object] = {"stages": []}
    lock = threading.Lock()

    def observer(event) -> None:
        if not isinstance(event, dict):
            return
        if event.get("event_type") == "kernel.stage":
            payload = event.get("payload")
            with lock:
                stages = list(holder.get("stages", ()))
                previous_stage = stages[-1] if stages and isinstance(stages[-1], dict) else None
                stage_event = dict(event)
                stages.append(stage_event)
                holder["stages"] = stages[-12:]
                if isinstance(payload, dict):
                    stage = payload.get("stage")
                    if stage == "context-compact":
                        holder["last_context_compact"] = stage_event
                    elif stage == "state_focus":
                        holder["last_state_focus"] = stage_event
                        if previous_stage is not None:
                            holder["last_state_focus_previous"] = previous_stage
        for extra_observer in extra_observers:
            try:
                extra_observer(event)
            except Exception:
                continue

    return holder, lock, observer


def visible_kernel_stage_events(holder, lock) -> tuple[dict[str, object], ...]:
    with lock:
        stages = holder.get("stages", ())
        if not isinstance(stages, list):
            return ()
        visible = [stage for stage in stages if isinstance(stage, dict)]
        state_focus_prefix = [
            stage
            for stage in (
                holder.get("last_state_focus_previous"),
                holder.get("last_state_focus"),
            )
            if isinstance(stage, dict) and stage not in visible
        ]
        if state_focus_prefix:
            visible = state_focus_prefix + visible
        last_context_compact = holder.get("last_context_compact")
        if isinstance(last_context_compact, dict) and last_context_compact not in visible:
            insert_at = len(state_focus_prefix)
            visible.insert(insert_at, last_context_compact)
        return tuple(visible)


def clear_kernel_stage_events(holder, lock) -> None:
    with lock:
        holder["stages"] = []
        holder.pop("last_state_focus", None)
        holder.pop("last_state_focus_previous", None)
        holder.pop("last_context_compact", None)


def remember_context_compaction_frame(
    shell: ProductizedShell,
    *,
    prompt: str,
    tick: int,
    kernel_stage_events: tuple[dict[str, object], ...],
) -> None:
    if not kernel_stages_include_compaction(kernel_stage_events):
        return
    shell._pending_context_compaction_frame = {
        "prompt": prompt,
        "tick": tick,
        "kernel_stage_events": kernel_stage_events,
    }
    shell._pending_context_compaction_frame_rendered = False


def kernel_stages_include_compaction(stages: tuple[dict[str, object], ...]) -> bool:
    for stage_event in stages:
        payload = stage_event.get("payload")
        if isinstance(payload, dict) and payload.get("stage") == "context-compact":
            return True
    return False


def _tool_event_hold_seconds(phase: str) -> float:
    if phase in {"requested", "execution.started"}:
        return 0.45
    if phase in {
        "execution.completed",
        "execution.failed",
        "approval.denied",
        "approval.deferred",
    }:
        return 1.1
    return 0.35


def stream_text_tracker():
    # holder["raw"]       — rolling 16KB buffer of raw model bytes
    # holder["_cache_key"] — id+length of the raw str at last parse
    # holder["_cached"]   — (reasoning, response) from the last parse
    # The render path reads `latest_stream_text()` / `response_only_stream_text()`
    # at every tick (~12.5 Hz). Caching the parse result by buffer length
    # turns that from a full regex pass into a dict read when nothing
    # changed, which is the common case between consecutive render ticks.
    holder: dict[str, object] = {"raw": "", "_cache_key": None, "_cached": None}
    lock = threading.Lock()

    def observer(delta: str) -> None:
        if not delta:
            return
        with lock:
            holder["raw"] = f"{holder['raw']}{delta}"[-16000:]
            # New bytes arrived — invalidate the parse cache.
            holder["_cache_key"] = None
            holder["_cached"] = None

    return holder, lock, observer


def _cached_stream_display_parts(holder) -> tuple[str, str]:
    """Read the parsed (reasoning, response) split under the holder lock.

    Caller MUST hold the lock. This is the hot-path reader — called on
    every render tick of the turn frame. We cache by raw length because
    (a) raw is append-only per the observer, and (b) equal length means
    the content hasn't advanced — cheap invariant.
    """
    raw = str(holder.get("raw", "") or "")
    cache_key = holder.get("_cache_key")
    cached = holder.get("_cached")
    if cache_key == len(raw) and isinstance(cached, tuple) and len(cached) == 2:
        return cached  # type: ignore[return-value]
    reasoning, response = _stream_display_parts(raw, streaming=True)
    holder["_cache_key"] = len(raw)
    holder["_cached"] = (reasoning, response)
    return reasoning, response


def response_only_stream_text(stream_text: str) -> str:
    _reasoning, response = _stream_display_parts(stream_text, streaming=True)
    return response


def retain_stream_response_only(holder, lock) -> str:
    with lock:
        response = response_only_stream_text(holder.get("raw", ""))
        holder["raw"] = response
        holder["_cache_key"] = None
        holder["_cached"] = None
        return response


def latest_stream_text(holder, lock) -> str:
    with lock:
        _reasoning, response = _cached_stream_display_parts(holder)
        return response


def reset_stream_text(holder, lock) -> None:
    with lock:
        holder["raw"] = ""
        holder["_cache_key"] = None
        holder["_cached"] = None
