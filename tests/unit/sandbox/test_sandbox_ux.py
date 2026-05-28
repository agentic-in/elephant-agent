"""Tests for sandbox-ux: SandboxMode, mode_to_policy, config parsing, CLI commands."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.sandbox.sandbox_mode import (
    AllowDenyDelta,
    PolicySpec,
    SandboxMode,
    PROTECTED_WRITE_PATTERNS,
    PROTECTED_CREDENTIAL_DIRS,
    mode_to_policy,
)
from packages.sandbox.config import (
    SandboxConfig,
    _NEW_MODE_VALUES,
)


# ---------------------------------------------------------------------------
# SandboxMode enum tests
# ---------------------------------------------------------------------------


class TestSandboxModeEnum(unittest.TestCase):
    """Test the SandboxMode enum."""

    def test_from_str_valid(self) -> None:
        self.assertEqual(SandboxMode.from_str("readonly"), SandboxMode.READONLY)
        self.assertEqual(SandboxMode.from_str("safe"), SandboxMode.SAFE)
        self.assertEqual(SandboxMode.from_str("dev"), SandboxMode.DEV)
        self.assertEqual(SandboxMode.from_str("open"), SandboxMode.OPEN)

    def test_from_str_case_insensitive(self) -> None:
        self.assertEqual(SandboxMode.from_str("SAFE"), SandboxMode.SAFE)
        self.assertEqual(SandboxMode.from_str("Dev"), SandboxMode.DEV)

    def test_from_str_invalid(self) -> None:
        with self.assertRaises(ValueError) as cm:
            SandboxMode.from_str("invalid")
        self.assertIn("invalid", str(cm.exception).lower())

    def test_is_new_mode(self) -> None:
        self.assertTrue(SandboxMode.is_new_mode("readonly"))
        self.assertTrue(SandboxMode.is_new_mode("safe"))
        self.assertTrue(SandboxMode.is_new_mode("dev"))
        self.assertTrue(SandboxMode.is_new_mode("open"))
        self.assertFalse(SandboxMode.is_new_mode("all"))
        self.assertFalse(SandboxMode.is_new_mode("off"))

    def test_values(self) -> None:
        self.assertEqual(SandboxMode.READONLY.value, "readonly")
        self.assertEqual(SandboxMode.SAFE.value, "safe")
        self.assertEqual(SandboxMode.DEV.value, "dev")
        self.assertEqual(SandboxMode.OPEN.value, "open")


# ---------------------------------------------------------------------------
# mode_to_policy tests
# ---------------------------------------------------------------------------


class TestModeToPolicyReadonly(unittest.TestCase):
    """Test readonly mode policy derivation."""

    def setUp(self) -> None:
        self.cwd = Path("/Users/test/project")
        self.spec = mode_to_policy(SandboxMode.READONLY, cwd=self.cwd)

    def test_no_writable_roots(self) -> None:
        self.assertEqual(self.spec.writable_roots, ())

    def test_restrict_file_read(self) -> None:
        self.assertTrue(self.spec.restrict_file_read)

    def test_no_network(self) -> None:
        self.assertFalse(self.spec.allow_network)
        self.assertFalse(self.spec.allow_network_loopback)

    def test_credentials_denied(self) -> None:
        self.assertTrue(self.spec.deny_read_credentials)

    def test_protected_paths_enforced(self) -> None:
        for pattern in PROTECTED_WRITE_PATTERNS:
            self.assertIn(pattern, self.spec.write_exclusions)


class TestModeToPolicySafe(unittest.TestCase):
    """Test safe mode policy derivation."""

    def setUp(self) -> None:
        self.cwd = Path("/Users/test/project")
        self.spec = mode_to_policy(SandboxMode.SAFE, cwd=self.cwd)

    def test_cwd_is_writable(self) -> None:
        resolved = str(self.cwd.resolve())
        self.assertIn(resolved, self.spec.writable_roots)

    def test_restrict_file_read(self) -> None:
        self.assertTrue(self.spec.restrict_file_read)

    def test_no_network(self) -> None:
        self.assertFalse(self.spec.allow_network)

    def test_loopback_allowed(self) -> None:
        self.assertTrue(self.spec.allow_network_loopback)


class TestModeToPolicyDev(unittest.TestCase):
    """Test dev mode policy derivation."""

    def setUp(self) -> None:
        self.cwd = Path("/Users/test/project")
        self.spec = mode_to_policy(SandboxMode.DEV, cwd=self.cwd)

    def test_cwd_is_writable(self) -> None:
        resolved = str(self.cwd.resolve())
        self.assertIn(resolved, self.spec.writable_roots)

    def test_restrict_file_read(self) -> None:
        self.assertTrue(self.spec.restrict_file_read)

    def test_network_open(self) -> None:
        self.assertTrue(self.spec.allow_network)
        self.assertTrue(self.spec.allow_network_loopback)


class TestModeToPolicyOpen(unittest.TestCase):
    """Test open mode policy derivation."""

    def setUp(self) -> None:
        self.cwd = Path("/Users/test/project")
        self.spec = mode_to_policy(SandboxMode.OPEN, cwd=self.cwd)

    def test_cwd_is_writable(self) -> None:
        resolved = str(self.cwd.resolve())
        self.assertIn(resolved, self.spec.writable_roots)

    def test_allow_all_read(self) -> None:
        self.assertFalse(self.spec.restrict_file_read)

    def test_network_open(self) -> None:
        self.assertTrue(self.spec.allow_network)


# ---------------------------------------------------------------------------
# Allow/Deny delta tests
# ---------------------------------------------------------------------------


class TestAllowDenyDelta(unittest.TestCase):
    """Test delta application on mode policies."""

    def test_allow_network_overrides_safe(self) -> None:
        delta = AllowDenyDelta(allow_network=True)
        spec = mode_to_policy(SandboxMode.SAFE, delta, cwd=Path("/tmp/x"))
        self.assertTrue(spec.allow_network)

    def test_deny_network_overrides_dev(self) -> None:
        delta = AllowDenyDelta(deny_network=True)
        spec = mode_to_policy(SandboxMode.DEV, delta, cwd=Path("/tmp/x"))
        self.assertFalse(spec.allow_network)
        self.assertFalse(spec.allow_network_loopback)

    def test_deny_beats_allow_network(self) -> None:
        delta = AllowDenyDelta(allow_network=True, deny_network=True)
        spec = mode_to_policy(SandboxMode.SAFE, delta, cwd=Path("/tmp/x"))
        # deny > allow
        self.assertFalse(spec.allow_network)

    def test_allow_write_adds_path(self) -> None:
        delta = AllowDenyDelta(allow_write=("~/output",))
        spec = mode_to_policy(SandboxMode.SAFE, delta, cwd=Path("/tmp/x"))
        output_resolved = str(Path("~/output").expanduser().resolve())
        self.assertIn(output_resolved, spec.writable_roots)

    def test_allow_read_adds_path(self) -> None:
        delta = AllowDenyDelta(allow_read=("~/.npmrc",))
        spec = mode_to_policy(SandboxMode.SAFE, delta, cwd=Path("/tmp/x"))
        self.assertIn("~/.npmrc", spec.extra_readable_paths)

    def test_allow_env_exempts_var(self) -> None:
        delta = AllowDenyDelta(allow_env=("NODE_AUTH_TOKEN",))
        spec = mode_to_policy(SandboxMode.SAFE, delta, cwd=Path("/tmp/x"))
        self.assertIn("NODE_AUTH_TOKEN", spec.exempt_env_vars)

    def test_deny_read_adds_glob(self) -> None:
        delta = AllowDenyDelta(deny_read=("**/*.key", "**/.env"))
        spec = mode_to_policy(SandboxMode.SAFE, delta, cwd=Path("/tmp/x"))
        self.assertIn("**/*.key", spec.deny_read_globs)
        self.assertIn("**/.env", spec.deny_read_globs)

    def test_protected_paths_always_present(self) -> None:
        """Protected paths cannot be removed even with allow overrides."""
        delta = AllowDenyDelta(allow_write=(".git/hooks",))
        spec = mode_to_policy(SandboxMode.DEV, delta, cwd=Path("/tmp/x"))
        # Protected write patterns still enforced
        self.assertIn(r"(^|/)\.git/hooks(/.*)?$", spec.write_exclusions)

    def test_from_config(self) -> None:
        section = {
            "allow": {
                "network": True,
                "read": ["~/.npmrc"],
                "write": ["~/output"],
                "env": ["NODE_AUTH_TOKEN"],
            },
            "deny": {
                "read": ["**/*.key"],
            },
        }
        delta = AllowDenyDelta.from_config(section)
        self.assertTrue(delta.allow_network)
        self.assertIn("~/.npmrc", delta.allow_read)
        self.assertIn("~/output", delta.allow_write)
        self.assertIn("NODE_AUTH_TOKEN", delta.allow_env)
        self.assertIn("**/*.key", delta.deny_read)

    def test_to_config_roundtrip(self) -> None:
        delta = AllowDenyDelta(
            allow_network=True,
            allow_read=("~/.npmrc",),
            deny_read=("**/*.key",),
        )
        config = delta.to_config()
        self.assertEqual(config["allow"]["network"], True)
        self.assertIn("~/.npmrc", config["allow"]["read"])
        self.assertIn("**/*.key", config["deny"]["read"])


# ---------------------------------------------------------------------------
# Config parsing tests (new format)
# ---------------------------------------------------------------------------


class TestConfigNewFormat(unittest.TestCase):
    """Test SandboxConfig.from_config_section with new-style modes."""

    def test_new_mode_safe(self) -> None:
        section = {"mode": "safe"}
        cfg = SandboxConfig.from_config_section(section)
        self.assertEqual(cfg.mode, "safe")
        self.assertTrue(cfg.is_active)
        self.assertTrue(cfg.is_new_mode)
        # Auto-configures backend and workspace_access
        self.assertEqual(cfg.backend, "seatbelt")
        self.assertEqual(cfg.workspace_access, "rw")

    def test_new_mode_readonly(self) -> None:
        section = {"mode": "readonly"}
        cfg = SandboxConfig.from_config_section(section)
        self.assertEqual(cfg.mode, "readonly")
        self.assertEqual(cfg.workspace_access, "ro")

    def test_new_mode_dev(self) -> None:
        section = {"mode": "dev"}
        cfg = SandboxConfig.from_config_section(section)
        self.assertEqual(cfg.mode, "dev")
        self.assertEqual(cfg.backend, "seatbelt")
        self.assertEqual(cfg.workspace_access, "rw")

    def test_new_mode_open(self) -> None:
        section = {"mode": "open"}
        cfg = SandboxConfig.from_config_section(section)
        self.assertEqual(cfg.mode, "open")
        self.assertEqual(cfg.workspace_access, "rw")

    def test_new_mode_with_allow_deny(self) -> None:
        section = {
            "mode": "safe",
            "allow": {"network": True, "read": ["~/.npmrc"]},
            "deny": {"read": ["**/*.key"]},
        }
        cfg = SandboxConfig.from_config_section(section)
        self.assertEqual(cfg.allow_delta, {"network": True, "read": ["~/.npmrc"]})
        self.assertEqual(cfg.deny_delta, {"read": ["**/*.key"]})

    def test_to_config_section_new_format(self) -> None:
        cfg = SandboxConfig(
            mode="dev",
            backend="seatbelt",
            workspace_access="rw",
            allow_delta={"network": True},
            deny_delta={"read": ["**/*.key"]},
        )
        section = cfg.to_config_section()
        self.assertEqual(section["mode"], "dev")
        self.assertEqual(section["allow"], {"network": True})
        self.assertEqual(section["deny"], {"read": ["**/*.key"]})
        # New format should NOT include backend/scope/docker/ssh fields
        self.assertNotIn("backend", section)
        self.assertNotIn("scope", section)

    def test_to_config_section_minimal(self) -> None:
        cfg = SandboxConfig(mode="safe", backend="seatbelt")
        section = cfg.to_config_section()
        self.assertEqual(section, {"mode": "safe"})


# ---------------------------------------------------------------------------
# Config parsing tests (legacy backward compat)
# ---------------------------------------------------------------------------


class TestConfigLegacyBackwardCompat(unittest.TestCase):
    """Test that old-style config still works."""

    def test_legacy_mode_all(self) -> None:
        section = {"mode": "all", "backend": "seatbelt"}
        cfg = SandboxConfig.from_config_section(section)
        self.assertEqual(cfg.mode, "all")
        self.assertEqual(cfg.backend, "seatbelt")
        self.assertFalse(cfg.is_new_mode)
        self.assertTrue(cfg.is_active)

    def test_legacy_mode_off(self) -> None:
        section = {"mode": "off"}
        cfg = SandboxConfig.from_config_section(section)
        self.assertEqual(cfg.mode, "off")
        self.assertFalse(cfg.is_active)
        self.assertFalse(cfg.is_new_mode)

    def test_legacy_full_config(self) -> None:
        section = {
            "mode": "all",
            "backend": "seatbelt",
            "scope": "session",
            "workspace_access": "rw",
            "seatbelt": {
                "allow_network": False,
                "allow_network_loopback": True,
            },
        }
        cfg = SandboxConfig.from_config_section(section)
        self.assertEqual(cfg.mode, "all")
        self.assertEqual(cfg.backend, "seatbelt")
        self.assertFalse(cfg.seatbelt.allow_network)
        self.assertTrue(cfg.seatbelt.allow_network_loopback)

    def test_legacy_to_config_section(self) -> None:
        """Legacy config roundtrips through to_config_section."""
        section = {
            "mode": "all",
            "backend": "seatbelt",
            "scope": "session",
            "workspace_access": "rw",
        }
        cfg = SandboxConfig.from_config_section(section)
        output = cfg.to_config_section()
        self.assertEqual(output["mode"], "all")
        self.assertEqual(output["backend"], "seatbelt")
        self.assertIn("seatbelt", output)


# ---------------------------------------------------------------------------
# Protected paths tests
# ---------------------------------------------------------------------------


class TestProtectedPaths(unittest.TestCase):
    """Test that protected_paths are correctly set."""

    def test_default_protected_paths_block_git_hooks(self) -> None:
        from packages.sandbox.config import SeatbeltSandboxOptions
        opts = SeatbeltSandboxOptions()
        # Should block .git/hooks
        self.assertTrue(any("git/hooks" in p for p in opts.protected_paths))

    def test_default_protected_paths_do_not_block_entire_git(self) -> None:
        from packages.sandbox.config import SeatbeltSandboxOptions
        import re
        opts = SeatbeltSandboxOptions()
        # None of the patterns should match .git/objects or .git/refs
        for pattern in opts.protected_paths:
            regex = re.compile(pattern)
            self.assertIsNone(regex.search(".git/objects/abc123"))
            self.assertIsNone(regex.search(".git/refs/heads/main"))

    def test_default_protected_paths_block_claude_settings(self) -> None:
        from packages.sandbox.config import SeatbeltSandboxOptions
        import re
        opts = SeatbeltSandboxOptions()
        # Should block .claude/settings.json
        matched = any(
            re.compile(p).search(".claude/settings.json")
            for p in opts.protected_paths
        )
        self.assertTrue(matched, "protected_paths should block .claude/settings.json")

    def test_default_protected_paths_block_claude_skills(self) -> None:
        from packages.sandbox.config import SeatbeltSandboxOptions
        import re
        opts = SeatbeltSandboxOptions()
        matched = any(
            re.compile(p).search(".claude/skills/evil.py")
            for p in opts.protected_paths
        )
        self.assertTrue(matched, "protected_paths should block .claude/skills/")

    def test_git_commit_not_blocked(self) -> None:
        """Ensure .git/objects, .git/refs, .git/index are NOT blocked."""
        from packages.sandbox.config import SeatbeltSandboxOptions
        import re
        opts = SeatbeltSandboxOptions()
        # Paths that git commit needs to write to
        git_write_paths = [
            ".git/objects/pack/tmp_pack",
            ".git/objects/ab/cdef1234",
            ".git/refs/heads/main",
            ".git/index",
            ".git/COMMIT_EDITMSG",
            ".git/logs/HEAD",
        ]
        for git_path in git_write_paths:
            blocked = any(
                re.compile(p).search(git_path)
                for p in opts.protected_paths
            )
            self.assertFalse(blocked, f"git path should NOT be blocked: {git_path}")


# ---------------------------------------------------------------------------
# CLI command helpers — tested via SandboxConfig construction
# ---------------------------------------------------------------------------


class TestSandboxConfigDeltaReplacement(unittest.TestCase):
    """Test building new configs with updated deltas (mimics CLI helper logic)."""

    def test_replace_allow_delta(self) -> None:
        cfg = SandboxConfig(
            mode="safe",
            backend="seatbelt",
            allow_delta={"network": True},
            deny_delta={},
        )
        # Simulate what _replace_deltas does
        new_cfg = SandboxConfig(
            mode=cfg.mode,
            backend=cfg.backend,
            scope=cfg.scope,
            workspace_access=cfg.workspace_access,
            resource_limits=cfg.resource_limits,
            allow_delta={"network": True, "read": ["~/.npmrc"]},
            deny_delta=cfg.deny_delta,
        )
        self.assertEqual(new_cfg.allow_delta, {"network": True, "read": ["~/.npmrc"]})
        self.assertEqual(new_cfg.deny_delta, {})

    def test_replace_deny_delta_preserves_mode(self) -> None:
        cfg = SandboxConfig(mode="dev", backend="seatbelt")
        new_cfg = SandboxConfig(
            mode=cfg.mode,
            backend=cfg.backend,
            scope=cfg.scope,
            workspace_access=cfg.workspace_access,
            resource_limits=cfg.resource_limits,
            allow_delta=cfg.allow_delta,
            deny_delta={"network": True},
        )
        self.assertEqual(new_cfg.mode, "dev")
        self.assertEqual(new_cfg.deny_delta, {"network": True})

    def test_config_serialization_with_deltas(self) -> None:
        """Config with deltas serializes to compact new format."""
        cfg = SandboxConfig(
            mode="safe",
            backend="seatbelt",
            allow_delta={"network": True, "read": ["~/.npmrc"]},
            deny_delta={"read": ["**/*.key"]},
        )
        section = cfg.to_config_section()
        self.assertEqual(section["mode"], "safe")
        self.assertEqual(section["allow"]["network"], True)
        self.assertIn("~/.npmrc", section["allow"]["read"])
        self.assertIn("**/*.key", section["deny"]["read"])

    def test_config_roundtrip(self) -> None:
        """Config with deltas survives serialize → parse roundtrip."""
        original = SandboxConfig(
            mode="dev",
            backend="seatbelt",
            allow_delta={"network": True, "write": ["~/output"]},
            deny_delta={"read": ["**/.env"]},
        )
        section = original.to_config_section()
        restored = SandboxConfig.from_config_section(section)
        self.assertEqual(restored.mode, "dev")
        self.assertEqual(restored.allow_delta, {"network": True, "write": ["~/output"]})
        self.assertEqual(restored.deny_delta, {"read": ["**/.env"]})


if __name__ == "__main__":
    unittest.main()
