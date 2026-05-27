from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from packages.runtime_config import (
    configured_external_skill_dirs,
    default_global_config,
    global_config_path_for_state_dir,
    global_config_schema,
    load_rtk_from_config,
    load_global_config,
    load_provider_from_config,
    save_provider_to_config,
    save_rtk_to_config,
    load_extensions_from_config,
    save_extensions_to_config,
    parse_global_config_text,
    serialize_global_config,
    write_global_config,
)


class RuntimeConfigTest(unittest.TestCase):
    def test_global_config_path_tracks_state_layouts(self) -> None:
        # `herd` and `state` are both recognised as runtime state dirs under an
        # install root — the config.yaml lives at the install root. Gateway is
        # no longer a separate layer, so a literal "gateway" dir IS the state
        # dir (not a wrapper above it).
        self.assertEqual(
            global_config_path_for_state_dir(Path("/tmp/elephant/herd")),
            Path("/tmp/elephant/config.yaml"),
        )
        self.assertEqual(
            global_config_path_for_state_dir(Path("/tmp/elephant/state")),
            Path("/tmp/elephant/config.yaml"),
        )

    def test_global_config_path_tracks_database_layout(self) -> None:
        self.assertEqual(
            global_config_path_for_state_dir(Path("/tmp/elephant/state")),
            Path("/tmp/elephant/config.yaml"),
        )
        self.assertEqual(
            global_config_path_for_state_dir(Path("/tmp")),
            Path("/tmp/config.yaml"),
        )

    def test_yaml_round_trip_and_default_merge(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            config_path = Path(tempdir) / "config.yaml"
            defaults = default_global_config(
                state_dir=Path(tempdir) / "state",
            )
            config = {
                **defaults,
                "sessions": {
                    **defaults["sessions"],
                    "max_history_rows": 42,
                    "persist_system_prompts": False,
                },
            }
            write_global_config(config_path, config)

            loaded = load_global_config(
                config_path,
                state_dir=Path(tempdir) / "state",
            )

            self.assertEqual(loaded["sessions"]["max_history_rows"], 42)
            self.assertEqual(loaded["sessions"]["persist_system_prompts"], False)
            self.assertEqual(loaded["models"]["default_provider_source"], "config")
            self.assertNotIn("state_focus_mode", loaded["models"])
            self.assertEqual(loaded["skills"]["external_dirs"], ["~/.agents/skills"])
            self.assertEqual(loaded["tools"]["rtk"]["enabled"], False)

    def test_default_global_config_from_gateway_state_uses_shared_install_root(self) -> None:
        """Gateway and CLI share the same state_dir.

        Passing ``.../gateway`` as an explicit override is honoured — the
        caller asked for it. But there's no implicit path flip: ``runtime``
        and ``gateway`` ``state_dir`` both echo what the caller passed.
        """
        defaults = default_global_config(state_dir=Path("/tmp/elephant/gateway"))
        self.assertEqual(defaults["runtime"]["state_dir"], "/tmp/elephant/gateway")
        self.assertEqual(defaults["gateway"]["state_dir"], "/tmp/elephant/gateway")

    def test_parse_json_or_simple_yaml_object(self) -> None:
        self.assertEqual(parse_global_config_text('{"dashboard": {"port": 9999}}')["dashboard"]["port"], 9999)
        parsed = parse_global_config_text("dashboard:\n  host: 127.0.0.1\n  port: 4174\n")
        self.assertEqual(parsed["dashboard"]["host"], "127.0.0.1")
        self.assertEqual(parsed["dashboard"]["port"], 4174)
        self.assertIn("dashboard:", serialize_global_config(parsed))

    def test_external_skill_dirs_default_and_schema_are_exposed(self) -> None:
        defaults = default_global_config(state_dir=Path("/tmp/state"))
        self.assertEqual(configured_external_skill_dirs(defaults), ("~/.agents/skills",))
        fields = {field["path"]: field for field in global_config_schema()}
        self.assertEqual(fields["skills.external_dirs"]["type"], "string_list")
        self.assertEqual(fields["tools.rtk.enabled"]["type"], "boolean")
        self.assertNotIn("models.state_focus_mode", fields)

    def test_removed_reset_config_keys_are_not_serialized(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            config_path = Path(tempdir) / "config.yaml"
            config_path.write_text(
                "models:\n  default_provider_source: profile\n  state_focus_mode: balanced\n",
                encoding="utf-8",
            )
            loaded = load_global_config(
                config_path,
                state_dir=Path(tempdir) / "state",
            )
            self.assertNotIn("state_focus_mode", loaded["models"])
            self.assertNotIn(
                "state_focus_mode",
                serialize_global_config(loaded),
            )

    def test_external_skill_dirs_accept_string_payloads(self) -> None:
        config = {"skills": {"external_dirs": "~/.agents/skills, /tmp/team-skills"}}
        self.assertEqual(
            configured_external_skill_dirs(config),
            ("~/.agents/skills", "/tmp/team-skills"),
        )

    def test_load_provider_from_config(self) -> None:
        self.assertIsNone(load_provider_from_config({}))
        self.assertIsNone(load_provider_from_config({"models": {}}))
        provider = load_provider_from_config({
            "models": {
                "provider": {
                    "profile_id": "provider-openai-compatible",
                    "provider_id": "openai-compatible",
                    "base_url": "https://api.example.com/v1",
                    "default_model": "gpt-4",
                }
            }
        })
        self.assertIsNotNone(provider)
        self.assertEqual(provider["profile_id"], "provider-openai-compatible")

    def test_save_and_load_provider_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            config_path = Path(tempdir) / "config.yaml"
            state_dir = Path(tempdir) / "state"
            save_provider_to_config(
                config_path,
                state_dir=state_dir,
                provider_payload={
                    "profile_id": "provider-openai-compatible",
                    "provider_id": "openai-compatible",
                    "base_url": "https://api.example.com/v1",
                    "default_model": "gpt-4",
                },
            )
            config = load_global_config(config_path, state_dir=state_dir)
            provider = load_provider_from_config(config)
            self.assertIsNotNone(provider)
            self.assertEqual(provider["provider_id"], "openai-compatible")

    def test_save_and_load_rtk_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            config_path = Path(tempdir) / "config.yaml"
            state_dir = Path(tempdir) / "state"
            save_rtk_to_config(
                config_path,
                state_dir=state_dir,
                rtk_payload={
                    "enabled": True,
                    "binary": "/usr/local/bin/rtk",
                    "rewrite_timeout_seconds": 5,
                    "file_read_optimizer": {"enabled": False, "min_chars": 16_000},
                },
            )
            config = load_global_config(config_path, state_dir=state_dir)
            rtk = load_rtk_from_config(config)
            self.assertTrue(rtk["enabled"])
            self.assertEqual(rtk["binary"], "/usr/local/bin/rtk")
            self.assertEqual(rtk["rewrite_timeout_seconds"], 5)
            self.assertFalse(rtk["file_read_optimizer"]["enabled"])
            self.assertEqual(rtk["file_read_optimizer"]["min_chars"], 16_000)

    def test_save_and_load_extensions_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            config_path = Path(tempdir) / "config.yaml"
            state_dir = Path(tempdir) / "state"
            save_extensions_to_config(
                config_path,
                state_dir=state_dir,
                extensions={"tool_manifests": ["/path/to/tools.yaml"]},
            )
            config = load_global_config(config_path, state_dir=state_dir)
            extensions = load_extensions_from_config(config)
            self.assertEqual(extensions["tool_manifests"], ["/path/to/tools.yaml"])


if __name__ == "__main__":
    unittest.main()
