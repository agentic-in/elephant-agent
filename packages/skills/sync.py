"""Materialize the repo-bundled built-in skill shelf into Elephant Agent home."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import threading
from typing import Any
from uuid import uuid4

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None  # type: ignore[assignment]

from packages.runtime_layout import default_builtin_skills_dir


MANIFEST_FILENAME = ".manifest.json"
_SYNC_THREAD_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class BuiltinSkillShelfSync:
    source_root: Path
    destination_root: Path
    manifest_path: Path
    entry_count: int


def sync_builtin_skill_shelf(
    *,
    source_root: Path | None = None,
    destination_root: Path | None = None,
) -> BuiltinSkillShelfSync:
    """Replace the materialized built-in skill shelf with the repo source.

    Built-ins are owned by the Elephant Agent package, so the home shelf is an exact
    inspectable mirror rather than a user-editable installed-skill directory.
    User-authored and installed skills live in sibling roots.
    """

    resolved_source = (source_root or repo_builtin_skill_source_root()).expanduser().resolve()
    resolved_destination = (destination_root or default_builtin_skills_dir()).expanduser()
    if not resolved_source.exists():
        resolved_destination.mkdir(parents=True, exist_ok=True)
        manifest = _manifest_payload(resolved_source, entries=())
        _write_manifest(resolved_destination / MANIFEST_FILENAME, manifest)
        return BuiltinSkillShelfSync(
            source_root=resolved_source,
            destination_root=resolved_destination,
            manifest_path=resolved_destination / MANIFEST_FILENAME,
            entry_count=0,
        )

    parent = resolved_destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    lock_path = parent / f".{resolved_destination.name}.lock"
    with _sync_lock(lock_path):
        entries = tuple(
            _skill_entry_payload(skill_md, shelf_root=resolved_source)
            for skill_md in sorted(resolved_source.rglob("SKILL.md"))
        )
        manifest = _manifest_payload(resolved_source, entries=entries)
        manifest_path = resolved_destination / MANIFEST_FILENAME
        if _manifest_matches(manifest_path, manifest) and _shelf_files_match(
            source=resolved_source,
            destination=resolved_destination,
        ):
            return BuiltinSkillShelfSync(
                source_root=resolved_source,
                destination_root=resolved_destination,
                manifest_path=manifest_path,
                entry_count=len(entries),
            )

        staging = parent / f".{resolved_destination.name}.{uuid4().hex}.tmp"
        backup = parent / f".{resolved_destination.name}.{uuid4().hex}.bak"
        try:
            shutil.copytree(
                resolved_source,
                staging,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            _write_manifest(staging / MANIFEST_FILENAME, manifest)
            if resolved_destination.exists():
                resolved_destination.replace(backup)
            staging.replace(resolved_destination)
            if backup.exists():
                _remove_path(backup)
        except Exception:
            if not resolved_destination.exists() and backup.exists():
                backup.replace(resolved_destination)
            raise
        finally:
            if staging.exists():
                _remove_path(staging)
            if backup.exists():
                _remove_path(backup)
    return BuiltinSkillShelfSync(
        source_root=resolved_source,
        destination_root=resolved_destination,
        manifest_path=resolved_destination / MANIFEST_FILENAME,
        entry_count=len(entries),
    )


def repo_builtin_skill_source_root() -> Path:
    return Path(__file__).resolve().parent / "builtin_packages"


def _skill_entry_payload(skill_md: Path, *, shelf_root: Path) -> dict[str, Any]:
    rel = skill_md.relative_to(shelf_root)
    package_root = skill_md.parent
    package_rel = str(package_root.relative_to(shelf_root))
    return {
        "path": package_rel,
        "entry": str(rel),
        "hash": _directory_hash(package_root),
    }


def _manifest_payload(source_root: Path, *, entries: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    return {
        "version": 1,
        "source_root": str(source_root),
        "entry_count": len(entries),
        "entries": list(entries),
    }


def _write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _manifest_matches(path: Path, expected: dict[str, Any]) -> bool:
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return current == expected


def _shelf_files_match(*, source: Path, destination: Path) -> bool:
    if not destination.is_dir():
        return False
    return _relative_shelf_files(source) == _relative_shelf_files(destination)


def _relative_shelf_files(root: Path) -> tuple[str, ...]:
    return tuple(
        str(candidate.relative_to(root))
        for candidate in sorted(root.rglob("*"))
        if candidate.is_file() and not _ignored_shelf_file(candidate)
    )


def _ignored_shelf_file(candidate: Path) -> bool:
    return candidate.name == MANIFEST_FILENAME or candidate.suffix == ".pyc" or "__pycache__" in candidate.parts


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


@contextmanager
def _sync_lock(path: Path):
    with _SYNC_THREAD_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a+", encoding="utf-8")
        try:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()


def _directory_hash(directory: Path) -> str:
    hasher = hashlib.sha256()
    for candidate in sorted(directory.rglob("*")):
        if not candidate.is_file() or "__pycache__" in candidate.parts:
            continue
        rel = candidate.relative_to(directory)
        hasher.update(str(rel).encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(candidate.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()


__all__ = [
    "BuiltinSkillShelfSync",
    "MANIFEST_FILENAME",
    "repo_builtin_skill_source_root",
    "sync_builtin_skill_shelf",
]
