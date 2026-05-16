"""Elephant memory/search target adapter for unified evals."""

from __future__ import annotations

import re
import tempfile
import json
from concurrent.futures import ThreadPoolExecutor
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
_ELEPHANT_MEMORY_MODES = frozenset(
    {
        "hybrid",
        "hybrid_query_fusion",
        "hybrid_observation",
        "hybrid_multilayer",
        "hybrid_multilayer_query_fusion",
    }
)


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
        system_prompt = (
            "You are answering a memory evaluation question for Elephant Agent.\n"
            "Use only the provided retrieved evidence.\n"
            "If the evidence is insufficient, answer exactly: I don't know\n"
            "Return only the final answer, with no explanation, quotes, citations, or markdown.\n"
            "Keep the answer to one short phrase or one short sentence."
        )
        user_prompt = (
            f"Question: {question.question}\n\n"
            f"Retrieved evidence:\n{_render_evidence_block(hits)}\n\n"
            "Final answer:"
        )
        return self._generate(
            request_id=question.question_id,
            question_ids=(question.question_id,),
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    def answer_questions(
        self,
        items: tuple[tuple[EvalQuestion, tuple[RetrievalHit, ...]], ...],
    ) -> tuple[str, ...]:
        if len(items) <= 1:
            return tuple(self.answer_question(question, hits) for question, hits in items)
        system_prompt = (
            "You are answering memory evaluation questions for Elephant Agent.\n"
            "Use only each question's provided retrieved evidence.\n"
            "If a question's evidence is insufficient, answer exactly: I don't know\n"
            "Return only a valid JSON object mapping each question_id to one short answer string.\n"
            "Do not include markdown, citations, or explanation."
        )
        blocks = []
        question_ids: list[str] = []
        for question, hits in items:
            question_ids.append(question.question_id)
            blocks.append(
                "\n".join(
                    (
                        f"question_id: {question.question_id}",
                        f"question: {question.question}",
                        "retrieved_evidence:",
                        _render_evidence_block(hits, max_chars=700),
                    )
                )
            )
        user_prompt = (
            "Answer these questions as JSON.\n\n"
            + "\n\n---\n\n".join(blocks)
            + "\n\nJSON object:"
        )
        text = self._generate(
            request_id="batch:" + _safe_id(":".join(question_ids)),
            question_ids=tuple(question_ids),
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        parsed = _parse_answer_json(text)
        if set(question_ids).issubset(parsed):
            return tuple(str(parsed.get(question.question_id) or "I don't know").strip() or "I don't know" for question, _ in items)
        return tuple(self.answer_question(question, hits) for question, hits in items)

    def _generate(
        self,
        *,
        request_id: str,
        question_ids: tuple[str, ...],
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        now = datetime.now(timezone.utc)
        episode = Episode(
            episode_id=f"eval-answer:{_safe_id(request_id)}",
            state_id=self.state_id,
            personal_model_id=self.personal_model_id,
            entry_surface="eval.locomo.answer",
            status="closed",
            started_at=now,
            ended_at=now,
            metadata={
                "question_ids": ",".join(question_ids),
            },
        )
        context = ContextBundle(
            bundle_id=f"eval-context:{_safe_id(request_id)}",
            episode_id=episode.episode_id,
            token_budget=4096,
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
        answer_concurrency: int = 1,
        answer_batch_size: int = 1,
    ) -> None:
        self.top_k = max(1, int(top_k or 5))
        self.answer_concurrency = max(1, int(answer_concurrency or 1))
        self.answer_batch_size = max(1, int(answer_batch_size or 1))
        self.retrieval_mode = _normalize_memory_mode(retrieval_mode)
        self.answer_mode = str(answer_mode or "model").strip().lower()
        if not is_elephant_memory_mode(self.retrieval_mode):
            raise ValueError(f"unsupported elephant memory retrieval mode: {retrieval_mode}")
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
            prepared = tuple(
                (question, self._retrieve_hits(sandbox, question))
                for question in conversation.questions
            )
            return self._answer_prepared_questions(prepared)
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
            for step in self._memory_steps_for_session(
                session,
                loop_id=loop_id,
                episode_id=episode_id,
                state_id=sandbox.state_id,
                personal_model_id=sandbox.personal_model_id,
                created_at=started_at + timedelta(hours=1),
            ):
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

    def _retrieve_hits(self, sandbox: _ConversationSandbox, question: EvalQuestion) -> tuple[RetrievalHit, ...]:
        if self.retrieval_mode in {"hybrid_query_fusion", "hybrid_multilayer_query_fusion"}:
            return self._retrieve_fused_hits(sandbox, question)
        return self._retrieve_single_query_hits(sandbox, question.question, limit=self.top_k)

    def _retrieve_single_query_hits(
        self,
        sandbox: _ConversationSandbox,
        query: str,
        *,
        limit: int,
    ) -> tuple[RetrievalHit, ...]:
        raw_hits = unified_recall(
            UnifiedRecallRequest(
                query=query,
                scopes=("steps",),
                personal_model_id=sandbox.personal_model_id,
                state_id=sandbox.state_id,
                limit=limit,
            ),
            repository=sandbox.repository,
            searcher=sandbox.searcher,
            embedding_service=sandbox.embedding_service,
        )
        return tuple(_retrieval_hit(index, hit) for index, hit in enumerate(raw_hits, start=1))

    def _retrieve_fused_hits(self, sandbox: _ConversationSandbox, question: EvalQuestion) -> tuple[RetrievalHit, ...]:
        candidates: dict[str, tuple[RetrievalHit, float]] = {}
        query_limit = max(self.top_k * 2, self.top_k)
        for query in _queries_for_question(question):
            for hit in self._retrieve_single_query_hits(sandbox, query, limit=query_limit):
                key = _retrieval_identity(hit)
                fused_score = (1.0 / (60.0 + hit.rank)) + (hit.score * 0.01)
                existing = candidates.get(key)
                if existing is None:
                    candidates[key] = (hit, fused_score)
                    continue
                existing_hit, existing_score = existing
                best_hit = hit if hit.rank < existing_hit.rank else existing_hit
                candidates[key] = (best_hit, existing_score + fused_score)
        ranked = sorted(candidates.values(), key=lambda item: item[1], reverse=True)
        return tuple(
            RetrievalHit(
                rank=index,
                source_id=hit.source_id,
                content=hit.content,
                score=score,
                kind=hit.kind,
                when=hit.when,
                metadata={**dict(hit.metadata), "query_fusion": "true"},
            )
            for index, (hit, score) in enumerate(ranked[: self.top_k], start=1)
        )

    def _memory_steps_for_session(
        self,
        session,
        *,
        loop_id: str,
        episode_id: str,
        state_id: str,
        personal_model_id: str,
        created_at: datetime,
    ) -> tuple[Step, ...]:
        if self.retrieval_mode in {"hybrid", "hybrid_query_fusion"}:
            return ()
        include_summary = self.retrieval_mode in {"hybrid_multilayer", "hybrid_multilayer_query_fusion"}
        steps: list[Step] = []
        if include_summary:
            summary = str(session.metadata.get("session_summary") or "").strip()
            if summary:
                steps.append(
                    self._memory_step(
                        step_id=f"eval:summary:S{session.session_index}",
                        loop_id=loop_id,
                        episode_id=episode_id,
                        state_id=state_id,
                        personal_model_id=personal_model_id,
                        created_at=created_at,
                        sequence=10_000 + session.session_index,
                        content=f"Session {session.session_index} at {session.date_time} summary: {summary}",
                        source_id=f"S{session.session_index}",
                        source_ids=",".join(message.message_id for message in session.messages),
                        memory_kind="session_summary",
                        session_index=session.session_index,
                        session_date_time=session.date_time,
                    )
                )
        for index, observation in enumerate(_loads_list(session.metadata.get("observations_json")), start=1):
            text = str(observation.get("text") or "").strip()
            if not text:
                continue
            evidence_ids = tuple(str(item).strip() for item in observation.get("evidence_ids") or () if str(item).strip())
            speaker = str(observation.get("speaker") or "").strip()
            steps.append(
                self._memory_step(
                    step_id=f"eval:observation:S{session.session_index}:{index}",
                    loop_id=loop_id,
                    episode_id=episode_id,
                    state_id=state_id,
                    personal_model_id=personal_model_id,
                    created_at=created_at + timedelta(minutes=index),
                    sequence=20_000 + index,
                    content=f"Session {session.session_index} at {session.date_time} observation for {speaker}: {text}",
                    source_id=evidence_ids[0] if evidence_ids else f"O{session.session_index}:{index}",
                    source_ids=",".join(evidence_ids),
                    memory_kind="observation",
                    session_index=session.session_index,
                    session_date_time=session.date_time,
                    speaker=speaker,
                )
            )
        for index, event in enumerate(_loads_list(session.metadata.get("events_json")), start=1):
            text = str(event.get("text") or "").strip()
            if not text:
                continue
            speaker = str(event.get("speaker") or "").strip()
            date = str(event.get("date") or session.date_time).strip()
            steps.append(
                self._memory_step(
                    step_id=f"eval:event:S{session.session_index}:{index}",
                    loop_id=loop_id,
                    episode_id=episode_id,
                    state_id=state_id,
                    personal_model_id=personal_model_id,
                    created_at=created_at + timedelta(minutes=500 + index),
                    sequence=30_000 + index,
                    content=f"Session {session.session_index} event on {date} for {speaker}: {text}",
                    source_id=f"E{session.session_index}:{index}",
                    source_ids=",".join(message.message_id for message in session.messages),
                    memory_kind="event_summary",
                    session_index=session.session_index,
                    session_date_time=session.date_time,
                    speaker=speaker,
                )
            )
        return tuple(steps)

    def _memory_step(
        self,
        *,
        step_id: str,
        loop_id: str,
        episode_id: str,
        state_id: str,
        personal_model_id: str,
        created_at: datetime,
        sequence: int,
        content: str,
        source_id: str,
        source_ids: str,
        memory_kind: str,
        session_index: int,
        session_date_time: str,
        speaker: str = "",
    ) -> Step:
        metadata = {
            "event_type": f"eval.memory.{memory_kind}",
            "source_id": source_id,
            "source_ids": source_ids,
            "recall_source": memory_kind,
            "session_index": str(session_index),
            "session_date_time": session_date_time,
            "speaker": speaker,
            "assistant_response": content,
        }
        return Step(
            step_id=step_id,
            loop_id=loop_id,
            episode_id=episode_id,
            state_id=state_id,
            personal_model_id=personal_model_id,
            phase="observation",
            action="emit_response",
            status="completed",
            sequence=sequence,
            created_at=created_at,
            summary=content,
            payload_refs=(source_id,),
            metadata=metadata,
        )

    def _answer_prepared_questions(
        self,
        prepared: tuple[tuple[EvalQuestion, tuple[RetrievalHit, ...]], ...],
    ) -> tuple[EvalQuestionResult, ...]:
        if self.answer_concurrency <= 1 or len(prepared) <= 1:
            return tuple(result for chunk in _chunks(prepared, self.answer_batch_size) for result in self._answer_chunk(chunk))
        chunks = tuple(_chunks(prepared, self.answer_batch_size))
        workers = min(self.answer_concurrency, len(chunks))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="elephant-eval-answer") as executor:
            futures = tuple(
                executor.submit(self._answer_chunk, chunk)
                for chunk in chunks
            )
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
        return tuple(self._answer_question(question, hits) for question, hits in chunk)

    def _answer_question(self, question: EvalQuestion, hits: tuple[RetrievalHit, ...]) -> EvalQuestionResult:
        predicted_answer = self.answer_runner.answer_question(question, hits)
        return self._result_for_question(question, hits, predicted_answer)

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


def is_elephant_memory_mode(value: str) -> bool:
    return _normalize_memory_mode(value) in _ELEPHANT_MEMORY_MODES


def _normalize_memory_mode(value: object) -> str:
    text = str(value or "hybrid").strip().lower().replace("-", "_")
    aliases = {
        "hybrid_fusion": "hybrid_query_fusion",
        "query_fusion": "hybrid_query_fusion",
        "hybrid_obs": "hybrid_observation",
        "hybrid_observations": "hybrid_observation",
        "hybrid_facts": "hybrid_observation",
        "hybrid_all": "hybrid_multilayer",
        "hybrid_multi_layer": "hybrid_multilayer",
        "hybrid_multilayer_fusion": "hybrid_multilayer_query_fusion",
        "hybrid_all_fusion": "hybrid_multilayer_query_fusion",
    }
    return aliases.get(text, text)


def _queries_for_question(question: EvalQuestion) -> tuple[str, ...]:
    base = question.question.strip()
    queries = [base]
    category = str(question.category or "").strip()
    if category == "2":
        queries.append(f"{base} date time session when happened relative day week month")
    elif category == "1":
        queries.append(f"{base} personal fact identity activity relationship preference")
    elif category == "3":
        queries.append(f"{base} infer likely preference goal field from evidence")
    elif category == "4":
        queries.append(f"{base} event detail reason awareness topic")
    else:
        queries.append(f"{base} memory evidence conversation detail")
    queries.append(_keyword_query(base))
    return tuple(dict.fromkeys(query for query in queries if query.strip()))


def _keyword_query(value: str) -> str:
    tokens = re.findall(r"[A-Za-z][A-Za-z'-]{2,}|\d{4}|\d{1,2}", value)
    stop = {
        "what",
        "when",
        "where",
        "who",
        "why",
        "how",
        "did",
        "does",
        "would",
        "could",
        "should",
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "was",
        "were",
        "is",
        "are",
    }
    kept = [token for token in tokens if token.lower() not in stop]
    return " ".join(kept[:12]) or value


def _retrieval_identity(hit: RetrievalHit) -> str:
    metadata = dict(hit.metadata)
    identity = (
        metadata.get("source_ids")
        or metadata.get("source_id")
        or metadata.get("dia_id")
        or hit.source_id
        or hit.content[:80]
    )
    return str(identity)


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


def _render_evidence_block(hits: tuple[RetrievalHit, ...], *, max_chars: int = 1200) -> str:
    if not hits:
        return "No retrieved evidence."
    lines = []
    for hit in hits:
        source = hit.source_id or f"rank-{hit.rank}"
        content_max_chars = 120_000 if hit.kind == "full_context" else max_chars
        content = _clean_evidence_text(hit.content, max_chars=content_max_chars)
        lines.append(f"[{hit.rank}] {source}: {content}")
    return "\n".join(lines)


def _clean_evidence_text(value: str, *, max_chars: int) -> str:
    return " ".join(str(value or "").split()).strip()[:max_chars]


def _parse_answer_json(value: str) -> dict[str, str]:
    text = str(value or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): str(value) for key, value in payload.items()}


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


def _safe_id(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.:-]+", "-", str(value or "").strip())
    return text[:120] or "question"
