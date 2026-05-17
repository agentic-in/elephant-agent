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
def _patch_choice_menu_dependencies(application_cls, *, bindings_cls=None, radio_list_cls=_FakeRadioList):
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
        stack.enter_context(mock.patch.object(cli_wizard, "PROMPT_TOOLKIT_DIALOGS_AVAILABLE", True))
        stack.enter_context(mock.patch.object(cli_wizard, "Application", application_cls))
        stack.enter_context(mock.patch.object(cli_wizard, "PromptKeyBindings", bindings_cls or mock.Mock))
        stack.enter_context(mock.patch.object(cli_wizard, "get_app", return_value=fake_app))
        stack.enter_context(mock.patch.object(cli_wizard, "has_focus", side_effect=lambda _value: True))
        stack.enter_context(mock.patch.object(cli_wizard, "focus_next", lambda *_args, **_kwargs: None))
        stack.enter_context(mock.patch.object(cli_wizard, "focus_previous", lambda *_args, **_kwargs: None))
        stack.enter_context(mock.patch.object(cli_wizard, "HSplit", lambda children, padding=0: (children, padding)))
        stack.enter_context(mock.patch.object(cli_wizard, "Window", lambda content, **kwargs: (content, kwargs)))
        stack.enter_context(mock.patch.object(cli_wizard, "FormattedTextControl", lambda fragments: fragments))
        stack.enter_context(mock.patch.object(cli_wizard, "Layout", lambda dialog, focused_element=None: (dialog, focused_element)))
        stack.enter_context(mock.patch.object(cli_wizard, "PromptDimension", SimpleNamespace))
        stack.enter_context(mock.patch.object(cli_wizard, "Button", _FakeButton))
        stack.enter_context(mock.patch.object(cli_wizard, "Dialog", _FakeDialog))
        stack.enter_context(mock.patch.object(cli_wizard, "Label", _FakeLabel))
        stack.enter_context(mock.patch.object(cli_wizard, "RadioList", radio_list_cls))
        stack.enter_context(mock.patch.object(cli_wizard, "_wizard_style", return_value=None))
        yield fake_app


class _BoundedRadioListStub:
    def __init__(self) -> None:
        self.values = (("companion", "Companion"), ("operator", "Operator"))
        self._selected_index = 0
        self.current_value = "companion"

    def _handle_enter(self) -> None:
        self.current_value = self.values[self._selected_index][0]


class CliInitIntroTest(unittest.TestCase):
    def test_init_welcome_frame_renders_enter_gate_without_removed_intro_animation(self) -> None:
        if not cli_main_setup.RICH_AVAILABLE or cli_main_setup.Console is None:
            self.skipTest("rich is not available")

        console = cli_main_setup.Console(record=True, width=100, height=30, highlight=False, soft_wrap=True)
        console.print(cli_main_setup._init_welcome_frame(0))

        rendered = console.export_text(styles=False)
        self.assertIn("Elephant Agent · English", rendered)
        self.assertIn("Elephants never forget. 🐘", rendered)
        self.assertIn("Evidence is the beginning.", rendered)
        self.assertIn("Warm evidence · PM-first · Gentle curiosity", rendered)
        self.assertIn("Create yours", rendered)
        self.assertIn("Press Enter to create yours.", rendered)
        self.assertNotIn("\n🐘\n", rendered)
        self.assertNotIn("Enter to begin", rendered)
        self.assertNotIn("Elephant Agent Init · Stage 0", rendered)
        self.assertNotIn("Only a few steps left", rendered)
        self.assertNotIn("Who you are first. Continuity second. Ca", rendered)
        self.assertNotIn("personal model boot", rendered.lower())
        self.assertNotIn("corrigible", rendered.lower())

    def test_init_welcome_copy_updates_all_language_variants(self) -> None:
        rendered_variants = "\n\n".join(
            cli_main_setup._init_welcome_plain_text(index)
            for index in range(len(cli_main_setup._INIT_WELCOME_VARIANTS))
        )

        self.assertIn("Press Enter to create yours.", rendered_variants)
        self.assertIn("按 Enter 创建属于你的 Elephant Agent。", rendered_variants)
        self.assertIn("Appuie sur Enter pour créer le tien.", rendered_variants)
        self.assertIn("Enter를 눌러 나만의 Elephant Agent를 만드세요.", rendered_variants)
        self.assertIn("Pulsa Enter para crear el tuyo.", rendered_variants)
        self.assertEqual(rendered_variants.count("Elephants never forget. 🐘"), 5)
        self.assertNotIn("\n🐘\n", rendered_variants)
        self.assertEqual(rendered_variants.count("Warm evidence · PM-first · Gentle curiosity"), 5)
        self.assertNotIn("进入 Elephant Agent 的世界", rendered_variants)
        self.assertNotIn("step into Elephant Agent's world", rendered_variants)

    def test_birth_wizard_intro_uses_short_pm_first_copy(self) -> None:
        if not cli_main_setup.RICH_AVAILABLE or cli_main_setup.Console is None:
            self.skipTest("rich is not available")

        console = cli_main_setup.Console(record=True, width=170, height=36, highlight=False, soft_wrap=True)
        with mock.patch.object(cli_main_setup, "Console", return_value=console):
            cli_main_setup._print_birth_wizard_intro()

        rendered = console.export_text(styles=False)
        self.assertIn("Stage 0: start from you", rendered)
        self.assertIn("small Personal Model", rendered)
        self.assertIn("Personal anchors first", rendered)
        self.assertIn("IM stays optional.", rendered)
        self.assertIn("Open first elephant; IM optional.", rendered)
        self.assertNotIn("begin with a blank elephant", rendered)
        self.assertNotIn("database dump", rendered)
        self.assertNotIn("the elephant before recall", rendered)

    def test_cli_help_intro_renders_only_once_without_separator_duplication(self) -> None:
        if not cli_main_support.RICH_AVAILABLE or cli_main_support.Console is None:
            self.skipTest("rich is not available")

        console = cli_main_support.Console(record=True, width=150, highlight=False, soft_wrap=True)
        with mock.patch.object(cli_main_support, "Console", return_value=console):
            cli_main_support._print_cli_help(
                "Elephant Agent launcher",
                "Warm, steady ways back to the elephant that remembers your path.",
                commands=(("init", "Run first-time setup."),),
                tagline=cli_main_support.CLI_HELP_TAGLINE,
            )

        rendered = console.export_text(styles=False)
        intro = "Elephant Agent is personal-model-first AI"
        self.assertEqual(rendered.count(intro), 1)
        self.assertIn(cli_main_support.CLI_HELP_TAGLINE, rendered)
        self.assertNotIn("• • init", rendered)

    def test_render_cli_banner_mark_uses_stage_zero_elephant(self) -> None:
        with mock.patch.object(cli_main_support, "render_stage_zero_elephant_mark", return_value="elephant-mark") as render_stage_zero_elephant_mark:
            result = cli_main_support._render_cli_banner_mark()

        self.assertEqual(result, "elephant-mark")
        render_stage_zero_elephant_mark.assert_called_once_with()


class InitQuestionDesignTest(unittest.TestCase):
    def test_starter_questions_use_human_labels_for_manual_and_blank_options(self) -> None:
        for spec in cli_main_impl._STARTER_QUESTIONS:
            choices = tuple(spec["choices_zh"])
            by_value = {choice[0]: choice for choice in choices}
            self.assertIn("我自己", by_value["type"][1])
            self.assertEqual(by_value["skip"][1], "暂时留空")
            self.assertNotEqual(by_value["type"][1], "type")
            self.assertNotEqual(by_value["skip"][1], "skip")

    def test_starter_question_options_read_as_balanced_short_phrases(self) -> None:
        for spec in cli_main_impl._STARTER_QUESTIONS:
            for choice in tuple(spec["choices_zh"]):
                value, label = choice[0], choice[1]
                if value in {"type", "skip"}:
                    continue
                self.assertGreaterEqual(len(label), 6)
                self.assertLessEqual(len(label), 11)
                self.assertNotIn("/", label)

    def test_attention_options_read_as_short_phrases(self) -> None:
        for choice in cli_main_impl._ATTENTION_CHOICES_ZH:
            value, label = choice[0], choice[1]
            if value == "type":
                continue
            self.assertGreaterEqual(len(label), 7)
            self.assertLessEqual(len(label), 11)
            self.assertNotIn("/", label)

    def test_init_options_can_carry_lightweight_emoji(self) -> None:
        self.assertEqual(cli_main_impl._ATTENTION_CHOICES_ZH[0][3], "🚀")
        for spec in cli_main_impl._STARTER_QUESTIONS:
            for choice in tuple(spec["choices_zh"]):
                self.assertGreaterEqual(len(choice), 4)
                self.assertTrue(str(choice[3]).strip())

    def test_hidden_profile_answer_does_not_replace_tui_detail(self) -> None:
        choice = cli_main_impl._ATTENTION_CHOICES_ZH[1]
        rendered = cli_main_impl._init_wizard_choice(choice)

        self.assertIn("像站在一条路", rendered.detail)
        self.assertNotIn("过渡和选择", rendered.detail)
        self.assertIn("过渡和选择", choice[4])

        english = cli_main_impl._ATTENTION_CHOICES_EN[1]
        rendered_en = cli_main_impl._init_wizard_choice(english)
        self.assertIn("Changing direction", rendered_en.detail)
        self.assertNotIn("Currently in transition", rendered_en.detail)
        self.assertIn("Currently in transition", english[4])

    def test_attention_choice_persists_hidden_profile_answer_for_pm(self) -> None:
        selected = "正站在一个岔路口"
        choice = next(choice for choice in cli_main_impl._ATTENTION_CHOICES_ZH if choice[0] == selected)
        with mock.patch.object(cli_main_impl, "_wizard_choice_prompt", return_value=selected):
            answer = cli_main_impl._prompt_choice_with_type(
                "zh",
                "Attention",
                "关注点",
                "Pick one.",
                "最近脑海里经常出现的想法，大概是关于什么的？",
                cli_main_impl._ATTENTION_CHOICES_ZH,
                default=selected,
                persist_choice_detail=True,
            )

        self.assertEqual(answer, choice[4])
        self.assertIn("过渡和选择", answer)
        self.assertNotIn("用户", answer)
        self.assertNotIn("像站在一条路将要分开的地方", answer)
        self.assertNotEqual(answer, selected)

    def test_english_attention_choice_persists_hidden_profile_answer_for_pm(self) -> None:
        selected = "standing at a fork"
        choice = next(choice for choice in cli_main_impl._ATTENTION_CHOICES_EN if choice[0] == selected)
        with mock.patch.object(cli_main_impl, "_wizard_choice_prompt", return_value=selected):
            answer = cli_main_impl._prompt_choice_with_type(
                "en",
                "Attention",
                "关注点",
                "Which thread is taking most of your attention lately?",
                "最近脑海里经常出现的想法，大概是关于什么的？",
                cli_main_impl._ATTENTION_CHOICES_EN,
                default=selected,
                persist_choice_detail=True,
            )

        self.assertEqual(answer, choice[4])
        self.assertIn("Currently in transition", answer)
        self.assertNotIn("Changing direction", answer)

    def test_attention_manual_input_persists_user_words(self) -> None:
        with (
            mock.patch.object(cli_main_impl, "_wizard_choice_prompt", return_value="type"),
            mock.patch.object(cli_main_impl, "_wizard_text_prompt", return_value="我正在重新整理生活优先级"),
        ):
            answer = cli_main_impl._prompt_choice_with_type(
                "zh",
                "Attention",
                "关注点",
                "Pick one.",
                "选一个。",
                cli_main_impl._ATTENTION_CHOICES_ZH,
                default="type",
                persist_choice_detail=True,
            )

        self.assertEqual(answer, "我正在重新整理生活优先级")

    def test_local_embedding_source_default_follows_language(self) -> None:
        defaults: list[str] = []

        def choose(_title, _body, _choices, *, default, **_kwargs):
            defaults.append(default)
            return "local" if len(defaults) == 1 else default

        with mock.patch.object(cli_main_impl, "_wizard_choice_prompt", side_effect=choose):
            zh_answer = cli_main_impl._run_embedding_birth_wizard(
                default_source="huggingface",
                language="zh",
            )

        self.assertEqual(defaults, ["local", "modelscope"])
        self.assertEqual(zh_answer[:2], ("local", "modelscope"))

        defaults.clear()
        with mock.patch.object(cli_main_impl, "_wizard_choice_prompt", side_effect=choose):
            en_answer = cli_main_impl._run_embedding_birth_wizard(
                default_source="modelscope",
                language="en",
            )

        self.assertEqual(defaults, ["local", "huggingface"])
        self.assertEqual(en_answer[:2], ("local", "huggingface"))

    def test_starter_question_persists_hidden_profile_answer(self) -> None:
        spec = cli_main_impl._STARTER_QUESTIONS[0]
        selected_choice = tuple(spec["choices_zh"])[0]
        selected = selected_choice[0]
        with mock.patch.object(cli_main_impl, "_wizard_choice_prompt", return_value=selected):
            answer = cli_main_impl._prompt_starter_question("zh", spec)

        self.assertIsNotNone(answer)
        assert answer is not None
        self.assertEqual(answer[0], "inner_landscape")
        self.assertEqual(answer[2], selected_choice[4])
        self.assertIn("视野未打开", answer[2])
        self.assertNotIn("当被问到", answer[2])
        self.assertNotIn("用户", answer[2])
        self.assertNotIn("用户选择", answer[2])
        self.assertNotIn("画像含义", answer[2])
        self.assertNotIn("也许可以先陪你确认脚下", answer[2])
        self.assertNotEqual(answer[2], selected)

        selected_choice_en = tuple(spec["choices_en"])[0]
        with mock.patch.object(cli_main_impl, "_wizard_choice_prompt", return_value=selected_choice_en[0]):
            answer_en = cli_main_impl._prompt_starter_question("en", spec)

        self.assertIsNotNone(answer_en)
        assert answer_en is not None
        self.assertEqual(answer_en[2], selected_choice_en[4])
        self.assertIn("visibility and direction", answer_en[2])
        self.assertNotIn("Not lost", answer_en[2])

    def test_mbti_choices_and_pm_entry_use_chinese_descriptions(self) -> None:
        intj_choice = next(choice for choice in cli_main_impl._mbti_choices("zh") if choice[0] == "INTJ")
        self.assertIn("架构师", intj_choice[2])
        self.assertNotIn("Architect", intj_choice[2])

        entries = cli_main_impl._learned_init_entries("zh", SimpleNamespace(mbti="INTJ", starter_answers=()))
        mbti_entry = next(content for content, metadata in entries if metadata.get("field") == "mbti")
        self.assertIn("MBTI：INTJ；特征参考：架构师", mbti_entry)

    def test_starter_questions_cover_distinct_foundation_dimensions(self) -> None:
        dimensions = {str(spec["id"]) for spec in cli_main_impl._STARTER_QUESTIONS}
        self.assertEqual(
            dimensions,
            {
                "inner_landscape",
                "value_anchor",
                "pressure_pattern",
                "recovery_style",
                "decision_compass",
            },
        )


class CliStatusDoctorTest(unittest.TestCase):
    def _runtime(self) -> mock.Mock:
        runtime = mock.Mock()
        runtime.provider_doctor.return_value = {
            "status": "ready",
            "provider": {
                "provider_id": "openai-compatible",
                "source": "configured",
                "model_id": "openai/gpt-4o-mini",
                "embedding_bootstrap_status": "ready",
            },
            "checks": (),
            "probe_summary": "",
        }
        runtime.security_doctor.return_value = {"status": "ready", "checks": ()}
        runtime.list_herd.return_value = ()
        runtime.embedding_provider_summary.return_value = {}
        return runtime

    def test_print_doctor_defaults_to_shallow_provider_check(self) -> None:
        runtime = self._runtime()

        with mock.patch.object(cli_elephant_support, "_print_cli_card"):
            cli_elephant_support._print_doctor(runtime)

        runtime.provider_doctor.assert_called_once_with(deep=False)

    def test_print_doctor_can_run_deep_provider_check(self) -> None:
        runtime = self._runtime()
        runtime.provider_doctor.return_value["probe_summary"] = "Doctor check"

        with mock.patch.object(cli_elephant_support, "_print_cli_card"):
            cli_elephant_support._print_doctor(runtime, deep=True)

        runtime.provider_doctor.assert_called_once_with(deep=True)


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

    def test_wizard_choice_fragments_render_without_blank_lines_between_options(self) -> None:
        choices = (
            WizardChoice(value="companion", label="Companion", detail="Steady and present.", emoji="🤝"),
            WizardChoice(value="operator", label="Operator", detail="Direct and durable.", emoji="🛠️"),
        )

        text = "".join(fragment for _, fragment in _wizard_choice_fragments("Choose", "Prompt", choices, selected=0))

        self.assertIn("› 🤝  Companion\n  Steady and present.\n  🛠️  Operator\n  Direct and durable.\n", text)
        self.assertNotIn("Steady and present.\n\n  Operator", text)
        self.assertIn("Enter confirms", text)

    def test_wizard_choice_fragments_show_scroll_hints_for_hidden_provider_rows(self) -> None:
        choices = tuple(
            WizardChoice(
                value=f"provider-{index}",
                label=f"Provider {index}",
                detail=f"Catalog summary {index}",
                emoji="🧠",
            )
            for index in range(12)
        )

        text = "".join(fragment for _, fragment in _wizard_choice_fragments("Choose", "Prompt", choices, selected=6))

        self.assertIn("↑ 2 more above", text)
        self.assertIn("↓ 1 more below", text)
        self.assertNotIn("Provider 0", text)
        self.assertIn("Provider 2", text)
        self.assertIn("Provider 10", text)
        self.assertNotIn("Provider 11", text)

    def test_wizard_choice_fragments_show_back_hint_when_allowed(self) -> None:
        choices = (
            WizardChoice(value="companion", label="Companion", detail="Steady and present.", emoji="🤝"),
            WizardChoice(value="operator", label="Operator", detail="Direct and durable.", emoji="🛠️"),
        )

        text = "".join(
            fragment
            for _, fragment in _wizard_choice_fragments("Choose", "Prompt", choices, selected=0, allow_back=True)
        )

        self.assertIn("Enter confirms · Esc cancels · ↑/↓ or j/k moves", text)

    def test_wizard_choice_menu_uses_centered_dialog_application(self) -> None:
        choices = (
            WizardChoice(value="companion", label="Companion", detail="Steady and present.", emoji="🤝"),
            WizardChoice(value="operator", label="Operator", detail="Direct and durable.", emoji="🛠️"),
        )
        captured: dict[str, object] = {}

        class _FakeApplication:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def run(self):
                return "operator"

        with _patch_choice_menu_dependencies(_FakeApplication):
            answer = _wizard_choice_menu("Choose", "Prompt", choices, default="companion")

        self.assertEqual(answer, "operator")
        self.assertTrue(captured["full_screen"])
        self.assertTrue(captured["mouse_support"])

    def test_wizard_choice_menu_runs_dialog_in_thread_when_loop_is_active(self) -> None:
        choices = (
            WizardChoice(value="companion", label="Companion", detail="Steady and present.", emoji="🤝"),
            WizardChoice(value="operator", label="Operator", detail="Direct and durable.", emoji="🛠️"),
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
            mock.patch.object(cli_wizard, "_wizard_asyncio_loop_running", return_value=True),
        ):
            answer = _wizard_choice_menu("Choose", "Prompt", choices, default="companion")

        self.assertEqual(answer, "operator")
        self.assertTrue(captured["in_thread"])

    def test_wizard_choice_menu_uses_single_line_radio_entries_for_mouse_safety(self) -> None:
        choices = (
            WizardChoice(value="companion", label="Companion", detail="Steady and present.", emoji="🤝"),
            WizardChoice(value="operator", label="Operator", detail="Direct and durable.", emoji="🛠️"),
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

        with _patch_choice_menu_dependencies(_FakeApplication, radio_list_cls=_CapturingRadioList):
            answer = _wizard_choice_menu("Choose", "Prompt", choices, default="companion")

        self.assertEqual(answer, "operator")
        first_value = captured["values"][0][1]
        rendered = "".join(fragment for _, fragment in first_value)
        self.assertNotIn("\n", rendered)
        self.assertIn("Steady and present.", rendered)

    def test_wizard_choice_menu_can_return_back_signal(self) -> None:
        choices = (
            WizardChoice(value="companion", label="Companion", detail="Steady and present.", emoji="🤝"),
            WizardChoice(value="operator", label="Operator", detail="Direct and durable.", emoji="🛠️"),
        )

        class _FakeApplication:
            def __init__(self, **_kwargs):
                pass

            def run(self):
                return WIZARD_BACK

        with _patch_choice_menu_dependencies(_FakeApplication):
            answer = _wizard_choice_menu("Choose", "Prompt", choices, default="companion", allow_back=True)

        self.assertIs(answer, WIZARD_BACK)

    def test_wizard_choice_menu_cancel_never_falls_back_to_default(self) -> None:
        choices = (
            WizardChoice(value="companion", label="Companion", detail="Steady and present.", emoji="🤝"),
            WizardChoice(value="operator", label="Operator", detail="Direct and durable.", emoji="🛠️"),
        )

        class _FakeApplication:
            def __init__(self, **_kwargs):
                pass

            def run(self):
                return WIZARD_BACK

        with _patch_choice_menu_dependencies(_FakeApplication):
            answer = _wizard_choice_menu("Choose", "Prompt", choices, default="companion")

        self.assertIs(answer, WIZARD_BACK)

    def test_wizard_choice_menu_binds_enter_eagerly_for_continue(self) -> None:
        choices = (
            WizardChoice(value="companion", label="Companion", detail="Steady and present.", emoji="🤝"),
            WizardChoice(value="operator", label="Operator", detail="Direct and durable.", emoji="🛠️"),
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

        with _patch_choice_menu_dependencies(_FakeApplication, bindings_cls=_FakeBindings):
            answer = _wizard_choice_menu("Choose", "Prompt", choices, default="companion")

        self.assertEqual(answer, "operator")
        enter_call = next((kwargs for keys, kwargs in binding_calls if keys == ("enter",)), None)
        self.assertIsNotNone(enter_call)
        self.assertTrue(enter_call["eager"])

    def test_wizard_dual_choice_menu_uses_only_continue_and_back_buttons(self) -> None:
        choices = (
            WizardChoice(value="gpt-5.4", label="gpt-5.4", detail="Large lane"),
            WizardChoice(value="gpt-5.4-mini", label="gpt-5.4-mini", detail="Small lane"),
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

    def test_wizard_dual_choice_menu_binds_space_and_delete_for_selection_flow(self) -> None:
        choices = (
            WizardChoice(value="gpt-5.4", label="gpt-5.4", detail="Large lane"),
            WizardChoice(value="gpt-5.4-mini", label="gpt-5.4-mini", detail="Small lane"),
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

        with _patch_choice_menu_dependencies(_FakeApplication, bindings_cls=_FakeBindings):
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

    def test_wizard_dual_choice_menu_space_accepts_when_complete_off_radio(self) -> None:
        choices = (
            WizardChoice(value="gpt-5.4", label="gpt-5.4", detail="Large lane"),
            WizardChoice(value="gpt-5.4-mini", label="gpt-5.4-mini", detail="Small lane"),
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

        with _patch_choice_menu_dependencies(_FakeApplication, bindings_cls=_FakeBindings) as fake_app:
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
            answer = _wizard_info_dialog("Setup", "Intro body", continue_text="Start setup")

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
            answer = _wizard_info_dialog("Setup", "Intro body", continue_text="Start setup")

        self.assertFalse(answer)

    def test_wizard_text_prompt_uses_back_button_for_born_flow(self) -> None:
        dialog = mock.Mock()
        dialog.run.return_value = None

        with (
            mock.patch.object(cli_wizard, "_wizard_dialogs_supported", return_value=True),
            mock.patch.object(cli_wizard, "input_dialog", return_value=dialog) as input_dialog_mock,
            mock.patch.object(cli_wizard, "_wizard_style", return_value=None),
        ):
            answer = _wizard_text_prompt("Choose", "Prompt", default="Aeon", allow_back=True)

        self.assertIs(answer, WIZARD_BACK)
        self.assertEqual(input_dialog_mock.call_args.kwargs["ok_text"], "Continue")
        self.assertEqual(input_dialog_mock.call_args.kwargs["cancel_text"], "Back")

    def test_wizard_text_prompt_uses_back_button_even_without_previous_step(self) -> None:
        dialog = mock.Mock()
        dialog.run.return_value = None

        with (
            mock.patch.object(cli_wizard, "_wizard_dialogs_supported", return_value=True),
            mock.patch.object(cli_wizard, "input_dialog", return_value=dialog) as input_dialog_mock,
            mock.patch.object(cli_wizard, "_wizard_style", return_value=None),
        ):
            answer = _wizard_text_prompt("Choose", "Prompt", default="Nova")

        self.assertIs(answer, WIZARD_BACK)
        self.assertEqual(input_dialog_mock.call_args.kwargs["ok_text"], "Continue")
        self.assertEqual(input_dialog_mock.call_args.kwargs["cancel_text"], "Back")

    def test_wizard_text_prompt_uses_required_dialog_when_validation_copy_is_needed(self) -> None:
        with (
            mock.patch.object(cli_wizard, "_wizard_dialogs_supported", return_value=True),
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
            mock.patch.object(cli_wizard, "_wizard_dialogs_supported", return_value=True),
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

    def test_wizard_text_prompt_runs_input_dialog_in_thread_when_loop_is_active(self) -> None:
        captured: dict[str, object] = {}

        class _FakeDialog:
            def run(self, **kwargs):
                captured.update(kwargs)
                return "Aeon"

        with (
            mock.patch.object(cli_wizard, "_wizard_dialogs_supported", return_value=True),
            mock.patch.object(cli_wizard, "input_dialog", return_value=_FakeDialog()),
            mock.patch.object(cli_wizard, "_wizard_style", return_value=None),
            mock.patch.object(cli_wizard, "_wizard_asyncio_loop_running", return_value=True),
        ):
            answer = _wizard_text_prompt("Choose", "Prompt", default="Nova")

        self.assertEqual(answer, "Aeon")
        self.assertTrue(captured["in_thread"])

    def test_wizard_choice_label_prefixes_emoji_when_present(self) -> None:
        self.assertEqual(
            _wizard_choice_label(WizardChoice(value="companion", label="Companion", detail="Steady", emoji="🤝")),
            "🤝  Companion",
        )
        self.assertEqual(
            _wizard_choice_label(WizardChoice(value="plain", label="Plain", detail="Simple")),
            "Plain",
        )

    def test_provider_choices_use_plain_labels_and_brand_accent_detail(self) -> None:
        runtime = mock.Mock()
        runtime.provider_inventory.return_value = (
            SimpleNamespace(provider_id="openai-compatible", display_name="OpenAI-compatible", status="requires-setup", source="none", runtime_enabled=True),
            SimpleNamespace(provider_id="moonshot", display_name="Moonshot Kimi", status="requires-setup", source="none", runtime_enabled=True),
            SimpleNamespace(provider_id="unknown-provider", display_name="Custom", status="requires-setup", source="none", runtime_enabled=True),
        )

        providers = _provider_choices(runtime)

        self.assertEqual([choice.emoji for choice in providers], ["", "", ""])
        self.assertEqual([choice.detail_style for choice in providers], ["accent-detail", "accent-detail", "accent-detail"])

    def test_build_parser_registers_brain_surface(self) -> None:
        parser = cli_main.build_parser()

        args = parser.parse_args(
            [
                "--state-dir",
                "/tmp/state",
                "--profile-dir",
                "/tmp/profile",
                "provider",
                "status",
            ]
        )

        self.assertEqual(args.command, "provider")
        self.assertEqual(args.provider_command, "status")

    def test_build_parser_registers_elephant_use_surface(self) -> None:
        parser = cli_main.build_parser()

        args = parser.parse_args(
            [
                "--state-dir",
                "/tmp/state",
                "--profile-dir",
                "/tmp/profile",
                "herd",
                "use",
                "atlas",
            ]
        )

        self.assertEqual(args.command, "herd")
        self.assertEqual(args.herd_command, "use")
        self.assertEqual(args.elephant_id, "atlas")

    def test_build_parser_registers_embedding_provider_surface(self) -> None:
        parser = cli_main.build_parser()

        args = parser.parse_args(
            [
                "--state-dir",
                "/tmp/state",
                "--profile-dir",
                "/tmp/profile",
                "provider",
                "embeddings",
                "status",
            ]
        )

        self.assertEqual(args.command, "provider")
        self.assertEqual(args.provider_command, "embeddings")
        self.assertEqual(args.embedding_command, "status")

    def test_build_parser_rejects_removed_provider_split_model_flags(self) -> None:
        parser = cli_main.build_parser()

        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "--state-dir",
                    "/tmp/state",
                    "--profile-dir",
                    "/tmp/profile",
                    "provider",
                    "--weak-model",
                    "openai/gpt-4o-mini",
                ]
            )

        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "--state-dir",
                    "/tmp/state",
                    "--profile-dir",
                    "/tmp/profile",
                    "provider",
                    "--intent-mode",
                    "embedded",
                ]
            )

    def test_build_parser_rejects_removed_wake_voice_and_session_flags(self) -> None:
        parser = cli_main.build_parser()

        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "--state-dir",
                    "/tmp/state",
                    "--profile-dir",
                    "/tmp/profile",
                    "wake",
                    "--session-id",
                    "session-demo",
                ]
            )

        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "--state-dir",
                    "/tmp/state",
                    "--profile-dir",
                    "/tmp/profile",
                    "wake",
                    "--voice-input-file",
                    "/tmp/input.wav",
                ]
            )

    def test_run_herd_routes_current_surface(self) -> None:
        runtime = mock.Mock()
        args = SimpleNamespace(herd_command="current")

        with mock.patch.object(cli_main, "_print_current_elephant") as print_current_elephant:
            exit_code = cli_main._run_herd(runtime, args)

        self.assertEqual(exit_code, 0)
        print_current_elephant.assert_called_once_with(runtime)

    def test_run_herd_use_selects_elephant_and_prints_selection(self) -> None:
        runtime = mock.Mock()
        args = SimpleNamespace(herd_command="use", elephant_id="atlas")

        with (
            mock.patch.object(cli_main, "_select_elephant") as select_elephant,
            mock.patch.object(cli_main, "_print_elephant_selected") as print_elephant_selected,
        ):
            exit_code = cli_main._run_herd(runtime, args)

        self.assertEqual(exit_code, 0)
        select_elephant.assert_called_once_with(runtime, "atlas")
        print_elephant_selected.assert_called_once_with(runtime, "atlas")

    def test_run_herd_delete_requires_delete_name_or_all(self) -> None:
        runtime = mock.Mock()
        runtime.list_herd.return_value = ()
        args = SimpleNamespace(herd_command="delete", elephant_id=None, delete_all=False)

        with mock.patch.object(cli_main, "_print_no_elephants") as print_no_elephants:
            exit_code = cli_main._run_herd(runtime, args)

        self.assertEqual(exit_code, 1)
        print_no_elephants.assert_called_once_with()

    def test_run_facts_routes_list_surface(self) -> None:
        runtime = mock.Mock()
        runtime.list_herd.return_value = (mock.Mock(),)
        args = SimpleNamespace(facts_command=None, elephant_id=None)

        with mock.patch.object(cli_main, "_print_fact_list") as print_fact_list:
            exit_code = cli_main._run_facts(runtime, args)

        self.assertEqual(exit_code, 0)
        print_fact_list.assert_called_once_with(runtime, elephant_id=None)

    def test_run_facts_routes_delete_surface(self) -> None:
        runtime = mock.Mock()
        runtime.list_herd.return_value = (mock.Mock(),)
        args = SimpleNamespace(
            facts_command="delete",
            elephant_id="atlas",
            fact_id="evidence.curate:personal_model:test",
            reason="cleanup stale preference",
        )

        with mock.patch.object(cli_main, "_delete_personal_model_fact") as delete_personal_model_fact:
            exit_code = cli_main._run_facts(runtime, args)

        self.assertEqual(exit_code, 0)
        delete_personal_model_fact.assert_called_once_with(
            runtime,
            elephant_id="atlas",
            fact_id="evidence.curate:personal_model:test",
            reason="cleanup stale preference",
        )

    def test_run_brain_routes_embedding_status_surface(self) -> None:
        runtime = mock.Mock()
        args = SimpleNamespace(provider_command="embeddings", embedding_command="status")

        with mock.patch.object(cli_main, "_print_embedding_provider_status") as print_status:
            exit_code = cli_main._run_brain(runtime, args)

        self.assertEqual(exit_code, 0)
        print_status.assert_called_once_with(runtime)

    def test_run_brain_switches_embedding_provider_back_to_local_default(self) -> None:
        runtime = mock.Mock()
        runtime.set_local_embedding_provider.return_value = {
            "source": "local-default",
            "provider_id": "local-elephant",
            "model_id": "elephant-embed",
            "dimensions": 256,
            "embedding_bootstrap_status": "ready",
        }
        args = SimpleNamespace(provider_command="embeddings", embedding_command="local")

        with mock.patch.object(cli_main, "_print_cli_card") as print_card:
            exit_code = cli_main._run_brain(runtime, args)

        self.assertEqual(exit_code, 0)
        runtime.set_local_embedding_provider.assert_called_once_with(source="huggingface")
        print_card.assert_called_once()

    def test_run_brain_configures_openai_compatible_embedding_provider(self) -> None:
        runtime = mock.Mock()
        runtime.set_openai_compatible_embedding_provider.return_value = {
            "source": "configured",
            "provider_id": "openai-compatible-embed",
            "model_id": "text-embedding-3-large",
            "dimensions": 1536,
            "base_url": "https://api.example.test/v1",
            "secret_status": "stored",
        }
        args = SimpleNamespace(
            provider_command="embeddings",
            embedding_command="openai-compatible",
            base_url="https://api.example.test/v1",
            embedding_model="text-embedding-3-large",
            embedding_dimensions="1536",
            api_key="sk-embed-test",
            secret_env_var="OPENAI_API_KEY",
        )

        with mock.patch.object(cli_main, "_print_cli_card") as print_card:
            exit_code = cli_main._run_brain(runtime, args)

        self.assertEqual(exit_code, 0)
        runtime.set_openai_compatible_embedding_provider.assert_called_once_with(
            base_url="https://api.example.test/v1",
            model_id="text-embedding-3-large",
            dimensions=1536,
            api_key="sk-embed-test",
            secret_env_var="OPENAI_API_KEY",
        )
        print_card.assert_called_once()

    def test_run_brain_interactive_provider_state_is_not_compared_as_hashable_signal(self) -> None:
        runtime = mock.Mock()
        profile_state = SimpleNamespace(profile_id="profile-default", display_name="Atlas", mode="companion")
        runtime.current_profile.return_value = SimpleNamespace(state=profile_state)
        runtime.provider_summary.return_value = {}
        runtime.provider_setup_guide.return_value = SimpleNamespace(
            auth_type="api_key",
            required_secret_keys=(),
            required_config_keys=(),
        )
        configured = cli_main.ProviderSelectionState(
            provider_id="openai-compatible",
            base_url="https://api.example.test/v1",
            api_key=None,
            model_id="model-a",
            reasoning_effort="medium",
            context_window_mode="manual",
            context_window_tokens=128000,
        )
        args = SimpleNamespace(
            provider_command="configure",
            provider_id=None,
            base_url=None,
            model_id=None,
            api_key=None,
            reasoning_effort=None,
            context_window_mode=None,
            context_window=None,
            non_interactive=False,
        )

        with (
            mock.patch.object(cli_main, "_interactive_shell_supported", return_value=True),
            mock.patch.object(cli_main, "provider_setup_defaults", return_value=configured),
            mock.patch.object(cli_main, "run_provider_selection_wizard", return_value=configured),
            mock.patch.object(cli_main, "_print_cli_card"),
        ):
            exit_code = cli_main._run_brain(runtime, args)

        self.assertEqual(exit_code, 0)
        runtime.set_default_provider.assert_called_once()

    def test_suggest_elephant_name_skips_existing_elephant_ids_when_possible(self) -> None:
        runtime = mock.Mock()
        runtime.latest_session_for_elephant.side_effect = lambda elephant_id: object() if elephant_id == "ada" else None
        captured: dict[str, tuple[str, ...]] = {}

        def _pick(options):
            captured["options"] = tuple(options)
            return options[0]

        with mock.patch.object(cli_main.random, "choice", side_effect=_pick):
            suggested = cli_main._suggest_elephant_name(runtime)

        self.assertEqual(suggested, captured["options"][0])
        self.assertNotIn("Ada", captured["options"])

    def test_run_setup_uses_random_name_suggestion_when_no_initial_name_is_given(self) -> None:
        runtime = mock.Mock()
        runtime.current_profile.return_value = SimpleNamespace(
            state=SimpleNamespace(display_name="Elephant Agent"),
            companion=SimpleNamespace(personality_preset="companion", initiative="gentle"),
        )
        runtime.provider_setup_guide.return_value = SimpleNamespace(
            suggested_base_url="https://api.example.com/v1",
            suggested_model_id="openai/gpt-4o-mini",
            required_secret_keys=("api_key",),
        )
        runtime.provider_summary.return_value = {
            "base_url": "",
            "model_id": "",
        }
        args = SimpleNamespace(
            provider_id="openai-compatible",
            elephant_name=None,
            display_name=None,
            elephant_identity_text=None,
            base_url=None,
            model_id=None,
            api_key=None,
            context_window_mode=None,
            context_window=None,
            non_interactive=False,
        )

        with (
            mock.patch.object(cli_main, "_interactive_shell_supported", return_value=True),
            mock.patch.object(cli_main, "_print_birth_wizard_intro"),
            mock.patch.object(cli_main, "_suggest_elephant_name", return_value="Rowan"),
            mock.patch.object(cli_main, "_run_interactive_birth_wizard", return_value=None) as birth_wizard,
            mock.patch.object(cli_main, "_print_birth_paused"),
        ):
            exit_code = cli_main._run_setup(runtime, args)

        self.assertEqual(exit_code, 0)
        self.assertEqual(birth_wizard.call_args.kwargs["display_name"], "Rowan")

    def test_run_setup_allows_oauth_provider_without_explicit_key(self) -> None:
        runtime = mock.Mock()
        runtime.current_profile.return_value = SimpleNamespace(
            state=SimpleNamespace(profile_id="profile-companion", display_name="Elephant Agent", mode="companion"),
            companion=SimpleNamespace(personality_preset="companion", initiative="gentle"),
        )
        runtime.provider_setup_guide.return_value = SimpleNamespace(
            auth_type="oauth_external",
            required_secret_keys=("api_key",),
        )
        runtime.detect_provider_context_window.return_value = 128000
        updated_profile = SimpleNamespace(
            state=SimpleNamespace(profile_id="profile-companion", display_name="Elephant Agent", mode="companion"),
            companion=SimpleNamespace(personality_preset="companion", initiative="gentle"),
        )
        runtime.update_identity.return_value = updated_profile
        runtime.update_companion_settings.return_value = updated_profile
        runtime.update_elephant_identity_text.return_value = updated_profile
        runtime.set_default_provider.return_value = updated_profile
        runtime.provider_doctor.return_value = {
            "status": "ready",
            "provider": {
                "display_name": "OpenAI Codex",
                "model_id": "gpt-5.4",
                "context_window_tokens": 128000,
            },
        }
        runtime.latest_session_for_elephant.return_value = None
        runtime.create_elephant.return_value = SimpleNamespace(session_id="session-1")
        runtime.elephant_id_for_session.return_value = "elephant"

        args = SimpleNamespace(
            provider_id="openai-codex",
            elephant_name=None,
            display_name="Elephant Agent",
            elephant_identity_text=None,
            base_url=None,
            model_id=None,
            api_key=None,
            context_window_mode=None,
            context_window=None,
            non_interactive=True,
        )

        provider_state = cli_main.ProviderSelectionState(
            provider_id="openai-codex",
            base_url="https://chatgpt.com/backend-api/codex",
            api_key=None,
            model_id="gpt-5.4",
            reasoning_effort="medium",
            context_window_mode="auto",
            context_window_tokens=None,
        )

        with (
            mock.patch.object(cli_main, "provider_setup_defaults", return_value=provider_state),
            mock.patch.object(cli_main, "_print_setup_intro"),
        ):
            exit_code = cli_main._run_setup(runtime, args)

        self.assertEqual(exit_code, 0)
        runtime.set_default_provider.assert_called_once()
        self.assertIsNone(runtime.set_default_provider.call_args.kwargs["api_key"])

    def test_interactive_birth_wizard_cancels_when_provider_setup_is_escaped(self) -> None:
        runtime = mock.Mock()
        runtime.personality_presets.return_value = (
            SimpleNamespace(preset_id="companion", label="Companion", summary="Steady."),
        )
        with (
            mock.patch.object(cli_main, "_prompt_first_language", return_value="en"),
            mock.patch.object(cli_main, "_prompt_first_elephant_name", return_value="Aeon"),
            mock.patch.object(cli_main, "_prompt_required_text", side_effect=("Bit", "Engineer")),
            mock.patch.object(cli_main, "_prompt_choice_with_type", return_value=""),
            mock.patch.object(cli_main, "_prompt_birth_date", return_value=""),
            mock.patch.object(cli_main, "_prompt_hobbies", return_value=""),
            mock.patch.object(cli_main, "_prompt_starter_question", return_value=""),
            mock.patch.object(cli_main, "_prompt_optional_text", return_value=""),
            mock.patch.object(cli_main, "run_provider_selection_wizard", return_value=WIZARD_CANCEL),
        ):
            state = _run_interactive_birth_wizard(
                runtime,
                display_name="Aeon",
                provider_state=cli_main.ProviderSelectionState(
                    provider_id="openai-compatible",
                    base_url="https://api.example.com/v1",
                    api_key=None,
                    model_id="openai/gpt-4o-mini",
                    reasoning_effort=None,
                    context_window_mode="auto",
                    context_window_tokens=128000,
                ),
            )

        self.assertIsNone(state)

    def test_prompt_birth_date_accepts_freeform_input(self) -> None:
        with mock.patch.object(cli_main, "_wizard_text_prompt", return_value="spring equinox 1991"):
            answer = cli_main._prompt_birth_date("en")

        self.assertEqual(answer, "spring equinox 1991")

    def test_interactive_elephant_wizard_uses_suggested_name_as_default(self) -> None:
        with mock.patch.object(
            cli_main,
            "_wizard_text_prompt",
            return_value="Nova",
        ) as text_prompt, mock.patch.object(
            cli_main,
            "_suggest_elephant_name",
            return_value="Rowan",
        ):
            state = _run_interactive_elephant_wizard(mock.Mock(), elephant_name=None)

        self.assertEqual(state, "Nova")
        self.assertEqual(text_prompt.call_count, 1)
        self.assertEqual(text_prompt.call_args_list[0].kwargs["default"], "Rowan")

    def test_interactive_elephant_wizard_can_cancel_before_creating_elephant(self) -> None:
        with (
            mock.patch.object(cli_main, "_wizard_text_prompt", return_value=WIZARD_BACK),
            mock.patch.object(cli_main, "_suggest_elephant_name", return_value="Theo") as suggest_name,
        ):
            runtime = mock.Mock()
            state = _run_interactive_elephant_wizard(runtime, elephant_name=None)

        self.assertIsNone(state)
        suggest_name.assert_called_once_with(runtime)

    def test_run_setup_creates_first_elephant_when_non_interactive(self) -> None:
        runtime = mock.Mock()
        runtime.current_profile.return_value = SimpleNamespace(
            state=SimpleNamespace(display_name="Elephant Agent"),
            companion=SimpleNamespace(personality_preset="companion", initiative="gentle"),
        )
        updated_profile = SimpleNamespace(
            state=SimpleNamespace(profile_id="profile-companion", display_name="Elephant Agent", mode="companion"),
            companion=SimpleNamespace(personality_preset="companion", initiative="gentle"),
        )
        runtime.provider_setup_guide.return_value = SimpleNamespace(auth_type="api_key", required_secret_keys=())
        runtime.detect_provider_context_window.return_value = 128000
        runtime.update_identity.return_value = updated_profile
        runtime.update_companion_settings.return_value = updated_profile
        runtime.update_identity_state.return_value = updated_profile
        runtime.set_default_provider.return_value = updated_profile
        runtime.provider_doctor.return_value = {
            "status": "ready",
            "provider": {
                "display_name": "OpenAI-compatible",
                "model_id": "openai/gpt-4o-mini",
                "embedding_bootstrap_status": "ready",
                "context_window_tokens": 128000,
                "provider_id": "openai-compatible",
            },
        }
        runtime.latest_session_for_elephant.return_value = None
        runtime.create_elephant.return_value = SimpleNamespace(episode_id="session-demo")
        runtime.elephant_id_for_session.return_value = "demo"
        args = SimpleNamespace(
            provider_id="openai-compatible",
            elephant_name="demo",
            display_name=None,
            elephant_identity_text=None,
            base_url="https://api.example.com/v1",
            model_id="openai/gpt-4o-mini",
            api_key="sk-cli-test-123",
            context_window_mode=None,
            context_window=None,
            non_interactive=True,
            secret_env_var=None,
        )

        with (
            mock.patch.object(
                cli_main,
                "provider_setup_defaults",
                return_value=cli_main.ProviderSelectionState(
                    provider_id="openai-compatible",
                    base_url="https://api.example.com/v1",
                    api_key="sk-cli-test-123",
                    model_id="openai/gpt-4o-mini",
                    reasoning_effort=None,
                    context_window_mode="auto",
                    context_window_tokens=128000,
                ),
            ),
            mock.patch.object(cli_main, "_print_setup_intro"),
            mock.patch.object(cli_main, "_print_cli_card"),
        ):
            exit_code = cli_main._run_setup(runtime, args)

        self.assertEqual(exit_code, 0)
        runtime.create_elephant.assert_called_once_with(
            elephant_id="demo",
            profile_id="profile-companion",
            display_name="Demo",
            mode="companion",
        )

    def test_run_setup_keeps_raw_birth_date_when_non_interactive(self) -> None:
        runtime = mock.Mock()
        runtime.current_profile.return_value = SimpleNamespace(
            state=SimpleNamespace(display_name="Elephant Agent"),
            companion=SimpleNamespace(personality_preset="companion", initiative="gentle"),
        )
        updated_profile = SimpleNamespace(
            state=SimpleNamespace(profile_id="profile-companion", display_name="Elephant Agent", mode="companion"),
            companion=SimpleNamespace(personality_preset="companion", initiative="gentle"),
        )
        runtime.provider_setup_guide.return_value = SimpleNamespace(auth_type="api_key", required_secret_keys=())
        runtime.detect_provider_context_window.return_value = 128000
        runtime.update_identity.return_value = updated_profile
        runtime.update_companion_settings.return_value = updated_profile
        runtime.update_identity_state.return_value = updated_profile
        runtime.set_default_provider.return_value = updated_profile
        runtime.provider_doctor.return_value = {
            "status": "ready",
            "provider": {
                "display_name": "OpenAI-compatible",
                "model_id": "openai/gpt-4o-mini",
                "embedding_bootstrap_status": "ready",
                "context_window_tokens": 128000,
                "provider_id": "openai-compatible",
            },
        }
        runtime.latest_session_for_elephant.return_value = None
        first_elephant = SimpleNamespace(episode_id="session-demo", personal_model_id="pm-demo")
        runtime.create_elephant.return_value = first_elephant
        runtime.elephant_id_for_session.return_value = "demo"
        args = SimpleNamespace(
            provider_id="openai-compatible",
            elephant_name="demo",
            display_name=None,
            elephant_identity_text=None,
            base_url="https://api.example.com/v1",
            model_id="openai/gpt-4o-mini",
            api_key="sk-cli-test-123",
            context_window_mode=None,
            context_window=None,
            non_interactive=True,
            secret_env_var=None,
            preferred_name=None,
            age=None,
            birth_date="late summer 1991",
            gender=None,
            occupation=None,
            city=None,
            mbti=None,
            hobbies=None,
            relationship_mode=None,
            astrology=None,
            safety_boundaries=None,
            communication_preference=None,
            first_language="en",
            learning_intensity="medium",
            embedding_provider="local",
            embedding_base_url=None,
            embedding_model=None,
            embedding_dimensions=None,
            embedding_api_key=None,
            embedding_secret_env_var=None,
        )

        with (
            mock.patch.object(
                cli_main,
                "provider_setup_defaults",
                return_value=cli_main.ProviderSelectionState(
                    provider_id="openai-compatible",
                    base_url="https://api.example.com/v1",
                    api_key="sk-cli-test-123",
                    model_id="openai/gpt-4o-mini",
                    reasoning_effort=None,
                    context_window_mode="auto",
                    context_window_tokens=128000,
                ),
            ),
            mock.patch.object(cli_main, "_print_setup_intro"),
            mock.patch.object(cli_main, "_print_cli_card"),
            mock.patch.object(cli_main, "_bootstrap_personal_model_from_init") as bootstrap_personal_model,
        ):
            exit_code = cli_main._run_setup(runtime, args)

        self.assertEqual(exit_code, 0)
        self.assertEqual(bootstrap_personal_model.call_args.args[2].birth_date, "late summer 1991")

    def test_init_question_config_persists_proactive_ask_from_learning_intensity(self) -> None:
        runtime = SimpleNamespace(paths=SimpleNamespace(state_dir="/tmp/elephant-test/herd"))
        captured: dict[str, object] = {}

        with (
            mock.patch(
                "packages.runtime_config.global_config_path_for_state_dir",
                return_value=Path("/tmp/elephant-test/config.yaml"),
            ),
            mock.patch(
                "packages.runtime_config.load_global_config",
                return_value={"personal_model_questions": {}},
            ),
            mock.patch(
                "packages.runtime_config.write_global_config",
                side_effect=lambda _path, config: captured.update(config),
            ),
        ):
            cli_main._persist_init_question_config(
                runtime,
                first_language="zh",
                learning_intensity="high",
            )

        questions = captured["personal_model_questions"]
        self.assertEqual(questions["learning_intensity"], "high")
        self.assertEqual(
            questions["proactive_ask"],
            {
                "enabled": True,
                "idle_threshold_minutes": 60,
                "daily_max": 24,
                "quiet_hours": [1, 7],
            },
        )
        self.assertEqual(captured["personal_model"]["first_language"], "zh")

    def test_interactive_setup_uses_shallow_provider_doctor_before_tui_handoff(self) -> None:
        runtime = mock.Mock()
        runtime.current_profile.return_value = SimpleNamespace(
            state=SimpleNamespace(display_name="Elephant Agent"),
            companion=SimpleNamespace(personality_preset="companion", initiative="gentle"),
        )
        updated_profile = SimpleNamespace(
            state=SimpleNamespace(profile_id="profile-companion", display_name="Elephant Agent", mode="companion"),
            companion=SimpleNamespace(personality_preset="companion", initiative="gentle"),
        )
        runtime.provider_setup_guide.return_value = SimpleNamespace(auth_type="api_key", required_secret_keys=())
        runtime.update_identity.return_value = updated_profile
        runtime.update_companion_settings.return_value = updated_profile
        runtime.update_identity_state.return_value = updated_profile
        runtime.set_default_provider.return_value = updated_profile
        runtime.set_local_embedding_provider.return_value = {
            "source": "local-default",
            "model_id": "elephant-embed",
            "embedding_bootstrap_status": "ready",
        }
        runtime.provider_doctor.return_value = {
            "status": "ready",
            "provider": {
                "display_name": "OpenAI-compatible",
                "model_id": "openai/gpt-4o-mini",
                "embedding_bootstrap_status": "ready",
                "context_window_tokens": 128000,
                "provider_id": "openai-compatible",
            },
        }
        first_elephant = SimpleNamespace(
            episode_id="session-demo",
            session_id="session-demo",
            personal_model_id="profile-companion",
        )
        runtime.latest_session_for_elephant.return_value = None
        runtime.create_elephant.return_value = first_elephant
        runtime.elephant_id_for_session.return_value = "demo"
        args = SimpleNamespace(
            provider_id="openai-compatible",
            elephant_name="demo",
            display_name=None,
            elephant_identity_text=None,
            base_url="https://api.example.com/v1",
            model_id="openai/gpt-4o-mini",
            api_key="sk-cli-test-123",
            context_window_mode=None,
            context_window=None,
            non_interactive=False,
            secret_env_var=None,
            embedding_provider="local",
            embedding_base_url=None,
            embedding_model=None,
            embedding_dimensions=None,
            embedding_api_key=None,
            embedding_secret_env_var=None,
            first_language="zh",
            learning_intensity="medium",
            preferred_name=None,
            age=None,
            gender=None,
            occupation=None,
            city=None,
            mbti=None,
            relationship_mode=None,
            astrology=None,
            safety_boundaries=None,
            communication_preference=None,
        )
        wizard_state = cli_main.BirthWizardState(
            display_name="Elephant Agent",
            provider_id="openai-compatible",
            base_url="https://api.example.com/v1",
            model_id="openai/gpt-4o-mini",
            api_key="sk-cli-test-123",
            embedding_provider="local",
            embedding_source="local-default",
            embedding_base_url="",
            embedding_model="",
            embedding_dimensions=None,
            embedding_api_key=None,
            reasoning_effort=None,
            context_window_mode="auto",
            context_window_tokens=128000,
            first_language="zh",
            preferred_name="Bit",
            occupation="在啃一个新问题",
        )
        shell = mock.Mock()
        shell.run.return_value = 0

        with (
            mock.patch.object(cli_main, "_interactive_shell_supported", return_value=True),
            mock.patch.object(cli_main, "_print_birth_wizard_intro"),
            mock.patch.object(cli_main, "_run_interactive_birth_wizard", return_value=wizard_state),
            mock.patch.object(cli_main, "_print_init_section"),
            mock.patch.object(cli_main, "provider_setup_defaults", return_value=cli_main.ProviderSelectionState(
                provider_id="openai-compatible",
                base_url="https://api.example.com/v1",
                api_key="sk-cli-test-123",
                model_id="openai/gpt-4o-mini",
                reasoning_effort=None,
                context_window_mode="auto",
                context_window_tokens=128000,
            )),
            mock.patch.object(cli_main, "_persist_init_question_config"),
            mock.patch.object(cli_main, "_bootstrap_personal_model_from_init"),
            mock.patch.object(cli_main, "_play_creating_transition"),
            mock.patch.object(cli_main, "_prompt_im_onboarding"),
            mock.patch.object(cli_main, "ProductizedShell", return_value=shell),
        ):
            exit_code = cli_main._run_setup(runtime, args)

        self.assertEqual(exit_code, 0)
        runtime.provider_doctor.assert_called_once_with(deep=False)
        shell.run.assert_called_once_with()

    def test_run_elephant_creates_state_without_current_work_seed(self) -> None:
        runtime = mock.Mock()
        runtime.provider_doctor.return_value = {"status": "ready"}
        runtime.create_elephant.return_value = SimpleNamespace(episode_id="session-nova")
        args = SimpleNamespace(
            elephant_name="nova",
            display_name=None,
            profile_id=None,
            debug=False,
            message=None,
        )

        with (
            mock.patch.object(cli_main, "_interactive_shell_supported", return_value=False),
            mock.patch.object(cli_main, "_unique_elephant_name", return_value="nova"),
        ):
            exit_code = cli_main._run_elephant(runtime, args)

        self.assertEqual(exit_code, 0)
        runtime.create_elephant.assert_called_once_with(
            elephant_id="nova",
            profile_id=None,
            display_name="Nova",
            mode="companion",
        )

    def test_run_elephant_does_not_open_wizard_when_name_is_preselected(self) -> None:
        runtime = mock.Mock()
        runtime.provider_doctor.return_value = {"status": "ready"}
        runtime.create_elephant.return_value = SimpleNamespace(episode_id="session-nova")
        shell = mock.Mock()
        shell.run.return_value = 0
        args = SimpleNamespace(
            elephant_name="nova",
            display_name=None,
            profile_id=None,
            debug=False,
            message=None,
        )

        with (
            mock.patch.object(cli_main, "_interactive_shell_supported", return_value=True),
            mock.patch.object(cli_main, "_run_interactive_elephant_wizard") as wizard,
            mock.patch.object(cli_main, "_unique_elephant_name", return_value="nova"),
            mock.patch.object(cli_main, "ProductizedShell", return_value=shell),
        ):
            exit_code = cli_main._run_elephant(runtime, args)

        self.assertEqual(exit_code, 0)
        wizard.assert_not_called()
        runtime.prepare_session_surface.assert_not_called()
        runtime.create_elephant.assert_called_once_with(
            elephant_id="nova",
            profile_id=None,
            display_name="Nova",
            mode="companion",
        )

    def test_run_grow_defers_surface_prepare_until_after_interactive_shell_boot(self) -> None:
        runtime = mock.Mock()
        runtime.provider_doctor.return_value = {"status": "ready"}
        shell = mock.Mock()
        shell.run.return_value = 0
        args = SimpleNamespace(
            message=None,
            elephant_id=None,
            debug=False,
        )

        with (
            mock.patch.object(cli_main, "_open_growth_episode", return_value=("episode-atlas", "Opened elephant atlas")),
            mock.patch.object(cli_main, "_interactive_shell_supported", return_value=True),
            mock.patch.object(cli_main, "ProductizedShell", return_value=shell) as productized_shell,
        ):
            exit_code = cli_main._run_grow(runtime, args)

        self.assertEqual(exit_code, 0)
        runtime.prepare_session_surface.assert_not_called()
        productized_shell.assert_called_once_with(
            runtime,
            session_id="episode-atlas",
            opened="Opened elephant atlas",
            debug=False,
        )

    def test_open_growth_episode_opens_next_episode_for_open_elephant(self) -> None:
        runtime = mock.Mock()
        runtime.latest_session_for_elephant.return_value = SimpleNamespace(episode_id="episode-parent", status="open", exit_summary="")
        runtime.open_next_episode.return_value = SimpleNamespace(episode=SimpleNamespace(episode_id="episode-child", status="open"))

        episode_id, opened = cli_main._open_growth_episode(runtime, elephant_id="atlas")

        self.assertEqual(episode_id, "episode-child")
        self.assertEqual(opened, "Opened elephant atlas")
        runtime.open_next_episode.assert_called_once_with("episode-parent", reason="wake_boundary", summary="")

    def test_open_growth_episode_opens_next_episode_for_closed_elephant(self) -> None:
        runtime = mock.Mock()
        runtime.latest_session_for_elephant.return_value = SimpleNamespace(episode_id="episode-parent", status="closed", exit_summary="parent handoff")
        runtime.open_next_episode.return_value = SimpleNamespace(episode=SimpleNamespace(episode_id="episode-child", status="open"))

        episode_id, opened = cli_main._open_growth_episode(runtime, elephant_id="atlas")

        self.assertEqual(episode_id, "episode-child")
        self.assertEqual(opened, "Opened elephant atlas")
        runtime.open_next_episode.assert_called_once_with("episode-parent", reason="wake_boundary", summary="parent handoff")

    def test_resolve_growth_session_prefers_current_elephant_snapshot_when_multiple_prompting_is_disabled(self) -> None:
        runtime = mock.Mock()
        runtime.elephant_id_for_session.return_value = "atlas"
        runtime.list_herd.return_value = (
            SimpleNamespace(elephant_id="atlas", latest_session_id="episode-atlas", session_count=1, latest_status="open"),
            SimpleNamespace(elephant_id="beta", latest_session_id="episode-beta", session_count=1, latest_status="open"),
        )
        current_session = SimpleNamespace(episode_id="episode-current", elephant_id="atlas", status="open", exit_summary="")
        runtime.open_next_episode.return_value = SimpleNamespace(episode=SimpleNamespace(episode_id="episode-next", status="open"))

        with mock.patch.object(cli_elephant_support, "_current_elephant_session", return_value=current_session):
            episode_id, opened = cli_main._open_growth_episode(runtime, prompt_for_multiple=False)

        self.assertEqual(episode_id, "episode-next")
        self.assertEqual(opened, "Opened elephant atlas")
        runtime.open_next_episode.assert_called_once_with("episode-current", reason="wake_boundary", summary="")

    def test_resolve_growth_session_prompts_for_multiple_elephants_in_interactive_mode(self) -> None:
        runtime = mock.Mock()
        runtime.list_herd.return_value = (
            SimpleNamespace(elephant_id="atlas", latest_session_id="episode-atlas", session_count=2, latest_status="open"),
            SimpleNamespace(elephant_id="beta", latest_session_id="episode-beta", session_count=3, latest_status="open"),
        )
        runtime.elephant_id_for_session.return_value = "atlas"
        runtime.inspect_session.return_value = SimpleNamespace(episode_id="episode-beta", status="open", exit_summary="")
        runtime.open_next_episode.return_value = SimpleNamespace(episode=SimpleNamespace(episode_id="episode-beta-next", status="open"))
        current_session = SimpleNamespace(episode_id="episode-current", elephant_id="atlas", status="open")
        selected_elephant = runtime.list_herd.return_value[1]

        with (
            mock.patch.object(cli_elephant_support, "_current_elephant_session", return_value=current_session),
            mock.patch.object(cli_elephant_support, "_prompt_elephant_choice", return_value=selected_elephant) as prompt_elephant_choice,
        ):
            episode_id, opened = cli_main._open_growth_episode(runtime, prompt_for_multiple=True)

        self.assertEqual(episode_id, "episode-beta-next")
        self.assertEqual(opened, "Opened elephant beta")
        prompt_elephant_choice.assert_called_once_with(
            runtime,
            runtime.list_herd.return_value,
            preferred_elephant_id="atlas",
        )
        runtime.inspect_session.assert_called_once_with("episode-beta")
        runtime.schedule_learning_for_session.assert_not_called()

    def test_resolve_growth_session_does_not_queue_boundary_learning_when_opening_different_elephant(self) -> None:
        runtime = mock.Mock()
        runtime.latest_session_for_elephant.return_value = SimpleNamespace(episode_id="episode-beta", status="open", exit_summary="")
        runtime.open_next_episode.return_value = SimpleNamespace(episode=SimpleNamespace(episode_id="episode-beta-next", status="open"))
        current_session = SimpleNamespace(episode_id="episode-atlas", elephant_id="atlas", status="open")
        runtime.elephant_id_for_session.return_value = "atlas"

        with mock.patch.object(cli_elephant_support, "_current_elephant_session", return_value=current_session):
            episode_id, opened = cli_main._open_growth_episode(runtime, elephant_id="beta")

        self.assertEqual(episode_id, "episode-beta-next")
        self.assertEqual(opened, "Opened elephant beta")
        runtime.schedule_learning_for_session.assert_not_called()


if __name__ == "__main__":
    unittest
