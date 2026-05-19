"""Static public skills projection derived from the canonical skill catalog."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .builtins import builtin_skill_catalog
from .hub import SkillCatalogEntry
from .provenance import public_skill_source_descriptor_from_metadata

_CATALOG_HEADLINE = "Browse the skills that ship with Elephant Agent."
_CATALOG_SUMMARY = "Packaged Elephant Agent skills and the external source lanes the CLI can install from."
_BUILTIN_POSTURE = (
    "Bundled skills already ship with Elephant Agent. Use `elephant skills install "
    "<skill-id>` only when you want an explicit local materialization record "
    "for one packaged skill."
)
_CURATED_ORIGIN_POSTURE = (
    "Bundled entries come from the packaged Elephant Agent catalog. External skills "
    "stay separate until the operator chooses a source and reference."
)
_OPERATOR_INSTALL_POSTURE = (
    "External skills stay explicit CLI actions: use `elephant skills search "
    "<query>` to browse and `elephant skills install <source:reference>` to "
    "materialize one."
)


@dataclass(frozen=True, slots=True)
class SkillHubSiteEntry:
    skill_id: str
    slug: str
    display_name: str
    summary: str
    reference: str
    section_id: str
    section_display_name: str
    detail_doc_id: str
    detail_path: str
    source_id: str
    source_label: str
    source_kind: str
    storage_tier: str
    default_enabled: bool
    default_enabled_label: str
    source_reference: str
    install_reference: str
    install_command: str
    trust_level: str
    packaging_posture: str
    install_posture: str
    operator_install_posture: str
    source_detail_url: str
    source_repo_url: str
    aliases: tuple[str, ...] = ()
    trigger_phrases: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()
    requires_tools: tuple[str, ...] = ()
    requires_toolsets: tuple[str, ...] = ()
    required_environment_variables: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SkillHubSiteSection:
    section_id: str
    display_name: str
    summary: str
    entry_count: int
    entries: tuple[SkillHubSiteEntry, ...]


@dataclass(frozen=True, slots=True)
class SkillHubSiteExternalSource:
    source_id: str
    display_name: str
    summary: str
    trust_posture: str
    reference_pattern: str
    search_command: str
    install_command: str


@dataclass(frozen=True, slots=True)
class SkillHubSiteCatalog:
    generated_at: str
    headline: str
    summary: str
    builtin_posture: str
    curated_origin_posture: str
    operator_install_posture: str
    stats: dict[str, int]
    external_sources: tuple[SkillHubSiteExternalSource, ...]
    sections: tuple[SkillHubSiteSection, ...]
    entries: tuple[SkillHubSiteEntry, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=False)


def build_skillhub_site_catalog(*, root: Path | None = None) -> SkillHubSiteCatalog:
    builtin_catalog = builtin_skill_catalog(root=root)
    external_sources = _external_install_lanes()
    section_membership: dict[str, tuple[str, str]] = {}
    for section in builtin_catalog.sections:
        for entry in section.entries:
            if entry.visibility.include_in_site:
                section_membership[entry.skill_id] = (
                    section.section_id,
                    section.display_name,
                )
    entries = [
        _site_entry_for_catalog_entry(
            entry,
            section_id=section_membership[entry.skill_id][0],
            section_display_name=section_membership[entry.skill_id][1],
        )
        for entry in builtin_catalog.site_entries()
    ]
    entries_by_id = {entry.skill_id: entry for entry in entries}
    sections: list[SkillHubSiteSection] = []
    for section in builtin_catalog.sections:
        section_entries = tuple(
            entries_by_id[entry.skill_id] for entry in section.entries if entry.visibility.include_in_site
        )
        if not section_entries:
            continue
        sections.append(
            SkillHubSiteSection(
                section_id=section.section_id,
                display_name=section.display_name,
                summary=section.summary,
                entry_count=len(section_entries),
                entries=section_entries,
            )
        )
    entry_count = len(entries)
    return SkillHubSiteCatalog(
        generated_at=_utc_timestamp(),
        headline=_CATALOG_HEADLINE,
        summary=_CATALOG_SUMMARY,
        builtin_posture=_BUILTIN_POSTURE,
        curated_origin_posture=_CURATED_ORIGIN_POSTURE,
        operator_install_posture=_OPERATOR_INSTALL_POSTURE,
        stats={
            "entry_count": entry_count,
            "section_count": len(sections),
            "external_source_count": len(external_sources),
            "default_enabled_count": sum(1 for entry in entries if entry.default_enabled),
        },
        external_sources=external_sources,
        sections=tuple(sections),
        entries=tuple(entries),
    )


def _site_entry_for_catalog_entry(
    entry: SkillCatalogEntry,
    *,
    section_id: str,
    section_display_name: str,
) -> SkillHubSiteEntry:
    slug = entry.skill_id
    detail_doc_id = f"skillhub/library/{slug}"
    detail_path = f"/skillhub/library/{slug}/"
    source_reference = _source_reference(entry)
    install_reference = _install_reference(entry)
    return SkillHubSiteEntry(
        skill_id=entry.skill_id,
        slug=slug,
        display_name=entry.display_name,
        summary=entry.summary,
        reference=_public_reference(entry),
        section_id=section_id,
        section_display_name=section_display_name,
        detail_doc_id=detail_doc_id,
        detail_path=detail_path,
        source_id=entry.source_id,
        source_label=entry.source_label,
        source_kind=entry.source_kind,
        storage_tier=entry.storage_tier,
        default_enabled=entry.default_enabled,
        default_enabled_label=_default_enabled_label(entry.default_enabled),
        source_reference=source_reference,
        install_reference=install_reference,
        install_command=f"elephant skills install {install_reference}",
        trust_level=_trust_level(entry),
        source_detail_url=_source_detail_url(entry),
        source_repo_url=_source_repo_url(entry),
        packaging_posture=_packaging_posture(entry),
        install_posture=_install_posture(entry),
        operator_install_posture=_OPERATOR_INSTALL_POSTURE,
        aliases=_metadata_strings(entry.metadata, "aliases"),
        trigger_phrases=_metadata_strings(entry.metadata, "trigger_phrases"),
        keywords=_metadata_strings(entry.metadata, "keywords"),
        platforms=_metadata_strings(entry.metadata, "platforms"),
        requires_tools=_metadata_strings(entry.metadata, "requires_tools"),
        requires_toolsets=_metadata_strings(entry.metadata, "requires_toolsets"),
        required_environment_variables=_metadata_strings(
            entry.metadata,
            "required_environment_variables",
        ),
    )


def _metadata_strings(metadata: dict[str, Any] | Any, key: str) -> tuple[str, ...]:
    raw = metadata.get(key) if isinstance(metadata, dict) else None
    if isinstance(raw, (tuple, list, set)):
        return tuple(str(item).strip() for item in raw if str(item).strip())
    if raw is None:
        return ()
    value = str(raw).strip()
    return (value,) if value else ()


def _default_enabled_label(default_enabled: bool) -> str:
    return "Enabled by default" if default_enabled else "Disabled by default"


def _packaging_posture(entry: SkillCatalogEntry) -> str:
    if entry.source_id == "builtin":
        return "Bundled with the packaged Elephant Agent CLI as a built-in procedural skill."
    return "Published from the canonical skill catalog for static site consumption."


def _install_posture(entry: SkillCatalogEntry) -> str:
    if entry.source_id == "builtin":
        return (
            "Already ships inside the packaged Elephant Agent bundle. Use "
            f"`elephant skills install {_install_reference(entry)}` only when you "
            "want an explicit local materialization record."
        )
    return (
        "Installed separately by the operator through explicit CLI flows with "
        f"`elephant skills install {_install_reference(entry)}`."
    )


def _public_reference(entry: SkillCatalogEntry) -> str:
    if entry.source_id == "builtin":
        return entry.skill_id
    descriptor = public_skill_source_descriptor_from_metadata(entry.metadata)
    if descriptor is not None and descriptor.source_reference:
        return descriptor.source_reference
    return entry.reference


def _source_reference(entry: SkillCatalogEntry) -> str:
    if entry.source_id == "builtin":
        return entry.skill_id
    descriptor = public_skill_source_descriptor_from_metadata(entry.metadata)
    if descriptor is not None and descriptor.source_reference:
        return descriptor.source_reference
    return entry.reference


def _install_reference(entry: SkillCatalogEntry) -> str:
    if entry.source_id == "builtin":
        return entry.skill_id
    descriptor = public_skill_source_descriptor_from_metadata(entry.metadata)
    if descriptor is not None and descriptor.install_reference:
        return descriptor.install_reference
    return str(entry.metadata.get("install_reference") or entry.reference).strip() or entry.reference


def _trust_level(entry: SkillCatalogEntry) -> str:
    descriptor = public_skill_source_descriptor_from_metadata(entry.metadata)
    if descriptor is not None and descriptor.trust_level:
        return descriptor.trust_level
    if entry.source_id == "builtin":
        return "builtin"
    if entry.source_id in {"path", "elephant-installed", "elephant-authored"}:
        return "trusted"
    return str(entry.metadata.get("trust_level") or "community").strip() or "community"


def _source_detail_url(entry: SkillCatalogEntry) -> str:
    descriptor = public_skill_source_descriptor_from_metadata(entry.metadata)
    if descriptor is not None and descriptor.source_detail_url:
        return descriptor.source_detail_url
    return ""


def _source_repo_url(entry: SkillCatalogEntry) -> str:
    descriptor = public_skill_source_descriptor_from_metadata(entry.metadata)
    if descriptor is not None and descriptor.source_repo_url:
        return descriptor.source_repo_url
    return ""


def _external_install_lanes() -> tuple[SkillHubSiteExternalSource, ...]:
    return (
        SkillHubSiteExternalSource(
            source_id="github",
            display_name="GitHub",
            summary=("Install a public skill directly from a repository path that contains a `SKILL.md` package."),
            trust_posture="Trusted or community, depending on repo provenance.",
            reference_pattern="github:<owner>/<repo>/<skill-path>",
            search_command="elephant skills search <query> --source github",
            install_command="elephant skills install github:<owner>/<repo>/<skill-path>",
        ),
        SkillHubSiteExternalSource(
            source_id="skills-sh",
            display_name="Skills.sh",
            summary=(
                "Search the Skills.sh index, then install the canonical GitHub "
                "reference Elephant Agent resolves for that package."
            ),
            trust_posture="Trust follows the resolved source repository.",
            reference_pattern="skills-sh:<owner>/<repo>/<skill-path>",
            search_command="elephant skills search <query> --source skills-sh",
            install_command="elephant skills install github:<owner>/<repo>/<skill-path>",
        ),
        SkillHubSiteExternalSource(
            source_id="well-known",
            display_name="Well-Known",
            summary=(
                "Load a skill from a published `/.well-known/skills` endpoint without "
                "turning the site into a hosted registry."
            ),
            trust_posture="Community by default.",
            reference_pattern=("well-known:https://example.com/.well-known/skills/index.json#skill-name"),
            search_command="elephant skills search https://example.com --source well-known",
            install_command=(
                "elephant skills install well-known:https://example.com/.well-known/skills/index.json#skill-name"
            ),
        ),
        SkillHubSiteExternalSource(
            source_id="clawhub",
            display_name="ClawHub",
            summary="Install a packaged community skill directly by ClawHub slug.",
            trust_posture="Community.",
            reference_pattern="clawhub:<skill-slug>",
            search_command="elephant skills search <query> --source clawhub",
            install_command="elephant skills install clawhub:<skill-slug>",
        ),
        SkillHubSiteExternalSource(
            source_id="claude-marketplace",
            display_name="Claude Marketplace",
            summary=(
                "Search marketplace repo descriptors, then install the canonical "
                "GitHub skill path Elephant Agent resolves."
            ),
            trust_posture="Trust follows the resolved source repository.",
            reference_pattern="claude-marketplace:<owner>/<repo>/<skill-path>",
            search_command="elephant skills search <query> --source claude-marketplace",
            install_command="elephant skills install github:<owner>/<repo>/<skill-path>",
        ),
        SkillHubSiteExternalSource(
            source_id="lobehub",
            display_name="LobeHub",
            summary=(
                "Materialize a LobeHub agent template into a local skill package through the explicit install surface."
            ),
            trust_posture="Community.",
            reference_pattern="lobehub:<agent-id>",
            search_command="elephant skills search <query> --source lobehub",
            install_command="elephant skills install lobehub:<agent-id>",
        ),
    )


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("json",), default="json")
    args = parser.parse_args(argv)
    catalog = build_skillhub_site_catalog()
    if args.format == "json":
        print(catalog.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
