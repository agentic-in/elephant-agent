"""Extension bootstrap helpers for the CLI runtime."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Any

from .snapshot_io import load_snapshot_payload, write_snapshot_payload
from packages.state import ProfileLoader
from packages.security import SecurityPolicy
from packages.skills import SkillActivationContext, SkillRuntime, builtin_skill_definitions
from packages.storage import RuntimeStorageRepository
from packages.tools import (
    BuiltinToolDependencies,
    ToolRuntime,
    ToolRuntimeContext,
    ToolRequester,
    build_secured_tool_runtime,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CliExtensionManifest:
    tool_overrides: Mapping[str, bool]
    tool_manifest_paths: tuple[Path, ...]
    skill_overrides: Mapping[str, bool]
    skill_manifest_paths: tuple[Path, ...]
    skill_package_paths: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class _PreviewTelemetrySink:
    snapshot_path: Path
    descriptor: Any = None
    observer: Any = None

    def emit(self, event: Mapping[str, Any]) -> None:
        if callable(self.observer):
            try:
                self.observer(dict(event))
            except Exception:
                LOGGER.warning("CLI telemetry observer failed", exc_info=True)
                pass
        existing = load_snapshot_payload(self.snapshot_path) or {}
        telemetry = list(existing.get("telemetry", ()))
        telemetry.append(dict(event))
        existing["telemetry"] = telemetry
        write_snapshot_payload(self.snapshot_path, existing)


def load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_extension_manifest(manifest: Mapping[str, Any], *, profile_dir: Path) -> CliExtensionManifest:
    sanitized, _removed_keys = sanitize_extension_manifest_payload(manifest)
    return CliExtensionManifest(
        tool_overrides=_load_enabled_overrides(sanitized, "tool_overrides"),
        tool_manifest_paths=_load_manifest_paths(sanitized, "tool_manifests", profile_dir=profile_dir),
        skill_overrides=_load_enabled_overrides(sanitized, "skill_overrides"),
        skill_manifest_paths=_load_manifest_paths(sanitized, "skill_manifests", profile_dir=profile_dir),
        skill_package_paths=_load_manifest_paths(sanitized, "skill_packages", profile_dir=profile_dir),
    )


def sanitize_extension_manifest_payload(
    manifest: Mapping[str, Any],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    payload = dict(manifest)
    removed: list[str] = []
    for key in ("mcp_servers", "mcp_overrides"):
        if key in payload:
            payload.pop(key, None)
            removed.append(key)
    return payload, tuple(removed)


def serialize_manifest_path(path: Path, *, profile_dir: Path) -> str:
    try:
        return str(path.relative_to(profile_dir))
    except ValueError:
        return str(path)


def build_tool_runtime(
    manifest: CliExtensionManifest,
    *,
    repository: RuntimeStorageRepository,
    dependencies: BuiltinToolDependencies,
    snapshot_path: Path,
    security_policy: SecurityPolicy,
) -> ToolRuntime:
    return build_secured_tool_runtime(
        enabled_overrides=manifest.tool_overrides,
        manifest_paths=manifest.tool_manifest_paths,
        dependencies=dependencies,
        security_policy=security_policy,
        telemetry=_PreviewTelemetrySink(snapshot_path),
        source="cli.tool.runtime",
        auto_approve_deferred=True,
        context_resolver=lambda session_id, requester: _resolve_tool_runtime_context(
            repository,
            session_id,
            requester=requester,
            dependencies=dependencies,
        ),
    )


def build_skill_runtime(
    manifest: CliExtensionManifest,
    *,
    repository: RuntimeStorageRepository,
    profile_loader: ProfileLoader,
    scan_on_init_dirs: tuple[Path, ...] = (),
) -> SkillRuntime:
    runtime = SkillRuntime(
        context_resolver=lambda session_id: _resolve_skill_activation_context(repository, profile_loader, session_id),
        state_resolver=repository.load_state,
        scan_on_init_dirs=scan_on_init_dirs or None,
    )
    for definition in builtin_skill_definitions(manifest.skill_overrides):
        runtime.register_skill(definition)
    for path in manifest.skill_manifest_paths:
        runtime.load_manifest(path)
    for path in manifest.skill_package_paths:
        runtime.load_package(path)
    return runtime


def _load_enabled_overrides(manifest: Mapping[str, Any], section: str) -> dict[str, bool]:
    payload = manifest.get(section, {})
    if not isinstance(payload, Mapping):
        return {}
    overrides: dict[str, bool] = {}
    for item_id, record in payload.items():
        if isinstance(record, Mapping) and "enabled" in record:
            overrides[str(item_id)] = bool(record["enabled"])
    return overrides


def _load_manifest_paths(manifest: Mapping[str, Any], section: str, *, profile_dir: Path) -> tuple[Path, ...]:
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


def _resolve_skill_activation_context(
    repository: RuntimeStorageRepository,
    profile_loader: ProfileLoader,
    session_id: str,
) -> SkillActivationContext:
    session = repository.load_episode_state(session_id)
    if session is None:
        raise KeyError(session_id)
    elephant_id = str(session.elephant_id or "").strip()
    state = _resolve_elephant_state(repository, elephant_id)
    from packages.state import load_runtime_profile

    # Identity + mode live on the State row; profile.json carries operator
    # extension overrides only.
    loaded = load_runtime_profile(
        repository,
        personal_model_id=session.personal_model_id,
        elephant_id=elephant_id or None,
        profile_loader=profile_loader,
    )
    return SkillActivationContext(
        personal_model_id="" if state is None else state.personal_model_id,
        state_id="" if state is None else state.state_id,
        surface_id=f"cli:{session_id}",
        surface_kind="cli",
        mode=loaded.state.mode,
    )


def _resolve_tool_runtime_context(
    repository: RuntimeStorageRepository,
    session_id: str,
    *,
    requester: ToolRequester | None,
    dependencies: BuiltinToolDependencies,
) -> ToolRuntimeContext:
    session = repository.load_episode_state(session_id)
    if session is None:
        raise KeyError(session_id)
    elephant_id = str(session.elephant_id or "").strip()
    state = _resolve_elephant_state(repository, elephant_id)
    cwd = dependencies.resolve_cwd(session_id)
    if elephant_id:
        cwd.mkdir(parents=True, exist_ok=True)
    return ToolRuntimeContext(
        cwd=cwd,
        allowed_roots=dependencies.additional_allowed_roots,
        env={},
        surface_id=f"cli:{session_id}",
        surface_kind="cli",
        requester=requester,
        personal_model_id="" if state is None else state.personal_model_id,
        state_id="" if state is None else state.state_id,
        elephant_id=elephant_id,
    )


def _resolve_elephant_state(repository: RuntimeStorageRepository, elephant_id: str):
    resolved_elephant_id = elephant_id.strip()
    if resolved_elephant_id:
        state = repository.load_state(f"state:{resolved_elephant_id}")
        if state is not None:
            return state
        try:
            candidates = repository.list_states(elephant_id=resolved_elephant_id)
        except TypeError:
            candidates = repository.list_states()
        for candidate in candidates:
            if candidate.elephant_id == resolved_elephant_id or candidate.state_anchor in {resolved_elephant_id, f"elephant:{resolved_elephant_id}"}:
                return candidate
    return repository.current_state()
