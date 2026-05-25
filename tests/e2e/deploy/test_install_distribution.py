from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]


class InstallDistributionSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.install_root = self.root / "install-root"
        self.bin_dir = self.root / "bin"
        self.launcher = self.bin_dir / "elephant"
        self.config_path = self.install_root / "config.yaml"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _run_install(self, *args: str) -> subprocess.CompletedProcess[str]:
        command = [
            "bash",
            str(ROOT / "scripts" / "install.sh"),
            *args,
            "--install-root",
            str(self.install_root),
            "--bin-dir",
            str(self.bin_dir),
            "--python",
            sys.executable,
        ]
        try:
            return subprocess.run(
                command,
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            self.fail(
                "install command timed out after 300s: "
                + " ".join(command)
                + f"\nstdout:\n{stdout}\nstderr:\n{stderr}"
            )

    def _run_launcher(self, *args: str) -> subprocess.CompletedProcess[str]:
        command = [str(self.launcher), *args]
        return subprocess.run(
            command,
            cwd=self.root,
            text=True,
            capture_output=True,
            check=True,
        )

    def test_install_upgrade_and_health(self) -> None:
        installed = self._run_install("install")
        self.assertIn("Installed Elephant Agent CLI launcher", installed.stdout)
        self.assertIn("Launching Elephant Agent", installed.stdout)
        self.assertIn("Elephant Agent CLI", installed.stdout)
        self.assertIn("personal-model-first AI", installed.stdout)
        self.assertIn("elephant init", installed.stdout)

        self.assertTrue(self.launcher.exists())
        self.assertTrue(self.config_path.exists())
        self.assertFalse((self.install_root / "profile").exists())

        overview = self._run_launcher()
        self.assertIn("Elephant Agent CLI", overview.stdout)
        self.assertIn("personal-model-first AI", overview.stdout)
        self.assertIn("Model what matters", overview.stdout)
        self.assertIn("elephant init", overview.stdout)
        self.assertIn("skills", overview.stdout)
        self.assertIn("dashboard", overview.stdout)

        help_output = self._run_launcher("--help")
        self.assertIn("skills", help_output.stdout)
        self.assertIn("gateway", help_output.stdout)
        self.assertIn("dashboard", help_output.stdout)

        upgraded = self._run_install("upgrade", "--skip-run")
        self.assertIn("Installed Elephant Agent CLI launcher", upgraded.stdout)
        self.assertNotIn("Launching Elephant Agent", upgraded.stdout)
        self.assertTrue(self.config_path.exists())

        health = self._run_install("health")
        self.assertIn("Elephant Agent status", health.stdout)
        self.assertIn("provider_status · preview", health.stdout)


if __name__ == "__main__":
    unittest.main()
