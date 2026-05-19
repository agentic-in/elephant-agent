from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[3]


class WheelInstallSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        shutil.rmtree(ROOT / "build", ignore_errors=True)
        shutil.rmtree(ROOT / "elephant.elephant-info", ignore_errors=True)
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.build_venv = self.root / "build-venv"
        self.install_venv = self.root / "install-venv"
        self.dist_dir = self.root / "dist"
        self.home_dir = self.root / "elephant-home"

    def tearDown(self) -> None:
        shutil.rmtree(ROOT / "build", ignore_errors=True)
        shutil.rmtree(ROOT / "elephant.elephant-info", ignore_errors=True)
        self.tempdir.cleanup()

    def _python_bin(self, venv_dir: Path) -> Path:
        if os.name == "nt":
            return venv_dir / "Scripts" / "python.exe"
        return venv_dir / "bin" / "python"

    def _elephant_bin(self) -> Path:
        if os.name == "nt":
            return self.install_venv / "Scripts" / "elephant.exe"
        return self.install_venv / "bin" / "elephant"

    def test_built_wheel_installs_cleanly(self) -> None:
        subprocess.run(
            [sys.executable, "-m", "venv", str(self.build_venv)],
            cwd=ROOT,
            check=True,
            text=True,
        )
        build_python = self._python_bin(self.build_venv)
        subprocess.run(
            [
                str(build_python),
                "-m",
                "pip",
                "wheel",
                ".",
                "--no-deps",
                "-w",
                str(self.dist_dir),
            ],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )

        wheels = tuple(self.dist_dir.glob("elephant-*.whl"))
        self.assertEqual(len(wheels), 1)
        with zipfile.ZipFile(wheels[0]) as wheel:
            self.assertNotIn("packages/state/ELEPHANT.md", wheel.namelist())

        subprocess.run(
            [sys.executable, "-m", "venv", str(self.install_venv)],
            cwd=ROOT,
            check=True,
            text=True,
        )
        install_python = self._python_bin(self.install_venv)
        subprocess.run(
            [str(install_python), "-m", "pip", "install", str(wheels[0])],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )

        env = os.environ.copy()
        env["ELEPHANT_HOME"] = str(self.home_dir)
        overview = subprocess.run(
            [str(self._elephant_bin())],
            cwd=self.root,
            env=env,
            check=True,
            text=True,
            capture_output=True,
        )
        self.assertIn("Elephant Agent CLI", overview.stdout)
        self.assertIn("personal-model-first AI", overview.stdout)
        self.assertIn("elephant init", overview.stdout)

        health = subprocess.run(
            [str(self._elephant_bin()), "status"],
            cwd=self.root,
            env=env,
            check=True,
            text=True,
            capture_output=True,
        )
        self.assertIn("Elephant Agent status", health.stdout)
        self.assertIn("provider_status · preview", health.stdout)


if __name__ == "__main__":
    unittest.main()
