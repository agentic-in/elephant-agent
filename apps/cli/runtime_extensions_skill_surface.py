"""Skill and growth management methods for the CLI runtime extension surface."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
import shutil

from packages.contracts.runtime import ExperienceRecord
from packages.growth import GrowthUpdate, ProgressionProjection, ProgressionTransition
from packages.skills import (
    PublicSkillSourceDescriptor,
    SkillDefinition,
    SkillHubEntry,
    SkillManifestLoadRecord,
    SkillPackageLoader,
    SkillSearchEntry,
    build_installed_skill_provenance,
    build_public_skill_source_descriptor,
    install_bucket_for_source_descriptor,
    load_skill_package_definition,
    materialize_skill_package,
    public_skill_source_descriptor_from_metadata,
)
from packages.skills.authoring import write_skill_package

from .runtime_extensions import load_extension_manifest, serialize_manifest_path
from .runtime_extensions_skill_sources import (
    install_record_detail as _install_record_detail,
    installed_skill_record as _installed_skill_record,
    matching_install_record as _matching_install_record,
    normalized_install_requester as _normalized_install_requester,
    record_install_reference as _record_install_reference,
    remote_skill_definition as _remote_skill_definition,
    source_descriptor_for_hub_entry as _source_descriptor_for_hub_entry,
    source_descriptor_for_path as _source_descriptor_for_path,
)
from .runtime_growth_surface import (
    inspect_experiences as _inspect_experiences,
    inspect_growth as _inspect_growth,
    inspect_growth_transition as _inspect_growth_transition,
)
from .runtime_support import _path_is_within, _utc_now


class CliRuntimeSkillExtensionsMixin:
    """Skill hub, authored skill, and growth-inspection runtime surface."""

    def skill_catalog(self, *, session_id: str | None = None) -> tuple[SkillDefinition, ...]:
        if session_id is not None:
            self.prepare_session_surface(session_id, steady_embeddings=False)
        return self.skill_runtime.catalog.list()

    def list_skill_hub(self, *, limit: int | None = None) -> tuple[SkillHubEntry, ...]:
        entries = self.skill_hub.list(self._current_skill_enabled_overrides())
        if limit is None or limit <= 0:
            return entries
        return entries[:limit]

    def search_skill_hub(self, query: str, *, limit: int = 12) -> tuple[SkillHubEntry, ...]:
        return self.skill_hub.search(query, limit=limit, enabled_overrides=self._current_skill_enabled_overrides())

    def search_skill_sources(self, query: str, *, source: str | None = None, limit: int = 12) -> tuple[SkillSearchEntry, ...]:
        return self.skill_search_hub.search(query, source=source, limit=limit)

    def inspect_experiences(
        self,
        *,
        session_id: str | None = None,
        profile_id: str | None = None,
        statuses: tuple[str, ...] = (),
        limit: int | None = None,
    ) -> tuple[ExperienceRecord, ...]:
        return _inspect_experiences(self, session_id=session_id, profile_id=profile_id, statuses=statuses, limit=limit)

    def inspect_growth(
        self,
        *,
        session_id: str | None = None,
        profile_id: str | None = None,
    ) -> ProgressionProjection:
        return _inspect_growth(self, session_id=session_id, profile_id=profile_id)

    def consume_growth_update(self, *, session_id: str) -> GrowthUpdate | None:
        return self.growth_updates.pop(session_id, None)

    def inspect_growth_transition(self, update: GrowthUpdate, *, session_id: str) -> ProgressionTransition:
        return _inspect_growth_transition(self, update, session_id=session_id)

    def inspect_skill_hub_entry(self, reference: str) -> SkillHubEntry:
        entry = self.skill_hub.resolve(reference, self._current_skill_enabled_overrides())
        if entry is None:
            raise KeyError(reference)
        return entry

    def inspect_skill(self, skill_id: str, *, session_id: str | None = None) -> SkillDefinition:
        if session_id is not None:
            self.prepare_session_surface(session_id)
        skill = self.skill_runtime.catalog.get(skill_id)
        if skill is None:
            entry = self.skill_hub.resolve(skill_id, self._current_skill_enabled_overrides())
            if entry is not None:
                definition = load_skill_package_definition(Path(entry.entry_path))
                metadata = dict(definition.metadata)
                metadata.update(entry.metadata)
                source_descriptor = _source_descriptor_for_hub_entry(entry)
                if source_descriptor is not None:
                    metadata.update(source_descriptor.to_metadata())
                metadata.update(
                    {
                        "installed": entry.source_id in {"elephant-installed", "elephant-authored"},
                        "hub_reference": entry.reference,
                    }
                )
                return replace(definition, enabled=False, metadata=metadata)
            raise KeyError(skill_id)
        metadata = dict(skill.metadata)
        metadata.setdefault("installed", True)
        metadata.setdefault("hub_reference", f"elephant-installed:{skill.skill_id}")
        return replace(skill, metadata=metadata)

    def inspect_skill_source(self, skill_id: str, *, session_id: str | None = None) -> SkillDefinition:
        if session_id is not None:
            self.prepare_session_surface(session_id)
        try:
            return self.inspect_skill(skill_id)
        except KeyError:
            fetched = self.skill_search_hub.fetch(skill_id)
            if fetched is None:
                raise KeyError(skill_id) from None
            return _remote_skill_definition(fetched)

    def set_skill_enabled(
        self,
        skill_id: str,
        enabled: bool,
        *,
        session_id: str | None = None,
        profile_id: str | None = None,
    ) -> SkillDefinition:
        resolved_profile_id = self._resolve_extension_profile_id(session_id=session_id, profile_id=profile_id)
        self._refresh_extensions(profile_id=resolved_profile_id)
        updated = self.skill_runtime.set_enabled(skill_id, enabled)
        self._write_extension_override(
            "skill_overrides",
            skill_id,
            enabled,
            profile_id=resolved_profile_id,
        )
        return updated

    def _current_skill_enabled_overrides(self) -> Mapping[str, bool]:
        loaded = self.current_profile()
        return load_extension_manifest(
            loaded.manifest,
            profile_dir=Path(loaded.profile_dir),
        ).skill_overrides

    def install_skill_manifest(
        self,
        manifest_path: str | Path,
        *,
        session_id: str | None = None,
        profile_id: str | None = None,
    ) -> SkillManifestLoadRecord:
        resolved_profile_id = self._resolve_extension_profile_id(session_id=session_id, profile_id=profile_id)
        target_profile = self._load_profile(resolved_profile_id)
        resolved_path = Path(manifest_path).expanduser().resolve()
        if not resolved_path.exists():
            raise FileNotFoundError(resolved_path)
        profile_dir = Path(target_profile.profile_dir)
        manifest = dict(target_profile.manifest)
        extension_manifest = load_extension_manifest(manifest, profile_dir=profile_dir)
        existing_paths = list(extension_manifest.skill_manifest_paths)
        if resolved_path not in existing_paths:
            existing_paths.append(resolved_path)
        manifest["skill_manifests"] = [
            serialize_manifest_path(path, profile_dir=profile_dir)
            for path in existing_paths
        ]
        self._save_extensions_manifest(manifest)
        self._refresh_extensions(profile_id=resolved_profile_id)
        return self._skill_manifest_load_record(resolved_path)

    def install_skill_source(
        self,
        reference: str | Path,
        *,
        session_id: str | None = None,
        profile_id: str | None = None,
        requester: str | None = "operator",
    ) -> SkillManifestLoadRecord:
        raw = str(reference).strip()
        if not raw:
            raise ValueError("skill install requires a hub id, skill path, or manifest path")
        resolved_requester = _normalized_install_requester(requester)
        self._authorize_write(
            operation="cli.skill.install",
            session_id=session_id,
            description=raw,
            metadata={
                "reference": raw,
                "requester": resolved_requester,
            },
        )
        path_candidate = Path(raw).expanduser()
        if path_candidate.exists():
            resolved_path = path_candidate.resolve()
            if resolved_path.is_dir() or resolved_path.name == "SKILL.md":
                return self._install_skill_package_path(
                    resolved_path,
                    session_id=session_id,
                    profile_id=profile_id,
                    source_bucket="path",
                    source_descriptor=_source_descriptor_for_path(resolved_path),
                    requester=resolved_requester,
                )
            return self.install_skill_manifest(
                resolved_path,
                session_id=session_id,
                profile_id=profile_id,
            )
        entry = self.skill_hub.resolve(raw)
        if entry is not None:
            return self._install_skill_package_path(
                Path(entry.entry_path),
                session_id=session_id,
                profile_id=profile_id,
                source_bucket=entry.source_id,
                source_descriptor=_source_descriptor_for_hub_entry(entry),
                requester=resolved_requester,
            )
        fetched = self.skill_search_hub.fetch(raw)
        if fetched is None:
            raise KeyError(f"skill source was not found: {raw}")
        return self._install_skill_package_path(
            Path(fetched.package_path),
            session_id=session_id,
            profile_id=profile_id,
            source_bucket=fetched.source_id,
            source_descriptor=build_public_skill_source_descriptor(
                source_id=fetched.source_id,
                source_label=fetched.source_label,
                source_reference=fetched.reference,
                install_reference=fetched.install_reference,
                trust_level=fetched.trust_level,
                metadata=fetched.metadata,
            ),
            requester=resolved_requester,
        )

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
        source_kind: str = "elephant-authored",
        metadata: Mapping[str, object] | None = None,
        session_id: str | None = None,
        profile_id: str | None = None,
    ) -> SkillManifestLoadRecord:
        package_path = write_skill_package(
            self.paths.authored_skills_dir,
            skill_id=skill_id,
            display_name=display_name,
            summary=summary,
            instruction_text=instruction_text,
            category=category,
            overwrite=overwrite,
            source_kind=source_kind,
            metadata=metadata,
        )
        if install:
            return self._install_skill_package_path(
                package_path,
                session_id=session_id,
                profile_id=profile_id,
                source_bucket="authored",
            )
        manifest = SkillPackageLoader().load(package_path)
        return SkillManifestLoadRecord(
            source_path=manifest.source_path,
            skill_ids=tuple(skill.skill_id for skill in manifest.skills),
            loaded_at=_utc_now(),
            status="written",
            detail="shared Elephant Agent authored skill package",
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
        skill = self.inspect_skill(skill_id, session_id=session_id)
        entry_path = Path(skill.entry_path).expanduser().resolve()
        authored_root = self.paths.authored_skills_dir.expanduser().resolve()
        if not _path_is_within(entry_path, authored_root):
            raise ValueError(f"only authored skills can be updated through tool.skill.manage: {skill_id}")
        current = load_skill_package_definition(entry_path)
        resolved_category = category
        if resolved_category is None:
            try:
                relative = entry_path.parent.relative_to(authored_root)
            except ValueError:
                relative = Path()
            parents = relative.parts[:-1]
            resolved_category = parents[0] if parents else None
        return self.create_authored_skill(
            skill_id=current.skill_id,
            display_name=display_name or current.display_name,
            summary=summary or current.summary,
            instruction_text=instruction_text or current.instruction_text,
            category=resolved_category,
            install=True,
            overwrite=True,
            source_kind="elephant-authored",
            metadata=None,
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
        resolved_profile_id = self._resolve_extension_profile_id(session_id=session_id, profile_id=profile_id)
        skill = self.inspect_skill(skill_id, session_id=session_id)
        entry_path = Path(skill.entry_path).expanduser().resolve()
        installed_root = self.paths.installed_skills_dir.expanduser().resolve()
        authored_root = self.paths.authored_skills_dir.expanduser().resolve()
        if not (_path_is_within(entry_path, installed_root) or _path_is_within(entry_path, authored_root)):
            raise ValueError(f"only installed or authored skills can be deleted from this surface: {skill_id}")
        target_profile = self._load_profile(resolved_profile_id)
        profile_dir = Path(target_profile.profile_dir)
        manifest = dict(target_profile.manifest)
        extension_manifest = load_extension_manifest(manifest, profile_dir=profile_dir)
        removed_path = entry_path
        manifest["skill_packages"] = [
            serialize_manifest_path(path, profile_dir=profile_dir)
            for path in extension_manifest.skill_package_paths
            if path.resolve() != removed_path
        ]
        existing_overrides = manifest.get("skill_overrides", {})
        overrides = dict(existing_overrides) if isinstance(existing_overrides, Mapping) else {}
        overrides.pop(skill.skill_id, None)
        if overrides:
            manifest["skill_overrides"] = overrides
        else:
            manifest.pop("skill_overrides", None)
        self._save_extensions_manifest(manifest)
        skill_dir = removed_path.parent
        if skill_dir.exists():
            shutil.rmtree(skill_dir)
        self._refresh_extensions(profile_id=resolved_profile_id)
        return skill.skill_id, str(removed_path)

    def create_experience_skill(
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
        package_path = write_skill_package(
            self.paths.authored_skills_dir,
            skill_id=skill_id,
            display_name=display_name,
            summary=summary,
            instruction_text=instruction_text,
            category=category or "experience",
            overwrite=overwrite,
        )
        if install:
            return self._install_skill_package_path(
                package_path,
                session_id=session_id,
                profile_id=profile_id,
            )
        manifest = SkillPackageLoader().load(package_path)
        return SkillManifestLoadRecord(
            source_path=manifest.source_path,
            skill_ids=tuple(skill.skill_id for skill in manifest.skills),
            loaded_at=_utc_now(),
            status="written",
            detail="shared Elephant Agent experience skill package",
        )

    def _install_skill_package_path(
        self,
        package_path: Path,
        *,
        session_id: str | None = None,
        profile_id: str | None = None,
        source_bucket: str | None = None,
        source_descriptor: PublicSkillSourceDescriptor | None = None,
        requester: str | None = "operator",
    ) -> SkillManifestLoadRecord:
        resolved_profile_id = self._resolve_extension_profile_id(session_id=session_id, profile_id=profile_id)
        target_profile = self._load_profile(resolved_profile_id)
        resolved_path = package_path.expanduser().resolve()
        if resolved_path.is_dir():
            resolved_path = resolved_path / "SKILL.md"
        if not resolved_path.exists():
            raise FileNotFoundError(resolved_path)
        installed_root = self.paths.installed_skills_dir
        authored_root = self.paths.authored_skills_dir
        definition = load_skill_package_definition(resolved_path)
        source_descriptor = source_descriptor or public_skill_source_descriptor_from_metadata(definition.metadata)
        if (
            source_descriptor is None
            and not _path_is_within(resolved_path, installed_root)
            and not _path_is_within(resolved_path, authored_root)
        ):
            source_descriptor = _source_descriptor_for_path(resolved_path, source_bucket=source_bucket)
        profile_dir = Path(target_profile.profile_dir)
        manifest = dict(target_profile.manifest)
        extension_manifest = load_extension_manifest(manifest, profile_dir=profile_dir)
        existing_paths = list(extension_manifest.skill_package_paths)
        existing_records = [
            record
            for path in existing_paths
            if (record := _installed_skill_record(path)) is not None and record["skill_id"] == definition.skill_id
        ]
        matching_record = _matching_install_record(
            existing_records,
            source_descriptor=source_descriptor,
            selection_path=resolved_path,
        )
        install_action = "install"
        previous_install_reference: str | None = None
        if existing_records:
            install_action = "refresh" if matching_record is not None else "migrate"
            if install_action == "migrate":
                previous_install_reference = _record_install_reference(existing_records[0])
        installed_at = _utc_now().isoformat()
        install_provenance = None
        if source_descriptor is not None:
            install_provenance = build_installed_skill_provenance(
                source=source_descriptor,
                install_action=install_action,
                installed_at=installed_at,
                install_requester=_normalized_install_requester(requester),
                previous_install_reference=previous_install_reference,
            )
        if _path_is_within(resolved_path, installed_root) or _path_is_within(resolved_path, authored_root):
            materialized_path = resolved_path
        else:
            materialized_dir = materialize_skill_package(
                installed_root,
                resolved_path,
                source_bucket=(
                    install_bucket_for_source_descriptor(source_descriptor)
                    if source_descriptor is not None
                    else source_bucket or "imported"
                ),
                install_provenance=install_provenance,
            )
            materialized_path = (materialized_dir / "SKILL.md").resolve()
        stale_paths = {
            Path(record["path"]).expanduser().resolve()
            for record in existing_records
            if Path(record["path"]).expanduser().resolve() != materialized_path
        }
        retained_paths: list[Path] = []
        retained_resolved: set[Path] = set()
        for path in existing_paths:
            resolved_existing = path.expanduser().resolve()
            if resolved_existing in stale_paths:
                continue
            if resolved_existing in retained_resolved:
                continue
            retained_paths.append(resolved_existing)
            retained_resolved.add(resolved_existing)
        if materialized_path not in retained_resolved:
            retained_paths.append(materialized_path)
        manifest["skill_packages"] = [
            serialize_manifest_path(path, profile_dir=profile_dir)
            for path in retained_paths
        ]
        self._save_extensions_manifest(manifest)
        for stale_path in stale_paths:
            if not _path_is_within(stale_path, installed_root):
                continue
            stale_dir = stale_path.parent if stale_path.name == "SKILL.md" else stale_path
            if stale_dir.exists():
                shutil.rmtree(stale_dir, ignore_errors=True)
        self._refresh_extensions(profile_id=resolved_profile_id)
        record = self._skill_manifest_load_record(materialized_path)
        record_metadata = dict(record.metadata)
        if install_provenance is not None:
            record_metadata.update(install_provenance.to_metadata())
        return replace(
            record,
            detail=_install_record_detail(
                source_descriptor=source_descriptor,
                install_action=install_action,
                previous_install_reference=previous_install_reference,
            ),
            metadata=record_metadata,
        )
