"""Volatility-based temporal policy for Personal Model facts.

Each fact carries a `volatility` annotation in its metadata that determines
how it ages:

- permanent:    Never decays. Identity, core preferences, personality traits.
- situational:  60-day half-life. Current job, city, active projects, life phases.
- ephemeral:    14-day half-life. This week's mood, short-term plans, recent events.

The freshness score combines:
- Time since last access (or commit if never accessed)
- Access count as a reinforcement signal (frequently used facts decay slower)
"""

from __future__ import annotations

from datetime import datetime

VOLATILITY_HALF_LIVES: dict[str, float | None] = {
    "permanent": None,
    "situational": 60.0,
    "ephemeral": 14.0,
}

# Auto-retirement thresholds: (max_age_days, max_idle_days)
# A fact is retired when BOTH conditions are met:
# - committed_at is older than max_age_days
# - last_accessed_at (or committed_at if never accessed) is older than max_idle_days
_AUTO_RETIRE_THRESHOLDS: dict[str, tuple[int, int] | None] = {
    "permanent": None,
    "situational": (240, 90),
    "ephemeral": (56, 30),
}


def freshness_score(
    volatility: str,
    committed_at: datetime,
    last_accessed_at: datetime | None,
    access_count: int,
    now: datetime,
) -> float:
    """Compute freshness score in [-1.0, 0.0] for search re-ranking.

    Returns 0.0 for permanent facts (always fresh).
    Returns negative values for facts that have aged past their half-life.
    """
    half_life = VOLATILITY_HALF_LIVES.get(volatility)
    if half_life is None:
        return 0.0
    # Age from last access — a fact that keeps being used stays fresh
    reference = last_accessed_at or committed_at
    age_days = max(0.0, (now - reference).total_seconds() / 86400.0)
    # Linear decay clamped to [-1, 0]
    decay = -1.0 * min(1.0, age_days / (half_life * 2.0))
    # Access count reinforcement: historically important facts decay slower (cap 40%)
    reinforcement = min(0.4, access_count * 0.05)
    return decay * (1.0 - reinforcement)


def auto_retire_threshold(volatility: str) -> tuple[int, int] | None:
    """Return (max_age_days, max_idle_days) or None if never auto-retires."""
    return _AUTO_RETIRE_THRESHOLDS.get(volatility)


def should_auto_retire(
    volatility: str,
    committed_at: datetime,
    last_accessed_at: datetime | None,
    now: datetime,
) -> bool:
    """Whether a fact exceeds its auto-retirement threshold."""
    threshold = auto_retire_threshold(volatility)
    if threshold is None:
        return False
    max_age_days, max_idle_days = threshold
    age_days = (now - committed_at).total_seconds() / 86400.0
    reference = last_accessed_at or committed_at
    idle_days = (now - reference).total_seconds() / 86400.0
    return age_days > max_age_days and idle_days > max_idle_days


def infer_volatility_from_lens(lens: str, topic: str) -> str:
    """Infer volatility from lens and topic for historical data migration.

    This function exists ONLY for migrating pre-volatility facts. New facts
    must be annotated at write time by the learning agent.
    """
    if lens == "trait":
        return "permanent"
    if lens == "rapport":
        return "permanent"
    if lens == "chapter":
        return "situational"
    # knowledge: infer from topic prefix
    if topic.startswith("knowledge.identity.") or topic.startswith("knowledge.preference.hobbies."):
        return "permanent"
    # Everything else defaults to situational (safer than permanent)
    return "situational"
