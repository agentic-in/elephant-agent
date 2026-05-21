"""API loop context compression helpers."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from packages.context.compress import compress_epoch
from packages.context.epoch_store import FileEpochStore
from packages.kernel import KernelStageRecord
from packages.kernel.context_compaction import flush_projection_cache


def compact_context_after_usage(app: Any, episode_id: str, outcome: Any) -> Any:
    """Mirror CLI chat's after-turn high-usage context compression for API loops."""
    execution = getattr(outcome, "execution", None)
    usage_tokens = max(
        _safe_int(getattr(execution, "prompt_tokens", 0)),
        _safe_int(getattr(execution, "total_tokens", 0)),
    )
    context = getattr(outcome, "context", None)
    context_limit = _safe_int(getattr(context, "token_budget", 0))
    if context_limit <= 0:
        runtime = getattr(getattr(app, "context", None), "runtime", None)
        context_limit = _safe_int(getattr(runtime, "total_tokens", 0))
    if usage_tokens <= 0 or context_limit <= 0:
        return outcome
    epoch_store = FileEpochStore(app.repository.database_path.parent)
    epoch = epoch_store.load(episode_id)
    if epoch is None:
        return outcome
    result = compress_epoch(
        epoch,
        context_limit=context_limit,
        usage_tokens=usage_tokens,
        reflect_compressor=None,
        session_id=episode_id,
    )
    if result is None:
        return outcome
    updated_epoch, compress_result = result
    epoch_store.save(updated_epoch)
    _persist_context_compress_summary(app, episode_id, compress_result.summary)
    compacted_messages = max(
        0,
        compress_result.before_messages - compress_result.after_messages,
    )
    detail = (
        f"reason=usage "
        f"tokens={compress_result.before_tokens}->{compress_result.after_tokens} "
        f"messages={compress_result.before_messages}->{compress_result.after_messages} "
        f"compacted_messages={compacted_messages} "
        f"tail={compress_result.after_messages} "
        f"method={compress_result.method}"
    )
    source_event_id = str(
        getattr(getattr(outcome, "event", None), "event_id", "")
    )
    record = KernelStageRecord(
        stage="context-compact",
        detail=detail,
        recorded_at=datetime.now(timezone.utc),
    )
    emit = getattr(getattr(app, "telemetry", None), "emit", None)
    if callable(emit):
        emit(
            {
                "event_id": f"telemetry:{episode_id}:context-compact:{uuid4().hex}",
                "event_type": "kernel.stage",
                "episode_id": episode_id,
                "session_id": episode_id,
                "source": "api",
                "payload": {
                    "stage": record.stage,
                    "detail": record.detail,
                    "recorded_at": record.recorded_at.isoformat(),
                    "event_id": source_event_id,
                },
            }
        )
    flush_projection_cache(getattr(app, "context", None))
    try:
        return replace(
            outcome,
            stages=(*tuple(getattr(outcome, "stages", ()) or ()), record),
        )
    except TypeError:
        return outcome


def _persist_context_compress_summary(app: Any, episode_id: str, summary: str) -> None:
    connection_factory = getattr(app.repository, "connection", None)
    if not callable(connection_factory):
        return
    try:
        with connection_factory() as connection:
            connection.execute(
                "UPDATE episodes SET exit_summary = ? WHERE episode_id = ?",
                (summary, episode_id),
            )
            connection.commit()
    except Exception:
        return


def _safe_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


__all__ = ["compact_context_after_usage"]
