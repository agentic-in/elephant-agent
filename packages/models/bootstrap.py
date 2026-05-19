"""Embedding bootstrap state and background worker helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
import warnings

from packages.embeddings import (
    ELEPHANT_EMBED_MODEL_ID,
    ELEPHANT_EMBED_MODELSCOPE_ID,
    ELEPHANT_EMBED_MODELSCOPE_URL,
    ELEPHANT_EMBED_SOURCE_URL,
    embedding_model_root_path,
    embedding_root_is_healthy,
    sentence_transformers_dependencies_ready,
)

EMBEDDING_MODEL_ID = ELEPHANT_EMBED_MODEL_ID
EMBEDDING_MODEL_SOURCE_URL = ELEPHANT_EMBED_SOURCE_URL
EMBEDDING_MODEL_MODELSCOPE_ID = ELEPHANT_EMBED_MODELSCOPE_ID
EMBEDDING_MODEL_MODELSCOPE_URL = ELEPHANT_EMBED_MODELSCOPE_URL
EMBEDDING_MODEL_ROOT = embedding_model_root_path()
EMBEDDING_BOOTSTRAP_STATE_FILE = "embedding-bootstrap.json"
EMBEDDING_BOOTSTRAP_LOG_FILE = "embedding-bootstrap.log"
_ALLOWED_EMBEDDING_BOOTSTRAP_STATUSES = frozenset({"pending", "downloading", "failed", "ready", "skipped"})
_ALLOWED_EMBEDDING_SOURCES = frozenset({"huggingface", "modelscope"})
_EMBEDDING_BOOTSTRAP_PIP_SPECS = (
    "sentence-transformers>=3,<4",
    "huggingface-hub>=0.30,<1",
)
_EMBEDDING_BOOTSTRAP_PIP_SPECS_MODELSCOPE = (
    "sentence-transformers>=3,<4",
    "modelscope>=1.10,<2",
)


@dataclass(frozen=True, slots=True)
class EmbeddingBootstrapState:
    status: str
    summary: str
    state_focus_mode: str
    updated_at: str
    failure_message: str | None = None
    background_pid: int | None = None
    model_id: str = EMBEDDING_MODEL_ID
    model_root: str = str(EMBEDDING_MODEL_ROOT)
    model_source_url: str = EMBEDDING_MODEL_SOURCE_URL
    source: str = "huggingface"


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return {str(key): value for key, value in payload.items()}


def _normalize_state_focus_mode(value: object) -> str:
    normalized = str(value or "skip").strip().lower() or "skip"
    return normalized if normalized in {"embedded", "skip"} else "skip"


def _normalize_embedding_bootstrap_status(value: object) -> str:
    normalized = str(value or "pending").strip().lower() or "pending"
    return normalized if normalized in _ALLOWED_EMBEDDING_BOOTSTRAP_STATUSES else "pending"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _embedding_bootstrap_pid_from_payload(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _embedding_bootstrap_pid_is_active(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def embedding_bootstrap_state_path(state_dir: Path | None) -> Path | None:
    if state_dir is None:
        return None
    return state_dir / EMBEDDING_BOOTSTRAP_STATE_FILE


def embedding_bootstrap_log_path(state_dir: Path | None) -> Path | None:
    if state_dir is None:
        return None
    return state_dir / EMBEDDING_BOOTSTRAP_LOG_FILE


def _embedding_bootstrap_summary(
    *,
    state_focus_mode: str,
    status: str,
    failure_message: str | None = None,
) -> str:
    if state_focus_mode == "skip":
        return "local semantic-index bootstrap is skipped for this provider turn."
    if status == "ready":
        return f"local embedding root is available at {EMBEDDING_MODEL_ROOT}"
    if status == "pending":
        return (
            "local semantic-index bootstrap is preparing minimal sentence-transformers dependencies in the background."
        )
    if status == "downloading":
        return (
            "local semantic-index bootstrap is running; background "
            f"model acquisition from {EMBEDDING_MODEL_SOURCE_URL} is in progress."
        )
    if status == "failed":
        detail = (
            str(failure_message or "embedding bootstrap request failed").strip() or "embedding bootstrap request failed"
        )
        return f"local semantic-index bootstrap remains non-blocking after a failure: {detail}"
    return "local semantic-index bootstrap is waiting for the background worker to report state."


def embedding_bootstrap_state_from_payload(
    payload: Mapping[str, Any],
) -> EmbeddingBootstrapState:
    status = _normalize_embedding_bootstrap_status(payload.get("status"))
    state_focus_mode = _normalize_state_focus_mode(payload.get("state_focus_mode"))
    failure_message = str(payload.get("failure_message") or "").strip() or None
    stored_summary = str(payload.get("summary") or "").strip()
    if "state_focus_mode=" in stored_summary:
        stored_summary = ""
    summary = stored_summary or _embedding_bootstrap_summary(
        state_focus_mode=state_focus_mode,
        status=status,
        failure_message=failure_message,
    )
    updated_at = str(payload.get("updated_at") or "").strip() or _utc_now_iso()
    model_id = str(payload.get("model_id") or EMBEDDING_MODEL_ID).strip() or EMBEDDING_MODEL_ID
    model_root = str(payload.get("model_root") or EMBEDDING_MODEL_ROOT).strip() or str(EMBEDDING_MODEL_ROOT)
    model_source_url = (
        str(payload.get("model_source_url") or EMBEDDING_MODEL_SOURCE_URL).strip() or EMBEDDING_MODEL_SOURCE_URL
    )
    source_raw = str(payload.get("source") or "huggingface").strip().lower()
    source = source_raw if source_raw in _ALLOWED_EMBEDDING_SOURCES else "huggingface"
    background_pid = _embedding_bootstrap_pid_from_payload(payload.get("background_pid"))
    return EmbeddingBootstrapState(
        status=status,
        summary=summary,
        state_focus_mode=state_focus_mode,
        updated_at=updated_at,
        failure_message=failure_message,
        background_pid=background_pid,
        model_id=model_id,
        model_root=model_root,
        model_source_url=model_source_url,
        source=source,
    )


def load_embedding_bootstrap_state(
    state_dir: Path | None,
) -> EmbeddingBootstrapState | None:
    path = embedding_bootstrap_state_path(state_dir)
    if path is None or not path.exists():
        return None
    payload = _read_json_object(path)
    if payload is None:
        return None
    return embedding_bootstrap_state_from_payload(payload)


def persist_embedding_bootstrap_state(
    state_dir: Path | None,
    state: EmbeddingBootstrapState,
) -> EmbeddingBootstrapState:
    path = embedding_bootstrap_state_path(state_dir)
    if path is None:
        return state
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": state.status,
        "summary": state.summary,
        "state_focus_mode": state.state_focus_mode,
        "updated_at": state.updated_at,
        "failure_message": state.failure_message,
        "background_pid": state.background_pid,
        "model_id": state.model_id,
        "model_root": state.model_root,
        "model_source_url": state.model_source_url,
        "source": state.source,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def _embedding_bootstrap_worker_command(state_dir: Path) -> tuple[str, ...]:
    return (
        sys.executable,
        "-c",
        (
            "import sys; "
            "from packages.models.bootstrap import run_embedding_bootstrap_worker as _worker; "
            "raise SystemExit(_worker(sys.argv[1]))"
        ),
        str(state_dir),
    )


def _spawn_embedding_bootstrap_worker(
    state_dir: Path,
    state: EmbeddingBootstrapState,
) -> EmbeddingBootstrapState:
    log_path = embedding_bootstrap_log_path(state_dir)
    if log_path is None:
        return state
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # Persist state before spawning so the worker can read source from disk.
    persist_embedding_bootstrap_state(state_dir, state)
    command = _embedding_bootstrap_worker_command(state_dir)
    with log_path.open("ab") as log_stream:
        process = subprocess.Popen(
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    background_pid = process.pid
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            category=ResourceWarning,
            message=r"subprocess \d+ is still running",
        )
        del process
    return EmbeddingBootstrapState(
        status=state.status,
        summary=state.summary,
        state_focus_mode=state.state_focus_mode,
        updated_at=_utc_now_iso(),
        failure_message=state.failure_message,
        background_pid=background_pid,
        model_id=state.model_id,
        model_root=state.model_root,
        model_source_url=state.model_source_url,
        source=state.source,
    )


def _embedding_bootstrap_state_for_runtime(
    *,
    status: str,
    failure_message: str | None = None,
    updated_at: str | None = None,
    background_pid: int | None = None,
    source: str = "huggingface",
) -> EmbeddingBootstrapState:
    return EmbeddingBootstrapState(
        status=status,
        summary=_embedding_bootstrap_summary(
            state_focus_mode="embedded",
            status=status,
            failure_message=failure_message,
        ),
        state_focus_mode="embedded",
        updated_at=updated_at or _utc_now_iso(),
        failure_message=failure_message,
        background_pid=background_pid,
        source=source,
    )


def resolve_embedding_bootstrap_state(
    state_dir: Path | None,
    *,
    state_focus_mode: str,
) -> EmbeddingBootstrapState:
    normalized_state_focus_mode = _normalize_state_focus_mode(state_focus_mode)
    stored = load_embedding_bootstrap_state(state_dir)
    if normalized_state_focus_mode == "skip":
        updated_at = stored.updated_at if stored is not None and stored.state_focus_mode == "skip" else _utc_now_iso()
        return EmbeddingBootstrapState(
            status="skipped",
            summary=_embedding_bootstrap_summary(state_focus_mode="skip", status="skipped"),
            state_focus_mode="skip",
            updated_at=updated_at,
            background_pid=None,
        )
    if embedding_root_is_healthy(str(EMBEDDING_MODEL_ROOT)):
        updated_at = (
            stored.updated_at
            if stored is not None and stored.state_focus_mode == "embedded" and stored.status == "ready"
            else _utc_now_iso()
        )
        return _embedding_bootstrap_state_for_runtime(status="ready", updated_at=updated_at)
    if stored is not None and stored.state_focus_mode == "embedded" and stored.status == "failed":
        return stored
    active_pid = None
    if stored is not None and stored.state_focus_mode == "embedded":
        active_pid = stored.background_pid if _embedding_bootstrap_pid_is_active(stored.background_pid) else None
        if stored.status in {"pending", "downloading"} and active_pid is not None:
            return _embedding_bootstrap_state_for_runtime(
                status=stored.status,
                updated_at=stored.updated_at,
                background_pid=active_pid,
            )
    status = "downloading" if sentence_transformers_dependencies_ready() else "pending"
    return _embedding_bootstrap_state_for_runtime(status=status, background_pid=active_pid)


def run_embedding_bootstrap_worker(state_dir_arg: str) -> int:
    state_dir = Path(state_dir_arg).expanduser()
    current_pid = os.getpid()
    # Determine source from persisted bootstrap state.
    stored = load_embedding_bootstrap_state(state_dir)
    source = stored.source if stored is not None else "huggingface"
    try:
        if embedding_root_is_healthy(str(EMBEDDING_MODEL_ROOT)):
            persist_embedding_bootstrap_state(
                state_dir,
                _embedding_bootstrap_state_for_runtime(status="ready", background_pid=None, source=source),
            )
            return 0
        if not sentence_transformers_dependencies_ready():
            persist_embedding_bootstrap_state(
                state_dir,
                _embedding_bootstrap_state_for_runtime(status="pending", background_pid=current_pid, source=source),
            )
            pip_specs = (
                _EMBEDDING_BOOTSTRAP_PIP_SPECS_MODELSCOPE if source == "modelscope" else _EMBEDDING_BOOTSTRAP_PIP_SPECS
            )
            subprocess.check_call(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    *pip_specs,
                ]
            )
        persist_embedding_bootstrap_state(
            state_dir,
            _embedding_bootstrap_state_for_runtime(status="downloading", background_pid=current_pid, source=source),
        )
        EMBEDDING_MODEL_ROOT.parent.mkdir(parents=True, exist_ok=True)
        if source == "modelscope":
            from modelscope import snapshot_download as ms_snapshot_download

            ms_snapshot_download(
                EMBEDDING_MODEL_MODELSCOPE_ID,
                local_dir=str(EMBEDDING_MODEL_ROOT),
            )
        else:
            from huggingface_hub import snapshot_download

            snapshot_download(
                repo_id=EMBEDDING_MODEL_ID,
                local_dir=str(EMBEDDING_MODEL_ROOT),
            )
        if not embedding_root_is_healthy(str(EMBEDDING_MODEL_ROOT)):
            raise RuntimeError(
                f"downloaded embedding root at {EMBEDDING_MODEL_ROOT} is missing sentence-transformers markers"
            )
        persist_embedding_bootstrap_state(
            state_dir,
            _embedding_bootstrap_state_for_runtime(status="ready", background_pid=None, source=source),
        )
        return 0
    except Exception as error:
        failure_message = str(error).strip() or error.__class__.__name__
        persist_embedding_bootstrap_state(
            state_dir,
            _embedding_bootstrap_state_for_runtime(
                status="failed",
                failure_message=failure_message,
                background_pid=None,
                source=source,
            ),
        )
        return 1


def trigger_embedding_bootstrap(
    state_dir: Path | None,
    *,
    state_focus_mode: str,
    source: str | None = None,
) -> EmbeddingBootstrapState:
    resolved = resolve_embedding_bootstrap_state(state_dir, state_focus_mode=state_focus_mode)
    if state_focus_mode != "embedded" or state_dir is None or resolved.status in {"ready", "skipped"}:
        return persist_embedding_bootstrap_state(state_dir, resolved)
    if resolved.background_pid is not None and _embedding_bootstrap_pid_is_active(resolved.background_pid):
        return persist_embedding_bootstrap_state(state_dir, resolved)
    # When source is not explicitly provided, preserve previously stored source.
    effective_source = source if source is not None else resolved.source
    normalized_source = effective_source if effective_source in _ALLOWED_EMBEDDING_SOURCES else "huggingface"
    retryable = resolved
    if resolved.status == "failed":
        retryable = _embedding_bootstrap_state_for_runtime(
            status="pending", background_pid=None, source=normalized_source
        )
    else:
        from dataclasses import replace as _dc_replace

        retryable = _dc_replace(retryable, source=normalized_source)
    try:
        spawned = _spawn_embedding_bootstrap_worker(state_dir, retryable)
    except OSError as error:
        return persist_embedding_bootstrap_state(
            state_dir,
            _embedding_bootstrap_state_for_runtime(
                status="failed",
                failure_message=str(error).strip() or error.__class__.__name__,
                background_pid=None,
                source=normalized_source,
            ),
        )
    return persist_embedding_bootstrap_state(state_dir, spawned)


__all__ = [
    "EMBEDDING_BOOTSTRAP_LOG_FILE",
    "EMBEDDING_BOOTSTRAP_STATE_FILE",
    "EMBEDDING_MODEL_ID",
    "EMBEDDING_MODEL_MODELSCOPE_ID",
    "EMBEDDING_MODEL_MODELSCOPE_URL",
    "EMBEDDING_MODEL_ROOT",
    "EMBEDDING_MODEL_SOURCE_URL",
    "EmbeddingBootstrapState",
    "embedding_bootstrap_log_path",
    "embedding_bootstrap_state_from_payload",
    "embedding_bootstrap_state_path",
    "load_embedding_bootstrap_state",
    "persist_embedding_bootstrap_state",
    "resolve_embedding_bootstrap_state",
    "run_embedding_bootstrap_worker",
    "trigger_embedding_bootstrap",
]
