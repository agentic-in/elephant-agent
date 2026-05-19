from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from packages.contracts import ExperienceRecord
from packages.models.reasoning_parser import split_reasoning_and_content

from .shell_banner import status_sections as _banner_status_sections
from .shell_progress import render_tool_trace_text
from .shell_stack import Align, Group, Panel, RICH_AVAILABLE, Table, Text
from .shell_ui import (
    BRAND_ACCENT,
    BRAND_ACCENT_STRONG,
    BRAND_DARK,
    BRAND_LIGHT,
    BRAND_MUTED,
    EXPERIENCE_NOISE_PATTERN,
    GROWTH_HIGHLIGHT_FG,
    GROWTH_LEVEL_PATTERN,
    GROWTH_META_PATTERN,
    GROWTH_PROGRESS_EMPTY,
    GROWTH_PROGRESS_FILLED,
    GROWTH_PROGRESS_WIDTH,
    SETTLED_DIFF_ADD_FG,
    SETTLED_DIFF_CONTEXT_FG,
    SETTLED_DIFF_FILE_FG,
    SETTLED_DIFF_HUNK_FG,
    SETTLED_DIFF_REMOVE_FG,
    SHELL_WELCOME_HEADLINE,
    USER_HISTORY_BG,
    USER_HISTORY_FG,
    compact_line,
    render_growth_mark,
    render_elephant_mark,
    render_highlighted_history_line,
    render_markdown_bold,
    strip_markdown_bold,
)

if TYPE_CHECKING:
    from .shell import ProductizedShell, TranscriptEntry


_BANNER_WIDE_MIN = 132
_BANNER_MEDIUM_MIN = 80


def _banner_layout_mode(console_width: int) -> str:
    """wide / medium / narrow, based on terminal width."""
    if not console_width or console_width >= _BANNER_WIDE_MIN:
        return "wide"
    if console_width >= _BANNER_MEDIUM_MIN:
        return "medium"
    return "narrow"


def render_shell_frame(shell: ProductizedShell):
    session = shell.runtime.inspect_session(shell.session_id)
    continuity = shell.runtime.inspect_continuity(session_id=shell.session_id)
    context_frame = shell.runtime.inspect_context_frame(session.episode_id)
    provider = dict(shell.runtime.provider_summary())
    growth = shell.runtime.inspect_growth(session_id=shell.session_id)
    elephant_id = shell.runtime.elephant_id_for_session(session)
    if RICH_AVAILABLE and Table is not None and Group is not None:
        hero = Table.grid(expand=True)
        console_width = int(getattr(shell.console.size, "width", 0) or 0)
        mode = _banner_layout_mode(console_width)
        if mode == "wide":
            hero.add_column(ratio=13, min_width=72)
            hero.add_column(ratio=12, min_width=42)
            hero.add_row(
                render_brand_column(shell, session, continuity, provider, growth),
                render_status_column(shell, session, continuity, context_frame, provider, growth),
            )
        elif mode == "medium":
            # Single column, keeps brand mark + status stacked vertically.
            hero.add_column(ratio=1, min_width=48)
            hero.add_row(render_brand_column(shell, session, continuity, provider, growth))
            hero.add_row(Text(" "))
            hero.add_row(render_status_column(shell, session, continuity, context_frame, provider, growth))
        else:  # narrow
            # Drop the brand mark — it eats vertical real estate. Show a
            # tight headline + status only.
            hero.add_column(ratio=1, min_width=28)
            narrow_heading = Text(no_wrap=False)
            narrow_heading.append(f"{SHELL_WELCOME_HEADLINE}\n", style=f"bold {BRAND_LIGHT}")
            narrow_heading.append(
                "🐘 Personal Model first · gentle curiosity · living path.",
                style=BRAND_MUTED,
            )
            hero.add_row(narrow_heading)
            hero.add_row(Text(" "))
            hero.add_row(render_status_column(shell, session, continuity, context_frame, provider, growth))
        return Panel(
            hero,
            title=f"[bold {BRAND_ACCENT}] 🐘 Elephant Agent [/bold {BRAND_ACCENT}]",
            subtitle=f"[bold {BRAND_LIGHT}]Personal Model first · curious at your pace[/bold {BRAND_LIGHT}]",
            border_style=BRAND_ACCENT,
            padding=(1, 2),
        )
    # Plain-terminal fallback (no rich): ASCII hero + a few status lines.
    logo = "\n".join(
        (
            "    ___    ________ _____ _____ _____",
            "   /   |  / ____/ //_/ // / ___// ___/",
            "  / /| | / / __/ ,< / ,<  \\__ \\\\__ \\",
            " / ___ |/ /_/ / /| / /| |___/ /__/ /",
            "/_/  |_|\\____/_/ |_/_/ |_/____/____/",
        )
    )
    growth_lines = growth_panel_lines(shell, session, continuity, provider, growth)
    lines = [
        SHELL_WELCOME_HEADLINE,
        "🐘 Personal Model first · gentle curiosity · living path.",
        logo,
        "",
        "models what matters · asks gently · follows the path",
        "",
        "💡 Tips for getting started",
        "Speak directly, or type / to open the command palette.",
        "  · /help for what I can do   · /status to check on me   · /exit to close this thread",
        "",
        "🌱 What Elephant Agent is learning",
        *growth_lines,
        "",
        f"elephant: {elephant_id}",
        "state: active",
        f"provider: {provider['provider_id']} · model: {provider.get('model_id') or provider.get('default_model') or '<unset>'}",
    ]
    return Panel(
        Text("\n".join(lines)),
        title=" 🐘 Elephant Agent ",
        subtitle=" Personal Model first · curious at your pace ",
        border_style="bright_white",
        padding=(1, 2),
    )


def render_brand_column(shell: ProductizedShell, session, continuity, provider, growth):
    elephant_state = shell.runtime.state_for_elephant(shell.runtime.elephant_id_for_session(session))
    display_name = (
        elephant_state.elephant_name
        if elephant_state is not None and elephant_state.elephant_name
        else continuity.profile.state.display_name or "Elephant Agent"
    )
    heading = Text(no_wrap=True)
    heading.append(f"{SHELL_WELCOME_HEADLINE}\n", style=f"bold {BRAND_LIGHT}")
    heading.append("🐘 Personal Model first. Curious by design.", style=BRAND_MUTED)
    meta = Text(no_wrap=True)
    meta.append(f"{display_name}\n", style=f"bold {BRAND_LIGHT}")
    meta.append(
        "understands first · asks gently · picks up the right thread\n",
        style=BRAND_MUTED,
    )
    meta.append(growth.identity_line, style=BRAND_ACCENT_STRONG)
    if Table is None:
        return Group(
            heading,
            shell._render_growth_mark(growth.brand_stage_id, level=growth.level),
            meta,
        )
    brand = Table.grid(expand=True)
    brand.add_column(no_wrap=True)
    brand.add_row(shell._center_brand_block(heading))
    brand.add_row(shell._center_brand_block(Text(" ")))
    brand.add_row(shell._center_brand_block(shell._render_growth_mark(growth.brand_stage_id, level=growth.level)))
    brand.add_row(shell._center_brand_block(Text(" ")))
    brand.add_row(shell._center_brand_block(meta))
    return brand


def _append_status_line(tips: Text, *, label: str, value: str, is_emphasized: bool) -> None:
    base_style = BRAND_LIGHT if is_emphasized else BRAND_MUTED
    tips.append(f"{label} · ", style=f"bold {base_style}")
    tips.append_text(render_markdown_bold(value, base_style=base_style))
    tips.append("\n")


def render_status_column(shell: ProductizedShell, session, continuity, context_frame, provider, growth):
    del provider
    divider = "─" * 44
    sections = _banner_status_sections(shell, session, continuity, context_frame, growth)

    tips = Text()
    for index, (heading, lines) in enumerate(sections):
        if index:
            tips.append(f"{divider}\n", style=BRAND_DARK)
        tips.append(f"{heading}\n", style=f"bold {BRAND_ACCENT}")
        for label, value, is_emphasized in lines:
            _append_status_line(tips, label=label, value=value, is_emphasized=is_emphasized)
    return tips


def skill_inventory_counts(shell: ProductizedShell) -> tuple[int, int]:
    skills = tuple(skill for skill in shell.runtime.skill_catalog(session_id=shell.session_id) if skill.enabled)
    authored_root = shell.runtime.paths.authored_skills_dir.expanduser().resolve()
    self_learned = sum(1 for skill in skills if is_self_learned_skill(skill, authored_root=authored_root))
    return (len(skills), self_learned)


def is_self_learned_skill(skill, *, authored_root: Path) -> bool:
    source_kind = str(skill.metadata.get("source_kind") or "").strip()
    if source_kind == "elephant-experience":
        return True
    provenance = str(skill.provenance or skill.metadata.get("entry_path") or "").strip()
    if not provenance:
        return False
    try:
        Path(provenance).expanduser().resolve().relative_to(authored_root)
    except (ValueError, OSError):
        return False
    return True


def render_pending_entries(shell: ProductizedShell) -> None:
    pending = shell.transcript[shell._rendered_entries :]
    if not pending:
        render_pending_context_compaction_frame(shell)
        return
    previous_kind = shell.transcript[shell._rendered_entries - 1].kind if shell._rendered_entries else None
    # Collect all renderables into a single batch to avoid multiple
    # console.print() calls which cause visible flicker between entries.
    parts: list[object] = []
    index = 0
    while index < len(pending):
        entry = pending[index]
        if entry.kind == "assistant" and previous_kind in {"user", "tooltrace"}:
            parts.append(Text(""))
        if entry.kind == "tooltrace":
            if previous_kind == "assistant":
                parts.append(Text(""))
            grouped_entries = [entry]
            index += 1
            while index < len(pending) and pending[index].kind == "tooltrace":
                grouped_entries.append(pending[index])
                index += 1
            parts.append(render_tooltrace_entries(tuple(grouped_entries)))
            previous_kind = "tooltrace"
            continue
        parts.append(render_entry(shell, entry))
        previous_kind = entry.kind
        index += 1
    if parts:
        if Group is not None and len(parts) > 1:
            shell.console.print(Group(*parts))
        else:
            for part in parts:
                shell.console.print(part)
    shell._rendered_entries = len(shell.transcript)
    render_pending_context_compaction_frame(shell)


def render_pending_context_compaction_frame(shell: ProductizedShell) -> None:
    # Context compaction is now surfaced as a transcript notice entry via
    # turn_metrics._append_outcome. This function is retained as a no-op
    # for callers that haven't been updated yet.
    pass


def _entry_reasoning_and_response(body: str) -> tuple[str, str]:
    parsed = split_reasoning_and_content(body, streaming=False)
    reasoning = strip_markdown_bold(parsed.reasoning).strip()
    response = parsed.content.strip()
    return reasoning, response


def _format_entry_reasoning_display(reasoning: str, response: str) -> str:
    from .shell_progress_trace import format_reasoning_display_text

    return format_reasoning_display_text(reasoning, response)


# Cap noisy transcript entries so long file reads / tool outputs don't
# flood the terminal. The full body is preserved on the shell under
# `_folded_entry_bodies` — `/expand last` can re-render it.
_MAX_TRANSCRIPT_BODY_LINES = 24
_MAX_TRANSCRIPT_BODY_CHARS = 2400

# Quick-fix hints for common recovery messages — each entry is a
# (substring match, inline hint) pair. The match is case-insensitive.
_RECOVERY_QUICK_FIX_HINTS: tuple[tuple[str, str], ...] = (
    ("invalid key:", "Try F1 or `?` for the cheatsheet of valid bindings."),
    ("no module named", "Check your virtualenv — something isn't importable."),
    ("permission denied", "This path might be outside the current project root."),
    (
        "connection refused",
        "The provider endpoint didn't answer — check /providers status.",
    ),
    ("token limit", "The conversation got long. Try /clear and start a fresh thread."),
    ("unauthorized", "Your provider key looks off — run /providers to update."),
    ("rate limit", "Provider is rate-limiting us. Wait a moment and try again."),
)


def _recovery_quick_fix_hint(body: str) -> str:
    text = (body or "").lower()
    for needle, hint in _RECOVERY_QUICK_FIX_HINTS:
        if needle in text:
            return hint
    return ""


def _fold_long_body(shell: ProductizedShell, entry: TranscriptEntry) -> tuple[str, bool]:
    """Return (possibly folded body, folded?).

    Keeps assistant/user/tooltrace untouched — folding only applies to
    notice/status entries that carry verbose dumps. Stores the full
    body on the shell keyed by (kind, title, body_id) so `/expand last`
    can restore it.
    """
    if entry.kind in {"assistant", "user", "growth", "tooltrace", "recovery"}:
        return entry.body, False
    body = entry.body or ""
    line_count = body.count("\n") + 1
    char_count = len(body)
    if line_count <= _MAX_TRANSCRIPT_BODY_LINES and char_count <= _MAX_TRANSCRIPT_BODY_CHARS:
        return body, False
    # Keep the head (most-recent information first in most dumps is rare,
    # so showing the head is the right default). Tail an ellipsis so users
    # know it's been trimmed.
    head_lines = body.split("\n")[:_MAX_TRANSCRIPT_BODY_LINES]
    hidden = line_count - len(head_lines)
    fold_marker = f"… {hidden} more line(s) hidden · type /expand last to see the whole thing"
    head = "\n".join(head_lines)
    if len(head) > _MAX_TRANSCRIPT_BODY_CHARS:
        head = head[: _MAX_TRANSCRIPT_BODY_CHARS - 1] + "…"
    # Persist the full body so /expand can retrieve it.
    full_bodies = getattr(shell, "_folded_entry_bodies", None)
    if full_bodies is None:
        full_bodies = {}
        shell._folded_entry_bodies = full_bodies
    full_bodies["__last__"] = body
    return f"{head}\n{fold_marker}", True


def render_entry(shell: ProductizedShell, entry: TranscriptEntry):
    styles = {
        "assistant": BRAND_LIGHT,
        "user": USER_HISTORY_FG,
        "growth": BRAND_ACCENT_STRONG,
        "tooltrace": BRAND_ACCENT_STRONG,
        "command": BRAND_ACCENT,
        "status": "bright_black",
        "notice": "white",
        "recovery": "#79afd4",
    }
    if entry.kind == "tooltrace":
        return render_tooltrace_entry(entry)
    if entry.kind in {"assistant", "user", "growth"}:
        if RICH_AVAILABLE:
            return render_chat_entry(shell, entry, accent=styles.get(entry.kind, "white"))
        reasoning = response = ""
        if entry.kind == "assistant":
            reasoning, response = _entry_reasoning_and_response(entry.body)
            plain_body = _format_entry_reasoning_display(reasoning, response)
        else:
            plain_body = strip_markdown_bold(entry.body)
        prefix = "" if entry.kind in {"user", "growth"} or reasoning else "● "
        lines = [f"{prefix}{plain_body}"]
        if entry.meta:
            lines.append(entry.meta)
        return "\n".join(lines) + "\n"
    # Notices render as compact inline lines (no Panel border).
    if entry.kind == "notice":
        body, _folded = _fold_long_body(shell, entry)
        compact = f"{entry.title}  {body}".strip() if body else entry.title
        return f"\033[2m{compact}\033[0m\n"
    # Errors/recovery entries get a prefix glyph so they stand out in the
    # transcript wall. Other kinds (status, command) render as-is.
    body, folded = _fold_long_body(shell, entry)
    title = entry.title
    if entry.kind == "recovery":
        body = body if body.startswith(("⚠", "✖", "⏹")) else f"⚠  {body}"
        title = title if title.startswith(("⚠", "✖", "⏹")) else f"⚠  {title}"
        # Quick-fix hint appended inline if we recognize the error shape.
        hint = _recovery_quick_fix_hint(entry.body)
        if hint and hint not in body:
            body = f"{body}\n\n↳ {hint}"
    subtitle = entry.meta
    if folded and not subtitle:
        subtitle = "folded · /expand last"
    return Panel(
        Text(body),
        title=title,
        subtitle=subtitle,
        border_style=styles.get(entry.kind, "white"),
        padding=(0, 1),
    )


def growth_panel_lines(shell: ProductizedShell, session, continuity, provider, growth) -> tuple[str, ...]:
    total_skills, self_learned_skills = skill_inventory_counts(shell)
    lines = [
        f"understanding · {growth.identity_line}",
        f"learning · {growth_progress_bar(growth)} · {growth.progress_percent}%",
        f"skills · {total_skills} enabled · {self_learned_skills} self-learned",
    ]
    lines.extend(
        [
            (f"history · {growth.canonical_dialogues} dialogues · {growth.canonical_active_days} active day(s)"),
            (f"saved work · {growth.canonical_experiences} experience(s) · {growth.state.total_tokens} tokens seen"),
        ]
    )
    experiences = shell.runtime.inspect_experiences(session_id=session.episode_id, limit=2)
    displayable = displayable_experiences(experiences)
    if displayable:
        lines.extend(recent_experience_lines(displayable))
        lines.append(f"latest · {format_experience_status(displayable[0])}")
    else:
        lines.append("latest · no captured grounded experience yet")
    return tuple(lines)


def recent_activity_lines(shell: ProductizedShell, session, continuity, provider) -> tuple[str, ...]:
    growth = shell.runtime.inspect_growth(session_id=session.episode_id)
    return growth_panel_lines(shell, session, continuity, provider, growth)


def recent_experience_lines(
    experiences: tuple[ExperienceRecord, ...],
) -> tuple[str, ...]:
    return tuple(f"evidence · {format_experience_status(experience)}" for experience in experiences)


def displayable_experiences(
    experiences: tuple[ExperienceRecord, ...],
) -> tuple[ExperienceRecord, ...]:
    filtered = tuple(experience for experience in experiences if should_display_experience(experience))
    return filtered[:2]


def should_display_experience(experience: ExperienceRecord) -> bool:
    title = " ".join(experience.title.split()).strip()
    summary = " ".join(experience.summary.split()).strip()
    text = f"{title} {summary}".strip()
    if not text:
        return False
    lowered = text.lower()
    if EXPERIENCE_NOISE_PATTERN.match(title) or EXPERIENCE_NOISE_PATTERN.match(summary):
        return False
    if "requires an 'action' argument" in lowered:
        return False
    if "controls:" in lowered and "outcome: error" in lowered:
        return False
    return True


def format_experience_status(experience: ExperienceRecord) -> str:
    markers = [experience.status]
    if experience.tool_call_count:
        markers.append(f"tools={experience.tool_call_count}")
    if experience.model_turn_count:
        markers.append(f"turns={experience.model_turn_count}")
    if experience.related_skill_ids:
        markers.append(f"skills={len(experience.related_skill_ids)}")
    title = compact_line(experience.title, limit=68)
    return f"{title} [{', '.join(markers)}]"


def growth_progress_counts(growth, *, width: int = GROWTH_PROGRESS_WIDTH) -> tuple[int, int]:
    filled = min(width, max(0, round(growth.progress_ratio * width)))
    if growth.progress_ratio > 0 and filled == 0:
        filled = 1
    if growth.progress_ratio < 1 and filled == width:
        filled = width - 1
    return filled, width - filled


def growth_progress_bar(growth, *, width: int = GROWTH_PROGRESS_WIDTH) -> str:
    filled, empty = growth_progress_counts(growth, width=width)
    return (GROWTH_PROGRESS_FILLED * filled) + (GROWTH_PROGRESS_EMPTY * empty)


def styled_growth_progress_bar(growth, *, width: int = GROWTH_PROGRESS_WIDTH):
    bar = Text()
    filled, empty = growth_progress_counts(growth, width=width)
    if filled:
        bar.append(GROWTH_PROGRESS_FILLED * filled, style=BRAND_ACCENT_STRONG)
    if empty:
        bar.append(GROWTH_PROGRESS_EMPTY * empty, style=BRAND_MUTED)
    return bar


def _is_table_separator_line(line: str) -> bool:
    """Check if a line is a markdown table separator (e.g. |---|---|)."""
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return False
    inner = stripped[1:-1]
    return all(char in "-|: " for char in inner) and "-" in inner


def _is_table_row_line(line: str) -> bool:
    """Check if a line looks like a markdown table row (| col | col |)."""
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 3


def _parse_table_block(lines: list[str], start_index: int) -> tuple[list[list[str]], int]:
    """Parse a markdown table starting at start_index.

    Returns (rows, end_index) where rows is a list of cell-value lists
    and end_index is the index after the last table line.
    """
    rows: list[list[str]] = []
    index = start_index
    while index < len(lines) and _is_table_row_line(lines[index]):
        row_text = lines[index].strip()
        cells = [cell.strip() for cell in row_text.strip("|").split("|")]
        if not _is_table_separator_line(lines[index]):
            rows.append(cells)
        index += 1
    return rows, index


def _build_rich_table(rows: list[list[str]]) -> Table:
    """Build a Rich Table with white border minimalist style from parsed rows."""
    from rich.box import SIMPLE_HEAVY

    table = Table(
        box=SIMPLE_HEAVY,
        border_style="white",
        header_style=f"bold {BRAND_LIGHT}",
        show_edge=True,
        pad_edge=True,
        padding=(0, 1),
    )
    if not rows:
        return table
    # First row as table header
    header = rows[0]
    for col_name in header:
        table.add_column(col_name, style=BRAND_LIGHT)
    # Subsequent rows as data
    for row in rows[1:]:
        # Pad columns to match header width
        padded = row + [""] * (len(header) - len(row)) if len(row) < len(header) else row[: len(header)]
        table.add_row(*padded)
    return table


def _render_assistant_response(response: str) -> Text | list[object]:
    """Render assistant response as lightweight styled Rich Text.

    Uses only brand-palette colors. Handles bold, italic, code, headings,
    lists, blockquotes, and **tables**. When tables are present, returns a
    list of renderables (Text segments + Table objects); otherwise returns
    a single Text object.
    """
    import re as _re

    lines = response.split("\n")
    bold_italic_pat = _re.compile(r"\*\*\*(.+?)\*\*\*")
    bold_pat = _re.compile(r"\*\*(.+?)\*\*")
    italic_pat = _re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
    code_pat = _re.compile(r"`([^`]+)`")
    link_pat = _re.compile(r"\[([^\]]+)\]\([^)]+\)")
    in_code_block = False

    # Collect render fragments: may be Text or Table
    renderables: list[object] = []
    current_block = Text()
    has_tables = False

    line_index = 0
    while line_index < len(lines):
        line = lines[line_index]

        # Detect table start
        if not in_code_block and _is_table_row_line(line):
            table_rows, end_index = _parse_table_block(lines, line_index)
            if len(table_rows) >= 2:  # At least header + one data row to count as a table
                has_tables = True
                # Save current text block
                if current_block.plain:
                    renderables.append(current_block)
                current_block = Text()
                # Build Rich Table
                renderables.append(_build_rich_table(table_rows))
                line_index = end_index
                continue

        if line_index > 0 or renderables:
            if current_block.plain or renderables:
                current_block.append("\n")
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            current_block.append(line, style=BRAND_MUTED)
            line_index += 1
            continue
        if in_code_block:
            current_block.append(line, style=BRAND_MUTED)
            line_index += 1
            continue
        heading_match = _re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading_match:
            level = len(heading_match.group(1))
            style = f"bold {BRAND_ACCENT_STRONG}" if level <= 2 else f"bold {BRAND_LIGHT}"
            current_block.append(heading_match.group(2), style=style)
            line_index += 1
            continue
        if _re.match(r"^[-*_]{3,}\s*$", line):
            current_block.append("─" * 40, style=BRAND_DARK)
            line_index += 1
            continue
        list_match = _re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", line)
        if list_match:
            current_block.append(f"{list_match.group(1)}{list_match.group(2)} ", style=BRAND_ACCENT)
            _append_inline_formatted(
                current_block,
                list_match.group(3),
                bold_italic_pat,
                bold_pat,
                italic_pat,
                code_pat,
                link_pat,
            )
            line_index += 1
            continue
        if line.startswith(">"):
            current_block.append("│ ", style=BRAND_MUTED)
            _append_inline_formatted(
                current_block,
                line.lstrip("> "),
                bold_italic_pat,
                bold_pat,
                italic_pat,
                code_pat,
                link_pat,
            )
            line_index += 1
            continue
        _append_inline_formatted(
            current_block,
            line,
            bold_italic_pat,
            bold_pat,
            italic_pat,
            code_pat,
            link_pat,
        )
        line_index += 1

    # If no table detected, keep original return type
    if not has_tables:
        return current_block
    # When tables exist, collect the last text block and return a list
    if current_block.plain:
        renderables.append(current_block)
    return renderables


def _append_inline_formatted(block: Text, text: str, bold_italic_pat, bold_pat, italic_pat, code_pat, link_pat):
    """Append text with inline markdown formatting (bold, italic, code, links)."""
    patterns = [
        (bold_italic_pat, f"bold italic {BRAND_LIGHT}"),
        (bold_pat, f"bold {BRAND_LIGHT}"),
        (italic_pat, f"italic {BRAND_LIGHT}"),
        (code_pat, BRAND_MUTED),
        (link_pat, BRAND_ACCENT),
    ]
    segments: list[tuple[int, int, str, str]] = []
    for pattern, style in patterns:
        for match in pattern.finditer(text):
            segments.append((match.start(), match.end(), match.group(1), style))
    segments.sort(key=lambda s: s[0])
    filtered: list[tuple[int, int, str, str]] = []
    last_end = 0
    for start, end, display, style in segments:
        if start >= last_end:
            filtered.append((start, end, display, style))
            last_end = end
    cursor = 0
    for start, end, display, style in filtered:
        if start > cursor:
            block.append(text[cursor:start], style=BRAND_LIGHT)
        block.append(display, style=style)
        cursor = end
    if cursor < len(text):
        block.append(text[cursor:], style=BRAND_LIGHT)


def render_chat_entry(shell: ProductizedShell, entry: TranscriptEntry, *, accent: str):
    if entry.kind in {"user", "growth"}:
        block = Text()
        lines = strip_markdown_bold(entry.body).splitlines() or [""]
        body_style = f"{USER_HISTORY_FG} on {USER_HISTORY_BG}"
        meta_style = f"{BRAND_MUTED} on {USER_HISTORY_BG}"
        for index, line in enumerate(lines):
            prefix = "› " if index == 0 else "  "
            padded_line = shell._pad_history_line(f"{prefix}{line}")
            if entry.kind == "growth":
                block.append_text(
                    render_highlighted_history_line(
                        padded_line,
                        base_style=body_style,
                        highlight_pattern=GROWTH_LEVEL_PATTERN,
                        highlight_style=f"{GROWTH_HIGHLIGHT_FG} on {USER_HISTORY_BG}",
                    )
                )
            else:
                block.append(padded_line, style=body_style)
            block.append("\n")
        if entry.meta:
            for meta_line in entry.meta.splitlines() or [""]:
                padded_meta = shell._pad_history_line(f"  {meta_line}")
                if entry.kind == "growth":
                    block.append_text(
                        render_highlighted_history_line(
                            padded_meta,
                            base_style=meta_style,
                            highlight_pattern=GROWTH_META_PATTERN,
                            highlight_style=f"{GROWTH_HIGHLIGHT_FG} on {USER_HISTORY_BG}",
                        )
                    )
                else:
                    block.append(padded_meta, style=meta_style)
                block.append("\n")
        return block

    block = Text()
    reasoning, response = _entry_reasoning_and_response(entry.body)
    if not reasoning:
        block.append("● ", style=f"bold {accent}")
    if reasoning:
        from .shell_progress_trace import STREAM_REASONING_HEADING

        block.append(STREAM_REASONING_HEADING, style=f"bold {BRAND_ACCENT_STRONG}")
        block.append("\n")
        block.append(reasoning, style=BRAND_MUTED)
        if response:
            block.append("\n\n")

    # Render the response body with lightweight markdown formatting.
    response_payload = response if response else (entry.body if not reasoning else "")
    if response_payload:
        rendered = _render_assistant_response(response_payload)
        if isinstance(rendered, list):
            # Mixed render with tables: return Group
            if block.plain:
                parts: list[object] = [block]
            else:
                parts = []
            parts.extend(rendered)
            if entry.meta:
                meta_text = Text(f"\n{entry.meta}", style=BRAND_MUTED)
                parts.append(meta_text)
            if Group is not None:
                return Group(*parts)
            # fallback: print one by one
            return parts
        else:
            block.append_text(rendered)
    elif not reasoning and not response:
        block.append_text(render_markdown_bold(entry.body, base_style=BRAND_LIGHT))
    if entry.meta:
        block.append(f"\n{entry.meta}", style=BRAND_MUTED)
    block.append("\n")
    return block


def render_tooltrace_entry(entry: TranscriptEntry):
    return render_tooltrace_entries((entry,))


def render_tooltrace_entries(entries: tuple[TranscriptEntry, ...]):
    if not RICH_AVAILABLE:
        lines: list[str] = []
        for entry in entries:
            body_lines = entry.body.splitlines() or [entry.body]
            lines.extend(strip_markdown_bold(line).rstrip("\n") for line in body_lines)
            if entry.meta:
                lines.extend(entry.meta.splitlines())
        return "\n".join(line for line in lines if line)

    block = Text()
    for entry_index, entry in enumerate(entries):
        body_lines = entry.body.splitlines() or [entry.body]
        normalized_body_lines = [strip_markdown_bold(line).rstrip("\n") for line in body_lines]
        for line_index, body_line in enumerate(normalized_body_lines):
            if body_line:
                block.append_text(_render_tooltrace_body_line(body_line))
            is_last_body_line = line_index == len(normalized_body_lines) - 1
            if not is_last_body_line or entry.meta or entry_index < len(entries) - 1:
                block.append("\n")
        if entry.meta:
            meta_lines = entry.meta.splitlines() or [entry.meta]
            for meta_index, meta_line in enumerate(meta_lines):
                block.append(meta_line, style=BRAND_MUTED)
                is_last_meta_line = meta_index == len(meta_lines) - 1
                if not is_last_meta_line or entry_index < len(entries) - 1:
                    block.append("\n")
    return block


def _render_tooltrace_body_line(line: str) -> Text:
    if line.startswith("a/") and " → b/" in line:
        return Text(line, style=SETTLED_DIFF_FILE_FG)
    if line.startswith("@@"):
        return Text(line, style=SETTLED_DIFF_HUNK_FG)
    if line.startswith("+"):
        return Text(line, style=SETTLED_DIFF_ADD_FG)
    if line.startswith("-"):
        return Text(line, style=SETTLED_DIFF_REMOVE_FG)
    if line.startswith(" "):
        return Text(line, style=SETTLED_DIFF_CONTEXT_FG)
    if line.startswith("… omitted ") and "diff line(s)" in line:
        return Text(line, style=SETTLED_DIFF_CONTEXT_FG)
    return render_tool_trace_text(line)


def center_brand_block(renderable):
    if Align is None:
        return renderable
    return Align.center(renderable)


def render_growth_mark_for_stage(stage_id: str, *, level: int | None = None):
    return render_growth_mark(stage_id, level=level)


def render_elephant_brand_mark():
    return render_elephant_mark()
