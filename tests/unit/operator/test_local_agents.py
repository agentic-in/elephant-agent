from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from packages.operator.local_agents import scan_local_agents


class LocalAgentDiscoveryTest(unittest.TestCase):
    def test_env_override_wins_and_records_executable_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            binary = _fake_executable(Path(tmpdir), "codex", "codex 1.2.3")

            records = scan_local_agents(
                env={
                    "ELEPHANT_CODEX_PATH": str(binary),
                    "ELEPHANT_CODEX_MODEL": "gpt-5.4",
                    "PATH": "",
                }
            )

        codex = _one(records, "codex")
        self.assertEqual(codex.resolved_path, str(binary.resolve()))
        self.assertEqual(codex.source, "env")
        self.assertEqual(codex.version, "codex 1.2.3")
        self.assertEqual(codex.default_model, "gpt-5.4")
        self.assertTrue(codex.can_execute)

    def test_path_discovery_uses_supplied_env_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bin_dir = Path(tmpdir) / "bin"
            binary = _fake_executable(bin_dir, "claude", "claude 0.9.0")

            records = scan_local_agents(env={"PATH": str(bin_dir)})

        claude = _one(records, "claude")
        self.assertEqual(claude.resolved_path, str(binary.resolve()))
        self.assertEqual(claude.source, "path")

    def test_login_shell_fallback_runs_only_on_unix_like_platforms(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            binary = _fake_executable(root, "gemini", "gemini 2.0.0")
            shell = root / "sh"
            shell.write_text(f"#!/bin/sh\nprintf 'gemini\\t{binary}\\n'\n", encoding="utf-8")
            shell.chmod(0o755)

            with mock.patch("packages.operator.local_agents.platform.system", return_value="Darwin"):
                records = scan_local_agents(env={"PATH": "", "SHELL": str(shell)})

            with mock.patch("packages.operator.local_agents.platform.system", return_value="Windows"):
                windows_records = scan_local_agents(env={"PATH": "", "SHELL": str(shell)})

        gemini = _one(records, "gemini")
        self.assertEqual(gemini.source, "login_shell")
        self.assertEqual(gemini.resolved_path, str(binary.resolve()))
        self.assertFalse(any(record.provider_id == "gemini" for record in windows_records))

    def test_discovered_without_adapter_is_not_executable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bin_dir = Path(tmpdir) / "bin"
            binary = _fake_executable(bin_dir, "cursor-agent", "cursor-agent 1")

            records = scan_local_agents(env={"PATH": str(bin_dir)})

        cursor = _one(records, "cursor-agent")
        self.assertEqual(cursor.resolved_path, str(binary.resolve()))
        self.assertFalse(cursor.can_execute)
        self.assertEqual(cursor.metadata["adapter"], "")


def _fake_executable(directory: Path, name: str, version: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(f"#!/bin/sh\nprintf '%s\\n' '{version}'\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _one(records, provider_id: str):
    matches = [record for record in records if record.provider_id == provider_id]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one {provider_id} record, got {matches!r}")
    return matches[0]


if __name__ == "__main__":
    unittest.main()
