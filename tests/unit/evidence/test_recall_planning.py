"""Tests for multilingual recall query planning."""

from __future__ import annotations

from packages.evidence import plan_recall_query


def test_recent_chinese_recap_extracts_topic_core() -> None:
    plan = plan_recall_query("最近小红书我们聊了一些啥？")

    assert plan.temporal_intent == "recent"
    assert plan.recall_mode == "recap"
    assert plan.query_core == "小红书"
    assert "temporal.recent" in plan.signals
    assert "mode.recap" in plan.signals


def test_recent_english_recap_extracts_topic_core() -> None:
    plan = plan_recall_query("Recently what did we discuss about xiaohongshu?")

    assert plan.temporal_intent == "recent"
    assert plan.recall_mode == "recap"
    assert plan.query_core == "xiaohongshu"


def test_unknown_language_uses_contextual_recall() -> None:
    plan = plan_recall_query("¿Qué hablamos sobre memoria?")

    assert plan.temporal_intent == "neutral"
    assert plan.recall_mode == "contextual_recall"
    assert plan.query_core == "¿Qué hablamos sobre memoria"
    assert plan.signals == ("mode.contextual_recall.default",)


def test_chinese_nearest_neighbor_is_not_recent_intent() -> None:
    plan = plan_recall_query("最近邻算法 recall search")

    assert plan.temporal_intent == "neutral"
    assert plan.recall_mode == "contextual_recall"
    assert "最近邻" in plan.query_core


def test_current_question_routes_to_verify() -> None:
    plan = plan_recall_query("现在小红书账号粉丝数是不是最新？")

    assert plan.temporal_intent == "current"
    assert plan.recall_mode == "verify"
    assert plan.query_core == "小红书账号粉丝数"


def test_recall_blocks_are_removed_before_planning() -> None:
    plan = plan_recall_query("小红书\n\nCurrent-turn recall support:\n- [x] old\n")

    assert plan.query_core == "小红书"


def test_list_recent_when_recap_has_no_topic_core() -> None:
    plan = plan_recall_query("最近我们聊了啥？")

    assert plan.temporal_intent == "recent"
    assert plan.recall_mode == "list_recent"
    assert plan.query_core == ""
