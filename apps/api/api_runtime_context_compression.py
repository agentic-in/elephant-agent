"""API loop context compression helpers."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import logging
from typing import Any
from uuid import uuid4

from apps.reflect.context_compression import FALLBACK_NOTE, reflect_compress_summary
from packages.context.compress import compress_epoch, split_for_compress
from packages.context.epoch_store import FileEpochStore
from packages.kernel import KernelStageRecord
from packages.kernel.context_compaction import flush_projection_cache


_LOG = logging.getLogger(__name__)
_USAGE_AFTER_TURN_COMPACTION_RATIO = 0.85


def compact_context_after_usage(app: Any, episode_id: str, outcome: Any) -> Any:
    """Mirror CLI chat's after-turn high-usage Reflect context compression for API loops."""
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
    trigger_tokens = max(1, int(context_limit * _USAGE_AFTER_TURN_COMPACTION_RATIO))
    if usage_tokens < trigger_tokens:
        return outcome
    epoch_store = FileEpochStore(app.repository.database_path.parent)
    epoch = epoch_store.load(episode_id)
    if epoch is None:
        return outcome
    if not epoch.frozen or not epoch.history_messages:
        return outcome
    to_summarize, tail = split_for_compress(epoch.history_messages)
    if not to_summarize:
        return outcome
    source_event_id = str(
        getattr(getattr(outcome, "event", None), "event_id", "")
    )
    _emit_context_compact_stage(
        app,
        episode_id,
        source_event_id=source_event_id,
        detail=(
            f"reason=usage phase=compressing "
            f"tokens={usage_tokens}->? "
            f"messages={len(epoch.history_messages)}->{len(tail)} "
            f"compacting={len(to_summarize)} tail={len(tail)} "
            f"method=reflect"
        ),
    )
    reflect_attempted = False

    def reflect_compressor(
        messages_to_summarize,
        protected_tail,
        *,
        session_id: str,
        context_limit: int,
    ) -> str:
        nonlocal reflect_attempted
        reflect_attempted = True
        return _run_reflect_context_compressor(
            app,
            session_id=session_id,
            frozen_epoch=epoch,
            to_summarize=tuple(messages_to_summarize),
            tail=tuple(protected_tail),
            context_limit=context_limit,
        )

    result = compress_epoch(
        epoch,
        context_limit=context_limit,
        usage_tokens=usage_tokens,
        trigger_ratio=_USAGE_AFTER_TURN_COMPACTION_RATIO,
        reflect_compressor=reflect_compressor,
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
    if reflect_attempted and compress_result.method != "reflect":
        detail = f"{detail} note={FALLBACK_NOTE}"
    record = KernelStageRecord(
        stage="context-compact",
        detail=detail,
        recorded_at=datetime.now(timezone.utc),
    )
    _emit_context_compact_stage(
        app,
        episode_id,
        source_event_id=source_event_id,
        detail=record.detail,
        recorded_at=record.recorded_at,
    )
    flush_projection_cache(getattr(app, "context", None))
    try:
        return replace(
            outcome,
            stages=(*tuple(getattr(outcome, "stages", ()) or ()), record),
        )
    except TypeError:
        return outcome


def _run_reflect_context_compressor(
    app: Any,
    *,
    session_id: str,
    frozen_epoch: Any,
    to_summarize: tuple[Any, ...],
    tail: tuple[Any, ...],
    context_limit: int,
) -> str:
    try:
        runtime = _reflect_runtime(app)
        summary, _fallback_note = reflect_compress_summary(
            runtime,
            session_id=session_id,
            frozen_epoch=frozen_epoch,
            to_summarize=to_summarize,
            tail=tail,
            context_limit=context_limit,
            log=_LOG,
        )
        return summary
    except Exception as exc:
        _LOG.warning("api context reflect compressor failed: %s", exc, exc_info=True)
        return ""


def _reflect_runtime(app: Any) -> Any:
    run_sub_agent = getattr(app, "run_sub_agent", None)
    if callable(run_sub_agent):
        return app
    from apps.cli.runtime import CliRuntime

    return CliRuntime.create(
        state_dir=app.repository.database_path.parent,
        warm_embedding=False,
    )


def _emit_context_compact_stage(
    app: Any,
    episode_id: str,
    *,
    source_event_id: str,
    detail: str,
    recorded_at: datetime | None = None,
) -> None:
    recorded = recorded_at or datetime.now(timezone.utc)
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
                    "stage": "context-compact",
                    "detail": detail,
                    "recorded_at": recorded.isoformat(),
                    "event_id": source_event_id,
                },
            }
        )


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
