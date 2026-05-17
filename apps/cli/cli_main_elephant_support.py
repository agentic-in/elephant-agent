"""Elephant and wake rendering helpers for the CLI entrypoint."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
import random
import re
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path

from packages.state import DEFAULT_ELEPHANT_IDENTITY_TEXT, render_default_elephant_identity

from .runtime import CliRuntime
from .turn_metrics import cache_hit_metric_line
from .provider_flow import (
    ProviderSelectionState,
    provider_choices as _shared_provider_choices,
    provider_setup_defaults,
    run_provider_selection_wizard,
)
from .shell import (
    Align,
    BRAND_ACCENT,
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
    render_elephant_mark,
)
from .wizard import (
    WIZARD_BACK,
    WizardChoice,
    _WizardBackSignal,
    _interactive_shell_supported,
    _wizard_choice_prompt,
    _wizard_dialogs_supported,
    _wizard_text_prompt,
)

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
CLI_THEME_WELCOME_GLYPH = "🤝"
CLI_THEME_SUBTITLE = "shaped from you · alive between sessions."



from .cli_main_support import *  # noqa: F401,F403


def _current_elephant_session(runtime: CliRuntime):
    current_state = runtime.current_elephant_state()
    if current_state is not None:
        session = runtime.latest_session_for_elephant(current_state.elephant_id)
        if session is not None:
            return session
    snapshot = runtime._load_snapshot()
    if not isinstance(snapshot, Mapping):
        return None
    session_payload = snapshot.get("session")
    if not isinstance(session_payload, Mapping):
        return None
    session_id = str(session_payload.get("episode_id") or "").strip()
    if not session_id:
        return None
    try:
        return runtime.inspect_session(session_id)
    except Exception:
        return None


def _select_elephant(runtime: CliRuntime, elephant_id: str):
    session = runtime.latest_session_for_elephant(elephant_id)
    if session is None:
        raise ValueError(f"unknown elephant: {elephant_id}")
    previous_session = _current_elephant_session(runtime)
    if previous_session is not None and runtime.elephant_id_for_session(previous_session) != elephant_id:
        try:
            runtime.schedule_learning_for_session(
                session_id=previous_session.episode_id,
                trigger="state_switch",
                summary=f"state switched to {elephant_id}",
                metadata={"source": "cli.herd.use"},
            )
        except Exception:
            pass
    elephant_state = runtime.ensure_elephant_state(session)
    loaded_profile = runtime._load_profile(session.personal_model_id)
    runtime._write_snapshot(
        profile=loaded_profile.state,
        session=session,
        work_items=(),
        recall_items=(),
        plan=None,
        execution=None,
        delivery=None,
        stages=(),
        event=None,
        elephant_identity_text=loaded_profile.elephant_identity_text,
        state_focus=None,
    )
    runtime.repository.switch_state(elephant_state.state_id)
    return session

def _print_doctor(runtime: CliRuntime, *, deep: bool = False) -> None:
    provider = runtime.provider_doctor(deep=deep)
    security = runtime.security_doctor()
    herd = runtime.list_herd(limit=5)
    active = provider["provider"]
    embedding = dict(runtime.embedding_provider_summary())
    status_lines = (
        f"provider_status · {provider['status']}",
        f"security_status · {security['status']}",
        f"active_provider_id · {active['provider_id']}",
        f"active_provider_source · {active['source']}",
        f"active_provider_model · {active.get('model_id') or active.get('default_model') or '<unset>'}",
        f"active_provider_embedding_bootstrap · {active.get('embedding_bootstrap_status') or '<unset>'}",
        f"active_provider_embedding_ready · {_embedding_bootstrap_ready_label(active.get('embedding_bootstrap_status'))}",
    )
    provider_checks = tuple(
        f"{check['check']} · {check['status']}{f' · {check['summary']}' if check.get('summary') else ''}"
        for check in provider["checks"]
    )
    security_checks = tuple(
        f"{check['check']} · {check['status']}{f' · {check['summary']}' if check.get('summary') else ''}"
        for check in security["checks"]
    )
    extra_lines = (
        (f"probe_summary · {provider['probe_summary']}",) if provider["probe_summary"] else ()
    )
    sections = [CliCardSection("Readiness", status_lines)]
    embedding_status_lines = _embedding_bootstrap_status_lines(embedding)
    if embedding_status_lines:
        sections.append(CliCardSection("Embedding bootstrap", embedding_status_lines))
    embedding_notice_lines = _embedding_bootstrap_notice_lines(embedding)
    if embedding_notice_lines:
        sections.append(CliCardSection("Background bootstrap", embedding_notice_lines))
    if provider_checks:
        sections.append(CliCardSection("Provider checks", provider_checks))
    if security_checks:
        sections.append(CliCardSection("Security checks", security_checks))
    if extra_lines:
        sections.append(CliCardSection("Probe", extra_lines))
    _print_cli_card(
        "Elephant Agent status",
        "Readiness before the wake surface opens.",
        sections=tuple(sections),
        next_commands=("elephant wake", "elephant herd new <name>", "elephant herd")
        if provider["status"] == "ready" and herd
        else ("elephant herd new <name>", "elephant wake", "elephant herd")
        if provider["status"] == "ready"
        else ("elephant init",),
    )

def _print_elephant_created(runtime: CliRuntime, session_id: str) -> None:
    session = runtime.inspect_session(session_id)
    elephant_id = runtime.elephant_id_for_session(session)
    elephant_state = runtime.ensure_elephant_state(session)
    ready_lines = [
        f"elephant_id · {elephant_id}",
        f"state_id · {elephant_state.state_id}",
        f"personal_model_id · {elephant_state.personal_model_id}",
        f"status · {session.status}",
    ]
    _print_cli_card(
        "Elephant Agent elephant",
        "A new elephant is ready.",
        sections=(
            CliCardSection(
                "Ready now",
                tuple(ready_lines),
            ),
        ),
        next_commands=("elephant wake", f"elephant wake --elephant-id {elephant_id}", "elephant herd"),
    )

def _print_elephant_paused() -> None:
    _print_cli_card(
        "Elephant Agent elephant paused",
        "No new elephant was created.",
        next_commands=("elephant herd new <name>", "elephant wake", "elephant herd"),
    )

def _print_herd(runtime: CliRuntime) -> None:
    herd = runtime.list_herd(limit=24)
    current_session = _current_elephant_session(runtime)
    current_elephant_id = runtime.elephant_id_for_session(current_session) if current_session is not None else None
    if not herd:
        _print_cli_card(
            "Elephant Agent herd",
            "Named Elephant Agent herd with their own durable threads.",
            sections=(CliCardSection("Current state", ("No herd yet.",)),),
            next_commands=("elephant herd new <name>",),
        )
        return
    elephant_lines = tuple(
        f"{elephant.elephant_id}{' · current' if elephant.elephant_id == current_elephant_id else ''} · latest route {elephant.latest_session_id[:8]} · {elephant.session_count} wake{'s' if elephant.session_count != 1 else ''} · {elephant.latest_status}"
        for elephant in herd
    )
    _print_cli_card(
        "Elephant Agent herd",
        "Named Elephant Agent herd with their own durable threads.",
        sections=(CliCardSection("Available herd", elephant_lines),),
        next_commands=(
            "elephant herd current",
            "elephant herd use <name>",
            "elephant wake",
            "elephant herd new <name>",
            "elephant herd delete <name>",
            "elephant herd delete --all",
        ),
    )

def _print_current_elephant(runtime: CliRuntime) -> None:
    session = _current_elephant_session(runtime)
    if session is None:
        _print_cli_card(
            "Current elephant",
            "No current elephant has been selected yet.",
            next_commands=("elephant herd", "elephant herd use <name>", "elephant wake"),
        )
        return
    elephant_id = runtime.elephant_id_for_session(session)
    elephant_state = runtime.ensure_elephant_state(session)
    _print_cli_card(
        "Current elephant",
        "Wake will return to this elephant unless you pass another elephant explicitly.",
        sections=(
            CliCardSection(
                "Selected now",
                (
                    f"elephant_id · {elephant_id}",
                    f"state_id · {elephant_state.state_id}",
                    f"status · {session.status}",
                    f"updated_at · {session.updated_at.isoformat()}",
                ),
            ),
        ),
        next_commands=(f"elephant wake --elephant-id {elephant_id}", "elephant wake", "elephant herd"),
    )


def _print_elephant_selected(runtime: CliRuntime, elephant_id: str) -> None:
    session = _current_elephant_session(runtime)
    if session is None:
        raise ValueError(f"unknown elephant: {elephant_id}")
    elephant_state = runtime.ensure_elephant_state(session)
    _print_cli_card(
        "Elephant selected",
        "Wake will open this elephant by default until you choose another one.",
        sections=(
            CliCardSection(
                "Selected now",
                (
                    f"elephant_id · {elephant_id}",
                    f"state_id · {elephant_state.state_id}",
                    f"status · {session.status}",
                    f"updated_at · {session.updated_at.isoformat()}",
                ),
            ),
        ),
        next_commands=("elephant wake", "elephant herd current", "elephant herd"),
    )

def _print_elephant_retired(elephant_id: str, deleted_sessions: int) -> None:
    _print_cli_card(
        "Elephant retired",
        "A named Elephant Agent elephant and its elephant have been cleared.",
        sections=(
            CliCardSection(
                "Retired now",
                (
                    f"elephant_id · {elephant_id}",
                    f"deleted_sessions · {deleted_sessions}",
                    "personal_model_facts · preserved",
                ),
            ),
        ),
        next_commands=("elephant herd", "elephant herd new <name>", "elephant wake"),
    )

def _print_elephant_retire_paused() -> None:
    _print_cli_card(
        "Elephant retire paused",
        "No elephant was cleared.",
        next_commands=("elephant herd", "elephant wake", "elephant herd new <name>"),
    )

def _print_all_herd_retired(deleted_elephants: int, deleted_sessions: int) -> None:
    _print_cli_card(
        "All herd retired",
        "Every named Elephant Agent elephant and elephant have been cleared.",
        sections=(
            CliCardSection(
                "Retired now",
                (
                    f"deleted_elephants · {deleted_elephants}",
                    f"deleted_sessions · {deleted_sessions}",
                    "personal_model_facts · preserved",
                ),
            ),
        ),
        next_commands=("elephant herd new <name>", "elephant init", "elephant status"),
    )

def _prompt_elephant_choice(
    runtime: CliRuntime,
    herd,
    *,
    state_focus: str = "enter",
    preferred_elephant_id: str | None = None,
) -> object:
    prompt = (
        "Multiple Elephant Agent herd are available. Pick one before entering wake."
        if state_focus == "enter"
        else "Multiple Elephant Agent herd are available. Pick one before clearing it."
    )
    default_elephant = next(
        (elephant.elephant_id for elephant in herd if elephant.elephant_id == preferred_elephant_id),
        herd[0].elephant_id,
    )
    if _wizard_dialogs_supported():
        choices = tuple(
            WizardChoice(
                value=elephant.elephant_id,
                label=(
                    f"{elephant.elephant_id} · {elephant.session_count} wake{'s' if elephant.session_count != 1 else ''} · "
                    f"{_display_name_from_elephant_name(elephant.elephant_id)}"
                ),
                detail=f"latest route {elephant.latest_session_id[:8]} · {elephant.latest_status}",
            )
            for elephant in herd
        )
        selected_id = _wizard_choice_prompt(
            "Choose elephant",
            prompt,
            choices,
            default=default_elephant,
            allow_back=True,
        )
        if selected_id is WIZARD_BACK:
            return WIZARD_BACK
        for elephant in herd:
            if elephant.elephant_id == selected_id:
                return elephant
    _print_cli_card(
        "Choose elephant",
        prompt,
        sections=(
            CliCardSection(
                "Available herd",
                tuple(
                    f"{index}. {elephant.elephant_id} · latest route {elephant.latest_session_id[:8]} · {elephant.session_count} wake{'s' if elephant.session_count != 1 else ''} · {elephant.latest_status} · {_display_name_from_elephant_name(elephant.elephant_id)}"
                    for index, elephant in enumerate(herd, start=1)
                ),
            ),
        ),
    )
    while True:
        answer = input("elephant: ").strip()
        if answer.isdigit():
            index = int(answer)
            if 1 <= index <= len(herd):
                return herd[index - 1]
        for elephant in herd:
            if elephant.elephant_id == answer:
                return elephant
        print("  enter an elephant number or elephant id from the list above")

def _open_growth_episode(
    runtime: CliRuntime,
    *,
    episode_id: str | None = None,
    elephant_id: str | None = None,
    prompt_for_multiple: bool | None = None,
) -> tuple[str, str]:
    def open_next(selected):
        return runtime.open_next_episode(
            selected.episode_id,
            reason="wake_boundary",
            summary=(getattr(selected, "exit_summary", "") or "").strip(),
        ).episode

    current = _current_elephant_session(runtime)
    if episode_id is not None:
        selected = runtime.inspect_session(episode_id)
        opened = open_next(selected)
        return opened.episode_id, "Opened elephant"
    if elephant_id is not None:
        selected = runtime.latest_session_for_elephant(elephant_id)
        if selected is None:
            raise ValueError(f"unknown elephant: {elephant_id}")
        opened = open_next(selected)
        return opened.episode_id, f"Opened elephant {elephant_id}"
    herd = runtime.list_herd(limit=16)
    if not herd:
        raise LookupError("no-herd")
    if len(herd) == 1:
        selected = runtime.inspect_session(herd[0].latest_session_id)
        opened = open_next(selected)
        return opened.episode_id, f"Opened elephant {herd[0].elephant_id}"
    interactive_prompt = _interactive_shell_supported() if prompt_for_multiple is None else prompt_for_multiple
    if interactive_prompt:
        selected = _prompt_elephant_choice(
            runtime,
            herd,
            preferred_elephant_id=runtime.elephant_id_for_session(current) if current is not None else None,
        )
        if selected is WIZARD_BACK:
            raise _WizardCancelledError("wake")
        selected_session = runtime.inspect_session(selected.latest_session_id)
        opened = open_next(selected_session)
        return opened.episode_id, f"Opened elephant {selected.elephant_id}"
    if current is not None:
        opened = open_next(current)
        return opened.episode_id, f"Opened elephant {runtime.elephant_id_for_session(current)}"
    raise ValueError("multiple herd are available; pass --elephant-id or enter wake from an interactive TTY")

def _print_elephant_blocked(runtime: CliRuntime) -> None:
    report = runtime.provider_doctor()
    provider = report["provider"]
    checks = tuple(
        f"{check['check']} · {check['status']}{f' · {check['summary']}' if check.get('summary') else ''}"
        for check in report["checks"]
    )
    sections = [
        CliCardSection(
            "Current readiness",
            (
                f"provider_status · {report['status']}",
                f"active_provider_id · {provider['provider_id']}",
                f"active_provider_source · {provider['source']}",
            ),
        )
    ]
    if checks:
        sections.append(CliCardSection("Provider checks", checks))
    _print_cli_card(
        "Elephant blocked",
        "Finish init before creating another Elephant Agent elephant.",
        sections=tuple(sections),
        next_commands=("elephant init", "elephant status"),
    )

def _print_grow_blocked(runtime: CliRuntime) -> None:
    report = runtime.provider_doctor()
    provider = report["provider"]
    checks = tuple(
        f"{check['check']} · {check['status']}{f' · {check['summary']}' if check.get('summary') else ''}"
        for check in report["checks"]
    )
    sections = [
        CliCardSection(
            "Current readiness",
            (
                f"provider_status · {report['status']}",
                f"active_provider_id · {provider['provider_id']}",
                f"active_provider_source · {provider['source']}",
            ),
        )
    ]
    if checks:
        sections.append(CliCardSection("Provider checks", checks))
    _print_cli_card(
        "Wake blocked",
        "Finish init and status checks before entering the wake surface.",
        sections=tuple(sections),
        next_commands=("elephant init", "elephant status"),
    )

def _provider_session_ready(report: dict[str, object]) -> bool:
    raw_checks = tuple(report.get("checks", ()))
    if not raw_checks:
        return str(report.get("status", "")).strip().lower() == "ready"
    checks = {
        str(check.get("check")): str(check.get("status"))
        for check in raw_checks
        if isinstance(check, dict)
    }
    return (
        checks.get("provider_profile") == "configured"
        and checks.get("credentials") in {"available", "not-required"}
    )

def _print_no_elephants() -> None:
    _print_cli_card(
        "No herd yet",
        "Create an Elephant Agent elephant before entering the wake surface.",
        next_commands=("elephant herd new <name>", "elephant status"),
    )

def _print_assistant_turn(runtime: CliRuntime, outcome, *, title: str = "Elephant Agent turn") -> None:
    provider = dict(runtime.provider_summary())
    lines = [
        f"state_id · {outcome.state.state_id}",
        f"personal_model_id · {outcome.personal_model.personal_model_id}",
        f"provider_id · {provider['provider_id']}",
        f"provider_model · {provider.get('model_id') or provider.get('default_model') or '<unset>'}",
        f"execution · {outcome.execution.summary}",
        f"current_context · {outcome.state.summary or '<unset>'}",
        f"steps_recorded · {len(outcome.steps)}",
        f"recall_hits · {len(outcome.recall_items)}",
    ]
    cache_metric = cache_hit_metric_line(outcome.execution)
    if cache_metric:
        lines.append(cache_metric.replace(":", " ·", 1))
    _print_cli_card(
        title,
        "One wake turn completed.",
        sections=(CliCardSection("Turn summary", tuple(lines)),),
    )


def _print_provider_turn_failed(
    runtime: CliRuntime,
    error: RuntimeError,
    *,
    session_id: str | None = None,
    title: str = "Provider turn failed",
) -> None:
    provider = dict(runtime.provider_summary())
    lines = [
        f"provider_id · {provider['provider_id']}",
        f"provider_model · {provider.get('model_id') or provider.get('default_model') or '<unset>'}",
        "elephant_preserved · durable elephant and Personal Model data kept",
        f"failure · {str(error).strip() or error.__class__.__name__}",
    ]
    if session_id:
        try:
            session = runtime.inspect_session(session_id)
            elephant_state = runtime.ensure_elephant_state(session)
            lines.insert(0, f"state_id · {elephant_state.state_id}")
            lines.insert(1, f"personal_model_id · {elephant_state.personal_model_id}")
        except Exception:
            lines.insert(0, f"route_id · {session_id}")
    _print_cli_card(
        title,
        "The provider failed before the Loop completed.",
        sections=(CliCardSection("Recovery state", tuple(lines)),),
        next_commands=("elephant provider status", "elephant status", "elephant wake --message \"...\""),
    )

__all__ = [
    "DEFAULT_PROVIDER_ID",
    "DEFAULT_ELEPHANT_NAME_SUGGESTIONS",
    "CLI_THEME_TITLE_GLYPH",
    "CLI_THEME_BULLET",
    "CLI_THEME_WELCOME_GLYPH",
    "CLI_THEME_SUBTITLE",
    "_print_doctor",
    "_print_elephant_created",
    "_print_elephant_paused",
    "_print_herd",
    "_print_current_elephant",
    "_print_elephant_selected",
    "_print_elephant_retired",
    "_print_elephant_retire_paused",
    "_print_all_herd_retired",
    "_prompt_elephant_choice",
    "_open_growth_episode",
    "_select_elephant",
    "_print_elephant_blocked",
    "_print_grow_blocked",
    "_provider_session_ready",
    "_print_no_elephants",
    "_print_assistant_turn",
    "_print_provider_turn_failed",
]
