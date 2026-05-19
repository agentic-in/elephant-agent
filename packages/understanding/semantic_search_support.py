"""Semantic search helpers for Personal Model claim lookup."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from packages.contracts import Fact
from packages.semantic_index import SemanticSearchQuery


def _clean(value: object) -> str:
    return str(value or "").strip()


def _topic_matches_filter(fact: Fact, topic_filter: str) -> bool:
    fact_topic = _clean((fact.metadata or {}).get("topic"))
    return fact_topic == topic_filter or fact_topic.startswith(f"{topic_filter}.")


def claim_ref_from_match(match: Any) -> str:
    entry = getattr(match, "semantic_index_entry", None)
    metadata = dict(getattr(entry, "metadata", {}) or {})
    return str(metadata.get("claim_ref") or getattr(entry, "source_id", "") or "").strip()


def rank_facts_by_semantic_queries(
    semantic_searcher: Any,
    queries: tuple[str, ...],
    *,
    pm_id: str,
    facts_by_ref: Mapping[str, Fact],
    query_vector: Callable[[str], tuple[tuple[float, ...], int | None]],
    limit: int,
) -> list[Fact]:
    """Run query plus variants through semantic search and fuse by claim ref."""
    scored_refs: dict[str, tuple[float, int]] = {}
    order = 0
    for search_text in queries:
        vector, dimensions = query_vector(search_text)
        query_kwargs: dict[str, object] = {
            "text": search_text,
            "owner_scope": "personal_model",
            "personal_model_id": pm_id,
            "limit": max(limit * 3, 30),
        }
        if vector and dimensions is not None:
            query_kwargs["vector"] = vector
            query_kwargs["dimensions"] = dimensions
        try:
            matches = semantic_searcher.search(SemanticSearchQuery(**query_kwargs))
        except Exception:
            matches = ()
        for match in matches:
            ref = claim_ref_from_match(match)
            if ref not in facts_by_ref:
                continue
            score = float(getattr(match, "score", 0.0) or 0.0)
            if ref in scored_refs:
                previous_score, previous_order = scored_refs[ref]
                scored_refs[ref] = (previous_score + score, previous_order)
            else:
                scored_refs[ref] = (score, order)
                order += 1
    return [
        facts_by_ref[ref]
        for ref, (_score, _order) in sorted(
            scored_refs.items(),
            key=lambda item: (-item[1][0], item[1][1], item[0]),
        )
    ]


def fallback_pm_search(
    queries: tuple[str, ...],
    *,
    facts: tuple[Fact, ...],
    topic: str,
    limit: int,
) -> tuple[tuple[Fact, ...], str]:
    """Fallback keyword search when HybridSemanticSearcher is unavailable."""
    query_text = " ".join(queries).lower()
    query_tokens = set(query_text.split())
    scored: list[tuple[float, Fact]] = []
    for fact in facts:
        fact_topic = _clean((fact.metadata or {}).get("topic"))
        score = 0.0
        if topic and fact_topic == topic:
            score += 100.0
        elif topic and topic in fact_topic:
            score += 50.0
        fact_text = f"{fact.lens} {fact_topic} {fact.text}".lower()
        if query_text in fact_text:
            score += 80.0
        else:
            fact_tokens = set(fact_text.split())
            overlap = len(query_tokens & fact_tokens)
            if overlap:
                score += 40.0 * (overlap / max(len(query_tokens), 1))
        if score > 0.0:
            scored.append((score, fact))
    scored.sort(key=lambda item: (-item[0], -item[1].committed_at.timestamp()))
    selected = tuple(fact for _, fact in scored[:limit])
    if not selected:
        return (), "no_match"
    return selected, "strong_match" if scored[0][0] >= 50.0 else "weak_match"


def keyword_boost(
    queries: tuple[str, ...],
    *,
    facts: tuple[Fact, ...],
    exclude_refs: set[str],
    limit: int = 10,
) -> list[Fact]:
    """Find facts matching query tokens when semantic search misses."""
    query_text = " ".join(queries).lower()
    query_tokens = set(query_text.split())
    if not query_tokens:
        return []
    scored: list[tuple[float, Fact]] = []
    for fact in facts:
        if fact.fact_id in exclude_refs:
            continue
        fact_topic = _clean((fact.metadata or {}).get("topic"))
        fact_text = f"{fact.lens} {fact_topic} {fact.text}".lower()
        if query_text in fact_text:
            scored.append((80.0, fact))
            continue
        fact_tokens = set(fact_text.split())
        overlap = len(query_tokens & fact_tokens)
        if overlap >= 2 or (overlap == 1 and len(query_tokens) == 1):
            score = 40.0 * (overlap / max(len(query_tokens), 1))
            scored.append((score, fact))
    scored.sort(key=lambda item: -item[0])
    return [fact for _, fact in scored[:limit]]
