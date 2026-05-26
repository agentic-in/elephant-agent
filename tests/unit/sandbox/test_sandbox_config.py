"""Tests for SandboxConfig, ResourceLimits, CloudProfileOptions, and cloud registry."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.sandbox.config import (
    CloudProfileOptions,
    CloudSandboxOptions,
    ResourceLimits,
    SandboxConfig,
    _parse_cloud_profile,
)


class TestSandboxConfig(unittest.TestCase):
    """SandboxConfig behavioural tests."""

    def test_default_mode_is_off(self) -> None:
        cfg = SandboxConfig()
        self.assertEqual(cfg.mode, "off")

    def test_default_is_active_is_false(self) -> None:
        cfg = SandboxConfig()
        self.assertFalse(cfg.is_active)

    def test_mode_all_is_active(self) -> None:
        cfg = SandboxConfig(mode="all")
        self.assertTrue(cfg.is_active)

    def test_mode_non_main_is_active(self) -> None:
        cfg = SandboxConfig(mode="non-main")
        self.assertTrue(cfg.is_active)

    def test_config_is_frozen(self) -> None:
        cfg = SandboxConfig()
        with self.assertRaises(AttributeError):
            cfg.mode = "all"  # type: ignore[misc]

    def test_frozen_prevents_field_mutation(self) -> None:
        cfg = SandboxConfig(mode="all")
        with self.assertRaises(AttributeError):
            cfg.backend = "docker"  # type: ignore[misc]

    def test_default_clouds_is_empty(self) -> None:
        cfg = SandboxConfig()
        self.assertEqual(cfg.clouds, {})

    def test_default_cloud_profile_is_empty(self) -> None:
        cfg = SandboxConfig()
        self.assertEqual(cfg.cloud_profile, "")

    def test_effective_cloud_falls_back_to_cloud(self) -> None:
        profile = CloudProfileOptions(provider="tencent", domain="ap-shanghai.tencentags.com")
        cfg = SandboxConfig(cloud=profile)
        self.assertIs(cfg.effective_cloud(), profile)

    def test_effective_cloud_resolves_named_profile(self) -> None:
        gz = CloudProfileOptions(provider="tencent", domain="ap-guangzhou.tencentags.com")
        sh = CloudProfileOptions(provider="tencent", domain="ap-shanghai.tencentags.com")
        cfg = SandboxConfig(
            cloud=gz,
            clouds={"shanghai": sh},
            cloud_profile="shanghai",
        )
        self.assertIs(cfg.effective_cloud(), sh)

    def test_effective_cloud_unknown_profile_falls_back(self) -> None:
        gz = CloudProfileOptions(provider="tencent", domain="ap-guangzhou.tencentags.com")
        cfg = SandboxConfig(
            cloud=gz,
            clouds={},
            cloud_profile="nonexistent",
        )
        self.assertIs(cfg.effective_cloud(), gz)


class TestResourceLimits(unittest.TestCase):
    """ResourceLimits default value sanity checks."""

    def test_default_max_wall_seconds(self) -> None:
        limits = ResourceLimits()
        self.assertEqual(limits.max_wall_seconds, 120)

    def test_default_max_memory_mb(self) -> None:
        limits = ResourceLimits()
        self.assertEqual(limits.max_memory_mb, 512)

    def test_default_max_processes(self) -> None:
        limits = ResourceLimits()
        self.assertEqual(limits.max_processes, 256)

    def test_default_max_file_size_mb(self) -> None:
        limits = ResourceLimits()
        self.assertEqual(limits.max_file_size_mb, 50)

    def test_default_max_stdout_bytes(self) -> None:
        limits = ResourceLimits()
        self.assertEqual(limits.max_stdout_bytes, 50_000)

    def test_default_max_stderr_bytes(self) -> None:
        limits = ResourceLimits()
        self.assertEqual(limits.max_stderr_bytes, 10_000)

    def test_resource_limits_is_frozen(self) -> None:
        limits = ResourceLimits()
        with self.assertRaises(AttributeError):
            limits.max_wall_seconds = 999  # type: ignore[misc]

    def test_custom_values(self) -> None:
        limits = ResourceLimits(max_wall_seconds=30, max_memory_mb=256)
        self.assertEqual(limits.max_wall_seconds, 30)
        self.assertEqual(limits.max_memory_mb, 256)

    def test_config_holds_custom_resource_limits(self) -> None:
        limits = ResourceLimits(max_wall_seconds=60)
        cfg = SandboxConfig(resource_limits=limits)
        self.assertEqual(cfg.resource_limits.max_wall_seconds, 60)


class TestCloudProfileOptions(unittest.TestCase):
    """CloudProfileOptions (formerly CloudSandboxOptions) tests."""

    def test_defaults(self) -> None:
        opts = CloudProfileOptions()
        self.assertEqual(opts.provider, "tencent")
        self.assertEqual(opts.template, "")
        self.assertEqual(opts.domain, "ap-guangzhou.tencentags.com")
        self.assertEqual(opts.api_key, "")
        self.assertEqual(opts.timeout, 3600)
        self.assertTrue(opts.allow_internet)
        self.assertEqual(opts.extra, {})

    def test_custom(self) -> None:
        opts = CloudProfileOptions(
            provider="e2b",
            template="base",
            domain="e2b.dev",
            api_key="e2b_xxx",
            timeout=7200,
            allow_internet=False,
            extra={"region": "us-east-1"},
        )
        self.assertEqual(opts.provider, "e2b")
        self.assertEqual(opts.template, "base")
        self.assertEqual(opts.domain, "e2b.dev")
        self.assertEqual(opts.api_key, "e2b_xxx")
        self.assertEqual(opts.timeout, 7200)
        self.assertFalse(opts.allow_internet)
        self.assertEqual(opts.extra["region"], "us-east-1")

    def test_frozen(self) -> None:
        opts = CloudProfileOptions()
        with self.assertRaises(AttributeError):
            opts.provider = "aws"  # type: ignore[misc]

    def test_backward_compat_alias(self) -> None:
        self.assertIs(CloudSandboxOptions, CloudProfileOptions)


class TestParseCloudProfile(unittest.TestCase):
    """_parse_cloud_profile helper tests."""

    def test_basic_fields(self) -> None:
        profile = _parse_cloud_profile({
            "provider": "e2b",
            "template": "code-interpreter",
            "domain": "e2b.dev",
            "api_key": "e2b_test",
            "timeout": 1800,
            "allow_internet": False,
        })
        self.assertEqual(profile.provider, "e2b")
        self.assertEqual(profile.template, "code-interpreter")
        self.assertEqual(profile.domain, "e2b.dev")
        self.assertEqual(profile.api_key, "e2b_test")
        self.assertEqual(profile.timeout, 1800)
        self.assertFalse(profile.allow_internet)

    def test_unknown_keys_go_to_extra(self) -> None:
        profile = _parse_cloud_profile({
            "provider": "aws",
            "region": "us-east-1",
            "role_arn": "arn:aws:lambda:...",
        })
        self.assertEqual(profile.provider, "aws")
        self.assertEqual(profile.extra["region"], "us-east-1")
        self.assertEqual(profile.extra["role_arn"], "arn:aws:lambda:...")

    def test_explicit_extra_dict(self) -> None:
        profile = _parse_cloud_profile({
            "provider": "aws",
            "extra": {"region": "eu-west-1"},
        })
        self.assertEqual(profile.extra["region"], "eu-west-1")

    def test_explicit_extra_merges_with_unknown_keys(self) -> None:
        profile = _parse_cloud_profile({
            "provider": "aws",
            "role_arn": "arn:aws:...",
            "extra": {"region": "us-west-2"},
        })
        self.assertEqual(profile.extra["region"], "us-west-2")
        self.assertEqual(profile.extra["role_arn"], "arn:aws:...")


class TestSandboxConfigCloudMultiProfile(unittest.TestCase):
    """Multi-profile clouds config parsing tests."""

    def test_from_config_section_single_cloud(self) -> None:
        """Old-style single cloud: section still works."""
        section = {
            "mode": "all",
            "backend": "cloud",
            "cloud": {
                "provider": "tencent",
                "template": "my-template",
                "domain": "ap-shanghai.tencentags.com",
                "api_key": "ark_test123",
                "timeout": 1800,
                "allow_internet": False,
            },
        }
        config = SandboxConfig.from_config_section(section)
        self.assertEqual(config.backend, "cloud")
        self.assertEqual(config.cloud.provider, "tencent")
        self.assertEqual(config.cloud.template, "my-template")
        self.assertEqual(config.cloud.domain, "ap-shanghai.tencentags.com")
        self.assertEqual(config.cloud.api_key, "ark_test123")
        self.assertEqual(config.cloud.timeout, 1800)
        self.assertFalse(config.cloud.allow_internet)

    def test_from_config_section_multi_cloud(self) -> None:
        section = {
            "mode": "all",
            "backend": "cloud",
            "cloud_profile": "tencent-sh",
            "clouds": {
                "tencent-gz": {
                    "provider": "tencent",
                    "domain": "ap-guangzhou.tencentags.com",
                    "api_key": "ark_gz",
                },
                "tencent-sh": {
                    "provider": "tencent",
                    "domain": "ap-shanghai.tencentags.com",
                    "api_key": "ark_sh",
                },
                "e2b-native": {
                    "provider": "e2b",
                    "api_key": "e2b_xxx",
                    "template": "base",
                },
            },
        }
        config = SandboxConfig.from_config_section(section)
        self.assertEqual(config.cloud_profile, "tencent-sh")
        self.assertIn("tencent-gz", config.clouds)
        self.assertIn("tencent-sh", config.clouds)
        self.assertIn("e2b-native", config.clouds)
        # effective_cloud resolves to tencent-sh
        active = config.effective_cloud()
        self.assertEqual(active.domain, "ap-shanghai.tencentags.com")
        self.assertEqual(active.api_key, "ark_sh")

    def test_from_config_section_with_extra(self) -> None:
        section = {
            "backend": "cloud",
            "clouds": {
                "aws-lambda": {
                    "provider": "aws",
                    "region": "us-east-1",
                    "role_arn": "arn:aws:lambda:...",
                },
            },
            "cloud_profile": "aws-lambda",
        }
        config = SandboxConfig.from_config_section(section)
        active = config.effective_cloud()
        self.assertEqual(active.provider, "aws")
        self.assertEqual(active.extra["region"], "us-east-1")
        self.assertEqual(active.extra["role_arn"], "arn:aws:lambda:...")

    def test_to_config_section_single_cloud(self) -> None:
        config = SandboxConfig(
            mode="all",
            backend="cloud",
            cloud=CloudProfileOptions(
                provider="tencent",
                template="test-tpl",
                api_key="ark_key",
                timeout=600,
            ),
        )
        section = config.to_config_section()
        self.assertEqual(section["backend"], "cloud")
        self.assertEqual(section["cloud"]["provider"], "tencent")
        self.assertEqual(section["cloud"]["template"], "test-tpl")
        self.assertEqual(section["cloud"]["api_key"], "ark_key")
        self.assertEqual(section["cloud"]["timeout"], 600)
        self.assertNotIn("clouds", section)
        self.assertNotIn("cloud_profile", section)

    def test_to_config_section_multi_cloud(self) -> None:
        config = SandboxConfig(
            mode="all",
            backend="cloud",
            cloud=CloudProfileOptions(provider="tencent", domain="ap-guangzhou.tencentags.com"),
            clouds={
                "tencent-sh": CloudProfileOptions(provider="tencent", domain="ap-shanghai.tencentags.com"),
            },
            cloud_profile="tencent-sh",
        )
        section = config.to_config_section()
        self.assertIn("clouds", section)
        self.assertIn("cloud_profile", section)
        self.assertEqual(section["cloud_profile"], "tencent-sh")
        self.assertIn("tencent-sh", section["clouds"])

    def test_roundtrip_single(self) -> None:
        original = SandboxConfig(
            mode="all",
            backend="cloud",
            cloud=CloudProfileOptions(
                provider="tencent",
                template="tpl",
                domain="ap-guangzhou.tencentags.com",
                api_key="ark_round",
                timeout=999,
                allow_internet=False,
            ),
        )
        section = original.to_config_section()
        restored = SandboxConfig.from_config_section(section)
        self.assertEqual(restored.cloud.provider, "tencent")
        self.assertEqual(restored.cloud.template, "tpl")
        self.assertEqual(restored.cloud.api_key, "ark_round")
        self.assertEqual(restored.cloud.timeout, 999)
        self.assertFalse(restored.cloud.allow_internet)

    def test_roundtrip_multi(self) -> None:
        original = SandboxConfig(
            mode="all",
            backend="cloud",
            cloud=CloudProfileOptions(provider="tencent"),
            clouds={
                "e2b": CloudProfileOptions(provider="e2b", api_key="e2b_test", extra={"region": "us-east-1"}),
            },
            cloud_profile="e2b",
        )
        section = original.to_config_section()
        restored = SandboxConfig.from_config_section(section)
        self.assertEqual(restored.cloud_profile, "e2b")
        self.assertIn("e2b", restored.clouds)
        self.assertEqual(restored.effective_cloud().provider, "e2b")
        self.assertEqual(restored.effective_cloud().api_key, "e2b_test")
        self.assertEqual(restored.effective_cloud().extra["region"], "us-east-1")


if __name__ == "__main__":
    unittest.main()
