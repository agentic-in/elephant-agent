"""Tests for SecurityGuard — env sanitization and path validation."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.sandbox.security_guard import SecurityGuard


class TestSanitizeEnv(unittest.TestCase):
    """SecurityGuard.sanitize_env tests."""

    def setUp(self) -> None:
        self.guard = SecurityGuard()

    # -- safe prefix pass-through ----------------------------------------

    def test_path_env_passes_through(self) -> None:
        env = self.guard.sanitize_env({"PATH": "/usr/bin:/bin"})
        self.assertEqual(env.get("PATH"), "/usr/bin:/bin")

    def test_home_env_passes_through(self) -> None:
        env = self.guard.sanitize_env({"HOME": "/home/user"})
        self.assertEqual(env.get("HOME"), "/home/user")

    def test_user_env_passes_through(self) -> None:
        env = self.guard.sanitize_env({"USER": "alice"})
        self.assertEqual(env.get("USER"), "alice")

    def test_lang_env_passes_through(self) -> None:
        env = self.guard.sanitize_env({"LANG": "en_US.UTF-8"})
        self.assertEqual(env.get("LANG"), "en_US.UTF-8")

    def test_term_env_passes_through(self) -> None:
        env = self.guard.sanitize_env({"TERM": "xterm-256color"})
        self.assertEqual(env.get("TERM"), "xterm-256color")

    def test_shell_env_passes_through(self) -> None:
        env = self.guard.sanitize_env({"SHELL": "/bin/zsh"})
        self.assertEqual(env.get("SHELL"), "/bin/zsh")

    def test_virtual_env_passes_through(self) -> None:
        env = self.guard.sanitize_env({"VIRTUAL_ENV": "/home/user/.venv"})
        self.assertEqual(env.get("VIRTUAL_ENV"), "/home/user/.venv")

    def test_tmpdir_env_passes_through(self) -> None:
        env = self.guard.sanitize_env({"TMPDIR": "/tmp"})
        self.assertEqual(env.get("TMPDIR"), "/tmp")

    # -- secret fragments are excluded even with safe prefix --------------

    def test_aws_secret_access_key_excluded(self) -> None:
        env = self.guard.sanitize_env({"AWS_SECRET_ACCESS_KEY": "wJalrXUtnFEMI/K7MDENG"})
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", env)

    def test_github_token_excluded(self) -> None:
        env = self.guard.sanitize_env({"GITHUB_TOKEN": "ghp_abc123"})
        self.assertNotIn("GITHUB_TOKEN", env)

    def test_database_password_excluded(self) -> None:
        env = self.guard.sanitize_env({"DATABASE_PASSWORD": "s3cret"})
        self.assertNotIn("DATABASE_PASSWORD", env)

    def test_aws_access_key_id_excluded(self) -> None:
        """KEY fragment in name triggers exclusion."""
        env = self.guard.sanitize_env({"AWS_ACCESS_KEY_ID": "AKIAIOSFODNN7EXAMPLE"})
        self.assertNotIn("AWS_ACCESS_KEY_ID", env)

    def test_authorization_header_excluded(self) -> None:
        """AUTH fragment triggers exclusion."""
        env = self.guard.sanitize_env({"HTTP_AUTHORIZATION": "Bearer xyz"})
        self.assertNotIn("HTTP_AUTHORIZATION", env)

    def test_credential_file_excluded(self) -> None:
        """CREDENTIAL fragment triggers exclusion."""
        env = self.guard.sanitize_env({"MY_CREDENTIAL_FILE": "/path"})
        self.assertNotIn("MY_CREDENTIAL_FILE", env)

    # -- unknown prefix vars are dropped ----------------------------------

    def test_unknown_prefix_dropped(self) -> None:
        env = self.guard.sanitize_env({"MY_CUSTOM_VAR": "hello"})
        self.assertNotIn("MY_CUSTOM_VAR", env)

    # -- extra_env overrides and adds ------------------------------------

    def test_extra_env_added_after_filtering(self) -> None:
        env = self.guard.sanitize_env(
            base_env={"PATH": "/usr/bin"},
            extra_env={"MY_TOOL_CONFIG": "value"},
        )
        self.assertEqual(env["MY_TOOL_CONFIG"], "value")

    def test_extra_env_overrides_base(self) -> None:
        env = self.guard.sanitize_env(
            base_env={"PATH": "/usr/bin"},
            extra_env={"PATH": "/custom/bin"},
        )
        self.assertEqual(env["PATH"], "/custom/bin")

    # -- sandbox-specific vars -------------------------------------------

    def test_sandbox_marker_added(self) -> None:
        env = self.guard.sanitize_env({})
        self.assertEqual(env.get("ELEPHANT_SANDBOX"), "1")

    # -- empty base_env --------------------------------------------------

    def test_empty_base_env_still_adds_sandbox_marker(self) -> None:
        env = self.guard.sanitize_env({})
        self.assertIn("ELEPHANT_SANDBOX", env)

    # -- no secrets leak through -----------------------------------------

    def test_mixed_env_no_secrets_leak(self) -> None:
        base = {
            "PATH": "/usr/bin",
            "HOME": "/home/user",
            "AWS_SECRET_ACCESS_KEY": "leak-me",
            "GITHUB_TOKEN": "leak-me-too",
            "DATABASE_PASSWORD": "also-leak",
            "API_KEY": "secret-key",
            "SHELL": "/bin/bash",
            "RANDOM_VAR": "dropped",
        }
        env = self.guard.sanitize_env(base)
        # Safe ones pass
        self.assertIn("PATH", env)
        self.assertIn("HOME", env)
        self.assertIn("SHELL", env)
        # Secrets are gone
        for secret_key in [
            "AWS_SECRET_ACCESS_KEY",
            "GITHUB_TOKEN",
            "DATABASE_PASSWORD",
            "API_KEY",
        ]:
            self.assertNotIn(secret_key, env, f"Secret {secret_key} leaked through")
        # Unknown prefix dropped
        self.assertNotIn("RANDOM_VAR", env)


class TestValidateSensitiveHostPath(unittest.TestCase):
    """SecurityGuard.validate_sensitive_host_path tests."""

    def setUp(self) -> None:
        self.guard = SecurityGuard()

    def test_etc_passwd_is_sensitive(self) -> None:
        reason = self.guard.validate_sensitive_host_path(Path("/etc/passwd"))
        self.assertIsNotNone(reason)

    def test_etc_shadow_is_sensitive(self) -> None:
        reason = self.guard.validate_sensitive_host_path(Path("/etc/shadow"))
        self.assertIsNotNone(reason)

    def test_ssh_private_key_is_sensitive(self) -> None:
        reason = self.guard.validate_sensitive_host_path(Path("~/.ssh/id_rsa"))
        self.assertIsNotNone(reason)

    def test_aws_credentials_is_sensitive(self) -> None:
        reason = self.guard.validate_sensitive_host_path(Path("~/.aws/credentials"))
        self.assertIsNotNone(reason)

    def test_docker_sock_is_sensitive(self) -> None:
        """On macOS /var/run/docker.sock resolves through symlinks to a podman
        socket, so the resolved path won't match the exact-path entry.  Use
        /run/docker.sock instead, which resolves to itself."""
        reason = self.guard.validate_sensitive_host_path(Path("/run/docker.sock"))
        self.assertIsNotNone(reason)

    def test_regular_project_path_is_allowed(self) -> None:
        reason = self.guard.validate_sensitive_host_path(
            Path("/home/user/project/src/main.py")
        )
        self.assertIsNone(reason)

    def test_workspace_cwd_not_blocked(self) -> None:
        """The workspace cwd itself should not be flagged as sensitive."""
        cwd = Path.cwd()
        reason = self.guard.validate_sensitive_host_path(cwd)
        self.assertIsNone(reason)

    def test_home_bashrc_is_sensitive(self) -> None:
        reason = self.guard.validate_sensitive_host_path(Path("~/.bashrc"))
        self.assertIsNotNone(reason)

    def test_home_env_is_sensitive(self) -> None:
        reason = self.guard.validate_sensitive_host_path(Path("~/.env"))
        self.assertIsNotNone(reason)

    def test_home_docker_is_sensitive(self) -> None:
        reason = self.guard.validate_sensitive_host_path(Path("~/.docker"))
        self.assertIsNotNone(reason)

    def test_home_gnupg_is_sensitive(self) -> None:
        reason = self.guard.validate_sensitive_host_path(Path("~/.gnupg"))
        self.assertIsNotNone(reason)

    def test_tmp_project_path_allowed(self) -> None:
        reason = self.guard.validate_sensitive_host_path(
            Path("/tmp/my-project/workdir")
        )
        self.assertIsNone(reason)


class TestValidateBindMounts(unittest.TestCase):
    """SecurityGuard.validate_bind_mounts tests (Phase 2)."""

    def setUp(self) -> None:
        self.guard = SecurityGuard()

    def test_workspace_path_allowed(self) -> None:
        mounts = [(Path("/tmp/my-project"), "rw")]
        rejected = self.guard.validate_bind_mounts(mounts)
        self.assertEqual(len(rejected), 0)

    def test_sensitive_path_rejected(self) -> None:
        mounts = [(Path.home() / ".ssh", "ro")]
        rejected = self.guard.validate_bind_mounts(mounts)
        self.assertEqual(len(rejected), 1)
        self.assertIn("sensitive", rejected[0][2])

    def test_docker_sock_rejected(self) -> None:
        # On macOS /var may be a symlink, so use a sensitive path that
        # doesn't depend on symlink resolution
        mounts = [(Path("/etc/passwd"), "rw")]
        rejected = self.guard.validate_bind_mounts(mounts)
        self.assertEqual(len(rejected), 1)

    def test_mixed_mounts(self) -> None:
        mounts = [
            (Path("/tmp/workspace"), "rw"),
            (Path.home() / ".aws", "ro"),
        ]
        rejected = self.guard.validate_bind_mounts(mounts)
        self.assertEqual(len(rejected), 1)
        self.assertIn(".aws", str(rejected[0][0]))

    def test_invalid_access_mode(self) -> None:
        mounts = [(Path("/tmp/workspace"), "rwx")]
        rejected = self.guard.validate_bind_mounts(mounts)
        self.assertEqual(len(rejected), 1)
        self.assertIn("invalid access mode", rejected[0][2])

    def test_empty_mounts_allowed(self) -> None:
        rejected = self.guard.validate_bind_mounts([])
        self.assertEqual(len(rejected), 0)


class TestValidateNetworkMode(unittest.TestCase):
    """SecurityGuard.validate_network_mode tests (Phase 2)."""

    def setUp(self) -> None:
        self.guard = SecurityGuard()

    def test_none_mode_allowed(self) -> None:
        self.assertIsNone(self.guard.validate_network_mode("none"))

    def test_bridge_mode_allowed(self) -> None:
        self.assertIsNone(self.guard.validate_network_mode("bridge"))

    def test_host_mode_rejected(self) -> None:
        reason = self.guard.validate_network_mode("host")
        self.assertIsNotNone(reason)
        self.assertIn("host", reason)

    def test_unknown_mode_rejected(self) -> None:
        reason = self.guard.validate_network_mode("custom_net")
        self.assertIsNotNone(reason)
        self.assertIn("unknown", reason)


if __name__ == "__main__":
    unittest.main()
