"""Tests for the shared lexical recall ranker used by internal recall paths."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


from packages.evidence import (
    RecallCandidate,
    plan_recall_query,
    rank_recall_candidates,
    render_recall_hit,
)


def _candidate(
    body: str,
    *,
    title: str = "",
    kind: str = "personal_model:style",
    when: datetime | None = None,
) -> RecallCandidate:
    return RecallCandidate(
        title=title or body[:32],
        body=body,
        kind=kind,
        when=when or datetime.now(timezone.utc),
    )


def test_exact_substring_outranks_weaker_signals() -> None:
    noise = _candidate("totally unrelated preference about colour")
    hit = _candidate("I prefer concise answers over long explanations")
    ranked = rank_recall_candidates("concise", (noise, hit), limit=3)
    assert ranked
    assert ranked[0].content == hit.body
    # noise has no token overlap and no substring — should not appear.
    assert len(ranked) == 1


def test_token_overlap_recalls_related_entries() -> None:
    # No literal substring match but the token "caching" appears in both.
    one = _candidate("Use redis caching when requests exceed 100/sec")
    two = _candidate("Our caching strategy should honour TTL")
    ranked = rank_recall_candidates("caching strategy redis", (one, two), limit=3)
    bodies = [hit.content for hit in ranked]
    assert one.body in bodies
    assert two.body in bodies


def test_cjk_fallback_picks_up_chinese_correction() -> None:
    chinese_hit = _candidate("用户更喜欢简洁的回答，不要冗长解释")
    filler = _candidate("random english note about scheduling")
    ranked = rank_recall_candidates("简洁的回答", (chinese_hit, filler), limit=2)
    assert ranked
    assert ranked[0].content == chinese_hit.body


def test_multilingual_temporal_recap_terms_are_query_operators() -> None:
    plan = plan_recall_query("最近小红书我们聊了一些啥？")
    assert plan.temporal_intent == "recent"
    assert plan.search_query == "小红书"
    assert plan_recall_query("我们最近聊了小红书什么？").search_query == "小红书"

    xhs = _candidate("小红书账号定位：女性成长、自我探索、运动。")
    inner_weather = _candidate("最近的内在天气像房间里开满标签页。")
    ranked = rank_recall_candidates("最近小红书我们聊了一些啥？", (inner_weather, xhs), limit=2)
    assert ranked
    assert ranked[0].content == xhs.body


def test_english_temporal_recap_terms_keep_topic_core() -> None:
    plan = plan_recall_query("Recently what did we discuss about xiaohongshu?")
    assert plan.temporal_intent == "recent"
    assert plan.search_query == "xiaohongshu"
    assert plan_recall_query("Recently we discussed xiaohongshu").search_query == "xiaohongshu"

    xhs = _candidate("xiaohongshu profile positioning and content planning")
    noise = _candidate("recently we discussed quiet rooms and recovery")
    ranked = rank_recall_candidates("Recently what did we discuss about xiaohongshu?", (noise, xhs), limit=2)
    assert ranked
    assert ranked[0].content == xhs.body


def test_chinese_nearest_neighbor_is_not_temporal_recent() -> None:
    plan = plan_recall_query("最近邻算法 evidence search")
    assert plan.temporal_intent == "neutral"
    assert "最近邻" in plan.search_query


def test_recency_breaks_ties() -> None:
    now = datetime.now(timezone.utc)
    older = _candidate("prefer concise", when=now - timedelta(days=90))
    newer = _candidate("prefer concise", when=now - timedelta(days=1))
    ranked = rank_recall_candidates("prefer concise", (older, newer), limit=2)
    assert ranked[0].when >= ranked[1].when


def test_empty_query_returns_recency_tail() -> None:
    now = datetime.now(timezone.utc)
    a = _candidate("older note", when=now - timedelta(days=10))
    b = _candidate("newer note", when=now - timedelta(days=1))
    ranked = rank_recall_candidates("", (a, b), limit=2)
    assert ranked[0].content == "newer note"
    assert ranked[1].content == "older note"


def test_limit_capped_and_respected() -> None:
    candidates = tuple(_candidate(f"note number {idx}") for idx in range(20))
    ranked = rank_recall_candidates("note number", candidates, limit=3)
    assert len(ranked) == 3


def test_render_hit_strips_internal_fields() -> None:
    cand = _candidate("redis caching note")
    ranked = rank_recall_candidates("redis", (cand,), limit=1)
    rendered = render_recall_hit(ranked[0])
    assert set(rendered) == {"title", "kind", "when", "content"}
    assert "score" not in rendered
    assert "evidence_id" not in rendered


def test_zero_signal_candidate_filtered() -> None:
    cand = _candidate("nothing in common at all")
    ranked = rank_recall_candidates("xyz123 unrelated token", (cand,), limit=3)
    assert ranked == ()
