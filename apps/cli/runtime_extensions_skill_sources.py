"""Skill source helper functions for the CLI runtime extension surface."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from packages.skills import (
    PublicSkillSourceDescriptor,
    SkillDefinition,
    SkillHubEntry,
    build_public_skill_source_descriptor,
    load_skill_package_definition,
    public_skill_source_descriptor_from_metadata,
)


def source_descriptor_for_hub_entry(
    entry: SkillHubEntry,
) -> PublicSkillSourceDescriptor | None:
    existing = public_skill_source_descriptor_from_metadata(entry.metadata)
    source_reference = public_hub_source_reference(entry)
    install_reference = public_hub_install_reference(entry)
    if existing is not None:
        explicit_trust = str(entry.metadata.get("trust_level") or "").strip()
        if (
            explicit_trust
            and existing.source_reference == source_reference
            and existing.install_reference == install_reference
        ):
            return existing
        return build_public_skill_source_descriptor(
            source_id=existing.source_id,
            source_label=existing.source_label,
            source_reference=source_reference,
            install_reference=install_reference,
            trust_level=local_skill_trust_level(existing.source_id, entry.metadata),
            metadata=entry.metadata,
        )
    return build_public_skill_source_descriptor(
        source_id=entry.source_id,
        source_label=entry.source_label,
        source_reference=source_reference,
        install_reference=install_reference,
        trust_level=local_skill_trust_level(entry.source_id, entry.metadata),
        metadata=entry.metadata,
    )


def remote_skill_definition(fetched) -> SkillDefinition:
    definition = load_skill_package_definition(Path(fetched.package_path))
    metadata = dict(definition.metadata)
    metadata.update(fetched.metadata)
    source_descriptor = build_public_skill_source_descriptor(
        source_id=fetched.source_id,
        source_label=fetched.source_label,
        source_reference=fetched.reference,
        install_reference=fetched.install_reference,
        trust_level=fetched.trust_level,
        metadata=fetched.metadata,
    )
    metadata.update(source_descriptor.to_metadata())
    metadata.update({"installed": False, "hub_reference": source_descriptor.source_reference})
    return replace(definition, enabled=False, metadata=metadata)


def source_descriptor_for_path(path: Path, *, source_bucket: str | None = None) -> PublicSkillSourceDescriptor:
    resolved = path.expanduser().resolve()
    bucket = (source_bucket or "path").strip().lower() or "path"
    source_reference = str(resolved.parent if resolved.name == "SKILL.md" else resolved)
    return build_public_skill_source_descriptor(
        source_id=bucket,
        source_label="Path" if bucket == "path" else bucket,
        source_reference=source_reference,
        install_reference=f"{bucket}:{source_reference}",
        trust_level="trusted",
        metadata={},
    )


def public_hub_source_reference(entry: SkillHubEntry) -> str:
    if entry.source_id == "builtin":
        return entry.skill_id
    return entry.reference


def public_hub_install_reference(entry: SkillHubEntry) -> str:
    if entry.source_id == "builtin":
        return entry.skill_id
    reference = str(entry.metadata.get("install_reference") or entry.reference).strip()
    return reference or entry.reference


def local_skill_trust_level(source_id: str, metadata: Mapping[str, Any]) -> str:
    configured = str(metadata.get("trust_level") or "").strip().lower()
    if configured:
        return configured
    if source_id == "builtin":
        return "builtin"
    if source_id in {
        "path",
        "elephant-installed",
        "elephant-authored",
    } or source_id.startswith("custom-"):
        return "trusted"
    return "community"


def normalized_install_requester(requester: str | None) -> str:
    return str(requester or "").strip().lower() or "operator"


def installed_skill_record(path: Path) -> dict[str, Any] | None:
    resolved = path.expanduser().resolve()
    try:
        definition = load_skill_package_definition(resolved)
    except Exception:
        return None
    descriptor = public_skill_source_descriptor_from_metadata(definition.metadata)
    return {
        "path": str(resolved),
        "skill_id": definition.skill_id,
        "install_reference": record_install_reference(
            {
                "path": str(resolved),
                "skill_id": definition.skill_id,
                "descriptor": descriptor,
            }
        ),
        "descriptor": descriptor,
    }


def matching_install_record(
    records: list[dict[str, Any]],
    *,
    source_descriptor: PublicSkillSourceDescriptor | None,
    selection_path: Path,
) -> dict[str, Any] | None:
    if source_descriptor is not None:
        for record in records:
            if record_install_reference(record) == source_descriptor.install_reference:
                return record
    resolved_fallback = selection_path.expanduser().resolve()
    for record in records:
        if Path(str(record["path"])).expanduser().resolve() == resolved_fallback:
            return record
    return None


def record_install_reference(record: Mapping[str, Any]) -> str | None:
    descriptor = record.get("descriptor")
    if isinstance(descriptor, PublicSkillSourceDescriptor):
        return descriptor.install_reference
    path = Path(str(record.get("path") or "")).expanduser().resolve()
    skill_id = str(record.get("skill_id") or "").strip()
    if skill_id and len(path.parts) >= 2 and path.name == "SKILL.md":
        bucket = path.parent.parent.name
        if bucket:
            return f"{bucket}:{skill_id}"
    resolved = str(path).strip()
    return resolved or None


def install_record_detail(
    *,
    source_descriptor: PublicSkillSourceDescriptor | None,
    install_action: str,
    previous_install_reference: str | None,
) -> str:
    if source_descriptor is None:
        return install_action
    if install_action == "migrate" and previous_install_reference:
        return (
            f"migrated via {source_descriptor.source_label}"
            f" from {previous_install_reference}"
            f" to {source_descriptor.install_reference}"
        )
    if install_action == "refresh":
        return f"refreshed via {source_descriptor.source_label} ({source_descriptor.trust_level})"
    return f"installed via {source_descriptor.source_label} ({source_descriptor.trust_level})"
