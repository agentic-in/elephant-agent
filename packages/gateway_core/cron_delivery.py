"""Delivery policy for cron execution results on messaging surfaces."""

from __future__ import annotations

from packages.cron import CronJobExecution


def cron_execution_should_deliver(execution: CronJobExecution) -> bool:
    """Return whether a cron execution result should be sent to IM adapters."""
    if execution.job.action_kind == "learning":
        return False
    summary = execution.summary.strip()
    return bool(summary) and summary != "[SILENT]"


__all__ = ["cron_execution_should_deliver"]
