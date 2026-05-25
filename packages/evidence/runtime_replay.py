"""Step replay parsing and projection helpers for evidence retrieval."""

from __future__ import annotations

import hashlib
import re

from packages.contracts.runtime import RecallEvidence, StepReplayRecord, StructuredTurnSlot
from packages.embeddings import EmbeddingPreloadEntry


_EVIDENCE_EMBED_TEXT_LIMIT = 8_192
_REPLAY_SLOT_NAMES = ("observation", "reasoning", "action", "outcome")
_REPLAY_SLOT_LABELS = {
    "observation": "observation",
    "reasoning": "reasoning",
    "action": "action",
    "outcome": "outcome",
}
_REPLAY_DETAIL_RANK = {
    "summary_only": 0,
    "episode_summary": 1,
    "structured_summary": 2,
    "structured": 3,
    "raw_turn": 4,
    "raw_trace": 5,
}
def _tuple_from_metadata(value: object) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if str(item))
    if value is None:
        return ()
    cleaned = str(value).strip()
    return (cleaned,) if cleaned else ()
def _record_search_text(record: RecallEvidence, *, structured_text: str = "") -> str:
    return "\n".join(part for part in (record.content, structured_text) if part)
def _embedding_text(value: str, *, max_chars: int = _EVIDENCE_EMBED_TEXT_LIMIT) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip()
def _record_embedding_text(record: RecallEvidence, *, structured_text: str | None = None) -> str:
    if structured_text is None:
        structured_turn = _structured_turn_from_record(record)
        structured_text = (
            _replay_text(structured_turn, selected_slots=_REPLAY_SLOT_NAMES)
            if structured_turn is not None
            else ""
        )
    search_text = _record_search_text(record, structured_text=structured_text) or record.content
    return _embedding_text(search_text)
def _evidence_cache_key(record: RecallEvidence, *, search_text: str) -> str:
    created_at = record.created_at.isoformat() if record.created_at is not None else ""
    digest = hashlib.sha256(search_text.encode("utf-8")).hexdigest()[:16]
    return f"{record.evidence_id}:{created_at}:{digest}"
def _evidence_preload_entry(record: RecallEvidence, *, structured_text: str = "") -> EmbeddingPreloadEntry:
    search_text = _record_embedding_text(record, structured_text=structured_text or None)
    return EmbeddingPreloadEntry(
        cache_key=_evidence_cache_key(record, search_text=search_text),
        text=search_text or record.content,
        metadata={
            "evidence_id": record.evidence_id,
            "evidence_kind": record.kind,
            "episode_id": record.episode_id,
        },
    )


def _structured_slot_from_metadata(value: object) -> StructuredTurnSlot:
    if not isinstance(value, dict):
        return StructuredTurnSlot()
    return StructuredTurnSlot(
        summary=str(value.get("summary", "")),
        detail=_tuple_from_metadata(value.get("detail")),
        compression=str(value.get("compression", "structured")),
        provenance=str(value.get("provenance", "")),
        source_refs=_tuple_from_metadata(value.get("source_refs")),
        linkage_refs=_tuple_from_metadata(value.get("linkage_refs")),
    )
def _structured_turn_from_record(record: RecallEvidence) -> StepReplayRecord | None:
    if record.kind != "structured_turn":
        return None
    payload = record.metadata.get("structured_turn")
    if not isinstance(payload, dict):
        return None
    return StepReplayRecord(
        turn_id=str(payload.get("turn_id", record.evidence_id)),
        episode_id=str(payload.get("episode_id", record.episode_id)),
        source=str(payload.get("source", "runtime")),
        observation=_structured_slot_from_metadata(payload.get("observation")),
        reasoning=_structured_slot_from_metadata(payload.get("reasoning")),
        action=_structured_slot_from_metadata(payload.get("action")),
        outcome=_structured_slot_from_metadata(payload.get("outcome")),
        personal_model_id=(
            str(payload.get("personal_model_id"))
            if payload.get("personal_model_id") is not None
            else None
        ),
        elephant_id=str(payload.get("elephant_id")) if payload.get("elephant_id") is not None else None,
        source_event_id=str(payload.get("source_event_id")) if payload.get("source_event_id") is not None else record.source_id,
        reasoning_availability=str(payload.get("reasoning_availability", "summary_only")),
        reasoning_provenance=str(payload.get("reasoning_provenance", "runtime.decision_summary")),
        compression_tier=str(payload.get("compression_tier", "raw_turn")),
        work_item_ids=_tuple_from_metadata(payload.get("work_item_ids") or record.work_item_ids),
        source_turn_ids=_tuple_from_metadata(payload.get("source_turn_ids")),
        correction_evidence_ids=_tuple_from_metadata(payload.get("correction_evidence_ids")),
        artifact_ids=_tuple_from_metadata(payload.get("artifact_ids")),
        created_at=record.created_at,
    )


def parse_step_replay_record(record: RecallEvidence) -> StepReplayRecord | None:
    """Parse Step replay metadata from a recall evidence record."""

    return _structured_turn_from_record(record)
def _normalize_target_slots(target_slots: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            slot.strip().lower()
            for slot in target_slots
            if slot.strip().lower() in _REPLAY_SLOT_NAMES
        )
    )



def _detail_rank(compression: str) -> int:
    return _REPLAY_DETAIL_RANK.get(compression.strip().lower(), _REPLAY_DETAIL_RANK["structured_summary"])



def _project_slot(
    slot: StructuredTurnSlot,
    *,
    max_compression: str,
) -> tuple[StructuredTurnSlot, bool]:
    allowed_rank = _detail_rank(max_compression)
    slot_rank = _detail_rank(slot.compression)
    if slot_rank <= allowed_rank:
        return slot, False
    return (
        StructuredTurnSlot(
            summary=slot.summary,
            detail=(),
            compression=max_compression,
            provenance=slot.provenance,
            source_refs=slot.source_refs,
            linkage_refs=slot.linkage_refs,
        ),
        True,
    )



def _selected_replay_slots(
    request: EvidenceRetrievalRequest,
    turn: StepReplayRecord | None,
) -> tuple[str, ...]:
    explicit = _normalize_target_slots(request.target_slots)
    if explicit:
        return explicit
    if turn is None or request.replay_mode == "off":
        return ()
    return tuple(
        slot_name
        for slot_name in _REPLAY_SLOT_NAMES
        if getattr(turn, slot_name).summary or getattr(turn, slot_name).detail
    )



def _project_replay_record(
    turn: StepReplayRecord,
    *,
    selected_slots: tuple[str, ...],
    max_compression: str,
) -> tuple[StepReplayRecord, tuple[str, ...]]:
    slots = set(selected_slots)
    degraded_slots: list[str] = []

    def project(slot_name: str) -> StructuredTurnSlot:
        slot = getattr(turn, slot_name)
        if slot_name not in slots:
            return StructuredTurnSlot()
        projected, degraded = _project_slot(slot, max_compression=max_compression)
        if degraded:
            degraded_slots.append(slot_name)
        return projected

    return (
        StepReplayRecord(
            turn_id=turn.turn_id,
            episode_id=turn.episode_id,
            source=turn.source,
            observation=project("observation"),
            reasoning=project("reasoning"),
            action=project("action"),
            outcome=project("outcome"),
            personal_model_id=turn.personal_model_id,
            elephant_id=turn.elephant_id,
            source_event_id=turn.source_event_id,
            reasoning_availability=turn.reasoning_availability,
            reasoning_provenance=turn.reasoning_provenance,
            compression_tier=turn.compression_tier,
            work_item_ids=turn.work_item_ids,
            source_turn_ids=turn.source_turn_ids,
            correction_evidence_ids=turn.correction_evidence_ids,
            artifact_ids=turn.artifact_ids,
            created_at=turn.created_at,
        ),
        tuple(dict.fromkeys(degraded_slots)),
    )



def _slot_text(slot_name: str, slot: StructuredTurnSlot) -> tuple[str, ...]:
    label = _REPLAY_SLOT_LABELS.get(slot_name, slot_name)
    lines: list[str] = []
    if slot.summary:
        lines.append(f"{label}: {slot.summary}")
    lines.extend(slot.detail)
    return tuple(lines)



def _replay_text(turn: StepReplayRecord, *, selected_slots: tuple[str, ...]) -> str:
    lines: list[str] = []
    for slot_name in selected_slots:
        lines.extend(_slot_text(slot_name, getattr(turn, slot_name)))
    return "\n".join(line for line in lines if line)



def _replay_summary(turn: StepReplayRecord, *, selected_slots: tuple[str, ...]) -> str:
    slot_summary = ", ".join(selected_slots) or "structured evidence"
    work_summary = ", ".join(turn.work_item_ids[:2]) or "the active thread"
    if turn.compression_tier == "episode_summary" or len(turn.source_turn_ids) > 1:
        boundary = f"episode replay across {len(turn.source_turn_ids) or 1} turn(s)"
    else:
        boundary = "turn replay"
    selected_compressions = tuple(
        dict.fromkeys(
            getattr(turn, slot_name).compression
            for slot_name in selected_slots
            if getattr(turn, slot_name).summary or getattr(turn, slot_name).detail
        )
    )
    compression = ",".join(selected_compressions) if selected_compressions else turn.compression_tier
    return (
        f"{boundary} for {work_summary}; slots={slot_summary}; "
        f"compression={compression}; reasoning={turn.reasoning_availability}"
    )


