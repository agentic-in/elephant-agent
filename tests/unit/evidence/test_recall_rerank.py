"""Tests for intent-aware recall reranking."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from packages.evidence import (
    RecallHit,
    plan_recall_query,
    rerank_recall_hits,
    score_recall_hit,
)

_NOW = datetime(2026, 5, 8, tzinfo=timezone.utc)


def _hit(
    content: str,
    *,
    score: float = 0.08,
    age_days: int = 0,
    kind: str = "episode_summary",
    metadata: dict[str, str] | None = None,
) -> RecallHit:
    when = _NOW - timedelta(days=age_days)
    return RecallHit(
        title=content[:32],
        content=content,
        kind=kind,
        when=when.strftime("%Y-%m-%d"),
        score=score,
        when_datetime=when,
        extra_metadata=metadata or {},
    )


def test_recent_recap_prefers_recent_episode_when_semantic_scores_are_close() -> None:
    plan = plan_recall_query("最近小红书我们聊了啥？")
    older = _hit("三个月前讨论小红书旧定位。", score=0.080, age_days=90)
    newer = _hit("昨天讨论小红书主页结构。", score=0.079, age_days=1)

    ranked = rerank_recall_hits((older, newer), plan=plan, now=_NOW)

    assert ranked[0].hit is newer
    assert ranked[0].time_score > ranked[1].time_score


def test_historical_intent_prefers_older() -> None:
    plan = plan_recall_query("当初为什么改 recall 注入方式？")
    older = _hit("旧的架构决策原因。", score=0.090, age_days=365)
    newer = _hit("新的相似讨论。", score=0.080, age_days=1)

    ranked = rerank_recall_hits((newer, older), plan=plan, now=_NOW)

    # Older hit wins: higher semantic + historical time boost for age
    assert ranked[0].hit is older


def test_current_intent_strongly_boosts_recent() -> None:
    plan = plan_recall_query("现在小红书粉丝数是多少？")
    fresh = _hit("小红书粉丝数 10+。", score=0.070, age_days=1)
    stale = _hit("小红书粉丝数 9。", score=0.071, age_days=60)

    ranked = rerank_recall_hits((stale, fresh), plan=plan, now=_NOW)

    # Fresh hit wins despite slightly lower semantic score
    assert ranked[0].hit is fresh
    assert ranked[0].time_score > ranked[1].time_score


def test_neutral_intent_minimal_recency_influence() -> None:
    plan = plan_recall_query("小红书定位")
    older = _hit("旧定位。", score=0.15, age_days=90)
    newer = _hit("新定位。", score=0.085, age_days=1)

    ranked = rerank_recall_hits((older, newer), plan=plan, now=_NOW)

    # Semantic dominates when intent is neutral; older wins with significantly higher score
    assert ranked[0].hit is older


def test_limit_caps_results() -> None:
    plan = plan_recall_query("test")
    hits = tuple(_hit(f"hit {i}", age_days=i) for i in range(10))
    ranked = rerank_recall_hits(hits, plan=plan, now=_NOW, limit=3)
    assert len(ranked) == 3


def test_no_when_datetime_gets_zero_time_score() -> None:
    plan = plan_recall_query("最近")
    hit = RecallHit(
        title="no date",
        content="no date content",
        kind="episode_summary",
        when="",
        score=0.5,
        when_datetime=None,
        extra_metadata={},
    )
    scored = score_recall_hit(hit, plan=plan, now=_NOW)
    assert scored.time_score == 0.0
    assert scored.final_score == 0.5
