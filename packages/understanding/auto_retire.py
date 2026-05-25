"""Automatic retirement of stale PM facts based on volatility thresholds.

Called by a daily cron job. Scans all active facts with situational/ephemeral
volatility and retires those exceeding their age + idle thresholds.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import logging
from typing import Any

from .temporal_policy import should_auto_retire

LOGGER = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def retire_stale_facts(repository: Any, *, now: datetime | None = None) -> int:
    """Scan active facts and retire those exceeding volatility thresholds.

    Returns the number of facts retired.
    """
    effective_now = now or _utc_now()
    retired_count = 0

    # Load all personal model IDs that have facts
    list_facts = getattr(repository, "list_personal_model_facts", None)
    upsert_fact = getattr(repository, "upsert_personal_model_fact", None)
    if not callable(list_facts) or not callable(upsert_fact):
        return 0

    # Get all active facts across all personal models
    # The repository method requires personal_model_id; use the canonical one
    list_pm_ids = getattr(repository, "list_personal_model_ids", None)
    if callable(list_pm_ids):
        pm_ids = list_pm_ids()
    else:
        # Fallback: use the default single-user ID
        pm_ids = ("you",)

    for pm_id in pm_ids:
        try:
            facts = list_facts(personal_model_id=pm_id, status="active")
        except Exception:
            LOGGER.warning(
                "failed to load active facts for auto-retire scan",
                extra={"personal_model_id": pm_id},
                exc_info=True,
            )
            continue

        for fact in facts:
            metadata = dict(fact.metadata or {})
            volatility = metadata.get("volatility", "situational")
            if volatility == "permanent":
                continue
            if not should_auto_retire(volatility, fact.committed_at, fact.last_accessed_at, effective_now):
                continue
            # Retire the fact
            upsert_fact(
                replace(
                    fact,
                    status="retired",
                    metadata={
                        **metadata,
                        "retired_by": "auto_retire",
                        "retired_reason": f"exceeded {volatility} staleness threshold",
                        "retired_at": effective_now.isoformat(),
                    },
                )
            )
            retired_count += 1

    return retired_count
