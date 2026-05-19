"""Skill loading, scope, dependency metadata, and skill-package discovery.

Skills are reusable procedural packages. They are not executable side effects
themselves; they are metadata-backed bundles that can be loaded, activated, and
resolved by scope.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Protocol, runtime_checkable
from uuid import uuid4

from packages.capabilities.runtime import CapabilityDescriptor, SkillCapability
from packages.contracts import State

from .provenance import (
    PERSISTED_INSTALL_PROVENANCE_FIELDS,
    PERSISTED_SOURCE_DESCRIPTOR_FIELDS,
)


@dataclass(frozen=True, slots=True)
class SkillScope:
    """Activation scope for a skill."""

    personal_model_ids: tuple[str, ...] = ()
    state_ids: tuple[str, ...] = ()
    surface_ids: tuple[str, ...] = ()
    surface_kinds: tuple[str, ...] = ()
    modes: tuple[str, ...] = ()

    def matches(
        self,
        *,
        personal_model_id: str,
        state_id: str,
        surface_id: str,
        surface_kind: str,
        mode: str,
    ) -> bool:
        if self.personal_model_ids and personal_model_id not in self.personal_model_ids:
            return False
        if self.state_ids and state_id not in self.state_ids:
            return False
        if self.surface_ids and surface_id not in self.surface_ids:
            return False
        if self.surface_kinds and surface_kind not in self.surface_kinds:
            return False
        if self.modes and mode not in self.modes:
            return False
        return True


@dataclass(frozen=True, slots=True)
class SkillDependency:
    skill_id: str
    minimum_version: str | None = None
    required: bool = True


@dataclass(frozen=True, slots=True)
class SkillDefinition:
    skill_id: str
    display_name: str
    version: str
    summary: str
    scope: SkillScope = field(default_factory=SkillScope)
    dependencies: tuple[SkillDependency, ...] = ()
    provenance: str = ""
    enabled: bool = True
    instruction_text: str = ""
    entry_path: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def include_in_overlay(self) -> bool:
        return _metadata_flag(self.metadata.get("include_in_overlay"), default=False)


@dataclass(frozen=True, slots=True)
class SkillActivationRecord:
    activation_id: str
    skill_id: str
    session_id: str
    personal_model_id: str
    state_id: str
    surface_id: str
    surface_kind: str
    mode: str
    activated_at: datetime
    episode_id: str | None = None
    status: str = "active"
    detail: str | None = None
    provenance: str = ""
    dependency_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SkillManifest:
    source_path: str
    skills: tuple[SkillDefinition, ...]


@dataclass(frozen=True, slots=True)
class SkillManifestLoadRecord:
    source_path: str
    skill_ids: tuple[str, ...]
    loaded_at: datetime
    status: str = "loaded"
    detail: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SkillActivationContext:
    personal_model_id: str
    state_id: str
    surface_id: str
    surface_kind: str
    mode: str
    episode_id: str | None = None


@runtime_checkable
class SkillLoader(Protocol):
    def load(self, path: Path) -> SkillManifest:
        """Load a skill manifest from disk."""


SkillStateResolver = Callable[[str], State | None]


@runtime_checkable
class SkillCatalog(Protocol):
    def register(self, definition: SkillDefinition) -> None:
        """Register a skill definition."""

    def get(self, skill_id: str) -> SkillDefinition | None:
        """Return a skill definition if it exists."""

    def list(self) -> tuple[SkillDefinition, ...]:
        """Return all registered skills."""

    def resolve_for_context(
        self,
        *,
        personal_model_id: str,
        state_id: str,
        surface_id: str,
        surface_kind: str,
        mode: str,
    ) -> tuple[SkillDefinition, ...]:
        """Return enabled skills matching the supplied scope."""


class JsonSkillLoader:
    """Load skill manifests from a JSON-shaped file."""

    def load(self, path: Path) -> SkillManifest:
        payload = json.loads(path.read_text(encoding="utf-8"))
        skills = tuple(_skill_from_dict(item, source_path=path) for item in payload.get("skills", []))
        return SkillManifest(source_path=str(path), skills=skills)


class SkillPackageLoader:
    """Load a skill package from a directory or ``SKILL.md`` entry file."""

    def load(self, path: Path) -> SkillManifest:
        definition = load_skill_package_definition(path)
        source_path = str(_resolve_skill_entry_path(path))
        return SkillManifest(source_path=source_path, skills=(definition,))


class InMemorySkillCatalog:
    """Simple in-memory catalog used for runtime wiring and tests."""

    def __init__(self) -> None:
        self._skills: dict[str, SkillDefinition] = {}

    def register(self, definition: SkillDefinition) -> None:
        existing = self._skills.get(definition.skill_id)
        if existing is not None and existing != definition:
            raise ValueError(f"skill is already registered with different metadata: {definition.skill_id}")
        self._skills[definition.skill_id] = definition

    def get(self, skill_id: str) -> SkillDefinition | None:
        return self._skills.get(skill_id)

    def list(self) -> tuple[SkillDefinition, ...]:
        return tuple(self._skills.values())

    def add_manifest(self, manifest: SkillManifest) -> None:
        for skill in manifest.skills:
            existing = self._skills.get(skill.skill_id)
            candidate = skill if existing is None else replace(skill, enabled=existing.enabled)
            self._skills[candidate.skill_id] = candidate

    def resolve_for_context(
        self,
        *,
        personal_model_id: str,
        state_id: str,
        surface_id: str,
        surface_kind: str,
        mode: str,
    ) -> tuple[SkillDefinition, ...]:
        resolved = [
            skill
            for skill in self.list()
            if skill.enabled
            and skill.scope.matches(
                personal_model_id=personal_model_id,
                state_id=state_id,
                surface_id=surface_id,
                surface_kind=surface_kind,
                mode=mode,
            )
        ]
        return tuple(resolved)

    def validate_dependencies(self, skill_id: str) -> tuple[str, ...]:
        skill = self._skills[skill_id]
        missing: list[str] = []
        for dependency in skill.dependencies:
            if dependency.required and dependency.skill_id not in self._skills:
                missing.append(dependency.skill_id)
        return tuple(missing)

    def set_enabled(self, skill_id: str, enabled: bool) -> SkillDefinition:
        definition = self._skills.get(skill_id)
        if definition is None:
            raise KeyError(f"skill is not registered: {skill_id}")
        updated = replace(definition, enabled=enabled)
        self._skills[skill_id] = updated
        return updated


class SkillRuntime(SkillCapability):
    """Capability adapter for skill activation."""

    def __init__(
        self,
        catalog: SkillCatalog | None = None,
        context_resolver: Callable[[str], SkillActivationContext] | None = None,
        state_resolver: SkillStateResolver | None = None,
        scan_on_init_dirs: tuple[Path, ...] | None = None,
    ) -> None:
        self.descriptor = CapabilityDescriptor(
            capability_id="skill.runtime",
            kind="skill_runtime",
            version="1.0.0",
            metadata={
                "description": "In-process skill activation adapter.",
            },
        )
        self._catalog = catalog or InMemorySkillCatalog()
        self._context_resolver = context_resolver
        self._state_resolver = state_resolver
        self._activations: list[SkillActivationRecord] = []
        self._manifest_loads: list[SkillManifestLoadRecord] = []
        self._scan_dirs: tuple[Path, ...] = tuple(scan_on_init_dirs or ())
        if self._scan_dirs:
            self.reload_from_disk()

    @property
    def catalog(self) -> SkillCatalog:
        return self._catalog

    def register_skill(self, definition: SkillDefinition) -> None:
        self._catalog.register(definition)

    def describe(self, skill_id: str) -> SkillDefinition | None:
        return self._catalog.get(skill_id)

    def list_skills(self) -> tuple[SkillDefinition, ...]:
        return self._catalog.list()

    def load_manifest(self, path: Path, loader: SkillLoader | None = None) -> SkillManifest:
        manifest = (loader or JsonSkillLoader()).load(path)
        if hasattr(self._catalog, "add_manifest"):
            self._catalog.add_manifest(manifest)  # type: ignore[attr-defined]
        else:
            for skill in manifest.skills:
                self._catalog.register(skill)
        self._manifest_loads.append(
            SkillManifestLoadRecord(
                source_path=manifest.source_path,
                skill_ids=tuple(skill.skill_id for skill in manifest.skills),
                loaded_at=datetime.now(timezone.utc),
            )
        )
        return manifest

    def load_package(self, path: Path) -> SkillManifest:
        from .hub import load_skill_catalog_entry, source_for_skill_path

        catalog_entry = load_skill_catalog_entry(path, source=source_for_skill_path(path))
        manifest = SkillManifest(
            source_path=catalog_entry.entry_path,
            skills=(catalog_entry.to_skill_definition(),),
        )
        if hasattr(self._catalog, "add_manifest"):
            self._catalog.add_manifest(manifest)  # type: ignore[attr-defined]
        else:
            for skill in manifest.skills:
                self._catalog.register(skill)
        self._manifest_loads.append(
            SkillManifestLoadRecord(
                source_path=manifest.source_path,
                skill_ids=tuple(skill.skill_id for skill in manifest.skills),
                loaded_at=datetime.now(timezone.utc),
            )
        )
        return manifest

    def list_manifest_loads(self) -> tuple[SkillManifestLoadRecord, ...]:
        return tuple(self._manifest_loads)

    def reload_from_disk(self) -> int:
        """Re-scan every ``scan_on_init_dirs`` entry for skill packages.

        A skill package is any directory containing ``SKILL.md``. Nested
        directories are walked up to two levels deep to cover the common
        ``<root>/<category>/<skill_id>/SKILL.md`` layout used by the authored
        skill directory. Returns the number of packages (re)registered.
        """
        loaded = 0
        for root in self._scan_dirs:
            try:
                root_path = Path(root).expanduser()
            except Exception:
                continue
            if not root_path.is_dir():
                continue
            for skill_md in root_path.rglob("SKILL.md"):
                try:
                    self.load_package(skill_md.parent)
                    loaded += 1
                except Exception:
                    # Keep scanning; a broken skill dir should not block others.
                    continue
        return loaded

    def resolve_for_context(
        self,
        *,
        personal_model_id: str,
        state_id: str,
        surface_id: str,
        surface_kind: str,
        mode: str,
    ) -> tuple[SkillDefinition, ...]:
        return _ranked_resolved_skills(
            self._catalog.list(),
            personal_model_id=personal_model_id,
            state_id=state_id,
            surface_id=surface_id,
            surface_kind=surface_kind,
            mode=mode,
            state=_resolved_state(self._state_resolver, state_id),
        )

    def activate(self, skill_name: str, *, session_id: str) -> SkillActivationRecord:
        if self._context_resolver is None:
            raise RuntimeError("skill activation requires a context resolver")
        context = self._context_resolver(session_id)
        definition = self._catalog.get(skill_name)
        if definition is None:
            raise KeyError(f"skill is not registered: {skill_name}")
        if not definition.enabled:
            raise ValueError(f"skill is disabled: {skill_name}")
        state = _resolved_state(self._state_resolver, context.state_id)
        if not _skill_is_runtime_eligible(
            definition,
            personal_model_id=context.personal_model_id,
            state_id=context.state_id,
            surface_id=context.surface_id,
            surface_kind=context.surface_kind,
            mode=context.mode,
            state=state,
        ):
            raise PermissionError(f"skill is out of scope for session: {skill_name}")
        missing = []
        if hasattr(self._catalog, "validate_dependencies"):
            missing = list(self._catalog.validate_dependencies(skill_name))  # type: ignore[attr-defined]
        if missing:
            raise RuntimeError(f"skill dependencies are missing: {', '.join(missing)}")
        record = SkillActivationRecord(
            activation_id=f"{session_id}:{skill_name}:{uuid4().hex[:8]}",
            skill_id=skill_name,
            session_id=session_id,
            personal_model_id=context.personal_model_id,
            state_id=context.state_id,
            surface_id=context.surface_id,
            surface_kind=context.surface_kind,
            mode=context.mode,
            episode_id=context.episode_id,
            activated_at=datetime.now(timezone.utc),
            provenance=definition.provenance,
            dependency_ids=tuple(dependency.skill_id for dependency in definition.dependencies),
        )
        self._activations.append(record)
        return record

    def list_activations(self) -> tuple[SkillActivationRecord, ...]:
        return tuple(self._activations)

    def set_enabled(self, skill_id: str, enabled: bool) -> SkillDefinition:
        if hasattr(self._catalog, "set_enabled"):
            return self._catalog.set_enabled(skill_id, enabled)  # type: ignore[attr-defined]
        definition = self._catalog.get(skill_id)
        if definition is None:
            raise KeyError(f"skill is not registered: {skill_id}")
        updated = replace(definition, enabled=enabled)
        self._catalog.register(updated)
        return updated


def _ranked_resolved_skills(
    definitions: tuple[SkillDefinition, ...],
    *,
    personal_model_id: str,
    state_id: str,
    surface_id: str,
    surface_kind: str,
    mode: str,
    state: State | None,
) -> tuple[SkillDefinition, ...]:
    eligible = [
        definition
        for definition in definitions
        if _skill_is_runtime_eligible(
            definition,
            personal_model_id=personal_model_id,
            state_id=state_id,
            surface_id=surface_id,
            surface_kind=surface_kind,
            mode=mode,
            state=state,
        )
    ]
    return tuple(sorted(eligible, key=_selection_sort_key))


def _skill_is_runtime_eligible(
    definition: SkillDefinition,
    *,
    personal_model_id: str,
    state_id: str,
    surface_id: str,
    surface_kind: str,
    mode: str,
    state: State | None,
) -> bool:
    if not definition.enabled:
        return False
    if not definition.scope.matches(
        personal_model_id=personal_model_id,
        state_id=state_id,
        surface_id=surface_id,
        surface_kind=surface_kind,
        mode=mode,
    ):
        return False
    return _state_allows_skill(state, definition)


def _resolved_state(
    resolver: SkillStateResolver | None,
    state_id: str,
) -> State | None:
    if resolver is None or not state_id.strip():
        return None
    return resolver(state_id)


def _state_allows_skill(state: State | None, definition: SkillDefinition) -> bool:
    if state is None or not state.capability_boundaries:
        return True
    required = _required_capability_set(definition)
    if not required:
        return True
    boundaries = {item.strip().lower() for item in state.capability_boundaries if item.strip()}
    return required.issubset(boundaries)


def _required_capability_set(definition: SkillDefinition) -> set[str]:
    return {
        item.strip().lower()
        for item in _metadata_string_list(definition.metadata.get("required_capabilities"))
        if item.strip()
    }


def _selection_sort_key(definition: SkillDefinition) -> tuple[Any, ...]:
    default_enabled = _metadata_flag(definition.metadata.get("default_enabled"), default=True)
    return (
        0 if default_enabled else 1,
        str(definition.display_name or definition.skill_id).casefold(),
        definition.skill_id,
    )


def _skill_from_dict(payload: Mapping[str, Any], *, source_path: Path | None = None) -> SkillDefinition:
    scope_payload = payload.get("scope", {})
    dependencies = tuple(
        SkillDependency(
            skill_id=item["skill_id"],
            minimum_version=item.get("minimum_version"),
            required=item.get("required", True),
        )
        for item in payload.get("dependencies", [])
    )
    return SkillDefinition(
        skill_id=payload["skill_id"],
        display_name=payload["display_name"],
        version=payload["version"],
        summary=payload.get("summary", ""),
        scope=SkillScope(
            personal_model_ids=tuple(scope_payload.get("personal_model_ids", ())),
            state_ids=tuple(scope_payload.get("state_ids", ())),
            surface_ids=tuple(scope_payload.get("surface_ids", ())),
            surface_kinds=tuple(scope_payload.get("surface_kinds", ())),
            modes=tuple(scope_payload.get("modes", ())),
        ),
        dependencies=dependencies,
        provenance=str(payload.get("provenance") or source_path or ""),
        enabled=payload.get("enabled", True),
        instruction_text=str(payload.get("instruction_text") or ""),
        entry_path=str(payload.get("entry_path") or source_path or ""),
        metadata=payload.get("metadata", {}),
    )


def _skill_identity(definition: SkillDefinition) -> SkillDefinition:
    return replace(definition, enabled=True)


def load_skill_package_definition(path: Path) -> SkillDefinition:
    entry_path = _resolve_skill_entry_path(path)
    text = entry_path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(text)
    title = (
        str(frontmatter.get("name") or frontmatter.get("display_name") or "").strip()
        or _first_heading(body)
        or entry_path.parent.name.replace("-", " ").title()
    )
    summary = (
        str(frontmatter.get("description") or frontmatter.get("summary") or "").strip()
        or _first_summary(body)
        or f"Skill package loaded from {entry_path.parent.name}."
    )
    skill_id = str(frontmatter.get("skill_id") or entry_path.parent.name).strip()
    version = str(frontmatter.get("version") or "1.0.0").strip() or "1.0.0"
    metadata = {
        "kind": "skill-package",
        "entry_path": str(entry_path),
        "slash_command": _skill_command_slug(skill_id or title),
    }
    source_kind = str(frontmatter.get("source_kind") or "").strip()
    if source_kind:
        metadata["source_kind"] = source_kind
    category = str(frontmatter.get("category") or "").strip()
    if category:
        metadata["category"] = category
    for key in (
        "aliases",
        "trigger_phrases",
        "keywords",
        "platforms",
        "required_capabilities",
        "requires_tools",
        "requires_toolsets",
        "required_environment_variables",
    ):
        values = _frontmatter_string_list(frontmatter.get(key))
        if values:
            metadata[key] = values
    for key in (
        "default_enabled",
        "include_in_hub",
        "include_in_prompt_index",
        "include_in_site",
        "include_in_overlay",
    ):
        value = _frontmatter_bool(frontmatter.get(key))
        if value is not None:
            metadata[key] = value
    for key in PERSISTED_SOURCE_DESCRIPTOR_FIELDS + PERSISTED_INSTALL_PROVENANCE_FIELDS:
        value = str(frontmatter.get(key) or "").strip()
        if value:
            metadata[key] = value
    return SkillDefinition(
        skill_id=skill_id,
        display_name=title,
        version=version,
        summary=summary,
        scope=SkillScope(),
        dependencies=(),
        provenance=str(entry_path.parent),
        enabled=True,
        instruction_text=body.strip(),
        entry_path=str(entry_path),
        metadata=metadata,
    )


def _resolve_skill_entry_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved.is_dir():
        resolved = resolved / "SKILL.md"
    if not resolved.exists():
        raise FileNotFoundError(resolved)
    if resolved.name != "SKILL.md":
        raise ValueError(f"skill packages must point at a SKILL.md file or skill directory: {resolved}")
    return resolved


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return ({}, text)
    closing = text.find("\n---\n", 4)
    if closing == -1:
        return ({}, text)
    payload: dict[str, Any] = {}
    block = text[4:closing]
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        payload[key.strip()] = value.strip()
    return payload, text[closing + len("\n---\n") :]


def _frontmatter_string_list(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set)):
        raw_items = tuple(value)
    else:
        text = str(value).strip()
        if not text:
            return ()
        raw_items: tuple[Any, ...]
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                raw_items = tuple(parsed)
            else:
                raw_items = tuple(segment.strip() for segment in text[1:-1].split(","))
        else:
            raw_items = tuple(segment.strip() for segment in text.split(","))
    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        token = str(item).strip().strip("\"'")
        if not token:
            continue
        dedupe_key = token.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized.append(token)
    return tuple(normalized)


def _frontmatter_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if text in {"true", "yes", "1", "on"}:
        return True
    if text in {"false", "no", "0", "off"}:
        return False
    return None


def _metadata_flag(value: Any, *, default: bool) -> bool:
    resolved = _frontmatter_bool(value)
    if resolved is None:
        return default
    return resolved


def _metadata_float(value: Any, *, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _metadata_string_list(value: Any) -> tuple[str, ...]:
    return _frontmatter_string_list(value)


def _first_heading(body: str) -> str:
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or not line.startswith("#"):
            continue
        return line.lstrip("#").strip()
    return ""


def _first_summary(body: str) -> str:
    paragraphs: list[str] = []
    current: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        if line.startswith("#"):
            continue
        current.append(line)
        if len(" ".join(current)) >= 180:
            paragraphs.append(" ".join(current))
            break
    if current and not paragraphs:
        paragraphs.append(" ".join(current))
    return paragraphs[0] if paragraphs else ""


def _skill_command_slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", value.lower().replace("_", "-").replace(" ", "-"))
    return re.sub(r"-{2,}", "-", normalized).strip("-")
