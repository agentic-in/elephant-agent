"""Built-in system scheduled jobs.

This module owns durable cron rows for product-owned background jobs. Execution
still belongs to the app/runtime surface that runs the cron payload.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from .runtime import CronJob


DREAM_CRON_NAME = "Nightly dream"
DREAM_CRON_SCHEDULE = "every day at 1am"
DREAM_CRON_SUMMARY = "nightly Personal Model, question, skill matching, skill evolution, and diary maintenance"
DREAM_CRON_FEATURES = "dream,questions,skill_affinity,skill_evolution,diary"


class SystemCronRuntime(Protocol):
    def list_jobs(self) -> list[CronJob] | tuple[CronJob, ...]: ...

    def create_job(
        self,
        *,
        name: str,
        schedule_text: str,
        payload: Mapping[str, Any],
    ) -> CronJob: ...

    def remove_job(self, job_id: str) -> CronJob: ...


def remove_former_diary_crons(cron_runtime: SystemCronRuntime) -> None:
    """Remove the former built-in diary cron; diary now runs inside Dream."""
    for job in cron_runtime.list_jobs():
        if job.action_kind != "learning":
            continue
        if job.payload.get("trigger") != "diary":
            continue
        name = str(getattr(job, "name", "") or "").strip().lower()
        summary = str(job.payload.get("summary") or "").strip().lower()
        if name == "daily diary" or summary == "daily diary entry for yesterday":
            cron_runtime.remove_job(job.job_id)


def ensure_dream_cron(cron_runtime: SystemCronRuntime) -> CronJob | None:
    """Create the nightly Dream consolidation cron row if it is missing."""
    remove_former_diary_crons(cron_runtime)
    existing = cron_runtime.list_jobs()
    for job in existing:
        if job.payload.get("trigger") == "dream" and job.action_kind == "learning":
            return job
    return cron_runtime.create_job(
        name=DREAM_CRON_NAME,
        schedule_text=DREAM_CRON_SCHEDULE,
        payload={
            "action_kind": "learning",
            "trigger": "dream",
            "summary": DREAM_CRON_SUMMARY,
            "metadata": {"features": DREAM_CRON_FEATURES},
        },
    )


def ensure_nightly_learning_crons(cron_runtime: SystemCronRuntime) -> None:
    """Ensure all built-in nightly learning cron rows exist."""
    ensure_dream_cron(cron_runtime)


__all__ = [
    "DREAM_CRON_FEATURES",
    "DREAM_CRON_NAME",
    "DREAM_CRON_SCHEDULE",
    "DREAM_CRON_SUMMARY",
    "ensure_dream_cron",
    "ensure_nightly_learning_crons",
    "remove_former_diary_crons",
]
