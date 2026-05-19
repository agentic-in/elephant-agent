"""Gateway setup wizard helpers."""

from __future__ import annotations
import json
from pathlib import Path

from apps.cli.runtime import CliRuntime


try:
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings as PromptKeyBindings
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.layout import Layout
    from prompt_toolkit.shortcuts import input_dialog
    from prompt_toolkit.styles import Style as PromptStyle

    PROMPT_TOOLKIT_DIALOGS_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - optional wizard polish
    Application = None
    PromptKeyBindings = None
    HSplit = None
    Window = None
    FormattedTextControl = None
    Layout = None
    input_dialog = None
    PromptStyle = None
    PROMPT_TOOLKIT_DIALOGS_AVAILABLE = False


from .gateway_main_wizard_ui import *  # noqa: F401,F403


def _load_gateway_control_runtime(
    *,
    profile_dir: Path | None,
    state_dir: Path | None,
) -> CliRuntime | None:
    if profile_dir is None or state_dir is None:
        return None
    database_path = state_dir / "elephant.sqlite3"
    if not profile_dir.exists() or not state_dir.exists() or not database_path.exists():
        return None
    try:
        return CliRuntime.create(state_dir=state_dir)
    except (
        OSError,
        RuntimeError,
        ValueError,
        TypeError,
        KeyError,
        json.JSONDecodeError,
    ):
        return None


def _gateway_elephant_choices(
    runtime: CliRuntime,
    *,
    current_elephant_id: str,
) -> tuple[GatewayWizardChoice, ...]:
    choices: list[GatewayWizardChoice] = [
        GatewayWizardChoice(
            value=_GATEWAY_NO_DEFAULT_ELEPHANT,
            label="No default elephant",
            detail="Leave new IM conversations unpinned until you bind them explicitly.",
            emoji="➖",
        )
    ]
    known_elephant_ids: set[str] = set()
    for elephant in runtime.list_herd(limit=12):
        elephant_id = str(getattr(elephant, "elephant_id", "")).strip()
        if not elephant_id:
            continue
        known_elephant_ids.add(elephant_id)
        latest_session_id = str(getattr(elephant, "latest_session_id", "")).strip()
        latest_status = str(getattr(elephant, "latest_status", "")).strip() or "unknown"
        session_count = int(getattr(elephant, "session_count", 0) or 0)
        choices.append(
            GatewayWizardChoice(
                value=elephant_id,
                label=elephant_id,
                detail=(
                    f"latest {latest_session_id[:8] or '<none>'} · "
                    f"{session_count} session{'s' if session_count != 1 else ''} · {latest_status}"
                ),
                emoji="🧬",
            )
        )
    current = current_elephant_id.strip()
    if current and current not in known_elephant_ids:
        choices.append(
            GatewayWizardChoice(
                value=current,
                label=f"Keep configured elephant ({current})",
                detail="Reuse the existing elephant id even though it is not in the current local list.",
                emoji="🧭",
            )
        )
    choices.append(
        GatewayWizardChoice(
            value=_GATEWAY_MANUAL_EGG,
            label="Enter elephant id manually",
            detail="Type an elephant id when you want to route to an elephant that is not in the current list yet.",
            emoji="🆔",
        )
    )
    return tuple(choices)


def _gateway_session_choices(
    runtime: CliRuntime,
    *,
    elephant_id: str,
    current_session_id: str,
) -> tuple[GatewayWizardChoice, ...]:
    session_ids = runtime.session_ids_for_elephant(elephant_id)
    if not session_ids:
        return ()
    choices: list[GatewayWizardChoice] = [
        GatewayWizardChoice(
            value=_GATEWAY_FOLLOW_LATEST_SESSION,
            label="Follow latest session",
            detail="Route unpinned messages into the newest local session for this elephant.",
            emoji="🔄",
        )
    ]
    known_session_ids: set[str] = set()
    for index, session_id in enumerate(session_ids):
        known_session_ids.add(session_id)
        try:
            session = runtime.inspect_session(session_id)
        except KeyError:
            detail = "session metadata unavailable"
        else:
            updated_at = getattr(session.updated_at, "isoformat", lambda: str(session.updated_at))()
            detail = f"{session.status} · updated {updated_at}"
            if session.parent_episode_id:
                detail += f" · resumed from {session.parent_episode_id[:8]}"
            if index == 0:
                detail += " · latest"
        choices.append(
            GatewayWizardChoice(
                value=session_id,
                label=session_id,
                detail=detail,
                emoji="🧵",
            )
        )
    current = current_session_id.strip()
    if current and current not in known_session_ids:
        choices.append(
            GatewayWizardChoice(
                value=current,
                label=f"Keep configured session ({current})",
                detail="Reuse the existing session id even though it is not in the current local list.",
                emoji="🧭",
            )
        )
    return tuple(choices)


def _prompt_gateway_control_binding(
    *,
    runtime: CliRuntime | None,
    current_elephant_id: str,
    current_session_id: str,
    allow_back: bool = False,
) -> tuple[str, str] | _GatewayWizardBackSignal:
    resolved_elephant_id = current_elephant_id.strip()
    resolved_session_id = current_session_id.strip()
    if runtime is None:
        answer = _gateway_wizard_text_prompt(
            "Default Elephant",
            "Optional: which elephant should plain text fall back to before a thread is pinned? Leave blank to require an explicit bind.",
            default=resolved_elephant_id or None,
            allow_back=allow_back,
            preserve_default_on_empty=False,
        )
        if answer is GATEWAY_WIZARD_BACK:
            return GATEWAY_WIZARD_BACK
        elephant_id = str(answer).strip()
        if not elephant_id:
            return "", ""
        session_id = resolved_session_id if elephant_id == resolved_elephant_id else ""
        return elephant_id, session_id

    while True:
        elephant_choices = _gateway_elephant_choices(runtime, current_elephant_id=resolved_elephant_id)
        default_elephant_choice = resolved_elephant_id or _GATEWAY_NO_DEFAULT_ELEPHANT
        elephant_answer = _gateway_wizard_choice_prompt(
            "Default Elephant",
            "Choose which active elephant new IM conversations should use before the thread is pinned.",
            elephant_choices,
            default=default_elephant_choice,
            allow_back=allow_back,
        )
        if elephant_answer is GATEWAY_WIZARD_BACK:
            return GATEWAY_WIZARD_BACK
        if elephant_answer == _GATEWAY_NO_DEFAULT_ELEPHANT:
            return "", ""
        if elephant_answer == _GATEWAY_MANUAL_EGG:
            manual = _gateway_wizard_text_prompt(
                "Default Elephant",
                "Type the elephant id to use for new IM conversations before the thread is pinned.",
                default=resolved_elephant_id or None,
                allow_back=allow_back,
                preserve_default_on_empty=False,
            )
            if manual is GATEWAY_WIZARD_BACK:
                continue
            elephant_id = str(manual).strip()
            if not elephant_id:
                return "", ""
        else:
            elephant_id = str(elephant_answer).strip()
        current_elephant_session_id = resolved_session_id if elephant_id == resolved_elephant_id else ""
        known_session_ids = tuple(runtime.session_ids_for_elephant(elephant_id))
        if not known_session_ids:
            return elephant_id, ""
        if len(known_session_ids) == 1:
            only_session_id = known_session_ids[0].strip()
            if not current_elephant_session_id or current_elephant_session_id == only_session_id:
                return elephant_id, only_session_id
        session_choices = _gateway_session_choices(
            runtime,
            elephant_id=elephant_id,
            current_session_id=current_elephant_session_id,
        )
        if not session_choices:
            return elephant_id, ""
        default_session_choice = (
            resolved_session_id
            if elephant_id == resolved_elephant_id and resolved_session_id
            else _GATEWAY_FOLLOW_LATEST_SESSION
        )
        session_answer = _gateway_wizard_choice_prompt(
            "Default Session",
            f"Optional: pick a known local session for elephant `{elephant_id}`, or follow its latest session automatically.",
            session_choices,
            default=default_session_choice,
            allow_back=allow_back,
        )
        if session_answer is GATEWAY_WIZARD_BACK:
            continue
        if session_answer == _GATEWAY_FOLLOW_LATEST_SESSION:
            return elephant_id, ""
        return elephant_id, str(session_answer).strip()


__all__ = [
    "_load_gateway_control_runtime",
    "_gateway_elephant_choices",
    "_gateway_session_choices",
    "_prompt_gateway_control_binding",
]
