from __future__ import annotations

import asyncio
from dataclasses import dataclass
import getpass
import os
import sys
from types import MethodType

from .shell_ui import BRAND_ACCENT, BRAND_ACCENT_STRONG, BRAND_LIGHT, BRAND_MUTED

try:
    from prompt_toolkit.application.current import get_app
    from prompt_toolkit.filters import has_focus
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings as PromptKeyBindings
    from prompt_toolkit.key_binding.bindings.focus import focus_next, focus_previous
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.layout import Layout
    from prompt_toolkit.layout.dimension import Dimension as PromptDimension
    from prompt_toolkit.shortcuts import input_dialog
    from prompt_toolkit.styles import Style as PromptStyle
    from prompt_toolkit.widgets import Button, CheckboxList, Dialog, Label, RadioList, TextArea

    PROMPT_TOOLKIT_DIALOGS_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - optional wizard polish
    get_app = None
    has_focus = None
    Application = None
    PromptKeyBindings = None
    focus_next = None
    focus_previous = None
    HSplit = None
    Window = None
    FormattedTextControl = None
    Layout = None
    PromptDimension = None
    input_dialog = None
    PromptStyle = None
    Button = None
    CheckboxList = None
    Dialog = None
    Label = None
    RadioList = None
    TextArea = None
    PROMPT_TOOLKIT_DIALOGS_AVAILABLE = False

WIZARD_MAX_VISIBLE_CHOICES = 9


@dataclass(frozen=True, slots=True)
class WizardChoice:
    value: str
    label: str
    detail: str
    emoji: str = ""
    detail_style: str = "detail"
    selected_detail_style: str = "selected-detail"


class _WizardBackSignal:
    __slots__ = ()


class _WizardCancelSignal:
    __slots__ = ()


WIZARD_BACK = _WizardBackSignal()
WIZARD_CANCEL = _WizardCancelSignal()


def _interactive_shell_supported() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _wizard_dialogs_supported() -> bool:
    return (
        _interactive_shell_supported()
        and PROMPT_TOOLKIT_DIALOGS_AVAILABLE
        and os.environ.get("ELEPHANT_NO_WIZARD_DIALOGS") != "1"
    )


def _wizard_style():
    if PromptStyle is None:
        return None
    return PromptStyle.from_dict(
        {
            "dialog": f"bg:#141922 {BRAND_LIGHT}",
            "dialog frame.label": f"bg:#141922 {BRAND_ACCENT} bold",
            "dialog.body": f"bg:#141922 {BRAND_LIGHT}",
            "dialog.body text-area": f"bg:#1a202b {BRAND_LIGHT}",
            "dialog.body radio": f"{BRAND_LIGHT}",
            "dialog.body radio-selected": f"{BRAND_ACCENT_STRONG} bold",
            "dialog.body button": f"bg:#1a202b {BRAND_LIGHT}",
            "dialog.body button.focused": f"bg:{BRAND_ACCENT_STRONG} #141922 bold",
            "dialog shadow": "bg:#0f1218",
            "title": f"{BRAND_ACCENT} bold",
            "prompt": f"{BRAND_LIGHT}",
            "item": f"{BRAND_LIGHT}",
            "selected": f"{BRAND_ACCENT_STRONG} bold",
            "detail": f"{BRAND_MUTED}",
            "selected-detail": f"{BRAND_LIGHT}",
            "accent-detail": f"{BRAND_ACCENT}",
            "accent-selected-detail": f"{BRAND_ACCENT}",
            "role-primary": f"{BRAND_ACCENT_STRONG} bold",
            "role-primary-detail": f"{BRAND_LIGHT}",
            "role-secondary": "fg:#7ac8ff bold",
            "role-secondary-detail": f"{BRAND_LIGHT}",
            "hint": f"{BRAND_MUTED}",
            "validation": f"{BRAND_ACCENT_STRONG} bold",
        }
    )


def _wizard_asyncio_loop_running() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def _wizard_run_dialog(application):
    if _wizard_asyncio_loop_running():
        try:
            return application.run(in_thread=True)
        except TypeError:
            return application.run()
    return application.run()


def _guard_radio_list_selection_bounds(radio_list: object) -> object:
    original_handle_enter = getattr(radio_list, "_handle_enter", None)
    values = getattr(radio_list, "values", None)
    if not callable(original_handle_enter) or values is None:
        return radio_list

    def _safe_handle_enter(self) -> None:
        current_values = getattr(self, "values", ())
        if not current_values:
            return
        selected_index = getattr(self, "_selected_index", 0)
        try:
            selected_index = int(selected_index)
        except (TypeError, ValueError):
            selected_index = 0
        if selected_index < 0:
            selected_index = 0
        elif selected_index >= len(current_values):
            selected_index = len(current_values) - 1
        self._selected_index = selected_index
        original_handle_enter()

    setattr(radio_list, "_handle_enter", MethodType(_safe_handle_enter, radio_list))
    return radio_list


def _wizard_choice_menu(
    title: str,
    prompt: str,
    choices: tuple[WizardChoice, ...],
    *,
    default: str,
    allow_back: bool = False,
) -> str | _WizardBackSignal:
    if not (
        PROMPT_TOOLKIT_DIALOGS_AVAILABLE
        and Application is not None
        and PromptKeyBindings is not None
        and get_app is not None
        and has_focus is not None
        and focus_next is not None
        and focus_previous is not None
        and HSplit is not None
        and Layout is not None
        and Button is not None
        and Dialog is not None
        and Label is not None
        and RadioList is not None
    ):
        return default
    default_value = next((choice.value for choice in choices if choice.value == default), choices[0].value)
    values = tuple(
        (
            choice.value,
            [
                ("class:item", _wizard_choice_label(choice)),
                (f"class:{choice.detail_style}", f" — {choice.detail}"),
            ],
        )
        for choice in choices
    )
    radio_list = RadioList(
        values=values,
        default=default_value,
        select_on_focus=True,
        show_scrollbar=len(choices) > WIZARD_MAX_VISIBLE_CHOICES,
    )
    _guard_radio_list_selection_bounds(radio_list)
    hint = "Enter continues · Back goes back · Esc cancels · ↑/↓ or j/k moves" if allow_back else "Enter continues · Esc cancels · ↑/↓ or j/k moves"

    def _accept() -> None:
        get_app().exit(result=radio_list.current_value)

    def _back() -> None:
        get_app().exit(result=WIZARD_BACK)

    def _cancel() -> None:
        get_app().exit(result=WIZARD_CANCEL)

    continue_button = Button(text="Continue", handler=_accept)
    cancel_button = Button(text="Back", handler=_back)
    dialog = Dialog(
        title=title,
        body=HSplit(
            [
                Label(text=prompt, dont_extend_height=True),
                radio_list,
                Label(text=hint, dont_extend_height=True),
            ],
            padding=1,
        ),
        buttons=[continue_button, cancel_button],
        with_background=True,
    )
    bindings = PromptKeyBindings()

    @bindings.add("tab")
    def _focus_next_binding(event) -> None:
        focus_next(event)

    @bindings.add("s-tab")
    def _focus_previous_binding(event) -> None:
        focus_previous(event)

    @bindings.add("enter", filter=has_focus(radio_list), eager=True)
    def _accept_binding(_event) -> None:
        _accept()

    @bindings.add("escape")
    def _cancel_binding(_event) -> None:
        _cancel()

    application = Application(
        layout=Layout(dialog, focused_element=radio_list),
        key_bindings=bindings,
        style=_wizard_style(),
        full_screen=True,
        mouse_support=True,
    )
    answer = _wizard_run_dialog(application)
    if answer is WIZARD_BACK or answer is WIZARD_CANCEL:
        return answer
    return str(answer or radio_list.current_value or default_value)


def _wizard_dual_choice_menu(
    title: str,
    prompt: str,
    choices: tuple[WizardChoice, ...],
    *,
    first_title: str,
    second_title: str,
    default_first: str,
    default_second: str,
    allow_back: bool = False,
) -> tuple[str, str] | _WizardBackSignal:
    if not (
        PROMPT_TOOLKIT_DIALOGS_AVAILABLE
        and Application is not None
        and PromptKeyBindings is not None
        and get_app is not None
        and has_focus is not None
        and focus_next is not None
        and focus_previous is not None
        and HSplit is not None
        and Window is not None
        and FormattedTextControl is not None
        and Layout is not None
        and PromptDimension is not None
        and Button is not None
        and Dialog is not None
        and Label is not None
        and RadioList is not None
    ):
        return default_first, default_second
    values_by_id = {choice.value: choice for choice in choices}
    fallback = choices[0].value
    selected = {
        "first": default_first if default_first in values_by_id else fallback,
        "second": default_second if default_second in values_by_id else default_first if default_first in values_by_id else fallback,
    }
    active_role = {"name": "first"}
    selection_history: list[str] = [role for role in ("first", "second") if selected[role]]
    validation_state = {"message": ""}

    values = tuple(
        (
            choice.value,
            [
                ("class:item", _wizard_choice_label(choice)),
                (f"class:{choice.detail_style}", f" — {choice.detail}"),
            ],
        )
        for choice in choices
    )
    radio_list = RadioList(
        values=values,
        default=selected["first"],
        select_on_focus=True,
        show_scrollbar=len(choices) > WIZARD_MAX_VISIBLE_CHOICES,
    )
    _guard_radio_list_selection_bounds(radio_list)

    def _complete() -> bool:
        return bool(selected["first"]) and bool(selected["second"])

    def _role_fragments():
        first_choice = values_by_id.get(selected["first"])
        second_choice = values_by_id.get(selected["second"])
        first_suffix = " · next" if active_role["name"] == "first" else ""
        second_suffix = " · next" if active_role["name"] == "second" else ""
        return [
            ("class:role-primary", f"* {first_title}"),
            ("class:role-primary-detail", f" · {(first_choice.label if first_choice is not None else '<unset>')}{first_suffix}\n"),
            ("class:role-secondary", f"* {second_title}"),
            ("class:role-secondary-detail", f" · {(second_choice.label if second_choice is not None else '<unset>')}{second_suffix}"),
        ]

    def _validation_fragments():
        message = validation_state["message"]
        if not message:
            return []
        return [("class:validation", message)]

    def _assign(role_key: str) -> None:
        selected[role_key] = str(radio_list.current_value or fallback)
        if role_key in selection_history:
            selection_history.remove(role_key)
        selection_history.append(role_key)
        active_role["name"] = "second" if role_key == "first" else "first"
        validation_state["message"] = ""
        get_app().invalidate()

    def _undo_last_assignment() -> None:
        if not selection_history:
            return
        role_key = selection_history.pop()
        selected[role_key] = ""
        active_role["name"] = role_key
        validation_state["message"] = ""
        get_app().invalidate()

    def _accept() -> None:
        if not _complete():
            validation_state["message"] = "Choose both models before continuing."
            get_app().invalidate()
            return
        get_app().exit(result=(selected["first"], selected["second"]))

    def _cancel() -> None:
        get_app().exit(result=WIZARD_BACK)

    hint = "Space selects · Delete undoes · Enter continues once both are chosen"
    continue_button = Button(text="Continue", handler=_accept)
    cancel_button = Button(text="Back", handler=_cancel)
    dialog = Dialog(
        title=title,
        body=HSplit(
            [
                Label(text=prompt, dont_extend_height=True),
                Window(
                    FormattedTextControl(_role_fragments),
                    dont_extend_height=True,
                    height=PromptDimension(min=2, preferred=2),
                ),
                radio_list,
                Window(
                    FormattedTextControl(_validation_fragments),
                    dont_extend_height=True,
                    height=PromptDimension(min=0, preferred=1),
                ),
                Label(text=hint, dont_extend_height=True),
            ],
            padding=1,
        ),
        buttons=[continue_button, cancel_button],
        with_background=True,
    )
    bindings = PromptKeyBindings()

    @bindings.add("tab")
    def _focus_next_binding(event) -> None:
        focus_next(event)

    @bindings.add("s-tab")
    def _focus_previous_binding(event) -> None:
        focus_previous(event)

    @bindings.add("enter", filter=has_focus(radio_list), eager=True)
    def _assign_binding(_event) -> None:
        if _complete():
            _accept()
            return
        _assign(active_role["name"])

    @bindings.add("space", eager=True)
    def _assign_space_binding(event) -> None:
        if event.app.layout.has_focus(radio_list):
            if _complete():
                _accept()
                return
            _assign(active_role["name"])
            return
        if _complete():
            _accept()

    @bindings.add("backspace", eager=True)
    def _undo_binding(_event) -> None:
        _undo_last_assignment()

    @bindings.add("delete", eager=True)
    def _delete_binding(_event) -> None:
        _undo_last_assignment()

    @bindings.add("escape")
    def _cancel_binding(_event) -> None:
        _cancel()

    application = Application(
        layout=Layout(dialog, focused_element=radio_list),
        key_bindings=bindings,
        style=_wizard_style(),
        full_screen=True,
        mouse_support=True,
    )
    answer = _wizard_run_dialog(application)
    if answer is WIZARD_BACK:
        return WIZARD_BACK
    if isinstance(answer, tuple) and len(answer) == 2:
        return str(answer[0]), str(answer[1])
    return selected["first"], selected["second"]


def _wizard_multi_choice_menu(
    title: str,
    prompt: str,
    choices: tuple[WizardChoice, ...],
    *,
    default_values: tuple[str, ...] = (),
    allow_back: bool = False,
) -> tuple[str, ...] | _WizardBackSignal:
    del allow_back
    if not PROMPT_TOOLKIT_DIALOGS_AVAILABLE or CheckboxList is None:
        return default_values
    checkbox = CheckboxList(
        values=tuple((choice.value, _wizard_choice_label(choice)) for choice in choices),
        default_values=default_values,
    )

    def _accept() -> None:
        selected = tuple(str(value) for value in checkbox.current_values)
        if "skip" in selected and len(selected) > 1:
            selected = tuple(value for value in selected if value != "skip")
        get_app().exit(result=selected)

    def _back() -> None:
        get_app().exit(result=WIZARD_BACK)

    def _cancel() -> None:
        get_app().exit(result=WIZARD_CANCEL)

    dialog = Dialog(
        title=title,
        body=HSplit(
            [Label(text=prompt, dont_extend_height=True), checkbox, Label(text="Space toggles · Enter continues · Back goes back · Esc cancels", dont_extend_height=True)],
            padding=1,
        ),
        buttons=[Button(text="Continue", handler=_accept), Button(text="Back", handler=_back)],
        with_background=True,
    )
    bindings = PromptKeyBindings()

    @bindings.add("enter", filter=has_focus(checkbox), eager=True)
    def _accept_binding(_event) -> None:
        _accept()

    @bindings.add("escape")
    def _cancel_binding(_event) -> None:
        _cancel()

    answer = _wizard_run_dialog(Application(
        layout=Layout(dialog, focused_element=checkbox),
        key_bindings=bindings,
        style=_wizard_style(),
        full_screen=True,
        mouse_support=True,
    ))
    if answer is WIZARD_BACK or answer is WIZARD_CANCEL:
        return answer
    return tuple(str(value) for value in (answer or ()))


def _wizard_multi_choice_prompt(
    title: str,
    prompt: str,
    choices: tuple[WizardChoice, ...],
    *,
    default_values: tuple[str, ...] = (),
    allow_back: bool = False,
) -> tuple[str, ...] | _WizardBackSignal:
    if not choices:
        return default_values
    valid_defaults = tuple(value for value in default_values if any(choice.value == value for choice in choices))
    if _wizard_dialogs_supported():
        return _wizard_multi_choice_menu(
            title,
            prompt,
            choices,
            default_values=valid_defaults,
            allow_back=allow_back,
        )
    print(prompt)
    for index, choice in enumerate(choices, start=1):
        marker = "*" if choice.value in valid_defaults else " "
        print(f"  {marker} {index}. {_wizard_choice_label(choice)} :: {choice.detail}")
    print("  Enter numbers separated by spaces. Leave empty to keep defaults or skip.")
    while True:
        tokens = input("choices: ").replace(",", " ").split()
        if not tokens:
            return valid_defaults
        selected: list[str] = []
        for token in tokens:
            if not token.isdigit() or not (1 <= int(token) <= len(choices)):
                print("  choose listed numbers separated by spaces.")
                selected = []
                break
            value = choices[int(token) - 1].value
            if value == "skip":
                return (value,)
            if value not in selected:
                selected.append(value)
        if selected:
            return tuple(selected)


def _wizard_choice_window(total: int, selected: int, *, max_visible: int = WIZARD_MAX_VISIBLE_CHOICES) -> tuple[int, int]:
    if total <= max_visible:
        return 0, total
    if selected < 0:
        selected = 0
    if selected >= total:
        selected = total - 1
    half = max_visible // 2
    start = max(0, selected - half)
    end = start + max_visible
    if end > total:
        end = total
        start = end - max_visible
    return start, end


def _wizard_choice_fragments(
    title: str,
    prompt: str,
    choices: tuple[WizardChoice, ...],
    *,
    selected: int,
    max_visible: int = WIZARD_MAX_VISIBLE_CHOICES,
    allow_back: bool = False,
) -> list[tuple[str, str]]:
    fragments: list[tuple[str, str]] = [
        ("class:title", f"{title}\n"),
        ("class:prompt", f"{prompt}\n\n"),
    ]
    start, end = _wizard_choice_window(len(choices), selected, max_visible=max_visible)
    if start > 0:
        fragments.append(("class:hint", f"↑ {start} more above\n"))
    for index in range(start, end):
        choice = choices[index]
        active = index == selected
        marker = "›" if active else " "
        label_style = "class:selected" if active else "class:item"
        detail_style = (
            f"class:{choice.selected_detail_style}"
            if active
            else f"class:{choice.detail_style}"
        )
        fragments.append((label_style, f"{marker} {_wizard_choice_label(choice)}\n"))
        fragments.append((detail_style, f"  {choice.detail}\n"))
    if end < len(choices):
        fragments.append(("class:hint", f"↓ {len(choices) - end} more below\n"))
    if allow_back:
        fragments.append(("class:hint", "\nEnter confirms · Esc cancels · ↑/↓ or j/k moves"))
    else:
        fragments.append(("class:hint", "\nEnter confirms · ↑/↓ or j/k moves"))
    return fragments


def _wizard_choice_label(choice: WizardChoice) -> str:
    if not choice.emoji:
        return choice.label
    return f"{choice.emoji}  {choice.label}"


def _wizard_text_prompt(
    title: str,
    prompt: str,
    *,
    default: str | None = None,
    allow_back: bool = False,
    password: bool = False,
    required_message: str | None = None,
    preserve_default_on_empty: bool = True,
) -> str | _WizardBackSignal:
    if password:
        if _wizard_dialogs_supported():
            answer = _wizard_password_dialog(title, prompt, allow_back=allow_back)
            if answer is not None:
                return answer
        if os.environ.get("ELEPHANT_NO_WIZARD_DIALOGS") == "1":
            try:
                return input(f"{prompt}: ").strip()
            except (KeyboardInterrupt, EOFError):
                return WIZARD_BACK if allow_back else ""
        try:
            return getpass.getpass(f"{prompt}: ").strip()
        except (KeyboardInterrupt, EOFError):
            return WIZARD_BACK if allow_back else ""
    if _wizard_dialogs_supported() and required_message is not None:
        answer = _wizard_required_text_dialog(
            title,
            prompt,
            default=default or "",
            allow_back=allow_back,
            required_message=required_message,
        )
        if answer is not None:
            return answer
    if _wizard_dialogs_supported() and input_dialog is not None:
        answer = input_dialog(
            title=title,
            text=prompt,
            default=default or "",
            style=_wizard_style(),
            ok_text="Continue",
            cancel_text="Back",
        )
        answer = _wizard_run_dialog(answer)
        if answer is None:
            return WIZARD_BACK
        resolved = str(answer or "").strip()
        if resolved:
            return resolved
        if preserve_default_on_empty:
            return default or ""
        return ""
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    if answer:
        return answer
    if preserve_default_on_empty:
        return default or ""
    return ""


def _wizard_required_text_dialog(
    title: str,
    prompt: str,
    *,
    default: str = "",
    allow_back: bool = False,
    required_message: str,
) -> str | _WizardBackSignal | None:
    if not (
        PROMPT_TOOLKIT_DIALOGS_AVAILABLE
        and Application is not None
        and PromptKeyBindings is not None
        and get_app is not None
        and has_focus is not None
        and focus_next is not None
        and focus_previous is not None
        and HSplit is not None
        and Layout is not None
        and Button is not None
        and Dialog is not None
        and Label is not None
        and TextArea is not None
    ):
        return None

    text_field = TextArea(
        text=default,
        multiline=False,
        wrap_lines=False,
        prompt="",
    )
    validation_state = {"message": ""}
    hint = "Enter continues · Esc goes back · Tab moves focus" if allow_back else "Enter continues · Esc cancels · Tab moves focus"

    def _set_validation() -> None:
        validation_state["message"] = required_message
        get_app().invalidate()

    def _accept() -> None:
        value = text_field.text.strip()
        if value:
            get_app().exit(result=value)
            return
        _set_validation()

    def _cancel() -> None:
        get_app().exit(result=WIZARD_BACK)

    continue_button = Button(text="Continue", handler=_accept)
    cancel_button = Button(text="Back", handler=_cancel)
    dialog = Dialog(
        title=title,
        body=HSplit(
            [
                Label(text=prompt, dont_extend_height=True),
                text_field,
                Label(text=lambda: validation_state["message"], style="class:validation", dont_extend_height=True),
                Label(text=hint, dont_extend_height=True),
            ],
            padding=1,
        ),
        buttons=[continue_button, cancel_button],
        with_background=True,
    )
    bindings = PromptKeyBindings()

    @bindings.add("tab")
    def _focus_next_binding(event) -> None:
        focus_next(event)

    @bindings.add("s-tab")
    def _focus_previous_binding(event) -> None:
        focus_previous(event)

    @bindings.add("enter", filter=has_focus(text_field), eager=True)
    def _accept_binding(_event) -> None:
        _accept()

    @bindings.add("escape")
    def _cancel_binding(_event) -> None:
        _cancel()

    application = Application(
        layout=Layout(dialog, focused_element=text_field),
        key_bindings=bindings,
        style=_wizard_style(),
        full_screen=True,
        mouse_support=True,
    )
    answer = _wizard_run_dialog(application)
    if answer is WIZARD_BACK:
        return WIZARD_BACK
    return str(answer or text_field.text).strip()


def _wizard_password_dialog(
    title: str,
    prompt: str,
    *,
    allow_back: bool = False,
) -> str | _WizardBackSignal | None:
    if not (
        PROMPT_TOOLKIT_DIALOGS_AVAILABLE
        and Application is not None
        and PromptKeyBindings is not None
        and get_app is not None
        and has_focus is not None
        and focus_next is not None
        and focus_previous is not None
        and HSplit is not None
        and Layout is not None
        and Button is not None
        and Dialog is not None
        and Label is not None
        and TextArea is not None
    ):
        return None

    password_field = TextArea(
        multiline=False,
        password=True,
        wrap_lines=False,
        prompt="",
    )
    hint = "Enter continues · Esc goes back · Tab moves focus" if allow_back else "Enter continues · Esc cancels · Tab moves focus"

    def _accept() -> None:
        get_app().exit(result=password_field.text)

    def _cancel() -> None:
        get_app().exit(result=WIZARD_BACK)

    continue_button = Button(text="Continue", handler=_accept)
    cancel_button = Button(text="Back", handler=_cancel)
    dialog = Dialog(
        title=title,
        body=HSplit(
            [
                Label(text=prompt, dont_extend_height=True),
                password_field,
                Label(text=hint, dont_extend_height=True),
            ],
            padding=1,
        ),
        buttons=[continue_button, cancel_button],
        with_background=True,
    )
    bindings = PromptKeyBindings()

    @bindings.add("tab")
    def _focus_next_binding(event) -> None:
        focus_next(event)

    @bindings.add("s-tab")
    def _focus_previous_binding(event) -> None:
        focus_previous(event)

    @bindings.add("enter", filter=has_focus(password_field), eager=True)
    def _accept_binding(_event) -> None:
        _accept()

    @bindings.add("escape")
    def _cancel_binding(_event) -> None:
        _cancel()

    application = Application(
        layout=Layout(dialog, focused_element=password_field),
        key_bindings=bindings,
        style=_wizard_style(),
        full_screen=True,
        mouse_support=True,
    )
    answer = _wizard_run_dialog(application)
    if answer is WIZARD_BACK:
        return WIZARD_BACK
    return str(answer or password_field.text).strip()


def _wizard_info_dialog(
    title: str,
    message: str,
    *,
    continue_text: str = "Continue",
    allow_back: bool = True,
) -> bool | None:
    if not (
        PROMPT_TOOLKIT_DIALOGS_AVAILABLE
        and Application is not None
        and PromptKeyBindings is not None
        and get_app is not None
        and focus_next is not None
        and focus_previous is not None
        and HSplit is not None
        and Layout is not None
        and Button is not None
        and Dialog is not None
        and Label is not None
    ):
        return None

    hint = "Enter continues · Esc goes back · Tab moves focus" if allow_back else "Enter continues · Tab moves focus"

    def _accept() -> None:
        get_app().exit(result=True)

    def _cancel() -> None:
        get_app().exit(result=False)

    buttons = [Button(text=continue_text, handler=_accept)]
    if allow_back:
        buttons.append(Button(text="Back", handler=_cancel))
    dialog = Dialog(
        title=title,
        body=HSplit(
            [
                Label(text=message, dont_extend_height=True),
                Label(text=hint, dont_extend_height=True),
            ],
            padding=1,
        ),
        buttons=buttons,
        with_background=True,
    )
    bindings = PromptKeyBindings()

    @bindings.add("tab")
    def _focus_next_binding(event) -> None:
        focus_next(event)

    @bindings.add("s-tab")
    def _focus_previous_binding(event) -> None:
        focus_previous(event)

    @bindings.add("enter", eager=True)
    def _accept_binding(_event) -> None:
        _accept()

    if allow_back:

        @bindings.add("escape")
        def _cancel_binding(_event) -> None:
            _cancel()

    application = Application(
        layout=Layout(dialog, focused_element=buttons[0]),
        key_bindings=bindings,
        style=_wizard_style(),
        full_screen=True,
        mouse_support=True,
    )
    return bool(_wizard_run_dialog(application))


def _wizard_choice_prompt(
    title: str,
    prompt: str,
    choices: tuple[WizardChoice, ...],
    *,
    default: str | None = None,
    allow_back: bool = False,
) -> str | _WizardBackSignal:
    if not choices:
        return default or ""
    default_value = default or choices[0].value
    if _wizard_dialogs_supported():
        return _wizard_choice_menu(title, prompt, choices, default=default_value, allow_back=allow_back)
    print(prompt)
    for index, choice in enumerate(choices, start=1):
        marker = "*" if choice.value == default_value else " "
        print(f"  {marker} {index}. {_wizard_choice_label(choice)} :: {choice.detail}")
    while True:
        answer = input(f"choice [{default_value}]: ").strip()
        if not answer:
            return default_value
        if answer.isdigit():
            index = int(answer)
            if 1 <= index <= len(choices):
                return choices[index - 1].value
        normalized = answer.casefold()
        for choice in choices:
            if normalized in {choice.value.casefold(), choice.label.casefold()}:
                return choice.value
        print("  choose a listed number, provider id, or label.")


def _wizard_dual_choice_prompt(
    title: str,
    prompt: str,
    choices: tuple[WizardChoice, ...],
    *,
    first_title: str,
    second_title: str,
    default_first: str | None = None,
    default_second: str | None = None,
    allow_back: bool = False,
) -> tuple[str, str] | _WizardBackSignal:
    if not choices:
        fallback = default_first or default_second or ""
        return fallback, fallback
    first_value = default_first or choices[0].value
    second_value = default_second or first_value
    if _wizard_dialogs_supported():
        return _wizard_dual_choice_menu(
            title,
            prompt,
            choices,
            first_title=first_title,
            second_title=second_title,
            default_first=first_value,
            default_second=second_value,
            allow_back=allow_back,
        )
    first_answer = _wizard_choice_prompt(
        f"Choose The {first_title}",
        prompt,
        choices,
        default=first_value,
        allow_back=allow_back,
    )
    if first_answer is WIZARD_BACK:
        return WIZARD_BACK
    second_answer = _wizard_choice_prompt(
        f"Choose The {second_title}",
        prompt,
        choices,
        default=second_value,
        allow_back=allow_back,
    )
    if second_answer is WIZARD_BACK:
        return WIZARD_BACK
    return str(first_answer), str(second_answer)
