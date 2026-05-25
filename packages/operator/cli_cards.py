"""Shared terminal card rendering for app command surfaces."""

from __future__ import annotations

from dataclasses import dataclass

from .shell_stack import Align, Console, Group, Panel, RICH_AVAILABLE, Text
from .shell_ui import (
    BRAND_ACCENT,
    BRAND_ACCENT_STRONG,
    BRAND_LIGHT,
    BRAND_MUTED,
    render_cli_banner_mark,
)

CLI_THEME_TITLE_GLYPH = "🐘"
CLI_THEME_BULLET = "•"
CLI_THEME_WELCOME_GLYPH = "🐘"
CLI_THEME_SUBTITLE = "Personal Model first, curious at your pace."
CLI_COMMAND_GLYPHS = (
    ("elephant init", "🐘"),
    ("elephant wake", "🐾"),
    ("elephant dashboard", "🗺️"),
    ("elephant herd new", "🐘"),
    ("elephant herd", "🐘"),
    ("elephant provider", "🧩"),
    ("elephant facts", "🐘"),
    ("elephant reflect", "🌱"),
    ("elephant skills", "📚"),
    ("elephant gateway", "💬"),
    ("elephant cron", "⏰"),
    ("elephant status", "📋"),
)


@dataclass(frozen=True, slots=True)
class CliCardSection:
    title: str
    lines: tuple[str, ...] = ()


def _command_hint_glyph(command: str) -> str:
    normalized = " ".join(command.split()).strip()
    for prefix, glyph in CLI_COMMAND_GLYPHS:
        if normalized.startswith(prefix):
            return glyph
    return CLI_THEME_BULLET


def _format_command_hint(command: str) -> str:
    return f"{_command_hint_glyph(command)} {command}"


def _append_command_highlight(target: Text, line: str) -> None:
    marker = " · "
    command_part, separator, detail_part = line.partition(marker)
    leading_token = command_part.split(maxsplit=1)[0] if command_part else ""
    has_command_glyph = leading_token == CLI_THEME_BULLET or any(
        leading_token == glyph for _, glyph in CLI_COMMAND_GLYPHS
    )
    if not has_command_glyph:
        target.append(f"{CLI_THEME_BULLET} ", style=BRAND_MUTED)
    if separator:
        target.append(command_part, style=f"bold {BRAND_ACCENT_STRONG}")
        target.append(separator, style=BRAND_MUTED)
        target.append(detail_part, style=BRAND_LIGHT)
    else:
        target.append(line, style=BRAND_LIGHT)


def _print_heading(title: str, detail: str | None = None) -> None:
    print(f"{CLI_THEME_TITLE_GLYPH} {title}")
    if detail:
        print(f"  {detail}")


def _print_bullet(text: str) -> None:
    print(f"  {CLI_THEME_BULLET} {text}")


def _print_command_hints(*commands: str) -> None:
    if not commands:
        return
    print("  next_invocations:")
    for command in commands:
        print(f"  {_format_command_hint(command)}")


def _print_cli_card(
    title: str,
    detail: str | None = None,
    *,
    sections: tuple[CliCardSection, ...] = (),
    next_commands: tuple[str, ...] = (),
    tagline: str | None = None,
) -> None:
    if RICH_AVAILABLE and Panel is not None and Group is not None:
        console = Console(highlight=False, soft_wrap=True)
        blocks: list[object] = []
        header = Text()
        header.append(f"{CLI_THEME_WELCOME_GLYPH} {title}\n", style=f"bold {BRAND_LIGHT}")
        if detail:
            header.append(f"{detail}", style=BRAND_MUTED)
        if header.plain.strip():
            blocks.append(header)
        if blocks:
            blocks.append(Text(" "))
        blocks.append(Align.center(render_cli_banner_mark()))
        if tagline:
            blocks.append(Text(" "))
            blocks.append(Align.center(Text(tagline, style=BRAND_LIGHT)))
        for section in sections:
            if blocks:
                blocks.append(Text(" "))
            section_text = Text()
            section_text.append(f"{section.title}\n", style=f"bold {BRAND_ACCENT}")
            for line in section.lines:
                _append_command_highlight(section_text, line)
                section_text.append("\n")
            blocks.append(section_text)
        if next_commands:
            if blocks:
                blocks.append(Text(" "))
            command_text = Text()
            command_text.append("Next invocations\n", style=f"bold {BRAND_ACCENT}")
            for command in next_commands:
                command_text.append(_format_command_hint(command), style=f"bold {BRAND_ACCENT_STRONG}")
                command_text.append("\n")
            blocks.append(command_text)
        console.print(
            Panel(
                Group(*blocks) if blocks else Text(""),
                title=f"[bold {BRAND_ACCENT}] {CLI_THEME_TITLE_GLYPH} {title} [/bold {BRAND_ACCENT}]",
                subtitle=f"[bold {BRAND_LIGHT}]{CLI_THEME_SUBTITLE}[/bold {BRAND_LIGHT}]",
                border_style=BRAND_ACCENT,
                padding=(1, 2),
            )
        )
        return

    _print_heading(title, detail)
    for section in sections:
        if section.title:
            print(f"  {section.title}:")
        for line in section.lines:
            _print_bullet(line)
    _print_command_hints(*next_commands)


__all__ = ["CliCardSection", "_print_cli_card"]
