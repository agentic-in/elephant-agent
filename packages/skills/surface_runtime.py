"""Shared skill runtime helpers for chat-capable surfaces."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from packages.contracts.layers import Episode
from packages.runtime_layout import default_authored_skills_dir
from packages.state import ProfileLoader, load_runtime_profile
from packages.state.loader import write_extensions_manifest
from packages.storage import RuntimeStorageRepository

from .authoring import write_skill_package
from .builtins import builtin_skill_definitions
from .hub import SkillHub, SkillHubEntry, operator_prompt_skill_catalog_entries
from .runtime import (
    SkillActivationContext,
    SkillDefinition,
    SkillManifestLoadRecord,
    SkillPackageLoader,
    SkillRuntime,
    load_skill_package_definition,
)
from .search import SkillSearchHub


@dataclass(frozen=True, slots=True)
class SkillExtensionManifest:
    skill_overrides: Mapping[str, bool]
    skill_manifest_paths: tuple[Path, ...]
    skill_package_paths: tuple[Path, ...]


def load_skill_extension_manifest(
    manifest: Mapping[str, Any],
    *,
    profile_dir: Path,
) -> SkillExtensionManifest:
    return SkillExtensionManifest(
        skill_overrides=_load_enabled_overrides(manifest, "skill_overrides"),
        skill_manifest_paths=_load_manifest_paths(manifest, "skill_manifests", profile_dir=profile_dir),
        skill_package_paths=_load_manifest_paths(manifest, "skill_packages", profile_dir=profile_dir),
    )


def build_surface_skill_runtime(
    manifest: SkillExtensionManifest,
    *,
    repository: RuntimeStorageRepository,
    profile_loader: ProfileLoader,
    surface_kind: str,
) -> SkillRuntime:
    runtime = SkillRuntime(
        context_resolver=lambda session_id: resolve_skill_activation_context(
            repository,
            profile_loader,
            session_id,
            surface_kind=surface_kind,
        ),
        state_resolver=repository.load_state,
    )
    for definition in builtin_skill_definitions(manifest.skill_overrides):
        runtime.register_skill(definition)
    for path in manifest.skill_manifest_paths:
        runtime.load_manifest(path)
    for path in manifest.skill_package_paths:
        runtime.load_package(path)
    return runtime


def resolve_skill_activation_context(
    repository: RuntimeStorageRepository,
    profile_loader: ProfileLoader,
    session_id: str,
    *,
    surface_kind: str,
) -> SkillActivationContext:
    session = repository.load_episode_state(session_id)
    if session is None:
        raise KeyError(session_id)
    elephant_id = str(session.elephant_id or "").strip()
    state = _resolve_elephant_state(repository, elephant_id)
    # Identity / mode comes from the canonical State row, not a disk manifest.
    profile = load_runtime_profile(
        repository,
        personal_model_id=session.personal_model_id,
        elephant_id=elephant_id or None,
        profile_loader=profile_loader,
    )
    return SkillActivationContext(
        personal_model_id="" if state is None else state.personal_model_id,
        state_id="" if state is None else state.state_id,
        surface_id=f"{surface_kind}:{session_id}",
        surface_kind=surface_kind,
        mode=profile.state.mode,
        episode_id=session.episode_id,
    )


class SkillPromptContextBuilder:
    """Build the skill disclosure block that lands in the cached system prompt.

    Design invariants (see R8 follow-up discussion):

    1. **Episode-frozen.** Within one episode, the same skill list is served
       on every turn. We compute it once and cache by `episode_id` — so
       repeated `stable_prefix_lines()` calls don't re-query the repository,
       and more importantly the RENDERED block stays byte-identical across
       turns (prefix caching depends on this).
    2. **No per-turn query rerank.** Query-aware rerank would mutate the
       stable prefix on every turn, defeating the cache. If the agent needs
       an on-demand skill, it can call `tool.skill.list`.
    3. **Stable cross-session order.** Skill order comes from active
       `skills.affinity.*` Personal Model facts, then authored catalog order.
       The prompt index is the learned shelf, not the full skill hub.

    The cache is intentionally per-instance (not global) so that a fresh
    `SkillPromptContextBuilder` picks up installed skill changes cleanly.
    """

    def __init__(
        self,
        *,
        repository: RuntimeStorageRepository,
        profile_loader: ProfileLoader,
        skill_runtime: SkillRuntime | None,
        install_root: Path | None,
        surface_kind: str,
    ) -> None:
        self.repository = repository
        self.profile_loader = profile_loader
        self.skill_runtime = skill_runtime
        self.install_root = install_root
        self.surface_kind = surface_kind
        # episode_id → rendered lines tuple.
        self._episode_cache: dict[str, tuple[str, ...]] = {}

    def stable_prefix_lines(
        self,
        session: Episode,
    ) -> tuple[str, ...]:
        """Return the disclosure block — cached per episode_id.

        The stable prefix renders only runtime-eligible skills with active
        `skills.affinity.*` Personal Model facts for this Episode. There is no
        query-time rerank; truncation is an explicit learned-shelf cap.

        The returned lines are byte-identical across turns of the same
        episode. The result only changes when:
          - the caller moves to a different episode (new episode_id),
          - the builder instance is re-created (fresh install / reload).
        """
        episode_id = str(getattr(session, "episode_id", "") or "")
        if episode_id and episode_id in self._episode_cache:
            return self._episode_cache[episode_id]
        skills = prompt_index_skills(
            repository=self.repository,
            profile_loader=self.profile_loader,
            skill_runtime=self.skill_runtime,
            session=session,
            install_root=self.install_root,
            surface_kind=self.surface_kind,
        )
        if not skills:
            result: tuple[str, ...] = ()
        else:
            result = skill_disclosure_lines(skills, install_root=self.install_root)
        if episode_id:
            self._episode_cache[episode_id] = result
        return result

    def invalidate_episode_cache(self, episode_id: str | None = None) -> None:
        """Drop the cached skill block for one episode (or all).

        Call this when an operator enables/disables a skill mid-episode, or
        when a new skill is installed. A new episode builds a fresh cache
        entry on demand.
        """
        if episode_id is None:
            self._episode_cache.clear()
            return
        self._episode_cache.pop(episode_id, None)


def _skill_index_id(skill_id: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in str(skill_id).strip().lower())
    return "_".join(part for part in cleaned.split("_") if part)


def _skill_affinity_index_ids(repository: RuntimeStorageRepository, *, personal_model_id: str) -> frozenset[str]:
    try:
        facts = tuple(repository.list_personal_model_facts(personal_model_id=personal_model_id, status="active"))
    except Exception:
        return frozenset()
    out: set[str] = set()
    for fact in facts:
        metadata = dict(getattr(fact, "metadata", {}) or {})
        topic = str(metadata.get("topic") or "").strip()
        if not (topic.startswith("world.skills.affinity.") or topic.startswith("skills.affinity.")):
            continue
        projection_policy = str(metadata.get("projection_policy") or "").strip().lower()
        if projection_policy in {
            "exclude",
            "excluded",
            "disabled",
            "retired",
            "not_relevant",
        }:
            continue
        skill_id = str(metadata.get("skill_id") or "").strip()
        index_id = str(metadata.get("index_id") or "").strip() or topic.rsplit(".", 1)[-1]
        for item in (skill_id, index_id):
            if item:
                out.add(item)
                out.add(_skill_index_id(item))
    return frozenset(out)


def _skill_matches_affinity(skill: SkillDefinition, affinity_ids: frozenset[str]) -> bool:
    if not affinity_ids:
        return False
    skill_id = str(skill.skill_id or "").strip()
    return skill_id in affinity_ids or _skill_index_id(skill_id) in affinity_ids


def prompt_index_skills(
    *,
    repository: RuntimeStorageRepository,
    profile_loader: ProfileLoader,
    skill_runtime: SkillRuntime | None,
    session: Episode,
    install_root: Path | None,
    surface_kind: str,
) -> tuple[SkillDefinition, ...]:
    # Extension manifest carries operator skill overrides only — identity
    # does not flow through profile.json anymore.
    loaded_profile = profile_loader.load()
    raw_overrides = loaded_profile.manifest.get("skill_overrides", {})
    enabled_overrides: dict[str, bool] = {}
    if isinstance(raw_overrides, Mapping):
        for skill_id, raw_value in raw_overrides.items():
            if isinstance(raw_value, Mapping) and "enabled" in raw_value:
                enabled_overrides[str(skill_id)] = _metadata_bool(raw_value.get("enabled"), default=True)
            elif isinstance(raw_value, bool):
                enabled_overrides[str(skill_id)] = raw_value
    affinity_ids = _skill_affinity_index_ids(repository, personal_model_id=session.personal_model_id)
    skills = [
        skill
        for skill in resolved_session_skills(
            repository=repository,
            profile_loader=profile_loader,
            skill_runtime=skill_runtime,
            session=session,
            surface_kind=surface_kind,
            prompt_visible_only=True,
        )
        if _skill_matches_affinity(skill, affinity_ids)
    ]
    seen = {skill.skill_id for skill in skills}
    for entry in operator_prompt_skill_catalog_entries(enabled_overrides, install_root=install_root):
        if entry.skill_id in seen:
            continue
        skill = entry.to_skill_definition()
        if not _skill_matches_affinity(skill, affinity_ids):
            continue
        skills.append(skill)
        seen.add(entry.skill_id)
    return tuple(skills[:12])


def resolved_session_skills(
    *,
    repository: RuntimeStorageRepository,
    profile_loader: ProfileLoader,
    skill_runtime: SkillRuntime | None,
    session: Episode,
    surface_kind: str,
    prompt_visible_only: bool = False,
) -> tuple[SkillDefinition, ...]:
    if skill_runtime is None:
        return ()
    # Identity / mode comes from the canonical State row so gateway + CLI see
    # the same mode and pick up the same skill set for the same elephant.
    profile = load_runtime_profile(
        repository,
        personal_model_id=session.personal_model_id,
        elephant_id=str(session.elephant_id or "") or None,
        profile_loader=profile_loader,
    )
    state = _resolve_elephant_state(repository, str(session.elephant_id or ""))
    skills = skill_runtime.resolve_for_context(
        personal_model_id="" if state is None else state.personal_model_id,
        state_id="" if state is None else state.state_id,
        surface_id=f"{surface_kind}:{session.episode_id}",
        surface_kind=surface_kind,
        mode=profile.state.mode,
    )
    if not prompt_visible_only:
        return skills
    return tuple(
        skill for skill in skills if _metadata_bool(skill.metadata.get("include_in_prompt_index"), default=True)
    )


def skill_disclosure_lines(
    prompt_skills: tuple[SkillDefinition, ...],
    *,
    install_root: Path | None,
) -> tuple[str, ...]:
    del install_root
    categories: dict[str, list[str]] = {}
    for skill in prompt_skills:
        category = str(skill.metadata.get("category") or "general").strip() or "general"
        categories.setdefault(category, []).append(f"{skill.display_name} ({skill.skill_id})")
    lines = [
        "### Capability Disclosure",
        "Skills are discoverable capabilities, not automatic prompt procedures.",
        "For procedural tasks, scan this episode-frozen index; if relevant, call `tool.skill.view` with the `skill_id` before relying on the procedure.",
        "Do not load skills for casual conversation or simple continuity replies unless the request needs a procedure.",
        f"Skill index ({len(prompt_skills)} episode-frozen entries):",
    ]
    for category in sorted(categories):
        listing = ", ".join(sorted(categories[category], key=str.casefold))
        lines.append(f"- {category} - {listing}")
    return tuple(lines)


@dataclass(frozen=True, slots=True)
class RuntimeSkillManagementSurface:
    skill_runtime: SkillRuntime
    skill_hub: SkillHub
    profile_loader: ProfileLoader
    profile_dir: Path
    skill_search_hub: SkillSearchHub | None = None
    installed_skills_dir: Path | None = None
    authored_skills_dir: Path | None = None

    def list_skill_hub(self, *, limit: int | None = None) -> tuple[SkillHubEntry, ...]:
        entries = self.skill_hub.list(self._enabled_overrides())
        if limit is None or limit <= 0:
            return entries
        return entries[:limit]

    def inspect_skill(self, skill_id: str, *, session_id: str | None = None) -> SkillDefinition:
        del session_id
        skill = self.skill_runtime.catalog.get(skill_id)
        if skill is not None:
            metadata = dict(skill.metadata)
            metadata.setdefault("installed", True)
            metadata.setdefault("hub_reference", f"elephant-installed:{skill.skill_id}")
            return replace(skill, metadata=metadata)
        entry = self.skill_hub.resolve(skill_id, self._enabled_overrides())
        if entry is None:
            raise KeyError(skill_id)
        definition = load_skill_package_definition(Path(entry.entry_path))
        metadata = dict(definition.metadata)
        metadata.update(entry.metadata)
        metadata.update(
            {
                "installed": entry.source_id in {"elephant-installed", "elephant-authored"},
                "hub_reference": entry.reference,
            }
        )
        return replace(definition, enabled=False, metadata=metadata)

    def inspect_skill_source(self, skill_id: str, *, session_id: str | None = None) -> SkillDefinition:
        try:
            return self.inspect_skill(skill_id, session_id=session_id)
        except KeyError:
            if self.skill_search_hub is None:
                raise
            fetched = self.skill_search_hub.fetch(skill_id)
            if fetched is None:
                raise
            return load_skill_package_definition(Path(fetched.package_path))

    def set_skill_enabled(
        self,
        skill_id: str,
        enabled: bool,
        *,
        session_id: str | None = None,
        profile_id: str | None = None,
    ) -> SkillDefinition:
        del session_id, profile_id
        updated = self.skill_runtime.set_enabled(skill_id, enabled)
        self._write_override(skill_id, enabled)
        return updated

    def install_skill_source(
        self,
        reference: str | Path,
        *,
        session_id: str | None = None,
        profile_id: str | None = None,
        requester: str | None = None,
    ) -> SkillManifestLoadRecord:
        del session_id, profile_id, requester
        raw = str(reference).strip()
        if not raw:
            raise ValueError("skill install requires a hub id, skill path, or manifest path")
        path_candidate = Path(raw).expanduser()
        if path_candidate.exists():
            return self._load_skill_package_or_manifest(path_candidate)
        entry = self.skill_hub.resolve(raw, self._enabled_overrides())
        if entry is not None:
            return self._load_skill_package_or_manifest(Path(entry.entry_path))
        if self.skill_search_hub is not None:
            fetched = self.skill_search_hub.fetch(raw)
            if fetched is not None:
                return self._load_skill_package_or_manifest(Path(fetched.package_path))
        raise KeyError(f"skill source was not found: {raw}")

    def create_authored_skill(
        self,
        *,
        skill_id: str,
        display_name: str,
        summary: str,
        instruction_text: str,
        category: str | None = None,
        install: bool = True,
        overwrite: bool = False,
        session_id: str | None = None,
        profile_id: str | None = None,
    ) -> SkillManifestLoadRecord:
        del session_id, profile_id
        root = self.authored_skills_dir or default_authored_skills_dir()
        package_path = write_skill_package(
            root,
            skill_id=skill_id,
            display_name=display_name,
            summary=summary,
            instruction_text=instruction_text,
            category=category,
            overwrite=overwrite,
            source_kind="elephant-authored",
        )
        if install:
            return self._load_skill_package_or_manifest(package_path)
        manifest = SkillPackageLoader().load(package_path)
        return SkillManifestLoadRecord(
            source_path=manifest.source_path,
            skill_ids=tuple(skill.skill_id for skill in manifest.skills),
            loaded_at=datetime.now(timezone.utc),
            status="written",
            detail="authored skill package written",
        )

    def update_authored_skill(
        self,
        skill_id: str,
        *,
        display_name: str | None = None,
        summary: str | None = None,
        instruction_text: str | None = None,
        category: str | None = None,
        session_id: str | None = None,
        profile_id: str | None = None,
    ) -> SkillManifestLoadRecord:
        current = self.inspect_skill(skill_id, session_id=session_id)
        return self.create_authored_skill(
            skill_id=current.skill_id,
            display_name=display_name or current.display_name,
            summary=summary or current.summary,
            instruction_text=instruction_text or current.instruction_text,
            category=category,
            install=True,
            overwrite=True,
            session_id=session_id,
            profile_id=profile_id,
        )

    def delete_skill_source(
        self,
        skill_id: str,
        *,
        session_id: str | None = None,
        profile_id: str | None = None,
    ) -> tuple[str, str]:
        del session_id, profile_id
        skill = self.inspect_skill(skill_id)
        self._write_override(skill.skill_id, False)
        self.skill_runtime.set_enabled(skill.skill_id, False)
        return skill.skill_id, str(skill.entry_path)

    def _load_skill_package_or_manifest(self, path: Path) -> SkillManifestLoadRecord:
        resolved = path.expanduser().resolve()
        if resolved.is_dir() or resolved.name == "SKILL.md":
            self.skill_runtime.load_package(resolved)
            self._append_profile_path("skill_packages", resolved)
        else:
            self.skill_runtime.load_manifest(resolved)
            self._append_profile_path("skill_manifests", resolved)
        return self.skill_runtime.list_manifest_loads()[-1]

    def _enabled_overrides(self) -> Mapping[str, bool]:
        loaded = self.profile_loader.load()
        return load_skill_extension_manifest(
            loaded.manifest,
            profile_dir=Path(loaded.profile_dir),
        ).skill_overrides

    def _read_manifest(self) -> dict[str, Any]:
        loaded = self.profile_loader.load()
        return dict(loaded.manifest)

    def _write_override(self, skill_id: str, enabled: bool) -> None:
        manifest = self._read_manifest()
        overrides = (
            dict(manifest.get("skill_overrides", {})) if isinstance(manifest.get("skill_overrides"), Mapping) else {}
        )
        overrides[skill_id] = {"enabled": enabled}
        manifest["skill_overrides"] = overrides
        write_extensions_manifest(self.profile_dir, manifest)

    def _append_profile_path(self, section: str, path: Path) -> None:
        manifest = self._read_manifest()
        current = manifest.get(section, ())
        values = [str(item) for item in current] if isinstance(current, list) else []
        serialized = _serialize_manifest_path(path, profile_dir=self.profile_dir)
        if serialized not in values:
            values.append(serialized)
        manifest[section] = values
        write_extensions_manifest(self.profile_dir, manifest)


def _load_enabled_overrides(manifest: Mapping[str, Any], section: str) -> dict[str, bool]:
    payload = manifest.get(section, {})
    if not isinstance(payload, Mapping):
        return {}
    overrides: dict[str, bool] = {}
    for item_id, record in payload.items():
        if isinstance(record, Mapping) and "enabled" in record:
            overrides[str(item_id)] = _metadata_bool(record.get("enabled"), default=True)
        elif isinstance(record, bool):
            overrides[str(item_id)] = record
    return overrides


def _load_manifest_paths(
    manifest: Mapping[str, Any],
    section: str,
    *,
    profile_dir: Path,
) -> tuple[Path, ...]:
    payload = manifest.get(section, ())
    if not isinstance(payload, list):
        return ()
    paths: list[Path] = []
    for item in payload:
        raw = str(item).strip()
        if not raw:
            continue
        path = Path(raw)
        if not path.is_absolute():
            path = profile_dir / path
        paths.append(path)
    return tuple(paths)


def _resolve_elephant_state(repository: RuntimeStorageRepository, elephant_id: str):
    resolved_elephant_id = elephant_id.strip()
    if resolved_elephant_id:
        state = repository.load_state(f"state:{resolved_elephant_id}")
        if state is not None:
            return state
        for candidate in repository.list_states():
            if candidate.elephant_id == resolved_elephant_id or candidate.state_anchor in {
                resolved_elephant_id,
                f"elephant:{resolved_elephant_id}",
            }:
                return candidate
    return repository.current_state()


def _metadata_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"true", "yes", "1", "on"}:
        return True
    if normalized in {"false", "no", "0", "off"}:
        return False
    return default


def _serialize_manifest_path(path: Path, *, profile_dir: Path) -> str:
    try:
        return str(path.relative_to(profile_dir))
    except ValueError:
        return str(path)
