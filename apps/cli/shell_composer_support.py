from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .shell_stack import FileHistory, FormattedText, PROMPT_TOOLKIT_AVAILABLE, Style
from .shell_ui import (
    BRAND_ACCENT,
    BRAND_ACCENT_STRONG,
    BRAND_DARK,
    BRAND_LIGHT,
    BRAND_MUTED,
    LIVE_DIFF_ADD_FG,
    LIVE_DIFF_CONTEXT_FG,
    LIVE_DIFF_FILE_FG,
    LIVE_DIFF_HUNK_FG,
    LIVE_DIFF_REMOVE_FG,
    USER_HISTORY_BG,
    USER_HISTORY_FG,
)

LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .shell import ProductizedShell


def shell_history(shell: ProductizedShell):
    return FileHistory(str(shell.runtime.paths.state_dir / "shell-history.txt"))


def history_search_matches(shell: ProductizedShell, query: str) -> list[str]:
    """Unique history entries containing `query` (case-insensitive), newest first."""
    history_strings: list[str] = []
    try:
        history_strings = list(shell_history(shell).get_strings())
    except Exception:
        LOGGER.warning("failed to read shell history for search", exc_info=True)
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


def history_search_active(shell: ProductizedShell) -> bool:
    return bool(getattr(shell, "_history_search_active", False))


def history_search_refresh(shell: ProductizedShell) -> None:
    query = getattr(shell, "_history_search_query", "") or ""
    matches = history_search_matches(shell, query)
    shell._history_search_matches = matches
    if not matches:
        shell._history_search_index = 0
        return
    # Clamp index to the new result set.
    index = int(getattr(shell, "_history_search_index", 0) or 0)
    shell._history_search_index = max(0, min(index, len(matches) - 1))


def history_search_enter(shell: ProductizedShell, buffer) -> None:
    """Enter reverse-search mode. Snapshot current buffer so Esc can restore."""
    shell._history_search_active = True
    shell._history_search_query = ""
    shell._history_search_index = 0
    shell._history_search_prior_text = buffer.text or ""
    history_search_refresh(shell)


def history_search_exit(shell: ProductizedShell, buffer, *, restore: bool) -> None:
    if not history_search_active(shell):
        return
    shell._history_search_active = False
    if restore:
        buffer.text = getattr(shell, "_history_search_prior_text", "") or ""
    shell._history_search_query = ""
    shell._history_search_matches = []
    shell._history_search_index = 0


def history_search_current_match(shell: ProductizedShell) -> str:
    matches = list(getattr(shell, "_history_search_matches", ()) or ())
    if not matches:
        return ""
    index = max(0, min(int(getattr(shell, "_history_search_index", 0) or 0), len(matches) - 1))
    return matches[index]


def history_search_fragments(shell: ProductizedShell):
    if not history_search_active(shell):
        return FormattedText([])
    query = str(getattr(shell, "_history_search_query", "") or "")
    matches = list(getattr(shell, "_history_search_matches", ()) or ())
    total = len(matches)
    index = int(getattr(shell, "_history_search_index", 0) or 0)
    # Compact preview — one-line match, truncated.
    preview = history_search_current_match(shell)
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
