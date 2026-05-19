"""OpenQuestion generator — contextual and ambiguity sources.

Questions are now primarily created by the background learning agent via
tool.personal_model.questions. This module provides programmatic helpers
for creating questions from structured seeds (e.g., during episode_close
extract or when the runtime detects ambiguity).

The legacy coverage_gap generator that relied on a static YAML question
bank has been removed — coverage gaps are now identified by the learning
agent's inspect-before-write flow.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence
from uuid import uuid4

from packages.contracts import OpenQuestion


def _make_question_id(personal_model_id: str, topic: str) -> str:
    return f"oq:{personal_model_id}:{topic}:{uuid4().hex[:8]}"


def generate_contextual_questions(
    *,
    personal_model_id: str,
    seeds: Sequence[dict],
    now: datetime | None = None,
) -> tuple[OpenQuestion, ...]:
    """Turn extract-time seeds into OpenQuestion rows.

    Each seed dict carries the keys: lens, topic, text, rationale,
    priority, sensitivity. Used during episode_close to capture
    contextual hooks while the path is still in view.
    """
    timestamp = now or datetime.now(timezone.utc)
    questions: list[OpenQuestion] = []
    for seed in seeds:
        lens = str(seed.get("lens", "")).strip()
        topic = str(seed.get("topic") or seed.get("sub_lens", "")).strip()
        text = str(seed.get("text", "")).strip()
        if not lens or not text:
            continue
        questions.append(
            OpenQuestion(
                question_id=_make_question_id(personal_model_id, topic or "contextual"),
                personal_model_id=personal_model_id,
                lens=lens,
                sub_lens=topic,
                text=text,
                rationale=str(seed.get("rationale", "")).strip() or "contextual follow-up",
                priority=float(seed.get("priority", 0.5)),
                sensitivity=str(seed.get("sensitivity", "low")).strip().lower(),
                source="contextual",
                created_at=timestamp,
                status="open",
                metadata={
                    "seed_text": text,
                    "question_intent": str(
                        seed.get("intent") or seed.get("rationale") or "follow up while context is steady"
                    ).strip(),
                },
            )
        )
    return tuple(questions)


def generate_ambiguity_questions(
    *,
    personal_model_id: str,
    conflicts: Sequence[dict],
    now: datetime | None = None,
) -> tuple[OpenQuestion, ...]:
    """Turn unresolvable conflicts into targeted clarifying questions.

    Each conflict dict carries: lens, topic (or sub_lens), summary, rationale, priority.
    """
    if not conflicts:
        return ()
    timestamp = now or datetime.now(timezone.utc)
    questions: list[OpenQuestion] = []
    for conflict in conflicts:
        lens = str(conflict.get("lens", "")).strip()
        topic = str(conflict.get("topic") or conflict.get("sub_lens", "")).strip()
        summary = str(conflict.get("summary", "")).strip()
        if not lens or not topic or not summary:
            continue
        questions.append(
            OpenQuestion(
                question_id=_make_question_id(personal_model_id, topic),
                personal_model_id=personal_model_id,
                lens=lens,
                sub_lens=topic,
                text=summary,
                rationale=str(conflict.get("rationale") or summary).strip(),
                priority=float(conflict.get("priority", 0.7)),
                sensitivity=str(conflict.get("sensitivity", "medium")).strip().lower(),
                source="ambiguity",
                created_at=timestamp,
                status="open",
                metadata={
                    "conflict_summary": summary,
                },
            )
        )
    return tuple(questions)


__all__ = [
    "generate_contextual_questions",
    "generate_ambiguity_questions",
]
