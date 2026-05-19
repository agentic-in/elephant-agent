from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from apps.cli.runtime import CliRuntime
from apps.cli.runtime_extensions import load_extension_manifest, serialize_manifest_path


class CliRuntimeExtensionsTest(unittest.TestCase):
    def test_load_extension_manifest_resolves_relative_paths_per_section(self) -> None:
        profile_dir = Path("/tmp/elephant-profile")
        manifest = load_extension_manifest(
            {
                "tool_overrides": {"tool.shell.exec": {"enabled": False}},
                "tool_manifests": ["tooling/demo-tool.yaml"],
                "skill_overrides": {"skill.shell": {"enabled": True}},
                "skill_manifests": ["skills/demo-skill.yaml"],
                "skill_packages": ["packages/focus-skill"],
                "mcp_overrides": {"filesystem": {"enabled": False}},
                "mcp_servers": [{"server_id": "filesystem"}],
            },
            profile_dir=profile_dir,
        )

        self.assertEqual(manifest.tool_overrides, {"tool.shell.exec": False})
        self.assertEqual(manifest.tool_manifest_paths, (profile_dir / "tooling/demo-tool.yaml",))
        self.assertEqual(manifest.skill_overrides, {"skill.shell": True})
        self.assertEqual(manifest.skill_manifest_paths, (profile_dir / "skills/demo-skill.yaml",))
        self.assertEqual(manifest.skill_package_paths, (profile_dir / "packages/focus-skill",))
        self.assertFalse(hasattr(manifest, "mcp_overrides"))
        self.assertFalse(hasattr(manifest, "mcp_definitions"))

    def test_serialize_manifest_path_keeps_relative_paths_inside_profile_dir(
        self,
    ) -> None:
        profile_dir = Path("/tmp/elephant-profile")

        self.assertEqual(
            serialize_manifest_path(profile_dir / "skills/demo-skill.yaml", profile_dir=profile_dir),
            "skills/demo-skill.yaml",
        )
        self.assertEqual(
            serialize_manifest_path(Path("/opt/shared/tool.yaml"), profile_dir=profile_dir),
            "/opt/shared/tool.yaml",
        )

    def test_cli_tool_catalog_includes_global_custom_mcp_tools_after_refresh(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            state_dir = root / "state"
            profile_dir = root / "profiles" / "default"
            state_dir.mkdir(parents=True, exist_ok=True)
            profile_dir.mkdir(parents=True, exist_ok=True)
            (profile_dir / "profile.json").write_text(
                json.dumps(
                    {
                        "profile_id": "profile-companion",
                        "display_name": "Elephant Agent",
                        "mode": "companion",
                    }
                ),
                encoding="utf-8",
            )
            (root / "config.yaml").write_text(
                json.dumps(
                    {
                        "mcp_servers": {
                            "filesystem": {
                                "label": "Filesystem",
                                "transport": "stdio",
                                "command": "npx",
                                "args": [
                                    "-y",
                                    "@modelcontextprotocol/server-filesystem",
                                    "/tmp/demo",
                                ],
                                "tools": {
                                    "read_file": {
                                        "display_name": "Read File",
                                        "description": "Read one file from the mounted root.",
                                        "reads_state": True,
                                        "schema": {
                                            "type": "object",
                                            "properties": {"path": {"type": "string"}},
                                            "required": ["path"],
                                        },
                                    }
                                },
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            runtime = CliRuntime.create(state_dir=state_dir, profile_dir=profile_dir)
            session = runtime.start()

            tools = runtime.tool_catalog(session_id=session.session_id, audience="model")
            visible_tool_ids = {tool.tool_id for tool in tools if tool.enabled and tool.available}

            self.assertIn("mcp.filesystem.read_file", visible_tool_ids)
            self.assertTrue(any(not tool_id.startswith("mcp.") for tool_id in visible_tool_ids))


if __name__ == "__main__":
    unittest.main()
