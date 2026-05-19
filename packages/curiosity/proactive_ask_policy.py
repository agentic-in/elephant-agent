"""Proactive ask policy — simplified numeric-parameter implementation.

Replaces the old tier-based system (ADR-0004) with direct numeric config:
  idle_threshold_minutes, daily_max, quiet_hours.

The caller provides concrete values; this module just evaluates the decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from packages.contracts import OpenQuestion


@dataclass(frozen=True, slots=True)
class AskDecision:
    should_ask: bool
    reason: str
    selected: OpenQuestion | None = None


def should_ask(
    *,
    enabled: bool = True,
    idle_minutes: float,
    idle_threshold_minutes: int,
    daily_max: int,
    asks_today: int,
    quiet_hours: tuple[int, int],
    current_hour: int,
    candidate_questions: Sequence[OpenQuestion],
    max_asked_count: int = 2,
) -> AskDecision:
    """Decide whether to ask a proactive question right now.

    All parameters are concrete numeric values — no tier lookup, no config parsing.

    Args:
        enabled: Master switch. If False, always skip.
        idle_minutes: How long the user has been idle (minutes).
        idle_threshold_minutes: Minimum idle time before asking.
        daily_max: Maximum questions per day.
        asks_today: How many have been asked today already.
        quiet_hours: (start_hour, end_hour) local time, 24h clock. Don't ask inside this range.
        current_hour: User's current local hour (0-23).
        candidate_questions: Open questions eligible for asking.
        max_asked_count: Dismiss questions asked more than this many times.

    Returns:
        AskDecision with should_ask, reason, and selected question (if any).
    """
    if not enabled:
        return AskDecision(False, "disabled")

    # 1. Quiet hours (range wraps across midnight when start > end).
    start, end = quiet_hours
    if start < end:
        in_quiet = start <= current_hour < end
    else:
        in_quiet = current_hour >= start or current_hour < end
    if in_quiet:
        return AskDecision(False, "quiet_hours")

    # 2. Daily max.
    if asks_today >= daily_max:
        return AskDecision(False, "daily_max_reached")

    # 3. Idle threshold.
    if idle_minutes < idle_threshold_minutes:
        return AskDecision(False, f"idle_{int(idle_minutes)}m_below_{idle_threshold_minutes}m")

    # 4. Select highest-priority eligible question.
    eligible = sorted(
        [q for q in candidate_questions if q.status == "open" and q.asked_count < max_asked_count],
        key=lambda q: q.priority,
        reverse=True,
    )
    if not eligible:
        return AskDecision(False, "no_eligible_questions")

    return AskDecision(True, "ready", selected=eligible[0])


__all__ = ["AskDecision", "should_ask"]
