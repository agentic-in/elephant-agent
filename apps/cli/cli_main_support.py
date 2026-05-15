"""Formatting, parser, and shared support for the CLI entrypoint."""

import argparse
from dataclasses import dataclass
import random
import re
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path

from packages.state import DEFAULT_ELEPHANT_IDENTITY_TEXT, render_default_elephant_identity

from .runtime import CliRuntime
from .provider_flow import (
    ProviderSelectionState,
    provider_choices as _shared_provider_choices,
    provider_setup_defaults,
    run_provider_selection_wizard,
)

_provider_choices = _shared_provider_choices
from .shell import (
    Align,
    BRAND_ACCENT,
    BRAND_DARK,
    BRAND_LIGHT,
    BRAND_MUTED,
    Console,
    Group,
    Panel,
    ProductizedShell,
    RICH_AVAILABLE,
    Table,
    Text,
    _resolve_elephant_version,
    render_stage_zero_elephant_mark,
)
from .wizard import (
    WIZARD_BACK,
    WizardChoice,
    _WizardBackSignal,
    _wizard_choice_prompt,
    _wizard_dialogs_supported,
    _wizard_text_prompt,
)

try:
    from .shell_ui import BRAND_ACCENT_STRONG
except Exception:
    BRAND_ACCENT_STRONG = BRAND_ACCENT

DEFAULT_PROVIDER_ID = "openai-compatible"
DEFAULT_ELEPHANT_NAME_SUGGESTIONS = (
    "Ada",
    "Asher",
    "Avery",
    "Caleb",
    "Chloe",
    "Eden",
    "Eli",
    "Eliza",
    "Felix",
    "Hazel",
    "Iris",
    "Jasper",
    "Julian",
    "Leah",
    "Lena",
    "Leo",
    "Maya",
    "Miles",
    "Milo",
    "Nina",
    "Nora",
    "Owen",
    "Ruby",
    "Rowan",
    "Simon",
    "Silas",
    "Theo",
    "Vera",
    "Zoe",
)
CLI_THEME_TITLE_GLYPH = "🐘"
CLI_THEME_BULLET = "•"
CLI_THEME_WELCOME_GLYPH = "🐘"
CLI_THEME_SUBTITLE = "Personal Model first, curious at your pace."
CLI_HELP_TAGLINE = "🐘 Model what matters · 👂 Ask gently · 🐾 Follow the path"
CLI_HELP_COMMANDS = (
    ("init", "Run first-time setup and persist identity, provider readiness, and the first elephant session."),
    ("wake", "Enter an existing Elephant Agent elephant through the branded TUI or run one provider-backed turn."),
    ("dashboard", "Launch the local operator dashboard when frontend assets are present."),
    ("herd", "Create, inspect, select, or retire existing Elephant Agent herd."),
    ("provider", "Configure or inspect the active provider, model, reasoning effort, and context window."),
    ("memory", "Inspect or retire Personal Model understanding without entering wake."),
    ("reflect", "Run, inspect, and manage background reflect agents (PM learning, dream, diary, audit)."),
    ("skills", "Inspect, search, install, and toggle skill packages without entering wake."),
    ("gateway", "Manage IM providers and accounts."),
    ("cron", "Manage the background cron scheduler."),
    ("status", "Review provider, model, and security readiness before opening the wake surface."),
)
CLI_COMMAND_HELP = {command: description for command, description in CLI_HELP_COMMANDS}
CLI_HELP_NEXT_COMMANDS = ("elephant init", "elephant wake", "elephant dashboard")
CLI_COMMAND_GLYPHS = (
    ("elephant init", "🐘"),
    ("elephant wake", "🐾"),
    ("elephant dashboard", "🗺️"),
    ("elephant herd new", "🐘"),
    ("elephant herd", "🐘"),
    ("elephant provider", "🧩"),
    ("elephant memory", "🐘"),
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

class _WizardCancelledError(Exception):
    __slots__ = ("surface",)

    def __init__(self, surface: str) -> None:
        super().__init__(surface)
        self.surface = surface

@dataclass(slots=True)
class BirthWizardState:
    display_name: str
    provider_id: str
    base_url: str
    model_id: str
    api_key: str | None
    embedding_provider: str
    embedding_source: str
    embedding_base_url: str
    embedding_model: str
    embedding_dimensions: int | None
    embedding_api_key: str | None
    reasoning_effort: str | None
    context_window_mode: str
    context_window_tokens: int | None
    # User's first language. Currently zh / en, intentionally stored as a
    # small code so later languages can be added without changing the shape.
    first_language: str = "en"
    # Curiosity tier — how often Elephant Agent is allowed to proactively ask open
    # questions about you (ADR-0004).  Default "medium" matches the PM
    # runtime default so an unset field behaves the same as the default.
    learning_intensity: str = "medium"
    preferred_name: str = ""
    age: str = ""
    birth_date: str = ""
    gender: str = ""
    occupation: str = ""
    city: str = ""
    mbti: str = ""
    hobbies: str = ""
    astrology: str = ""
    safety_boundaries: str = ""
    communication_preference: str = ""
    relationship_mode: str = ""
    starter_answers: tuple[tuple[str, str, str], ...] = ()

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="elephant",
        description="Elephant Agent CLI with explicit init, provider, status, herd, Personal Model recall, and wake entrypoints.",
    )
    parser.add_argument("--state-dir", required=True, type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--profile-dir", required=True, type=Path, help=argparse.SUPPRESS)

    subparsers = parser.add_subparsers(dest="command")

    def _add_init_parser(name: str, *, hidden: bool = False) -> None:
        init = subparsers.add_parser(
            name,
            help=argparse.SUPPRESS if hidden else "Run first-time setup and persist identity, provider readiness, and the first elephant session.",
        )
        init.add_argument("--provider-id", default=DEFAULT_PROVIDER_ID)
        init.add_argument("--display-name", default=None)
        init.add_argument("--elephant-text", default=None)
        init.add_argument("--elephant-name", default=None)
        init.add_argument("--base-url", default=None)
        init.add_argument("--model-id", default=None)
        init.add_argument("--api-key", default=None)
        init.add_argument("--secret-env-var", default=None)
        init.add_argument("--embedding-provider", choices=("local", "openai-compatible"), default="local")
        init.add_argument("--embedding-base-url", default=None)
        init.add_argument("--embedding-model", default=None)
        init.add_argument("--embedding-dimensions", default=None)
        init.add_argument("--embedding-api-key", default=None)
        init.add_argument("--embedding-secret-env-var", default=None)
        init.add_argument("--context-window-mode", default=None)
        init.add_argument("--context-window", default=None)
        init.add_argument("--first-language", choices=("en", "zh"), default="en")
        init.add_argument("--learning-intensity", choices=("low", "medium", "high"), default="medium")
        init.add_argument("--preferred-name", default=None)
        init.add_argument("--age", default=None, help=argparse.SUPPRESS)
        init.add_argument("--birth-date", default=None)
        init.add_argument("--gender", default=None)
        init.add_argument("--occupation", default=None)
        init.add_argument("--city", default=None)
        init.add_argument("--mbti", default=None)
        init.add_argument("--hobbies", default=None)
        init.add_argument("--safety-boundaries", default=None)
        init.add_argument("--non-interactive", action="store_true")

    def _add_status_parser(name: str, *, hidden: bool = False) -> None:
        status = subparsers.add_parser(
            name,
            help=argparse.SUPPRESS if hidden else "Review provider, model, and security readiness before opening the wake surface.",
        )
        status.add_argument(
            "--deep",
            action="store_true",
            help=argparse.SUPPRESS if hidden else "Run live provider catalog and runtime probe checks.",
        )

    def _add_provider_parser(name: str, *, hidden: bool = False) -> None:
        provider = subparsers.add_parser(
            name,
            help=argparse.SUPPRESS if hidden else "Configure or inspect the active provider, model, reasoning effort, and context window.",
        )
        provider.add_argument(
            "provider_command",
            nargs="?",
            default="configure",
            choices=("configure", "status", "providers", "models", "embeddings"),
            help="Choose whether to configure the active provider or inspect provider/model inventory.",
        )
        provider.add_argument("embedding_command", nargs="?", default=None, help=argparse.SUPPRESS)
        provider.add_argument("--provider-id", default=None)
        provider.add_argument("--base-url", default=None)
        provider.add_argument("--model-id", default=None)
        provider.add_argument("--model", dest="embedding_model", default=None)
        provider.add_argument("--dimensions", dest="embedding_dimensions", default=None)
        provider.add_argument("--api-key", default=None)
        provider.add_argument("--secret-env-var", default=None)
        provider.add_argument("--reasoning-effort", default=None)
        provider.add_argument("--context-window-mode", default=None)
        provider.add_argument("--context-window", default=None)
        provider.add_argument("--non-interactive", action="store_true")

    def _add_wake_parser(name: str, *, hidden: bool = False) -> None:
        wake = subparsers.add_parser(
            name,
            help=argparse.SUPPRESS if hidden else "Enter an existing Elephant Agent elephant through the branded TUI or run one provider-backed turn.",
        )
        wake.add_argument("--elephant-id", default=None, help="Open the latest session for a known elephant.")
        wake.add_argument("--debug", action="store_true", help="Show runtime diagnostics inside the wake surface.")
        wake.add_argument("--message", default=None, help="Run one wake turn and exit.")

    _add_init_parser("init")
    _add_status_parser("status")
    _add_provider_parser("provider")

    herd = subparsers.add_parser(
        "herd",
        help="Create, inspect, select, or delete existing Elephant Agent herd.",
    )
    herd_subparsers = herd.add_subparsers(dest="herd_command")
    elephant_new = herd_subparsers.add_parser(
        "new",
        help="Create a fresh elephant and optionally enter it immediately.",
    )
    elephant_new.add_argument("elephant_name", nargs="?", help="Name the new Elephant Agent elephant.")
    elephant_new.add_argument("--profile-id", default=None)
    elephant_new.add_argument("--display-name", default=None)
    elephant_new.add_argument("--debug", action="store_true", help="Show runtime diagnostics inside the wake surface.")
    elephant_new.add_argument("--message", default=None, help="Create the elephant, run one turn, and exit.")
    elephant_current = herd_subparsers.add_parser(
        "current",
        help="Show which elephant will open next when wake runs without an explicit elephant id.",
    )
    elephant_use = herd_subparsers.add_parser(
        "use",
        help="Select one named elephant as the current wake target.",
    )
    elephant_use.add_argument("elephant_id", nargs="?", help="Name the Elephant Agent elephant to select.")
    elephant_delete = herd_subparsers.add_parser(
        "delete",
        help="Delete one named elephant or clear every elephant.",
    )
    elephant_delete.add_argument("elephant_id", nargs="?", help="Name the Elephant Agent elephant to delete.")
    elephant_delete.add_argument("--all", action="store_true", dest="delete_all", help="Delete every elephant.")

    memory = subparsers.add_parser(
        "memory",
        help="Inspect or retire Personal Model understanding without entering wake.",
    )
    memory.add_argument("--elephant-id", default=None, help="Resolve Personal Model understanding through a named elephant.")
    memory_subparsers = memory.add_subparsers(dest="memory_command")
    memory_list = memory_subparsers.add_parser(
        "list",
        help="List Personal Model understanding for the current or named elephant.",
    )
    memory_list.add_argument("--elephant-id", default=None, help="Resolve Personal Model understanding through a named elephant.")
    memory_delete = memory_subparsers.add_parser(
        "delete",
        help="Retire one Personal Model entry by id.",
    )
    memory_delete.add_argument("memory_id", help="Name the Personal Model entry to retire.")
    memory_delete.add_argument("--elephant-id", default=None, help="Resolve Personal Model understanding through a named elephant.")
    memory_delete.add_argument("--reason", default=None, help="Record why this Personal Model entry is being retired.")

    _add_wake_parser("wake")

    return parser

def _print_heading(title: str, detail: str | None = None) -> None:
    print(f"{CLI_THEME_TITLE_GLYPH} {title}")
    if detail:
        print(f"  {detail}")

def _print_field(label: str, value: object) -> None:
    rendered = ""
    if value is not None:
        rendered = str(value)
    print(f"  {label}: {rendered}")

def _print_bullet(text: str) -> None:
    print(f"  {CLI_THEME_BULLET} {text}")

def _command_hint_glyph(command: str) -> str:
    normalized = " ".join(command.split()).strip()
    for prefix, glyph in CLI_COMMAND_GLYPHS:
        if normalized.startswith(prefix):
            return glyph
    return CLI_THEME_BULLET

def _format_command_hint(command: str) -> str:
    return f"{_command_hint_glyph(command)} {command}"

def _format_command_line(command: str, detail: str) -> str:
    return f"{_command_hint_glyph(command)} {command} · {detail}"


def _render_cli_banner_mark():
    return render_stage_zero_elephant_mark()


def _append_command_highlight(target: Text, line: str) -> None:
    marker = " · "
    command_part, separator, detail_part = line.partition(marker)
    leading_token = command_part.split(maxsplit=1)[0] if command_part else ""
    has_command_glyph = leading_token == CLI_THEME_BULLET or any(leading_token == glyph for _, glyph in CLI_COMMAND_GLYPHS)
    if not has_command_glyph:
        target.append(f"{CLI_THEME_BULLET} ", style=BRAND_MUTED)
    if separator:
        target.append(command_part, style=f"bold {BRAND_ACCENT_STRONG}")
        target.append(separator, style=BRAND_MUTED)
        target.append(detail_part, style=BRAND_LIGHT)
    else:
        target.append(line, style=BRAND_LIGHT)

def _print_command_line(command: str, detail: str) -> None:
    print(f"  {_format_command_line(command, detail)}")

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
        blocks.append(Align.center(_render_cli_banner_mark()))
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


def _print_cli_help(
    title: str,
    detail: str,
    *,
    commands: tuple[tuple[str, str], ...],
    options: tuple[tuple[str, str], ...] = (("--help", "Show this message and exit."),),
    next_commands: tuple[str, ...] = (),
    tagline: str | None = None,
) -> None:
    intro = (
        "Elephant Agent is personal-model-first AI — it grows from you, understands first, gets curious at your pace, and grows into your shape over time."
    )
    sections: list[CliCardSection] = [CliCardSection("Elephant Agent", (intro,))]
    if options:
        sections.append(
            CliCardSection(
                "Options",
                tuple(f"{flag} · {description}" for flag, description in options),
            )
        )
    if commands:
        sections.append(
            CliCardSection(
                "Commands",
                tuple(_format_command_line(command, description) for command, description in commands),
            )
        )
    _print_cli_card(
        title,
        detail,
        sections=tuple(sections),
        next_commands=next_commands,
        tagline=tagline,
    )


def _play_creating_transition(title: str, detail: str) -> None:
    return None

def _provider_secret_ready(runtime: CliRuntime, *, provider_id: str) -> bool:
    provider_summary = dict(runtime.provider_summary())
    if (
        provider_summary.get("provider_id") == provider_id
        and provider_summary.get("secret_status") in {"stored", "not-required"}
    ):
        return True
    try:
        discovered = runtime.discovered_provider(provider_id)
    except LookupError:
        return provider_id in {"", "preview"}
    return discovered.status in {"authenticated", "configured"}


def _embedding_bootstrap_ready_label(status: object) -> str:
    normalized = str(status or "").strip().lower()
    if normalized == "ready":
        return "ready"
    if normalized in {"pending", "downloading"}:
        return "orienting"
    if normalized == "failed":
        return "attention-needed"
    if normalized == "external":
        return "external"
    if normalized == "skipped":
        return "skipped"
    return normalized or "unknown"


def _embedding_bootstrap_status_lines(embedding: Mapping[str, object]) -> tuple[str, ...]:
    status = str(embedding.get("embedding_bootstrap_status") or "<unset>")
    summary = str(embedding.get("embedding_bootstrap_summary") or "").strip()
    lines = [
        f"embedding_bootstrap_status · {status}",
        f"embedding_bootstrap_ready · {_embedding_bootstrap_ready_label(status)}",
    ]
    if summary:
        lines.append(f"embedding_bootstrap_summary · {summary}")
    return tuple(lines)


def _embedding_bootstrap_notice_lines(embedding: Mapping[str, object]) -> tuple[str, ...]:
    status = str(embedding.get("embedding_bootstrap_status") or "").strip().lower()
    source = str(embedding.get("source") or "").strip().lower()
    if source != "local-default":
        return ()
    if status in {"pending", "downloading"}:
        return (
            "elephant-embed will finish preparing in the background.",
            "You can keep using Elephant Agent while sentence-transformers dependencies and model weights download.",
            "Run elephant status to watch when elephant-embed becomes ready.",
        )
    if status == "ready":
        return (
            "elephant-embed is ready for local semantic recall.",
            "elephant status will continue to show this path as ready.",
        )
    if status == "failed":
        return (
            "elephant-embed bootstrap needs attention before local semantic recall is fully ready.",
            "Run elephant status to inspect the latest bootstrap summary.",
        )
    return ()

def _print_brain_status(runtime: CliRuntime) -> None:
    provider = dict(runtime.provider_summary())
    embedding = dict(runtime.embedding_provider_summary())
    provider_id = str(provider.get("provider_id") or DEFAULT_PROVIDER_ID)
    try:
        discovered = runtime.discovered_provider(provider_id)
        discovery_status = discovered.status
        discovery_source = discovered.source
    except LookupError:
        discovery_status = str(provider.get("status") or "preview")
        discovery_source = str(provider.get("source") or "preview-fallback")
    embedding_status_lines = _embedding_bootstrap_status_lines(embedding)
    embedding_notice_lines = _embedding_bootstrap_notice_lines(embedding)
    sections = (
        CliCardSection(
            "Provider",
            (
                f"provider_id · {provider.get('provider_id', '<unset>')}",
                f"display_name · {provider.get('display_name', provider.get('provider_id', '<unset>'))}",
                f"base_url · {provider.get('base_url') or '<unset>'}",
                f"transport · {provider.get('transport_display_name', provider.get('transport_id', '<unset>'))}",
                f"secret_status · {provider.get('secret_status', '<unknown>')}",
                f"secret_source · {provider.get('secret_source', '<unknown>')}",
                f"discovery_status · {discovery_status}",
                f"discovery_source · {discovery_source}",
            ),
        ),
        CliCardSection(
            "Model selection",
            (
                f"model · {provider.get('model_id') or provider.get('default_model') or '<unset>'}",
                f"context_window_tokens · {provider.get('context_window_tokens') or '<unset>'}",
                f"context_window_mode · {provider.get('context_window_mode') or '<unset>'}",
                f"reasoning_effort · {provider.get('reasoning_effort') or '<unset>'}",
                f"reasoning_efforts · {', '.join(provider.get('reasoning_efforts', ())) or '<none>'}",
            ),
        ),
        CliCardSection(
            "Embedding selection",
            (
                f"source · {embedding.get('source') or '<unset>'}",
                f"provider_id · {embedding.get('provider_id') or '<unset>'}",
                f"model_id · {embedding.get('model_id') or '<unset>'}",
                f"dimensions · {embedding.get('dimensions') or '<unset>'}",
                f"base_url · {embedding.get('base_url') or '<unset>'}",
                f"secret_status · {embedding.get('secret_status') or '<unset>'}",
                *embedding_status_lines,
            ),
        ),
        *((CliCardSection("Background bootstrap", embedding_notice_lines),) if embedding_notice_lines else ()),
    )
    _print_cli_card(
        "Provider status",
        "The active provider and model posture Elephant Agent will use for the next turn.",
        sections=sections,
        next_commands=(
            "elephant provider",
            "elephant provider models",
            "elephant provider embeddings status",
        ),
    )

def _print_brain_provider_inventory(runtime: CliRuntime) -> None:
    lines = tuple(
        f"{state.provider_id} · {state.display_name} · {state.transport_display_name} · status={state.status} · source={state.source}"
        for state in runtime.provider_inventory()
        if state.runtime_enabled
    ) or ("<empty>",)
    _print_cli_card(
        "Provider catalog",
        "Providers Elephant Agent can configure right now.",
        sections=(CliCardSection("Catalog", lines),),
        next_commands=("elephant provider", "elephant provider status"),
    )

def _print_brain_models(runtime: CliRuntime, *, provider_id: str) -> None:
    try:
        models = runtime.discover_provider_models(provider_id=provider_id)
    except Exception as error:
        _print_cli_card(
            "Provider models",
            str(error),
            next_commands=("elephant provider", "elephant provider status"),
        )
        return
    lines = tuple(
        f"{model.model_id} · context={model.context_window_tokens or '<unknown>'} · output={model.max_output_tokens or '<unknown>'} · source={model.source}"
        for model in models
    ) or ("<empty>",)
    _print_cli_card(
        "Provider models",
        f"Models Elephant Agent can see for {provider_id}.",
        sections=(CliCardSection("Catalog", lines),),
        next_commands=("elephant provider", "elephant provider status"),
    )

def _print_embedding_provider_status(runtime: CliRuntime) -> None:
    embedding = dict(runtime.embedding_provider_summary())
    sections = (
        CliCardSection(
            "Embedding provider",
            (
                f"source · {embedding.get('source') or '<unset>'}",
                f"provider_id · {embedding.get('provider_id') or '<unset>'}",
                f"provider_kind · {embedding.get('provider_kind') or '<unset>'}",
                f"model_id · {embedding.get('model_id') or '<unset>'}",
                f"dimensions · {embedding.get('dimensions') or '<unset>'}",
                f"base_url · {embedding.get('base_url') or '<unset>'}",
                f"secret_status · {embedding.get('secret_status') or '<unset>'}",
                *_embedding_bootstrap_status_lines(embedding),
            ),
        ),
        *((CliCardSection("Background bootstrap", _embedding_bootstrap_notice_lines(embedding)),) if _embedding_bootstrap_notice_lines(embedding) else ()),
    )
    _print_cli_card(
        "Embedding provider status",
        "The active embedding posture backing semantic retrieval.",
        sections=sections,
        next_commands=(
            "elephant provider embeddings local",
            "elephant provider embeddings openai-compatible --base-url <url> --model <id> --dimensions <n>",
            "elephant provider status",
        ),
    )

def _slugify_elephant_name(value: str) -> str:
    collapsed = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return collapsed or "elephant"

def _display_name_from_elephant_name(value: str) -> str:
    collapsed = re.sub(r"[^a-zA-Z0-9]+", " ", value.strip()).strip()
    return collapsed.title() or "Elephant Agent"

def _suggest_elephant_name(runtime: CliRuntime | None = None) -> str:
    candidates = DEFAULT_ELEPHANT_NAME_SUGGESTIONS
    if runtime is None:
        return random.choice(candidates)
    available = tuple(
        name
        for name in candidates
        if runtime.latest_session_for_elephant(_slugify_elephant_name(name)) is None
    )
    return random.choice(available or candidates)


def _unique_elephant_name(runtime: CliRuntime, value: str) -> str:
    base_name = _slugify_elephant_name(value)
    candidate = base_name
    suffix = 2
    while runtime.latest_session_for_elephant(candidate) is not None:
        candidate = f"{base_name}-{suffix}"
        suffix += 1
    return candidate

__all__ = [
    "_provider_choices",
    "DEFAULT_PROVIDER_ID",
    "DEFAULT_ELEPHANT_NAME_SUGGESTIONS",
    "CLI_THEME_TITLE_GLYPH",
    "CLI_THEME_BULLET",
    "CLI_THEME_WELCOME_GLYPH",
    "CLI_THEME_SUBTITLE",
    "CLI_HELP_TAGLINE",
    "CLI_HELP_COMMANDS",
    "CLI_COMMAND_HELP",
    "CLI_HELP_NEXT_COMMANDS",
    "CLI_COMMAND_GLYPHS",
    "CliCardSection",
    "_WizardCancelledError",
    "BirthWizardState",
    "build_parser",
    "_print_heading",
    "_print_field",
    "_print_bullet",
    "_command_hint_glyph",
    "_format_command_hint",
    "_format_command_line",
    "_render_cli_banner_mark",
    "_append_command_highlight",
    "_print_command_line",
    "_print_command_hints",
    "_print_cli_card",
    "_print_cli_help",
    "_play_creating_transition",
    "_provider_secret_ready",
    "_print_brain_status",
    "_print_brain_provider_inventory",
    "_print_brain_models",
    "_print_embedding_provider_status",
    "_embedding_bootstrap_ready_label",
    "_embedding_bootstrap_status_lines",
    "_embedding_bootstrap_notice_lines",
    "_slugify_elephant_name",
    "_display_name_from_elephant_name",
    "_suggest_elephant_name",
    "_unique_elephant_name",
]
