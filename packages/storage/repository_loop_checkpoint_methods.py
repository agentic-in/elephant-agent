"""Loop checkpoint repository methods."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Mapping

from packages.contracts import Loop, Step
from packages.contracts.runtime import LoopState, LoopStep, PendingToolCall, RetryState, WaitCondition

from .repository_support import _iso
from .repository_system_methods import (
    _iso_optional_datetime,
    _json_metadata,
    _parse_optional_datetime,
    canonical_personal_model_id,
)


_LOOP_STATE_SCHEMA_VERSION = 2


def _wait_condition_to_mapping(condition: WaitCondition | None) -> Mapping[str, object] | None:
    if condition is None:
        return None
    payload = dict(condition.payload or {})
    event_match = dict(condition.event_match or {}) if condition.event_match is not None else None
    return {
        "kind": condition.kind,
        "payload": payload,
        "wake_at": _iso_optional_datetime(condition.wake_at),
        "event_topic": condition.event_topic,
        "event_match": event_match,
        "tool_handle_id": condition.tool_handle_id,
        "created_at": _iso_optional_datetime(condition.created_at),
        "auto_wake": condition.auto_wake,
    }


def _wait_condition_from_mapping(value: object) -> WaitCondition | None:
    if value is None:
        return None
    parsed = _maybe_json_mapping(value)
    if parsed is None:
        return None
    kind = str(parsed.get("kind") or "").strip()
    if not kind:
        return None
    payload_raw = parsed.get("payload") or {}
    payload = {str(k): str(v) for k, v in dict(payload_raw).items()} if isinstance(payload_raw, Mapping) else {}
    event_match_raw = parsed.get("event_match")
    event_match: Mapping[str, str] | None
    if isinstance(event_match_raw, Mapping):
        event_match = {str(k): str(v) for k, v in event_match_raw.items()}
    else:
        event_match = None
    return WaitCondition(
        kind=kind,
        payload=payload,
        wake_at=_parse_optional_datetime(parsed.get("wake_at")),
        event_topic=(str(parsed.get("event_topic")) if parsed.get("event_topic") else None),
        event_match=event_match,
        tool_handle_id=(str(parsed.get("tool_handle_id")) if parsed.get("tool_handle_id") else None),
        created_at=_parse_optional_datetime(parsed.get("created_at")),
        auto_wake=bool(parsed.get("auto_wake", True)),
    )


def _retry_state_to_mapping(state: RetryState | None) -> Mapping[str, object] | None:
    if state is None:
        return None
    return {
        "attempt": int(state.attempt),
        "last_error_kind": state.last_error_kind,
        "last_error_detail": state.last_error_detail,
        "next_retry_at": _iso_optional_datetime(state.next_retry_at),
        "idempotency_key": state.idempotency_key,
    }


def _retry_state_from_mapping(value: object) -> RetryState | None:
    if value is None:
        return None
    parsed = _maybe_json_mapping(value)
    if parsed is None:
        return None
    return RetryState(
        attempt=int(parsed.get("attempt") or 0),
        last_error_kind=str(parsed.get("last_error_kind") or ""),
        last_error_detail=str(parsed.get("last_error_detail") or ""),
        next_retry_at=_parse_optional_datetime(parsed.get("next_retry_at")),
        idempotency_key=(str(parsed.get("idempotency_key")) if parsed.get("idempotency_key") else None),
    )


def _pending_tool_call_to_mapping(call: PendingToolCall) -> Mapping[str, object]:
    arguments = dict(call.arguments or {})
    return {
        "call_id": call.call_id,
        "tool_name": call.tool_name,
        "arguments": arguments,
        "started_at": _iso_optional_datetime(call.started_at),
        "step_id": call.step_id,
        "handle_id": call.handle_id,
        "status": call.status,
        "idempotency_key": call.idempotency_key,
    }


def _pending_tool_calls_to_list(calls: tuple[PendingToolCall, ...]) -> list[Mapping[str, object]]:
    return [_pending_tool_call_to_mapping(call) for call in calls]


def _pending_tool_calls_from_value(value: object) -> tuple[PendingToolCall, ...]:
    if value is None:
        return ()
    parsed: object
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return ()
    else:
        parsed = value
    if not isinstance(parsed, list):
        return ()
    calls: list[PendingToolCall] = []
    for item in parsed:
        if not isinstance(item, Mapping):
            continue
        started_at = _parse_optional_datetime(item.get("started_at")) or datetime.now(timezone.utc)
        arguments_raw = item.get("arguments") or {}
        arguments = dict(arguments_raw) if isinstance(arguments_raw, Mapping) else {}
        calls.append(
            PendingToolCall(
                call_id=str(item.get("call_id") or ""),
                tool_name=str(item.get("tool_name") or ""),
                arguments=arguments,
                started_at=started_at,
                step_id=str(item.get("step_id") or ""),
                handle_id=(str(item.get("handle_id")) if item.get("handle_id") else None),
                status=str(item.get("status") or "dispatched"),
                idempotency_key=(
                    str(item.get("idempotency_key"))
                    if item.get("idempotency_key") is not None and str(item.get("idempotency_key")).strip()
                    else None
                ),
            )
        )
    return tuple(calls)


def _maybe_json_mapping(value: object) -> Mapping[str, object] | None:
    """Decode a JSON-encoded mapping stored in Loop.metadata.

    ``_json_metadata`` persists dict/list values as JSON strings so the
    sqlite text columns stay text. Reading them back therefore needs a
    JSON decode step. Any value that cannot be parsed into a mapping
    returns None so callers can fall back to defaults.
    """
    if isinstance(value, Mapping):
        return {str(k): v for k, v in value.items()}
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            parsed = json.loads(stripped)
        except (TypeError, ValueError):
            return None
        if isinstance(parsed, Mapping):
            return {str(k): v for k, v in parsed.items()}
    return None


def _active_evidence_refs_from_value(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (tuple, list)):
        return tuple(str(item) for item in value if str(item).strip())
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return ()
        try:
            parsed = json.loads(stripped)
        except (TypeError, ValueError):
            return ()
        if isinstance(parsed, list):
            return tuple(str(item) for item in parsed if str(item).strip())
    return ()


def migrate_loop_state_metadata(metadata: Mapping[str, object]) -> dict[str, object]:
    """Normalize Loop.metadata into schema v2 shape.

    v1 rows (pre-harness) only carried the legacy budget reason in
    ``waiting_reason``. v2 writers always emit ``schema_version=2`` and the
    new keys (``wait_condition``, ``pending_tool_calls``, ``retry_state``,
    ``partial_assistant``, ``context_bundle_id``, ``active_evidence_refs``,
    ``heartbeat_at``, ``crash_marker``). The return value is a plain
    dictionary suitable for ``LoopState`` construction (not for
    re-serialization).
    """
    data = dict(metadata)
    schema_version = int(data.get("schema_version") or 0)
    if schema_version >= _LOOP_STATE_SCHEMA_VERSION:
        return data
    legacy_reason = (str(data.get("waiting_reason") or "").strip()) or None
    if legacy_reason and "wait_condition" not in data:
        data["wait_condition"] = {
            "kind": "budget_exhausted",
            "payload": {"legacy_reason": legacy_reason},
            "auto_wake": False,
        }
    data.setdefault("pending_tool_calls", [])
    data.setdefault("partial_assistant", None)
    data.setdefault("context_bundle_id", None)
    data.setdefault("active_evidence_refs", [])
    data.setdefault("retry_state", None)
    data.setdefault("heartbeat_at", None)
    data.setdefault("crash_marker", None)
    data["schema_version"] = _LOOP_STATE_SCHEMA_VERSION
    return data


def _loop_metadata(run: LoopState) -> dict[str, str]:
    return _json_metadata(
        {
            "kind": "loop_checkpoint",
            "schema_version": _LOOP_STATE_SCHEMA_VERSION,
            "source_event_id": run.source_event_id,
            "prompt": run.prompt,
            "phase": run.phase,
            "step_count": run.step_count,
            "model_turn_count": run.model_turn_count,
            "tool_call_count": run.tool_call_count,
            "max_model_turns": run.max_model_turns,
            "max_wall_time_seconds": run.max_wall_time_seconds,
            "waiting_reason": run.waiting_reason,
            "continuation_prompt": run.continuation_prompt,
            "last_summary": run.last_summary,
            "wait_condition": _wait_condition_to_mapping(run.wait_condition),
            "pending_tool_calls": _pending_tool_calls_to_list(run.pending_tool_calls),
            "partial_assistant": run.partial_assistant,
            "context_bundle_id": run.context_bundle_id,
            "active_evidence_refs": list(run.active_evidence_refs),
            "retry_state": _retry_state_to_mapping(run.retry_state),
            "heartbeat_at": _iso_optional_datetime(run.heartbeat_at),
            "crash_marker": run.crash_marker,
        }
    )


def _loop_state_from_loop(loop: Loop) -> LoopState:
    metadata = migrate_loop_state_metadata(dict(loop.metadata))
    return LoopState(
        run_id=loop.loop_id,
        episode_id=loop.episode_id,
        source_event_id=str(metadata.get("source_event_id") or ""),
        prompt=str(metadata.get("prompt") or ""),
        status=loop.status,
        phase=str(metadata.get("phase") or "model"),
        step_count=int(metadata.get("step_count") or 0),
        model_turn_count=int(metadata.get("model_turn_count") or 0),
        tool_call_count=int(metadata.get("tool_call_count") or 0),
        max_model_turns=int(metadata.get("max_model_turns") or 0),
        max_wall_time_seconds=int(metadata.get("max_wall_time_seconds") or 0),
        created_at=loop.started_at,
        updated_at=loop.ended_at or loop.started_at,
        waiting_reason=(str(metadata.get("waiting_reason")) if metadata.get("waiting_reason") else None),
        continuation_prompt=(
            str(metadata.get("continuation_prompt")) if metadata.get("continuation_prompt") else None
        ),
        last_summary=(str(metadata.get("last_summary")) if metadata.get("last_summary") else None),
        schema_version=int(metadata.get("schema_version") or _LOOP_STATE_SCHEMA_VERSION),
        wait_condition=_wait_condition_from_mapping(metadata.get("wait_condition")),
        pending_tool_calls=_pending_tool_calls_from_value(metadata.get("pending_tool_calls")),
        partial_assistant=(
            str(metadata.get("partial_assistant")) if metadata.get("partial_assistant") else None
        ),
        context_bundle_id=(
            str(metadata.get("context_bundle_id")) if metadata.get("context_bundle_id") else None
        ),
        active_evidence_refs=_active_evidence_refs_from_value(metadata.get("active_evidence_refs")),
        retry_state=_retry_state_from_mapping(metadata.get("retry_state")),
        heartbeat_at=_parse_optional_datetime(metadata.get("heartbeat_at")),
        crash_marker=(str(metadata.get("crash_marker")) if metadata.get("crash_marker") else None),
    )


def upsert_loop_checkpoint(self, run: LoopState, *, verify: bool = True) -> None:
    episode = self.load_episode(run.episode_id)
    if episode is None:
        episode_state = self.load_episode_state(run.episode_id)
        if episode_state is None:
            raise KeyError(run.episode_id)
        self.upsert_episode_state(episode_state)
        episode = self.load_episode(run.episode_id)
    if episode is None:
        raise KeyError(run.episode_id)
    state = self.load_state(episode.state_id)
    if state is None:
        raise KeyError(episode.state_id)
    existing = self.load_loop(run.run_id)
    loop = Loop(
        loop_id=run.run_id,
        episode_id=episode.episode_id,
        state_id=state.state_id,
        personal_model_id=episode.personal_model_id,
        trigger_type="model_tool_checkpoint",
        status=run.status,
        started_at=run.created_at,
        ended_at=run.updated_at if run.status in {"completed", "failed", "cancelled"} else None,
        summary=run.last_summary or (existing.summary if existing is not None else ""),
        outcome=run.waiting_reason or (existing.outcome if existing is not None else ""),
        metadata=_loop_metadata(run),
    )
    self.upsert_loop(loop)
    if verify:
        reloaded = _verify_loop_checkpoint_roundtrip(self, run)
        if reloaded is None:
            raise RuntimeError(
                f"loop checkpoint verify failed: run {run.run_id} did not round-trip"
            )


def _verify_loop_checkpoint_roundtrip(self, run: LoopState) -> LoopState | None:
    """Load the checkpoint back and confirm the key fields survive.

    We do not compare every field for equality — timestamps may be
    normalized, optional values may collapse — but we do require that:
      * the run reloads,
      * status / phase / step counters match what we just wrote,
      * the v2 envelope (schema_version=2) was persisted,
      * any wait_condition kind the caller chose round-tripped.

    Returning None signals the caller that the write did not land
    correctly; the caller raises so the runtime can treat park as
    refused rather than assume durable persistence.
    """
    loop = self.load_loop(run.run_id)
    if loop is None:
        return None
    reloaded = _loop_state_from_loop(loop)
    if reloaded.schema_version < _LOOP_STATE_SCHEMA_VERSION:
        return None
    if reloaded.status != run.status:
        return None
    if reloaded.phase != run.phase:
        return None
    if reloaded.step_count != run.step_count:
        return None
    if reloaded.model_turn_count != run.model_turn_count:
        return None
    if reloaded.tool_call_count != run.tool_call_count:
        return None
    if (run.wait_condition is None) != (reloaded.wait_condition is None):
        return None
    if run.wait_condition is not None and reloaded.wait_condition is not None:
        if run.wait_condition.kind != reloaded.wait_condition.kind:
            return None
    return reloaded


def list_loop_checkpoints(
    self,
    *,
    statuses: tuple[str, ...] = ("active", "pending"),
    heartbeat_before: datetime | None = None,
    personal_model_id: str | None = None,
    state_id: str | None = None,
    limit: int | None = None,
) -> tuple[LoopState, ...]:
    """Return loop checkpoints, filtered for supervisor use.

    The supervisor scans for loops whose heartbeat is older than a
    staleness TTL to reclaim crashed runs. The resume path also needs
    to locate parked loops by state or personal model. Keep the broad
    heartbeat predicate in Python because it lives inside metadata, but
    push durable columns into the SQL query so checkpoint recovery does
    not scan unrelated Loop rows.
    """
    kept: list[LoopState] = []
    active_status_filter = set(str(status) for status in statuses if str(status).strip())
    status_filter = next(iter(active_status_filter)) if len(active_status_filter) == 1 else None
    for loop in self.list_loops(
        state_id=state_id,
        personal_model_id=personal_model_id,
        trigger_type="model_tool_checkpoint",
        status=status_filter,
    ):
        if loop.metadata.get("kind") != "loop_checkpoint":
            continue
        if active_status_filter and loop.status not in active_status_filter:
            continue
        if state_id is not None and loop.state_id != state_id:
            continue
        if personal_model_id is not None:
            if canonical_personal_model_id(loop.personal_model_id) != canonical_personal_model_id(
                personal_model_id
            ):
                continue
        run = _loop_state_from_loop(loop)
        if heartbeat_before is not None:
            hb = run.heartbeat_at
            if hb is None:
                # No heartbeat recorded yet; treat as stale so long-lived rows
                # from an older writer still become supervisor candidates.
                pass
            elif hb > heartbeat_before:
                continue
        kept.append(run)
    kept.sort(
        key=lambda item: (
            item.heartbeat_at or item.updated_at or item.created_at,
            item.run_id,
        )
    )
    if limit is not None and limit > 0:
        kept = kept[:limit]
    return tuple(kept)


def load_latest_open_loop_checkpoint(
    self,
    episode_id: str,
) -> LoopState | None:
    candidates = [
        loop
        for loop in self.list_loops(episode_id=episode_id)
        if loop.metadata.get("kind") == "loop_checkpoint" and loop.status in {"active", "pending"}
    ]
    if not candidates:
        return None
    latest = sorted(
        candidates,
        key=lambda loop: ((loop.ended_at or loop.started_at).isoformat(), loop.started_at.isoformat(), loop.loop_id),
        reverse=True,
    )[0]
    return _loop_state_from_loop(latest)


def append_loop_checkpoint_step(self, step: LoopStep) -> None:
    loop = self.load_loop(step.run_id)
    if loop is None:
        raise KeyError(step.run_id)
    phase = "acting" if step.kind == "tool" else "reasoning"
    self.upsert_step(
        Step(
            step_id=step.step_id,
            loop_id=loop.loop_id,
            episode_id=loop.episode_id,
            state_id=loop.state_id,
            personal_model_id=loop.personal_model_id,
            phase=phase,
            action=step.kind,
            status="completed",
            sequence=step.step_index,
            summary=step.title,
            outcome=step.outcome or "",
            payload_refs=(),
            metadata=_json_metadata(
                {
                    "checkpoint_kind": step.kind,
                    "content": step.content,
                    "tool_name": step.tool_name,
                }
            ),
            created_at=step.created_at,
        )
    )


def _step_to_loop_step(step: Step) -> LoopStep:
    metadata = dict(step.metadata)
    return LoopStep(
        step_id=step.step_id,
        run_id=step.loop_id,
        episode_id=step.episode_id,
        step_index=step.sequence,
        kind=metadata.get("checkpoint_kind", step.action),
        title=step.summary,
        content=metadata.get("content", step.summary),
        created_at=step.created_at,
        outcome=step.outcome or None,
        tool_name=metadata.get("tool_name") or None,
    )


def list_loop_checkpoint_steps(
    self,
    run_id: str,
    *,
    limit: int | None = None,
) -> tuple[LoopStep, ...]:
    steps = tuple(reversed(self.list_steps(loop_id=run_id)))
    if limit is not None:
        steps = steps[:limit]
    return tuple(_step_to_loop_step(step) for step in steps)
