from __future__ import annotations

import asyncio
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime
import io
import json
import os
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

from apps.gateway import (
    DEFAULT_DISCORD_BOT_TOKEN_ENV,
    DISCORD_ADAPTER_ID,
    DiscordGatewayService,
    DiscordMessagingAdapter,
    GatewayAdapterDescriptor,
    load_discord_gateway_accounts,
)
from apps.gateway.discord import DiscordPyDeliveryTransport
import apps.gateway.__main__ as gateway_main
from apps.gateway.__main__ import command_main
from packages.contracts.layers import Episode
from packages.gateway_core import (
    DEFAULT_GATEWAY_ACCOUNT_ID,
    GatewayAccountRef,
    GatewayConversationRef,
    GatewayOutboundMessage,
)
from packages.security.runtime import PolicyDecision
from tests.e2e.gateway.gateway_adapter_test_base import GatewayAdapterTestBase


class GatewayAdapterDiscordE2ETests(GatewayAdapterTestBase):
    class _FakeDiscordDeliveryTransport:
        def __init__(self) -> None:
            self.requests: list[tuple[dict[str, object], object]] = []

        async def send_request(self, request, *, account):
            normalized_request = {str(key): value for key, value in request.items()}
            self.requests.append((normalized_request, account))
            return {"id": "discord-reply-1"}

    def test_ensure_discord_sdk_available_installs_missing_dependency(self) -> None:
        self.ensure_discord_sdk_patcher.stop()
        try:
            output = io.StringIO()
            with (
                mock.patch(
                    "apps.gateway.__main__.importlib.util.find_spec",
                    side_effect=[None, object()],
                ),
                mock.patch("apps.gateway.__main__.subprocess.run") as run,
                redirect_stdout(output),
            ):
                installed = gateway_main._ensure_discord_sdk_available(
                    reason="Discord setup"
                )

            self.assertTrue(installed)
            run.assert_called_once_with(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    gateway_main.DISCORD_PY_PIP_SPEC,
                ],
                check=True,
            )
            rendered = output.getvalue()
            self.assertIn("Preparing Discord support for Discord setup...", rendered)
            self.assertIn("Discord support is ready.", rendered)
        finally:
            self.ensure_discord_sdk = self.ensure_discord_sdk_patcher.start()

    def test_gateway_add_discord_command_writes_profile_config_and_local_secret(
        self,
    ) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"].pop("discord", None)
        )

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = command_main(
                [
                    "discord",
                    "setup",
                    "--state-dir",
                    str(self.state_dir),
                    "--cli-state-dir",
                    str(self.state_dir),
                    "--no-wizard",
                    "--account-id",
                    "ops-discord",
                    "--no-start",
                    "--bot-token-env-var",
                    "ELEPHANT_TEST_DISCORD_BOT_TOKEN",
                    "--bot-token",
                    "discord-token-123",
                    "--allow-guild-id",
                    "123",
                    "--allow-channel-id",
                    "456",
                    "--enabled",
                ]
            )

        self.assertEqual(exit_code, 0)
        rendered = output.getvalue()
        self.assertIn("Configured Discord IM", rendered)
        self.assertIn("Discord developer portal checklist:", rendered)
        self.assertIn("Open Discord Developer Portal", rendered)
        self.assertIn("MESSAGE_CONTENT", rendered)
        self.assertIn("View Channels", rendered)
        self.assertIn("Send Messages", rendered)
        self.assertIn("Send Messages in Threads", rendered)
        self.assertIn("Read Message History", rendered)
        self.assertIn("elephant gateway discord start", rendered)
        self.ensure_discord_sdk.assert_called_with(reason="Discord setup")

        manifest = self._read_runtime_manifest()
        discord = manifest["gateway"]["adapters"]["discord"]
        self.assertTrue(discord["enabled"])
        self.assertEqual(discord["surface"], "gateway")
        account = discord["accounts"][0]
        self.assertEqual(account["account_id"], "ops-discord")
        self.assertEqual(account["surface"], "gateway")
        self.assertEqual(
            account["env"], {"bot_token": "ELEPHANT_TEST_DISCORD_BOT_TOKEN"}
        )
        self.assertEqual(account["allow_guild_ids"], ["123"])
        self.assertEqual(account["allow_channel_ids"], ["456"])

        secret_path = self.state_dir / "gateway-local-secrets.json"
        self.assertTrue(secret_path.exists())
        local_secrets = json.loads(secret_path.read_text(encoding="utf-8"))
        self.assertEqual(
            local_secrets["ELEPHANT_TEST_DISCORD_BOT_TOKEN"], "discord-token-123"
        )

        describe_output = io.StringIO()
        with redirect_stdout(describe_output):
            exit_code = command_main(
                ["discord", "describe"],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )

        self.assertEqual(exit_code, 0)
        described = json.loads(describe_output.getvalue())
        account = described["discord"]["accounts"][0]
        self.assertEqual(account["account_id"], "ops-discord")
        self.assertEqual(account["credentials_status"], "configured")
        self.assertEqual(
            account["bot_token_env_var"], "ELEPHANT_TEST_DISCORD_BOT_TOKEN"
        )

    def test_gateway_add_discord_command_uses_wizard_by_default_when_shell_is_interactive(
        self,
    ) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"].pop("discord", None)
        )
        output = io.StringIO()
        with (
            mock.patch(
                "apps.gateway.gateway_main_setup_impl._interactive_shell_supported",
                return_value=True,
            ),
            mock.patch(
                "apps.gateway.gateway_main_setup_impl._start_discord_runtime_after_setup",
                return_value=0,
            ) as auto_start,
            mock.patch(
                "apps.gateway.gateway_main_setup_impl.getpass.getpass",
                return_value="wizard-discord-token",
            ),
            redirect_stdout(output),
        ):
            exit_code = command_main(
                [
                    "discord",
                    "setup",
                    "--state-dir",
                    str(self.state_dir),
                    "--cli-state-dir",
                    str(self.state_dir),
                ]
            )

        self.assertEqual(exit_code, 0)
        rendered = output.getvalue()
        self.assertIn("Bring Discord into Elephant Agent Gateway.", rendered)
        self.assertIn("Discord portal checklist", rendered)
        self.assertIn("Configured Discord IM", rendered)
        self.assertIn(
            "Starting the configured Discord bridge in the background...", rendered
        )
        self.assertIn("Discord setup is complete.", rendered)
        auto_start.assert_called_once()
        self.assertEqual(auto_start.call_args.kwargs["transport"], "gateway")

        manifest = self._read_runtime_manifest()
        discord = manifest["gateway"]["adapters"]["discord"]
        account = discord["accounts"][0]
        self.assertEqual(account["account_id"], DEFAULT_GATEWAY_ACCOUNT_ID)
        self.assertTrue(discord["enabled"])
        self.assertTrue(account["enabled"])
        self.assertNotIn("default_elephant_id", discord.get("control", {}))
        self.assertNotIn("default_session_id", discord.get("control", {}))
        self.assertNotIn("auto_create_elephant", discord.get("control", {}))
        self.assertNotIn("allow_group_chats", discord.get("control", {}))
        self.assertNotIn("allow_guild_ids", account)
        self.assertNotIn("allow_channel_ids", account)

        local_secrets = json.loads(
            (self.state_dir / "gateway-local-secrets.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            local_secrets[DEFAULT_DISCORD_BOT_TOKEN_ENV], "wizard-discord-token"
        )

    def test_gateway_add_discord_command_replaces_unconfigured_default_placeholder(
        self,
    ) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = command_main(
                [
                    "discord",
                    "setup",
                    "--state-dir",
                    str(self.state_dir),
                    "--cli-state-dir",
                    str(self.state_dir),
                    "--no-wizard",
                    "--account-id",
                    "ops-discord",
                    "--no-start",
                    "--bot-token",
                    "discord-token-ops",
                ]
            )

        self.assertEqual(exit_code, 0)
        manifest = self._read_runtime_manifest()
        discord = manifest["gateway"]["adapters"]["discord"]
        self.assertEqual(len(discord["accounts"]), 1)
        account = discord["accounts"][0]
        self.assertEqual(account["account_id"], "ops-discord")
        self.assertEqual(
            account["env"], {"bot_token": "ELEPHANT_DISCORD_OPS_DISCORD_BOT_TOKEN"}
        )
        rendered = output.getvalue()
        self.assertNotIn("Configure the Discord bot token", rendered)

    def test_gateway_add_discord_command_can_disable_account_without_disabling_adapter(
        self,
    ) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = command_main(
                [
                    "discord",
                    "setup",
                    "--state-dir",
                    str(self.state_dir),
                    "--cli-state-dir",
                    str(self.state_dir),
                    "--no-wizard",
                    "--account-id",
                    "ops-discord",
                    "--no-start",
                    "--bot-token",
                    "discord-token-ops",
                    "--enabled",
                    "--account-disabled",
                ]
            )

        self.assertEqual(exit_code, 0)
        manifest = self._read_runtime_manifest()
        discord = manifest["gateway"]["adapters"]["discord"]
        self.assertTrue(discord["enabled"])
        self.assertFalse(discord["accounts"][0]["enabled"])
        self.assertIn(
            "Discord account enabled for default runtime starts: no", output.getvalue()
        )

    def test_load_discord_gateway_accounts_reads_allowlists_and_runtime_metadata(
        self,
    ) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"].update(
                {
                    "discord": {
                        "enabled": True,
                        "surface": "gateway",
                        "accounts": [
                            {
                                "account_id": "ops-discord",
                                "env": {"bot_token": "ELEPHANT_TEST_DISCORD_BOT_TOKEN"},
                                "allow_guild_ids": ["123", "456"],
                                "allow_channel_ids": ["789"],
                                "runtime": {"shard_count": 2, "shard_ids": [0, 1]},
                            }
                        ],
                    }
                }
            )
        )

        app, _, _ = self._build()
        accounts = load_discord_gateway_accounts(app)

        self.assertEqual(len(accounts), 1)
        account = accounts[0]
        self.assertEqual(account.account_id, "ops-discord")
        self.assertEqual(account.bot_token_env_var, "ELEPHANT_TEST_DISCORD_BOT_TOKEN")
        self.assertEqual(account.surface, "gateway")
        self.assertEqual(account.allow_guild_ids, ("123", "456"))
        self.assertEqual(account.allow_channel_ids, ("789",))
        self.assertEqual(account.runtime_metadata["shard_count"], 2)
        self.assertEqual(tuple(account.runtime_metadata["shard_ids"]), (0, 1))

    def test_load_discord_gateway_accounts_skips_disabled_accounts_but_describe_reports_them(
        self,
    ) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"].update(
                {
                    "discord": {
                        "enabled": True,
                        "surface": "gateway",
                        "accounts": [
                            {
                                "account_id": "ops-discord",
                                "enabled": True,
                                "env": {"bot_token": "ELEPHANT_TEST_DISCORD_BOT_TOKEN"},
                            },
                            {
                                "account_id": "shadow-discord",
                                "enabled": False,
                                "env": {
                                    "bot_token": "ELEPHANT_DISABLED_DISCORD_BOT_TOKEN"
                                },
                            },
                        ],
                    }
                }
            )
        )

        app, _, _ = self._build()
        accounts = load_discord_gateway_accounts(app)
        self.assertEqual(
            tuple(account.account_id for account in accounts), ("ops-discord",)
        )

        description = DiscordGatewayService(
            app=app,
            environ={"ELEPHANT_TEST_DISCORD_BOT_TOKEN": "discord-token-123"},
        ).describe()
        self.assertEqual(description["account_status"]["service_status"], "ready")
        self.assertEqual(description["account_status"]["enabled_accounts"], 1)
        self.assertEqual(description["account_status"]["disabled_accounts"], 1)
        self.assertEqual(
            description["account_status"]["disabled_account_ids"], ("shadow-discord",)
        )
        self.assertEqual(len(description["accounts"]), 2)
        self.assertFalse(description["accounts"][1]["enabled"])
        self.assertEqual(description["accounts"][1]["startup_status"], "disabled")

    def test_discord_service_describe_reports_credentials_and_intents(self) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"].update(
                {
                    "discord": {
                        "enabled": True,
                        "surface": "gateway",
                        "accounts": [
                            {
                                "account_id": "ops-discord",
                                "env": {"bot_token": "ELEPHANT_TEST_DISCORD_BOT_TOKEN"},
                                "allow_guild_ids": ["123", "456"],
                                "allow_channel_ids": ["789"],
                            }
                        ],
                    }
                }
            )
        )

        app, _, _ = self._build()
        description = DiscordGatewayService(
            app=app,
            environ={"ELEPHANT_TEST_DISCORD_BOT_TOKEN": "discord-token-123"},
        ).describe()

        self.assertEqual(description["adapter_id"], DISCORD_ADAPTER_ID)
        self.assertEqual(description["configured_transport"], "gateway")
        self.assertEqual(
            description["required_intents"],
            ("guilds", "messages", "message_content"),
        )
        self.assertEqual(
            description["privileged_intents"],
            ("message_content",),
        )
        self.assertEqual(description["mention_policy"], "suppress-all")
        self.assertEqual(description["runtime"]["runtime"], "managed-service")
        self.assertEqual(description["account_status"]["service_status"], "ready")
        account = description["accounts"][0]
        self.assertEqual(account["account_id"], "ops-discord")
        self.assertTrue(account["enabled"])
        self.assertEqual(account["startup_status"], "ready")
        self.assertEqual(account["credentials_status"], "configured")
        self.assertEqual(
            account["bot_token_env_var"], "ELEPHANT_TEST_DISCORD_BOT_TOKEN"
        )
        self.assertEqual(account["allow_guild_ids"], ("123", "456"))
        self.assertEqual(account["allow_channel_ids"], ("789",))

    def test_gateway_describe_all_includes_discord_service(self) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"].update(
                {
                    "discord": {
                        "enabled": True,
                        "accounts": [
                            {
                                "account_id": "ops-discord",
                                "env": {"bot_token": DEFAULT_DISCORD_BOT_TOKEN_ENV},
                            }
                        ],
                    }
                }
            )
        )
        pid = os.getpid()
        pid_path = self.state_dir / "discord-gateway.pid"
        log_path = self.state_dir / "discord-gateway.log"
        record_path = self.state_dir / "discord-gateway.runtime.json"
        pid_path.write_text(f"{pid}\n", encoding="utf-8")
        log_path.write_text("discord runtime online\n", encoding="utf-8")
        record_path.write_text(
            json.dumps(
                {
                    "runtime_id": "discord:gateway",
                    "service_key": "discord",
                    "target": "gateway",
                    "status": "running",
                    "pid": pid,
                    "pid_path": str(pid_path),
                    "log_path": str(log_path),
                    "record_path": str(record_path),
                    "command": [
                        sys.executable,
                        "-m",
                        "apps.launcher",
                        "gateway",
                        "discord",
                        "start",
                    ],
                    "profile_dir": str(self.profile_dir),
                    "state_dir": str(self.state_dir),
                    "started_at": datetime.now(UTC).isoformat(),
                    "transport": "gateway",
                }
            ),
            encoding="utf-8",
        )

        describe_output = io.StringIO()
        with redirect_stdout(describe_output):
            exit_code = command_main(
                ["describe"],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )

        self.assertEqual(exit_code, 0)
        described = json.loads(describe_output.getvalue())
        self.assertIn("discord", described["services"])
        self.assertIn("discord", described)
        self.assertEqual(
            described["discord"]["accounts"][0]["account_id"], "ops-discord"
        )
        runtime = described["discord"]["runtime"]
        self.assertEqual(runtime["runtime_status"], "running")
        self.assertEqual(runtime["recorded_status"], "running")
        self.assertEqual(runtime["target"], "gateway")
        self.assertEqual(runtime["pid"], pid)
        self.assertTrue(runtime["pid_active"])
        self.assertFalse(runtime["stale_pid_file"])
        self.assertEqual(runtime["pid_file"], str(pid_path))
        self.assertEqual(runtime["log_file"], str(log_path))
        self.assertEqual(runtime["record_file"], str(record_path))

    def test_gateway_discord_doctor_reports_runtime_state(self) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"].update(
                {
                    "discord": {
                        "enabled": True,
                        "accounts": [
                            {
                                "account_id": "ops-discord",
                                "env": {"bot_token": DEFAULT_DISCORD_BOT_TOKEN_ENV},
                            }
                        ],
                    }
                }
            )
        )
        pid = os.getpid()
        pid_path = self.state_dir / "discord-gateway.pid"
        record_path = self.state_dir / "discord-gateway.runtime.json"
        pid_path.write_text(f"{pid}\n", encoding="utf-8")
        record_path.write_text(
            json.dumps(
                {
                    "runtime_id": "discord:gateway",
                    "service_key": "discord",
                    "target": "gateway",
                    "status": "running",
                    "pid": pid,
                    "pid_path": str(pid_path),
                    "log_path": str(self.state_dir / "discord-gateway.log"),
                    "record_path": str(record_path),
                    "command": [
                        sys.executable,
                        "-m",
                        "apps.launcher",
                        "gateway",
                        "discord",
                        "start",
                    ],
                    "profile_dir": str(self.profile_dir),
                    "state_dir": str(self.state_dir),
                    "started_at": datetime.now(UTC).isoformat(),
                    "transport": "gateway",
                }
            ),
            encoding="utf-8",
        )

        doctor_output = io.StringIO()
        with redirect_stdout(doctor_output):
            exit_code = command_main(
                ["discord", "doctor"],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )

        self.assertEqual(exit_code, 0)
        rendered = doctor_output.getvalue()
        self.assertIn("runtime_status: running", rendered)
        self.assertIn("runtime_target: gateway", rendered)
        self.assertIn(f"runtime_pid: {pid}", rendered)
        self.assertIn("discord_portal_checklist:", rendered)
        self.assertIn("Open Discord Developer Portal", rendered)
        self.assertIn("MESSAGE_CONTENT", rendered)
        self.assertIn("View Channels", rendered)
        self.assertIn("Send Messages in Threads", rendered)
        self.assertIn("Read Message History", rendered)
        self.assertIn("already running on `gateway`", rendered)

    def test_gateway_discord_help_lists_runtime_commands(self) -> None:
        output = io.StringIO()
        with self.assertRaises(SystemExit) as exit_info, redirect_stdout(output):
            command_main(["discord", "-h"])

        self.assertEqual(exit_info.exception.code, 0)
        rendered = output.getvalue()
        self.assertIn(
            "{setup,remove,start,status,stop,restart,logs,describe,doctor,message}",
            rendered,
        )
        self.assertIn("setup               Add or update a Discord account.", rendered)
        self.assertIn("remove              Remove a Discord account.", rendered)
        self.assertIn("status              Show Discord status.", rendered)
        self.assertIn(
            "logs                Show logs for one Discord account.", rendered
        )

    def test_gateway_discord_start_detach_spawns_background_process(self) -> None:
        self._update_manifest(
            lambda payload: payload["gateway"]["adapters"].update(
                {
                    "discord": {
                        "enabled": True,
                        "accounts": [
                            {
                                "account_id": "ops-discord",
                                "env": {"bot_token": "ELEPHANT_TEST_DISCORD_BOT_TOKEN"},
                            }
                        ],
                    }
                }
            )
        )

        class FakeProcess:
            pid = 54322

            def poll(self) -> None:
                return None

        output = io.StringIO()
        with (
            mock.patch(
                "apps.gateway.__main__.subprocess.Popen", return_value=FakeProcess()
            ) as popen,
            mock.patch(
                "apps.daemon_command._daemon_healthz_payload",
                side_effect=[
                    None,
                    {
                        "status": "running",
                        "pid": 54322,
                        "state_dir": str(self.state_dir),
                    },
                ],
            ),
            mock.patch("apps.gateway.__main__.time.sleep", return_value=None),
            redirect_stdout(output),
        ):
            exit_code = command_main(
                ["discord", "start", "--transport", "gateway", "--detach"],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )

        self.assertEqual(exit_code, 0)
        rendered = output.getvalue()
        self.assertIn("Elephant daemon is now running in the background.", rendered)
        self.assertIn("PID: 54322", rendered)
        self.assertIn("HTTP: http://0.0.0.0:8900", rendered)
        pid_path = self.state_dir / "daemon.pid"
        log_path = self.state_dir / "daemon.log"
        record_path = self.state_dir / "daemon.runtime.json"
        self.assertTrue(pid_path.exists())
        self.assertEqual(pid_path.read_text(encoding="utf-8").strip(), "54322")
        self.assertTrue(log_path.exists())
        self.assertTrue(record_path.exists())
        runtime_record = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertEqual(runtime_record["runtime_id"], "daemon:unified")
        self.assertEqual(runtime_record["status"], "running")
        self.assertEqual(runtime_record["pid"], 54322)
        launcher_calls = [
            call
            for call in popen.call_args_list
            if len(call.args) >= 1
            and call.args[0][:4] == [sys.executable, "-m", "apps.launcher", "daemon"]
        ]
        self.assertEqual(len(launcher_calls), 1)
        command = launcher_calls[0].args[0]
        self.assertEqual(
            command[:5], [sys.executable, "-m", "apps.launcher", "daemon", "start"]
        )
        self.assertEqual(command[command.index("--state-dir") + 1], str(self.state_dir))
        self.assertEqual(
            command[command.index("--cli-state-dir") + 1], str(self.state_dir)
        )
        self.assertTrue(launcher_calls[0].kwargs["start_new_session"])


if __name__ == "__main__":
    unittest.main()
