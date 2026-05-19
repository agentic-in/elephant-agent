"""Intent-aware recall reranking.

Reranks hits from HybridSemanticSearcher by combining the fused relevance
score with a recency signal adjusted by query temporal intent. Semantic
relevance (the 5-signal RRF fusion from HybridSemanticSearcher) is primary;
recency breaks close calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .recall_support import RecallHit
from .recall_planning import RecallQueryPlan

__all__ = [
    "RecallRankedHit",
    "rerank_recall_hits",
    "score_recall_hit",
]

# How much recency influences final score, keyed by temporal intent.
# Positive = prefer recent; negative = prefer older.
RECENCY_WEIGHTS: dict[str, float] = {
    "current": 0.15,
    "recent": 0.10,
    "neutral": 0.05,
    "historical": -0.03,
}


@dataclass(frozen=True, slots=True)
class RecallRankedHit:
    hit: RecallHit
    final_score: float
    semantic_score: float
    time_score: float


def _hit_when(hit: RecallHit) -> datetime | None:
    if hit.when_datetime is not None:
        when = hit.when_datetime
        return when if when.tzinfo is not None else when.replace(tzinfo=timezone.utc)
    raw = str(hit.when or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def score_recall_hit(hit: RecallHit, *, plan: RecallQueryPlan, now: datetime) -> RecallRankedHit:
    semantic_score = float(hit.score or 0.0)
    when = _hit_when(hit)
    if when is None:
        time_score = 0.0
    else:
        age_days = max(0.0, (now.timestamp() - when.timestamp()) / 86400.0)
        recency = 1.0 / (1.0 + age_days / 30.0)
        weight = RECENCY_WEIGHTS.get(plan.temporal_intent, 0.05)
        if weight < 0:
            # Historical intent: prefer older hits
            time_score = abs(weight) * (1.0 - recency)
        else:
            time_score = weight * recency
    final_score = semantic_score + time_score
    return RecallRankedHit(
        hit=hit,
        final_score=final_score,
        semantic_score=semantic_score,
        time_score=time_score,
    )


def rerank_recall_hits(
    hits: tuple[RecallHit, ...],
    *,
    plan: RecallQueryPlan,
    now: datetime,
    limit: int | None = None,
) -> tuple[RecallRankedHit, ...]:
    ranked = sorted(
        (score_recall_hit(hit, plan=plan, now=now) for hit in hits),
        key=lambda item: (
            -item.final_score,
            item.hit.title.casefold(),
            item.hit.content.casefold(),
        ),
    )
    if limit is not None:
        return tuple(ranked[: max(0, int(limit))])
    return tuple(ranked)
