"""Unit tests for packages.skills.provenance data logic."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.skills.provenance import (
    PERSISTED_INSTALL_PROVENANCE_FIELDS,
    PERSISTED_SOURCE_DESCRIPTOR_FIELDS,
    InstalledSkillProvenance,
    PublicSkillSourceDescriptor,
    build_installed_skill_provenance,
    build_public_skill_source_descriptor,
    install_bucket_for_source_descriptor,
    installed_skill_provenance_from_metadata,
    public_skill_source_descriptor_from_metadata,
    skill_provenance_fields,
)


def _make_source(**overrides: object) -> PublicSkillSourceDescriptor:
    defaults = {
        "source_id": "test-source",
        "source_label": "Test Source",
        "source_reference": "test-ref",
        "install_reference": "test-install-ref",
    }
    defaults.update(overrides)
    return PublicSkillSourceDescriptor(**defaults)  # type: ignore[arg-type]


class TestPublicSkillSourceDescriptor(unittest.TestCase):
    def test_to_metadata_required_fields(self) -> None:
        desc = _make_source()
        meta = desc.to_metadata()
        self.assertEqual(meta["source_id"], "test-source")
        self.assertEqual(meta["source_label"], "Test Source")
        self.assertEqual(meta["source_reference"], "test-ref")
        self.assertEqual(meta["install_reference"], "test-install-ref")
        self.assertEqual(meta["trust_level"], "community")

    def test_to_metadata_optional_fields_omitted_when_none(self) -> None:
        desc = _make_source()
        meta = desc.to_metadata()
        self.assertNotIn("canonical_id", meta)
        self.assertNotIn("source_detail_url", meta)
        self.assertNotIn("source_repo_url", meta)
        self.assertNotIn("source_version", meta)

    def test_to_metadata_includes_optional_fields_when_set(self) -> None:
        desc = _make_source(
            canonical_id="canonical-123",
            source_detail_url="https://example.com/detail",
            source_repo_url="https://example.com/repo",
            source_version="2.0.0",
        )
        meta = desc.to_metadata()
        self.assertEqual(meta["canonical_id"], "canonical-123")
        self.assertEqual(meta["source_detail_url"], "https://example.com/detail")
        self.assertEqual(meta["source_repo_url"], "https://example.com/repo")
        self.assertEqual(meta["source_version"], "2.0.0")

    def test_frozen(self) -> None:
        desc = _make_source()
        with self.assertRaises(AttributeError):
            desc.source_id = "changed"  # type: ignore[misc]


class TestInstalledSkillProvenance(unittest.TestCase):
    def test_to_metadata_includes_source_fields(self) -> None:
        source = _make_source()
        prov = InstalledSkillProvenance(
            source=source,
            install_action="install",
            installed_at="2025-01-01T00:00:00Z",
        )
        meta = prov.to_metadata()
        self.assertEqual(meta["source_id"], "test-source")
        self.assertEqual(meta["install_action"], "install")
        self.assertEqual(meta["installed_at"], "2025-01-01T00:00:00Z")

    def test_to_metadata_optional_fields(self) -> None:
        source = _make_source()
        prov = InstalledSkillProvenance(
            source=source,
            install_action="update",
            installed_at="2025-01-01T00:00:00Z",
            install_requester="user-1",
            previous_install_reference="old-ref",
        )
        meta = prov.to_metadata()
        self.assertEqual(meta["install_requester"], "user-1")
        self.assertEqual(meta["previous_install_reference"], "old-ref")

    def test_to_metadata_omits_none_optional_fields(self) -> None:
        source = _make_source()
        prov = InstalledSkillProvenance(
            source=source,
            install_action="install",
            installed_at="2025-01-01T00:00:00Z",
        )
        meta = prov.to_metadata()
        self.assertNotIn("install_requester", meta)
        self.assertNotIn("previous_install_reference", meta)


class TestBuildPublicSkillSourceDescriptor(unittest.TestCase):
    def test_basic_construction(self) -> None:
        desc = build_public_skill_source_descriptor(
            source_id="hub",
            source_label="Hub",
            source_reference="hub/ref",
            install_reference="hub/ref",
        )
        self.assertEqual(desc.source_id, "hub")
        self.assertEqual(desc.trust_level, "community")

    def test_strips_whitespace(self) -> None:
        desc = build_public_skill_source_descriptor(
            source_id=" hub ",
            source_label=" Hub ",
            source_reference=" hub/ref ",
            install_reference=" hub/ref ",
        )
        self.assertEqual(desc.source_reference, "hub/ref")
        self.assertEqual(desc.install_reference, "hub/ref")

    def test_install_reference_defaults_to_source_reference(self) -> None:
        desc = build_public_skill_source_descriptor(
            source_id="hub",
            source_label="Hub",
            source_reference="hub/ref",
            install_reference=None,
        )
        self.assertEqual(desc.install_reference, "hub/ref")

    def test_metadata_fields_populated(self) -> None:
        desc = build_public_skill_source_descriptor(
            source_id="hub",
            source_label="Hub",
            source_reference="hub/ref",
            install_reference="hub/ref",
            metadata={
                "canonical_id": "c-1",
                "source_version": "1.0",
            },
        )
        self.assertEqual(desc.canonical_id, "c-1")
        self.assertEqual(desc.source_version, "1.0")

    def test_empty_trust_level_defaults_to_community(self) -> None:
        desc = build_public_skill_source_descriptor(
            source_id="hub",
            source_label="Hub",
            source_reference="hub/ref",
            install_reference="hub/ref",
            trust_level="",
        )
        self.assertEqual(desc.trust_level, "community")


class TestBuildInstalledSkillProvenance(unittest.TestCase):
    def test_basic_construction(self) -> None:
        source = _make_source()
        prov = build_installed_skill_provenance(
            source=source,
            install_action=" install ",
            installed_at=" 2025-01-01 ",
        )
        self.assertEqual(prov.install_action, "install")
        self.assertEqual(prov.installed_at, "2025-01-01")

    def test_strips_optional_fields(self) -> None:
        source = _make_source()
        prov = build_installed_skill_provenance(
            source=source,
            install_action="install",
            installed_at="2025-01-01",
            install_requester="  user  ",
            previous_install_reference="  old  ",
        )
        self.assertEqual(prov.install_requester, "user")
        self.assertEqual(prov.previous_install_reference, "old")

    def test_whitespace_only_optional_becomes_none(self) -> None:
        source = _make_source()
        prov = build_installed_skill_provenance(
            source=source,
            install_action="install",
            installed_at="2025-01-01",
            install_requester="   ",
            previous_install_reference="   ",
        )
        self.assertIsNone(prov.install_requester)
        self.assertIsNone(prov.previous_install_reference)


class TestPublicSkillSourceDescriptorFromMetadata(unittest.TestCase):
    def test_valid_metadata(self) -> None:
        meta = {
            "source_id": "hub",
            "source_label": "Hub",
            "source_reference": "hub/ref",
            "install_reference": "hub/ref",
        }
        desc = public_skill_source_descriptor_from_metadata(meta)
        self.assertIsNotNone(desc)
        self.assertEqual(desc.source_id, "hub")  # type: ignore[union-attr]

    def test_missing_source_id_returns_none(self) -> None:
        meta = {
            "source_label": "Hub",
            "source_reference": "hub/ref",
        }
        self.assertIsNone(public_skill_source_descriptor_from_metadata(meta))

    def test_missing_source_reference_and_install_reference_returns_none(self) -> None:
        meta = {
            "source_id": "hub",
            "source_label": "Hub",
        }
        self.assertIsNone(public_skill_source_descriptor_from_metadata(meta))

    def test_hub_reference_fallback(self) -> None:
        meta = {
            "source_id": "hub",
            "source_label": "Hub",
            "hub_reference": "hub/fallback-ref",
        }
        desc = public_skill_source_descriptor_from_metadata(meta)
        self.assertIsNotNone(desc)
        self.assertEqual(desc.source_reference, "hub/fallback-ref")  # type: ignore[union-attr]

    def test_builtin_default_trust(self) -> None:
        meta = {
            "source_id": "builtin",
            "source_label": "Builtin",
            "source_reference": "builtin/ref",
        }
        desc = public_skill_source_descriptor_from_metadata(meta)
        self.assertEqual(desc.trust_level, "builtin")  # type: ignore[union-attr]


class TestInstalledSkillProvenanceFromMetadata(unittest.TestCase):
    def test_valid_metadata(self) -> None:
        meta = {
            "source_id": "hub",
            "source_label": "Hub",
            "source_reference": "hub/ref",
            "install_action": "install",
            "installed_at": "2025-01-01",
        }
        prov = installed_skill_provenance_from_metadata(meta)
        self.assertIsNotNone(prov)
        self.assertEqual(prov.install_action, "install")  # type: ignore[union-attr]

    def test_missing_install_fields_returns_none(self) -> None:
        meta = {
            "source_id": "hub",
            "source_label": "Hub",
            "source_reference": "hub/ref",
        }
        self.assertIsNone(installed_skill_provenance_from_metadata(meta))

    def test_install_action_defaults_to_install(self) -> None:
        meta = {
            "source_id": "hub",
            "source_label": "Hub",
            "source_reference": "hub/ref",
            "installed_at": "2025-01-01",
        }
        prov = installed_skill_provenance_from_metadata(meta)
        self.assertIsNotNone(prov)
        self.assertEqual(prov.install_action, "install")  # type: ignore[union-attr]


class TestInstallBucketForSourceDescriptor(unittest.TestCase):
    def test_colon_prefix(self) -> None:
        desc = _make_source(install_reference="npm:lodash@4")
        self.assertEqual(install_bucket_for_source_descriptor(desc), "npm")

    def test_no_colon_uses_source_id(self) -> None:
        desc = _make_source(install_reference="local-path")
        self.assertEqual(install_bucket_for_source_descriptor(desc), "test-source")

    def test_empty_prefix_falls_back_to_source_id(self) -> None:
        desc = _make_source(install_reference=":something")
        self.assertEqual(install_bucket_for_source_descriptor(desc), "test-source")


class TestSkillProvenanceFields(unittest.TestCase):
    def test_full_metadata(self) -> None:
        meta = {
            "source_id": "hub",
            "source_label": "Hub",
            "source_reference": "hub/ref",
            "install_reference": "hub/ref",
            "install_action": "install",
            "installed_at": "2025-01-01",
            "source_kind": "external",
        }
        fields = skill_provenance_fields(meta)
        keys = [key for key, _ in fields]
        self.assertIn("source", keys)
        self.assertIn("source_reference", keys)
        self.assertIn("install_reference", keys)
        self.assertIn("trust_level", keys)
        self.assertIn("install_action", keys)
        self.assertIn("installed_at", keys)
        self.assertIn("source_kind", keys)

    def test_minimal_metadata(self) -> None:
        meta = {
            "source_id": "builtin",
            "source_label": "Builtin",
            "source_reference": "builtin/ref",
        }
        fields = skill_provenance_fields(meta)
        keys = [key for key, _ in fields]
        self.assertIn("source", keys)
        self.assertIn("trust_level", keys)
        self.assertNotIn("install_action", keys)

    def test_empty_metadata(self) -> None:
        fields = skill_provenance_fields({})
        self.assertEqual(fields, ())

    def test_default_enabled_bool_field(self) -> None:
        meta = {
            "source_id": "hub",
            "source_label": "Hub",
            "source_reference": "hub/ref",
            "default_enabled": True,
        }
        fields = skill_provenance_fields(meta)
        keys = [key for key, _ in fields]
        self.assertIn("default_enabled", keys)
        # Find the default_enabled value
        for key, value in fields:
            if key == "default_enabled":
                self.assertEqual(value, "true")
                break


class TestRoundTripSerialization(unittest.TestCase):
    def test_source_descriptor_round_trip(self) -> None:
        desc = build_public_skill_source_descriptor(
            source_id="hub",
            source_label="Hub",
            source_reference="hub/ref",
            install_reference="hub/ref",
            trust_level="trusted",
            metadata={
                "canonical_id": "c-1",
                "source_version": "1.0",
            },
        )
        meta = desc.to_metadata()
        restored = public_skill_source_descriptor_from_metadata(meta)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.source_id, desc.source_id)  # type: ignore[union-attr]
        self.assertEqual(restored.source_label, desc.source_label)  # type: ignore[union-attr]
        self.assertEqual(restored.source_reference, desc.source_reference)  # type: ignore[union-attr]
        self.assertEqual(restored.canonical_id, desc.canonical_id)  # type: ignore[union-attr]
        self.assertEqual(restored.source_version, desc.source_version)  # type: ignore[union-attr]

    def test_provenance_round_trip(self) -> None:
        source = build_public_skill_source_descriptor(
            source_id="hub",
            source_label="Hub",
            source_reference="hub/ref",
            install_reference="hub/ref",
        )
        prov = build_installed_skill_provenance(
            source=source,
            install_action="install",
            installed_at="2025-01-01",
            install_requester="user-1",
        )
        meta = prov.to_metadata()
        restored = installed_skill_provenance_from_metadata(meta)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.install_action, prov.install_action)  # type: ignore[union-attr]
        self.assertEqual(restored.installed_at, prov.installed_at)  # type: ignore[union-attr]
        self.assertEqual(restored.install_requester, prov.install_requester)  # type: ignore[union-attr]


if __name__ == "__main__":
    unittest.main()
