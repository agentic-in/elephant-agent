"""Personal Model fact metrics used by runtime growth scoring."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apps.cli.runtime import CliRuntime


@dataclass(frozen=True, slots=True)
class PersonalModelGrowthMetrics:
    fact_count: int
    lens_counts: tuple[tuple[str, int], ...]
    topic_count: int
    new_fact_count: int
    updated_fact_count: int
    supported_fact_count: int
    evidence_ref_count: int
    high_confidence_fact_count: int
    rich_fact_count: int
    average_confidence: float


def active_personal_model_facts_for_growth(
    runtime: "CliRuntime",
    *,
    personal_model_id: str,
) -> tuple[Any, ...]:
    list_facts = getattr(runtime.repository, "list_personal_model_facts", None)
    if not callable(list_facts):
        return ()
    try:
        return tuple(list_facts(personal_model_id=personal_model_id, status="active"))
    except Exception:
        return ()


def personal_model_growth_metrics(
    *,
    facts: tuple[Any, ...],
    since: datetime | None,
) -> PersonalModelGrowthMetrics:
    lens_counts = {lens: 0 for lens in ("identity", "world", "pulse", "journey")}
    topics: set[str] = set()
    confidence_total = 0.0
    high_confidence = 0
    rich_facts = 0
    supported_facts = 0
    evidence_refs = 0
    new_facts = 0
    updated_facts = 0
    since_utc = _aware_utc(since) if since is not None else None
    for fact in facts:
        metadata = dict(getattr(fact, "metadata", {}) or {})
        topic = _fact_topic(fact, metadata)
        lens = _fact_lens(fact, metadata, topic=topic)
        if lens in lens_counts:
            lens_counts[lens] += 1
        if topic:
            topics.add(topic)
        confidence = _fact_confidence(fact)
        confidence_total += confidence
        if confidence >= 0.8:
            high_confidence += 1
        text = str(getattr(fact, "text", "") or "").strip()
        if len(text.split()) >= 8 or len(text) >= 80:
            rich_facts += 1
        fact_evidence_refs = len(tuple(getattr(fact, "source_episode_ids", ()) or ()))
        evidence_refs += fact_evidence_refs
        if fact_evidence_refs > 0:
            supported_facts += 1
        committed_at = _aware_utc(getattr(fact, "committed_at", None))
        changed_this_turn = since_utc is not None and committed_at is not None and committed_at > since_utc
        if changed_this_turn:
            new_facts += 1
            action = str(metadata.get("action") or "").strip().lower()
            if getattr(fact, "supersedes_fact_id", None) or action in {
                "correct",
                "restore",
            }:
                updated_facts += 1
    fact_count = len(facts)
    return PersonalModelGrowthMetrics(
        fact_count=fact_count,
        lens_counts=tuple((lens, lens_counts[lens]) for lens in ("identity", "world", "pulse", "journey")),
        topic_count=len(topics),
        new_fact_count=new_facts,
        updated_fact_count=updated_facts,
        supported_fact_count=supported_facts,
        evidence_ref_count=evidence_refs,
        high_confidence_fact_count=high_confidence,
        rich_fact_count=rich_facts,
        average_confidence=(confidence_total / fact_count) if fact_count else 0.0,
    )


def _fact_confidence(fact: Any) -> float:
    try:
        confidence = float(getattr(fact, "confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, confidence))


def _fact_topic(fact: Any, metadata: Mapping[str, Any]) -> str:
    topic = str(metadata.get("topic") or "").strip()
    if topic:
        return topic
    return str(getattr(fact, "fact_id", "") or "").strip()


def _fact_lens(fact: Any, metadata: Mapping[str, Any], *, topic: str) -> str:
    if topic:
        prefix = topic.split(".", 1)[0].strip().lower()
        if prefix in {"identity", "world", "pulse", "journey"}:
            return prefix
    metadata_lens = str(metadata.get("lens") or "").strip().lower()
    if metadata_lens in {"identity", "world", "pulse", "journey"}:
        return metadata_lens
    return str(getattr(fact, "lens", "") or "").strip().lower()


def _aware_utc(moment: Any) -> datetime | None:
    if not isinstance(moment, datetime):
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)
