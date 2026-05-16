"""Adapters for original LoCoMo and LoCoMo-Refined datasets."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from packages.evals.contracts import (
    EvalConversation,
    EvalDataset,
    EvalMessage,
    EvalQuestion,
    EvalSession,
)


def load_locomo_dataset(
    *,
    dataset: str,
    path: str | Path,
    limit_conversations: int | None = None,
    limit_questions: int | None = None,
) -> EvalDataset:
    kind = _normalize_dataset_kind(dataset)
    source_path = Path(path)
    if kind == "locomo_refined":
        return _load_refined(
            source_path,
            limit_conversations=limit_conversations,
            limit_questions=limit_questions,
        )
    return _load_original(
        source_path,
        dataset_id="locomo",
        limit_conversations=limit_conversations,
        limit_questions=limit_questions,
    )


def _normalize_dataset_kind(value: str) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    if text in {"refined", "locomo_refined", "locomo_refined_public"}:
        return "locomo_refined"
    if text in {"original", "locomo", "locomo_original"}:
        return "locomo"
    raise ValueError(f"unsupported LoCoMo dataset kind: {value}")


def _load_original(
    path: Path,
    *,
    dataset_id: str,
    limit_conversations: int | None,
    limit_questions: int | None,
) -> EvalDataset:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"expected top-level LoCoMo array: {path}")
    records = payload[:limit_conversations] if limit_conversations is not None else payload
    conversations: list[EvalConversation] = []
    remaining_questions = limit_questions
    for index, record in enumerate(records):
        conversation = _convert_original_record(
            record,
            conversation_index=index,
            question_limit=remaining_questions,
            source_label=dataset_id,
        )
        conversations.append(conversation)
        if remaining_questions is not None:
            remaining_questions = max(0, remaining_questions - len(conversation.questions))
            if remaining_questions <= 0:
                break
    return EvalDataset(
        dataset_id=dataset_id,
        source_path=str(path),
        conversations=tuple(conversations),
        metadata={"format": "locomo10.json"},
    )


def _load_refined(
    path: Path,
    *,
    limit_conversations: int | None,
    limit_questions: int | None,
) -> EvalDataset:
    public_dir = _resolve_refined_public_dir(path)
    conversations_path = public_dir / "conversations.jsonl"
    questions_path = public_dir / "questions.jsonl"
    if not conversations_path.exists() or not questions_path.exists():
        raise FileNotFoundError(f"missing LoCoMo-Refined public files under {public_dir}")
    raw_conversations = _read_jsonl(conversations_path)
    raw_questions = _read_jsonl(questions_path)
    raw_records_by_id = _load_refined_raw_records(public_dir)
    if limit_conversations is not None:
        allowed_ids = {
            str(item.get("sample_id") or "")
            for item in raw_conversations[:limit_conversations]
        }
        raw_conversations = [item for item in raw_conversations if str(item.get("sample_id") or "") in allowed_ids]
        raw_questions = [item for item in raw_questions if str(item.get("sample_id") or "") in allowed_ids]
    if limit_questions is not None:
        raw_questions = raw_questions[:limit_questions]
        allowed_ids = {str(item.get("sample_id") or "") for item in raw_questions}
        raw_conversations = [item for item in raw_conversations if str(item.get("sample_id") or "") in allowed_ids]
    questions_by_sample: dict[str, list[EvalQuestion]] = {}
    for item in raw_questions:
        question = _refined_question(item)
        questions_by_sample.setdefault(question.conversation_id, []).append(question)
    conversations = tuple(
        _refined_conversation(
            item,
            questions=tuple(questions_by_sample.get(str(item.get("sample_id") or ""), ())),
            raw_record=raw_records_by_id.get(str(item.get("sample_id") or "")),
        )
        for item in raw_conversations
    )
    return EvalDataset(
        dataset_id="locomo_refined",
        source_path=str(public_dir),
        conversations=conversations,
        metadata={"format": "public-jsonl"},
    )


def _resolve_refined_public_dir(path: Path) -> Path:
    if path.is_file():
        return path.parent
    if (path / "conversations.jsonl").exists() and (path / "questions.jsonl").exists():
        return path
    public_dir = path / "data" / "public"
    if public_dir.exists():
        return public_dir
    return path


def _load_refined_raw_records(public_dir: Path) -> dict[str, dict[str, Any]]:
    raw_path = public_dir.parent / "raw" / "locomo_refined.json"
    if not raw_path.exists():
        return {}
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return {}
    return {
        str(item.get("sample_id") or ""): item
        for item in payload
        if isinstance(item, dict) and str(item.get("sample_id") or "").strip()
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise json.JSONDecodeError(
                f"{exc.msg} while parsing {path} line {line_number}",
                exc.doc,
                exc.pos,
            ) from exc
        if isinstance(item, dict):
            out.append(item)
    return out


def _limited_items(items: list[Any], limit: int | None) -> list[Any]:
    if limit is None:
        return items
    return items[: max(0, limit)]


def _convert_original_record(
    record: dict[str, Any],
    *,
    conversation_index: int,
    question_limit: int | None,
    source_label: str = "locomo_original",
) -> EvalConversation:
    conversation = dict(record.get("conversation") or {})
    conversation_id = str(record.get("sample_id") or f"conversation-{conversation_index:04d}")
    speaker_a = str(conversation.get("speaker_a") or "")
    speaker_b = str(conversation.get("speaker_b") or "")
    sessions = _original_sessions(
        conversation,
        conversation_id=conversation_id,
        speaker_a=speaker_a,
        speaker_b=speaker_b,
        raw_record=record,
    )
    questions = tuple(
        _original_question(
            item,
            conversation_id=conversation_id,
            conversation_index=conversation_index,
            question_index=question_index,
        )
        for question_index, item in enumerate(_limited_items(record.get("qa") or [], question_limit))
        if isinstance(item, dict)
    )
    return EvalConversation(
        conversation_id=conversation_id,
        conversation_index=conversation_index,
        speaker_a=speaker_a,
        speaker_b=speaker_b,
        sessions=tuple(sessions),
        questions=questions,
        metadata={"source": source_label},
    )


def _original_sessions(
    conversation: dict[str, Any],
    *,
    conversation_id: str,
    speaker_a: str,
    speaker_b: str,
    raw_record: dict[str, Any] | None = None,
) -> tuple[EvalSession, ...]:
    sessions: list[EvalSession] = []
    session_index = 1
    while f"session_{session_index}" in conversation:
        raw_messages = conversation.get(f"session_{session_index}") or []
        date_time = str(conversation.get(f"session_{session_index}_date_time") or "")
        messages = tuple(
            _message_from_raw(
                item,
                conversation_id=conversation_id,
                session_index=session_index,
                fallback_index=message_index,
                speaker_a=speaker_a,
                speaker_b=speaker_b,
                date_time=date_time,
            )
            for message_index, item in enumerate(raw_messages, start=1)
            if isinstance(item, dict) and str(item.get("text") or "").strip()
        )
        sessions.append(
            EvalSession(
                session_id=f"{conversation_id}:session:{session_index}",
                session_index=session_index,
                date_time=date_time,
                messages=messages,
                metadata=_session_memory_metadata(raw_record, session_index=session_index),
            )
        )
        session_index += 1
    return tuple(sessions)


def _message_from_raw(
    raw: dict[str, Any],
    *,
    conversation_id: str,
    session_index: int,
    fallback_index: int,
    speaker_a: str,
    speaker_b: str,
    date_time: str,
) -> EvalMessage:
    message_id = str(raw.get("dia_id") or f"D{session_index}:{fallback_index}")
    images = _normalize_images(raw.get("images", raw.get("img_url")))
    speaker = str(raw.get("speaker") or "")
    return EvalMessage(
        message_id=message_id,
        session_index=session_index,
        message_index=_message_index(message_id) or fallback_index,
        speaker=speaker,
        role=_role_for_speaker(speaker, speaker_a=speaker_a, speaker_b=speaker_b),
        text=str(raw.get("text") or "").strip(),
        images=images,
        image_caption=str(raw.get("blip_caption") or "").strip(),
        image_query=str(raw.get("query") or "").strip(),
        metadata={"conversation_id": conversation_id, "session_date_time": date_time},
    )


def _original_question(
    item: dict[str, Any],
    *,
    conversation_id: str,
    conversation_index: int,
    question_index: int,
) -> EvalQuestion:
    answers = _answers_tuple(item.get("answer"))
    return EvalQuestion(
        question_id=f"{conversation_id}#q{question_index:04d}",
        conversation_id=conversation_id,
        question=str(item.get("question") or "").strip(),
        answers=answers,
        category=str(item.get("category") or ""),
        evidence_ids=tuple(str(value) for value in item.get("evidence") or () if str(value).strip()),
        is_multimodal=bool(item.get("is_multi_modality")),
        metadata={"conversation_idx": str(conversation_index), "qa_index": str(question_index)},
    )


def _refined_conversation(
    item: dict[str, Any],
    *,
    questions: tuple[EvalQuestion, ...],
    raw_record: dict[str, Any] | None = None,
) -> EvalConversation:
    conversation_id = str(item.get("sample_id") or f"conversation-{item.get('conversation_idx', 0)}")
    speaker_a = str(item.get("speaker_a") or "")
    speaker_b = str(item.get("speaker_b") or "")
    sessions = []
    for raw_session in item.get("sessions") or []:
        if not isinstance(raw_session, dict):
            continue
        session_index = int(raw_session.get("session_index") or len(sessions) + 1)
        date_time = str(raw_session.get("date_time") or "")
        messages = tuple(
            _message_from_raw(
                raw_message,
                conversation_id=conversation_id,
                session_index=session_index,
                fallback_index=message_index,
                speaker_a=speaker_a,
                speaker_b=speaker_b,
                date_time=date_time,
            )
            for message_index, raw_message in enumerate(raw_session.get("messages") or (), start=1)
            if isinstance(raw_message, dict) and str(raw_message.get("text") or "").strip()
        )
        sessions.append(
            EvalSession(
                session_id=f"{conversation_id}:session:{session_index}",
                session_index=session_index,
                date_time=date_time,
                messages=messages,
                metadata=_session_memory_metadata(raw_record, session_index=session_index),
            )
        )
    return EvalConversation(
        conversation_id=conversation_id,
        conversation_index=int(item.get("conversation_idx") or 0),
        speaker_a=speaker_a,
        speaker_b=speaker_b,
        sessions=tuple(sessions),
        questions=questions,
        metadata={"source": "locomo_refined"},
    )


def _session_memory_metadata(raw_record: dict[str, Any] | None, *, session_index: int) -> dict[str, str]:
    if not raw_record:
        return {}
    metadata: dict[str, str] = {}
    summary = (raw_record.get("session_summary") or {}).get(f"session_{session_index}_summary")
    if isinstance(summary, str) and summary.strip():
        metadata["session_summary"] = summary.strip()
    observation = (raw_record.get("observation") or {}).get(f"session_{session_index}_observation")
    normalized_observations = _normalize_observations(observation)
    if normalized_observations:
        metadata["observations_json"] = json.dumps(normalized_observations, ensure_ascii=False)
    event_summary = (raw_record.get("event_summary") or {}).get(f"events_session_{session_index}")
    normalized_events = _normalize_events(event_summary)
    if normalized_events:
        metadata["events_json"] = json.dumps(normalized_events, ensure_ascii=False)
    return metadata


def _normalize_observations(value: object) -> list[dict[str, object]]:
    if not isinstance(value, dict):
        return []
    out: list[dict[str, object]] = []
    for speaker, observations in value.items():
        if not isinstance(observations, list):
            continue
        for observation in observations:
            text = ""
            evidence_ids: list[str] = []
            if isinstance(observation, list) and observation:
                text = str(observation[0] or "").strip()
                evidence_ids = [str(item).strip() for item in observation[1:] if str(item).strip()]
            elif isinstance(observation, str):
                text = observation.strip()
            if text:
                out.append({"speaker": str(speaker), "text": text, "evidence_ids": evidence_ids})
    return out


def _normalize_events(value: object) -> list[dict[str, str]]:
    if not isinstance(value, dict):
        return []
    date = str(value.get("date") or "").strip()
    out: list[dict[str, str]] = []
    for speaker, events in value.items():
        if speaker == "date" or not isinstance(events, list):
            continue
        for event in events:
            text = str(event or "").strip()
            if text:
                out.append({"speaker": str(speaker), "date": date, "text": text})
    return out


def _refined_question(item: dict[str, Any]) -> EvalQuestion:
    conversation_id = str(item.get("sample_id") or "")
    return EvalQuestion(
        question_id=str(item.get("qa_id") or ""),
        conversation_id=conversation_id,
        question=str(item.get("question") or "").strip(),
        answers=_answers_tuple(item.get("answer")),
        category=str(item.get("category") or ""),
        evidence_ids=tuple(str(value) for value in item.get("evidence") or () if str(value).strip()),
        is_multimodal=bool(item.get("is_multi_modality")),
        metadata={
            "conversation_idx": str(item.get("conversation_idx") or ""),
            "qa_index": str(item.get("qa_index") or ""),
        },
    )


def _answers_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    text = str(value or "").strip()
    return (text,) if text else ()


def _normalize_images(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    text = str(value or "").strip()
    return (text,) if text else ()


def _message_index(message_id: str) -> int | None:
    match = re.search(r":(\d+)$", message_id)
    if match is None:
        return None
    return int(match.group(1))


def _role_for_speaker(speaker: str, *, speaker_a: str, speaker_b: str) -> str:
    if speaker and speaker == speaker_b:
        return "assistant"
    if speaker and speaker == speaker_a:
        return "user"
    return "user"
