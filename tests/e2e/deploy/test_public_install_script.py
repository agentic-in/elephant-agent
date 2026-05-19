from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[3]


class PublicInstallScriptSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.install_root = self.root / "install-root"
        self.bin_dir = self.root / "bin"
        self.launcher = self.bin_dir / "elephant"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _run_install(self, *args: str) -> subprocess.CompletedProcess[str]:
        command = [
            "bash",
            str(ROOT / "install.sh"),
            *args,
            "--install-root",
            str(self.install_root),
            "--bin-dir",
            str(self.bin_dir),
            "--python",
            sys.executable,
            "--pip-spec",
            str(ROOT),
        ]
        env = {**os.environ, "ELEPHANT_SKIP_BROWSER_INSTALL": "1"}
        return subprocess.run(
            command,
            cwd=ROOT,
            env={**env},
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
        self.assertTrue((self.install_root / "venv" / "bin" / "python").exists())
        self.assertTrue((self.install_root / "config.yaml").exists())
        self.assertFalse((self.install_root / "profile").exists())

        overview = subprocess.run(
            [str(self.launcher)],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertIn("Elephant Agent CLI", overview.stdout)
        self.assertIn("personal-model-first AI", overview.stdout)
        self.assertIn("elephant init", overview.stdout)
        launcher_content = self.launcher.read_text(encoding="utf-8")
        self.assertIn("ELEPHANT_HERD_DIR", launcher_content)
        self.assertNotIn("ELEPHANT_GATEWAY_DIR", launcher_content)
        self.assertNotIn("ELEPHANT_PROFILE_DIR", launcher_content)
        self.assertFalse((self.install_root / "gateway").exists())

        upgraded = self._run_install("upgrade", "--skip-run")
        self.assertIn("Installed Elephant Agent CLI launcher", upgraded.stdout)
        self.assertNotIn("Launching Elephant Agent", upgraded.stdout)

        health = self._run_install("health")
        self.assertIn("Elephant Agent status", health.stdout)

    def test_public_install_script_defaults_to_dev_channel_and_supports_stable_override(
        self,
    ) -> None:
        content = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertIn('channel="${ELEPHANT_INSTALL_CHANNEL:-dev}"', content)
        self.assertIn("--channel CHANNEL", content)
        self.assertIn("--pip-spec SPEC", content)
        self.assertIn('"${venv_python}" -m pip install --upgrade --pre "${package_name}"', content)
        self.assertIn('"${venv_python}" -m pip install --upgrade "${package_name}"', content)
        self.assertIn('"${venv_python}" -m playwright install chromium', content)
        self.assertIn("ELEPHANT_SKIP_BROWSER_INSTALL", content)
        self.assertIn("has_uv", content)
        self.assertIn("uv pip install --python", content)
        self.assertIn("--prerelease=allow", content)

    def test_publish_workflow_builds_dev_versions_from_main(self) -> None:
        content = (ROOT / ".github" / "workflows" / "pypi-publish.yml").read_text(encoding="utf-8")
        makefile_content = (ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn("branches:", content)
        self.assertIn("- main", content)
        self.assertIn("environment: PYPI_API_TOKEN", content)
        self.assertIn("f'version = \"{target}\"'", content)
        self.assertIn('base = re.sub(r"\\.dev\\d+$", "", current)', content)
        self.assertIn("make package-build", content)
        self.assertIn("make package-verify", content)
        self.assertIn("apps/site/node_modules", makefile_content)
        self.assertIn("uvx twine check dist/*", makefile_content)
        self.assertIn("uv build", makefile_content)
        self.assertIn("Missing PYPI_API_TOKEN for the publish job", content)
        self.assertIn("curl -fsSL https://elephant.agentic-in.ai/install.sh | bash", content)
        self.assertIn("pip install elephant-agent==", content)

    def test_pyproject_excludes_site_packages_from_python_distribution(self) -> None:
        content = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn(
            'include = ["apps", "apps.api*", "apps.cli*", "apps.dashboard*", "apps.gateway*", "packages*"]',
            content,
        )
        self.assertIn('exclude = ["tests*", ".worktrees*", "apps.site*"]', content)
        self.assertIn('"apps.dashboard" = ["dist/*", "dist/assets/*"]', content)

    def test_pyproject_bundles_feishu_sdk_by_default(self) -> None:
        payload = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        dependencies = payload["project"]["dependencies"]
        self.assertIn("lark-oapi>=1.5.3,<2", dependencies)
        self.assertIn("playwright>=1.51,<2", dependencies)
        self.assertNotIn("optional-dependencies", payload["project"])

    def test_site_build_script_uses_portable_mktemp_template(self) -> None:
        content = (ROOT / "apps" / "site" / "build.sh").read_text(encoding="utf-8")
        self.assertIn('mktemp "${TMPDIR:-/tmp}/elephant-site-build.XXXXXX"', content)


if __name__ == "__main__":
    unittest.main()
