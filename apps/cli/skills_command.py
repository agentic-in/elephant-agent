"""Top-level skill management surface for the Elephant Agent launcher."""

from __future__ import annotations

from argparse import SUPPRESS, ArgumentParser, Namespace
from pathlib import Path

import typer

from packages.skills import SkillDefinition, skill_provenance_fields

from .cli_main_support import CliCardSection, _print_cli_card
from .runtime import CliRuntime
from .typer_support import run_typer_app


def _build_parser(
    *,
    default_state_dir: Path | None = None,
) -> ArgumentParser:
    parser = ArgumentParser(
        prog="elephant skills",
        description="Inspect, search, install, and toggle skill packages without entering wake.",
    )
    parser.add_argument("--state-dir", default=default_state_dir, type=Path, help=SUPPRESS)
    subparsers = parser.add_subparsers(dest="command")

    list_parser = subparsers.add_parser(
        "list",
        help="List built-in, installed, authored, and discovered local skill entries.",
    )
    list_parser.add_argument("--limit", type=int, default=24)

    active = subparsers.add_parser(
        "active",
        help="Show the currently enabled installed skills for the active profile.",
    )
    active.add_argument("--limit", type=int, default=24)

    search = subparsers.add_parser(
        "search",
        help="Search local shelves first, then configured external skill sources.",
    )
    search.add_argument("query", nargs="+")
    search.add_argument("--source", default=None)
    search.add_argument("--limit", type=int, default=12)

    view = subparsers.add_parser(
        "view",
        help="Inspect one local or external skill package by id or reference.",
    )
    view.add_argument("reference")

    enable = subparsers.add_parser(
        "enable",
        help="Enable one installed skill for the active profile.",
    )
    enable.add_argument("skill_id")

    disable = subparsers.add_parser(
        "disable",
        help="Disable one installed skill for the active profile.",
    )
    disable.add_argument("skill_id")

    install = subparsers.add_parser(
        "install",
        help="Install one skill package from a hub id, public reference, local path, or manifest path.",
    )
    install.add_argument("reference")

    return parser


def _runtime_from_args(args: Namespace) -> CliRuntime:
    return CliRuntime.create(
        state_dir=Path(args.state_dir).expanduser(),
    )


def _runtime(*, state_dir: Path) -> CliRuntime:
    return CliRuntime.create(
        state_dir=state_dir.expanduser(),
    )


def _skill_summary_lines(skill: SkillDefinition) -> tuple[str, ...]:
    lines = [
        f"skill_id · {skill.skill_id}",
        f"display_name · {skill.display_name}",
        f"enabled · {skill.enabled}",
        f"version · {skill.version}",
        f"summary · {skill.summary}",
        f"provenance · {skill.provenance or 'built-in'}",
    ]
    slash_command = str(skill.metadata.get("slash_command") or "").strip()
    if slash_command:
        lines.append(f"slash_command · /{slash_command}")
    for label, value in skill_provenance_fields(skill.metadata):
        lines.append(f"{label} · {value}")
    return tuple(lines)


def _instruction_lines(skill: SkillDefinition) -> tuple[str, ...]:
    text = skill.instruction_text.strip()
    if not text:
        return ("<empty>",)
    return tuple(line.rstrip() for line in text.splitlines())


def _print_skill_list(runtime: CliRuntime, *, limit: int) -> None:
    entries = runtime.list_skill_hub(limit=limit)
    lines = tuple(
        f"{_display_skill_reference(entry)} | {entry.display_name} | source={entry.source_id} | {entry.summary}"
        for entry in entries
    ) or ("<empty>",)
    _print_cli_card(
        "Elephant Agent skills",
        "Local skill shelves and bundled entries visible to the current operator profile.",
        sections=(
            CliCardSection("Visible catalog", lines),
            CliCardSection(
                "Next steps",
                (
                    "elephant skills active",
                    "elephant skills search <query>",
                    "elephant skills view <skill-id|reference>",
                    "elephant skills install <skill-id|reference|/path/to/skill>",
                ),
            ),
        ),
        next_commands=("elephant wake",),
    )


def _print_active_skills(runtime: CliRuntime, *, limit: int) -> None:
    skills = tuple(skill for skill in runtime.skill_catalog() if skill.enabled)
    lines = tuple(
        f"{skill.skill_id} | enabled={skill.enabled} | {skill.display_name} | {skill.summary}"
        for skill in skills[:limit]
    ) or ("<empty>",)
    _print_cli_card(
        "Elephant Agent skills",
        "Enabled installed skill packages for the active profile.",
        sections=(CliCardSection("Active skills", lines),),
        next_commands=("elephant skills list", "elephant wake"),
    )


def _print_search_results(runtime: CliRuntime, query: str, *, source: str | None, limit: int) -> None:
    local_entries = runtime.search_skill_hub(query, limit=limit)
    external_entries = runtime.search_skill_sources(query, source=source, limit=limit)
    sections = [
        CliCardSection(
            "Local shelves",
            tuple(
                f"{_display_skill_reference(entry)} | {entry.display_name} | source={entry.source_id} | {entry.summary}"
                for entry in local_entries
            )
            or ("<empty>",),
        ),
        CliCardSection(
            "External sources",
            tuple(
                f"{entry.reference} | {entry.display_name} | source={entry.source_id} | trust={entry.trust_level or '<unknown>'} | {entry.summary}"
                for entry in external_entries
            )
            or ("<empty>",),
        ),
    ]
    _print_cli_card(
        "Elephant Agent skills",
        f'Search results for "{query}".',
        sections=tuple(sections),
        next_commands=(
            "elephant skills view <skill-id|reference>",
            "elephant skills install <skill-id|reference>",
        ),
    )


def _print_skill_detail(runtime: CliRuntime, reference: str) -> None:
    skill = runtime.inspect_skill_source(reference)
    _print_cli_card(
        "Elephant Agent skills",
        f"Detail for {skill.display_name}.",
        sections=(
            CliCardSection("Metadata", _skill_summary_lines(skill)),
            CliCardSection("Instructions", _instruction_lines(skill)),
        ),
        next_commands=("elephant skills install <skill-id|reference>", "elephant wake"),
    )


def _print_skill_toggle(runtime: CliRuntime, *, skill_id: str, enabled: bool) -> None:
    updated = runtime.set_skill_enabled(skill_id, enabled)
    detail = "enabled" if enabled else "disabled"
    _print_cli_card(
        "Elephant Agent skills",
        f"{updated.display_name} is now {detail}.",
        sections=(CliCardSection("Updated skill", _skill_summary_lines(updated)),),
        next_commands=("elephant skills active", "elephant wake"),
    )


def _print_skill_install(runtime: CliRuntime, reference: str) -> None:
    record = runtime.install_skill_source(reference)
    skill_ids = ", ".join(record.skill_ids) if record.skill_ids else "<empty>"
    _print_cli_card(
        "Elephant Agent skills",
        "Installed one skill source into the active operator profile.",
        sections=(
            CliCardSection(
                "Install record",
                (
                    f"status · {record.status}",
                    f"source_path · {record.source_path}",
                    f"skill_ids · {skill_ids}",
                    f"detail · {record.detail}",
                ),
            ),
        ),
        next_commands=("elephant skills active", "elephant wake"),
    )


def _display_skill_reference(entry) -> str:
    if getattr(entry, "source_id", "") == "builtin":
        return str(getattr(entry, "skill_id", "")).strip() or str(getattr(entry, "reference", ""))
    return str(getattr(entry, "reference", "")).strip()


def build_typer_app(
    *,
    default_state_dir: Path | None = None,
) -> typer.Typer:
    app = typer.Typer(
        name="elephant skills",
        help="Inspect, search, install, and toggle skill packages without entering wake.",
        no_args_is_help=False,
        rich_markup_mode="rich",
        add_completion=False,
    )

    @app.callback(invoke_without_command=True)
    def main_callback(
        ctx: typer.Context,
        state_dir: Path = typer.Option(default_state_dir, "--state-dir", hidden=True),
    ) -> None:
        ctx.obj = {
            "state_dir": Path(state_dir).expanduser() if state_dir is not None else None,
        }
        if ctx.invoked_subcommand is None:
            runtime = _runtime(state_dir=ctx.obj["state_dir"])
            _print_skill_list(runtime, limit=24)
            raise typer.Exit(0)

    @app.command("list")
    def list_command(
        ctx: typer.Context,
        limit: int = typer.Option(24, "--limit", help="Maximum visible entries to show."),
    ) -> None:
        runtime = _runtime(state_dir=ctx.obj["state_dir"])
        _print_skill_list(runtime, limit=limit)
        raise typer.Exit(0)

    @app.command("active")
    def active_command(
        ctx: typer.Context,
        limit: int = typer.Option(24, "--limit", help="Maximum enabled skills to show."),
    ) -> None:
        runtime = _runtime(state_dir=ctx.obj["state_dir"])
        _print_active_skills(runtime, limit=limit)
        raise typer.Exit(0)

    @app.command("search")
    def search_command(
        ctx: typer.Context,
        query: list[str] = typer.Argument(..., help="One or more search terms to combine."),
        source: str | None = typer.Option(None, "--source", help="Restrict search to one external source."),
        limit: int = typer.Option(12, "--limit", help="Maximum results to show per source tier."),
    ) -> None:
        runtime = _runtime(state_dir=ctx.obj["state_dir"])
        _print_search_results(runtime, " ".join(query).strip(), source=source, limit=limit)
        raise typer.Exit(0)

    @app.command("view")
    def view_command(
        ctx: typer.Context,
        reference: str = typer.Argument(..., help="Skill id or source reference to inspect."),
    ) -> None:
        runtime = _runtime(state_dir=ctx.obj["state_dir"])
        _print_skill_detail(runtime, reference)
        raise typer.Exit(0)

    @app.command("enable")
    def enable_command(
        ctx: typer.Context,
        skill_id: str = typer.Argument(..., help="Installed skill id to enable."),
    ) -> None:
        runtime = _runtime(state_dir=ctx.obj["state_dir"])
        _print_skill_toggle(runtime, skill_id=skill_id, enabled=True)
        raise typer.Exit(0)

    @app.command("disable")
    def disable_command(
        ctx: typer.Context,
        skill_id: str = typer.Argument(..., help="Installed skill id to disable."),
    ) -> None:
        runtime = _runtime(state_dir=ctx.obj["state_dir"])
        _print_skill_toggle(runtime, skill_id=skill_id, enabled=False)
        raise typer.Exit(0)

    @app.command("install")
    def install_command(
        ctx: typer.Context,
        reference: str = typer.Argument(..., help="Hub id, public reference, local path, or manifest path."),
    ) -> None:
        runtime = _runtime(state_dir=ctx.obj["state_dir"])
        _print_skill_install(runtime, reference)
        raise typer.Exit(0)

    return app


def command_main(
    argv: list[str] | None = None,
    *,
    default_state_dir: Path | None = None,
) -> int:
    return run_typer_app(
        build_typer_app(
            default_state_dir=default_state_dir,
        ),
        argv,
        prog_name="elephant skills",
    )


__all__ = ["command_main", "build_typer_app"]
