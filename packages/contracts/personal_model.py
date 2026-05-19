"""Personal Model contracts for four-lens understanding.

A durable active ``Fact`` is the prompt-visible claim Elephant Agent currently
believes. An ``OpenQuestion`` is a lens/topic-bound question that may improve
future help.

Four lenses — Identity, World, Pulse, Journey — each answer a distinct question
about the person:
- identity: Who am I? Durable attributes — character, values, style, body.
- world:    What is around me? Environment — people, projects, tools, places.
- pulse:    How am I right now? Current state — chapter, focus, mood, blockers.
- journey:  What have I been through? Accumulated experience — lessons, patterns, decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping


ALLOWED_LENSES = frozenset({"identity", "world", "pulse", "journey"})
ALLOWED_FACT_STATUSES = frozenset({"active", "retired", "disputed", "deleted"})
ALLOWED_FACT_SOURCES = frozenset({"user_explicit", "pm_agent_promote"})
ALLOWED_QUESTION_STATUSES = frozenset({"open", "asked", "answered", "dismissed", "stale"})
ALLOWED_QUESTION_SOURCES = frozenset({"coverage_gap", "ambiguity", "contextual"})
ALLOWED_SENSITIVITIES = frozenset({"low", "medium", "high"})
ALLOWED_LEARNING_INTENSITIES = frozenset({"low", "medium", "high"})


def _ensure_non_empty_text(value: str, *, name: str) -> None:
    if not str(value).strip():
        raise ValueError(f"{name} must not be empty")


def _ensure_confidence(value: float, *, name: str) -> None:
    if not 0.0 <= float(value) <= 1.0:
        raise ValueError(f"{name} confidence must stay between 0.0 and 1.0")


def _ensure_lens(value: str | None, *, name: str, allow_none: bool = False) -> None:
    if value is None:
        if allow_none:
            return
        raise ValueError(f"{name} lens must be provided")
    if value not in ALLOWED_LENSES:
        raise ValueError(f"{name} lens must be one of {sorted(ALLOWED_LENSES)}: {value}")


@dataclass(frozen=True, slots=True)
class Fact:
    """A durable, prompt-visible statement about the user."""

    fact_id: str
    personal_model_id: str
    lens: str
    text: str
    confidence: float
    committed_at: datetime
    source: str
    source_episode_ids: tuple[str, ...] = ()
    status: str = "active"
    supersedes_fact_id: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)
    last_accessed_at: datetime | None = None
    access_count: int = 0

    def __post_init__(self) -> None:
        _ensure_non_empty_text(self.fact_id, name="fact id")
        _ensure_non_empty_text(self.personal_model_id, name="fact personal model id")
        _ensure_non_empty_text(self.text, name="fact text")
        _ensure_lens(self.lens, name="fact")
        _ensure_confidence(self.confidence, name="fact")
        if self.source not in ALLOWED_FACT_SOURCES:
            raise ValueError(f"fact source must be one of {sorted(ALLOWED_FACT_SOURCES)}: {self.source}")
        if self.status not in ALLOWED_FACT_STATUSES:
            raise ValueError(f"fact status must be one of {sorted(ALLOWED_FACT_STATUSES)}: {self.status}")


@dataclass(frozen=True, slots=True)
class OpenQuestion:
    """A question Elephant Agent would like to ask the user next.

    Generated from one of three sources: coverage_gap (empty sub_lens during
    daily consolidation), ambiguity (unresolvable L1/L2 conflict), or
    contextual (mentioned-but-unexplored thread during extract).
    """

    question_id: str
    personal_model_id: str
    lens: str
    sub_lens: str
    text: str
    rationale: str
    priority: float
    sensitivity: str
    source: str
    created_at: datetime
    status: str = "open"
    asked_count: int = 0
    last_asked_at: datetime | None = None
    last_asked_surface: str | None = None
    user_response_episode_ids: tuple[str, ...] = ()
    dismissed_reason: str | None = None
    generated_fact_ids: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _ensure_non_empty_text(self.question_id, name="open question id")
        _ensure_non_empty_text(self.personal_model_id, name="open question personal model id")
        _ensure_lens(self.lens, name="open question")
        _ensure_non_empty_text(self.sub_lens, name="open question sub_lens")
        _ensure_non_empty_text(self.text, name="open question text")
        _ensure_non_empty_text(self.rationale, name="open question rationale")
        if not 0.0 <= float(self.priority) <= 1.0:
            raise ValueError("open question priority must stay between 0.0 and 1.0")
        if self.sensitivity not in ALLOWED_SENSITIVITIES:
            raise ValueError(
                f"open question sensitivity must be one of {sorted(ALLOWED_SENSITIVITIES)}: {self.sensitivity}"
            )
        if self.source not in ALLOWED_QUESTION_SOURCES:
            raise ValueError(f"open question source must be one of {sorted(ALLOWED_QUESTION_SOURCES)}: {self.source}")
        if self.status not in ALLOWED_QUESTION_STATUSES:
            raise ValueError(f"open question status must be one of {sorted(ALLOWED_QUESTION_STATUSES)}: {self.status}")
        if self.asked_count < 0:
            raise ValueError("open question asked_count must be >= 0")


@dataclass(frozen=True, slots=True)
class DiaryEntry:
    """A daily reflective diary entry written by the learning agent."""

    entry_id: str
    personal_model_id: str
    entry_date: str  # YYYY-MM-DD
    content: str  # markdown
    generated_at: datetime
    source_episode_ids: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)
