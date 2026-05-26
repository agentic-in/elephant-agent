"""Helpers for writing and materializing Elephant Agent-owned skill packages."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import hashlib
import re
import shutil

from .provenance import InstalledSkillProvenance
from .runtime import load_skill_package_definition


_VALID_SEGMENT_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
# Hard per-asset cap to avoid exotic skill packages. 1 MiB is plenty for
# scripts/configs; templates larger than that should live elsewhere.
_MAX_ASSET_BYTES = 1 * 1024 * 1024


def write_skill_package(
    root: Path,
    *,
    skill_id: str,
    display_name: str,
    summary: str,
    instruction_text: str,
    category: str | None = None,
    overwrite: bool = False,
    source_kind: str = "elephant-experience",
    assets: Mapping[str, bytes] | None = None,
    metadata: Mapping[str, object] | None = None,
) -> Path:
    resolved_skill_id = _validated_segment(skill_id, field_name="skill_id")
    resolved_category = _validated_segment(category, field_name="category") if category else None
    resolved_display_name = display_name.strip()
    resolved_summary = " ".join(summary.split())
    resolved_instructions = instruction_text.strip()
    if not resolved_display_name:
        raise ValueError("display_name is required")
    if not resolved_summary:
        raise ValueError("summary is required")
    if not resolved_instructions:
        raise ValueError("instruction_text is required")
    skill_dir = root.expanduser()
    if resolved_category:
        skill_dir = skill_dir / resolved_category
    skill_dir = skill_dir / resolved_skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    resolved_assets = _resolve_assets(assets, skill_dir=skill_dir, overwrite=overwrite)
    skill_file = skill_dir / "SKILL.md"
    if skill_file.exists() and not overwrite:
        raise FileExistsError(skill_file)
    skill_file.write_text(
        _render_skill_markdown(
            skill_id=resolved_skill_id,
            display_name=resolved_display_name,
            summary=resolved_summary,
            instruction_text=resolved_instructions,
            source_kind=source_kind,
            asset_paths=tuple(path for path, _ in resolved_assets),
            metadata=metadata,
        ),
        encoding="utf-8",
    )
    for rel_path, payload in resolved_assets:
        _write_asset(skill_dir, rel_path=rel_path, payload=payload, overwrite=overwrite)
    return skill_dir


def _resolve_assets(
    assets: Mapping[str, bytes] | None,
    *,
    skill_dir: Path,
    overwrite: bool,
) -> list[tuple[str, bytes]]:
    """Validate and normalize asset map into ``(rel_path, payload_bytes)`` pairs."""
    if not assets:
        return []
    resolved: list[tuple[str, bytes]] = []
    seen: set[str] = set()
    for raw_path, payload in assets.items():
        rel_path = _validated_asset_path(raw_path, skill_dir=skill_dir)
        if rel_path in seen:
            raise ValueError(f"duplicate asset path: {rel_path!r}")
        seen.add(rel_path)
        if payload is None:
            raise ValueError(f"asset payload for {rel_path!r} is None")
        if isinstance(payload, str):
            payload_bytes = payload.encode("utf-8")
        elif isinstance(payload, (bytes, bytearray)):
            payload_bytes = bytes(payload)
        else:
            raise TypeError(f"asset payload for {rel_path!r} must be bytes or str; got {type(payload).__name__}")
        if len(payload_bytes) > _MAX_ASSET_BYTES:
            raise ValueError(
                f"asset {rel_path!r} is {len(payload_bytes)} bytes which exceeds "
                f"the per-asset limit of {_MAX_ASSET_BYTES} bytes"
            )
        target = (skill_dir / rel_path).resolve()
        if target.exists() and not overwrite:
            # If the existing file has the same hash, silently accept (idempotent).
            existing_hash = hashlib.sha256(target.read_bytes()).hexdigest()
            new_hash = hashlib.sha256(payload_bytes).hexdigest()
            if existing_hash != new_hash:
                raise FileExistsError(target)
        resolved.append((rel_path, payload_bytes))
    return resolved


def _validated_asset_path(raw_path: object, *, skill_dir: Path) -> str:
    path_str = str(raw_path or "").strip()
    if not path_str:
        raise ValueError("asset path is required")
    if path_str.startswith("/") or path_str.startswith("~"):
        raise ValueError(f"asset path must be relative: {path_str!r}")
    parts = [segment for segment in path_str.replace("\\", "/").split("/") if segment]
    if any(segment in {"", ".", ".."} for segment in parts):
        raise ValueError(f"asset path cannot contain '.' or '..': {path_str!r}")
    if parts and parts[0].upper() == "SKILL.MD":
        raise ValueError("asset path must not overwrite SKILL.md")
    rel_path = "/".join(parts)
    # Final containment check: must resolve under skill_dir.
    resolved = (skill_dir / rel_path).resolve()
    try:
        resolved.relative_to(skill_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"asset path escapes skill directory: {path_str!r}") from exc
    return rel_path


def _write_asset(skill_dir: Path, *, rel_path: str, payload: bytes, overwrite: bool) -> None:
    target = skill_dir / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not overwrite:
        existing_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        new_hash = hashlib.sha256(payload).hexdigest()
        if existing_hash == new_hash:
            return  # idempotent no-op
        raise FileExistsError(target)
    target.write_bytes(payload)


def materialize_skill_package(
    root: Path,
    source_path: Path,
    *,
    source_bucket: str,
    install_provenance: InstalledSkillProvenance | None = None,
    overwrite: bool = True,
) -> Path:
    resolved_bucket = _validated_segment(source_bucket, field_name="source_bucket")
    definition = load_skill_package_definition(source_path)
    resolved_skill_id = _validated_segment(definition.skill_id, field_name="skill_id")
    source_entry = Path(definition.entry_path).expanduser().resolve()
    source_dir = source_entry.parent
    target_dir = root.expanduser() / resolved_bucket / resolved_skill_id
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    if target_dir.exists():
        if not overwrite:
            return target_dir
        shutil.rmtree(target_dir)
    shutil.copytree(source_dir, target_dir)
    if install_provenance is not None:
        _write_install_provenance(target_dir / "SKILL.md", install_provenance)
    return target_dir


def _validated_segment(value: str | None, *, field_name: str) -> str:
    if value is None:
        raise ValueError(f"{field_name} is required")
    resolved = value.strip().lower()
    if not resolved:
        raise ValueError(f"{field_name} is required")
    if not _VALID_SEGMENT_RE.match(resolved):
        raise ValueError(
            f"{field_name} must use lowercase letters, digits, dots, underscores, or hyphens: {value!r}"
        )
    return resolved


def _render_skill_markdown(
    *,
    skill_id: str,
    display_name: str,
    summary: str,
    instruction_text: str,
    source_kind: str,
    asset_paths: tuple[str, ...] = (),
    metadata: Mapping[str, object] | None = None,
) -> str:
    lines = [
        "---",
        f"name: {display_name}",
        f"skill_id: {skill_id}",
        f"description: {summary}",
        "version: 1.0.0",
        f"source_kind: {source_kind}",
    ]
    for key, value in _frontmatter_metadata(metadata).items():
        lines.append(f"{key}: {value}")
    if asset_paths:
        lines.append(f"assets: {', '.join(asset_paths)}")
    lines.extend([
        "---",
        "",
        f"# {display_name}",
        "",
        instruction_text.rstrip(),
        "",
    ])
    if asset_paths:
        lines.extend([
            "## Dependent files",
            "",
            *(f"- `{path}`" for path in asset_paths),
            "",
        ])
    return "\n".join(lines)


def _frontmatter_metadata(metadata: Mapping[str, object] | None) -> dict[str, str]:
    if not isinstance(metadata, Mapping):
        return {}
    allowed_keys = (
        "default_enabled",
        "include_in_hub",
        "include_in_prompt_index",
        "include_in_site",
        "include_in_overlay",
        "review_status",
        "draft_kind",
        "target_skill_id",
        "candidate_key",
        "confidence",
        "source_episode_ids",
        "overlap_reviewed_skill_ids",
        "evidence_summary",
    )
    rendered: dict[str, str] = {}
    for key in allowed_keys:
        if key not in metadata:
            continue
        value = metadata.get(key)
        if value is None:
            continue
        if isinstance(value, bool):
            text = "true" if value else "false"
        elif isinstance(value, (list, tuple)):
            text = ", ".join(str(item).strip() for item in value if str(item).strip())
        else:
            text = " ".join(str(value).split()).strip()
        if text:
            rendered[key] = text.replace("\n", " ")
    return rendered


def _write_install_provenance(skill_file: Path, install_provenance: InstalledSkillProvenance) -> None:
    text = skill_file.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter_block(text)
    for key, value in install_provenance.to_metadata().items():
        normalized = str(value).strip()
        if normalized:
            frontmatter[key] = normalized
    skill_file.write_text(_render_frontmatter_block(frontmatter, body), encoding="utf-8")


def _split_frontmatter_block(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return ({}, text)
    closing = text.find("\n---\n", 4)
    if closing == -1:
        return ({}, text)
    payload: dict[str, str] = {}
    for raw_line in text[4:closing].splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        payload[key.strip()] = value.strip()
    return payload, text[closing + len("\n---\n") :]


def _render_frontmatter_block(frontmatter: dict[str, str], body: str) -> str:
    lines = ["---"]
    lines.extend(f"{key}: {value}" for key, value in frontmatter.items())
    lines.extend(["---", ""])
    stripped_body = body.lstrip("\n").rstrip()
    if stripped_body:
        lines.append(stripped_body)
        lines.append("")
    return "\n".join(lines)
