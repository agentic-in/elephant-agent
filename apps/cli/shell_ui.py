from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
import re

from .shell_stack import RICH_AVAILABLE, Text, rich_cell_len

BRAND_ACCENT = "#79afd4"
BRAND_ACCENT_STRONG = "#b8dcf2"
BRAND_LIGHT = "#edf7ff"
BRAND_MUTED = "#9bbbd0"
BRAND_DARK = "#365f78"
LIVE_DIFF_FILE_FG = "#8fc0de"
LIVE_DIFF_HUNK_FG = "#b8dcf2"
LIVE_DIFF_ADD_FG = "#8ff0aa"
LIVE_DIFF_REMOVE_FG = "#ff9f8f"
LIVE_DIFF_CONTEXT_FG = "#c9d2de"
SETTLED_DIFF_FILE_FG = "#5f95b8"
SETTLED_DIFF_HUNK_FG = "#79afd4"
SETTLED_DIFF_ADD_FG = "#5c9a70"
SETTLED_DIFF_REMOVE_FG = "#aa6c63"
SETTLED_DIFF_CONTEXT_FG = "#7d8798"
COMMAND_PALETTE_VISIBLE_ROWS = 6
USER_HISTORY_BG = "#173141"
USER_HISTORY_FG = "#edf7ff"
SHELL_WELCOME_HEADLINE = "Your elephant still knows the path."
GROWTH_PROGRESS_WIDTH = 14
GROWTH_PROGRESS_FILLED = "▰"
GROWTH_PROGRESS_EMPTY = "▱"
GROWTH_HIGHLIGHT_FG = BRAND_ACCENT_STRONG
QUEUE_PREVIEW_INSET = 3
MARKDOWN_BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*")
WEB_URL_PATTERN = re.compile(r"(https?://[^\s]+)", re.IGNORECASE)
EXPERIENCE_NOISE_PATTERN = re.compile(
    r"^(?:it looks like|i couldn't|i could not|sorry|tool failed\b|unable to\b)",
    re.IGNORECASE,
)
GROWTH_LEVEL_PATTERN = re.compile(r"\bLv\.\d+\b")
GROWTH_META_PATTERN = re.compile(r"\b(checkpoint|clearer path)\b")
# ASCII elephant mark for CLI surfaces. Keep this as literal text so terminal
# rendering preserves the lightweight side-profile mascot.
ELEPHANT_STAGE_ROWS = (
    "        /  \\~~~/  \\",
    "      (     ..    )---.",
    "       \\__     __/    \\",
    "        )|  /)         |",
    "       / | / /~~~\\    /",
    "      '-'-'     `---'",
)
HATCHLING_HEAD_ROWS = ELEPHANT_STAGE_ROWS[:8]
SEED_STAGE_ROWS = ELEPHANT_STAGE_ROWS
HATCHLING_STAGE_ROWS = ELEPHANT_STAGE_ROWS
SCOUT_STAGE_ROWS = ELEPHANT_STAGE_ROWS
GROWTH_STAGE_ROWS = {
    "seed": ELEPHANT_STAGE_ROWS,
    "elephant": ELEPHANT_STAGE_ROWS,
    "scout": ELEPHANT_STAGE_ROWS,
}
GROWTH_MARK_CANVAS_WIDTH = max(
    24,
    *(
        len(row)
        for rows in (
            ELEPHANT_STAGE_ROWS,
            SEED_STAGE_ROWS,
            HATCHLING_STAGE_ROWS,
            SCOUT_STAGE_ROWS,
            ELEPHANT_STAGE_ROWS,
        )
        for row in rows
    ),
)


def display_path(path: Path) -> str:
    home = Path.home()
    try:
        return f"~/{path.relative_to(home)}"
    except ValueError:
        return str(path)


# Terminals we know handle OSC 8 hyperlinks well. TERM_PROGRAM is set
# by each of these on macOS and Linux; on other hosts we skip wrapping
# to avoid leaking escape bytes into a terminal that renders them as
# literal text.
_OSC8_FRIENDLY_TERMS = frozenset(
    {
        "iterm.app",
        "wezterm",
        "kitty",
        "ghostty",
        "vscode",
        "cursor",
        "warpterminal",
        "warp",
        "apple_terminal",
    }
)


def terminal_supports_hyperlinks() -> bool:
    """True when the current terminal is known to render OSC 8 links.

    Conservative by default — an unknown terminal returns False rather
    than emit bytes that might show up as literal garbage.
    """
    import os as _os

    if _os.environ.get("ELEPHANT_NO_HYPERLINKS") == "1":
        return False
    if _os.environ.get("NO_COLOR"):
        # Respect NO_COLOR as a "plain text please" signal.
        return False
    term_program = (_os.environ.get("TERM_PROGRAM") or "").strip().lower()
    if term_program and term_program in _OSC8_FRIENDLY_TERMS:
        return True
    # Some hosts set TERM to "xterm-kitty" etc. — sniff that too.
    term = (_os.environ.get("TERM") or "").strip().lower()
    if term in {"xterm-kitty", "wezterm"}:
        return True
    return False


def wrap_file_hyperlink(absolute_path: str, *, line: int | None = None, label: str | None = None) -> str:
    """Wrap a file path in an OSC 8 escape sequence when the terminal supports it.

    Silently returns the raw label (or path) on unsupported terminals so
    callers never need to branch. Accepts an optional line number that
    most editors honor through the `file://` URL fragment (`#L42`).
    """
    raw_path = str(absolute_path or "").strip()
    if not raw_path:
        return str(label or "")
    text = str(label or raw_path)
    if not terminal_supports_hyperlinks():
        return text
    # Build the file:// URL. Line hint piggybacks on the fragment, which
    # Kitty, iTerm2, and WezTerm accept; other terminals ignore it
    # harmlessly.
    uri = f"file://{raw_path}"
    if line and line > 0:
        uri = f"{uri}#L{int(line)}"
    return f"\x1b]8;;{uri}\x1b\\{text}\x1b]8;;\x1b\\"


def display_width(content: str) -> int:
    if RICH_AVAILABLE:
        return rich_cell_len(content)
    return len(content)


def compact_line(value: str, *, limit: int) -> str:
    compact = " ".join(value.split()).strip()
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."


def render_stage_zero_elephant_mark():
    return _render_pixel_mark(centered_elephant_rows(), fallback="[Elephant Agent elephant]")


def render_elephant_mark():
    return _render_pixel_mark(centered_elephant_rows(), fallback="[Elephant Agent elephant]")


def render_growth_mark(stage_id: str, *, level: int | None = None):
    rows = _growth_rows(stage_id, level=level)
    fallback = (
        "[Elephant Agent elephant]" if stage_id == "seed" and (level or 0) <= 0 else f"[Elephant Agent {stage_id}]"
    )
    centered = rows if _uses_literal_cells(rows) else visual_centered_rows(rows, width=GROWTH_MARK_CANVAS_WIDTH)
    return _render_pixel_mark(centered, fallback=fallback)


def centered_elephant_rows() -> tuple[str, ...]:
    """Return the shared elephant mark rows for CLI frames."""
    if _uses_literal_cells(ELEPHANT_STAGE_ROWS):
        return ELEPHANT_STAGE_ROWS
    return visual_centered_rows(ELEPHANT_STAGE_ROWS, width=GROWTH_MARK_CANVAS_WIDTH)


def centered_rows(rows: tuple[str, ...], *, width: int | None = None) -> tuple[str, ...]:
    resolved_width = width or max(len(row) for row in rows)
    centered: list[str] = []
    for row in rows:
        padding = resolved_width - len(row)
        left = padding // 2
        right = padding - left
        centered.append((" " * left) + row + (" " * right))
    return tuple(centered)


def visual_centered_rows(rows: tuple[str, ...], *, width: int | None = None) -> tuple[str, ...]:
    """Center the visible pixels, not the transparent source-canvas whitespace."""
    visible_cells = [index for row in rows for index, cell in enumerate(row) if cell != " "]
    if not visible_cells:
        return centered_rows(rows, width=width)
    visible_left = min(visible_cells)
    visible_right = max(visible_cells)
    visible_width = visible_right - visible_left + 1
    resolved_width = max(width or visible_width, visible_width)
    target_left = (resolved_width - visible_width) // 2
    target_right = resolved_width - visible_width - target_left
    centered: list[str] = []
    for row in rows:
        segment = row.ljust(visible_right + 1)[visible_left : visible_right + 1]
        centered.append((" " * target_left) + segment + (" " * target_right))
    return tuple(centered)


def resolve_elephant_version() -> str:
    try:
        return package_version("elephant")
    except PackageNotFoundError:
        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        if pyproject.exists():
            for raw in pyproject.read_text(encoding="utf-8").splitlines():
                stripped = raw.strip()
                if stripped.startswith("version = "):
                    return stripped.split("=", 1)[1].strip().strip('"')
        return "dev"


def strip_markdown_bold(text: str) -> str:
    return MARKDOWN_BOLD_PATTERN.sub(lambda match: match.group(1), text)


def render_markdown_bold(text: str, *, base_style: str) -> Text:
    rendered = Text()
    cursor = 0
    for match in MARKDOWN_BOLD_PATTERN.finditer(text):
        if match.start() > cursor:
            rendered.append(text[cursor : match.start()], style=base_style)
        rendered.append(match.group(1), style=f"bold {base_style}")
        cursor = match.end()
    if cursor < len(text):
        rendered.append(text[cursor:], style=base_style)
    if not text:
        rendered.append("", style=base_style)
    return rendered


def render_highlighted_history_line(
    text: str,
    *,
    base_style: str,
    highlight_pattern: re.Pattern[str],
    highlight_style: str,
) -> Text:
    rendered = Text(text, style=base_style)
    for match in highlight_pattern.finditer(text):
        rendered.stylize(highlight_style, match.start(), match.end())
    return rendered


def _growth_rows(stage_id: str, *, level: int | None = None) -> tuple[str, ...]:
    if stage_id == "seed" and (level or 0) <= 0:
        return ELEPHANT_STAGE_ROWS
    return GROWTH_STAGE_ROWS.get(stage_id, ELEPHANT_STAGE_ROWS)


_PIXEL_MARK_PALETTE = {
    "g": "#7c8b78",
    "b": "#79afd4",
    "c": "#c8c3ba",
    "t": "#fbf5e9",
    "m": "#92998d",
    "d": "#bf6f51",
    "s": "#e7dfd1",
    "k": "#252829",
    "x": "#252829",
    " ": None,
}


def _uses_literal_cells(rows: tuple[str, ...]) -> bool:
    return any(cell not in _PIXEL_MARK_PALETTE for row in rows for cell in row)


def _render_pixel_mark(rows: tuple[str, ...], *, fallback: str):
    if not RICH_AVAILABLE:
        return Text(fallback)
    if _uses_literal_cells(rows):
        return Text("\n".join(rows), style=BRAND_LIGHT, no_wrap=True)
    glyph = Text(no_wrap=True)
    for row_index, row in enumerate(rows):
        for cell in row:
            color = _PIXEL_MARK_PALETTE.get(cell)
            if color is None:
                glyph.append(" ")
            else:
                glyph.append("█", style=color)
        if row_index < len(rows) - 1:
            glyph.append("\n")
    return glyph
