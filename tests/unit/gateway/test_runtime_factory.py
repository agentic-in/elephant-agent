from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from apps.gateway.runtime_factory import build_gateway_app
from packages.runtime_config import default_global_config, write_global_config
from packages.sandbox import SandboxToolExecutor


class GatewayRuntimeFactorySandboxConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="test-gateway-runtime-factory-"))
        self.cli_root = self.base / "cli-home"
        self.gateway_root = self.base / "gateway-home"
        self.cli_state_dir = self.cli_root / "herd"
        self.gateway_state_dir = self.gateway_root / "herd"
        self.cli_state_dir.mkdir(parents=True)
        self.gateway_state_dir.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.base, ignore_errors=True)

    def test_tool_runtime_uses_control_state_dir_for_sandbox_config(self) -> None:
        cli_config = default_global_config(state_dir=self.cli_state_dir)
        cli_config["sandbox"] = {
            "mode": "all",
            "backend": "local",
            "scope": "session",
            "workspace_access": "full",
        }
        write_global_config(self.cli_root / "config.yaml", cli_config)
        write_global_config(
            self.gateway_root / "config.yaml",
            default_global_config(state_dir=self.gateway_state_dir),
        )

        with mock.patch(
            "apps.learning_worker_runtime.ensure_learning_worker_running",
            return_value=False,
        ):
            app, _, _ = build_gateway_app(
                state_dir=self.gateway_state_dir,
                control_state_dir=self.cli_state_dir,
            )

        self.assertEqual(app.repository.database_path, self.gateway_state_dir / "elephant.sqlite3")
        assert app.tool_runtime is not None
        self.assertIsInstance(app.tool_runtime.executor, SandboxToolExecutor)
