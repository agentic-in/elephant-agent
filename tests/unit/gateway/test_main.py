from __future__ import annotations

from datetime import UTC, datetime
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

import apps.gateway.__main__ as gateway_main
import apps.gateway.gateway_main_setup_impl as gateway_setup_impl
import apps.gateway.gateway_main_wizard_binding as gateway_wizard_binding
import apps.gateway.gateway_main_wizard_ui as gateway_wizard_ui
from apps.cli.wizard import WIZARD_BACK, WizardChoice
from apps.gateway import CronSchedulerService, GatewayManagedRuntime
from packages.contracts.layers import Episode


class GatewayWizardIntegrationTest(unittest.TestCase):
    def test_gateway_text_prompt_uses_shared_wizard_dialogs(self) -> None:
        with (
            mock.patch.object(
                gateway_wizard_ui,
                "_gateway_wizard_dialogs_supported",
                return_value=True,
            ),
            mock.patch.object(
                gateway_wizard_ui,
                "_shared_wizard_text_prompt",
                return_value="demo-elephant",
            ) as shared_prompt,
        ):
            answer = gateway_main._gateway_wizard_text_prompt(
                "Default Elephant",
                "Which elephant should plain text use?",
                default="aeon",
                allow_back=True,
                preserve_default_on_empty=False,
            )

        self.assertEqual(answer, "demo-elephant")
        shared_prompt.assert_called_once_with(
            "Default Elephant",
            "Which elephant should plain text use?",
            default="aeon",
            allow_back=True,
            preserve_default_on_empty=False,
        )

    def test_gateway_choice_prompt_uses_shared_wizard_dialogs(self) -> None:
        choices = (
            WizardChoice(
                value="long-connection",
                label="Long Connection",
                detail="Local bridge.",
                emoji="🛰️",
            ),
            WizardChoice(value="skip", label="Skip", detail="Stay local.", emoji="➖"),
        )
        with (
            mock.patch.object(
                gateway_wizard_ui,
                "_gateway_wizard_dialogs_supported",
                return_value=True,
            ),
            mock.patch.object(
                gateway_wizard_ui,
                "_shared_wizard_choice_prompt",
                return_value="long-connection",
            ) as shared_choice,
        ):
            answer = gateway_main._gateway_wizard_choice_prompt(
                "Ingress Transport",
                "How should this Feishu bridge receive events?",
                choices,
                default="long-connection",
                allow_back=True,
            )

        self.assertEqual(answer, "long-connection")
        shared_choice.assert_called_once_with(
            "Ingress Transport",
            "How should this Feishu bridge receive events?",
            choices,
            default="long-connection",
            allow_back=True,
        )

    def test_gateway_secret_prompt_uses_shared_password_dialog(self) -> None:
        with (
            mock.patch.object(
                gateway_wizard_ui,
                "_gateway_wizard_dialogs_supported",
                return_value=True,
            ),
            mock.patch.object(
                gateway_wizard_ui,
                "_shared_wizard_text_prompt",
                return_value="secret-value",
            ) as shared_prompt,
        ):
            answer = gateway_main._gateway_wizard_secret_prompt(
                "Paste App Secret",
                "Paste the Feishu App Secret / API key to store it in the local IM secret file.",
                allow_back=True,
            )

        self.assertEqual(answer, "secret-value")
        shared_prompt.assert_called_once_with(
            "Paste App Secret",
            "Paste the Feishu App Secret / API key to store it in the local IM secret file.",
            allow_back=True,
            password=True,
        )

    def test_gateway_choice_prompt_preserves_back_signal_from_shared_wizard(
        self,
    ) -> None:
        choices = (WizardChoice(value="feishu", label="Feishu", detail="Wire Feishu.", emoji="🐦"),)
        with (
            mock.patch.object(
                gateway_wizard_ui,
                "_gateway_wizard_dialogs_supported",
                return_value=True,
            ),
            mock.patch.object(
                gateway_wizard_ui,
                "_shared_wizard_choice_prompt",
                return_value=WIZARD_BACK,
            ),
        ):
            answer = gateway_main._gateway_wizard_choice_prompt(
                "💬 IM Setup",
                "Which IM should Elephant Agent configure right now?",
                choices,
                default="feishu",
                allow_back=True,
            )

        self.assertIs(answer, gateway_main.GATEWAY_WIZARD_BACK)

    def test_run_im_setup_can_dispatch_discord_wizard(self) -> None:
        with (
            mock.patch.object(gateway_main, "_gateway_wizard_choice_prompt", return_value="discord"),
            mock.patch.object(gateway_main, "command_main", return_value=0) as command_main,
        ):
            exit_code = gateway_main.run_im_setup(
                default_state_dir=Path("/tmp/state"),
                default_control_state_dir=Path("/tmp/state"),
            )

        self.assertEqual(exit_code, 0)
        command_main.assert_called_once_with(
            ["discord", "setup", "--wizard"],
            default_state_dir=Path("/tmp/state"),
            default_control_state_dir=Path("/tmp/state"),
        )

    def test_gateway_discord_wizard_intro_prints_setup_card_without_extra_confirmation(
        self,
    ) -> None:
        output = io.StringIO()
        with (
            mock.patch.object(gateway_wizard_ui, "RICH_AVAILABLE", False),
            mock.patch("builtins.input", return_value="") as input_mock,
            mock.patch("sys.stdout", new=output),
        ):
            answer = gateway_main._print_gateway_discord_wizard_intro()

        self.assertTrue(answer)
        input_mock.assert_not_called()
        rendered = output.getvalue()
        self.assertIn("Bring Discord into Elephant Agent Gateway.", rendered)
        self.assertIn("Discord portal checklist", rendered)

    def test_gateway_feishu_wizard_intro_prints_setup_card_without_extra_confirmation(
        self,
    ) -> None:
        output = io.StringIO()
        with (
            mock.patch.object(gateway_wizard_ui, "RICH_AVAILABLE", False),
            mock.patch("builtins.input", return_value="") as input_mock,
            mock.patch("sys.stdout", new=output),
        ):
            answer = gateway_main._print_gateway_feishu_wizard_intro()

        self.assertTrue(answer)
        input_mock.assert_not_called()
        rendered = output.getvalue()
        self.assertIn("💬 Elephant Agent Gateway // Feishu setup", rendered)

    def test_confirm_gateway_wizard_intro_auto_accepts_without_prompt(self) -> None:
        with mock.patch("builtins.input", return_value="q") as input_mock:
            self.assertTrue(gateway_main._confirm_gateway_wizard_intro())

        input_mock.assert_not_called()

    def test_prompt_gateway_control_binding_uses_elephant_and_session_menus_when_runtime_is_ready(
        self,
    ) -> None:
        now = datetime.now(UTC)
        latest_session = Episode(
            episode_id="session-demo-latest",
            state_id="state:test",
            personal_model_id="you",
            entry_surface="test",
            elephant_id="demo",
            status="open",
            started_at=now,
            updated_at=now,
        )
        root_session = Episode(
            episode_id="session-demo-root",
            state_id="state:test",
            personal_model_id="you",
            entry_surface="test",
            elephant_id="demo",
            status="paused",
            started_at=now,
            updated_at=now,
            parent_episode_id="session-demo-origin",
        )

        class _Runtime:
            def list_herd(self, *, limit: int = 12):
                return (
                    SimpleNamespace(
                        elephant_id="demo",
                        latest_session_id=latest_session.episode_id,
                        latest_status=latest_session.status,
                        updated_at=latest_session.updated_at,
                        session_count=2,
                    ),
                )[:limit]

            def session_ids_for_elephant(self, elephant_id: str) -> tuple[str, ...]:
                if elephant_id != "demo":
                    return ()
                return (latest_session.episode_id, root_session.episode_id)

            def inspect_session(self, session_id: str) -> Episode:
                if session_id == latest_session.episode_id:
                    return latest_session
                if session_id == root_session.episode_id:
                    return root_session
                raise KeyError(session_id)

        with mock.patch.object(
            gateway_wizard_binding,
            "_gateway_wizard_choice_prompt",
            side_effect=["demo", "session-demo-root"],
        ) as choice_prompt:
            answer = gateway_main._prompt_gateway_control_binding(
                runtime=_Runtime(),
                current_elephant_id="",
                current_session_id="",
                allow_back=True,
            )

        self.assertEqual(answer, ("demo", "session-demo-root"))
        elephant_choices = choice_prompt.call_args_list[0].args[2]
        self.assertTrue(any(choice.value == "demo" for choice in elephant_choices))
        self.assertTrue(any(choice.value == gateway_main._GATEWAY_MANUAL_EGG for choice in elephant_choices))
        session_choices = choice_prompt.call_args_list[1].args[2]
        self.assertEqual(session_choices[0].value, gateway_main._GATEWAY_FOLLOW_LATEST_SESSION)
        self.assertTrue(any(choice.value == "session-demo-root" for choice in session_choices))

    def test_prompt_gateway_control_binding_skips_session_menu_when_elephant_has_single_session(
        self,
    ) -> None:
        now = datetime.now(UTC)
        only_session = Episode(
            episode_id="session-demo-only",
            state_id="state:test",
            personal_model_id="you",
            entry_surface="test",
            elephant_id="demo",
            status="open",
            started_at=now,
            updated_at=now,
        )

        class _Runtime:
            def list_herd(self, *, limit: int = 12):
                return (
                    SimpleNamespace(
                        elephant_id="demo",
                        latest_session_id=only_session.episode_id,
                        latest_status=only_session.status,
                        updated_at=only_session.updated_at,
                        session_count=1,
                    ),
                )[:limit]

            def session_ids_for_elephant(self, elephant_id: str) -> tuple[str, ...]:
                if elephant_id != "demo":
                    return ()
                return (only_session.episode_id,)

            def inspect_session(self, session_id: str) -> Episode:
                if session_id == only_session.episode_id:
                    return only_session
                raise KeyError(session_id)

        with mock.patch.object(
            gateway_wizard_binding,
            "_gateway_wizard_choice_prompt",
            return_value="demo",
        ) as choice_prompt:
            answer = gateway_main._prompt_gateway_control_binding(
                runtime=_Runtime(),
                current_elephant_id="",
                current_session_id="",
                allow_back=True,
            )

        self.assertEqual(answer, ("demo", "session-demo-only"))
        choice_prompt.assert_called_once()

    def test_start_discord_runtime_after_setup_fills_runtime_defaults(self) -> None:
        args = gateway_main.Namespace(
            profile_dir=Path("/tmp/profile"),
            state_dir=Path("/tmp/state"),
            cli_profile_dir=Path("/tmp/cli-profile"),
            cli_state_dir=Path("/tmp/cli-state"),
            account_id="default",
        )

        with (
            mock.patch.object(gateway_setup_impl, "_build_discord_service", return_value=object()) as build_service,
            mock.patch.object(gateway_setup_impl, "_run_restart", return_value=0) as run_restart,
        ):
            exit_code = gateway_main._start_discord_runtime_after_setup(args, transport="gateway")

        self.assertEqual(exit_code, 0)
        build_service.assert_called_once_with(args)
        restart_args = run_restart.call_args.args[0]
        self.assertEqual(restart_args.runtime_target, "gateway")
        self.assertTrue(restart_args.detach)
        self.assertEqual(restart_args.timeout, 10.0)
        self.assertFalse(restart_args.force)
        self.assertEqual(run_restart.call_args.kwargs["service"], build_service.return_value)

    def test_start_feishu_runtime_after_setup_fills_runtime_defaults(self) -> None:
        args = gateway_main.Namespace(
            profile_dir=Path("/tmp/profile"),
            state_dir=Path("/tmp/state"),
            cli_profile_dir=Path("/tmp/cli-profile"),
            cli_state_dir=Path("/tmp/cli-state"),
            account_id="default",
        )

        with (
            mock.patch.object(gateway_setup_impl, "_build_feishu_service", return_value=object()) as build_service,
            mock.patch.object(gateway_setup_impl, "_run_restart", return_value=0) as run_restart,
        ):
            exit_code = gateway_main._start_feishu_runtime_after_setup(args, transport="long-connection")

        self.assertEqual(exit_code, 0)
        build_service.assert_called_once_with(args)
        restart_args = run_restart.call_args.args[0]
        self.assertEqual(restart_args.runtime_target, "long-connection")
        self.assertTrue(restart_args.detach)
        self.assertEqual(restart_args.host, "127.0.0.1")
        self.assertEqual(restart_args.port, 8788)
        self.assertEqual(restart_args.timeout, 10.0)
        self.assertFalse(restart_args.force)
        self.assertEqual(run_restart.call_args.kwargs["service"], build_service.return_value)

    def test_prompt_gateway_control_binding_falls_back_to_text_when_runtime_is_unavailable(
        self,
    ) -> None:
        with mock.patch.object(
            gateway_wizard_binding,
            "_gateway_wizard_text_prompt",
            return_value="demo-manual",
        ) as text_prompt:
            answer = gateway_main._prompt_gateway_control_binding(
                runtime=None,
                current_elephant_id="",
                current_session_id="",
                allow_back=True,
            )

        self.assertEqual(answer, ("demo-manual", ""))
        text_prompt.assert_called_once()


class _ManagedOnlyService:
    service_key = "discord"
    app = object()

    def describe(self) -> dict[str, object]:
        return {"configured_transport": "gateway"}

    def configured_runtime_target(self) -> str:
        return "gateway"

    def managed_runtime(
        self,
        *,
        args,
        target: str,
    ) -> GatewayManagedRuntime:
        return GatewayManagedRuntime(
            service_key=self.service_key,
            runtime_id=f"{self.service_key}:{target}",
            target=target,
            label="Discord gateway runtime",
            pid_path=Path("/tmp/discord-gateway.pid"),
            log_path=Path("/tmp/discord-gateway.log"),
            record_path=Path("/tmp/discord-gateway.runtime.json"),
        )

    def build_detached_runtime_command(self, *, args, target: str) -> tuple[str, ...]:
        return ("python", "-m", "apps.launcher")

    def prepare_managed_runtime(self, *, action: str, target: str) -> None:
        return None

    def managed_runtime_log_hint(self, *, target: str) -> str:
        return "elephant gateway discord logs --target gateway --follow"


class GatewayManagedServiceTest(unittest.TestCase):
    def test_run_serve_rejects_profiles_without_http_services(self) -> None:
        with mock.patch.object(
            gateway_main,
            "_build_services",
            return_value=(object(), {"discord": _ManagedOnlyService()}),
        ):
            with self.assertRaises(SystemExit) as exit_info:
                gateway_main._run_serve(
                    mock.Mock(host="127.0.0.1", port=8788),
                )

        self.assertEqual(
            str(exit_info.exception),
            "No enabled gateway HTTP services are available in the active profile manifest.",
        )

    def test_run_status_prints_discord_account_summary(self) -> None:
        class _DiscordStatusService(_ManagedOnlyService):
            def describe(self) -> dict[str, object]:
                return {
                    "configured_transport": "gateway",
                    "account_status": {
                        "service_status": "degraded",
                        "configured_accounts": 2,
                        "enabled_accounts": 1,
                        "runnable_accounts": 1,
                        "blocked_accounts": 0,
                        "disabled_accounts": 1,
                        "blocked_account_ids": (),
                        "disabled_account_ids": ("shadow-discord",),
                    },
                    "accounts": (
                        {
                            "account_id": "ops-discord",
                            "enabled": True,
                            "startup_status": "ready",
                            "credentials_status": "configured",
                            "surface": "gateway",
                            "bot_token_env_var": "ELEPHANT_DISCORD_OPS_BOT_TOKEN",
                            "allow_guild_ids": (),
                            "allow_channel_ids": (),
                        },
                        {
                            "account_id": "shadow-discord",
                            "enabled": False,
                            "startup_status": "disabled",
                            "credentials_status": "missing_credentials",
                            "surface": "gateway",
                            "bot_token_env_var": "ELEPHANT_DISCORD_SHADOW_BOT_TOKEN",
                            "allow_guild_ids": (),
                            "allow_channel_ids": (),
                        },
                    ),
                }

        args = mock.Mock(runtime_target="configured")
        runtime_state = {
            "status": "running",
            "pid": 123,
            "pid_active": True,
            "stale_pid": False,
            "record": {
                "status": "running",
                "command": ("python", "-m", "apps.launcher"),
            },
        }
        output = io.StringIO()
        with (
            mock.patch.object(gateway_main, "_runtime_state", return_value=runtime_state),
            mock.patch("sys.stdout", new=output),
        ):
            exit_code = gateway_main._run_status(args, service=_DiscordStatusService())

        self.assertEqual(exit_code, 0)
        rendered = output.getvalue()
        self.assertIn("account_service_status: degraded", rendered)
        self.assertIn("disabled_account_ids: shadow-discord", rendered)
        self.assertIn("account: ops-discord · enabled=yes · startup=ready", rendered)
        self.assertIn("account: shadow-discord · enabled=no · startup=disabled", rendered)

    def test_service_runtime_status_summary_accepts_managed_service(self) -> None:
        runtime_status, runtime_error = gateway_main._service_runtime_status_summary(
            _ManagedOnlyService(),
            SimpleNamespace(runtime_target="configured"),
        )

        self.assertEqual(runtime_status, "stopped")
        self.assertIsNone(runtime_error)

    def test_cron_scheduler_service_builds_managed_runtime_command(self) -> None:
        service = CronSchedulerService(
            app=SimpleNamespace(state_dir="/state"),
            default_cli_state_dir="/state",
        )
        args = SimpleNamespace(
            state_dir=Path("/state"),
            cli_state_dir=Path("/state"),
            interval_seconds=30.0,
        )

        runtime = service.managed_runtime(args=args, target="configured")
        command = service.build_detached_runtime_command(args=args, target="configured")

        self.assertEqual(runtime.service_key, "cron")
        self.assertEqual(runtime.target, "scheduler")
        self.assertIn("cron", command)
        self.assertIn("run", command)
        self.assertIn("--interval-seconds", command)
        self.assertIn("30.0", command)

    def test_cron_logs_do_not_require_account_id(self) -> None:
        service = _ManagedOnlyService()
        service.service_key = "cron"
        args = mock.Mock(
            runtime_target="configured",
            account_id=None,
            account_id_flag=None,
            path=True,
        )
        runtime_state = {
            "status": "running",
            "pid": 123,
            "pid_active": True,
            "stale_pid": False,
            "record": {
                "status": "running",
                "command": ("python", "-m", "apps.launcher"),
            },
        }
        output = io.StringIO()
        with (
            mock.patch.object(gateway_main, "_runtime_state", return_value=runtime_state),
            mock.patch("sys.stdout", new=output),
        ):
            exit_code = gateway_main._run_logs(args, service=service)

        self.assertEqual(exit_code, 0)
        self.assertIn("discord-gateway.log", output.getvalue())

    def test_discord_doctor_lines_include_account_health_summary(self) -> None:
        service = mock.Mock()
        service.describe.return_value = {
            "configured_transport": "gateway",
            "sdk_dependency_status": "installed",
            "required_intents": ("guilds", "messages", "message_content"),
            "runtime": {"runtime_status": "running", "target": "gateway", "pid": 321},
            "control": {"runtime_status": "ready", "known_elephants": ("zoe",)},
            "account_status": {
                "service_status": "degraded",
                "configured_accounts": 2,
                "enabled_accounts": 2,
                "runnable_accounts": 1,
                "blocked_accounts": 1,
                "disabled_accounts": 0,
                "blocked_account_ids": ("shadow-discord",),
                "disabled_account_ids": (),
            },
            "accounts": (
                {
                    "account_id": "ops-discord",
                    "enabled": True,
                    "startup_status": "ready",
                    "credentials_status": "configured",
                    "surface": "gateway",
                    "bot_token_env_var": "ELEPHANT_DISCORD_OPS_BOT_TOKEN",
                    "allow_guild_ids": (),
                    "allow_channel_ids": (),
                },
                {
                    "account_id": "shadow-discord",
                    "enabled": True,
                    "startup_status": "blocked",
                    "credentials_status": "missing_credentials",
                    "credentials_error": "discord account 'shadow-discord' requires ELEPHANT_DISCORD_SHADOW_BOT_TOKEN",
                    "surface": "gateway",
                    "bot_token_env_var": "ELEPHANT_DISCORD_SHADOW_BOT_TOKEN",
                    "allow_guild_ids": (),
                    "allow_channel_ids": (),
                },
            ),
        }
        args = mock.Mock(
            profile_dir=Path("/tmp/profile"),
            state_dir=Path("/tmp/state"),
            cli_profile_dir=Path("/tmp/profile"),
            cli_state_dir=Path("/tmp/state"),
        )

        lines = gateway_main._discord_doctor_lines(service, args)

        self.assertIn("account_service_status: degraded", lines)
        self.assertIn("blocked_account_ids: shadow-discord", lines)
        self.assertIn("discord_portal_checklist:", lines)
        self.assertIn(
            "- Open Discord Developer Portal → OAuth2 → URL Generator and include the `bot` scope before inviting the app.",
            lines,
        )
        self.assertIn(
            "- Enable the Discord `MESSAGE_CONTENT` privileged intent for this bot before starting the gateway runtime.",
            lines,
        )
        self.assertIn(
            "- Grant these bot permissions in Discord: `View Channels` (`查看频道`), `Send Messages` (`发送消息`), `Send Messages in Threads` (`在子区内发送消息`), and `Read Message History` (`阅读消息历史记录`).",
            lines,
        )
        self.assertTrue(
            any(line.startswith("discord_account: shadow-discord · enabled=yes · startup=blocked") for line in lines)
        )

    def test_doctor_services_lines_tolerate_non_mapping_runtime_payloads(self) -> None:
        service = mock.Mock()
        service.describe.return_value = {
            "configured_transport": "gateway",
            "sdk_dependency_status": "installed",
            "runtime": "managed-service",
            "accounts": (),
        }
        args = mock.Mock(
            profile_dir=Path("/tmp/profile"),
            state_dir=Path("/tmp/state"),
            cli_profile_dir=Path("/tmp/profile"),
            cli_state_dir=Path("/tmp/state"),
        )

        lines = gateway_main._doctor_services_lines(mock.Mock(), {"cron": service}, args)

        self.assertIn("registered_services: cron", lines)
        self.assertIn("service[cron].configured_transport: gateway", lines)
        self.assertNotIn("service[cron].runtime_status: <unknown>", lines)
