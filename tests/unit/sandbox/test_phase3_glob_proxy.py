"""Tests for Phase 3: glob→regex converter and proxy extraction."""

from __future__ import annotations

import unittest

from packages.sandbox.glob_to_regex import format_seatbelt_deny_read, glob_to_seatbelt_regex
from packages.sandbox.proxy import ProxyConfig, extract_proxy_config


# ---------------------------------------------------------------------------
# Glob to Regex tests
# ---------------------------------------------------------------------------


class TestGlobToSeatbeltRegex(unittest.TestCase):
    """Test glob_to_seatbelt_regex conversion."""

    def test_empty_pattern(self):
        self.assertIsNone(glob_to_seatbelt_regex(""))

    def test_globstar_prefix(self):
        """**/.env → matches .env at any depth."""
        regex = glob_to_seatbelt_regex("**/.env")
        self.assertIsNotNone(regex)
        self.assertIn("\\.env$", regex)
        # Should match paths like /foo/bar/.env
        import re
        self.assertTrue(re.match(regex, "/foo/bar/.env"))
        self.assertTrue(re.match(regex, "/.env"))
        self.assertFalse(re.match(regex, "/foo/.env.local"))

    def test_globstar_suffix(self):
        """**/secret/** → matches anything under secret/."""
        regex = glob_to_seatbelt_regex("**/secret/**")
        self.assertIsNotNone(regex)
        import re
        self.assertTrue(re.match(regex, "/foo/secret/bar"))
        self.assertTrue(re.match(regex, "/secret/"))

    def test_single_star(self):
        """*.key → matches .key files in one directory level."""
        regex = glob_to_seatbelt_regex("*.key")
        self.assertIsNotNone(regex)
        import re
        self.assertTrue(re.match(regex, "server.key"))
        self.assertFalse(re.match(regex, "dir/server.key"))

    def test_question_mark(self):
        """?.txt → matches single char + .txt."""
        regex = glob_to_seatbelt_regex("?.txt")
        self.assertIsNotNone(regex)
        import re
        self.assertTrue(re.match(regex, "a.txt"))
        self.assertFalse(re.match(regex, "ab.txt"))
        self.assertFalse(re.match(regex, "/.txt"))

    def test_character_class(self):
        """[abc].txt → character class."""
        regex = glob_to_seatbelt_regex("[abc].txt")
        self.assertIsNotNone(regex)
        import re
        self.assertTrue(re.match(regex, "a.txt"))
        self.assertTrue(re.match(regex, "c.txt"))
        self.assertFalse(re.match(regex, "d.txt"))

    def test_negated_character_class(self):
        """[!abc].txt → negated class."""
        regex = glob_to_seatbelt_regex("[!abc].txt")
        self.assertIsNotNone(regex)
        import re
        self.assertFalse(re.match(regex, "a.txt"))
        self.assertTrue(re.match(regex, "d.txt"))

    def test_literal_no_glob(self):
        """/path/to/file → exact path + subtree."""
        regex = glob_to_seatbelt_regex("/path/to/file")
        self.assertIsNotNone(regex)
        import re
        self.assertTrue(re.match(regex, "/path/to/file"))
        self.assertTrue(re.match(regex, "/path/to/file/sub"))
        self.assertFalse(re.match(regex, "/path/to/file2"))

    def test_dot_env_variants(self):
        """**/.env.* → matches .env.local, .env.production, etc."""
        regex = glob_to_seatbelt_regex("**/.env.*")
        self.assertIsNotNone(regex)
        import re
        self.assertTrue(re.match(regex, "/project/.env.local"))
        self.assertTrue(re.match(regex, "/.env.production"))
        self.assertFalse(re.match(regex, "/project/.env"))

    def test_pem_files(self):
        """**/*.pem → matches any .pem file."""
        regex = glob_to_seatbelt_regex("**/*.pem")
        self.assertIsNotNone(regex)
        import re
        self.assertTrue(re.match(regex, "/certs/server.pem"))
        self.assertTrue(re.match(regex, "/a/b/c/key.pem"))

    def test_format_seatbelt_deny_read(self):
        """format_seatbelt_deny_read returns complete SBPL rule."""
        rule = format_seatbelt_deny_read("**/.env")
        self.assertIsNotNone(rule)
        self.assertTrue(rule.startswith("(deny file-read*"))
        self.assertIn("regex", rule)
        self.assertIn(".env", rule)

    def test_format_seatbelt_deny_read_empty(self):
        self.assertIsNone(format_seatbelt_deny_read(""))


# ---------------------------------------------------------------------------
# Proxy extraction tests
# ---------------------------------------------------------------------------


class TestProxyExtraction(unittest.TestCase):
    """Test extract_proxy_config from environment variables."""

    def test_no_proxy_vars(self):
        """No proxy vars → empty config."""
        config = extract_proxy_config(env={})
        self.assertFalse(config.has_proxy)
        self.assertEqual(config.loopback_ports, ())
        self.assertEqual(config.unix_sockets, ())

    def test_http_proxy_localhost(self):
        """HTTP_PROXY=http://127.0.0.1:8080 → port 8080."""
        config = extract_proxy_config(env={"HTTP_PROXY": "http://127.0.0.1:8080"})
        self.assertTrue(config.has_proxy)
        self.assertIn(8080, config.loopback_ports)

    def test_https_proxy_localhost(self):
        """HTTPS_PROXY=http://localhost:3128 → port 3128."""
        config = extract_proxy_config(env={"HTTPS_PROXY": "http://localhost:3128"})
        self.assertTrue(config.has_proxy)
        self.assertIn(3128, config.loopback_ports)

    def test_proxy_non_loopback_ignored(self):
        """Remote proxy hosts are not extracted."""
        config = extract_proxy_config(env={"HTTP_PROXY": "http://proxy.corp.com:8080"})
        self.assertTrue(config.has_proxy)
        self.assertEqual(config.loopback_ports, ())

    def test_proxy_no_port_uses_default(self):
        """No explicit port → default based on scheme."""
        config = extract_proxy_config(env={"HTTP_PROXY": "http://localhost"})
        self.assertTrue(config.has_proxy)
        self.assertIn(80, config.loopback_ports)

    def test_socks_proxy(self):
        """SOCKS5 proxy on localhost."""
        config = extract_proxy_config(env={"ALL_PROXY": "socks5://localhost:1080"})
        self.assertTrue(config.has_proxy)
        self.assertIn(1080, config.loopback_ports)

    def test_unix_socket_proxy(self):
        """Unix socket proxy URL."""
        config = extract_proxy_config(
            env={"ALL_PROXY": "socks5h://unix:///tmp/proxy.sock"}
        )
        self.assertTrue(config.has_proxy)
        self.assertIn("/tmp/proxy.sock", config.unix_sockets)

    def test_extra_unix_sockets(self):
        """Extra unix sockets are included."""
        config = extract_proxy_config(
            env={},
            extra_unix_sockets=("/var/run/docker.sock",),
        )
        self.assertFalse(config.has_proxy)
        self.assertIn("/var/run/docker.sock", config.unix_sockets)

    def test_multiple_proxy_vars(self):
        """Multiple proxy vars → all ports collected."""
        config = extract_proxy_config(env={
            "HTTP_PROXY": "http://127.0.0.1:8080",
            "HTTPS_PROXY": "http://localhost:8443",
        })
        self.assertTrue(config.has_proxy)
        self.assertIn(8080, config.loopback_ports)
        self.assertIn(8443, config.loopback_ports)

    def test_lowercase_vars(self):
        """Lowercase env vars are also parsed."""
        config = extract_proxy_config(env={"http_proxy": "http://localhost:9090"})
        self.assertTrue(config.has_proxy)
        self.assertIn(9090, config.loopback_ports)


# ---------------------------------------------------------------------------
# Policy builder integration tests (Phase 3)
# ---------------------------------------------------------------------------

from pathlib import Path

from packages.sandbox.backends.seatbelt import SeatbeltPolicyBuilder
from packages.sandbox.config import SandboxConfig, SeatbeltSandboxOptions


class TestSeatbeltPhase3Integration(unittest.TestCase):
    """Integration tests for proxy and glob deny in policy builder."""

    def _config(self, **overrides) -> SandboxConfig:
        seatbelt = SeatbeltSandboxOptions(**overrides)
        return SandboxConfig(mode="all", backend="seatbelt", seatbelt=seatbelt)

    def test_proxy_mode_adds_port_rules(self):
        """Proxy mode adds localhost port allow rules."""
        config = self._config(allow_network=False, allow_network_loopback=False)
        builder = SeatbeltPolicyBuilder(config)
        builder.add_network_proxy(env={"HTTP_PROXY": "http://127.0.0.1:8080"})

        policy_text, params = builder.render()

        self.assertIn("localhost:8080", policy_text)
        self.assertIn("proxy-routed", policy_text)

    def test_proxy_mode_with_unix_socket(self):
        """Proxy mode with unix socket adds parameterized socket rules."""
        config = self._config(allow_network=False)
        builder = SeatbeltPolicyBuilder(config)
        builder.add_network_proxy(
            env={"ALL_PROXY": "socks5h://unix:///tmp/proxy.sock"}
        )

        policy_text, params = builder.render()

        self.assertIn('(param "UNIX_SOCKET_0")', policy_text)
        self.assertTrue(any("UNIX_SOCKET_0=" in p and "proxy.sock" in p for p in params))

    def test_proxy_mode_skipped_when_network_full(self):
        """When allow_network=True, proxy rules don't override full network."""
        config = self._config(allow_network=True)
        builder = SeatbeltPolicyBuilder(config)
        builder.add_network_rules()
        builder.add_network_proxy(env={"HTTP_PROXY": "http://localhost:8080"})

        policy_text, _ = builder.render()

        # Full network mode takes precedence — should have unrestricted allow
        self.assertIn("(allow network-outbound)", policy_text)
        # Should NOT have specific port restrictions (proxy didn't override)
        self.assertNotIn("localhost:8080", policy_text)

    def test_proxy_mode_no_proxy_vars_no_change(self):
        """No proxy vars → no proxy rules added."""
        config = self._config(allow_network=False)
        builder = SeatbeltPolicyBuilder(config)
        builder.add_network_proxy(env={})

        policy_text, _ = builder.render()

        self.assertNotIn("proxy-routed", policy_text)
        self.assertNotIn("UNIX_SOCKET", policy_text)

    def test_deny_read_globs_rendered(self):
        """Deny-read globs are converted to regex deny rules."""
        config = self._config()
        builder = SeatbeltPolicyBuilder(config)
        builder.add_deny_read_globs(("**/.env", "**/*.pem"))

        policy_text, _ = builder.render()

        self.assertIn("(deny file-read*", policy_text)
        self.assertIn(".env", policy_text)
        self.assertIn(".pem", policy_text)

    def test_deny_read_globs_empty(self):
        """Empty glob list adds no deny rules in extra_policy_lines."""
        config = self._config()
        builder = SeatbeltPolicyBuilder(config)
        builder.add_deny_read_globs(())

        # _extra_policy_lines should be empty (no globs = no extra deny rules)
        self.assertEqual(builder._extra_policy_lines, [])

    def test_network_policy_file_loaded(self):
        """Network policy SBPL file is included when network enabled."""
        config = self._config(allow_network=True)
        builder = SeatbeltPolicyBuilder(config)
        builder.add_network_rules()

        policy_text, _ = builder.render()

        # Network policy includes TLS/DNS services
        self.assertIn("com.apple.SecurityServer", policy_text)
        self.assertIn("com.apple.networkd", policy_text)
        self.assertIn("com.apple.trustd.agent", policy_text)


if __name__ == "__main__":
    unittest.main()
