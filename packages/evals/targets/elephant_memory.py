"""Elephant memory/search target adapter for unified evals."""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from packages.contracts import (
    ContextBundle,
    Episode,
    Loop,
    PromptEnvelope,
    PromptMessage,
    Step,
)
from packages.evals.contracts import (
    EvalConversation,
    EvalDataset,
    EvalMessage,
    EvalQuestion,
    EvalQuestionResult,
    RetrievalHit,
)
from packages.evidence import (
    SemanticSummaryIndexer,
    UnifiedRecallRequest,
    build_semantic_index_bundle,
    unified_recall,
)
from packages.storage import RuntimeStorageRepository


_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
_DAY_MONTH_YEAR_RE = re.compile(r"\b(\d{1,2})\s+([A-Za-z]+),?\s+(\d{4})\b")


class EmbeddingServiceLike(Protocol):
    def embed_text(self, text: str, **kwargs: object) -> object:
        """Return an embedding vector object with values and dimensions."""


class AnswerRunner(Protocol):
    def answer_question(self, question: EvalQuestion, hits: tuple[RetrievalHit, ...]) -> str:
        """Return a final answer for one normalized eval question."""


@dataclass
class _ConversationSandbox:
    tempdir: tempfile.TemporaryDirectory[str]
    repository: RuntimeStorageRepository
    personal_model_id: str
    state_id: str
    searcher: Any
    embedding_service: EmbeddingServiceLike
    indexer: SemanticSummaryIndexer

    def cleanup(self) -> None:
        self.tempdir.cleanup()


class ElephantModelAnswerRunner:
    """Answer LoCoMo-style questions with the configured Elephant model provider."""

    def __init__(
        self,
        *,
        model_provider: Any,
        profile: Any,
        model_role: str = "strong",
        state_id: str = "eval-state",
        personal_model_id: str | None = None,
    ) -> None:
        active_profile = getattr(model_provider, "active_profile", None)
        if callable(active_profile) and active_profile() is None:
            raise RuntimeError("elephant eval requires an active model provider profile")
        self.model_provider = model_provider
        self.profile = profile
        self.model_role = model_role
        self.state_id = state_id
        self.personal_model_id = personal_model_id or str(getattr(profile, "profile_id", "eval-profile") or "eval-profile")

    def answer_question(self, question: EvalQuestion, hits: tuple[RetrievalHit, ...]) -> str:
        evidence_block = _render_evidence_block(hits)
        system_prompt = (
            "You are answering a memory evaluation question for Elephant Agent.\n"
            "Use only the provided retrieved evidence.\n"
            "If the evidence is insufficient, answer exactly: I don't know\n"
            "Return only the final answer, with no explanation, quotes, citations, or markdown.\n"
            "Keep the answer to one short phrase or one short sentence."
        )
        user_prompt = (
            f"Question: {question.question}\n\n"
            f"Retrieved evidence:\n{evidence_block}\n\n"
            "Final answer:"
        )
        episode = Episode(
            episode_id=f"eval-answer:{_safe_id(question.question_id)}",
            state_id=self.state_id,
            personal_model_id=self.personal_model_id,
            entry_surface="eval.locomo.answer",
            status="closed",
            started_at=datetime.now(timezone.utc),
            ended_at=datetime.now(timezone.utc),
            metadata={
                "question_id": question.question_id,
                "conversation_id": question.conversation_id,
            },
        )
        context = ContextBundle(
            bundle_id=f"eval-context:{_safe_id(question.question_id)}",
            episode_id=episode.episode_id,
            token_budget=4096,
            evidence_refs=tuple(hit.source_id for hit in hits if hit.source_id),
            prompt_envelope=PromptEnvelope(
                frozen_prefix=system_prompt,
                messages=(PromptMessage(role="user", content=user_prompt),),
            ),
            rendered_prompt=user_prompt,
        )
        result = self.model_provider.generate(
            profile=self.profile,
            session=episode,
            context=context,
            prompt=user_prompt,
            model_role=self.model_role,
        )
        answer = str(getattr(result, "summary", "") or "").strip()
        return answer or "I don't know"


class ElephantMemoryEvalTarget:
    """Runs normalized eval conversations through Elephant hybrid recall."""

    def __init__(
        self,
        *,
        embedding_service: EmbeddingServiceLike,
        answer_runner: AnswerRunner,
        top_k: int = 5,
        retrieval_mode: str = "hybrid",
        answer_mode: str = "model",
    ) -> None:
        self.top_k = max(1, int(top_k or 5))
        self.retrieval_mode = str(retrieval_mode or "hybrid").strip().lower()
        self.answer_mode = str(answer_mode or "model").strip().lower()
        if self.retrieval_mode != "hybrid":
            raise ValueError("elephant eval only supports hybrid retrieval")
        if self.answer_mode != "model":
            raise ValueError("elephant eval only supports model answer mode")
        if embedding_service is None:
            raise ValueError("elephant eval requires a configured embedding service")
        self.embedding_service = embedding_service
        self.answer_runner = answer_runner

    def evaluate_dataset(self, dataset: EvalDataset) -> tuple[EvalQuestionResult, ...]:
        results: list[EvalQuestionResult] = []
        for conversation in dataset.conversations:
            results.extend(self.evaluate_conversation(conversation))
        return tuple(results)

    def evaluate_conversation(self, conversation: EvalConversation) -> tuple[EvalQuestionResult, ...]:
        sandbox = self._create_sandbox()
        try:
            self._ingest_conversation(sandbox, conversation)
            return tuple(self._evaluate_question(sandbox, question) for question in conversation.questions)
        finally:
            sandbox.cleanup()

    def _create_sandbox(self) -> _ConversationSandbox:
        tempdir = tempfile.TemporaryDirectory(prefix="elephant-eval-")
        root = Path(tempdir.name)
        state_dir = root / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        repository = RuntimeStorageRepository(state_dir / "elephant.sqlite3")
        repository.bootstrap()
        state = repository.create_state(elephant_id="eval-elephant", elephant_name="Eval Elephant")
        bundle = build_semantic_index_bundle(repository=repository, state_dir=state_dir)
        indexer = SemanticSummaryIndexer(
            semantic_index=bundle.service,
            embedding_service=self.embedding_service,
            repository=repository,
        )
        return _ConversationSandbox(
            tempdir=tempdir,
            repository=repository,
            personal_model_id=state.personal_model_id,
            state_id=state.state_id,
            searcher=bundle.searcher,
            embedding_service=self.embedding_service,
            indexer=indexer,
        )

    def _ingest_conversation(self, sandbox: _ConversationSandbox, conversation: EvalConversation) -> None:
        for session in conversation.sessions:
            episode_id = f"eval:{conversation.conversation_id}:session:{session.session_index}"
            loop_id = f"eval:{conversation.conversation_id}:loop:{session.session_index}"
            started_at = _parse_session_datetime(session.date_time) or (
                datetime(2023, 1, 1, tzinfo=timezone.utc) + timedelta(days=session.session_index)
            )
            sandbox.repository.upsert_episode(
                Episode(
                    episode_id=episode_id,
                    state_id=sandbox.state_id,
                    personal_model_id=sandbox.personal_model_id,
                    entry_surface="eval.locomo",
                    status="closed",
                    started_at=started_at,
                    ended_at=started_at,
                    metadata={
                        "conversation_id": conversation.conversation_id,
                        "session_index": str(session.session_index),
                        "session_date_time": session.date_time,
                    },
                )
            )
            sandbox.repository.upsert_loop(
                Loop(
                    loop_id=loop_id,
                    episode_id=episode_id,
                    state_id=sandbox.state_id,
                    personal_model_id=sandbox.personal_model_id,
                    trigger_type="eval.locomo.session",
                    status="closed",
                    started_at=started_at,
                    ended_at=started_at,
                    metadata={"conversation_id": conversation.conversation_id},
                )
            )
            for message in session.messages:
                step = self._step_for_message(
                    message,
                    loop_id=loop_id,
                    episode_id=episode_id,
                    state_id=sandbox.state_id,
                    personal_model_id=sandbox.personal_model_id,
                    session_date_time=session.date_time,
                    created_at=started_at + timedelta(minutes=message.message_index),
                )
                sandbox.repository.upsert_step(step)
                sandbox.indexer.index_step(step)

    def _step_for_message(
        self,
        message: EvalMessage,
        *,
        loop_id: str,
        episode_id: str,
        state_id: str,
        personal_model_id: str,
        session_date_time: str,
        created_at: datetime,
    ) -> Step:
        action = "emit_response" if message.role == "assistant" else "record_input"
        content = _render_message_for_recall(message, session_date_time=session_date_time)
        metadata = {
            "event_type": "turn.response" if action == "emit_response" else "turn.received",
            "conversation_id": str(message.metadata.get("conversation_id") or ""),
            "source_id": message.message_id,
            "dia_id": message.message_id,
            "speaker": message.speaker,
            "session_index": str(message.session_index),
            "message_index": str(message.message_index),
            "session_date_time": session_date_time,
        }
        if action == "emit_response":
            metadata["assistant_response"] = content
        else:
            metadata["user_query"] = content
        return Step(
            step_id=f"eval:{message.message_id}",
            loop_id=loop_id,
            episode_id=episode_id,
            state_id=state_id,
            personal_model_id=personal_model_id,
            phase="observation",
            action=action,
            status="completed",
            sequence=message.message_index,
            created_at=created_at,
            summary=content,
            payload_refs=(message.message_id,),
            metadata=metadata,
        )

    def _evaluate_question(self, sandbox: _ConversationSandbox, question: EvalQuestion) -> EvalQuestionResult:
        raw_hits = unified_recall(
            UnifiedRecallRequest(
                query=question.question,
                scopes=("steps",),
                personal_model_id=sandbox.personal_model_id,
                state_id=sandbox.state_id,
                limit=self.top_k,
            ),
            repository=sandbox.repository,
            searcher=sandbox.searcher,
            embedding_service=sandbox.embedding_service,
        )
        hits = tuple(_retrieval_hit(index, hit) for index, hit in enumerate(raw_hits, start=1))
        predicted_answer = self.answer_runner.answer_question(question, hits)
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
                "answer_mode": self.answer_mode,
                "retrieval_mode": self.retrieval_mode,
            },
        )


def _retrieval_hit(rank: int, hit: Any) -> RetrievalHit:
    metadata = {str(key): str(value) for key, value in dict(getattr(hit, "extra_metadata", {}) or {}).items()}
    source_id = (
        str(metadata.get("source_id") or "").strip()
        or str(metadata.get("dia_id") or "").strip()
        or _source_id_from_step_id(metadata.get("step_id", ""))
    )
    return RetrievalHit(
        rank=rank,
        source_id=source_id,
        content=str(getattr(hit, "content", "") or ""),
        score=float(getattr(hit, "score", 0.0) or 0.0),
        kind=str(getattr(hit, "kind", "") or ""),
        when=str(getattr(hit, "when", "") or ""),
        metadata=metadata,
    )


def _source_id_from_step_id(value: object) -> str:
    text = str(value or "").strip()
    if text.startswith("eval:"):
        return text.removeprefix("eval:")
    return text


def _render_message_for_recall(message: EvalMessage, *, session_date_time: str) -> str:
    parts = [
        f"Session {message.session_index} at {session_date_time}",
        f"{message.speaker}: {message.text}",
    ]
    if message.image_caption:
        parts.append(f"image caption: {message.image_caption}")
    if message.image_query:
        parts.append(f"image query: {message.image_query}")
    return " | ".join(part for part in parts if str(part).strip())


def _parse_session_datetime(value: str) -> datetime | None:
    match = _DAY_MONTH_YEAR_RE.search(str(value or ""))
    if match is None:
        return None
    day = int(match.group(1))
    month = _MONTHS.get(match.group(2).lower())
    year = int(match.group(3))
    if month is None:
        return None
    return datetime(year, month, day, tzinfo=timezone.utc)


def _render_evidence_block(hits: tuple[RetrievalHit, ...]) -> str:
    if not hits:
        return "No retrieved evidence."
    lines = []
    for hit in hits:
        source = hit.source_id or f"rank-{hit.rank}"
        content = _clean_evidence_text(hit.content)
        lines.append(f"[{hit.rank}] {source}: {content}")
    return "\n".join(lines)


def _clean_evidence_text(value: str) -> str:
    return " ".join(str(value or "").split()).strip()[:1200]


def _safe_id(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.:-]+", "-", str(value or "").strip())
    return text[:120] or "question"
