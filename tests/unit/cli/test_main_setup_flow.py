from __future__ import annotations

from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest import mock

import apps.cli.__main__ as cli_main
import apps.cli.cli_main_elephant_support as cli_elephant_support
import apps.cli.cli_main_impl as cli_main_impl
import apps.cli.cli_main_setup as cli_main_setup
import apps.cli.cli_main_support as cli_main_support
from apps.cli.__main__ import (
    _provider_choices,
    _run_interactive_birth_wizard,
    _run_interactive_elephant_wizard,
)
from apps.cli.wizard import WIZARD_BACK, WIZARD_CANCEL


class CliMainSetupFlowTest(unittest.TestCase):
    def test_run_setup_defaults_first_elephant_to_mother_when_no_initial_name_is_given(
        self,
    ) -> None:
        runtime = mock.Mock()
        runtime.current_profile.return_value = SimpleNamespace(
            state=SimpleNamespace(display_name="Elephant Agent"),
            companion=SimpleNamespace(
                personality_preset="companion", initiative="gentle"
            ),
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
            mock.patch.object(
                cli_main, "_interactive_shell_supported", return_value=True
            ),
            mock.patch.object(cli_main, "_print_birth_wizard_intro"),
            mock.patch.object(
                cli_main, "_suggest_elephant_name", return_value="Rowan"
            ) as suggest_name,
            mock.patch.object(
                cli_main, "_run_interactive_birth_wizard", return_value=None
            ) as birth_wizard,
            mock.patch.object(cli_main, "_print_birth_paused"),
        ):
            exit_code = cli_main._run_setup(runtime, args)

        self.assertEqual(exit_code, 0)
        suggest_name.assert_not_called()
        self.assertEqual(
            birth_wizard.call_args.kwargs["display_name"], "Mother Elephant"
        )

    def test_run_setup_allows_oauth_provider_without_explicit_key(self) -> None:
        runtime = mock.Mock()
        runtime.current_profile.return_value = SimpleNamespace(
            state=SimpleNamespace(
                profile_id="profile-companion",
                display_name="Elephant Agent",
                mode="companion",
            ),
            companion=SimpleNamespace(
                personality_preset="companion", initiative="gentle"
            ),
        )
        runtime.provider_setup_guide.return_value = SimpleNamespace(
            auth_type="oauth_external",
            required_secret_keys=("api_key",),
        )
        runtime.detect_provider_context_window.return_value = 128000
        updated_profile = SimpleNamespace(
            state=SimpleNamespace(
                profile_id="profile-companion",
                display_name="Elephant Agent",
                mode="companion",
            ),
            companion=SimpleNamespace(
                personality_preset="companion", initiative="gentle"
            ),
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
            mock.patch.object(
                cli_main, "provider_setup_defaults", return_value=provider_state
            ),
            mock.patch.object(cli_main, "_print_setup_intro"),
        ):
            exit_code = cli_main._run_setup(runtime, args)

        self.assertEqual(exit_code, 0)
        runtime.set_default_provider.assert_called_once()
        self.assertIsNone(runtime.set_default_provider.call_args.kwargs["api_key"])

    def test_interactive_birth_wizard_cancels_when_provider_setup_is_escaped(
        self,
    ) -> None:
        runtime = mock.Mock()
        runtime.personality_presets.return_value = (
            SimpleNamespace(
                preset_id="companion", label="Companion", summary="Steady."
            ),
        )
        with (
            mock.patch.object(cli_main, "_prompt_first_language", return_value="en"),
            mock.patch.object(
                cli_main, "_prompt_first_elephant_name", return_value="Aeon"
            ),
            mock.patch.object(
                cli_main, "_prompt_required_text", side_effect=("Bit", "Engineer")
            ),
            mock.patch.object(cli_main, "_prompt_choice_with_type", return_value=""),
            mock.patch.object(cli_main, "_prompt_birth_date", return_value=""),
            mock.patch.object(cli_main, "_prompt_hobbies", return_value=""),
            mock.patch.object(cli_main, "_prompt_starter_question", return_value=""),
            mock.patch.object(cli_main, "_prompt_optional_text", return_value=""),
            mock.patch.object(
                cli_main, "run_provider_selection_wizard", return_value=WIZARD_CANCEL
            ),
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
        with mock.patch.object(
            cli_main, "_wizard_text_prompt", return_value="spring equinox 1991"
        ):
            answer = cli_main._prompt_birth_date("en")

        self.assertEqual(answer, "spring equinox 1991")

    def test_interactive_elephant_wizard_uses_suggested_name_as_default(self) -> None:
        with (
            mock.patch.object(
                cli_main,
                "_wizard_text_prompt",
                return_value="Nova",
            ) as text_prompt,
            mock.patch.object(
                cli_main,
                "_suggest_elephant_name",
                return_value="Rowan",
            ),
        ):
            state = _run_interactive_elephant_wizard(mock.Mock(), elephant_name=None)

        self.assertEqual(state, "Nova")
        self.assertEqual(text_prompt.call_count, 1)
        self.assertEqual(text_prompt.call_args_list[0].kwargs["default"], "Rowan")

    def test_interactive_elephant_wizard_can_cancel_before_creating_elephant(
        self,
    ) -> None:
        with (
            mock.patch.object(
                cli_main, "_wizard_text_prompt", return_value=WIZARD_BACK
            ),
            mock.patch.object(
                cli_main, "_suggest_elephant_name", return_value="Theo"
            ) as suggest_name,
        ):
            runtime = mock.Mock()
            state = _run_interactive_elephant_wizard(runtime, elephant_name=None)

        self.assertIsNone(state)
        suggest_name.assert_called_once_with(runtime)

    def test_run_setup_creates_first_elephant_when_non_interactive(self) -> None:
        runtime = mock.Mock()
        runtime.current_profile.return_value = SimpleNamespace(
            state=SimpleNamespace(display_name="Elephant Agent"),
            companion=SimpleNamespace(
                personality_preset="companion", initiative="gentle"
            ),
        )
        updated_profile = SimpleNamespace(
            state=SimpleNamespace(
                profile_id="profile-companion",
                display_name="Elephant Agent",
                mode="companion",
            ),
            companion=SimpleNamespace(
                personality_preset="companion", initiative="gentle"
            ),
        )
        runtime.provider_setup_guide.return_value = SimpleNamespace(
            auth_type="api_key", required_secret_keys=()
        )
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
        runtime.create_elephant.return_value = SimpleNamespace(
            episode_id="session-demo"
        )
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
            companion=SimpleNamespace(
                personality_preset="companion", initiative="gentle"
            ),
        )
        updated_profile = SimpleNamespace(
            state=SimpleNamespace(
                profile_id="profile-companion",
                display_name="Elephant Agent",
                mode="companion",
            ),
            companion=SimpleNamespace(
                personality_preset="companion", initiative="gentle"
            ),
        )
        runtime.provider_setup_guide.return_value = SimpleNamespace(
            auth_type="api_key", required_secret_keys=()
        )
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
        first_elephant = SimpleNamespace(
            episode_id="session-demo", personal_model_id="pm-demo"
        )
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
            mock.patch.object(
                cli_main, "_bootstrap_personal_model_from_init"
            ) as bootstrap_personal_model,
        ):
            exit_code = cli_main._run_setup(runtime, args)

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            bootstrap_personal_model.call_args.args[2].birth_date, "late summer 1991"
        )

    def test_init_question_config_persists_proactive_ask_from_learning_intensity(
        self,
    ) -> None:
        runtime = SimpleNamespace(
            paths=SimpleNamespace(state_dir="/tmp/elephant-test/herd")
        )
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

    def test_interactive_setup_uses_shallow_provider_doctor_before_tui_handoff(
        self,
    ) -> None:
        runtime = mock.Mock()
        runtime.current_profile.return_value = SimpleNamespace(
            state=SimpleNamespace(display_name="Elephant Agent"),
            companion=SimpleNamespace(
                personality_preset="companion", initiative="gentle"
            ),
        )
        updated_profile = SimpleNamespace(
            state=SimpleNamespace(
                profile_id="profile-companion",
                display_name="Elephant Agent",
                mode="companion",
            ),
            companion=SimpleNamespace(
                personality_preset="companion", initiative="gentle"
            ),
        )
        runtime.provider_setup_guide.return_value = SimpleNamespace(
            auth_type="api_key", required_secret_keys=()
        )
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
            mock.patch.object(
                cli_main, "_interactive_shell_supported", return_value=True
            ),
            mock.patch.object(cli_main, "_print_birth_wizard_intro"),
            mock.patch.object(
                cli_main, "_run_interactive_birth_wizard", return_value=wizard_state
            ),
            mock.patch.object(cli_main, "_print_init_section"),
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
        runtime.create_elephant.return_value = SimpleNamespace(
            episode_id="session-nova"
        )
        args = SimpleNamespace(
            elephant_name="nova",
            display_name=None,
            profile_id=None,
            debug=False,
            message=None,
        )

        with (
            mock.patch.object(
                cli_main, "_interactive_shell_supported", return_value=False
            ),
            mock.patch.object(cli_main, "_unique_elephant_name", return_value="nova"),
        ):
            exit_code = cli_main._run_elephant(runtime, args)

        self.assertEqual(exit_code, 0)
        runtime.provider_doctor.assert_called_once_with(deep=False)
        runtime.create_elephant.assert_called_once_with(
            elephant_id="nova",
            profile_id=None,
            display_name="Nova",
            mode="companion",
        )

    def test_run_elephant_does_not_open_wizard_when_name_is_preselected(self) -> None:
        runtime = mock.Mock()
        runtime.provider_doctor.return_value = {"status": "ready"}
        runtime.create_elephant.return_value = SimpleNamespace(
            episode_id="session-nova"
        )
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
            mock.patch.object(
                cli_main, "_interactive_shell_supported", return_value=True
            ),
            mock.patch.object(cli_main, "_run_interactive_elephant_wizard") as wizard,
            mock.patch.object(cli_main, "_unique_elephant_name", return_value="nova"),
            mock.patch.object(cli_main, "ProductizedShell", return_value=shell),
        ):
            exit_code = cli_main._run_elephant(runtime, args)

        self.assertEqual(exit_code, 0)
        runtime.provider_doctor.assert_called_once_with(deep=False)
        wizard.assert_not_called()
        runtime.prepare_session_surface.assert_not_called()
        runtime.create_elephant.assert_called_once_with(
            elephant_id="nova",
            profile_id=None,
            display_name="Nova",
            mode="companion",
        )

    def test_run_grow_defers_surface_prepare_until_after_interactive_shell_boot(
        self,
    ) -> None:
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
            mock.patch.object(
                cli_main,
                "_open_growth_episode",
                return_value=("episode-atlas", "Opened elephant atlas"),
            ),
            mock.patch.object(
                cli_main, "_interactive_shell_supported", return_value=True
            ),
            mock.patch.object(
                cli_main, "ProductizedShell", return_value=shell
            ) as productized_shell,
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
        runtime.latest_session_for_elephant.return_value = SimpleNamespace(
            episode_id="episode-parent", status="open", exit_summary=""
        )
        runtime.open_next_episode.return_value = SimpleNamespace(
            episode=SimpleNamespace(episode_id="episode-child", status="open")
        )

        episode_id, opened = cli_main._open_growth_episode(runtime, elephant_id="atlas")

        self.assertEqual(episode_id, "episode-child")
        self.assertEqual(opened, "Opened elephant atlas")
        runtime.open_next_episode.assert_called_once_with(
            "episode-parent", reason="wake_boundary", summary=""
        )

    def test_open_growth_episode_opens_next_episode_for_closed_elephant(self) -> None:
        runtime = mock.Mock()
        runtime.latest_session_for_elephant.return_value = SimpleNamespace(
            episode_id="episode-parent", status="closed", exit_summary="parent handoff"
        )
        runtime.open_next_episode.return_value = SimpleNamespace(
            episode=SimpleNamespace(episode_id="episode-child", status="open")
        )

        episode_id, opened = cli_main._open_growth_episode(runtime, elephant_id="atlas")

        self.assertEqual(episode_id, "episode-child")
        self.assertEqual(opened, "Opened elephant atlas")
        runtime.open_next_episode.assert_called_once_with(
            "episode-parent", reason="wake_boundary", summary="parent handoff"
        )

    def test_resolve_growth_session_prefers_current_elephant_snapshot_when_multiple_prompting_is_disabled(
        self,
    ) -> None:
        runtime = mock.Mock()
        runtime.elephant_id_for_session.return_value = "atlas"
        runtime.list_herd.return_value = (
            SimpleNamespace(
                elephant_id="atlas",
                latest_session_id="episode-atlas",
                session_count=1,
                latest_status="open",
            ),
            SimpleNamespace(
                elephant_id="beta",
                latest_session_id="episode-beta",
                session_count=1,
                latest_status="open",
            ),
        )
        current_session = SimpleNamespace(
            episode_id="episode-current",
            elephant_id="atlas",
            status="open",
            exit_summary="",
        )
        runtime.open_next_episode.return_value = SimpleNamespace(
            episode=SimpleNamespace(episode_id="episode-next", status="open")
        )

        with mock.patch.object(
            cli_elephant_support,
            "_current_elephant_session",
            return_value=current_session,
        ):
            episode_id, opened = cli_main._open_growth_episode(
                runtime, prompt_for_multiple=False
            )

        self.assertEqual(episode_id, "episode-next")
        self.assertEqual(opened, "Opened elephant atlas")
        runtime.open_next_episode.assert_called_once_with(
            "episode-current", reason="wake_boundary", summary=""
        )

    def test_resolve_growth_session_prompts_for_multiple_elephants_in_interactive_mode(
        self,
    ) -> None:
        runtime = mock.Mock()
        runtime.list_herd.return_value = (
            SimpleNamespace(
                elephant_id="atlas",
                latest_session_id="episode-atlas",
                session_count=2,
                latest_status="open",
            ),
            SimpleNamespace(
                elephant_id="beta",
                latest_session_id="episode-beta",
                session_count=3,
                latest_status="open",
            ),
        )
        runtime.elephant_id_for_session.return_value = "atlas"
        runtime.inspect_session.return_value = SimpleNamespace(
            episode_id="episode-beta", status="open", exit_summary=""
        )
        runtime.open_next_episode.return_value = SimpleNamespace(
            episode=SimpleNamespace(episode_id="episode-beta-next", status="open")
        )
        current_session = SimpleNamespace(
            episode_id="episode-current", elephant_id="atlas", status="open"
        )
        selected_elephant = runtime.list_herd.return_value[1]

        with (
            mock.patch.object(
                cli_elephant_support,
                "_current_elephant_session",
                return_value=current_session,
            ),
            mock.patch.object(
                cli_elephant_support,
                "_prompt_elephant_choice",
                return_value=selected_elephant,
            ) as prompt_elephant_choice,
        ):
            episode_id, opened = cli_main._open_growth_episode(
                runtime, prompt_for_multiple=True
            )

        self.assertEqual(episode_id, "episode-beta-next")
        self.assertEqual(opened, "Opened elephant beta")
        prompt_elephant_choice.assert_called_once_with(
            runtime,
            runtime.list_herd.return_value,
            preferred_elephant_id="atlas",
        )
        runtime.inspect_session.assert_called_once_with("episode-beta")
        runtime.schedule_learning_for_session.assert_not_called()

    def test_resolve_growth_session_does_not_queue_boundary_learning_when_opening_different_elephant(
        self,
    ) -> None:
        runtime = mock.Mock()
        runtime.latest_session_for_elephant.return_value = SimpleNamespace(
            episode_id="episode-beta", status="open", exit_summary=""
        )
        runtime.open_next_episode.return_value = SimpleNamespace(
            episode=SimpleNamespace(episode_id="episode-beta-next", status="open")
        )
        current_session = SimpleNamespace(
            episode_id="episode-atlas", elephant_id="atlas", status="open"
        )
        runtime.elephant_id_for_session.return_value = "atlas"

        with mock.patch.object(
            cli_elephant_support,
            "_current_elephant_session",
            return_value=current_session,
        ):
            episode_id, opened = cli_main._open_growth_episode(
                runtime, elephant_id="beta"
            )

        self.assertEqual(episode_id, "episode-beta-next")
        self.assertEqual(opened, "Opened elephant beta")
        runtime.schedule_learning_for_session.assert_not_called()


if __name__ == "__main__":
    unittest.main()
