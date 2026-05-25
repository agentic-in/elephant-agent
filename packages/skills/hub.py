"""Searchable skill-package discovery and canonical catalog projections."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
import re
from typing import Any

from packages.runtime_config import default_external_skill_dirs
from packages.runtime_layout import (
    default_authored_skills_dir,
    default_builtin_skills_dir,
    default_installed_skills_dir,
)

from .runtime import SkillDefinition, SkillDependency, SkillScope, load_skill_package_definition

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SkillCatalogVisibility:
    include_in_hub: bool = True
    include_in_prompt_index: bool = True
    include_in_site: bool = True
    include_in_overlay: bool = False


@dataclass(frozen=True, slots=True)
class SkillHubEntry:
    skill_id: str
    display_name: str
    summary: str
    source_id: str
    source_label: str
    skill_path: str
    entry_path: str
    provenance: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def reference(self) -> str:
        return f"{self.source_id}:{self.skill_id}"


@dataclass(frozen=True, slots=True)
class SkillHubSource:
    source_id: str
    label: str
    root: Path


@dataclass(frozen=True, slots=True)
class SkillCatalogEntry:
    skill_id: str
    display_name: str
    summary: str
    version: str
    source_id: str
    source_label: str
    source_kind: str
    storage_tier: str
    default_enabled: bool
    skill_path: str
    entry_path: str
    provenance: str
    instruction_text: str = ""
    scope: SkillScope = field(default_factory=SkillScope)
    dependencies: tuple[SkillDependency, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    visibility: SkillCatalogVisibility = field(default_factory=SkillCatalogVisibility)

    @property
    def reference(self) -> str:
        return f"{self.source_id}:{self.skill_id}"

    def to_skill_definition(self, *, enabled_override: bool | None = None) -> SkillDefinition:
        enabled = self.default_enabled if enabled_override is None else bool(enabled_override)
        metadata = dict(self.metadata)
        metadata.setdefault("source_kind", self.source_kind)
        metadata.setdefault("source_id", self.source_id)
        metadata.setdefault("source_label", self.source_label)
        metadata.setdefault("hub_reference", self.reference)
        metadata.setdefault("storage_tier", self.storage_tier)
        metadata.setdefault("default_enabled", self.default_enabled)
        metadata.setdefault("include_in_hub", self.visibility.include_in_hub)
        metadata.setdefault("include_in_prompt_index", self.visibility.include_in_prompt_index)
        metadata.setdefault("include_in_site", self.visibility.include_in_site)
        metadata.setdefault("include_in_overlay", self.visibility.include_in_overlay)
        return SkillDefinition(
            skill_id=self.skill_id,
            display_name=self.display_name,
            version=self.version,
            summary=self.summary,
            scope=self.scope,
            dependencies=self.dependencies,
            provenance=self.provenance,
            enabled=enabled,
            instruction_text=self.instruction_text,
            entry_path=self.entry_path,
            metadata=metadata,
        )

    def to_hub_entry(self) -> SkillHubEntry:
        metadata = dict(self.metadata)
        metadata.setdefault("source_kind", self.source_kind)
        metadata.setdefault("storage_tier", self.storage_tier)
        metadata.setdefault("default_enabled", self.default_enabled)
        metadata.setdefault("include_in_hub", self.visibility.include_in_hub)
        metadata.setdefault("include_in_prompt_index", self.visibility.include_in_prompt_index)
        metadata.setdefault("include_in_site", self.visibility.include_in_site)
        metadata.setdefault("include_in_overlay", self.visibility.include_in_overlay)
        return SkillHubEntry(
            skill_id=self.skill_id,
            display_name=self.display_name,
            summary=self.summary,
            source_id=self.source_id,
            source_label=self.source_label,
            skill_path=self.skill_path,
            entry_path=self.entry_path,
            provenance=self.provenance,
            metadata=metadata,
        )


class SkillHub:
    """Search local skill shelves and resolve installable skill packages."""

    def __init__(self, sources: tuple[SkillHubSource, ...] | None = None) -> None:
        self._sources = sources or default_skill_hub_sources()

    @property
    def sources(self) -> tuple[SkillHubSource, ...]:
        return self._sources

    def list(self, enabled_overrides: Mapping[str, bool] | None = None) -> tuple[SkillHubEntry, ...]:
        entries: list[SkillHubEntry] = []
        overrides = dict(enabled_overrides or {})
        for source in self._sources:
            if not source.root.exists():
                continue
            if source.source_id == "builtin":
                from .builtins import builtin_skill_hub_entries

                entries.extend(builtin_skill_hub_entries(overrides, root=source.root))
                continue
            for skill_md in _iter_skill_entry_paths(source.root):
                try:
                    catalog_entry = load_skill_catalog_entry(skill_md, source=source)
                except Exception:
                    LOGGER.warning(
                        "failed to load skill hub catalog entry",
                        extra={"path": str(skill_md), "source_id": source.source_id},
                        exc_info=True,
                    )
                    continue
                if catalog_entry.skill_id in overrides:
                    catalog_entry = _replace_default_enabled(catalog_entry, overrides[catalog_entry.skill_id])
                if not catalog_entry.visibility.include_in_hub:
                    continue
                entries.append(catalog_entry.to_hub_entry())
        entries.sort(key=lambda item: _hub_sort_key(item))
        return tuple(entries)

    def search(
        self,
        query: str,
        *,
        limit: int = 12,
        enabled_overrides: Mapping[str, bool] | None = None,
    ) -> tuple[SkillHubEntry, ...]:
        tokens = tuple(token for token in _normalize_query(query).split() if token)
        if not tokens:
            return self.list(enabled_overrides)[:limit]
        scored: list[tuple[int, str, SkillHubEntry]] = []
        for entry in self.list(enabled_overrides):
            metadata_terms = " ".join(_metadata_search_terms(entry.metadata))
            haystack = " ".join(
                (
                    entry.skill_id,
                    entry.reference,
                    entry.display_name,
                    entry.summary,
                    metadata_terms,
                )
            ).lower()
            if not all(token in haystack for token in tokens):
                continue
            score = 0
            normalized_tokens = " ".join(tokens)
            if _normalize_query(entry.skill_id) == normalized_tokens:
                score += 6
            if _normalize_query(entry.display_name) == normalized_tokens:
                score += 5
            if all(token in _normalize_query(entry.display_name) for token in tokens):
                score += 3
            if all(token in _normalize_query(entry.summary) for token in tokens):
                score += 1
            if all(token in _normalize_query(metadata_terms) for token in tokens):
                score += 1
            scored.append((score, entry.reference, entry))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return tuple(item[2] for item in scored[:limit])

    def resolve(
        self,
        reference: str,
        enabled_overrides: Mapping[str, bool] | None = None,
    ) -> SkillHubEntry | None:
        candidate = reference.strip()
        if not candidate:
            return None
        path_candidate = Path(candidate).expanduser()
        if path_candidate.exists():
            catalog_entry = load_skill_catalog_entry(
                path_candidate,
                source=SkillHubSource(
                    source_id="path",
                    label="Path",
                    root=path_candidate.resolve().parent if path_candidate.is_file() else path_candidate.resolve(),
                ),
            )
            return catalog_entry.to_hub_entry()
        lowered = candidate.lower()
        for entry in self.list(enabled_overrides):
            if lowered in {
                entry.reference.lower(),
                entry.skill_id.lower(),
                entry.display_name.lower(),
            }:
                return entry
        return None


def default_skill_hub_sources(
    *,
    external_dirs: Sequence[str | Path] | None = None,
    install_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[SkillHubSource, ...]:
    env = environ or os.environ
    configured = str(env.get("ELEPHANT_SKILL_PATHS") or "").strip()
    if configured:
        return _prepend_builtin_source(
            _append_elephant_skill_sources(
                _custom_skill_sources_from_paths(
                    tuple(Path(raw_path).expanduser() for raw_path in configured.split(os.pathsep) if raw_path.strip())
                ),
                install_root=install_root,
            )
        )

    configured_external_dirs = external_dirs
    if configured_external_dirs is None:
        configured_external_dirs = default_external_skill_dirs()
    return _prepend_builtin_source(
        _append_elephant_skill_sources(
            _external_skill_sources_from_paths(configured_external_dirs),
            install_root=install_root,
        )
    )


def elephant_operator_skill_sources(*, install_root: Path | None = None) -> tuple[SkillHubSource, ...]:
    sources = [
        SkillHubSource("builtin", "Built In", builtin_elephant_skill_source_root()),
        SkillHubSource("elephant-installed", "Elephant Agent Installed", default_installed_elephant_skill_source_root() if install_root is None else default_installed_skills_dir(install_root=install_root)),
        SkillHubSource("elephant-authored", "Elephant Agent Authored", default_authored_elephant_skill_source_root() if install_root is None else default_authored_skills_dir(install_root=install_root)),
    ]
    return tuple(source for source in sources if source.root.exists())


def operator_skill_catalog_entries(
    *,
    install_root: Path | None = None,
) -> tuple[SkillCatalogEntry, ...]:
    entries: list[SkillCatalogEntry] = []
    for source in elephant_operator_skill_sources(install_root=install_root):
        if source.source_id == "builtin":
            entries.extend(builtin_skill_catalog_entries(root=source.root))
            continue
        for skill_md in source.root.rglob("SKILL.md"):
            if ".git" in skill_md.parts or "__pycache__" in skill_md.parts:
                continue
            entries.append(load_skill_catalog_entry(skill_md, source=source))
    entries.sort(key=_catalog_sort_key)
    return tuple(entries)


def operator_prompt_skill_catalog_entries(
    enabled_overrides: Mapping[str, bool] | None = None,
    *,
    install_root: Path | None = None,
    limit: int | None = None,
) -> tuple[SkillCatalogEntry, ...]:
    overrides = dict(enabled_overrides or {})
    entries: list[SkillCatalogEntry] = []
    for entry in operator_skill_catalog_entries(install_root=install_root):
        resolved = _replace_default_enabled(entry, overrides[entry.skill_id]) if entry.skill_id in overrides else entry
        if not resolved.visibility.include_in_prompt_index or not resolved.default_enabled:
            continue
        entries.append(resolved)
    if limit is None:
        return tuple(entries)
    return tuple(entries[:limit])


def default_elephant_skill_source_root() -> Path:
    return default_installed_elephant_skill_source_root()


def default_installed_elephant_skill_source_root() -> Path:
    return default_installed_skills_dir()


def default_authored_elephant_skill_source_root() -> Path:
    return default_authored_skills_dir()


def builtin_elephant_skill_source_root() -> Path:
    materialized = default_builtin_skills_dir()
    if materialized.exists():
        return materialized
    return repo_builtin_elephant_skill_source_root()


def repo_builtin_elephant_skill_source_root() -> Path:
    return Path(__file__).resolve().parent / "builtin_packages"


def builtin_skill_catalog_entries(
    enabled_overrides: Mapping[str, bool] | None = None,
    *,
    root: Path | None = None,
) -> tuple[SkillCatalogEntry, ...]:
    source_root = (root or builtin_elephant_skill_source_root()).expanduser().resolve()
    if not source_root.exists():
        return ()
    source = SkillHubSource("builtin", "Built In", source_root)
    entries: list[SkillCatalogEntry] = []
    overrides = dict(enabled_overrides or {})
    for skill_md in source_root.rglob("SKILL.md"):
        if ".git" in skill_md.parts or "__pycache__" in skill_md.parts:
            continue
        catalog_entry = load_skill_catalog_entry(skill_md, source=source)
        if catalog_entry.skill_id in overrides:
            catalog_entry = _replace_default_enabled(catalog_entry, overrides[catalog_entry.skill_id])
        entries.append(catalog_entry)
    entries.sort(key=_catalog_sort_key)
    return tuple(entries)


def load_skill_catalog_entry(path: Path, *, source: SkillHubSource) -> SkillCatalogEntry:
    definition = load_skill_package_definition(path)
    return catalog_entry_from_definition(definition, source=source)


def source_for_skill_path(path: Path) -> SkillHubSource:
    resolved = path.expanduser().resolve()
    package_root = resolved.parent if resolved.is_file() else resolved
    builtin_root = builtin_elephant_skill_source_root().expanduser().resolve()
    installed_root = default_installed_elephant_skill_source_root().expanduser().resolve()
    authored_root = default_authored_elephant_skill_source_root().expanduser().resolve()
    for source in (
        SkillHubSource("builtin", "Built In", builtin_root),
        SkillHubSource("elephant-installed", "Elephant Agent Installed", installed_root),
        SkillHubSource("elephant-authored", "Elephant Agent Authored", authored_root),
    ):
        try:
            package_root.relative_to(source.root)
        except ValueError:
            continue
        return source
    return SkillHubSource(
        "path",
        "Path",
        package_root if package_root.is_dir() else package_root.parent,
    )


def catalog_entry_from_definition(definition: SkillDefinition, *, source: SkillHubSource) -> SkillCatalogEntry:
    entry_path = Path(definition.entry_path or definition.provenance or "").expanduser().resolve()
    skill_path = entry_path.parent if entry_path.name == "SKILL.md" else entry_path
    metadata = dict(definition.metadata)
    source_kind = str(metadata.get("source_kind") or "skill-package").strip() or "skill-package"
    metadata.setdefault("source_kind", source_kind)
    try:
        relative_parts = skill_path.relative_to(source.root.expanduser().resolve()).parts
    except ValueError:
        relative_parts = ()
    category = "/".join(relative_parts[:-1]).strip("/") if len(relative_parts) > 1 else ""
    if category:
        metadata.setdefault("category", category)
    metadata.setdefault("slash_command", _skill_command_slug(definition.skill_id or definition.display_name))
    storage_tier = _storage_tier_for_source(source.source_id)
    metadata.setdefault("storage_tier", storage_tier)
    is_builtin = source.source_id == "builtin" or source_kind == "elephant-builtin"
    default_enabled = _metadata_bool(
        metadata.get("default_enabled"),
        default=True if is_builtin else definition.enabled,
    )
    metadata.setdefault("default_enabled", default_enabled)
    prompt_index_default = is_builtin or source.source_id in {"elephant-installed", "elephant-authored"}
    visibility = SkillCatalogVisibility(
        include_in_hub=_metadata_bool(metadata.get("include_in_hub"), default=True),
        include_in_prompt_index=_metadata_bool(metadata.get("include_in_prompt_index"), default=prompt_index_default),
        include_in_site=_metadata_bool(metadata.get("include_in_site"), default=is_builtin),
        include_in_overlay=_metadata_bool(metadata.get("include_in_overlay"), default=not is_builtin),
    )
    return SkillCatalogEntry(
        skill_id=definition.skill_id,
        display_name=definition.display_name,
        summary=definition.summary,
        version=definition.version,
        source_id=source.source_id,
        source_label=source.label,
        source_kind=source_kind,
        storage_tier=storage_tier,
        default_enabled=default_enabled,
        skill_path=str(skill_path),
        entry_path=str(entry_path),
        provenance=definition.provenance,
        instruction_text=definition.instruction_text,
        scope=definition.scope,
        dependencies=definition.dependencies,
        metadata=metadata,
        visibility=visibility,
    )


def _custom_skill_sources_from_paths(paths: Sequence[Path]) -> tuple[SkillHubSource, ...]:
    sources: list[SkillHubSource] = []
    seen_roots: set[Path] = set()
    for index, path in enumerate(paths, start=1):
        resolved = path.expanduser().resolve()
        if resolved in seen_roots:
            continue
        seen_roots.add(resolved)
        sources.append(
            SkillHubSource(
                source_id=f"custom-{index}",
                label=resolved.name or f"custom-{index}",
                root=resolved,
            )
        )
    return tuple(sources)


def _iter_skill_entry_paths(root: Path) -> tuple[Path, ...]:
    stack = [root]
    seen_dirs: set[Path] = set()
    seen_entries: set[Path] = set()
    entries: list[Path] = []
    while stack:
        current = stack.pop()
        try:
            resolved_current = current.expanduser().resolve()
        except OSError:
            continue
        if resolved_current in seen_dirs:
            continue
        seen_dirs.add(resolved_current)
        try:
            children = tuple(current.iterdir())
        except OSError:
            continue
        for child in children:
            if child.name in {".git", "__pycache__"}:
                continue
            if child.name == "SKILL.md" and child.is_file():
                try:
                    resolved_entry = child.expanduser().resolve()
                except OSError:
                    continue
                if resolved_entry in seen_entries:
                    continue
                seen_entries.add(resolved_entry)
                entries.append(child)
                continue
            if child.is_dir():
                stack.append(child)
    return tuple(entries)


def _external_skill_sources_from_paths(paths: Sequence[str | Path]) -> tuple[SkillHubSource, ...]:
    sources: list[SkillHubSource] = []
    seen_roots: set[Path] = set()
    seen_ids: set[str] = set()
    for index, raw_path in enumerate(paths, start=1):
        raw = str(raw_path).strip()
        if not raw:
            continue
        resolved, identity_path = _external_skill_source_root(Path(raw).expanduser())
        if resolved in seen_roots:
            continue
        seen_roots.add(resolved)
        source_id, label = _external_source_identity(identity_path, index=index, seen_ids=seen_ids)
        sources.append(SkillHubSource(source_id=source_id, label=label, root=resolved))
    return tuple(sources)


def _external_skill_source_root(path: Path) -> tuple[Path, Path]:
    skills_child = path / "skills"
    if path.name != "skills" and skills_child.exists() and skills_child.is_dir():
        return (skills_child.resolve(), skills_child)
    return (path.resolve(), path)


def _external_source_identity(path: Path, *, index: int, seen_ids: set[str]) -> tuple[str, str]:
    if path.name == "skills":
        candidate_name = path.parent.name.lstrip(".") or path.name
    else:
        candidate_name = path.name.lstrip(".") or f"external-{index}"
    source_id = _skill_command_slug(candidate_name) or f"external-{index}"
    if source_id in seen_ids:
        source_id = f"{source_id}-{index}"
    seen_ids.add(source_id)
    label = candidate_name.replace("-", " ").replace("_", " ").strip().title() or f"External {index}"
    return (source_id, label)


def _append_elephant_skill_sources(
    sources: tuple[SkillHubSource, ...],
    *,
    install_root: Path | None = None,
) -> tuple[SkillHubSource, ...]:
    resolved = list(sources)
    existing_roots = {source.root.expanduser().resolve() for source in sources}
    elephant_sources = (
        SkillHubSource(
            "elephant-installed",
            "Elephant Agent Installed",
            default_installed_elephant_skill_source_root() if install_root is None else default_installed_skills_dir(install_root=install_root),
        ),
        SkillHubSource(
            "elephant-authored",
            "Elephant Agent Authored",
            default_authored_elephant_skill_source_root() if install_root is None else default_authored_skills_dir(install_root=install_root),
        ),
    )
    for source in elephant_sources:
        root = source.root.expanduser().resolve()
        if root in existing_roots:
            continue
        resolved.append(source)
        existing_roots.add(root)
    return tuple(resolved)


def _prepend_builtin_source(sources: tuple[SkillHubSource, ...]) -> tuple[SkillHubSource, ...]:
    builtin_root = builtin_elephant_skill_source_root()
    resolved = list(sources)
    if not builtin_root.exists():
        return tuple(resolved)
    builtin_resolved = builtin_root.expanduser().resolve()
    existing_roots = {source.root.expanduser().resolve() for source in resolved}
    if builtin_resolved not in existing_roots:
        resolved.insert(0, SkillHubSource("builtin", "Built In", builtin_root))
    return tuple(resolved)


def _catalog_sort_key(entry: SkillCatalogEntry) -> tuple[int, int, str, str]:
    default_rank = 0 if entry.default_enabled else 1
    return (
        _hub_source_rank(entry.source_id),
        default_rank,
        entry.display_name.lower(),
        entry.skill_id,
    )


def _hub_sort_key(entry: SkillHubEntry) -> tuple[int, int, str, str]:
    default_enabled = bool(entry.metadata.get("default_enabled"))
    return (
        _hub_source_rank(entry.source_id),
        0 if default_enabled else 1,
        entry.display_name.lower(),
        entry.skill_id,
    )


def _replace_default_enabled(entry: SkillCatalogEntry, enabled: bool) -> SkillCatalogEntry:
    next_enabled = bool(enabled)
    metadata = dict(entry.metadata)
    metadata["default_enabled"] = next_enabled
    return SkillCatalogEntry(
        skill_id=entry.skill_id,
        display_name=entry.display_name,
        summary=entry.summary,
        version=entry.version,
        source_id=entry.source_id,
        source_label=entry.source_label,
        source_kind=entry.source_kind,
        storage_tier=entry.storage_tier,
        default_enabled=next_enabled,
        skill_path=entry.skill_path,
        entry_path=entry.entry_path,
        provenance=entry.provenance,
        instruction_text=entry.instruction_text,
        scope=entry.scope,
        dependencies=entry.dependencies,
        metadata=metadata,
        visibility=entry.visibility,
    )


def _metadata_search_terms(metadata: Mapping[str, Any]) -> tuple[str, ...]:
    terms: list[str] = []
    for key in ("category", "source_kind", "storage_tier"):
        value = str(metadata.get(key) or "").strip()
        if value:
            terms.append(value)
    for key in ("aliases", "trigger_phrases", "keywords", "platforms"):
        raw = metadata.get(key)
        if isinstance(raw, (tuple, list, set)):
            terms.extend(str(item).strip() for item in raw if str(item).strip())
    return tuple(terms)


def _normalize_query(value: str) -> str:
    return " ".join(value.lower().replace("-", " ").replace("_", " ").split())


def _skill_command_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", value.lower().replace("_", "-").replace(" ", "-"))
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug


def _storage_tier_for_source(source_id: str) -> str:
    if source_id == "builtin":
        return "builtin"
    if source_id == "elephant-installed":
        return "installed"
    if source_id == "elephant-authored":
        return "authored"
    return "external"


def _hub_source_rank(source_id: str) -> int:
    order = {
        "builtin": 0,
        "elephant-installed": 1,
        "elephant-authored": 2,
        "path": 3,
    }
    return order.get(source_id, 8)


def _metadata_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"true", "yes", "1", "on"}:
        return True
    if text in {"false", "no", "0", "off"}:
        return False
    return default
