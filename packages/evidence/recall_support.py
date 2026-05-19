"""Shared lexical recall helper for internal current-turn recall paths.

Ranks committed Personal Model facts, State facts, and episode exit
summaries against a user query in a language-agnostic way (works for English
tokens AND CJK substrings), then returns human-readable hits with no record
ids. CLI, API, and gateway surfaces all funnel through this module so recall
behaves identically on every transport.

Design:
  - tier 0: exact lowercase substring match (fast confident hit)
  - tier 1: token-overlap score on `[A-Za-z0-9]+` tokens (English-ish)
  - tier 2: 3-char n-gram Jaccard on compacted alnum text (CJK fallback)
  - final rank = tier_weight * signal + small recency boost

A future hook exposes a `hybrid_searcher` slot so R7 (episode-summary
indexing) can inject a populated HybridSemanticSearcher and get vector +
BM25 fused results without touching callers.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import re

from .recall_planning import RecallQueryPlan, plan_recall_query


__all__ = [
    "RecallCandidate",
    "RecallHit",
    "RecallQueryPlan",
    "plan_recall_query",
    "rank_recall_candidates",
    "render_recall_hit",
]


_TOKEN_RE = re.compile(r"[A-Za-z0-9_./:-]+")
_COMPACT_TEXT_RE = re.compile(r"[a-z0-9\u3400-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]+")


@dataclass(frozen=True, slots=True)
class RecallCandidate:
    """One candidate chunk to rank against the query.

    The candidate is a neutral wrapper — it hides PM/State fact vs episode
    storage differences from the ranker, which only needs a text body, a
    timestamp, and display metadata.
    """

    title: str
    body: str
    kind: str
    when: datetime | None
    extra_metadata: Mapping[str, str] = None  # type: ignore[assignment]
    # LLM-rated significance in [0.0, 1.0]. Defaults to 0.5 for
    # back-compat with legacy wrappers that don't plumb importance
    # through (episode summaries, synthetic candidates, etc.). See
    # `_score_candidate` for how this feeds the final ranking.
    importance: float = 0.5

    def display_when(self) -> str:
        if self.when is None:
            return ""
        return self.when.strftime("%Y-%m-%d")

    def timestamp(self) -> float:
        if self.when is None:
            return 0.0
        return self.when.timestamp()


@dataclass(frozen=True, slots=True)
class RecallHit:
    title: str
    content: str
    kind: str
    when: str
    score: float
    when_datetime: datetime | None = None
    extra_metadata: Mapping[str, str] = None  # type: ignore[assignment]


def _tokens(text: str) -> set[str]:
    return {match.group(0).lower() for match in _TOKEN_RE.finditer(text) if match.group(0)}


def _alnum_compact(text: str) -> str:
    return "".join(_COMPACT_TEXT_RE.findall(text.lower()))


def _char_ngrams(text: str, *, width: int = 3) -> set[str]:
    if not text:
        return set()
    if len(text) <= width:
        return {text}
    return {text[i : i + width] for i in range(0, len(text) - width + 1)}


def _recency_weight(temporal_intent: str) -> float:
    if temporal_intent in {"recent", "current"}:
        return 0.16
    if temporal_intent == "historical":
        return 0.0
    return 0.05


def _score_candidate(
    query: str,
    query_tokens: set[str],
    query_ngrams: set[str],
    candidate: RecallCandidate,
    *,
    now_ts: float,
    temporal_intent: str,
) -> float:
    if not candidate.body.strip():
        return 0.0
    body_lower = candidate.body.lower()
    signal = 0.0
    # Tier 0 — exact substring of the raw user query. Strong confident hit.
    if query and query.lower() in body_lower:
        signal += 1.0
    # Tier 1 — token overlap (English-ish words, camelCase, filepaths).
    if query_tokens:
        body_tokens = _tokens(candidate.body)
        overlap = len(query_tokens & body_tokens)
        if overlap:
            signal += 0.35 * (overlap / max(len(query_tokens), 1))
    # Tier 2 — CJK fallback: 3-char alnum ngram Jaccard.
    if query_ngrams:
        body_ngrams = _char_ngrams(_alnum_compact(candidate.body))
        if body_ngrams:
            jaccard = len(query_ngrams & body_ngrams) / float(len(query_ngrams | body_ngrams))
            signal += 0.25 * jaccard
    if signal <= 0.0:
        return 0.0
    # Small recency nudge — halves weight roughly every 30 days.
    if candidate.when is not None:
        age_days = max(0.0, (now_ts - candidate.timestamp()) / 86400.0)
        recency = 1.0 / (1.0 + age_days / 30.0)
    else:
        recency = 0.5
    # Importance is an LLM-rated significance score in [0.0, 1.0]. We
    # nudge (not dominate) — a high-importance entry lifts a marginal
    # lexical hit, but a zero-signal entry still scores 0. Weight of 0.15
    # chosen so a 1.0-importance entry adds roughly as much as the
    # CJK-ngram tier at maximum jaccard, preserving the hybrid balance.
    importance = max(0.0, min(1.0, float(getattr(candidate, "importance", 0.5))))
    return signal + _recency_weight(temporal_intent) * recency + 0.15 * importance


def rank_recall_candidates(
    query: str,
    candidates: Iterable[RecallCandidate],
    *,
    limit: int,
    now: datetime | None = None,
) -> tuple[RecallHit, ...]:
    """Rank candidates by hybrid multi-signal score; return human hits.

    When the query is empty we still return the most recent candidates, which
    keeps `recall_evidence(query="", scope="personal_model")` behaving like a
    tailed-list over committed Personal Model facts.
    """
    capped = max(1, int(limit or 1))
    now_ts = (now or datetime.now(timezone.utc)).timestamp()
    plan = plan_recall_query(query)
    q = plan.search_query.strip()
    q_tokens = _tokens(q)
    q_ngrams = _char_ngrams(_alnum_compact(q))
    scored: list[tuple[float, RecallCandidate]] = []
    if q:
        for candidate in candidates:
            score = _score_candidate(
                q,
                q_tokens,
                q_ngrams,
                candidate,
                now_ts=now_ts,
                temporal_intent=plan.temporal_intent,
            )
            if score > 0.0:
                scored.append((score, candidate))
        scored.sort(key=lambda item: (-item[0], -item[1].timestamp()))
    else:
        # Empty query: return the most recent, scored by recency only.
        for candidate in candidates:
            scored.append((candidate.timestamp(), candidate))
        scored.sort(key=lambda item: -item[0])
    return tuple(
        RecallHit(
            title=candidate.title or candidate.kind or "<untitled>",
            content=candidate.body,
            kind=candidate.kind,
            when=candidate.display_when(),
            score=score,
            when_datetime=candidate.when,
            extra_metadata=candidate.extra_metadata,
        )
        for score, candidate in scored[:capped]
    )


def render_recall_hit(hit: RecallHit) -> dict[str, object]:
    metadata = dict(hit.extra_metadata or {})
    payload = {
        "title": hit.title[:72].strip() or hit.kind or "<untitled>",
        "kind": hit.kind,
        "when": hit.when,
        "content": hit.content,
    }
    for key in ("document_id", "episode_id", "loop_id", "step_id", "source_id"):
        value = str(metadata.get(key) or "").strip()
        if value:
            payload[key] = value
    return payload
