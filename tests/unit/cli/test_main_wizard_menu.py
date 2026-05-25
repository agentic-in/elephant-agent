from __future__ import annotations

from contextlib import ExitStack, contextmanager
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest import mock

import apps.cli.__main__ as cli_main
import apps.cli.cli_main_elephant_support as cli_elephant_support
import apps.cli.cli_main_impl as cli_main_impl
import apps.cli.cli_main_setup as cli_main_setup
import apps.cli.cli_main_support as cli_main_support
import apps.cli.wizard as cli_wizard
from apps.cli.__main__ import (
    _run_interactive_elephant_wizard,
    _provider_choices,
    _run_interactive_birth_wizard,
)
from apps.cli.wizard import (
    _guard_radio_list_selection_bounds,
    _wizard_info_dialog,
    _wizard_dual_choice_menu,
    _wizard_text_prompt,
    WIZARD_MAX_VISIBLE_CHOICES,
    WIZARD_BACK,
    WIZARD_CANCEL,
    WizardChoice,
    _wizard_choice_fragments,
    _wizard_choice_label,
    _wizard_choice_menu,
    _wizard_choice_window,
)


class _FakeRadioList:
    def __init__(self, values, default, **_kwargs):
        self.values = values
        self.current_value = default


class _FakeButton:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakeLabel:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakeDialog:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


@contextmanager
def _patch_choice_menu_dependencies(
    application_cls, *, bindings_cls=None, radio_list_cls=_FakeRadioList
):
    exit_calls: list[dict[str, object]] = []
    focused = {"element": None}
    fake_app = SimpleNamespace(
        exit=lambda **kwargs: exit_calls.append(kwargs),
        invalidate=lambda: None,
        layout=SimpleNamespace(
            has_focus=lambda value: focused["element"] is value,
            focus=lambda value: focused.__setitem__("element", value),
        ),
        _exit_calls=exit_calls,
        _focused=focused,
    )
    with ExitStack() as stack:
        stack.enter_context(
            mock.patch.object(cli_wizard, "PROMPT_TOOLKIT_DIALOGS_AVAILABLE", True)
        )
        stack.enter_context(
            mock.patch.object(cli_wizard, "Application", application_cls)
        )
        stack.enter_context(
            mock.patch.object(
                cli_wizard, "PromptKeyBindings", bindings_cls or mock.Mock
            )
        )
        stack.enter_context(
            mock.patch.object(cli_wizard, "get_app", return_value=fake_app)
        )
        stack.enter_context(
            mock.patch.object(cli_wizard, "has_focus", side_effect=lambda _value: True)
        )
        stack.enter_context(
            mock.patch.object(cli_wizard, "focus_next", lambda *_args, **_kwargs: None)
        )
        stack.enter_context(
            mock.patch.object(
                cli_wizard, "focus_previous", lambda *_args, **_kwargs: None
            )
        )
        stack.enter_context(
            mock.patch.object(
                cli_wizard, "HSplit", lambda children, padding=0: (children, padding)
            )
        )
        stack.enter_context(
            mock.patch.object(
                cli_wizard, "Window", lambda content, **kwargs: (content, kwargs)
            )
        )
        stack.enter_context(
            mock.patch.object(
                cli_wizard, "FormattedTextControl", lambda fragments: fragments
            )
        )
        stack.enter_context(
            mock.patch.object(
                cli_wizard,
                "Layout",
                lambda dialog, focused_element=None: (dialog, focused_element),
            )
        )
        stack.enter_context(
            mock.patch.object(cli_wizard, "PromptDimension", SimpleNamespace)
        )
        stack.enter_context(mock.patch.object(cli_wizard, "Button", _FakeButton))
        stack.enter_context(mock.patch.object(cli_wizard, "Dialog", _FakeDialog))
        stack.enter_context(mock.patch.object(cli_wizard, "Label", _FakeLabel))
        stack.enter_context(mock.patch.object(cli_wizard, "RadioList", radio_list_cls))
        stack.enter_context(
            mock.patch.object(cli_wizard, "_wizard_style", return_value=None)
        )
        yield fake_app


class _BoundedRadioListStub:
    def __init__(self) -> None:
        self.values = (("companion", "Companion"), ("operator", "Operator"))
        self._selected_index = 0
        self.current_value = "companion"

    def _handle_enter(self) -> None:
        self.current_value = self.values[self._selected_index][0]


class WizardChoiceMenuTest(unittest.TestCase):
    def test_guard_radio_list_selection_bounds_clamps_large_index(self) -> None:
        radio_list = _BoundedRadioListStub()
        radio_list._selected_index = 99

        _guard_radio_list_selection_bounds(radio_list)
        radio_list._handle_enter()

        self.assertEqual(radio_list._selected_index, 1)
        self.assertEqual(radio_list.current_value, "operator")

    def test_guard_radio_list_selection_bounds_clamps_negative_index(self) -> None:
        radio_list = _BoundedRadioListStub()
        radio_list._selected_index = -3

        _guard_radio_list_selection_bounds(radio_list)
        radio_list._handle_enter()

        self.assertEqual(radio_list._selected_index, 0)
        self.assertEqual(radio_list.current_value, "companion")

    def test_wizard_choice_window_caps_long_lists_to_nine_rows(self) -> None:
        self.assertEqual(_wizard_choice_window(4, 0), (0, 4))
        self.assertEqual(_wizard_choice_window(12, 0), (0, WIZARD_MAX_VISIBLE_CHOICES))
        self.assertEqual(_wizard_choice_window(12, 6), (2, 11))
        self.assertEqual(_wizard_choice_window(12, 11), (3, 12))

    def test_wizard_choice_fragments_render_without_blank_lines_between_options(
        self,
    ) -> None:
        choices = (
            WizardChoice(
                value="companion",
                label="Companion",
                detail="Steady and present.",
                emoji="🤝",
            ),
            WizardChoice(
                value="operator",
                label="Operator",
                detail="Direct and durable.",
                emoji="🛠️",
            ),
        )

        text = "".join(
            fragment
            for _, fragment in _wizard_choice_fragments(
                "Choose", "Prompt", choices, selected=0
            )
        )

        self.assertIn(
            "› 🤝  Companion\n  Steady and present.\n  🛠️  Operator\n  Direct and durable.\n",
            text,
        )
        self.assertNotIn("Steady and present.\n\n  Operator", text)
        self.assertIn("Enter confirms", text)

    def test_wizard_choice_fragments_show_scroll_hints_for_hidden_provider_rows(
        self,
    ) -> None:
        choices = tuple(
            WizardChoice(
                value=f"provider-{index}",
                label=f"Provider {index}",
                detail=f"Catalog summary {index}",
                emoji="🧠",
            )
            for index in range(12)
        )

        text = "".join(
            fragment
            for _, fragment in _wizard_choice_fragments(
                "Choose", "Prompt", choices, selected=6
            )
        )

        self.assertIn("↑ 2 more above", text)
        self.assertIn("↓ 1 more below", text)
        self.assertNotIn("Provider 0", text)
        self.assertIn("Provider 2", text)
        self.assertIn("Provider 10", text)
        self.assertNotIn("Provider 11", text)

    def test_wizard_choice_fragments_show_back_hint_when_allowed(self) -> None:
        choices = (
            WizardChoice(
                value="companion",
                label="Companion",
                detail="Steady and present.",
                emoji="🤝",
            ),
            WizardChoice(
                value="operator",
                label="Operator",
                detail="Direct and durable.",
                emoji="🛠️",
            ),
        )

        text = "".join(
            fragment
            for _, fragment in _wizard_choice_fragments(
                "Choose", "Prompt", choices, selected=0, allow_back=True
            )
        )

        self.assertIn("Enter confirms · Esc cancels · ↑/↓ or j/k moves", text)

    def test_wizard_choice_menu_uses_centered_dialog_application(self) -> None:
        choices = (
            WizardChoice(
                value="companion",
                label="Companion",
                detail="Steady and present.",
                emoji="🤝",
            ),
            WizardChoice(
                value="operator",
                label="Operator",
                detail="Direct and durable.",
                emoji="🛠️",
            ),
        )
        captured: dict[str, object] = {}

        class _FakeApplication:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def run(self):
                return "operator"

        with _patch_choice_menu_dependencies(_FakeApplication):
            answer = _wizard_choice_menu(
                "Choose", "Prompt", choices, default="companion"
            )

        self.assertEqual(answer, "operator")
        self.assertTrue(captured["full_screen"])
        self.assertTrue(captured["mouse_support"])

    def test_wizard_choice_menu_runs_dialog_in_thread_when_loop_is_active(self) -> None:
        choices = (
            WizardChoice(
                value="companion",
                label="Companion",
                detail="Steady and present.",
                emoji="🤝",
            ),
            WizardChoice(
                value="operator",
                label="Operator",
                detail="Direct and durable.",
                emoji="🛠️",
            ),
        )
        captured: dict[str, object] = {}

        class _FakeApplication:
            def __init__(self, **_kwargs):
                pass

            def run(self, **kwargs):
                captured.update(kwargs)
                return "operator"

        with (
            _patch_choice_menu_dependencies(_FakeApplication),
            mock.patch.object(
                cli_wizard, "_wizard_asyncio_loop_running", return_value=True
            ),
        ):
            answer = _wizard_choice_menu(
                "Choose", "Prompt", choices, default="companion"
            )

        self.assertEqual(answer, "operator")
        self.assertTrue(captured["in_thread"])

    def test_wizard_choice_menu_uses_single_line_radio_entries_for_mouse_safety(
        self,
    ) -> None:
        choices = (
            WizardChoice(
                value="companion",
                label="Companion",
                detail="Steady and present.",
                emoji="🤝",
            ),
            WizardChoice(
                value="operator",
                label="Operator",
                detail="Direct and durable.",
                emoji="🛠️",
            ),
        )
        captured: dict[str, object] = {}

        class _CapturingRadioList:
            def __init__(self, values, default, **_kwargs):
                captured["values"] = values
                self.values = values
                self.current_value = default

        class _FakeApplication:
            def __init__(self, **_kwargs):
                pass

            def run(self):
                return "operator"

        with _patch_choice_menu_dependencies(
            _FakeApplication, radio_list_cls=_CapturingRadioList
        ):
            answer = _wizard_choice_menu(
                "Choose", "Prompt", choices, default="companion"
            )

        self.assertEqual(answer, "operator")
        first_value = captured["values"][0][1]
        rendered = "".join(fragment for _, fragment in first_value)
        self.assertNotIn("\n", rendered)
        self.assertIn("Steady and present.", rendered)

    def test_wizard_choice_menu_can_return_back_signal(self) -> None:
        choices = (
            WizardChoice(
                value="companion",
                label="Companion",
                detail="Steady and present.",
                emoji="🤝",
            ),
            WizardChoice(
                value="operator",
                label="Operator",
                detail="Direct and durable.",
                emoji="🛠️",
            ),
        )

        class _FakeApplication:
            def __init__(self, **_kwargs):
                pass

            def run(self):
                return WIZARD_BACK

        with _patch_choice_menu_dependencies(_FakeApplication):
            answer = _wizard_choice_menu(
                "Choose", "Prompt", choices, default="companion", allow_back=True
            )

        self.assertIs(answer, WIZARD_BACK)

    def test_wizard_choice_menu_cancel_never_falls_back_to_default(self) -> None:
        choices = (
            WizardChoice(
                value="companion",
                label="Companion",
                detail="Steady and present.",
                emoji="🤝",
            ),
            WizardChoice(
                value="operator",
                label="Operator",
                detail="Direct and durable.",
                emoji="🛠️",
            ),
        )

        class _FakeApplication:
            def __init__(self, **_kwargs):
                pass

            def run(self):
                return WIZARD_BACK

        with _patch_choice_menu_dependencies(_FakeApplication):
            answer = _wizard_choice_menu(
                "Choose", "Prompt", choices, default="companion"
            )

        self.assertIs(answer, WIZARD_BACK)

    def test_wizard_choice_menu_binds_enter_eagerly_for_continue(self) -> None:
        choices = (
            WizardChoice(
                value="companion",
                label="Companion",
                detail="Steady and present.",
                emoji="🤝",
            ),
            WizardChoice(
                value="operator",
                label="Operator",
                detail="Direct and durable.",
                emoji="🛠️",
            ),
        )
        binding_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

        class _FakeBindings:
            def add(self, *keys, **kwargs):
                binding_calls.append((keys, kwargs))

                def _decorator(func):
                    return func

                return _decorator

        class _FakeApplication:
            def __init__(self, **_kwargs):
                pass

            def run(self):
                return "operator"

        with _patch_choice_menu_dependencies(
            _FakeApplication, bindings_cls=_FakeBindings
        ):
            answer = _wizard_choice_menu(
                "Choose", "Prompt", choices, default="companion"
            )

        self.assertEqual(answer, "operator")
        enter_call = next(
            (kwargs for keys, kwargs in binding_calls if keys == ("enter",)), None
        )
        self.assertIsNotNone(enter_call)
        self.assertTrue(enter_call["eager"])

    def test_wizard_dual_choice_menu_uses_only_continue_and_back_buttons(self) -> None:
        choices = (
            WizardChoice(value="gpt-5.4", label="gpt-5.4", detail="Large lane"),
            WizardChoice(
                value="gpt-5.4-mini", label="gpt-5.4-mini", detail="Small lane"
            ),
        )
        captured: dict[str, object] = {}

        class _FakeDialog:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        class _FakeApplication:
            def __init__(self, **_kwargs):
                pass

            def run(self):
                return ("gpt-5.4", "gpt-5.4-mini")

        with (
            _patch_choice_menu_dependencies(_FakeApplication),
            mock.patch.object(cli_wizard, "Dialog", _FakeDialog),
        ):
            answer = _wizard_dual_choice_menu(
                "Choose Models",
                "Pick both lanes.",
                choices,
                first_title="Deliberate",
                second_title="Swift",
                default_first="gpt-5.4",
                default_second="gpt-5.4-mini",
            )

        self.assertEqual(answer, ("gpt-5.4", "gpt-5.4-mini"))
        button_labels = [button.kwargs["text"] for button in captured["buttons"]]
        self.assertEqual(button_labels, ["Continue", "Back"])

    def test_wizard_dual_choice_menu_binds_space_and_delete_for_selection_flow(
        self,
    ) -> None:
        choices = (
            WizardChoice(value="gpt-5.4", label="gpt-5.4", detail="Large lane"),
            WizardChoice(
                value="gpt-5.4-mini", label="gpt-5.4-mini", detail="Small lane"
            ),
        )
        binding_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

        class _FakeBindings:
            def add(self, *keys, **kwargs):
                binding_calls.append((keys, kwargs))

                def _decorator(func):
                    return func

                return _decorator

        class _FakeApplication:
            def __init__(self, **_kwargs):
                pass

            def run(self):
                return ("gpt-5.4", "gpt-5.4-mini")

        with _patch_choice_menu_dependencies(
            _FakeApplication, bindings_cls=_FakeBindings
        ):
            answer = _wizard_dual_choice_menu(
                "Choose Models",
                "Pick both lanes.",
                choices,
                first_title="Deliberate",
                second_title="Swift",
                default_first="gpt-5.4",
                default_second="gpt-5.4-mini",
            )

        self.assertEqual(answer, ("gpt-5.4", "gpt-5.4-mini"))
        self.assertIn((("space",), {"eager": True}), binding_calls)
        self.assertIn((("backspace",), {"eager": True}), binding_calls)
        self.assertIn((("delete",), {"eager": True}), binding_calls)

    def test_wizard_dual_choice_menu_space_accepts_when_complete_off_radio(
        self,
    ) -> None:
        choices = (
            WizardChoice(value="gpt-5.4", label="gpt-5.4", detail="Large lane"),
            WizardChoice(
                value="gpt-5.4-mini", label="gpt-5.4-mini", detail="Small lane"
            ),
        )
        handlers: dict[tuple[object, ...], object] = {}

        class _FakeBindings:
            def add(self, *keys, **_kwargs):
                def _decorator(func):
                    handlers[keys] = func
                    return func

                return _decorator

        class _FakeApplication:
            def __init__(self, **_kwargs):
                pass

            def run(self):
                handlers[("space",)](SimpleNamespace(app=fake_app))
                return fake_app._exit_calls[-1]["result"]

        with _patch_choice_menu_dependencies(
            _FakeApplication, bindings_cls=_FakeBindings
        ) as fake_app:
            answer = _wizard_dual_choice_menu(
                "Choose Models",
                "Pick both lanes.",
                choices,
                first_title="Deliberate",
                second_title="Swift",
                default_first="gpt-5.4",
                default_second="gpt-5.4-mini",
            )

        self.assertEqual(answer, ("gpt-5.4", "gpt-5.4-mini"))

    def test_wizard_info_dialog_uses_full_screen_application(self) -> None:
        captured: dict[str, object] = {}

        class _FakeApplication:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def run(self):
                return True

        with (
            _patch_choice_menu_dependencies(_FakeApplication),
            mock.patch.object(cli_wizard, "_wizard_style", return_value=None),
        ):
            answer = _wizard_info_dialog(
                "Setup", "Intro body", continue_text="Start setup"
            )

        self.assertTrue(answer)
        self.assertTrue(captured["full_screen"])
        self.assertTrue(captured["mouse_support"])

    def test_wizard_info_dialog_can_return_back_signal_as_false(self) -> None:
        class _FakeApplication:
            def __init__(self, **_kwargs):
                pass

            def run(self):
                return False

        with (
            _patch_choice_menu_dependencies(_FakeApplication),
            mock.patch.object(cli_wizard, "_wizard_style", return_value=None),
        ):
            answer = _wizard_info_dialog(
                "Setup", "Intro body", continue_text="Start setup"
            )

        self.assertFalse(answer)

    def test_wizard_text_prompt_uses_back_button_for_born_flow(self) -> None:
        dialog = mock.Mock()
        dialog.run.return_value = None

        with (
            mock.patch.object(
                cli_wizard, "_wizard_dialogs_supported", return_value=True
            ),
            mock.patch.object(
                cli_wizard, "input_dialog", return_value=dialog
            ) as input_dialog_mock,
            mock.patch.object(cli_wizard, "_wizard_style", return_value=None),
        ):
            answer = _wizard_text_prompt(
                "Choose", "Prompt", default="Aeon", allow_back=True
            )

        self.assertIs(answer, WIZARD_BACK)
        self.assertEqual(input_dialog_mock.call_args.kwargs["ok_text"], "Continue")
        self.assertEqual(input_dialog_mock.call_args.kwargs["cancel_text"], "Back")

    def test_wizard_text_prompt_uses_back_button_even_without_previous_step(
        self,
    ) -> None:
        dialog = mock.Mock()
        dialog.run.return_value = None

        with (
            mock.patch.object(
                cli_wizard, "_wizard_dialogs_supported", return_value=True
            ),
            mock.patch.object(
                cli_wizard, "input_dialog", return_value=dialog
            ) as input_dialog_mock,
            mock.patch.object(cli_wizard, "_wizard_style", return_value=None),
        ):
            answer = _wizard_text_prompt("Choose", "Prompt", default="Nova")

        self.assertIs(answer, WIZARD_BACK)
        self.assertEqual(input_dialog_mock.call_args.kwargs["ok_text"], "Continue")
        self.assertEqual(input_dialog_mock.call_args.kwargs["cancel_text"], "Back")

    def test_wizard_text_prompt_uses_required_dialog_when_validation_copy_is_needed(
        self,
    ) -> None:
        with (
            mock.patch.object(
                cli_wizard, "_wizard_dialogs_supported", return_value=True
            ),
            mock.patch.object(
                cli_wizard,
                "_wizard_required_text_dialog",
                return_value="Name this Elephant Agent",
            ) as required_dialog,
        ):
            answer = _wizard_text_prompt(
                "Name This Elephant Agent",
                "Prompt",
                default="",
                allow_back=True,
                required_message="Add a name before continuing.",
            )

        self.assertEqual(answer, "Name this Elephant Agent")
        required_dialog.assert_called_once_with(
            "Name This Elephant Agent",
            "Prompt",
            default="",
            allow_back=True,
            required_message="Add a name before continuing.",
        )

    def test_wizard_text_prompt_can_clear_a_prefilled_value(self) -> None:
        dialog = mock.Mock()
        dialog.run.return_value = ""

        with (
            mock.patch.object(
                cli_wizard, "_wizard_dialogs_supported", return_value=True
            ),
            mock.patch.object(cli_wizard, "input_dialog", return_value=dialog),
            mock.patch.object(cli_wizard, "_wizard_style", return_value=None),
        ):
            answer = _wizard_text_prompt(
                "Default Elephant",
                "Prompt",
                default="aeon",
                preserve_default_on_empty=False,
            )

        self.assertEqual(answer, "")

    def test_wizard_text_prompt_runs_input_dialog_in_thread_when_loop_is_active(
        self,
    ) -> None:
        captured: dict[str, object] = {}

        class _FakeDialog:
            def run(self, **kwargs):
                captured.update(kwargs)
                return "Aeon"

        with (
            mock.patch.object(
                cli_wizard, "_wizard_dialogs_supported", return_value=True
            ),
            mock.patch.object(cli_wizard, "input_dialog", return_value=_FakeDialog()),
            mock.patch.object(cli_wizard, "_wizard_style", return_value=None),
            mock.patch.object(
                cli_wizard, "_wizard_asyncio_loop_running", return_value=True
            ),
        ):
            answer = _wizard_text_prompt("Choose", "Prompt", default="Nova")

        self.assertEqual(answer, "Aeon")
        self.assertTrue(captured["in_thread"])

    def test_wizard_choice_label_prefixes_emoji_when_present(self) -> None:
        self.assertEqual(
            _wizard_choice_label(
                WizardChoice(
                    value="companion", label="Companion", detail="Steady", emoji="🤝"
                )
            ),
            "🤝  Companion",
        )
        self.assertEqual(
            _wizard_choice_label(
                WizardChoice(value="plain", label="Plain", detail="Simple")
            ),
            "Plain",
        )


if __name__ == "__main__":
    unittest.main()
