"""Shared console configuration and file helpers for API operator surfaces."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import json

from packages.runtime_config import (
    global_config_path_for_state_dir,
    load_global_config,
    load_extensions_from_config,
    write_global_config,
)


def _write_manifest_to_config(state_dir: Path, manifest: Mapping[str, Any]) -> Path:
    """Write manifest data (gateway, extensions) to config.yaml.

    Treats the fields *present* in ``manifest`` as authoritative:

    - If ``manifest["gateway"]`` is a Mapping, the persisted gateway
      section is *replaced* by it (not merged). This ensures keys
      removed from the manifest (e.g. dropping the last account) are
      actually dropped on disk.
    - If ``manifest["gateway"]`` is explicitly ``None`` or an empty
      Mapping, the gateway section is deleted from config. Callers
      signal "drop this section" by setting ``manifest["gateway"] =
      None``.
    - If ``manifest`` omits ``gateway`` entirely, the persisted
      gateway section is left untouched. This preserves compatibility
      with callers (e.g. operator settings patcher) that only care
      about other sections.
    """
    config_path = global_config_path_for_state_dir(state_dir)
    config = load_global_config(config_path, state_dir=state_dir)
    # Gateway section
    if "gateway" in manifest:
        gateway_payload = manifest.get("gateway")
        if isinstance(gateway_payload, Mapping) and gateway_payload:
            # Replace rather than merge so removed keys are honoured.
            config["gateway"] = dict(gateway_payload)
        else:
            # Explicit None / empty mapping — delete the section.
            config.pop("gateway", None)
    # (else: caller omitted gateway entirely — leave persisted value alone.)
    # Provider section
    provider_profile = manifest.get("provider_profile")
    if isinstance(provider_profile, Mapping):
        models = config.get("models", {})
        models["provider"] = dict(provider_profile)
        models["default_provider_source"] = "config"
        config["models"] = models
    # Extension keys
    extension_keys = ("tool_manifests", "skill_manifests", "skill_overrides", "tool_overrides", "skill_packages")
    extensions = config.get("extensions", {})
    for key in extension_keys:
        if key in manifest:
            extensions[key] = manifest[key]
    if extensions:
        config["extensions"] = extensions
    write_global_config(config_path, config)
    return config_path


def _read_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _load_manifest_from_config(state_dir: Path) -> dict[str, Any]:
    """Load manifest data (gateway, extensions) from config.yaml for the given state_dir."""
    from packages.runtime_config import global_config_path_for_state_dir
    config_path = global_config_path_for_state_dir(state_dir)
    try:
        config = load_global_config(config_path, state_dir=state_dir)
        result: dict[str, Any] = {}
        extensions = load_extensions_from_config(config)
        if extensions:
            result.update(extensions)
        gateway = config.get("gateway")
        if isinstance(gateway, Mapping):
            result["gateway"] = dict(gateway)
        return result
    except (OSError, ValueError):
        pass
    return {}


def _read_text_file(path: Path, *, max_chars: int = 20_000) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _tail_lines(path: Path, *, max_lines: int = 160) -> tuple[str, ...]:
    text = _read_text_file(path, max_chars=80_000)
    if not text:
        return ()
    return tuple(text.splitlines()[-max_lines:])


def _logs(state_dir: Path) -> list[dict[str, Any]]:
    candidates = [
        *state_dir.glob("*.log"),
    ]
    seen: set[Path] = set()
    rows: list[dict[str, Any]] = []
    for path in sorted(candidates):
        resolved = path.resolve()
        if resolved in seen or not path.is_file():
            continue
        seen.add(resolved)
        rows.append(
            {
                "name": path.name,
                "path": str(path),
                "size": path.stat().st_size,
                "updatedAt": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
                "tail": _tail_lines(path),
            }
        )
    return rows



__all__ = [
    "_write_manifest_to_config",
    "_read_json_file",
    "_load_manifest_from_config",
    "_read_text_file",
    "_tail_lines",
    "_logs",
]
