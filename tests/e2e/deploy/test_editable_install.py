from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]


class EditableInstallSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.venv_dir = self.root / "venv"
        self.home_dir = self.root / "elephant-home"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _python_bin(self) -> Path:
        if os.name == "nt":
            return self.venv_dir / "Scripts" / "python.exe"
        return self.venv_dir / "bin" / "python"

    def _elephant_bin(self) -> Path:
        if os.name == "nt":
            return self.venv_dir / "Scripts" / "elephant.exe"
        return self.venv_dir / "bin" / "elephant"

    def _run(self, *args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self._elephant_bin()), *args],
            cwd=self.root,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )

    def test_editable_install_exposes_elephant_command(self) -> None:
        subprocess.run([sys.executable, "-m", "venv", str(self.venv_dir)], cwd=ROOT, check=True, text=True)
        python_bin = self._python_bin()
        subprocess.run(
            [str(python_bin), "-m", "pip", "install", "-e", "."],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )

        env = os.environ.copy()
        env["ELEPHANT_HOME"] = str(self.home_dir)

        overview = self._run(env=env)
        self.assertIn("Elephant Agent CLI", overview.stdout)
        self.assertIn("personal-model-first AI", overview.stdout)
        self.assertIn("Model what matters", overview.stdout)
        self.assertIn("elephant init", overview.stdout)

        state_dir = self.home_dir / "herd"
        config_path = self.home_dir / "config.yaml"
        self.assertTrue(config_path.exists())
        self.assertTrue(state_dir.exists())

        health = self._run("status", env=env)
        self.assertIn("Elephant Agent status", health.stdout)
        self.assertIn("provider_status · preview", health.stdout)

        gateway = self._run("gateway", "describe", env=env)
        payload = json.loads(gateway.stdout)
        self.assertEqual(payload["gateway"]["state_dir"], str(state_dir))
        self.assertTrue(payload["feishu"]["control"]["enabled"])
        self.assertEqual(payload["feishu"]["control"]["runtime"], "shared-runtime")

        im = self._run("gateway", "feishu", "setup", "--no-wizard", env=env)
        self.assertIn("Configured Feishu IM", im.stdout)
        self.assertIn("elephant gateway feishu start", im.stdout)


if __name__ == "__main__":
    unittest.main()
