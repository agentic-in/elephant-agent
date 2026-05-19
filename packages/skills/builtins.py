"""Canonical built-in skill projections for Elephant Agent product surfaces."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .hub import (
    SkillCatalogEntry,
    SkillHubEntry,
    SkillHubSource,
    builtin_elephant_skill_source_root,
    builtin_skill_catalog_entries as _builtin_skill_catalog_entries,
)
from .runtime import SkillDefinition

_BUILTIN_SECTION_DISPLAY_NAMES: Mapping[str, str] = {
    "autonomous-ai-agents": "Autonomous AI Agents",
    "apple": "Apple",
    "communication": "Communication",
    "continuity": "Continuity",
    "creative": "Creative",
    "data-science": "Data Science",
    "devops": "DevOps",
    "email": "Email",
    "gaming": "Gaming",
    "github": "GitHub",
    "leisure": "Leisure",
    "mcp": "MCP",
    "media": "Media",
    "migration": "Migration",
    "mlops": "MLOps",
    "note-taking": "Note Taking",
    "productivity": "Productivity",
    "red-teaming": "Red Teaming",
    "research": "Research",
    "runtime": "Runtime",
    "security": "Security",
    "smart-home": "Smart Home",
    "social-media": "Social Media",
    "software-development": "Software Development",
    "voice": "Voice",
}

_BUILTIN_SECTION_SUMMARIES: Mapping[str, str] = {
    "autonomous-ai-agents": "Elephant Agent-native guidance for autonomous agent workflows and persona framing.",
    "apple": "macOS and Apple-device workflows curated as repo-bundled operator guides.",
    "communication": "Decision briefs and communication frameworks that keep operator proposals explicit and actionable.",
    "continuity": "Procedures that protect canonical identity, relationship, and resume-state continuity.",
    "creative": "Design, diagram, and visual-production workflows kept crisp, editable, and static-first.",
    "data-science": "Notebook and exploratory-analysis procedures that stay reproducible instead of one-off.",
    "devops": "Operational integration and automation workflows for event-driven systems and delivery surfaces.",
    "email": "Email delivery and mailbox workflows aligned with the shared runtime boundary.",
    "gaming": "Game-focused operator guides for servers, play support, and interactive hobby workflows.",
    "github": "Repository, review, and issue workflows packaged as built-in procedural guides.",
    "leisure": "Local-life and lifestyle tasks that fit the Elephant Agent operator shell.",
    "mcp": "Model Context Protocol setup and interoperability guides curated for Elephant Agent.",
    "media": "Media lookup and content workflows that stay procedural instead of tool-owned.",
    "migration": "Migration playbooks that move state, settings, and habits from adjacent agent runtimes into Elephant Agent.",
    "mlops": "Model, inference, evaluation, and retrieval workflows kept explicit, reproducible, and operator-owned.",
    "note-taking": "Knowledge-capture guides for note systems that stay outside canonical memory owners.",
    "productivity": "Work execution guides for documents, planning, and operator productivity surfaces.",
    "red-teaming": "Adversarial evaluation and refusal-analysis guides kept explicit and separate from core runtime behavior.",
    "research": "Research and information-gathering workflows packaged as built-in guidance.",
    "runtime": "Core shell, search, and scheduling guides that shape the default Elephant Agent runtime posture.",
    "security": "Security, secrets, and investigative workflows that require explicit operator boundaries and verification.",
    "smart-home": "Smart-home operator workflows kept separate from executable tool truth.",
    "social-media": "Social publishing and browsing workflows exposed as curated built-ins.",
    "software-development": "Engineering execution guides for planning, debugging, testing, and code review.",
    "voice": "Voice and reply-style procedures that remain subordinate to the text-first runtime.",
}

_BUILTIN_SECTION_ORDER: Mapping[str, int] = {
    "runtime": 0,
    "continuity": 1,
    "software-development": 2,
    "github": 3,
    "autonomous-ai-agents": 4,
    "creative": 5,
    "productivity": 6,
    "communication": 7,
    "research": 8,
    "data-science": 9,
    "mlops": 10,
    "devops": 11,
    "security": 12,
    "migration": 13,
    "apple": 14,
    "note-taking": 15,
    "mcp": 16,
    "email": 17,
    "media": 18,
    "gaming": 19,
    "red-teaming": 20,
    "voice": 21,
    "social-media": 22,
    "smart-home": 23,
    "leisure": 24,
}


@dataclass(frozen=True, slots=True)
class BuiltinSkillCatalogSection:
    section_id: str
    display_name: str
    summary: str
    entries: tuple[SkillCatalogEntry, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BuiltinSkillCatalog:
    source: SkillHubSource
    entries: tuple[SkillCatalogEntry, ...]
    sections: tuple[BuiltinSkillCatalogSection, ...]

    def definitions(self) -> tuple[SkillDefinition, ...]:
        return tuple(entry.to_skill_definition() for entry in self.entries)

    def hub_entries(self) -> tuple[SkillHubEntry, ...]:
        return tuple(
            entry.to_hub_entry() for entry in self.entries if entry.visibility.include_in_hub and entry.default_enabled
        )

    def prompt_entries(self) -> tuple[SkillCatalogEntry, ...]:
        return tuple(
            entry for entry in self.entries if entry.visibility.include_in_prompt_index and entry.default_enabled
        )

    def site_entries(self) -> tuple[SkillCatalogEntry, ...]:
        return tuple(entry for entry in self.entries if entry.visibility.include_in_site)


def builtin_skill_catalog(
    enabled_overrides: Mapping[str, bool] | None = None,
    *,
    root: Path | None = None,
) -> BuiltinSkillCatalog:
    source_root = (root or builtin_elephant_skill_source_root()).expanduser().resolve()
    source = SkillHubSource("builtin", "Built In", source_root)
    entries = _builtin_skill_catalog_entries(enabled_overrides, root=source_root)
    section_buckets: dict[str, list[SkillCatalogEntry]] = {}
    for entry in entries:
        section_id = _builtin_section_id(entry)
        section_buckets.setdefault(section_id, []).append(entry)
    sections = tuple(
        BuiltinSkillCatalogSection(
            section_id=section_id,
            display_name=_builtin_section_display_name(section_id),
            summary=_builtin_section_summary(section_id),
            entries=tuple(section_buckets[section_id]),
            metadata={
                "entry_count": len(section_buckets[section_id]),
                "include_in_prompt_index": any(
                    item.visibility.include_in_prompt_index for item in section_buckets[section_id]
                ),
                "include_in_site": any(item.visibility.include_in_site for item in section_buckets[section_id]),
            },
        )
        for section_id in sorted(section_buckets, key=_builtin_section_sort_key)
    )
    return BuiltinSkillCatalog(
        source=source,
        entries=entries,
        sections=sections,
    )


def builtin_skill_definitions(
    enabled_overrides: Mapping[str, bool] | None = None,
) -> tuple[SkillDefinition, ...]:
    return builtin_skill_catalog(enabled_overrides).definitions()


def builtin_skill_hub_entries(
    enabled_overrides: Mapping[str, bool] | None = None,
    *,
    root: Path | None = None,
) -> tuple[SkillHubEntry, ...]:
    return builtin_skill_catalog(enabled_overrides, root=root).hub_entries()


def builtin_prompt_skill_catalog_entries(
    enabled_overrides: Mapping[str, bool] | None = None,
    *,
    root: Path | None = None,
    limit: int | None = None,
) -> tuple[SkillCatalogEntry, ...]:
    entries = builtin_skill_catalog(root=root).prompt_entries()
    if enabled_overrides:
        entries = tuple(entry for entry in entries if enabled_overrides.get(entry.skill_id, True) is not False)
    if limit is None:
        return entries
    return entries[:limit]


def builtin_site_skill_catalog_entries(
    enabled_overrides: Mapping[str, bool] | None = None,
    *,
    root: Path | None = None,
) -> tuple[SkillCatalogEntry, ...]:
    return builtin_skill_catalog(enabled_overrides, root=root).site_entries()


def _builtin_section_id(entry: SkillCatalogEntry) -> str:
    return str(entry.metadata.get("category") or "general").strip() or "general"


def _builtin_section_display_name(section_id: str) -> str:
    label = _BUILTIN_SECTION_DISPLAY_NAMES.get(section_id)
    if label:
        return label
    return section_id.replace("-", " ").replace("/", " / ").title()


def _builtin_section_summary(section_id: str) -> str:
    summary = _BUILTIN_SECTION_SUMMARIES.get(section_id)
    if summary:
        return summary
    display_name = _builtin_section_display_name(section_id)
    return f"{display_name} skills curated as Elephant Agent-native built-in procedural guides."


def _builtin_section_sort_key(section_id: str) -> tuple[int, str, str]:
    return (
        _BUILTIN_SECTION_ORDER.get(section_id, len(_BUILTIN_SECTION_ORDER)),
        _builtin_section_display_name(section_id).lower(),
        section_id,
    )
