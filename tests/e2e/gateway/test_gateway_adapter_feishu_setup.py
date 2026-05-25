from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import sys
import unittest
from unittest import mock

from apps.gateway import (
    DEFAULT_FEISHU_APP_ID_ENV,
    DEFAULT_FEISHU_APP_SECRET_ENV,
    FEISHU_ADAPTER_ID,
    FeishuGatewayService,
    load_feishu_gateway_accounts,
)
import apps.gateway.__main__ as gateway_main
from apps.gateway.__main__ import command_main
from packages.gateway_core import DEFAULT_GATEWAY_ACCOUNT_ID
from tests.e2e.gateway.gateway_adapter_test_base import GatewayAdapterTestBase


class GatewayAdapterFeishuSetupE2ETests(GatewayAdapterTestBase):
    def test_gateway_add_feishu_command_writes_secret_reference_profile_config(
        self,
    ) -> None:
        self._update_manifest(lambda payload: payload.pop("gateway", None))
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = command_main(
                [
                    "feishu",
                    "setup",
                    "--state-dir",
                    str(self.state_dir),
                    "--cli-state-dir",
                    str(self.state_dir),
                    "--no-start",
                ]
            )
        self.assertEqual(exit_code, 0)
        rendered = output.getvalue()
        self.assertIn("Configured Feishu IM", rendered)
        self.assertIn("elephant gateway feishu start", rendered)
        manifest = self._read_runtime_manifest()
        self.assertIn("provider_profile", manifest)
        feishu = manifest["gateway"]["adapters"]["feishu"]
        self.assertTrue(feishu["enabled"])
        self.assertEqual(feishu["surface"], "long-connection")
        self.assertNotIn("default_elephant_id", feishu.get("control", {}))
        self.assertNotIn("default_session_id", feishu.get("control", {}))
        self.assertNotIn("auto_create_elephant", feishu.get("control", {}))
        self.assertEqual(len(feishu["accounts"]), 1)
        account = feishu["accounts"][0]
        self.assertEqual(account["account_id"], DEFAULT_GATEWAY_ACCOUNT_ID)
        self.assertEqual(account["surface"], "long-connection")
        self.assertEqual(account["event_path"], "/feishu/events")
        self.assertEqual(
            account["secret_references"],
            [
                {
                    "reference_id": "secret-feishu-default-app-id",
                    "provider_id": FEISHU_ADAPTER_ID,
                    "secret_name": "app_id",
                    "secret_key": "app_id",
                    "metadata": {"env_var": DEFAULT_FEISHU_APP_ID_ENV},
                },
                {
                    "reference_id": "secret-feishu-default-app-secret",
                    "provider_id": FEISHU_ADAPTER_ID,
                    "secret_name": "app_secret",
                    "secret_key": "app_secret",
                    "metadata": {"env_var": DEFAULT_FEISHU_APP_SECRET_ENV},
                },
            ],
        )
        app, _, _ = self._build()
        accounts = load_feishu_gateway_accounts(app, respect_enabled=False)
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0].account_id, DEFAULT_GATEWAY_ACCOUNT_ID)
        self.assertEqual(accounts[0].surface, "long-connection")
        self.assertEqual(
            tuple(
                (reference.reference_id for reference in accounts[0].secret_references)
            ),
            ("secret-feishu-default-app-id", "secret-feishu-default-app-secret"),
        )
        description = FeishuGatewayService(app=app, respect_enabled=False).describe()
        described_account = description["accounts"][0]
        self.assertEqual(described_account["credentials_source"], "secret_references")
        self.assertEqual(
            described_account["secret_reference_ids"],
            ("secret-feishu-default-app-id", "secret-feishu-default-app-secret"),
        )
        self.ensure_feishu_sdk.assert_called_with(reason="Feishu setup")

    def test_ensure_feishu_sdk_available_installs_missing_dependency(self) -> None:
        self.ensure_feishu_sdk_patcher.stop()
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
                installed = gateway_main._ensure_feishu_sdk_available(
                    reason="Feishu setup"
                )
            self.assertTrue(installed)
            run.assert_called_once_with(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    gateway_main.FEISHU_SDK_PIP_SPEC,
                ],
                check=True,
            )
            rendered = output.getvalue()
            self.assertIn("Preparing Feishu support for Feishu setup...", rendered)
            self.assertIn("Feishu support is ready.", rendered)
        finally:
            self.ensure_feishu_sdk = self.ensure_feishu_sdk_patcher.start()

    def test_gateway_add_feishu_command_updates_existing_account_without_clobbering_profile(
        self,
    ) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = command_main(
                [
                    "feishu",
                    "setup",
                    "--state-dir",
                    str(self.state_dir),
                    "--cli-state-dir",
                    str(self.state_dir),
                    "--account-id",
                    "ops-feishu",
                    "--transport",
                    "long-connection",
                    "--no-start",
                    "--app-id-env-var",
                    "ELEPHANT_UPDATED_FEISHU_APP_ID",
                    "--app-secret-env-var",
                    "ELEPHANT_UPDATED_FEISHU_APP_SECRET",
                    "--enabled",
                ]
            )
        self.assertEqual(exit_code, 0)
        manifest = self._read_runtime_manifest()
        self.assertEqual(
            manifest["provider_profile"]["profile_id"], "provider-openrouter"
        )
        feishu = manifest["gateway"]["adapters"]["feishu"]
        self.assertTrue(feishu["enabled"])
        self.assertEqual(feishu["surface"], "long-connection")
        self.assertEqual(len(feishu["accounts"]), 1)
        account = feishu["accounts"][0]
        self.assertEqual(account["account_id"], "ops-feishu")
        self.assertEqual(account["surface"], "long-connection")
        self.assertEqual(account["event_path"], "/hooks/feishu")
        self.assertEqual(
            account["secret_references"],
            [
                {
                    "reference_id": "secret-feishu-ops-feishu-app-id",
                    "provider_id": FEISHU_ADAPTER_ID,
                    "secret_name": "app_id",
                    "secret_key": "app_id",
                    "metadata": {"env_var": "ELEPHANT_UPDATED_FEISHU_APP_ID"},
                },
                {
                    "reference_id": "secret-feishu-ops-feishu-app-secret",
                    "provider_id": FEISHU_ADAPTER_ID,
                    "secret_name": "app_secret",
                    "secret_key": "app_secret",
                    "metadata": {"env_var": "ELEPHANT_UPDATED_FEISHU_APP_SECRET"},
                },
            ],
        )
        app, _, _ = self._build()
        accounts = load_feishu_gateway_accounts(app)
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0].account_id, "ops-feishu")
        self.assertEqual(accounts[0].surface, "long-connection")
        self.assertEqual(accounts[0].event_path, "/hooks/feishu")
        self.assertEqual(
            tuple(
                (reference.reference_id for reference in accounts[0].secret_references)
            ),
            ("secret-feishu-ops-feishu-app-id", "secret-feishu-ops-feishu-app-secret"),
        )
        description = FeishuGatewayService(app=app).describe()
        described_account = description["accounts"][0]
        self.assertEqual(described_account["credentials_source"], "secret_references")
        self.assertEqual(
            described_account["secret_reference_ids"],
            ("secret-feishu-ops-feishu-app-id", "secret-feishu-ops-feishu-app-secret"),
        )

    def test_gateway_add_feishu_command_persists_local_secret_file_for_raw_credentials(
        self,
    ) -> None:
        self._update_manifest(lambda payload: payload.pop("gateway", None))
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = command_main(
                [
                    "feishu",
                    "setup",
                    "--state-dir",
                    str(self.state_dir),
                    "--cli-state-dir",
                    str(self.state_dir),
                    "--no-wizard",
                    "--no-start",
                    "--app-id",
                    "cli-app-id-123",
                    "--app-secret",
                    "cli-app-secret-456",
                ]
            )
        self.assertEqual(exit_code, 0)
        rendered = output.getvalue()
        self.assertIn("Local IM secret file:", rendered)
        secret_path = self.state_dir / "gateway-local-secrets.json"
        self.assertTrue(secret_path.exists())
        local_secrets = json.loads(secret_path.read_text(encoding="utf-8"))
        self.assertEqual(local_secrets[DEFAULT_FEISHU_APP_ID_ENV], "cli-app-id-123")
        self.assertEqual(
            local_secrets[DEFAULT_FEISHU_APP_SECRET_ENV], "cli-app-secret-456"
        )
        describe_output = io.StringIO()
        with redirect_stdout(describe_output):
            exit_code = command_main(
                ["feishu", "describe"],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )
        self.assertEqual(exit_code, 0)
        described = json.loads(describe_output.getvalue())
        account = described["feishu"]["accounts"][0]
        self.assertEqual(account["credentials_status"], "configured")
        self.assertEqual(account["resolved_app_id"], "cli-app-id-123")

    def test_im_setup_command_can_capture_raw_credentials(self) -> None:
        self._update_manifest(lambda payload: payload.pop("gateway", None))
        scripted_answers = iter(["3", "wizard-app-id-789"])
        output = io.StringIO()
        with (
            mock.patch(
                "apps.gateway.gateway_main_setup_impl._start_feishu_runtime_after_setup",
                return_value=0,
            ) as auto_start,
            mock.patch(
                "builtins.input", side_effect=lambda _prompt="": next(scripted_answers)
            ),
            mock.patch(
                "apps.gateway.gateway_main_setup_impl.getpass.getpass",
                return_value="wizard-app-secret-789",
            ),
            redirect_stdout(output),
        ):
            exit_code = command_main(
                ["setup"],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )
        self.assertEqual(exit_code, 0)
        rendered = output.getvalue()
        self.assertIn(
            "Starting the configured Feishu bridge in the background...", rendered
        )
        self.assertIn("Feishu setup is complete.", rendered)
        auto_start.assert_called_once()
        self.assertEqual(auto_start.call_args.kwargs["transport"], "long-connection")
        manifest = self._read_runtime_manifest()
        feishu = manifest["gateway"]["adapters"]["feishu"]
        account = feishu["accounts"][0]
        self.assertEqual(account["account_id"], DEFAULT_GATEWAY_ACCOUNT_ID)
        self.assertNotIn("default_elephant_id", feishu.get("control", {}))
        self.assertNotIn("default_session_id", feishu.get("control", {}))
        self.assertNotIn("auto_create_elephant", feishu.get("control", {}))
        self.assertNotIn("allow_group_chats", feishu.get("control", {}))
        self.assertEqual(
            account["secret_references"],
            [
                {
                    "reference_id": "secret-feishu-default-app-id",
                    "provider_id": FEISHU_ADAPTER_ID,
                    "secret_name": "app_id",
                    "secret_key": "app_id",
                    "metadata": {"env_var": DEFAULT_FEISHU_APP_ID_ENV},
                },
                {
                    "reference_id": "secret-feishu-default-app-secret",
                    "provider_id": FEISHU_ADAPTER_ID,
                    "secret_name": "app_secret",
                    "secret_key": "app_secret",
                    "metadata": {"env_var": DEFAULT_FEISHU_APP_SECRET_ENV},
                },
            ],
        )
        local_secrets = json.loads(
            (self.state_dir / "gateway-local-secrets.json").read_text(encoding="utf-8")
        )
        self.assertEqual(local_secrets[DEFAULT_FEISHU_APP_ID_ENV], "wizard-app-id-789")
        self.assertEqual(
            local_secrets[DEFAULT_FEISHU_APP_SECRET_ENV], "wizard-app-secret-789"
        )

    def test_im_setup_command_does_not_capture_elephant_defaults(self) -> None:
        self._update_manifest(lambda payload: payload.pop("gateway", None))
        scripted_answers = iter(["3", "wizard-app-id-single"])
        with (
            mock.patch(
                "apps.gateway.gateway_main_setup_impl._start_feishu_runtime_after_setup",
                return_value=0,
            ),
            mock.patch(
                "builtins.input", side_effect=lambda _prompt="": next(scripted_answers)
            ),
            mock.patch(
                "apps.gateway.gateway_main_setup_impl.getpass.getpass",
                return_value="wizard-app-secret-single",
            ),
        ):
            exit_code = command_main(
                ["setup"],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )
        self.assertEqual(exit_code, 0)
        manifest = self._read_runtime_manifest()
        feishu = manifest["gateway"]["adapters"]["feishu"]
        self.assertNotIn("default_elephant_id", feishu.get("control", {}))
        self.assertNotIn("default_session_id", feishu.get("control", {}))

    def test_gateway_feishu_describe_serializes_default_path_overrides(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = command_main(
                ["feishu", "describe"],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )
        self.assertEqual(exit_code, 0)
        rendered = json.loads(output.getvalue())
        control = rendered["feishu"]["control"]
        self.assertNotIn("profile_dir", control)
        self.assertEqual(control["state_dir"], str(self.state_dir))

    def test_gateway_feishu_help_lists_runtime_commands(self) -> None:
        output = io.StringIO()
        with self.assertRaises(SystemExit) as exit_info, redirect_stdout(output):
            command_main(["feishu", "-h"])
        self.assertEqual(exit_info.exception.code, 0)
        rendered = output.getvalue()
        self.assertIn(
            "{setup,remove,start,status,stop,restart,logs,describe,doctor,message}",
            rendered,
        )
        self.assertIn("setup               Add or update a Feishu account.", rendered)
        self.assertIn("remove              Remove a Feishu account.", rendered)
        self.assertIn("status              Show Feishu status.", rendered)
        self.assertIn("logs                Show logs for one Feishu account.", rendered)

    def test_gateway_feishu_without_subcommand_defaults_to_status(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = command_main(
                ["feishu"],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )
        self.assertEqual(exit_code, 0)
        rendered = output.getvalue()
        self.assertIn("Elephant Agent Gateway runtime status", rendered)
        self.assertIn("service_key: feishu", rendered)
        self.assertIn("target: long-connection", rendered)

    def test_gateway_feishu_logs_reads_tail_and_can_print_path(self) -> None:
        log_path = self.state_dir / "feishu-long-connection.log"
        log_path.write_text("line-1\nline-2\nline-3\n", encoding="utf-8")
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = command_main(
                [
                    "feishu",
                    "logs",
                    "ops-feishu",
                    "--transport",
                    "long-connection",
                    "--tail",
                    "2",
                ],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )
        self.assertEqual(exit_code, 0)
        self.assertEqual(output.getvalue().strip().splitlines(), ["line-2", "line-3"])
        path_output = io.StringIO()
        with redirect_stdout(path_output):
            exit_code = command_main(
                [
                    "feishu",
                    "logs",
                    "ops-feishu",
                    "--transport",
                    "long-connection",
                    "--path",
                ],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )
        self.assertEqual(exit_code, 0)
        self.assertEqual(path_output.getvalue().strip(), str(log_path))

    def test_gateway_feishu_status_reports_running_detached_runtime(self) -> None:
        pid_path = self.state_dir / "feishu-long-connection.pid"
        record_path = self.state_dir / "feishu-long-connection.runtime.json"
        pid_path.write_text("43210\n", encoding="utf-8")
        record_path.write_text(
            json.dumps(
                {
                    "runtime_id": "feishu:long-connection",
                    "service_key": "feishu",
                    "transport": "long-connection",
                    "status": "running",
                    "pid": 43210,
                    "pid_path": str(pid_path),
                    "log_path": str(self.state_dir / "feishu-long-connection.log"),
                    "record_path": str(record_path),
                    "command": [
                        sys.executable,
                        "-m",
                        "apps.launcher",
                        "gateway",
                        "start",
                    ],
                    "profile_dir": str(self.profile_dir),
                    "state_dir": str(self.state_dir),
                    "cli_profile_dir": str(self.profile_dir),
                    "cli_state_dir": str(self.state_dir),
                    "started_at": "2026-04-13T03:58:00+00:00",
                }
            ),
            encoding="utf-8",
        )
        output = io.StringIO()
        with (
            mock.patch("apps.gateway.__main__.os.kill", return_value=None),
            redirect_stdout(output),
        ):
            exit_code = command_main(
                ["feishu", "status", "--transport", "long-connection"],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )
        self.assertEqual(exit_code, 0)
        rendered = output.getvalue()
        self.assertIn("runtime_id: feishu:long-connection", rendered)
        self.assertIn("status: running", rendered)
        self.assertIn("pid: 43210", rendered)
        self.assertIn("pid_active: yes", rendered)
        self.assertIn("recorded_status: running", rendered)

    def test_gateway_feishu_stop_updates_runtime_record_and_cleans_pid(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = command_main(
                [
                    "feishu",
                    "stop",
                    "--transport",
                    "long-connection",
                    "--timeout",
                    "0.1",
                ],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )
        self.assertEqual(exit_code, 0)
        self.assertIn(
            "Elephant daemon is not running. Nothing to stop.", output.getvalue()
        )
        self.assertFalse((self.state_dir / "daemon.pid").exists())

    def test_gateway_feishu_restart_replaces_existing_background_runtime(self) -> None:

        class FakeProcess:
            pid = 54321

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
                    None,
                    {
                        "status": "running",
                        "pid": 54321,
                        "state_dir": str(self.state_dir),
                    },
                ],
            ),
            mock.patch("apps.gateway.__main__.time.sleep", return_value=None),
            redirect_stdout(output),
        ):
            exit_code = command_main(
                [
                    "feishu",
                    "restart",
                    "--transport",
                    "long-connection",
                    "--timeout",
                    "0.1",
                ],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )
        self.assertEqual(exit_code, 0)
        rendered = output.getvalue()
        self.assertIn("Elephant daemon is now running in the background.", rendered)
        pid_path = self.state_dir / "daemon.pid"
        record_path = self.state_dir / "daemon.runtime.json"
        self.assertEqual(pid_path.read_text(encoding="utf-8").strip(), "54321")
        record = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "running")
        self.assertEqual(record["pid"], 54321)
        launcher_calls = [
            call
            for call in popen.call_args_list
            if len(call.args) >= 1
            and call.args[0][:4] == [sys.executable, "-m", "apps.launcher", "daemon"]
        ]
        self.assertEqual(len(launcher_calls), 1)
        command = launcher_calls[0].args[0]
        self.assertEqual(command[command.index("--state-dir") + 1], str(self.state_dir))
        self.assertEqual(
            command[command.index("--cli-state-dir") + 1], str(self.state_dir)
        )

    def test_gateway_feishu_start_detach_spawns_background_process(self) -> None:

        class FakeProcess:
            pid = 43210

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
                        "pid": 43210,
                        "state_dir": str(self.state_dir),
                    },
                ],
            ),
            mock.patch("apps.gateway.__main__.time.sleep", return_value=None),
            redirect_stdout(output),
        ):
            exit_code = command_main(
                ["feishu", "start", "--transport", "long-connection", "--detach"],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )
        self.assertEqual(exit_code, 0)
        rendered = output.getvalue()
        self.assertIn("Elephant daemon is now running in the background.", rendered)
        self.assertIn("PID: 43210", rendered)
        self.assertIn("HTTP: http://127.0.0.1:8788", rendered)
        pid_path = self.state_dir / "daemon.pid"
        log_path = self.state_dir / "daemon.log"
        record_path = self.state_dir / "daemon.runtime.json"
        self.assertTrue(pid_path.exists())
        self.assertEqual(pid_path.read_text(encoding="utf-8").strip(), "43210")
        self.assertTrue(log_path.exists())
        self.assertTrue(record_path.exists())
        runtime_record = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertEqual(runtime_record["runtime_id"], "daemon:unified")
        self.assertEqual(runtime_record["status"], "running")
        self.assertEqual(runtime_record["pid"], 43210)
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
        self.assertTrue(popen.call_args.kwargs["start_new_session"])

    def test_gateway_feishu_start_detach_launches_unified_daemon_with_cli_state(
        self,
    ) -> None:

        class FakeProcess:
            pid = 43211

            def poll(self) -> None:
                return None

        output = io.StringIO()
        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch(
                "apps.gateway.__main__.subprocess.Popen", return_value=FakeProcess()
            ) as popen,
            mock.patch(
                "apps.daemon_command._daemon_healthz_payload",
                side_effect=[
                    None,
                    {
                        "status": "running",
                        "pid": 43211,
                        "state_dir": str(self.state_dir),
                    },
                ],
            ),
            mock.patch("apps.gateway.__main__.time.sleep", return_value=None),
            redirect_stdout(output),
        ):
            exit_code = command_main(
                ["feishu", "start", "--transport", "long-connection", "--detach"],
                default_state_dir=self.state_dir,
                default_control_state_dir=self.state_dir,
            )
        self.assertEqual(exit_code, 0)
        launcher_calls = [
            call
            for call in popen.call_args_list
            if len(call.args) >= 1
            and call.args[0][:4] == [sys.executable, "-m", "apps.launcher", "daemon"]
        ]
        self.assertEqual(len(launcher_calls), 1)
        command = launcher_calls[0].args[0]
        self.assertEqual(command[command.index("--state-dir") + 1], str(self.state_dir))
        self.assertEqual(
            command[command.index("--cli-state-dir") + 1], str(self.state_dir)
        )
        self.assertNotIn("env", launcher_calls[0].kwargs)


if __name__ == "__main__":
    unittest.main()
