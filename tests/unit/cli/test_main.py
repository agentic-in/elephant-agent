from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

import apps.cli.cli_main_elephant_support as cli_elephant_support
import apps.cli.cli_main_impl as cli_main_impl
import apps.cli.cli_main_setup as cli_main_setup
import apps.cli.cli_main_support as cli_main_support


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

    def test_prompt_im_onboarding_uses_gateway_command_boundary(self) -> None:
        runtime = SimpleNamespace(paths=SimpleNamespace(state_dir=Path("/tmp/elephant-state")))

        with mock.patch.object(cli_main_setup.subprocess, "run") as run:
            cli_main_setup._prompt_im_onboarding(runtime, elephant_name="Ada")

        command = run.call_args.args[0]
        self.assertEqual(command[:4], (cli_main_setup.sys.executable, "-m", "apps.gateway", "setup"))
        self.assertIn("--allow-skip", command)
        self.assertIn("--state-dir", command)
        self.assertIn(str(runtime.paths.state_dir), command)
        run.assert_called_once_with(command, check=False)

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




if __name__ == "__main__":
    unittest
