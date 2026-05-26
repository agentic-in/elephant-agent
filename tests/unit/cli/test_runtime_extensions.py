from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from apps.cli.runtime import CliRuntime
from apps.cli.runtime_extensions import load_extension_manifest, serialize_manifest_path
from packages.contracts.runtime import ExecutionResult


class _StubClarifySurface:
    def __init__(self, label: str) -> None:
        self.label = label

    def request_clarification(
        self,
        *,
        session_id: str,
        question: str,
        mode: str,
        choices: tuple[str, ...] = (),
    ) -> ExecutionResult:
        return ExecutionResult(
            execution_id=f"clarify:{session_id}:{uuid4().hex[:8]}",
            episode_id=session_id,
            outcome="needs_input",
            summary=f"surface={self.label}; question={question}; mode={mode}; choices={','.join(choices)}",
            side_effects=("clarify",),
        )


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

    def test_serialize_manifest_path_keeps_relative_paths_inside_profile_dir(self) -> None:
        profile_dir = Path("/tmp/elephant-profile")

        self.assertEqual(
            serialize_manifest_path(profile_dir / "skills/demo-skill.yaml", profile_dir=profile_dir),
            "skills/demo-skill.yaml",
        )
        self.assertEqual(
            serialize_manifest_path(Path("/opt/shared/tool.yaml"), profile_dir=profile_dir),
            "/opt/shared/tool.yaml",
        )

    def test_cli_tool_catalog_includes_global_custom_mcp_tools_after_refresh(self) -> None:
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
                                "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp/demo"],
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

            runtime = CliRuntime.create(state_dir=state_dir)
            session = runtime.start()

            tools = runtime.tool_catalog(session_id=session.episode_id, audience="model")
            visible_tool_ids = {tool.tool_id for tool in tools if tool.enabled and tool.available}

            self.assertIn("mcp.filesystem.read_file", visible_tool_ids)
            self.assertTrue(any(not tool_id.startswith("mcp.") for tool_id in visible_tool_ids))

    def test_prepare_session_surface_reuses_existing_tool_runtime_when_extensions_unchanged(self) -> None:
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

            runtime = CliRuntime.create(state_dir=state_dir)
            session = runtime.start()
            original_tool_runtime = runtime.tool_runtime
            original_executor = runtime.tool_runtime.executor

            runtime.prepare_session_surface(session.episode_id, steady_embeddings=False)

            self.assertIs(runtime.tool_runtime, original_tool_runtime)
            self.assertIs(runtime.tool_runtime.executor, original_executor)

    def test_set_clarify_surface_updates_delegate_without_rebuilding_tool_runtime(self) -> None:
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

            runtime = CliRuntime.create(state_dir=state_dir)
            session = runtime.start()
            original_surface = runtime.clarify_surface
            original_tool_runtime = runtime.tool_runtime
            original_executor = runtime.tool_runtime.executor

            runtime.set_clarify_surface(_StubClarifySurface("interactive"))
            interactive_result = runtime.run_tool(
                "tool.clarify",
                {"question": "Which target should I use?", "choices": ["alpha", "beta"]},
                session_id=session.episode_id,
            )

            runtime.set_clarify_surface(original_surface)
            restored_result = runtime.run_tool(
                "tool.clarify",
                {"question": "Which target should I use?", "choices": ["alpha"]},
                session_id=session.episode_id,
            )

            self.assertIs(runtime.tool_runtime, original_tool_runtime)
            self.assertIs(runtime.tool_runtime.executor, original_executor)
            self.assertIn("surface=interactive", interactive_result.summary)
            self.assertIn("surface: cli", restored_result.summary)


if __name__ == "__main__":
    unittest.main()
