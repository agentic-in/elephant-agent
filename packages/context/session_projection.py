"""Shared session transcript projection for all runtime surfaces."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from packages.contracts.layers import Episode
from packages.contracts.runtime import (
    ContextBundle,
    EventEnvelope,
    ExecutionResult,
    PromptEnvelope,
    PromptMessage,
)
from packages.context.projection import (
    estimate_projection_tokens,
    projection_result_with_estimated_tokens,
)
from packages.context.projection_types import ContextProjectionCompactionResult

SESSION_CONTEXT_EPOCH_SCHEMA_VERSION = "session_context_epoch/v1"
SESSION_CONTEXT_EPOCH_LAYER = "session_context_epoch"


@dataclass(frozen=True, slots=True)
class SkillDisclosureRecord:
    skill_id: str
    display_name: str = ""
    reason: str = ""
    source: str = "runtime-overlay"


@dataclass(frozen=True, slots=True)
class FrozenSkillIndexEntry:
    skill_id: str
    display_name: str = ""
    category: str = ""
    source_id: str = ""
    storage_tier: str = ""
    slash_command: str = ""
    index_id: str = ""
    source_topic: str = ""
    reason: str = ""


@dataclass(frozen=True, slots=True)
class SessionContextEpoch:
    session_id: str
    frozen: bool = False
    frozen_prefix: str = ""
    session_snapshot: str = ""
    base_loop_context: str = ""
    thread_focus: str = ""
    frozen_skill_count: int = 0
    frozen_tool_count: int = 0
    frozen_skill_index: tuple[FrozenSkillIndexEntry, ...] = ()
    frozen_skill_ids: tuple[str, ...] = ()
    frozen_tool_ids: tuple[str, ...] = ()
    frozen_skill_disclosures: tuple[SkillDisclosureRecord, ...] = ()
    latest_skill_disclosures: tuple[SkillDisclosureRecord, ...] = ()
    compacted_history_summary: str = ""
    compaction_count: int = 0
    compacted_history_count: int = 0
    context_projection_tokens: int = 0
    context_projection_limit: int = 0
    history_messages: tuple[PromptMessage, ...] = ()
    frozen_at: datetime | None = None


def prompt_message_payload(message: PromptMessage) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "role": message.role,
        "content": message.content,
    }
    if message.name:
        payload["name"] = message.name
    if message.tool_call_id:
        payload["tool_call_id"] = message.tool_call_id
    if message.tool_name:
        payload["tool_name"] = message.tool_name
    if message.tool_calls:
        payload["tool_calls"] = [dict(call) for call in message.tool_calls]
    if message.metadata:
        payload["metadata"] = dict(message.metadata)
    return payload


def prompt_messages_tuple(value: object) -> tuple[PromptMessage, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    messages: list[PromptMessage] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        tool_calls_raw = item.get("tool_calls")
        tool_calls = (
            tuple(dict(call) for call in tool_calls_raw if isinstance(call, Mapping))
            if isinstance(tool_calls_raw, (list, tuple))
            else ()
        )
        metadata_raw = item.get("metadata")
        messages.append(
            PromptMessage(
                role=str(item.get("role") or ""),
                content=str(item.get("content") or ""),
                name=str(item.get("name") or ""),
                tool_call_id=str(item.get("tool_call_id") or ""),
                tool_name=str(item.get("tool_name") or ""),
                tool_calls=tool_calls,
                metadata={str(k): str(v) for k, v in dict(metadata_raw).items()}
                if isinstance(metadata_raw, Mapping)
                else {},
            )
        )
    return tuple(message for message in messages if message.role)


def restore_session_context_epoch(
    payload: Mapping[str, Any] | None, *, session_id: str | None = None
) -> SessionContextEpoch | None:
    if not isinstance(payload, Mapping):
        return None
    if "session_context_epoch" in payload:
        if session_id is not None:
            session = payload.get("session")
            resolved = (
                str(session.get("episode_id") or session.get("session_id") or "").strip()
                if isinstance(session, Mapping)
                else ""
            )
            if resolved and resolved != session_id:
                return None
        payload = payload.get("session_context_epoch")  # type: ignore[assignment]
    if not isinstance(payload, Mapping):
        return None
    resolved_session_id = str(payload.get("episode_id") or payload.get("session_id") or "").strip()
    if not resolved_session_id or (session_id is not None and resolved_session_id != session_id):
        return None
    return SessionContextEpoch(
        session_id=resolved_session_id,
        frozen=bool(payload.get("frozen", False)),
        frozen_prefix=str(payload.get("frozen_prefix") or ""),
        session_snapshot=str(payload.get("session_snapshot") or ""),
        base_loop_context=_base_loop_context_refs(payload.get("base_loop_context")),
        thread_focus=str(payload.get("thread_focus") or ""),
        frozen_skill_count=int(payload.get("frozen_skill_count") or 0),
        frozen_tool_count=int(payload.get("frozen_tool_count") or 0),
        frozen_skill_index=_frozen_skill_index_tuple(payload.get("frozen_skill_index")),
        frozen_skill_ids=_as_str_tuple(payload.get("frozen_skill_ids")),
        frozen_tool_ids=_as_str_tuple(payload.get("frozen_tool_ids")),
        frozen_skill_disclosures=_skill_disclosure_tuple(payload.get("frozen_skill_disclosures")),
        latest_skill_disclosures=_skill_disclosure_tuple(payload.get("latest_skill_disclosures")),
        compacted_history_summary=str(payload.get("compacted_history_summary") or ""),
        compaction_count=int(payload.get("compaction_count") or 0),
        compacted_history_count=int(payload.get("compacted_history_count") or 0),
        context_projection_tokens=int(payload.get("context_projection_tokens") or 0),
        context_projection_limit=int(payload.get("context_projection_limit") or 0),
        history_messages=prompt_messages_tuple(payload.get("history_messages")),
        frozen_at=_optional_datetime(payload.get("frozen_at")),
    )


def session_context_epoch_payload(epoch: SessionContextEpoch) -> dict[str, Any]:
    return {
        "episode_id": epoch.session_id,
        "session_id": epoch.session_id,
        "frozen": epoch.frozen,
        "frozen_prefix": epoch.frozen_prefix,
        "session_snapshot": epoch.session_snapshot,
        "base_loop_context": epoch.base_loop_context,
        "thread_focus": epoch.thread_focus,
        "frozen_skill_count": epoch.frozen_skill_count,
        "frozen_tool_count": epoch.frozen_tool_count,
        "frozen_skill_index": [_frozen_skill_index_payload(entry) for entry in epoch.frozen_skill_index],
        "frozen_skill_ids": list(epoch.frozen_skill_ids),
        "frozen_tool_ids": list(epoch.frozen_tool_ids),
        "frozen_skill_disclosures": [_skill_disclosure_payload(record) for record in epoch.frozen_skill_disclosures],
        "latest_skill_disclosures": [_skill_disclosure_payload(record) for record in epoch.latest_skill_disclosures],
        "compacted_history_summary": epoch.compacted_history_summary,
        "compaction_count": epoch.compaction_count,
        "compacted_history_count": epoch.compacted_history_count,
        "context_projection_tokens": epoch.context_projection_tokens,
        "context_projection_limit": epoch.context_projection_limit,
        "history_messages": [prompt_message_payload(message) for message in epoch.history_messages],
        "frozen_at": _iso(epoch.frozen_at) if epoch.frozen_at is not None else None,
    }


def next_session_context_epoch(
    existing: SessionContextEpoch | None,
    *,
    session: Episode,
    event: EventEnvelope | None,
    execution: ExecutionResult | None,
    context: ContextBundle | None,
    turn_messages: tuple[PromptMessage, ...],
    thread_focus: str = "",
    frozen_skill_index: tuple[FrozenSkillIndexEntry, ...] = (),
    frozen_tool_count: int = 0,
    frozen_tool_ids: tuple[str, ...] = (),
    skill_disclosures: tuple[SkillDisclosureRecord, ...] = (),
    fallback_history_messages: tuple[PromptMessage, ...] = (),
    now: datetime | None = None,
) -> SessionContextEpoch:
    epoch = (
        existing
        if existing is not None and existing.session_id == session.episode_id
        else SessionContextEpoch(session_id=session.episode_id)
    )
    is_user_turn = event is not None and _event_is_user_turn(event)
    episode_open_refresh = (
        epoch.frozen and context is not None and event is None and execution is None and not epoch.history_messages
    )
    if context is not None:
        envelope = context.prompt_envelope
        refresh_frozen = (
            not epoch.frozen or episode_open_refresh
            # No longer detecting prefix changes per-turn and refreshing; the caller refreshes explicitly during compress
        )
        if refresh_frozen:
            epoch = replace(
                epoch,
                frozen=True,
                frozen_prefix=envelope.frozen_prefix,
                session_snapshot=envelope.session_snapshot,
                base_loop_context=_base_loop_context_refs(envelope.loop_context),
                thread_focus=thread_focus,
                frozen_skill_count=len(frozen_skill_index),
                frozen_tool_count=frozen_tool_count,
                frozen_skill_index=frozen_skill_index,
                frozen_skill_ids=tuple(entry.skill_id for entry in frozen_skill_index),
                frozen_tool_ids=frozen_tool_ids,
                frozen_skill_disclosures=skill_disclosures,
                latest_skill_disclosures=skill_disclosures,
                frozen_at=now or _utc_now(),
            )
        elif is_user_turn:
            epoch = replace(epoch, latest_skill_disclosures=skill_disclosures)
    elif is_user_turn:
        epoch = replace(epoch, latest_skill_disclosures=skill_disclosures)
    now_value = now or _utc_now()
    raw_history_messages = tuple(message for message in turn_messages if message.content.strip() or message.tool_calls)
    history_messages = _annotate_history_messages(
        _with_fallback_user_anchor(raw_history_messages, fallback_history_messages) or fallback_history_messages,
        event=event,
        now=now_value,
    )
    if is_user_turn and history_messages:
        if _event_is_im(event) and _history_idle_gap_exceeded(epoch.history_messages, now_value):
            epoch = replace(epoch, history_messages=(), compacted_history_summary="")
        epoch = replace(epoch, history_messages=(*epoch.history_messages, *history_messages))
    return epoch


def apply_session_context_epoch(bundle: ContextBundle, epoch: SessionContextEpoch | None) -> ContextBundle:
    if epoch is None or not epoch.frozen:
        return bundle
    return replace(
        bundle,
        prompt_envelope=PromptEnvelope(
            frozen_prefix=epoch.frozen_prefix,
            session_snapshot="",
            loop_context=epoch.base_loop_context.strip(),
            messages=epoch.history_messages,
        ),
    )


def compact_session_context_epoch(
    epoch: SessionContextEpoch,
    *,
    total_tokens: int,
    reason: str = "manual",
    force: bool = False,
    summary_hook: Any | None = None,
    relevance_scorer: Any | None = None,
    summary_text: str | None = None,
    tail_messages: tuple[PromptMessage, ...] | None = None,
) -> tuple[SessionContextEpoch, ContextProjectionCompactionResult]:
    """Compact the epoch's history messages.

    When *summary_text* and *tail_messages* are provided (the new reflect-based
    compress path), they are used directly — no legacy compactor is invoked.
    The old *summary_hook* / *relevance_scorer* parameters are accepted for
    backward compatibility but ignored when the new path is active.
    """
    total_tokens = max(1024, int(total_tokens or 0))
    before_tokens = estimate_epoch_prompt_tokens(
        epoch,
        history_messages=epoch.history_messages,
        compacted_summary=epoch.compacted_history_summary,
    )

    if summary_text is not None and tail_messages is not None:
        # New reflect-based compress path
        after_tokens = estimate_epoch_prompt_tokens(
            epoch,
            history_messages=tail_messages,
            compacted_summary=summary_text,
        )
        result = ContextProjectionCompactionResult(
            compacted=True,
            reason=reason,
            before_tokens=before_tokens,
            after_tokens=after_tokens,
            before_line_count=len(epoch.history_messages),
            after_line_count=len(tail_messages),
            summary=summary_text,
            protected_tail_count=len(tail_messages),
            compacted_line_count=max(0, len(epoch.history_messages) - len(tail_messages)),
        )
        updated = replace(
            epoch,
            compacted_history_summary=summary_text,
            compaction_count=epoch.compaction_count + 1,
            compacted_history_count=epoch.compacted_history_count + result.compacted_line_count,
            context_projection_tokens=after_tokens,
            context_projection_limit=total_tokens,
            history_messages=tail_messages,
        )
        return updated, result

    # Legacy fallback — kept for safety-net overflow retries
    from packages.context.projection import (
        DeterministicProjectionSummaryHook,
        SessionProjectionCompactor,
    )

    projection = SessionProjectionCompactor(
        summary_hook=summary_hook or DeterministicProjectionSummaryHook(),
        relevance_scorer=relevance_scorer,
    ).compact_messages(
        messages=epoch.history_messages,
        thread_focus=epoch.thread_focus,
        previous_summary=epoch.compacted_history_summary,
        total_tokens=total_tokens,
        reason=reason,
        force=force,
    )
    after_tokens = estimate_epoch_prompt_tokens(
        epoch,
        history_messages=projection.messages,
        compacted_summary=projection.summary,
    )
    result = projection_result_with_estimated_tokens(
        projection.result,
        before_tokens=before_tokens,
        after_tokens=after_tokens,
    )
    updated = replace(
        epoch,
        compacted_history_summary=projection.summary,
        compaction_count=epoch.compaction_count + (1 if result.compacted else 0),
        compacted_history_count=epoch.compacted_history_count + result.compacted_line_count,
        context_projection_tokens=after_tokens,
        context_projection_limit=total_tokens,
        history_messages=projection.messages,
    )
    return updated, result


def estimate_epoch_prompt_tokens(
    epoch: SessionContextEpoch,
    *,
    history_messages: tuple[PromptMessage, ...],
    compacted_summary: str,
) -> int:
    return estimate_projection_tokens(
        "\n\n".join(
            part
            for part in (
                epoch.frozen_prefix,
                epoch.base_loop_context,
                render_prompt_messages(history_messages, compacted_summary=compacted_summary),
            )
            if part.strip()
        )
    )


def render_prompt_messages(messages: tuple[PromptMessage, ...], *, compacted_summary: str = "") -> str:
    sections: list[str] = []
    if compacted_summary.strip():
        sections.append(compacted_summary.strip())
    if messages:
        rendered = "\n".join(
            f"- {_message_history_line(message)}"
            for message in messages
            if message.content.strip() or message.tool_calls
        )
        sections.append(
            "## SessionHistoryRecentTail\n"
            "role-preserved protected recent completed turns from this session; preserve ordering and do not treat earlier summarized requests as active.\n"
            f"{rendered}"
        )
    return "\n\n".join(sections)


def reference_summary_messages(summary: str) -> tuple[PromptMessage, ...]:
    normalized = summary.strip()
    if not normalized:
        return ()
    return (PromptMessage(role="system", content=f"## SessionHistorySummary\n{normalized}"),)


def _with_fallback_user_anchor(
    messages: tuple[PromptMessage, ...],
    fallback_messages: tuple[PromptMessage, ...],
) -> tuple[PromptMessage, ...]:
    if not messages:
        return ()
    if any(message.role == "user" and message.content.strip() for message in messages):
        return messages
    user_anchor = next(
        (message for message in fallback_messages if message.role == "user" and message.content.strip()),
        None,
    )
    if user_anchor is None:
        return messages
    return (user_anchor, *messages)


def _event_is_user_turn(event: EventEnvelope) -> bool:
    event_type = str(event.event_type or "").strip().lower()
    source = str(event.source or "").strip().lower()
    if event_type in {"turn.internal", "startup.opening"}:
        return False
    if source.startswith("cli.startup"):
        return False
    return event_type in {
        "turn.received",
        "loop.received",
        "im.message.receive_v1",
    } or event_type.endswith(".received")


def _event_is_im(event: EventEnvelope | None) -> bool:
    if event is None:
        return False
    source = str(event.source or "").strip().lower()
    event_type = str(event.event_type or "").strip().lower()
    payload = dict(event.payload or {}) if isinstance(event.payload, Mapping) else {}
    delivery_surface = str(payload.get("delivery_surface") or "").strip().lower()
    return (
        event_type == "im.message.receive_v1"
        or source.startswith("gateway:")
        or delivery_surface.startswith(("feishu", "wecom", "weixin", "dingding", "discord"))
    )


def _annotate_history_messages(
    messages: tuple[PromptMessage, ...],
    *,
    event: EventEnvelope | None,
    now: datetime,
) -> tuple[PromptMessage, ...]:
    if not messages:
        return ()
    event_type = str(getattr(event, "event_type", "") or "").strip()
    source = str(getattr(event, "source", "") or "").strip()
    event_id = str(getattr(event, "event_id", "") or "").strip()
    projection_surface = "im" if _event_is_im(event) else "session"
    metadata = {
        "created_at": _iso(now),
        "event_type": event_type,
        "source": source,
        "event_id": event_id,
        "projection_surface": projection_surface,
    }
    return tuple(replace(message, metadata={**metadata, **dict(message.metadata or {})}) for message in messages)


def _history_idle_gap_exceeded(
    messages: tuple[PromptMessage, ...],
    now: datetime,
    *,
    idle_gap_seconds: int = 1800,
) -> bool:
    previous = None
    for message in reversed(messages):
        value = str((message.metadata or {}).get("created_at") or "").strip()
        if not value:
            continue
        try:
            previous = datetime.fromisoformat(value)
        except ValueError:
            continue
        break
    if previous is None:
        return False
    return max(0.0, (now - previous).total_seconds()) > idle_gap_seconds


def _message_history_line(message: PromptMessage) -> str:
    role = str(message.role or "").strip().lower()
    if role == "tool":
        tool_name = message.tool_name.strip() or "unknown"
        return f"tool: {tool_name} summary: {message.content.strip()}"
    if role == "assistant":
        return f"elephant: {message.content.strip()}"
    if role == "user":
        return f"user: {message.content.strip()}"
    return f"{role}: {message.content.strip()}"


def _base_loop_context_refs(value: object) -> str:
    if isinstance(value, (tuple, list)):
        raw = "\n".join(str(item) for item in value if str(item).strip())
    else:
        raw = str(value or "")
    lines = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if "source_ref" in lower or "selected skill" in lower or "capability" in lower:
            lines.append(stripped)
    return "\n".join(lines)


def _as_str_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value if str(item).strip())
    return (str(value),) if str(value).strip() else ()


def _optional_datetime(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _skill_disclosure_tuple(value: object) -> tuple[SkillDisclosureRecord, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    records = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        records.append(
            SkillDisclosureRecord(
                skill_id=str(item.get("skill_id") or ""),
                display_name=str(item.get("display_name") or ""),
                reason=str(item.get("reason") or ""),
                source=str(item.get("source") or "runtime-overlay"),
            )
        )
    return tuple(record for record in records if record.skill_id)


def _skill_disclosure_payload(record: SkillDisclosureRecord) -> dict[str, str]:
    return {
        "skill_id": record.skill_id,
        "display_name": record.display_name,
        "reason": record.reason,
        "source": record.source,
    }


def _frozen_skill_index_tuple(value: object) -> tuple[FrozenSkillIndexEntry, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    entries = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        entries.append(
            FrozenSkillIndexEntry(
                skill_id=str(item.get("skill_id") or ""),
                display_name=str(item.get("display_name") or ""),
                category=str(item.get("category") or ""),
                source_id=str(item.get("source_id") or ""),
                storage_tier=str(item.get("storage_tier") or ""),
                slash_command=str(item.get("slash_command") or ""),
                index_id=str(item.get("index_id") or ""),
                source_topic=str(item.get("source_topic") or ""),
                reason=str(item.get("reason") or ""),
            )
        )
    return tuple(entry for entry in entries if entry.skill_id)


def _frozen_skill_index_payload(entry: FrozenSkillIndexEntry) -> dict[str, str]:
    return {
        "skill_id": entry.skill_id,
        "display_name": entry.display_name,
        "category": entry.category,
        "source_id": entry.source_id,
        "storage_tier": entry.storage_tier,
        "slash_command": entry.slash_command,
        "index_id": entry.index_id,
        "source_topic": entry.source_topic,
        "reason": entry.reason,
    }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "FrozenSkillIndexEntry",
    "SESSION_CONTEXT_EPOCH_SCHEMA_VERSION",
    "SessionContextEpoch",
    "SkillDisclosureRecord",
    "apply_session_context_epoch",
    "compact_session_context_epoch",
    "estimate_epoch_prompt_tokens",
    "next_session_context_epoch",
    "prompt_message_payload",
    "prompt_messages_tuple",
    "reference_summary_messages",
    "render_prompt_messages",
    "restore_session_context_epoch",
    "session_context_epoch_payload",
]
