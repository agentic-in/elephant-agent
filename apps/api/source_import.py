"""Local source import orchestration for desktop/profile-builder flows."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from packages.contracts import Episode, Loop, SemanticIndexEntry, State, Step

MAX_IMPORT_FILES = 120
MAX_IMPORT_BYTES = 256 * 1024
MAX_STEP_CONTENT_CHARS = 6_000

SKIP_DIR_NAMES = frozenset(
    {
        ".cache",
        ".git",
        ".hg",
        ".mypy_cache",
        ".next",
        ".pytest_cache",
        ".ruff_cache",
        ".svn",
        ".turbo",
        ".venv",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "node_modules",
        "target",
        "vendor",
    }
)

SECRET_NAME_MARKERS = frozenset(
    {
        ".env",
        ".pem",
        ".p12",
        ".pfx",
        ".key",
        "credential",
        "credentials",
        "secret",
        "secrets",
        "token",
    }
)

SUPPORTED_SUFFIXES = frozenset(
    {
        ".c",
        ".cfg",
        ".conf",
        ".cpp",
        ".css",
        ".go",
        ".h",
        ".hpp",
        ".html",
        ".ini",
        ".java",
        ".js",
        ".json",
        ".jsx",
        ".kt",
        ".lua",
        ".md",
        ".mdx",
        ".mjs",
        ".py",
        ".rb",
        ".rs",
        ".rst",
        ".sh",
        ".sql",
        ".swift",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
        ".zsh",
    }
)

SUPPORTED_FILE_NAMES = frozenset(
    {
        "Dockerfile",
        "Makefile",
        "README",
        "AGENTS.md",
        "LICENSE",
        "Pipfile",
        "Gemfile",
    }
)


@dataclass(frozen=True, slots=True)
class SourceFile:
    path: Path
    root: Path
    size_bytes: int
    content: str
    content_hash: str

    @property
    def display_path(self) -> str:
        try:
            return str(self.path.relative_to(self.root))
        except ValueError:
            return str(self.path)


def _now() -> datetime:
    return datetime.now(UTC)


def _normalize_mode(value: object) -> str:
    mode = str(value or "manual").strip()
    if mode not in {"profile_builder", "manual"}:
        raise ValueError('mode must be "profile_builder" or "manual"')
    return mode


def _secret_like(path: Path) -> bool:
    lowered_parts = tuple(part.lower() for part in path.parts)
    name = path.name.lower()
    if name.startswith(".env"):
        return True
    if name in SECRET_NAME_MARKERS:
        return True
    if path.suffix.lower() in SECRET_NAME_MARKERS:
        return True
    return any(marker in part for marker in SECRET_NAME_MARKERS for part in lowered_parts)


def _supported_file(path: Path) -> bool:
    return path.name in SUPPORTED_FILE_NAMES or path.suffix.lower() in SUPPORTED_SUFFIXES


def _decode_text(path: Path) -> tuple[str | None, str | None, int]:
    try:
        stat = path.stat()
    except OSError:
        return None, "unreadable", 0
    if stat.st_size > MAX_IMPORT_BYTES:
        return None, "too_large", int(stat.st_size)
    try:
        raw = path.read_bytes()
    except OSError:
        return None, "unreadable", int(stat.st_size)
    if b"\x00" in raw[:4096]:
        return None, "binary", int(stat.st_size)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, "binary", int(stat.st_size)
    if not text.strip():
        return None, "empty", int(stat.st_size)
    return text, None, int(stat.st_size)


def _iter_candidate_files(root: Path) -> tuple[Path, ...]:
    if root.is_file():
        return (root,)
    if not root.is_dir():
        return ()
    files: list[Path] = []
    for path in root.rglob("*"):
        if len(files) >= MAX_IMPORT_FILES:
            break
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        if path.is_file():
            files.append(path)
    return tuple(files)


def scan_source_paths(paths: tuple[str, ...]) -> tuple[tuple[SourceFile, ...], dict[str, int], dict[str, int]]:
    admitted: list[SourceFile] = []
    skipped: Counter[str] = Counter()
    stats: Counter[str] = Counter()

    for raw_path in paths:
        expanded = Path(raw_path).expanduser()
        try:
            root = expanded.resolve()
        except OSError:
            skipped["missing"] += 1
            continue
        if not root.exists():
            skipped["missing"] += 1
            continue
        for path in _iter_candidate_files(root):
            stats["scanned_count"] += 1
            if len(admitted) >= MAX_IMPORT_FILES:
                skipped["file_limit"] += 1
                continue
            if _secret_like(path):
                skipped["secret_like"] += 1
                continue
            if not _supported_file(path):
                skipped["unsupported_type"] += 1
                continue
            content, reason, size_bytes = _decode_text(path)
            if reason is not None or content is None:
                skipped[reason or "unreadable"] += 1
                continue
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            admitted.append(
                SourceFile(
                    path=path,
                    root=root if root.is_dir() else root.parent,
                    size_bytes=size_bytes,
                    content=content,
                    content_hash=content_hash,
                )
            )

    stats["admitted_count"] = len(admitted)
    stats["skipped_count"] = sum(skipped.values())
    return tuple(admitted), dict(skipped), dict(stats)


def _state_for_import(app: Any, elephant_id: str | None) -> State:
    repository = app.repository
    pm = repository.ensure_default_personal_model()
    target = str(elephant_id or "").strip()
    if target:
        direct = repository.load_state(f"state:{target}")
        if direct is not None:
            repository.switch_state(direct.state_id)
            return direct
        for candidate in repository.list_states(personal_model_id=pm.personal_model_id):
            if candidate.elephant_id == target:
                repository.switch_state(candidate.state_id)
                return candidate
        raise KeyError(target)

    current = repository.current_state()
    if current is not None:
        return current
    states = repository.list_states(personal_model_id=pm.personal_model_id)
    if states:
        repository.switch_state(states[0].state_id)
        return states[0]
    state = repository.create_state(
        personal_model_id=pm.personal_model_id,
        state_id="state:desktop",
        state_anchor="elephant:desktop",
        elephant_id="desktop",
        elephant_name="Elephant Desktop",
        identity_mode="companion",
        surface_bindings=("api", "dashboard", "desktop"),
        summary="Elephant Desktop is ready to build local context.",
        metadata={"source": "desktop.source_import"},
    )
    repository.switch_state(state.state_id)
    return state


def _step_for_source(
    *,
    source: SourceFile,
    import_id: str,
    episode: Episode,
    loop: Loop,
    sequence: int,
    current: datetime,
) -> Step:
    preview = source.content[:MAX_STEP_CONTENT_CHARS]
    if len(source.content) > MAX_STEP_CONTENT_CHARS:
        preview = f"{preview}\n\n[truncated]"
    return Step(
        step_id=f"source-step:{import_id}:{sequence}",
        loop_id=loop.loop_id,
        episode_id=episode.episode_id,
        state_id=episode.state_id,
        personal_model_id=episode.personal_model_id,
        phase="observation",
        action="source_import",
        status="completed",
        sequence=sequence,
        created_at=current,
        summary=f"Imported local source: {source.display_path}",
        outcome=f"Path: {source.path}\nBytes: {source.size_bytes}\nSHA256: {source.content_hash}\n\n{preview}",
        payload_refs=(f"source-import:{import_id}:{source.content_hash}",),
        metadata={
            "source": "desktop.source_import",
            "import_id": import_id,
            "path": str(source.path),
            "display_path": source.display_path,
            "content_hash": source.content_hash,
            "size_bytes": str(source.size_bytes),
        },
    )


def _semantic_entry_for_source(
    *,
    source: SourceFile,
    import_id: str,
    episode: Episode,
    sequence: int,
    current: datetime,
) -> SemanticIndexEntry:
    return SemanticIndexEntry(
        semantic_index_entry_id=f"semantic-source:{import_id}:{sequence}",
        owner_scope="state",
        source_id=f"source-import:{import_id}:{source.content_hash}",
        provider_id="source-import",
        model_id="local-text",
        dimensions=1,
        content_hash=source.content_hash,
        personal_model_id=episode.personal_model_id,
        state_id=episode.state_id,
        backend="metadata",
        vector_ref=f"step:{episode.episode_id}:{sequence}",
        status="indexed",
        created_at=current,
        updated_at=current,
        metadata={
            "source": "desktop.source_import",
            "import_id": import_id,
            "episode_id": episode.episode_id,
            "path": str(source.path),
            "display_path": source.display_path,
            "size_bytes": str(source.size_bytes),
        },
    )


def _store_import_status(app: Any, import_id: str, payload: Mapping[str, Any]) -> None:
    registry = getattr(app, "_source_imports", None)
    if registry is None:
        registry = {}
        setattr(app, "_source_imports", registry)
    registry[import_id] = dict(payload)


def load_source_import_status(app: Any, import_id: str) -> dict[str, Any] | None:
    registry = getattr(app, "_source_imports", None)
    if not isinstance(registry, dict):
        return None
    item = registry.get(import_id)
    return dict(item) if isinstance(item, Mapping) else None


def run_source_import(app: Any, *, paths: tuple[str, ...], elephant_id: str | None, mode: object) -> dict[str, Any]:
    if not paths:
        raise ValueError("paths must include at least one local file or folder")

    import_mode = _normalize_mode(mode)
    import_id = f"source-import:{uuid4().hex}"
    files, skipped_reasons, stats = scan_source_paths(paths)
    current = _now()
    state = _state_for_import(app, elephant_id)
    pm = app.repository.ensure_default_personal_model(personal_model_id=state.personal_model_id)

    episode_id: str | None = None
    job_id: str | None = None
    status = "completed"
    progress = 100

    if files:
        episode_id = f"episode:{import_id}"
        loop_id = f"loop:{import_id}"
        episode = Episode(
            episode_id=episode_id,
            state_id=state.state_id,
            personal_model_id=pm.personal_model_id,
            entry_surface="desktop",
            status="closed",
            started_at=current,
            ended_at=current,
            updated_at=current,
            exit_summary=f"Imported {len(files)} local source files for review and background understanding.",
            elephant_id=state.elephant_id,
            metadata={
                "source": "desktop.source_import",
                "import_id": import_id,
                "mode": import_mode,
            },
        )
        loop = Loop(
            loop_id=loop_id,
            episode_id=episode.episode_id,
            state_id=episode.state_id,
            personal_model_id=episode.personal_model_id,
            trigger_type="source_import",
            status="completed",
            started_at=current,
            ended_at=current,
            summary=f"Scanned {stats.get('scanned_count', 0)} files; admitted {len(files)}.",
            outcome="Imported local sources as evidence. Personal Model facts were not written directly.",
            metadata={
                "source": "desktop.source_import",
                "import_id": import_id,
                "mode": import_mode,
            },
        )
        app.repository.upsert_episode(episode)
        app.repository.upsert_loop(loop)
        for sequence, source in enumerate(files, start=1):
            app.repository.upsert_step(
                _step_for_source(
                    source=source,
                    import_id=import_id,
                    episode=episode,
                    loop=loop,
                    sequence=sequence,
                    current=current,
                )
            )
            app.repository.upsert_semantic_index_entry(
                _semantic_entry_for_source(
                    source=source,
                    import_id=import_id,
                    episode=episode,
                    sequence=sequence,
                    current=current,
                )
            )
        trigger = "init_profile" if import_mode == "profile_builder" else "source_import"
        job = app.repository.enqueue_learning_job(
            job_type="episode_boundary_learning",
            trigger=trigger,
            personal_model_id=pm.personal_model_id,
            state_id=state.state_id,
            episode_id=episode.episode_id,
            loop_id=loop.loop_id,
            summary=f"source import reflect job ({len(files)} admitted files)",
            metadata={
                "source": "desktop.source_import",
                "import_id": import_id,
                "mode": import_mode,
                "admitted_count": str(len(files)),
            },
            force_new=True,
        )
        job_id = job.job_id
        try:
            from apps.learning_worker_runtime import ensure_learning_worker_running

            ensure_learning_worker_running(state_dir=app.repository.database_path.parent)
        except Exception:
            pass

    payload = {
        "import_id": import_id,
        "status": status,
        "progress": progress,
        "scanned_count": int(stats.get("scanned_count", 0)),
        "admitted_count": int(stats.get("admitted_count", 0)),
        "skipped_count": int(stats.get("skipped_count", 0)),
        "skipped_reasons": skipped_reasons,
        "episode_id": episode_id,
        "job_id": job_id,
        "error": None,
        "paths": tuple(paths),
    }
    _store_import_status(app, import_id, payload)
    return dict(payload)


__all__ = [
    "load_source_import_status",
    "run_source_import",
    "scan_source_paths",
]
