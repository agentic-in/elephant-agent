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


class CliMainWizardTest(unittest.TestCase):
    def test_provider_choices_use_plain_labels_and_brand_accent_detail(self) -> None:
        runtime = mock.Mock()
        runtime.provider_inventory.return_value = (
            SimpleNamespace(
                provider_id="openai-compatible",
                display_name="OpenAI-compatible",
                status="requires-setup",
                source="none",
                runtime_enabled=True,
            ),
            SimpleNamespace(
                provider_id="moonshot",
                display_name="Moonshot Kimi",
                status="requires-setup",
                source="none",
                runtime_enabled=True,
            ),
            SimpleNamespace(
                provider_id="unknown-provider",
                display_name="Custom",
                status="requires-setup",
                source="none",
                runtime_enabled=True,
            ),
        )

        providers = _provider_choices(runtime)

        self.assertEqual([choice.emoji for choice in providers], ["", "", ""])
        self.assertEqual(
            [choice.detail_style for choice in providers],
            ["accent-detail", "accent-detail", "accent-detail"],
        )

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

        with mock.patch.object(
            cli_main, "_print_current_elephant"
        ) as print_current_elephant:
            exit_code = cli_main._run_herd(runtime, args)

        self.assertEqual(exit_code, 0)
        print_current_elephant.assert_called_once_with(runtime)

    def test_run_herd_use_selects_elephant_and_prints_selection(self) -> None:
        runtime = mock.Mock()
        args = SimpleNamespace(herd_command="use", elephant_id="atlas")

        with (
            mock.patch.object(cli_main, "_select_elephant") as select_elephant,
            mock.patch.object(
                cli_main, "_print_elephant_selected"
            ) as print_elephant_selected,
        ):
            exit_code = cli_main._run_herd(runtime, args)

        self.assertEqual(exit_code, 0)
        select_elephant.assert_called_once_with(runtime, "atlas")
        print_elephant_selected.assert_called_once_with(runtime, "atlas")

    def test_run_herd_delete_requires_delete_name_or_all(self) -> None:
        runtime = mock.Mock()
        runtime.list_herd.return_value = ()
        args = SimpleNamespace(
            herd_command="delete", elephant_id=None, delete_all=False
        )

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

        with mock.patch.object(
            cli_main, "_delete_personal_model_fact"
        ) as delete_personal_model_fact:
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
        args = SimpleNamespace(
            provider_command="embeddings", embedding_command="status"
        )

        with mock.patch.object(
            cli_main, "_print_embedding_provider_status"
        ) as print_status:
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
        runtime.set_local_embedding_provider.assert_called_once_with(
            source="huggingface"
        )
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

    def test_run_brain_interactive_provider_state_is_not_compared_as_hashable_signal(
        self,
    ) -> None:
        runtime = mock.Mock()
        profile_state = SimpleNamespace(
            profile_id="profile-default", display_name="Atlas", mode="companion"
        )
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
            mock.patch.object(
                cli_main, "_interactive_shell_supported", return_value=True
            ),
            mock.patch.object(
                cli_main, "provider_setup_defaults", return_value=configured
            ),
            mock.patch.object(
                cli_main, "run_provider_selection_wizard", return_value=configured
            ),
            mock.patch.object(cli_main, "_print_cli_card"),
        ):
            exit_code = cli_main._run_brain(runtime, args)

        self.assertEqual(exit_code, 0)
        runtime.set_default_provider.assert_called_once()

    def test_suggest_elephant_name_skips_existing_elephant_ids_when_possible(
        self,
    ) -> None:
        runtime = mock.Mock()
        runtime.latest_session_for_elephant.side_effect = lambda elephant_id: (
            object() if elephant_id == "ada" else None
        )
        captured: dict[str, tuple[str, ...]] = {}

        def _pick(options):
            captured["options"] = tuple(options)
            return options[0]

        with mock.patch.object(cli_main.random, "choice", side_effect=_pick):
            suggested = cli_main._suggest_elephant_name(runtime)

        self.assertEqual(suggested, captured["options"][0])
        self.assertNotIn("Ada", captured["options"])


if __name__ == "__main__":
    unittest.main()
