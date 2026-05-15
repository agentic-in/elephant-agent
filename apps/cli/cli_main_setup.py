"""Interactive setup helpers for the CLI entrypoint."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
import random
import re
import select
import sys
import time
from collections.abc import Iterable
from pathlib import Path

from packages.state import DEFAULT_ELEPHANT_IDENTITY_TEXT, render_default_elephant_identity

from .runtime import CliRuntime
from .provider_flow import (
    ProviderSelectionState,
    provider_choices as _shared_provider_choices,
    provider_setup_defaults,
    run_provider_selection_wizard,
)
from .shell import (
    Align,
    BRAND_ACCENT,
    BRAND_ACCENT_STRONG,
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
    WIZARD_CANCEL,
    WizardChoice,
    _WizardBackSignal,
    _interactive_shell_supported,
    _wizard_choice_prompt,
    _wizard_dialogs_supported,
    _wizard_text_prompt,
)
from .shell_stack import Live

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
CLI_THEME_SUBTITLE = "Who you are, what matters, and what should stay close."

INIT_REFLECTION_LINES = (
    "Personal anchors first: name, language, style, rhythms.",
    "Then choose the elephant, model, and recall path.",
    "IM stays optional.",
)
INIT_SETUP_STEPS = (
    ("01  You", "Name, language, context, care notes."),
    ("02  Almost", "Pause after Personal Model anchors."),
    ("03  Elephant + Model", "Name, dialogue model, recall path."),
    ("04  Wake + IM", "Open first elephant; IM optional."),
)



from .cli_main_support import *  # noqa: F401,F403

def _default_personality_preset(runtime: CliRuntime, *, mode: str, current: str | None = None) -> str | None:
    if mode != "companion":
        return None
    if current:
        return current
    for preset in runtime.personality_presets():
        if preset.preset_id == "companion":
            return preset.preset_id
    return runtime.personality_presets()[0].preset_id

def _print_birth_wizard_intro() -> None:
    if not RICH_AVAILABLE or Table is None or Panel is None or Group is None:
        _print_heading("Elephant Agent Init", "Start from you, then choose the first elephant and model path.")
        for line in INIT_REFLECTION_LINES:
            _print_bullet(line)
        return
    console = Console(highlight=False, soft_wrap=True)
    questions = Text()
    questions.append("Stage 0: start from you\n", style=f"bold {BRAND_LIGHT}")
    questions.append(
        "Elephant Agent begins with a small Personal Model so the first reply sees the right person, path, and pace.\n\n",
        style=BRAND_MUTED,
    )
    for line in INIT_REFLECTION_LINES:
        questions.append(f"• {line}\n", style=BRAND_LIGHT)

    flow = Text()
    flow.append("What will happen\n", style=f"bold {BRAND_ACCENT}")
    for label, detail in INIT_SETUP_STEPS:
        flow.append(f"{label}\n", style=f"bold {BRAND_LIGHT}")
        flow.append(f"    {detail}\n", style=BRAND_MUTED)

    brand = Text(justify="center", no_wrap=True)
    brand.append("STAGE 0\n", style=f"bold {BRAND_ACCENT}")

    layout = Table.grid(expand=True)
    console_width = getattr(console.size, "width", 0)
    if console_width and console_width < 132:
        layout.add_column(ratio=1, min_width=48)
        layout.add_row(_center_brand_block(render_stage_zero_elephant_mark()))
        layout.add_row(_center_brand_block(Text("STAGE 0 · Elephant Agent Init", style=f"bold {BRAND_ACCENT}")))
        layout.add_row(Text(" "))
        layout.add_row(questions)
        layout.add_row(Text(" "))
        layout.add_row(flow)
    else:
        layout.add_column(ratio=5, min_width=28)
        layout.add_column(min_width=3)
        layout.add_column(ratio=17, min_width=66)
        layout.add_column(min_width=3)
        layout.add_column(ratio=8, min_width=34)
        logo_block = Table.grid(expand=True)
        logo_block.add_column()
        logo_block.add_row(_center_brand_block(brand))
        logo_block.add_row(_center_brand_block(render_stage_zero_elephant_mark()))
        layout.add_row(_center_brand_block(logo_block), Text(" "), questions, Text(" "), flow)
    console.print(
        _center_intro_window(Panel(
            layout,
            title=f"[bold {BRAND_ACCENT}]Elephant Agent Init · Stage 0 → first wake · v{_resolve_elephant_version()}[/bold {BRAND_ACCENT}]",
            border_style=BRAND_ACCENT,
            expand=False,
            padding=(1, 2),
        ))
    )


_INIT_WELCOME_VARIANTS = (
    {
        "title": "Elephant Agent",
        "language": "English",
        "glyph": "🐘",
        "slogan": "Elephants never forget.",
        "lines": (
            "Memory is the beginning.",
            "Elephant Agent grows a Personal Model so the right people, risks,",
            "rhythms, and decisions can guide what happens next.",
            "",
            "Warm memory · PM-first · Gentle curiosity",
        ),
        "enter": "Press Enter to create yours.",
    },
    {
        "title": "开始之前",
        "language": "中文",
        "glyph": "🐘",
        "slogan": "Elephants never forget.",
        "lines": (
            "记忆只是起点。",
            "Elephant Agent 从那些真正影响你的东西开始理解你：",
            "人、风险、节奏、决定，以及一路留下的经验。",
            "",
            "Warm memory · PM-first · Gentle curiosity",
        ),
        "enter": "按 Enter 创建属于你的 Elephant Agent。",
    },
    {
        "title": "Avant de commencer",
        "language": "Français",
        "glyph": "🐘",
        "slogan": "Elephants never forget.",
        "lines": (
            "La mémoire est le début.",
            "Elephant Agent fait grandir un Personal Model pour que les bonnes",
            "personnes, les risques, les rythmes et les décisions guident la suite.",
            "",
            "Warm memory · PM-first · Gentle curiosity",
        ),
        "enter": "Appuie sur Enter pour créer le tien.",
    },
    {
        "title": "시작하기 전에",
        "language": "한국어",
        "glyph": "🐘",
        "slogan": "Elephants never forget.",
        "lines": (
            "기억은 시작일 뿐입니다.",
            "Elephant Agent는 당신에게 진짜 영향을 주는 것들에서 시작해",
            "이해를 키웁니다: 사람, 위험, 리듬, 결정, 그리고 남은 경험.",
            "",
            "Warm memory · PM-first · Gentle curiosity",
        ),
        "enter": "Enter를 눌러 나만의 Elephant Agent를 만드세요.",
    },
    {
        "title": "Antes de empezar",
        "language": "Español",
        "glyph": "🐘",
        "slogan": "Elephants never forget.",
        "lines": (
            "La memoria es el comienzo.",
            "Elephant Agent hace crecer un Personal Model para que las personas,",
            "los riesgos, los ritmos y las decisiones guíen lo que viene.",
            "",
            "Warm memory · PM-first · Gentle curiosity",
        ),
        "enter": "Pulsa Enter para crear el tuyo.",
    },
)


def _init_welcome_variant(variant_index: int) -> tuple[str, str, str, str, tuple[str, ...], str]:
    variant = _INIT_WELCOME_VARIANTS[variant_index % len(_INIT_WELCOME_VARIANTS)]
    return (
        str(variant["title"]),
        str(variant["language"]),
        str(variant["glyph"]),
        str(variant["slogan"]),
        tuple(str(line) for line in variant["lines"]),
        str(variant["enter"]),
    )


def _init_welcome_plain_text(variant_index: int) -> str:
    _title, language, glyph, slogan, lines, enter = _init_welcome_variant(variant_index)
    return "\n".join((f"Elephant Agent · {language}", "", f"{slogan} {glyph}", "", *lines, "", enter))


def _init_welcome_elephant_mark():
    mark = render_stage_zero_elephant_mark()
    if Text is None:
        return mark
    plain = getattr(mark, "plain", "")
    rows = plain.splitlines()
    visible_cells = [
        index
        for row in rows
        for index, cell in enumerate(row)
        if cell != " "
    ]
    if not rows or not visible_cells:
        return mark
    visible_left = min(visible_cells)
    visible_right = max(visible_cells)
    centered_rows = [row.ljust(visible_right + 1)[visible_left : visible_right + 1] for row in rows]
    return Text("\n".join(centered_rows), style=BRAND_LIGHT, no_wrap=True)


def _init_welcome_frame(variant_index: int):
    _title, language, glyph, slogan, lines, enter = _init_welcome_variant(variant_index)
    if Table is None or Panel is None or Text is None:
        return _init_welcome_plain_text(variant_index)
    body = Table.grid(expand=True)
    body.add_column()
    body.add_row(_center_brand_block(_init_welcome_elephant_mark()))
    body.add_row(Text(" "))
    copy = Text(justify="center", no_wrap=True)
    copy.append("Elephant Agent · ", style=BRAND_MUTED)
    copy.append(language + "\n", style=f"bold {BRAND_LIGHT}")
    copy.append(slogan, style=f"bold {BRAND_LIGHT}")
    copy.append(f" {glyph}\n\n", style=f"bold {BRAND_ACCENT_STRONG}")
    for index, line in enumerate(lines):
        style = f"bold {BRAND_ACCENT_STRONG}" if index == 0 else BRAND_LIGHT
        if "Elephant Agent" not in line:
            copy.append(line + "\n", style=style)
            continue
        prefix, suffix = line.split("Elephant Agent", 1)
        copy.append(prefix, style=style)
        copy.append("Elephant Agent", style=f"bold {BRAND_LIGHT}")
        copy.append(suffix + "\n", style=style)
    indicator = " ".join("●" if index == variant_index % len(_INIT_WELCOME_VARIANTS) else "·" for index in range(len(_INIT_WELCOME_VARIANTS)))
    copy.append("\n" + indicator + "\n", style=BRAND_MUTED)
    copy.append(enter + "\n", style=f"bold {BRAND_LIGHT}")
    body.add_row(_center_brand_block(copy))
    return _center_intro_window(Panel(
        body,
        subtitle=f"[bold {BRAND_ACCENT}]Create yours[/bold {BRAND_ACCENT}]",
        subtitle_align="center",
        border_style=BRAND_DARK,
        expand=True,
        padding=(1, 3),
        width=92,
        height=28,
    ))


def _prompt_init_welcome_gate() -> bool:
    if not _interactive_shell_supported():
        return True
    if (
        not RICH_AVAILABLE
        or Live is None
        or Console is None
        or Table is None
        or Panel is None
        or Text is None
        or os.environ.get("ELEPHANT_NO_ANIMATION") == "1"
    ):
        _print_heading("Elephant Agent", _init_welcome_plain_text(0))
        try:
            input()
        except (KeyboardInterrupt, EOFError):
            return False
        return True
    console = Console(highlight=False, soft_wrap=True)
    frame_index = 0
    next_switch = time.monotonic() + 4.2
    with Live(
        _init_welcome_frame(frame_index),
        console=console,
        refresh_per_second=8,
        screen=True,
        transient=False,
    ) as live:
        while True:
            try:
                ready, _, _ = select.select([sys.stdin], [], [], 0.1)
            except (OSError, ValueError):
                ready = []
            if ready:
                try:
                    sys.stdin.readline()
                except (KeyboardInterrupt, EOFError):
                    return False
                return True
            if time.monotonic() >= next_switch:
                frame_index = (frame_index + 1) % len(_INIT_WELCOME_VARIANTS)
                live.update(_init_welcome_frame(frame_index))
                next_switch = time.monotonic() + 4.2


def _intro_console_size() -> tuple[int, int]:
    if Console is None:
        return (0, 0)
    try:
        size = Console(highlight=False, soft_wrap=True).size
    except Exception:
        return (0, 0)
    return (getattr(size, "width", 0), getattr(size, "height", 0))


def _center_intro_window(renderable):
    if Align is None:
        return renderable
    _, height = _intro_console_size()
    try:
        if height > 0:
            return Align(renderable, align="center", vertical="middle", height=max(22, height - 1))
        return Align.center(renderable, vertical="middle")
    except TypeError:
        return Align.center(renderable)


def _play_after_personal_transition(language: str = "en") -> None:
    return None


def _prompt_first_elephant_name(default_name: str, *, allow_back: bool = False) -> str | _WizardBackSignal:
    return _wizard_text_prompt(
        "Name Your First Elephant Agent",
        "This first Elephant Agent is yours. What name feels right?",
        default=default_name,
        allow_back=allow_back,
    )

def _run_interactive_elephant_wizard(
    runtime: CliRuntime,
    *,
    elephant_name: str | None,
) -> str | None:
    current_elephant_name = elephant_name or _suggest_elephant_name(runtime)
    answer = _wizard_text_prompt(
        "Name Another Elephant Agent",
        "What should this new Elephant Agent be called?",
        default=current_elephant_name,
        allow_back=True,
    )
    if answer is WIZARD_BACK:
        return None
    return str(answer).strip() or current_elephant_name

def _run_interactive_birth_wizard(
    runtime: CliRuntime,
    *,
    display_name: str,
    provider_state: ProviderSelectionState,
) -> BirthWizardState | None:
    state = BirthWizardState(
        display_name=display_name,
        provider_id=provider_state.provider_id,
        base_url=provider_state.base_url,
        model_id=provider_state.model_id,
        api_key=provider_state.api_key,
        embedding_provider="local",
        embedding_source="huggingface",
        embedding_base_url="",
        embedding_model="",
        embedding_dimensions=None,
        embedding_api_key=None,
        reasoning_effort=provider_state.reasoning_effort,
        context_window_mode=provider_state.context_window_mode,
        context_window_tokens=provider_state.context_window_tokens,
    )
    steps = ("display_name", "provider_setup")
    step_index = 0
    while step_index < len(steps):
        step = steps[step_index]
        if step == "display_name":
            answer = _prompt_first_elephant_name(state.display_name, allow_back=True)
            if answer is WIZARD_BACK:
                return None
            state.display_name = str(answer).strip() or state.display_name
            step_index += 1
            continue
        if step == "provider_setup":
            answer = run_provider_selection_wizard(
                runtime,
                initial_state=ProviderSelectionState(
                    provider_id=state.provider_id,
                    base_url=state.base_url,
                    api_key=state.api_key,
                    model_id=state.model_id,
                    reasoning_effort=state.reasoning_effort,
                    context_window_mode=state.context_window_mode,
                    context_window_tokens=state.context_window_tokens,
                ),
                allow_back=True,
            )
            if answer is WIZARD_BACK or answer is WIZARD_CANCEL:
                return None
            state.provider_id = answer.provider_id
            state.base_url = answer.base_url
            state.api_key = answer.api_key
            state.model_id = answer.model_id
            state.reasoning_effort = answer.reasoning_effort
            state.context_window_mode = answer.context_window_mode
            state.context_window_tokens = answer.context_window_tokens
            step_index += 1
            continue
    return state

def _print_birth_paused() -> None:
    _print_cli_card(
        "Elephant Agent birth paused",
        "No new identity or provider changes were written.",
        next_commands=("elephant init", "elephant status"),
    )

def _gateway_birth_lines(elephant_name: str) -> tuple[str, ...]:
    return (
        "wire IM · elephant gateway setup",
        "inspect readiness · elephant gateway doctor",
        "inspect skill packages · elephant skills",
        "launch operator dashboard · elephant dashboard --dry-run",
    )

def _prompt_im_onboarding(runtime: CliRuntime, *, elephant_name: str) -> None:
    from apps.gateway.__main__ import run_im_setup

    run_im_setup(
        default_state_dir=runtime.paths.state_dir,
        default_control_state_dir=runtime.paths.state_dir,
        prompt_title="💬 IM Setup",
        prompt_text="💬 Which IM should Elephant Agent wire before wake opens?",
        allow_skip=True,
    )

def _print_overview(runtime: CliRuntime) -> None:
    provider = dict(runtime.provider_summary())
    doctor = runtime.provider_doctor()
    herd = runtime.list_herd(limit=5)
    if RICH_AVAILABLE and Table is not None and Panel is not None and Group is not None:
        console = Console(highlight=False, soft_wrap=True)
        brand = Table.grid(expand=True)
        brand.add_column(no_wrap=True)
        headline = Text(no_wrap=True)
        headline.append("Your Elephant Agent is awake\n", style=f"bold {BRAND_LIGHT}")
        headline.append("Still steady — and now, still yours.", style=BRAND_MUTED)
        capability = Text("You · Threads · Herd · Skills · Providers", style=BRAND_MUTED)
        action_lines = Text()
        action_lines.append("Start\n", style=f"bold {BRAND_ACCENT}")
        action_lines.append(f"{_format_command_line('elephant wake', 'continue the active thread')}\n", style=BRAND_LIGHT)
        action_lines.append(f"{_format_command_line('elephant init', 'set name, provider, model, and recall path')}\n", style=BRAND_LIGHT)
        action_lines.append(f"{_format_command_line('elephant herd new <name>', 'create another named continuity thread')}\n", style=BRAND_LIGHT)
        action_lines.append(f"{_format_command_line('elephant herd', 'inspect named continuity threads')}\n", style=BRAND_LIGHT)
        action_lines.append(f"{_format_command_line('elephant dashboard', 'open the continuity console')}\n", style=BRAND_LIGHT)
        action_lines.append("\nSystem controls\n", style=f"bold {BRAND_ACCENT}")
        action_lines.append(f"{_format_command_line('elephant provider', 'manage models, keys, context, and embeddings')}\n", style=BRAND_LIGHT)
        action_lines.append(f"{_format_command_line('elephant skills', 'inspect, install, search, and toggle skills')}\n", style=BRAND_LIGHT)
        action_lines.append(f"{_format_command_line('elephant gateway', 'bind messenger surfaces')}\n", style=BRAND_LIGHT)
        action_lines.append(f"{_format_command_line('elephant status', 'check provider and recall readiness')}\n", style=BRAND_LIGHT)
        action_lines.append("\nCurrent install\n", style=f"bold {BRAND_ACCENT}")
        action_lines.append(f"readiness · {doctor['status']}\n", style=BRAND_MUTED if doctor["status"] != "ready" else BRAND_LIGHT)
        action_lines.append(f"provider · {provider['provider_id']}\n", style=BRAND_MUTED)
        if provider.get("model_id") or provider.get("default_model"):
            action_lines.append(f"model · {provider.get('model_id') or provider.get('default_model')}\n", style=BRAND_MUTED)
        if herd:
            action_lines.append("states · " + ", ".join(elephant.elephant_id for elephant in herd), style=BRAND_MUTED)
        else:
            action_lines.append("states · none yet", style=BRAND_MUTED)
        brand.add_row(_center_brand_block(headline))
        brand.add_row(Text(" "))
        brand.add_row(_center_brand_block(_render_cli_banner_mark()))
        brand.add_row(Text(" "))
        brand.add_row(_center_brand_block(capability))
        layout = Table.grid(expand=True)
        console_width = getattr(console.size, "width", 0)
        if console_width and console_width < 132:
            layout.add_column(ratio=1, min_width=48)
            compact_brand = Table.grid(expand=True)
            compact_brand.add_column(no_wrap=True)
            compact_brand.add_row(_center_brand_block(headline))
            compact_brand.add_row(Text(" "))
            compact_brand.add_row(_center_brand_block(capability))
            layout.add_row(compact_brand)
            layout.add_row(Text(" "))
            layout.add_row(action_lines)
        else:
            layout.add_column(ratio=11, min_width=46)
            layout.add_column(ratio=11, min_width=44)
            layout.add_row(brand, action_lines)
        console.print(
            Panel(
                layout,
                title=f"[bold {BRAND_ACCENT}]Elephant Agent v{_resolve_elephant_version()}[/bold {BRAND_ACCENT}]",
                subtitle=f"[bold {BRAND_LIGHT}]You stay at the center. Everything else grows around that.[/bold {BRAND_LIGHT}]",
                border_style=BRAND_ACCENT,
                padding=(1, 2),
            )
        )
        return

    _print_heading("Your Elephant Agent is awake", "Still steady — and now, still yours.")
    _print_bullet("You · Threads · Herd · Skills · Providers")
    _print_command_line("elephant wake", "continue the active thread")
    _print_command_line("elephant init", "set name, provider, model, and recall path")
    _print_command_line("elephant herd new <name>", "create another named continuity thread")
    _print_command_line("elephant herd", "inspect named continuity threads")
    _print_command_line("elephant dashboard", "open the continuity console")
    _print_command_line("elephant provider", "manage models, keys, context, and embeddings")
    _print_command_line("elephant skills", "inspect, install, search, and toggle skills")
    _print_command_line("elephant gateway", "bind messenger surfaces")
    _print_command_line("elephant status", "check provider and recall readiness")
    _print_field("readiness", doctor["status"])
    _print_field("provider", provider["provider_id"])
    if provider.get("model_id") or provider.get("default_model"):
        _print_field("model", provider.get("model_id") or provider.get("default_model"))
    _print_field("states", ", ".join(elephant.elephant_id for elephant in herd) if herd else "none yet")

def _center_brand_block(renderable):
    if Align is None:
        return renderable
    return Align.center(renderable)

def _print_setup_intro(runtime: CliRuntime, *, provider_id: str) -> None:
    guide = runtime.provider_setup_guide(provider_id)
    loaded = runtime.current_profile()
    _print_cli_card(
        "Elephant Agent init",
        "Open the first thread of an Elephant Agent that will stay with you.",
        sections=(
            CliCardSection(
                "Current setup",
                (
                    f"name · {loaded.state.display_name}",
                    f"provider · {guide.display_name}",
                    f"transport · {guide.transport_display_name}",
                ),
            ),
            CliCardSection(
                "Init will set",
                (
                    "who this Elephant Agent is learning with",
                    "which dialogue model answers the first Episode",
                    "whether semantic recall uses elephant-embed or an embedding provider",
                    "which elephant wake should open first",
                ),
            ),
        ),
    )

def _default_born_args() -> argparse.Namespace:
    return argparse.Namespace(
        provider_id=DEFAULT_PROVIDER_ID,
        display_name=None,
        elephant_identity_text=None,
        elephant_name=None,
        base_url=None,
        model_id=None,
        api_key=None,
        context_window_mode=None,
        context_window=None,
        preferred_name=None,
        age=None,
        birth_date=None,
        gender=None,
        occupation=None,
        city=None,
        mbti=None,
        hobbies=None,
        safety_boundaries=None,
        non_interactive=False,
    )

def _default_grow_args() -> argparse.Namespace:
    return argparse.Namespace(
        elephant_id=None,
        debug=False,
        message=None,
    )

def _ensure_elephant_ready(
    runtime: CliRuntime,
    *,
    elephant_name: str,
    display_name: str,
    profile_id: str,
) -> tuple[object, str]:
    existing = runtime.latest_session_for_elephant(elephant_name)
    if existing is not None:
        return existing, "existing"
    session = runtime.create_elephant(
        elephant_id=elephant_name,
        profile_id=profile_id,
        display_name=display_name,
        mode="companion",
    )
    return session, "created"

__all__ = [
    "DEFAULT_PROVIDER_ID",
    "DEFAULT_ELEPHANT_NAME_SUGGESTIONS",
    "CLI_THEME_TITLE_GLYPH",
    "CLI_THEME_BULLET",
    "CLI_THEME_WELCOME_GLYPH",
    "CLI_THEME_SUBTITLE",
    "_default_personality_preset",
    "_print_birth_wizard_intro",
    "_prompt_init_welcome_gate",
    "_play_after_personal_transition",
    "_prompt_first_elephant_name",
    "_run_interactive_elephant_wizard",
    "_run_interactive_birth_wizard",
    "_print_birth_paused",
    "_gateway_birth_lines",
    "_prompt_im_onboarding",
    "_print_overview",
    "_center_brand_block",
    "_print_setup_intro",
    "_default_born_args",
    "_default_grow_args",
    "_ensure_elephant_ready",
]
