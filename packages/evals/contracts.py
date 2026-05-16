"""Stable contracts for dataset-agnostic eval runners."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True, slots=True)
class EvalMessage:
    message_id: str
    session_index: int
    message_index: int
    speaker: str
    role: str
    text: str
    images: tuple[str, ...] = ()
    image_caption: str = ""
    image_query: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvalSession:
    session_id: str
    session_index: int
    date_time: str
    messages: tuple[EvalMessage, ...]
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvalQuestion:
    question_id: str
    conversation_id: str
    question: str
    answers: tuple[str, ...]
    category: str = ""
    evidence_ids: tuple[str, ...] = ()
    is_multimodal: bool = False
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvalConversation:
    conversation_id: str
    conversation_index: int
    speaker_a: str
    speaker_b: str
    sessions: tuple[EvalSession, ...]
    questions: tuple[EvalQuestion, ...]
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvalDataset:
    dataset_id: str
    source_path: str
    conversations: tuple[EvalConversation, ...]
    metadata: Mapping[str, str] = field(default_factory=dict)

    @property
    def question_count(self) -> int:
        return sum(len(conversation.questions) for conversation in self.conversations)


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    rank: int
    source_id: str
    content: str
    score: float
    kind: str = ""
    when: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvalQuestionResult:
    question_id: str
    conversation_id: str
    question: str
    answers: tuple[str, ...]
    predicted_answer: str
    category: str = ""
    evidence_ids: tuple[str, ...] = ()
    hits: tuple[RetrievalHit, ...] = ()
    is_multimodal: bool = False
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvalRunConfig:
    dataset: str
    dataset_path: str
    output_dir: str
    top_k: int = 5
    retrieval_mode: str = "hybrid"
    answer_mode: str = "model"
    limit_conversations: int | None = None
    limit_questions: int | None = None


@dataclass(frozen=True, slots=True)
class EvalRunOutput:
    dataset: EvalDataset
    results: tuple[EvalQuestionResult, ...]
    metrics: Mapping[str, object]
    artifacts: Mapping[str, Path]
