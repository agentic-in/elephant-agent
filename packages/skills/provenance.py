"""Canonical public skill-source descriptors and installed-skill provenance."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

PERSISTED_SOURCE_DESCRIPTOR_FIELDS = (
    "source_id",
    "source_label",
    "source_reference",
    "install_reference",
    "trust_level",
    "canonical_id",
    "source_detail_url",
    "source_repo_url",
    "source_version",
)

PERSISTED_INSTALL_PROVENANCE_FIELDS = (
    "install_action",
    "installed_at",
    "install_requester",
    "previous_install_reference",
)


@dataclass(frozen=True, slots=True)
class PublicSkillSourceDescriptor:
    source_id: str
    source_label: str
    source_reference: str
    install_reference: str
    trust_level: str = "community"
    canonical_id: str | None = None
    source_detail_url: str | None = None
    source_repo_url: str | None = None
    source_version: str | None = None

    def to_metadata(self) -> dict[str, str]:
        metadata = {
            "source_id": self.source_id,
            "source_label": self.source_label,
            "source_reference": self.source_reference,
            "install_reference": self.install_reference,
            "trust_level": self.trust_level,
        }
        if self.canonical_id:
            metadata["canonical_id"] = self.canonical_id
        if self.source_detail_url:
            metadata["source_detail_url"] = self.source_detail_url
        if self.source_repo_url:
            metadata["source_repo_url"] = self.source_repo_url
        if self.source_version:
            metadata["source_version"] = self.source_version
        return metadata


@dataclass(frozen=True, slots=True)
class InstalledSkillProvenance:
    source: PublicSkillSourceDescriptor
    install_action: str
    installed_at: str
    install_requester: str | None = None
    previous_install_reference: str | None = None

    def to_metadata(self) -> dict[str, str]:
        metadata = self.source.to_metadata()
        metadata["install_action"] = self.install_action
        metadata["installed_at"] = self.installed_at
        if self.install_requester:
            metadata["install_requester"] = self.install_requester
        if self.previous_install_reference:
            metadata["previous_install_reference"] = self.previous_install_reference
        return metadata


def build_public_skill_source_descriptor(
    *,
    source_id: str,
    source_label: str,
    source_reference: str,
    install_reference: str,
    trust_level: str = "community",
    metadata: Mapping[str, Any] | None = None,
) -> PublicSkillSourceDescriptor:
    payload = dict(metadata or {})
    return PublicSkillSourceDescriptor(
        source_id=source_id,
        source_label=source_label,
        source_reference=source_reference.strip(),
        install_reference=(install_reference or source_reference).strip(),
        trust_level=(trust_level or "community").strip() or "community",
        canonical_id=_metadata_string(payload, "canonical_id"),
        source_detail_url=_metadata_string(payload, "source_detail_url", "detail_url"),
        source_repo_url=_metadata_string(payload, "source_repo_url", "repo_url"),
        source_version=_metadata_string(payload, "source_version", "version"),
    )


def build_installed_skill_provenance(
    *,
    source: PublicSkillSourceDescriptor,
    install_action: str,
    installed_at: str,
    install_requester: str | None = None,
    previous_install_reference: str | None = None,
) -> InstalledSkillProvenance:
    return InstalledSkillProvenance(
        source=source,
        install_action=install_action.strip(),
        installed_at=installed_at.strip(),
        install_requester=_optional_string(install_requester),
        previous_install_reference=_optional_string(previous_install_reference),
    )


def public_skill_source_descriptor_from_metadata(
    metadata: Mapping[str, Any],
) -> PublicSkillSourceDescriptor | None:
    source_id = _optional_string(metadata.get("source_id"))
    source_label = _optional_string(metadata.get("source_label"))
    source_reference = _optional_string(metadata.get("source_reference") or metadata.get("hub_reference"))
    install_reference = _optional_string(metadata.get("install_reference"))
    if source_id is None or source_label is None or (source_reference is None and install_reference is None):
        return None
    return build_public_skill_source_descriptor(
        source_id=source_id,
        source_label=source_label,
        source_reference=source_reference or install_reference or "",
        install_reference=install_reference or source_reference or "",
        trust_level=_default_trust_level(source_id, metadata),
        metadata=metadata,
    )


def installed_skill_provenance_from_metadata(
    metadata: Mapping[str, Any],
) -> InstalledSkillProvenance | None:
    source = public_skill_source_descriptor_from_metadata(metadata)
    if source is None:
        return None
    install_action = _optional_string(metadata.get("install_action"))
    installed_at = _optional_string(metadata.get("installed_at"))
    install_requester = _optional_string(metadata.get("install_requester"))
    previous_install_reference = _optional_string(metadata.get("previous_install_reference"))
    if (
        install_action is None
        and installed_at is None
        and install_requester is None
        and previous_install_reference is None
    ):
        return None
    return InstalledSkillProvenance(
        source=source,
        install_action=install_action or "install",
        installed_at=installed_at or "",
        install_requester=install_requester,
        previous_install_reference=previous_install_reference,
    )


def install_bucket_for_source_descriptor(source: PublicSkillSourceDescriptor) -> str:
    prefix, separator, _rest = source.install_reference.partition(":")
    if separator and prefix.strip():
        return prefix.strip().lower()
    return source.source_id.strip().lower()


def skill_provenance_fields(metadata: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    fields: list[tuple[str, str]] = []
    source = public_skill_source_descriptor_from_metadata(metadata)
    if source is not None:
        fields.append(("source", f"{source.source_label} ({source.source_id})"))
        fields.append(("source_reference", source.source_reference))
        fields.append(("install_reference", source.install_reference))
        fields.append(("trust_level", source.trust_level))
        if source.canonical_id:
            fields.append(("canonical_id", source.canonical_id))
        if source.source_detail_url:
            fields.append(("source_detail_url", source.source_detail_url))
        if source.source_repo_url:
            fields.append(("source_repo_url", source.source_repo_url))
        if source.source_version:
            fields.append(("source_version", source.source_version))
    source_kind = _optional_string(metadata.get("source_kind"))
    if source_kind is not None:
        fields.append(("source_kind", source_kind))
    storage_tier = _optional_string(metadata.get("storage_tier"))
    if storage_tier is not None:
        fields.append(("storage_tier", storage_tier))
    default_enabled = metadata.get("default_enabled")
    if isinstance(default_enabled, bool):
        fields.append(("default_enabled", str(default_enabled).lower()))
    install = installed_skill_provenance_from_metadata(metadata)
    if install is not None:
        fields.append(("install_action", install.install_action))
        if install.installed_at:
            fields.append(("installed_at", install.installed_at))
        if install.install_requester:
            fields.append(("install_requester", install.install_requester))
        if install.previous_install_reference:
            fields.append(("previous_install_reference", install.previous_install_reference))
    return tuple(fields)


def _metadata_string(metadata: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _optional_string(metadata.get(key))
        if value is not None:
            return value
    return None


def _optional_string(value: Any) -> str | None:
    resolved = str(value or "").strip()
    return resolved or None


def _default_trust_level(source_id: str, metadata: Mapping[str, Any]) -> str:
    explicit = _optional_string(metadata.get("trust_level"))
    if explicit is not None:
        return explicit
    if source_id == "builtin":
        return "builtin"
    if source_id in {
        "path",
        "elephant-installed",
        "elephant-authored",
    } or source_id.startswith("custom-"):
        return "trusted"
    return "community"
