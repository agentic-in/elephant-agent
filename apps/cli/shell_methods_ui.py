"""Bound methods extracted from apps/cli/shell.py."""

from __future__ import annotations

import threading
import time

from packages.growth import ProgressionProjectionBuilder
from packages.state.governance import companion_display_name
from .shell_composer import (
    build_command_palette as _build_shell_command_palette,
    build_composer_body as _build_shell_composer_body,
    build_divider_window as _build_shell_divider_window,
    build_input_window as _build_shell_input_window,
    build_key_bindings as _build_shell_key_bindings,
    build_prompt_buffer as _build_shell_prompt_buffer,
    build_queue_preview_window as _build_shell_queue_preview_window,
    prompt_continuation as _shell_prompt_continuation,
    prompt_label as _shell_prompt_label,
    prompt_style as _shell_prompt_style,
    prompt_style_map as _shell_prompt_style_map,
    prompt_toolkit_composer_available as _shell_prompt_toolkit_composer_available,
    read_command as _read_shell_command,
    shell_history as _shell_history,
)
from .shell_opening import (
    ShellOpeningContext,
    compose_shell_opening_instruction,
    compose_shell_opener,
)
from .shell_render import (
    render_brand_column as _render_shell_brand_column,
    render_shell_frame as _render_shell_frame_view,
    render_status_column as _render_shell_status_column,
)
from .shell_stack import (
    Console,
    Document,
    PROMPT_TOOLKIT_AVAILABLE,
    RICH_AVAILABLE,
)
from .shell_ui import (
    BRAND_ACCENT,
    BRAND_ACCENT_STRONG,
    BRAND_DARK,
    BRAND_LIGHT,
    BRAND_MUTED,
    COMMAND_PALETTE_VISIBLE_ROWS,
    ELEPHANT_STAGE_ROWS,
    GROWTH_HIGHLIGHT_FG,
    GROWTH_PROGRESS_EMPTY,
    GROWTH_PROGRESS_FILLED,
    GROWTH_PROGRESS_WIDTH,
    HATCHLING_HEAD_ROWS,
    HATCHLING_STAGE_ROWS,
    QUEUE_PREVIEW_INSET,
    SCOUT_STAGE_ROWS,
    SEED_STAGE_ROWS,
    SHELL_WELCOME_HEADLINE,
    USER_HISTORY_BG,
    USER_HISTORY_FG,
    compact_line as _compact_line,
    centered_elephant_rows as _centered_elephant_rows,
    display_width as _display_width,
    render_elephant_mark,
)

__all__ = [
    "BRAND_ACCENT",
    "BRAND_ACCENT_STRONG",
    "BRAND_DARK",
    "BRAND_LIGHT",
    "BRAND_MUTED",
    "COMMAND_PALETTE_VISIBLE_ROWS",
    "Console",
    "Document",
    "ELEPHANT_STAGE_ROWS",
    "GROWTH_HIGHLIGHT_FG",
    "GROWTH_PROGRESS_EMPTY",
    "GROWTH_PROGRESS_FILLED",
    "GROWTH_PROGRESS_WIDTH",
    "HATCHLING_HEAD_ROWS",
    "HATCHLING_STAGE_ROWS",
    "HATCHLING_STAGE_ROWS",
    "PendingShellCommand",
    "ProductizedShell",
    "QUEUE_PREVIEW_INSET",
    "RICH_AVAILABLE",
    "SCOUT_STAGE_ROWS",
    "SEED_STAGE_ROWS",
    "SHELL_WELCOME_HEADLINE",
    "ShellCompleter",
    "TranscriptEntry",
    "USER_HISTORY_BG",
    "USER_HISTORY_FG",
    "_centered_elephant_rows",
    "_display_width",
    "render_elephant_mark",
]


from .shell_support_runtime import *  # noqa: F401,F403


def _first_language_from_runtime(runtime, profile) -> str:
    try:
        from packages.runtime_config import (
            global_config_path_for_state_dir,
            load_global_config,
        )

        config_path = global_config_path_for_state_dir(runtime.paths.state_dir)
        config = load_global_config(config_path, state_dir=runtime.paths.state_dir)
        value = (config.get("personal_model") or {}).get("first_language")
        if value:
            return str(value).strip() or "en"
    except Exception:
        pass
    state = getattr(profile, "state", None)
    for preference in tuple(getattr(state, "preferences", ()) or ()):
        key, separator, value = str(preference or "").partition("=")
        if separator and key.strip() == "first_language":
            return value.strip() or "en"
    return "en"


def _next_command(self) -> PendingShellCommand:
    if self._pending_commands:
        return self._pending_commands.popleft()
    return coerce_pending_shell_command(self._read_command())


def _prompt_toolkit_composer_available(self) -> bool:
    return _shell_prompt_toolkit_composer_available(self)


def _shell_history(self):
    return _shell_history(self)


def _build_prompt_buffer(self):
    return _build_shell_prompt_buffer(self)


def _build_input_window(self, buffer):
    return _build_shell_input_window(self, buffer)


def _build_command_palette(self):
    return _build_shell_command_palette(self)


def _build_queue_preview_window(self):
    return _build_shell_queue_preview_window(self)


def _build_divider_window(self):
    return _build_shell_divider_window(self)


def _build_composer_body(
    self,
    *,
    input_window,
    command_palette,
    top_windows=(),
    buffer=None,
):
    return _build_shell_composer_body(
        self,
        input_window=input_window,
        command_palette=command_palette,
        top_windows=top_windows,
        buffer=buffer,
    )


def _read_command(self) -> object:
    return _read_shell_command(self)


def personality_preset_choices(self) -> tuple[tuple[str, str], ...]:
    return tuple(
        (preset.preset_id, preset.summary)
        for preset in self.runtime.personality_presets()
        if preset.preset_id != "custom"
    )


def _prompt_label(self) -> str:
    return _shell_prompt_label(self)


def _prompt_continuation(self):
    return _shell_prompt_continuation()


def _prompt_style(self):
    return _shell_prompt_style()


def _prompt_style_map(self) -> dict[str, str]:
    return _shell_prompt_style_map()


def _build_key_bindings(self, *, submit=None, allow_exit: bool = True) -> KeyBindings:
    return _build_shell_key_bindings(self, submit=submit, allow_exit=allow_exit)


def _composer_divider(self) -> str:
    try:
        width = int(self.console.size.width)
    except AttributeError:
        width = int(getattr(self.console, "width", 100) or 100)
    cache = getattr(self, "_composer_divider_cache", None)
    if cache is not None and cache[0] == width:
        return cache[1]
    divider = "─" * max(24, width - 1)
    self._composer_divider_cache = (width, divider)
    return divider


def _format_status_tokens(self, value: int | None) -> str:
    if value is None or value <= 0:
        return "--"
    if value >= 1_000_000:
        whole = round(value / 1_000_000, 1)
        return f"{whole:g}M"
    if value >= 1_000:
        whole = round(value / 1_000)
        return f"{whole}K"
    return str(value)


def _status_bar_context_style(self, percent_used: int | None) -> str:
    if percent_used is None:
        return "class:status-bar-muted"
    if percent_used >= 95:
        return "class:status-bar-critical"
    if percent_used > 80:
        return "class:status-bar-warn"
    return "class:status-bar-good"


_STATUS_BAR_PROGRESS_FILLED = "█"
_STATUS_BAR_PROGRESS_EMPTY = "░"
_STATUS_CONTEXT_RING_STEPS = ("○", "◜", "◔", "◑", "◕", "●")


def _build_context_bar(self, percent_used: int | None, width: int = 12) -> str:
    safe_percent = max(0, min(100, percent_used or 0))
    filled = round((safe_percent / 100) * width)
    return f"[{(_STATUS_BAR_PROGRESS_FILLED * filled) + (_STATUS_BAR_PROGRESS_EMPTY * max(0, width - filled))}]"


def _build_context_ring(self, percent_used: int | None) -> str:
    if percent_used is None:
        return _STATUS_CONTEXT_RING_STEPS[0]
    safe_percent = max(0, min(100, percent_used))
    if safe_percent <= 0:
        return _STATUS_CONTEXT_RING_STEPS[0]
    if safe_percent < 25:
        return _STATUS_CONTEXT_RING_STEPS[1]
    if safe_percent < 50:
        return _STATUS_CONTEXT_RING_STEPS[2]
    if safe_percent < 75:
        return _STATUS_CONTEXT_RING_STEPS[3]
    if safe_percent < 95:
        return _STATUS_CONTEXT_RING_STEPS[4]
    return _STATUS_CONTEXT_RING_STEPS[5]


def _build_growth_bar_fragments(self, growth, *, width: int = 12) -> list[tuple[str, str]]:
    filled, empty = self._growth_progress_counts(growth, width=width)
    fragments: list[tuple[str, str]] = [("class:status-bar-growth-bracket", "[")]
    if filled:
        fragments.append(("class:status-bar-growth-fill", _STATUS_BAR_PROGRESS_FILLED * filled))
    if empty:
        fragments.append(("class:status-bar-growth-empty", _STATUS_BAR_PROGRESS_EMPTY * empty))
    fragments.append(("class:status-bar-growth-bracket", "]"))
    return fragments


def _status_bar_elapsed_fragments(elapsed_seconds: int, *, streaming_active: bool = False) -> list[tuple[str, str]]:
    fragments: list[tuple[str, str]] = [("class:status-bar-muted", f"{elapsed_seconds}s")]
    if streaming_active:
        fragments.extend(
            [
                ("class:status-bar-sep", " · "),
                ("class:status-bar-stream", "streaming"),
            ]
        )
    return fragments


_STATUS_BAR_GROWTH_BUILDER = ProgressionProjectionBuilder()


# Status bar refreshes at ~5 Hz; snapshot/growth/learning each hit
# DB + projection work, so keep a short cache keyed on (turn flag,
# monotonic tick) to take pressure off the render loop without
# looking stale to the user.
_STATUS_BAR_SNAPSHOT_TTL_IDLE = 0.9
_STATUS_BAR_SNAPSHOT_TTL_ACTIVE = 0.25
_STATUS_BAR_GROWTH_TTL = 1.5
_STATUS_BAR_ELEPHANT_TTL = 2.5

# ── Shared animation clock ────────────────────────────────────────────
#
# Everything that animates in the chat surface reads from this single
# function. Using one time source means every pip, marker, and glyph
# moves in phase — no drift, no jitter, no out-of-sync wobble.
#
# 20 Hz was picked to match prompt_toolkit's refresh cadence on active
# turns (~12.5 Hz) while staying fast enough for smooth motion. Using
# `time.monotonic()` directly means the "clock" is stateless — any
# thread can read the same tick.
_ANIM_CLOCK_HZ = 20.0


def _anim_tick(rate_hz: float) -> int:
    """Return a monotonic tick index for a per-animation rate.

    A single wall clock keeps every animation in phase — if two pips
    both run at 10 Hz, they hit frame N at the same moment, every
    time. Callers pick a rate that matches the mood they want:
      * 10 Hz — reply dots (quick but readable)
      * 8 Hz  — tool glyph pulse (calmer, suggests real work)
      * 8 Hz  — thought pulse (visible enough to read as active work)
    """
    return int(time.monotonic() * rate_hz)


# Thinking pulse — taller block steps make the active pre-reply phase
# visible, while keeping a stable one-cell footprint.
_STATUS_PHASE_THINK_FRAMES = ("▁", "▃", "▅", "▇", "▅", "▃")
# Tool-work glyph pulse — eight solid frames that read as a filling
# elephant (orienting, doing work). Wider character keeps the column
# stable when paired with the "working" label.
_STATUS_PHASE_TOOL_FRAMES = ("⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷")
# Reply dots — same visual width, 10 frames, smooth curve.
_STATUS_PHASE_STREAM_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


# Minimum time a phase label has to stay visible once it's been chosen.
# Protects against flicker when Elephant Agent flips between thinking and
# streaming within the same second (common with fast providers).
_PHASE_MIN_HOLD_SECONDS = 1.5


def _resolve_phase_key(self) -> str:
    """Raw phase key derived from the current shell flags (pre-debounce)."""
    if bool(getattr(self, "_cancel_requested", False)):
        return "cancel"
    if bool(getattr(self, "_streaming_response_active", False)):
        return "stream"
    if self._turn_started_at is None:
        return "idle"
    if bool(getattr(self, "_tool_execution_active", False)):
        return "tool"
    return "think"


def _held_phase_key(self) -> str:
    """Debounced phase key — holds each state for at least 1.5s.

    Without this, "thinking → streaming → thinking" flickers as the
    model alternates reasoning tokens and response tokens. Holding
    for a minimum interval reads as intentional work, not twitching.

    Three transitions bypass the hold (they're signals users need
    immediately, not UX polish):
      * ANY → 'idle'   — turn ended, pip should disappear at once
      * ANY → 'cancel' — Ctrl+C pressed, acknowledge now
      * 'idle' → ANY   — turn started, show work state immediately
    """
    now = time.monotonic()
    target = _resolve_phase_key(self)
    current = getattr(self, "_phase_held_key", None)
    held_since = getattr(self, "_phase_held_since", None)
    if current is None or current == target:
        if current is None:
            self._phase_held_key = target
            self._phase_held_since = now
        return target
    # Terminal states + work-starting transitions are always immediate.
    if target in ("idle", "cancel") or current == "idle":
        self._phase_held_key = target
        self._phase_held_since = now
        return target
    if held_since is not None and (now - held_since) < _PHASE_MIN_HOLD_SECONDS:
        return current
    self._phase_held_key = target
    self._phase_held_since = now
    return target


def _status_phase_indicator(self) -> tuple[str, str] | None:
    """Return (style_class, glyph+label) for the phase pip, or None at rest.

    All glyph selection reads from the shared animation clock so every
    pip on screen stays in phase with every other animation.
    """
    key = _held_phase_key(self)
    if key == "idle":
        return None
    if key == "cancel":
        return ("class:status-bar-warn", "⏹ cancelling")
    if key == "stream":
        # 10 Hz — quick path dots for live assistant output.
        glyph = _STATUS_PHASE_STREAM_FRAMES[_anim_tick(10) % len(_STATUS_PHASE_STREAM_FRAMES)]
        return ("class:status-bar-stream", f"{glyph} following")
    if key == "tool":
        # 8 Hz — deliberate, suggests work. Label is "working" not
        # "tool" because we already render which tool in the turn frame.
        glyph = _STATUS_PHASE_TOOL_FRAMES[_anim_tick(8) % len(_STATUS_PHASE_TOOL_FRAMES)]
        return ("class:status-bar-stream", f"{glyph} working")
    # think (default active)
    glyph = _STATUS_PHASE_THINK_FRAMES[_anim_tick(8) % len(_STATUS_PHASE_THINK_FRAMES)]
    return ("class:status-bar-stream", f"{glyph} orienting")


def _status_bar_growth(self):
    now = time.monotonic()
    cache = getattr(self, "_status_bar_growth_cache", None)
    if cache is not None and (now - cache[0]) < _STATUS_BAR_GROWTH_TTL:
        return cache[1]
    session = self.runtime.inspect_session(self.session_id)
    growth_state = self.runtime.repository.load_personal_model_growth(session.personal_model_id)
    growth = _STATUS_BAR_GROWTH_BUILDER.build(profile_id=session.personal_model_id, state=growth_state)
    self._status_bar_growth_cache = (now, growth)
    return growth


def _status_bar_elephant_label(self) -> str:
    """Short friendly identity for the current elephant/Elephant Agent, for the status bar."""
    now = time.monotonic()
    cache = getattr(self, "_status_bar_elephant_cache", None)
    if cache is not None and (now - cache[0]) < _STATUS_BAR_ELEPHANT_TTL:
        return cache[1]
    label = ""
    try:
        session = self.runtime.inspect_session(self.session_id)
        elephant_id = self.runtime.elephant_id_for_session(session)
        state = self.runtime.state_for_elephant(elephant_id) if elephant_id else None
        name = (getattr(state, "elephant_name", "") or "").strip()
        if not name and elephant_id:
            name = elephant_id
        label = _compact_line(name or "Elephant Agent", limit=18)
    except Exception:
        label = "Elephant Agent"
    self._status_bar_elephant_cache = (now, label)
    return label


# Background refresher — the render thread reads the cached snapshot
# fields above. A daemon thread proactively steadys them so we rarely
# pay a DB read on the UI path. Event-wake hooks (e.g., after a growth checkpoint)
# can bypass the 0.5s rhythm when state changes matter immediately.
_STATUS_REFRESHER_INTERVAL = 0.5


def _status_refresher_prime(self) -> None:
    """One-off steadyup of all status caches, safe to call from any thread."""
    try:
        _status_bar_growth(self)
    except Exception:
        pass
    try:
        _status_bar_elephant_label(self)
    except Exception:
        pass


def _start_status_refresher(self) -> None:
    """Start the background refresher thread once per shell lifetime."""
    if getattr(self, "_status_refresher_thread", None) is not None:
        return
    import threading as _threading

    stop_event: _threading.Event = _threading.Event()
    wake_event: _threading.Event = _threading.Event()
    self._status_refresher_stop = stop_event
    self._status_refresher_wake = wake_event

    def _loop() -> None:
        while not stop_event.is_set():
            _status_refresher_prime(self)
            # Wake short-circuits the sleep when the main thread signals
            # (e.g., after a growth checkpoint invalidates the growth cache).
            wake_event.wait(timeout=_STATUS_REFRESHER_INTERVAL)
            wake_event.clear()

    thread = _threading.Thread(
        target=_loop,
        name="elephant-status-refresher",
        daemon=True,
    )
    self._status_refresher_thread = thread
    thread.start()


def _stop_status_refresher(self) -> None:
    """Stop the refresher if it's running. Idempotent and safe to call on exit."""
    stop_event = getattr(self, "_status_refresher_stop", None)
    wake_event = getattr(self, "_status_refresher_wake", None)
    if stop_event is not None:
        stop_event.set()
    if wake_event is not None:
        wake_event.set()
    self._status_refresher_thread = None


def _wake_status_refresher(self) -> None:
    """Poke the refresher to re-prime immediately after a state change."""
    wake_event = getattr(self, "_status_refresher_wake", None)
    if wake_event is not None:
        wake_event.set()


def _status_bar_snapshot(self) -> dict[str, object]:
    now = time.monotonic()
    active_turn = self._turn_started_at is not None
    streaming_active = bool(getattr(self, "_streaming_response_active", False))
    ttl = _STATUS_BAR_SNAPSHOT_TTL_ACTIVE if (active_turn or streaming_active) else _STATUS_BAR_SNAPSHOT_TTL_IDLE
    cache = getattr(self, "_status_bar_snapshot_cache", None)
    if cache is not None:
        cached_at, cached_snapshot, cached_active = cache
        if (now - cached_at) < ttl and cached_active == active_turn:
            # Elapsed seconds still need to tick for the live counter,
            # so only refresh that field cheaply without redoing the DB
            # reads for the rest of the snapshot.
            if active_turn:
                refreshed = dict(cached_snapshot)
                refreshed["elapsed_seconds"] = max(0, round(now - (self._turn_started_at or now)))
                return refreshed
            return cached_snapshot

    provider = dict(self.runtime.provider_summary())
    model_name = str(provider.get("model_id") or provider.get("default_model") or "<unset>")
    model_short = model_name.split("/")[-1] if "/" in model_name else model_name
    model_short = _compact_line(model_short, limit=26)
    context_window = provider.get("context_window_tokens")
    try:
        context_limit = int(context_window) if context_window is not None else None
    except (TypeError, ValueError):
        context_limit = None
    projection_used = max(0, self._last_prompt_tokens)
    request_used = max(0, int(getattr(self, "_last_provider_prompt_tokens", 0) or 0))
    context_used = request_used or projection_used or None
    context_percent = None
    if context_limit and context_used is not None:
        context_percent = max(0, min(100, round((context_used / context_limit) * 100)))
    if active_turn:
        elapsed_seconds = max(0, round(now - self._turn_started_at))
    else:
        elapsed_seconds = max(0, int(self._last_turn_elapsed_seconds))
    snapshot = {
        "model_short": model_short,
        "context_used": context_used,
        "context_limit": context_limit,
        "context_percent": context_percent,
        "projection_used": projection_used,
        "request_used": request_used,
        "elapsed_seconds": elapsed_seconds,
    }
    self._status_bar_snapshot_cache = (now, snapshot, active_turn)
    return snapshot


def _status_bar_fragments(self):
    snapshot = self._status_bar_snapshot()
    growth = _status_bar_growth(self)
    percent = snapshot["context_percent"]
    percent_style = self._status_bar_context_style(percent if isinstance(percent, int) else None)
    context_used = self._format_status_tokens(snapshot["context_used"])
    context_limit = self._format_status_tokens(snapshot["context_limit"])
    percent_label = f"{percent}%" if isinstance(percent, int) else "--"
    elapsed_seconds = int(snapshot["elapsed_seconds"])
    streaming_active = bool(getattr(self, "_streaming_response_active", False))
    active_turn = bool(self._turn_started_at is not None)
    elephant_glyph = "🐘" if (active_turn or streaming_active) else "🐾"
    elephant_label = _status_bar_elephant_label(self)
    phase_indicator = _status_phase_indicator(self)
    fragments: list[tuple[str, str]] = [
        ("class:status-bar-edge", " "),
        ("class:status-bar-level", f"{elephant_glyph} "),
        ("class:status-bar-model", elephant_label),
    ]
    # Phase pip sits right next to the elephant identity cluster so the
    # status bar reads as one thought about what Elephant Agent is doing.
    # At rest (phase_indicator is None), the path glyph carries the idle state.
    if phase_indicator is not None:
        phase_style, phase_label = phase_indicator
        fragments.append(("class:status-bar-sep", " · "))
        fragments.append((phase_style, phase_label))
    fragments.extend(
        [
            ("class:status-bar-sep", " │ "),
            ("class:status-bar-model", str(snapshot["model_short"])),
            ("class:status-bar-sep", " │ "),
            ("class:status-bar-muted", f"{context_used}/{context_limit}"),
            ("class:status-bar-sep", " "),
            (
                percent_style,
                self._build_context_ring(percent if isinstance(percent, int) else None),
            ),
            ("class:status-bar-sep", " "),
            (percent_style, percent_label),
            ("class:status-bar-sep", " │ "),
            *_status_bar_elapsed_fragments(elapsed_seconds, streaming_active=streaming_active),
            ("class:status-bar-sep", " │ "),
            ("class:status-bar-level", growth.cycle_label),
            ("class:status-bar-sep", " "),
            *self._build_growth_bar_fragments(growth),
            ("class:status-bar-sep", " "),
            (
                "class:status-bar-level",
                f"checkpoint {growth.level} · {growth.progress_percent}%",
            ),
        ]
    )
    fragments.append(("class:status-bar-edge", " "))
    return fragments


def _clear_composer(self, command: str) -> None:
    if PROMPT_TOOLKIT_AVAILABLE:
        return
    stream = getattr(self.console, "file", None)
    if stream is None or not hasattr(stream, "isatty") or not stream.isatty():
        return
    logical_lines = 3 + command.count("\n")
    stream.write("\r\x1b[2K")
    for _ in range(logical_lines):
        stream.write("\x1b[1A\r\x1b[2K")
    stream.flush()


def _enqueue_followup_command(self, raw_command: object) -> None:
    pending = coerce_pending_shell_command(raw_command)
    command = pending.command.strip()
    if not command:
        return
    self._pending_commands.append(
        PendingShellCommand(
            command=command,
            display_command=pending.display_command.strip(),
            event_payload=dict(pending.event_payload),
        )
    )


def _is_startup_conversational_command(self, raw_command: str) -> bool:
    command = raw_command.strip()
    return bool(command) and not command.startswith("/")


def _startup_state_focus_dispatch_ready(self) -> bool:
    return True


def _startup_should_hold_user_command(self, raw_command: str) -> bool:
    if not self._is_startup_conversational_command(raw_command):
        return False
    return not self._startup_transcript_primed


def _mark_startup_user_turn_submitted(self, raw_command: str) -> None:
    if self._is_startup_conversational_command(raw_command):
        self._startup_user_turn_submitted = True


def _startup_should_surface_state_focus_notices(self) -> bool:
    if not self._startup_surface_prepared or not self._state_focus_runtime_ready_seen:
        return True
    return not self._startup_transcript_primed


def _set_state_focus_runtime_notice(self, title: str, body: str) -> None:
    """Replace the live startup notice with a single (title, body) slot.

    The startup surface only ever needs to show the current state. Appending
    gave us a three-line stack where obsolete phases ("init") lingered next
    to current ones ("ready") — collapse it to one live line.
    """
    notice = (title, body)
    if self._state_focus_runtime_notices and self._state_focus_runtime_notices[-1] == notice:
        return
    self._state_focus_runtime_notices = [notice]


def _clear_state_focus_runtime_notice(self) -> None:
    if self._state_focus_runtime_notices:
        self._state_focus_runtime_notices = []


def _sync_state_focus_runtime_notices(self) -> None:
    status = self.runtime.state_focus_runtime_status()
    if not bool(status.get("embedding_ready")):
        return
    runtime_state = str(status.get("runtime_state") or "cold").strip().lower() or "cold"
    # The startup surface is "ready for chat" when the embedding runtime is
    # loaded AND the transcript has been primed (first-turn opener completed).
    # Showing "ready" before the transcript primes was misleading: users
    # saw "ready" but any message they typed was queued until the background
    # opening reply finished.
    transcript_ready = self._startup_transcript_primed
    prime_started = getattr(self, "_startup_prime_started", False)
    # Once truly ready, drop the notice — the phase pip in the status bar
    # carries the "what is Elephant Agent doing" signal from here on.
    if runtime_state == "loaded" and transcript_ready:
        self._clear_state_focus_runtime_notice()
        self._state_focus_runtime_last_state = runtime_state
        return
    if runtime_state == "steadying":
        key_state = "steadying"
        title = "🐘 orienting"
        body = "Getting in step with you — one moment."
    elif runtime_state == "loaded":
        if prime_started:
            key_state = "opening-reply"
            title = "🐾 opening path"
            body = "Shaping the first reply — just a moment."
        else:
            key_state = "embedding-loaded"
            title = "🐘 path nearly ready"
            body = "Personal Model is ready — finishing setup."
    else:
        # cold / pending / downloading all read as "still opening".
        key_state = "opening"
        title = "🐾 opening path"
        body = "I'm settling into your elephant."
    if key_state == self._state_focus_runtime_last_state:
        return
    self._state_focus_runtime_last_state = key_state
    self._set_state_focus_runtime_notice(title, body)
    if runtime_state == "loaded" and not transcript_ready:
        # Keep the "runtime loaded" time stamped so the prime-dispatch
        # idle threshold logic still works, but the banner no longer lies.
        self._state_focus_runtime_ready_seen = True
        self._state_focus_runtime_ready_seen_at = time.monotonic()


def _prepare_startup_surface(self) -> None:
    self._sync_state_focus_runtime_notices()
    if self._startup_surface_prepared or self._startup_surface_prepare_started:
        return
    self._startup_surface_prepare_started = True

    def prepare_surface() -> None:
        try:
            self.runtime.prepare_session_surface(self.session_id)
            self._refresh_skill_slash_specs()
        finally:
            self._startup_surface_prepared = True
            self._sync_state_focus_runtime_notices()

    threading.Thread(
        target=prepare_surface,
        name="elephant-startup-surface",
        daemon=True,
    ).start()


def _prime_startup_transcript_if_needed(self) -> None:
    if self._startup_transcript_primed:
        self._sync_state_focus_runtime_notices()
        return
    self._prime_transcript()
    self._startup_transcript_primed = True
    self._sync_state_focus_runtime_notices()


def _prime_transcript(self, *, use_proactive_opening: bool = True) -> None:
    session = self.runtime.inspect_session(self.session_id)
    continuity = self.runtime.inspect_continuity(session_id=self.session_id)
    state = self.runtime.state_for_elephant(session.elephant_id or "") if session.elephant_id else None
    assistant_name = (
        (state.elephant_name if state is not None else "")
        or companion_display_name(continuity.profile)
        or "Elephant Agent"
    )
    opening_context = ShellOpeningContext(
        opened=self.opened,
        display_name=assistant_name,
        user_profile_text=(continuity.profile.user_profile_text or "").strip(),
        personality=continuity.profile.companion.personality if continuity.profile.companion is not None else (),
        reengagement_style=continuity.reengagement_style,
        wake_action=continuity.wake_action or "",
        wake_summary=continuity.wake_summary or "",
        has_state_focus=bool(state and state.summary.strip()),
        first_language=_first_language_from_runtime(self.runtime, continuity.profile),
    )
    startup_outcome = None
    if use_proactive_opening:
        try:
            startup_outcome = self.runtime.generate_opening_reply(
                session_id=self.session_id,
                prompt=compose_shell_opening_instruction(opening_context),
                opening_label=self.opened,
            )
        except Exception as error:
            if self.debug:
                self._append_entry(
                    "notice",
                    "Startup prompt",
                    f"fallback to local opener\nreason: {error}",
                )
    if startup_outcome is not None and startup_outcome.execution.summary.strip():
        self._append_entry("assistant", assistant_name, startup_outcome.execution.summary.strip())
    else:
        self._append_entry("assistant", assistant_name, compose_shell_opener(opening_context))
    for execution in self.runtime.run_due_cron_jobs(session_id=self.session_id):
        self._append_entry(
            "assistant",
            assistant_name,
            execution.summary,
            meta=f"cron · {execution.job.name}",
        )
    if self.debug:
        provider = dict(self.runtime.provider_summary())
        self._append_entry(
            "notice",
            "Elephant context",
            "\n".join(
                [
                    f"route_id: {session.episode_id}",
                    f"elephant_id: {self.runtime.elephant_id_for_session(session)}",
                    f"model {provider.get('model_id') or provider.get('default_model') or '<unset>'}",
                    f"continuity: {continuity.continuity_summary}",
                    f"state_action: {continuity.wake_action}",
                    f"state_summary: {continuity.wake_summary}",
                    f"reengagement_style: {continuity.reengagement_style}",
                    f"reengagement_prompt: {continuity.reengagement_prompt}",
                ]
            ),
        )
    self._startup_transcript_primed = True


def _assistant_name(self) -> str:
    session = self.runtime.inspect_session(self.session_id)
    state = self.runtime.state_for_elephant(session.elephant_id or "") if session.elephant_id else None
    if state is not None and state.elephant_name.strip():
        return state.elephant_name.strip()
    identity = self.runtime.inspect_identity(session_id=self.session_id)
    if identity.display_name.strip():
        return identity.display_name.strip()
    return "Elephant Agent"


def _append_assistant_surface_reply(self, body: str, *, meta: str = "") -> None:
    self._append_entry("assistant", self._assistant_name(), body, meta=meta)


def _render_shell_frame(self):
    return _render_shell_frame_view(self)


def _render_brand_column(self, session, continuity, provider, growth):
    return _render_shell_brand_column(self, session, continuity, provider, growth)


def _render_status_column(self, session, continuity, context_frame, provider, growth):
    return _render_shell_status_column(self, session, continuity, context_frame, provider, growth)
