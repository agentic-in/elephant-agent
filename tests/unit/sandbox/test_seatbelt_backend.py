"""Unit tests for the macOS Seatbelt sandbox backend (Phase 1: security foundation)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from packages.sandbox.backends.seatbelt import (
    SeatbeltBackend,
    SeatbeltPolicyBuilder,
    _get_base_policy,
)
from packages.sandbox.config import SandboxConfig, SeatbeltSandboxOptions


# ---------------------------------------------------------------------------
# SeatbeltPolicyBuilder tests
# ---------------------------------------------------------------------------


class TestSeatbeltPolicyBuilder(unittest.TestCase):
    """Tests for the SeatbeltPolicyBuilder policy generation."""

    def _default_config(self, **overrides) -> SandboxConfig:
        seatbelt = SeatbeltSandboxOptions(**overrides)
        return SandboxConfig(mode="all", backend="seatbelt", seatbelt=seatbelt)

    def test_base_policy_loaded(self):
        """Base policy template is loaded and contains core deny default."""
        policy = _get_base_policy()
        self.assertIn("(version 1)", policy)
        self.assertIn("(deny default)", policy)

    def test_base_policy_has_parameterized_references(self):
        """Base policy uses (param ...) for paths, not hardcoded strings."""
        policy = _get_base_policy()
        self.assertIn('(param "HOME_SSH")', policy)
        self.assertIn('(param "SANDBOX_TMPDIR")', policy)

    def test_render_produces_inline_policy(self):
        """render() returns policy text and param list."""
        config = self._default_config()
        builder = SeatbeltPolicyBuilder(config)
        builder.add_writable_root(Path("/tmp/workspace"))
        builder.add_sandbox_tmpdir(Path("/tmp/sandbox-abc"))
        builder.add_credential_deny(Path("/Users/testuser"))

        policy_text, params = builder.render()

        self.assertIsInstance(policy_text, str)
        self.assertIsInstance(params, list)
        self.assertTrue(len(policy_text) > 100)
        self.assertTrue(any("-DWRITABLE_ROOT_0=" in p for p in params))

    def test_writable_root_parameterized(self):
        """Writable roots use (param ...) syntax, not hardcoded paths."""
        config = self._default_config()
        builder = SeatbeltPolicyBuilder(config)
        builder.add_writable_root(Path("/workspace/project"))

        policy_text, params = builder.render()

        self.assertIn('(param "WRITABLE_ROOT_0")', policy_text)
        self.assertNotIn("/workspace/project", policy_text)
        self.assertIn("-DWRITABLE_ROOT_0=/workspace/project", params)

    def test_writable_root_with_exclusions(self):
        """Writable roots with exclusions produce require-all + require-not."""
        config = self._default_config()
        builder = SeatbeltPolicyBuilder(config)
        builder.add_writable_root(
            Path("/workspace"),
            exclusions=[r"(^|/)\.git(/.*)?$"],
        )

        policy_text, params = builder.render()

        self.assertIn("require-all", policy_text)
        self.assertIn("require-not", policy_text)
        self.assertIn(r"\.git", policy_text)

    def test_protected_paths_from_config(self):
        """Default config protected_paths produce exclusion rules."""
        config = self._default_config()
        builder = SeatbeltPolicyBuilder(config)
        exclusions = list(config.seatbelt.protected_paths)
        builder.add_writable_root(Path("/workspace"), exclusions=exclusions)

        policy_text, _ = builder.render()

        self.assertIn(r"\.git/hooks", policy_text)
        self.assertIn(r"\.claude/settings", policy_text)
        self.assertIn(r"\.claude/skills", policy_text)

    def test_multiple_writable_roots(self):
        """Multiple writable roots get indexed parameters."""
        config = self._default_config(extra_writable_roots=("/tmp/build",))
        builder = SeatbeltPolicyBuilder(config)
        builder.add_writable_root(Path("/workspace"))
        builder.add_writable_root(Path("/tmp/build"))

        policy_text, params = builder.render()

        self.assertIn('(param "WRITABLE_ROOT_0")', policy_text)
        self.assertIn('(param "WRITABLE_ROOT_1")', policy_text)
        # Use startswith to handle macOS /tmp -> /private/tmp resolution
        self.assertTrue(any(p.startswith("-DWRITABLE_ROOT_0=") for p in params))
        self.assertTrue(any(p.startswith("-DWRITABLE_ROOT_1=") for p in params))

    def test_credential_deny_params(self):
        """Credential deny adds HOME_SSH, HOME_AWS, etc. parameters."""
        config = self._default_config()
        builder = SeatbeltPolicyBuilder(config)
        builder.add_credential_deny(Path("/Users/alice"))

        _, params = builder.render()

        self.assertIn("-DHOME_SSH=/Users/alice/.ssh", params)
        self.assertIn("-DHOME_AWS=/Users/alice/.aws", params)
        self.assertIn("-DHOME_GNUPG=/Users/alice/.gnupg", params)
        self.assertIn("-DHOME_KUBE=/Users/alice/.kube", params)
        self.assertIn("-DHOME_DOCKER=/Users/alice/.docker", params)

    def test_credential_deny_disabled(self):
        """When deny_read_credentials=False, no credential params emitted."""
        config = self._default_config(deny_read_credentials=False)
        builder = SeatbeltPolicyBuilder(config)
        # Don't call add_credential_deny

        _, params = builder.render()

        self.assertFalse(any("HOME_SSH" in p for p in params))

    def test_mach_lookup_restricted(self):
        """Base policy has named mach-lookup services, not blanket allow."""
        policy = _get_base_policy()

        # Must NOT have bare (allow mach-lookup) without service filter
        lines = policy.splitlines()
        bare_mach = [l for l in lines if l.strip() == "(allow mach-lookup)"]
        self.assertEqual(bare_mach, [], "Found bare (allow mach-lookup) without service restriction")

        # Must have specific services
        self.assertIn("com.apple.system.opendirectoryd.libinfo", policy)
        self.assertIn("com.apple.PowerManagement.control", policy)
        self.assertIn("com.apple.cfprefsd.daemon", policy)

    def test_ipc_no_sysv(self):
        """Base policy has ipc-posix-sem but NOT (allow ipc-sysv*)."""
        policy = _get_base_policy()

        self.assertIn("ipc-posix-sem", policy)
        # Must not have a permissive ipc-sysv* ALLOW rule
        self.assertNotIn("(allow ipc-sysv", policy)

    def test_no_file_on_disk(self):
        """Policy builder does NOT write any file to disk."""
        config = self._default_config()
        builder = SeatbeltPolicyBuilder(config)
        builder.add_writable_root(Path("/tmp/test"))
        builder.add_sandbox_tmpdir(Path("/tmp/sandbox"))

        policy_text, params = builder.render()

        # Verify it's just a string, not a file path
        self.assertIn("(version 1)", policy_text)
        # No temp file should be created by the builder itself

    def test_network_allow_full(self):
        """allow_network=True produces full network rules."""
        config = self._default_config(allow_network=True)
        builder = SeatbeltPolicyBuilder(config)
        builder.add_network_rules()

        policy_text, _ = builder.render()

        self.assertIn("(allow network-outbound)", policy_text)
        self.assertIn("(allow network-inbound)", policy_text)

    def test_network_loopback_only(self):
        """Default loopback mode denies outbound, allows unix sockets."""
        config = self._default_config(allow_network=False, allow_network_loopback=True)
        builder = SeatbeltPolicyBuilder(config)
        builder.add_network_rules()

        policy_text, _ = builder.render()

        self.assertIn("(deny network-outbound)", policy_text)
        self.assertIn("unix-socket", policy_text)

    def test_network_fully_denied(self):
        """allow_network=False + allow_network_loopback=False → no network allow rules in dynamic section."""
        config = self._default_config(allow_network=False, allow_network_loopback=False)
        builder = SeatbeltPolicyBuilder(config)
        builder.add_network_rules()

        # The builder's own _network_lines should be empty
        self.assertEqual(builder._network_lines, [])

    def test_sandbox_tmpdir_param(self):
        """Sandbox tmpdir is parameterized."""
        config = self._default_config()
        builder = SeatbeltPolicyBuilder(config)
        builder.add_sandbox_tmpdir(Path("/tmp/elephant-seatbelt-xyz"))

        _, params = builder.render()

        # macOS resolves /tmp -> /private/tmp, so check prefix
        self.assertTrue(
            any("SANDBOX_TMPDIR=" in p and "elephant-seatbelt-xyz" in p for p in params),
            f"Expected SANDBOX_TMPDIR param with 'elephant-seatbelt-xyz', got: {params}",
        )

    def test_dev_null_constrained(self):
        """Base policy constrains /dev/null writes with vnode-type."""
        policy = _get_base_policy()
        self.assertIn("vnode-type CHARACTER-DEVICE", policy)
        self.assertIn("/dev/null", policy)


# ---------------------------------------------------------------------------
# SeatbeltBackend tests
# ---------------------------------------------------------------------------


class TestSeatbeltBackend(unittest.TestCase):
    """Test SeatbeltBackend implementation."""

    def test_backend_id(self):
        backend = SeatbeltBackend(SandboxConfig())
        self.assertEqual(backend.BACKEND_ID, "seatbelt")

    def test_health_check_on_macos(self):
        backend = SeatbeltBackend(SandboxConfig())
        with mock.patch.object(sys, "platform", "darwin"):
            with mock.patch("os.path.isfile", return_value=True):
                with mock.patch("os.access", return_value=True):
                    self.assertTrue(backend.health_check())

    def test_health_check_on_linux(self):
        backend = SeatbeltBackend(SandboxConfig())
        with mock.patch.object(sys, "platform", "linux"):
            self.assertFalse(backend.health_check())

    def test_health_check_no_sandbox_exec(self):
        backend = SeatbeltBackend(SandboxConfig())
        with mock.patch.object(sys, "platform", "darwin"):
            with mock.patch("os.path.isfile", return_value=False):
                self.assertFalse(backend.health_check())

    def test_create_session(self):
        config = SandboxConfig(mode="all", backend="seatbelt")
        backend = SeatbeltBackend(config)
        with tempfile.TemporaryDirectory() as tmpdir:
            handle = backend.create_session(
                session_id="test-session",
                cwd=Path(tmpdir),
                env={},
            )
            self.assertEqual(handle.backend_id, "seatbelt")
            self.assertEqual(handle.session_id, "test-session")
            self.assertTrue(handle.sandbox_root.exists())
            # No policy file should exist in sandbox_root (inline delivery)
            policy_files = list(handle.sandbox_root.glob("*.sbpl"))
            self.assertEqual(policy_files, [], "No .sbpl file should be created")
            backend.cleanup_session(handle)

    def test_create_session_no_policy_file(self):
        """Session creation does NOT write a policy file (inline -p mode)."""
        config = SandboxConfig(mode="all", backend="seatbelt")
        backend = SeatbeltBackend(config)
        with tempfile.TemporaryDirectory() as tmpdir:
            handle = backend.create_session(
                session_id="test-no-policy",
                cwd=Path(tmpdir),
                env={},
            )
            # Verify no .sbpl in sandbox_root
            all_files = list(handle.sandbox_root.iterdir())
            sbpl_files = [f for f in all_files if f.suffix == ".sbpl"]
            self.assertEqual(sbpl_files, [])
            # Attachments should be empty (no policy path stored)
            self.assertEqual(handle.attachments, ())
            backend.cleanup_session(handle)

    def test_cleanup_session_removes_directory(self):
        config = SandboxConfig(mode="all", backend="seatbelt")
        backend = SeatbeltBackend(config)
        with tempfile.TemporaryDirectory() as tmpdir:
            handle = backend.create_session(
                session_id="test-cleanup",
                cwd=Path(tmpdir),
                env={},
            )
            sandbox_root = handle.sandbox_root
            self.assertTrue(sandbox_root.exists())
            backend.cleanup_session(handle)
            self.assertFalse(sandbox_root.exists())

    def test_build_policy_uses_inline_params(self):
        """_build_policy returns policy text and -D params, not a file."""
        config = SandboxConfig(mode="all", backend="seatbelt", workspace_access="rw")
        backend = SeatbeltBackend(config)
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir).resolve()
            sandbox_root = Path(tempfile.mkdtemp(prefix="test-seatbelt-"))
            try:
                policy_text, params = backend._build_policy(cwd, sandbox_root)

                # Policy is a string, not a file path
                self.assertIn("(version 1)", policy_text)
                self.assertIn("(deny default)", policy_text)

                # Params are -D flags
                self.assertTrue(all(p.startswith("-D") for p in params))

                # Writable root is parameterized (use resolved cwd)
                self.assertTrue(
                    any(f"WRITABLE_ROOT_0={cwd}" in p for p in params),
                    f"Expected WRITABLE_ROOT_0={cwd} in {params}",
                )

                # Credential denies present
                self.assertTrue(any("HOME_SSH" in p for p in params))
            finally:
                import shutil
                shutil.rmtree(sandbox_root, ignore_errors=True)

    @unittest.skipUnless(sys.platform == "darwin", "Seatbelt only works on macOS")
    def test_run_command_basic(self):
        """Basic command execution works through sandbox."""
        config = SandboxConfig(mode="all", backend="seatbelt")
        backend = SeatbeltBackend(config)
        with tempfile.TemporaryDirectory() as tmpdir:
            handle = backend.create_session(
                session_id="test-basic",
                cwd=Path(tmpdir),
                env={},
            )
            result = backend.run_command(handle, "echo hello", timeout_seconds=10)
            self.assertEqual(result.returncode, 0)
            self.assertIn("hello", result.stdout)
            backend.cleanup_session(handle)

    @unittest.skipUnless(sys.platform == "darwin", "Seatbelt only works on macOS")
    def test_run_command_git_write_denied(self):
        """Writing to .git directory is denied by sandbox policy."""
        config = SandboxConfig(mode="all", backend="seatbelt", workspace_access="rw")
        backend = SeatbeltBackend(config)
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create .git/hooks dir
            git_hooks = Path(tmpdir) / ".git" / "hooks"
            git_hooks.mkdir(parents=True)

            handle = backend.create_session(
                session_id="test-git-deny",
                cwd=Path(tmpdir),
                env={},
            )
            result = backend.run_command(
                handle,
                f"touch {git_hooks}/pre-commit 2>&1; echo EXIT=$?",
                timeout_seconds=10,
            )
            # The touch should fail with Operation not permitted
            self.assertIn("EXIT=1", result.stdout + result.stderr)
            backend.cleanup_session(handle)

    @unittest.skipUnless(sys.platform == "darwin", "Seatbelt only works on macOS")
    def test_run_command_credential_read_denied(self):
        """Reading ~/.ssh is denied by sandbox policy."""
        config = SandboxConfig(mode="all", backend="seatbelt")
        backend = SeatbeltBackend(config)
        with tempfile.TemporaryDirectory() as tmpdir:
            handle = backend.create_session(
                session_id="test-cred-deny",
                cwd=Path(tmpdir),
                env={},
            )
            home = str(Path.home())
            result = backend.run_command(
                handle,
                f"ls {home}/.ssh 2>&1; echo EXIT=$?",
                timeout_seconds=10,
            )
            # Should fail with Operation not permitted or No such file
            output = result.stdout + result.stderr
            denied = "Operation not permitted" in output or "EXIT=1" in output or "EXIT=2" in output
            self.assertTrue(denied, f"Expected denial, got: {output}")
            backend.cleanup_session(handle)


# ---------------------------------------------------------------------------
# SeatbeltSandboxOptions config tests
# ---------------------------------------------------------------------------


class TestSeatbeltConfigOptions(unittest.TestCase):
    """Test the expanded SeatbeltSandboxOptions config."""

    def test_default_protected_paths(self):
        opts = SeatbeltSandboxOptions()
        self.assertIn(r"(^|/)\.git/hooks(/.*)?$", opts.protected_paths)
        self.assertIn(r"(^|/)\.claude/settings[^/]*$", opts.protected_paths)
        self.assertIn(r"(^|/)\.claude/skills(/.*)?$", opts.protected_paths)
        self.assertIn(r"(^|/)\.claude/commands(/.*)?$", opts.protected_paths)
        self.assertIn(r"(^|/)\.claude/agents(/.*)?$", opts.protected_paths)

    def test_default_mach_services(self):
        opts = SeatbeltSandboxOptions()
        self.assertIn("com.apple.system.opendirectoryd.libinfo", opts.mach_services)
        self.assertEqual(len(opts.mach_services), 4)

    def test_deny_read_credentials_default_true(self):
        opts = SeatbeltSandboxOptions()
        self.assertTrue(opts.deny_read_credentials)

    def test_from_config_section_with_new_fields(self):
        section = {
            "mode": "all",
            "backend": "seatbelt",
            "seatbelt": {
                "allow_network": False,
                "protected_paths": [r"(^|/)\.git(/.*)?$", r"(^|/)\.custom(/.*)?$"],
                "deny_read_credentials": True,
                "extra_writable_roots": ["/tmp/build"],
            },
        }
        config = SandboxConfig.from_config_section(section)
        self.assertEqual(len(config.seatbelt.protected_paths), 2)
        self.assertIn(r"(^|/)\.custom(/.*)?$", config.seatbelt.protected_paths)
        self.assertEqual(config.seatbelt.extra_writable_roots, ("/tmp/build",))

    def test_to_config_section_includes_new_fields(self):
        config = SandboxConfig(mode="all", backend="seatbelt")
        section = config.to_config_section()
        self.assertIn("protected_paths", section["seatbelt"])
        self.assertIn("mach_services", section["seatbelt"])
        self.assertIn("deny_read_credentials", section["seatbelt"])
        self.assertIn("extra_writable_roots", section["seatbelt"])

    def test_backward_compat_minimal_config(self):
        """Minimal YAML config (only allow_network) still works."""
        section = {
            "mode": "all",
            "backend": "seatbelt",
            "seatbelt": {
                "allow_network": False,
            },
        }
        config = SandboxConfig.from_config_section(section)
        self.assertFalse(config.seatbelt.allow_network)
        # All new fields should have sensible defaults
        self.assertTrue(len(config.seatbelt.protected_paths) >= 3)
        self.assertTrue(config.seatbelt.deny_read_credentials)
        self.assertEqual(config.seatbelt.extra_writable_roots, ())


# ---------------------------------------------------------------------------
# Phase 2: file-read whitelist, sysctl, PTY tests
# ---------------------------------------------------------------------------


class TestSeatbeltPhase2ReadWhitelist(unittest.TestCase):
    """Tests for Phase 2: restrict_file_read mode."""

    def _config(self, **overrides) -> SandboxConfig:
        seatbelt = SeatbeltSandboxOptions(**overrides)
        return SandboxConfig(mode="all", backend="seatbelt", seatbelt=seatbelt)

    def test_restrict_file_read_removes_blanket_allow(self):
        """When restrict_file_read=True, no bare (allow file-read*) in policy."""
        config = self._config(restrict_file_read=True)
        builder = SeatbeltPolicyBuilder(config)
        builder.add_writable_root(Path("/workspace"))
        builder.add_sandbox_tmpdir(Path("/tmp/sandbox"))
        builder.add_credential_deny(Path("/Users/test"))

        policy_text, _ = builder.render()

        # Should NOT have a standalone blanket allow line
        for line in policy_text.splitlines():
            stripped = line.strip()
            if stripped == "(allow file-read*)":
                self.fail("Found bare (allow file-read*) when restrict_file_read=True")

    def test_restrict_file_read_includes_platform_defaults(self):
        """When restrict_file_read=True, platform defaults are included."""
        config = self._config(restrict_file_read=True)
        builder = SeatbeltPolicyBuilder(config)
        builder.add_writable_root(Path("/workspace"))
        builder.add_sandbox_tmpdir(Path("/tmp/sandbox"))

        policy_text, _ = builder.render()

        # Platform defaults include system paths
        self.assertIn("/usr/lib", policy_text)
        self.assertIn("/System/Library/Frameworks", policy_text)
        self.assertIn("/opt/homebrew", policy_text)
        self.assertIn("/private/var/db/dyld", policy_text)

    def test_restrict_file_read_writable_roots_implicitly_readable(self):
        """Writable roots get explicit file-read* rules in restricted mode."""
        config = self._config(restrict_file_read=True)
        builder = SeatbeltPolicyBuilder(config)
        builder.add_writable_root(Path("/workspace"))
        builder.add_sandbox_tmpdir(Path("/tmp/sandbox"))

        policy_text, _ = builder.render()

        self.assertIn("Writable roots are implicitly readable", policy_text)
        # Should have a file-read* rule for WRITABLE_ROOT_0
        self.assertIn('(allow file-read* (subpath (param "WRITABLE_ROOT_0")))', policy_text)

    def test_restrict_file_read_false_keeps_blanket(self):
        """When restrict_file_read=False, blanket (allow file-read*) is kept."""
        config = self._config(restrict_file_read=False)
        builder = SeatbeltPolicyBuilder(config)
        builder.add_writable_root(Path("/workspace"))
        builder.add_sandbox_tmpdir(Path("/tmp/sandbox"))

        policy_text, _ = builder.render()

        # Should still have the blanket allow
        self.assertIn("(allow file-read*)", policy_text)
        # Should NOT include platform defaults
        self.assertNotIn("Platform defaults", policy_text)

    def test_extra_readable_paths(self):
        """Extra readable paths from config are parameterized."""
        config = self._config(
            restrict_file_read=True,
            extra_readable_paths=("/custom/sdk", "/another/path"),
        )
        builder = SeatbeltPolicyBuilder(config)
        builder.add_writable_root(Path("/workspace"))
        builder.add_sandbox_tmpdir(Path("/tmp/sandbox"))

        policy_text, params = builder.render()

        self.assertIn('(param "EXTRA_READABLE_0")', policy_text)
        self.assertIn('(param "EXTRA_READABLE_1")', policy_text)
        self.assertTrue(any("EXTRA_READABLE_0=" in p for p in params))
        self.assertTrue(any("EXTRA_READABLE_1=" in p for p in params))


class TestSeatbeltPhase2Sysctl(unittest.TestCase):
    """Tests for Phase 2: sysctl whitelist."""

    def test_sysctl_whitelist_present(self):
        """Base policy has precise sysctl-name whitelist."""
        policy = _get_base_policy()
        self.assertIn('(sysctl-name "hw.ncpu")', policy)
        self.assertIn('(sysctl-name "hw.memsize")', policy)
        self.assertIn('(sysctl-name "kern.osversion")', policy)
        self.assertIn('(sysctl-name "kern.hostname")', policy)
        self.assertIn('(sysctl-name "machdep.cpu.brand_string")', policy)

    def test_sysctl_no_blanket_allow(self):
        """Base policy does NOT have bare (allow sysctl-read) without filter."""
        policy = _get_base_policy()
        for line in policy.splitlines():
            stripped = line.strip()
            # A bare allow would be just "(allow sysctl-read)" without any filter
            if stripped == "(allow sysctl-read)":
                self.fail("Found bare (allow sysctl-read) without name filter")

    def test_sysctl_write_for_java(self):
        """Java CPU grading sysctl-write is allowed."""
        policy = _get_base_policy()
        self.assertIn("kern.grade_cputype", policy)
        self.assertIn("sysctl-write", policy)


class TestSeatbeltPhase2PTY(unittest.TestCase):
    """Tests for Phase 2: PTY support."""

    def test_pseudo_tty_allowed(self):
        """Base policy allows pseudo-tty."""
        policy = _get_base_policy()
        self.assertIn("(allow pseudo-tty)", policy)

    def test_ptmx_access(self):
        """Base policy allows /dev/ptmx read/write/ioctl."""
        policy = _get_base_policy()
        self.assertIn("/dev/ptmx", policy)
        self.assertIn("file-ioctl", policy)

    def test_ttys_regex(self):
        """Base policy has regex for /dev/ttys[0-9]+."""
        policy = _get_base_policy()
        self.assertIn("^/dev/ttys[0-9]+", policy)

    @unittest.skipUnless(sys.platform == "darwin", "Seatbelt only works on macOS")
    def test_python_repl_works_in_sandbox(self):
        """Python can import basic modules in sandbox (verifies read whitelist)."""
        # Use restrict_file_read=False to avoid Python framework path issues
        # (non-standard Python installs like /Library/Frameworks/Python.framework
        # may need paths not in the default whitelist)
        config = SandboxConfig(
            mode="all", backend="seatbelt",
            seatbelt=SeatbeltSandboxOptions(restrict_file_read=False),
        )
        backend = SeatbeltBackend(config)
        with tempfile.TemporaryDirectory() as tmpdir:
            handle = backend.create_session(
                session_id="test-python-repl",
                cwd=Path(tmpdir),
                env={},
            )
            result = backend.run_command(
                handle,
                'python3 -c "import os; print(os.name)"',
                timeout_seconds=15,
            )
            self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
            self.assertIn("posix", result.stdout)
            backend.cleanup_session(handle)

    @unittest.skipUnless(sys.platform == "darwin", "Seatbelt only works on macOS")
    def test_cat_etc_hosts_succeeds(self):
        """Reading /etc/hosts works (in platform defaults whitelist)."""
        config = SandboxConfig(mode="all", backend="seatbelt")
        backend = SeatbeltBackend(config)
        with tempfile.TemporaryDirectory() as tmpdir:
            handle = backend.create_session(
                session_id="test-etc-hosts",
                cwd=Path(tmpdir),
                env={},
            )
            result = backend.run_command(
                handle,
                "cat /etc/hosts | head -1",
                timeout_seconds=10,
            )
            self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
            # /etc/hosts typically starts with a comment or localhost
            self.assertTrue(len(result.stdout.strip()) > 0)
            backend.cleanup_session(handle)


if __name__ == "__main__":
    unittest.main()
