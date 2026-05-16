"""LoCoMo baseline targets for isolating memory-system variables."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Protocol

from packages.evals.contracts import (
    EvalConversation,
    EvalDataset,
    EvalQuestion,
    EvalQuestionResult,
    EvalSession,
    RetrievalHit,
)
from packages.evals.targets.elephant_memory import AnswerRunner


class EmbeddingServiceLike(Protocol):
    def embed_text(self, text: str, **kwargs: object) -> object:
        """Return an embedding vector object with values and dimensions."""


@dataclass(frozen=True, slots=True)
class _MemoryDocument:
    source_id: str
    content: str
    kind: str
    when: str = ""
    metadata: dict[str, str] | None = None


@dataclass(frozen=True, slots=True)
class _EmbeddedDocument:
    document: _MemoryDocument
    vector: tuple[float, ...]


class LoCoMoBaselineEvalTarget:
    """Runs LoCoMo questions through non-Elephant baseline memory views."""

    def __init__(
        self,
        *,
        embedding_service: EmbeddingServiceLike | None,
        answer_runner: AnswerRunner,
        top_k: int = 5,
        retrieval_mode: str = "semantic_raw_dialog",
        answer_concurrency: int = 1,
        answer_batch_size: int = 1,
    ) -> None:
        self.top_k = max(1, int(top_k or 5))
        self.retrieval_mode = normalize_baseline_mode(retrieval_mode)
        self.embedding_service = embedding_service
        self.answer_runner = answer_runner
        self.answer_concurrency = max(1, int(answer_concurrency or 1))
        self.answer_batch_size = max(1, int(answer_batch_size or 1))
        if self.retrieval_mode.startswith("semantic_") and embedding_service is None:
            raise ValueError(f"{self.retrieval_mode} requires a configured embedding service")

    def evaluate_dataset(self, dataset: EvalDataset) -> tuple[EvalQuestionResult, ...]:
        results: list[EvalQuestionResult] = []
        for conversation in dataset.conversations:
            results.extend(self.evaluate_conversation(conversation))
        return tuple(results)

    def evaluate_conversation(self, conversation: EvalConversation) -> tuple[EvalQuestionResult, ...]:
        if self.retrieval_mode == "oracle_evidence":
            prepared = tuple((question, _oracle_hits(conversation, question)) for question in conversation.questions)
        elif self.retrieval_mode == "full_context":
            full_hits = _full_context_hits(conversation)
            prepared = tuple((question, full_hits) for question in conversation.questions)
        else:
            documents = _documents_for_mode(conversation, self.retrieval_mode)
            embedded = self._embed_documents(documents)
            prepared = tuple((question, self._semantic_hits(embedded, question)) for question in conversation.questions)
        return self._answer_prepared_questions(prepared)

    def _embed_documents(self, documents: tuple[_MemoryDocument, ...]) -> tuple[_EmbeddedDocument, ...]:
        assert self.embedding_service is not None
        embedded: list[_EmbeddedDocument] = []
        cache: dict[str, tuple[float, ...]] = {}
        for document in documents:
            vector = cache.get(document.content)
            if vector is None:
                vector = _vector_values(
                    self.embedding_service.embed_text(
                        document.content,
                        request_id=f"eval-baseline-doc:{document.kind}:{document.source_id}",
                    )
                )
                cache[document.content] = vector
            embedded.append(_EmbeddedDocument(document=document, vector=vector))
        return tuple(embedded)

    def _semantic_hits(self, embedded: tuple[_EmbeddedDocument, ...], question: EvalQuestion) -> tuple[RetrievalHit, ...]:
        if not embedded:
            return ()
        assert self.embedding_service is not None
        query_vector = _vector_values(
            self.embedding_service.embed_text(
                question.question,
                request_id=f"eval-baseline-question:{question.question_id}",
            )
        )
        scored = sorted(
            (
                (_cosine(query_vector, item.vector), item.document)
                for item in embedded
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        hits = []
        for rank, (score, document) in enumerate(scored[: self.top_k], start=1):
            metadata = dict(document.metadata or {})
            metadata["retrieval_mode"] = self.retrieval_mode
            hits.append(
                RetrievalHit(
                    rank=rank,
                    source_id=document.source_id,
                    content=document.content,
                    score=score,
                    kind=document.kind,
                    when=document.when,
                    metadata=metadata,
                )
            )
        return tuple(hits)

    def _answer_prepared_questions(
        self,
        prepared: tuple[tuple[EvalQuestion, tuple[RetrievalHit, ...]], ...],
    ) -> tuple[EvalQuestionResult, ...]:
        if self.answer_concurrency <= 1 or len(prepared) <= 1:
            return tuple(result for chunk in _chunks(prepared, self.answer_batch_size) for result in self._answer_chunk(chunk))
        chunks = tuple(_chunks(prepared, self.answer_batch_size))
        workers = min(self.answer_concurrency, len(chunks))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="locomo-baseline-answer") as executor:
            futures = tuple(executor.submit(self._answer_chunk, chunk) for chunk in chunks)
            return tuple(result for future in futures for result in future.result())

    def _answer_chunk(
        self,
        chunk: tuple[tuple[EvalQuestion, tuple[RetrievalHit, ...]], ...],
    ) -> tuple[EvalQuestionResult, ...]:
        batch_answer = getattr(self.answer_runner, "answer_questions", None)
        if callable(batch_answer) and len(chunk) > 1:
            predicted_answers = tuple(str(answer).strip() or "I don't know" for answer in batch_answer(chunk))
            if len(predicted_answers) == len(chunk):
                return tuple(
                    self._result_for_question(question, hits, predicted_answer)
                    for (question, hits), predicted_answer in zip(chunk, predicted_answers)
                )
        return tuple(
            self._result_for_question(question, hits, self.answer_runner.answer_question(question, hits))
            for question, hits in chunk
        )

    def _result_for_question(
        self,
        question: EvalQuestion,
        hits: tuple[RetrievalHit, ...],
        predicted_answer: str,
    ) -> EvalQuestionResult:
        return EvalQuestionResult(
            question_id=question.question_id,
            conversation_id=question.conversation_id,
            question=question.question,
            answers=question.answers,
            predicted_answer=predicted_answer,
            category=question.category,
            evidence_ids=question.evidence_ids,
            hits=hits,
            is_multimodal=question.is_multimodal,
            metadata={
                **dict(question.metadata),
                "answer_mode": "model",
                "retrieval_mode": self.retrieval_mode,
            },
        )


def normalize_baseline_mode(value: str) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "raw": "semantic_raw_dialog",
        "raw_dialog": "semantic_raw_dialog",
        "semantic_dialog": "semantic_raw_dialog",
        "dialog": "semantic_raw_dialog",
        "summary": "semantic_session_summary",
        "session_summary": "semantic_session_summary",
        "semantic_summary": "semantic_session_summary",
        "observation": "semantic_observation",
        "observations": "semantic_observation",
        "semantic_observations": "semantic_observation",
        "combined": "semantic_combined",
        "all": "semantic_combined",
        "semantic_all": "semantic_combined",
        "full": "full_context",
        "fullcontext": "full_context",
        "oracle": "oracle_evidence",
        "oracle_gold": "oracle_evidence",
    }
    return aliases.get(text, text)


def is_baseline_mode(value: str) -> bool:
    return normalize_baseline_mode(value) in {
        "semantic_raw_dialog",
        "semantic_session_summary",
        "semantic_observation",
        "semantic_combined",
        "full_context",
        "oracle_evidence",
    }


def _documents_for_mode(conversation: EvalConversation, mode: str) -> tuple[_MemoryDocument, ...]:
    documents: list[_MemoryDocument] = []
    if mode in {"semantic_raw_dialog", "semantic_combined"}:
        documents.extend(_dialog_documents(conversation))
    if mode in {"semantic_session_summary", "semantic_combined"}:
        documents.extend(_session_summary_documents(conversation))
    if mode in {"semantic_observation", "semantic_combined"}:
        documents.extend(_observation_documents(conversation))
        documents.extend(_event_documents(conversation))
    return tuple(documents)


def _dialog_documents(conversation: EvalConversation) -> Iterable[_MemoryDocument]:
    for session in conversation.sessions:
        for message in session.messages:
            content = _render_message(message, session=session)
            yield _MemoryDocument(
                source_id=message.message_id,
                content=content,
                kind="dialog",
                when=session.date_time,
                metadata={
                    "source_ids": message.message_id,
                    "speaker": message.speaker,
                    "session_index": str(session.session_index),
                    "message_index": str(message.message_index),
                },
            )


def _session_summary_documents(conversation: EvalConversation) -> Iterable[_MemoryDocument]:
    for session in conversation.sessions:
        summary = str(session.metadata.get("session_summary") or "").strip()
        if not summary:
            continue
        source_ids = ",".join(message.message_id for message in session.messages)
        yield _MemoryDocument(
            source_id=f"S{session.session_index}",
            content=f"Session {session.session_index} at {session.date_time} summary: {summary}",
            kind="session_summary",
            when=session.date_time,
            metadata={
                "source_ids": source_ids,
                "session_index": str(session.session_index),
            },
        )


def _observation_documents(conversation: EvalConversation) -> Iterable[_MemoryDocument]:
    for session in conversation.sessions:
        observations = _loads_list(session.metadata.get("observations_json"))
        for index, observation in enumerate(observations, start=1):
            text = str(observation.get("text") or "").strip()
            if not text:
                continue
            evidence_ids = tuple(str(item).strip() for item in observation.get("evidence_ids") or () if str(item).strip())
            source_id = evidence_ids[0] if evidence_ids else f"O{session.session_index}:{index}"
            speaker = str(observation.get("speaker") or "").strip()
            yield _MemoryDocument(
                source_id=source_id,
                content=f"Session {session.session_index} at {session.date_time} observation for {speaker}: {text}",
                kind="observation",
                when=session.date_time,
                metadata={
                    "source_ids": ",".join(evidence_ids),
                    "speaker": speaker,
                    "session_index": str(session.session_index),
                },
            )


def _event_documents(conversation: EvalConversation) -> Iterable[_MemoryDocument]:
    for session in conversation.sessions:
        events = _loads_list(session.metadata.get("events_json"))
        source_ids = ",".join(message.message_id for message in session.messages)
        for index, event in enumerate(events, start=1):
            text = str(event.get("text") or "").strip()
            if not text:
                continue
            speaker = str(event.get("speaker") or "").strip()
            date = str(event.get("date") or session.date_time).strip()
            yield _MemoryDocument(
                source_id=f"E{session.session_index}:{index}",
                content=f"Session {session.session_index} event on {date} for {speaker}: {text}",
                kind="event_summary",
                when=date,
                metadata={
                    "source_ids": source_ids,
                    "speaker": speaker,
                    "session_index": str(session.session_index),
                },
            )


def _full_context_hits(conversation: EvalConversation) -> tuple[RetrievalHit, ...]:
    source_ids = ",".join(
        message.message_id
        for session in conversation.sessions
        for message in session.messages
    )
    content = "\n".join(
        _render_message(message, session=session)
        for session in conversation.sessions
        for message in session.messages
    )
    return (
        RetrievalHit(
            rank=1,
            source_id="FULL_CONTEXT",
            content=content,
            score=1.0,
            kind="full_context",
            metadata={"source_ids": source_ids, "retrieval_mode": "full_context"},
        ),
    )


def _oracle_hits(conversation: EvalConversation, question: EvalQuestion) -> tuple[RetrievalHit, ...]:
    by_id = {
        message.message_id: (session, message)
        for session in conversation.sessions
        for message in session.messages
    }
    hits: list[RetrievalHit] = []
    for rank, evidence_id in enumerate(question.evidence_ids, start=1):
        item = by_id.get(evidence_id)
        if item is None:
            continue
        session, message = item
        hits.append(
            RetrievalHit(
                rank=rank,
                source_id=evidence_id,
                content=_render_message(message, session=session),
                score=1.0,
                kind="oracle_evidence",
                when=session.date_time,
                metadata={"source_ids": evidence_id, "retrieval_mode": "oracle_evidence"},
            )
        )
    return tuple(hits)


def _render_message(message, *, session: EvalSession) -> str:
    parts = [
        f"Session {session.session_index} at {session.date_time}",
        f"{message.speaker}: {message.text}",
    ]
    if message.image_caption:
        parts.append(f"image caption: {message.image_caption}")
    if message.image_query:
        parts.append(f"image query: {message.image_query}")
    return " | ".join(part for part in parts if str(part).strip())


def _vector_values(vector: object) -> tuple[float, ...]:
    values = getattr(vector, "values", vector)
    if isinstance(values, tuple):
        return tuple(float(value) for value in values)
    if isinstance(values, list):
        return tuple(float(value) for value in values)
    return ()


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if not left or not right:
        return 0.0
    size = min(len(left), len(right))
    dot = sum(left[index] * right[index] for index in range(size))
    left_norm = math.sqrt(sum(value * value for value in left[:size]))
    right_norm = math.sqrt(sum(value * value for value in right[:size]))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _loads_list(value: object) -> list[dict[str, object]]:
    try:
        payload = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _chunks(
    items: tuple[tuple[EvalQuestion, tuple[RetrievalHit, ...]], ...],
    size: int,
) -> tuple[tuple[tuple[EvalQuestion, tuple[RetrievalHit, ...]], ...], ...]:
    capped = max(1, int(size or 1))
    return tuple(tuple(items[index : index + capped]) for index in range(0, len(items), capped))
