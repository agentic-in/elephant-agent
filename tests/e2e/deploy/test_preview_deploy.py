from __future__ import annotations

from pathlib import Path
import shutil
import socket
import subprocess
import time
import unittest
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[3]


class PreviewDeploySmokeTest(unittest.TestCase):
    def test_preview_assets_and_docker_smoke(self) -> None:
        docker = shutil.which("docker")

        dockerfile = ROOT / "deploy" / "docker" / "preview.Dockerfile"
        compose = ROOT / "deploy" / "docker" / "docker-compose.preview.yml"
        systemd_unit = ROOT / "deploy" / "systemd" / "elephant-preview.service"

        self.assertTrue(dockerfile.exists())
        self.assertTrue(compose.exists())
        self.assertTrue(systemd_unit.exists())

        dockerfile_text = dockerfile.read_text(encoding="utf-8")
        compose_text = compose.read_text(encoding="utf-8")
        unit_text = systemd_unit.read_text(encoding="utf-8")
        self.assertIn("apps/site/dist", dockerfile_text)
        self.assertIn("docker compose", unit_text)
        self.assertIn("4180:8080", compose_text)

        subprocess.run(["make", "site-build"], cwd=ROOT, check=True, text=True)
        dist_index = ROOT / "apps" / "site" / "dist" / "index.html"
        dist_docs = ROOT / "apps" / "site" / "dist" / "docs" / "index.html"
        dist_docs_system_model = (
            ROOT / "apps" / "site" / "dist" / "docs" / "philosophy" / "system-model" / "index.html"
        )
        dist_docs_tools = (
            ROOT
            / "apps"
            / "site"
            / "dist"
            / "docs"
            / "capacities"
            / "tools"
            / "index.html"
        )
        dist_install_script = ROOT / "apps" / "site" / "dist" / "install.sh"
        dist_robots = ROOT / "apps" / "site" / "dist" / "robots.txt"
        dist_sitemap = ROOT / "apps" / "site" / "dist" / "sitemap.xml"
        self.assertTrue(dist_index.exists())
        self.assertTrue(dist_docs.exists())
        self.assertTrue(dist_docs_system_model.exists())
        self.assertTrue(dist_docs_tools.exists())
        self.assertFalse((ROOT / "apps" / "site" / "dist" / "docs" / "system-design").exists())
        self.assertTrue(dist_install_script.exists())
        self.assertTrue(dist_robots.exists())
        self.assertTrue(dist_sitemap.exists())
        install_script_text = dist_install_script.read_text(encoding="utf-8")
        index_text = dist_index.read_text(encoding="utf-8")
        docs_tools_text = dist_docs_tools.read_text(encoding="utf-8")
        robots_text = dist_robots.read_text(encoding="utf-8")
        self.assertIn('channel="${ELEPHANT_INSTALL_CHANNEL:-dev}"', install_script_text)
        self.assertIn('package_name="elephant-agent"', install_script_text)
        self.assertIn(
            '<link data-rh="true" rel="canonical" href="https://elephant.agentic-in.ai/"',
            index_text,
        )
        self.assertIn(
            '<meta data-rh="true" name="description" content="Elephant Agent is personal-model-first AI: it turns memory into correctable understanding, then gets curious at your pace."',
            index_text,
        )
        self.assertIn(
            '<title data-rh="true">Tools | Elephant Agent</title>',
            docs_tools_text,
        )
        self.assertIn(
            '<meta data-rh="true" name="description" content="Elephant Agent combines a curated built-in tool surface with conversation-first execution so you can stay in one durable shell."',
            docs_tools_text,
        )
        self.assertIn("Sitemap: https://elephant.agentic-in.ai/sitemap.xml", robots_text)

        if docker is None:
            self.skipTest("docker is not installed")

        if not _docker_daemon_ready(docker):
            self.skipTest("docker daemon is not available")

        image_name = "elephant-preview:test"
        subprocess.run(
            [docker, "build", "-f", str(dockerfile), "-t", image_name, "."],
            cwd=ROOT,
            check=True,
            text=True,
        )

        port = _free_port()
        container = subprocess.run(
            [docker, "run", "-d", "-p", f"127.0.0.1:{port}:8080", image_name],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        try:
            body = _wait_for_http(port)
            self.assertIn("Elephant Agent", body)
            docs_body = _wait_for_http(port, path="/docs/")
            self.assertIn("personal-model-first AI", docs_body)
            install_body = _wait_for_http(port, path="/install.sh")
            self.assertIn("Installed Elephant Agent CLI launcher", install_body)
        finally:
            subprocess.run([docker, "rm", "-f", container], cwd=ROOT, check=False, text=True)


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    _, port = sock.getsockname()
    sock.close()
    return port


def _docker_daemon_ready(docker: str) -> bool:
    result = subprocess.run(
        [docker, "info"],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    return result.returncode == 0


def _wait_for_http(port: int, timeout: float = 30.0, path: str = "/") -> str:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as response:
                return response.read().decode("utf-8")
        except Exception as exc:  # pragma: no cover - best-effort smoke loop
            last_error = exc
            time.sleep(0.5)
    raise AssertionError(f"Timed out waiting for preview container: {last_error}")


if __name__ == "__main__":
    unittest.main()
