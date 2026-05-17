"""Async task loops for the unified Elephant daemon."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger("elephant.daemon")


# ── Cron Scheduler ─────────────────────────────────────────────

async def cron_scheduler_loop(
    *,
    cli_state_dir: Path,
    state_dir: Path,
    is_running: Callable[[], bool],
    interval_seconds: float = 60.0,
) -> None:
    """Async cron scheduler: same logic as ``run_cron_scheduler_loop`` but using ``asyncio.sleep``."""
    from apps.gateway.cron_service import (
        build_gateway_cron_delivery_callback,
        cron_execution_should_deliver,
        run_cron_scheduler_loop,
    )
    from apps.cli.runtime import CliRuntime

    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be greater than zero")

    runtime = CliRuntime.create(state_dir=cli_state_dir)
    delivery_callback = build_gateway_cron_delivery_callback(
        state_dir=str(state_dir),
        cli_state_dir=str(cli_state_dir),
    )
    logger.info("cron scheduler started (interval=%gs)", interval_seconds)

    last_maintenance_at = 0.0
    last_proactive_ask_at = 0.0
    tick_count = 0

    while is_running():
        tick_count += 1
        try:
            executions = runtime.run_due_cron_jobs_for_scheduler()
            if executions:
                for execution in executions:
                    logger.info(
                        "cron %s: %s %s - %s",
                        execution.outcome,
                        execution.job.job_id,
                        execution.job.name,
                        execution.summary,
                    )
                    if delivery_callback is not None and cron_execution_should_deliver(execution):
                        try:
                            delivery_callback(execution.job, execution)
                        except Exception as exc:
                            logger.error("cron delivery failed for %s: %s", execution.job.job_id, exc)
            elif tick_count % 10 == 0:
                logger.debug("cron tick #%d: no due jobs", tick_count)
        except Exception as exc:
            logger.error("cron tick failed: %s", exc)

        # Daily maintenance (auto-retire stale facts)
        now_ts = time.time()
        if now_ts - last_maintenance_at > 86400:
            try:
                from packages.understanding.auto_retire import retire_stale_facts
                retired = retire_stale_facts(runtime.repository)
                if retired:
                    logger.info("cron auto-retire: %d stale fact(s) retired", retired)
                last_maintenance_at = now_ts
            except Exception as exc:
                logger.error("cron auto-retire failed: %s", exc)
                last_maintenance_at = now_ts

        # Proactive ask
        if now_ts - last_proactive_ask_at > 60:
            last_proactive_ask_at = now_ts
            try:
                _run_proactive_ask_tick(cli_state_dir, delivery_callback)
            except Exception as exc:
                logger.error("cron proactive-ask failed: %s", exc)

        await asyncio.sleep(interval_seconds)


def _run_proactive_ask_tick(cli_state_dir: Path, delivery_callback) -> None:
    """Run proactive ask tick for every configured adapter."""
    from apps.gateway.cron_service import CONFIGURED_IM_ADAPTERS
    from packages.runtime_config import (
        global_config_path_for_state_dir,
        load_global_config,
        personal_model_question_config_from_global,
    )

    config_path = global_config_path_for_state_dir(cli_state_dir)
    config = load_global_config(config_path, state_dir=cli_state_dir)
    question_config = personal_model_question_config_from_global(config)
    proactive_config = question_config.get("proactive_ask")
    if not isinstance(proactive_config, dict) or proactive_config.get("enabled") is False:
        return

    from apps.gateway.proactive_ask_job import run_proactive_ask_tick
    from apps.gateway.runtime import build_gateway_app

    app, outbound_queue, _ = build_gateway_app(state_dir=str(cli_state_dir))
    for adapter_id in CONFIGURED_IM_ADAPTERS:
        try:
            result = run_proactive_ask_tick(
                app=app,
                adapter_id=adapter_id,
                outbound_queue=outbound_queue,
                config=proactive_config,
            )
            if result.enqueued:
                logger.info("cron proactive-ask %s: delivered %d question(s)", adapter_id, result.enqueued)
        except Exception as exc:
            logger.error("cron proactive-ask %s failed: %s", adapter_id, exc)


# ── Supervisor ──────────────────────────────────────────────────

async def supervisor_loop(
    *,
    state_dir: Path,
    is_running: Callable[[], bool],
    interval_seconds: float = 30.0,
    heartbeat_stale_ttl_seconds: float = 180.0,
) -> None:
    """Async supervisor: same logic as ``run_supervisor_loop`` but using ``asyncio.sleep``."""
    from packages.harness.supervisor import (
        DEFAULT_HEARTBEAT_STALE_TTL_SECONDS,
        DEFAULT_SUPERVISOR_INTERVAL_SECONDS,
        scan_once,
    )
    from apps.supervisor_command import _build_repository

    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be > 0")

    repo = _build_repository(state_dir)
    stale_ttl = heartbeat_stale_ttl_seconds or DEFAULT_HEARTBEAT_STALE_TTL_SECONDS
    interval = interval_seconds or DEFAULT_SUPERVISOR_INTERVAL_SECONDS

    logger.info("supervisor started (interval=%gs, stale_ttl=%gs)", interval, stale_ttl)

    tick_count = 0
    while is_running():
        try:
            tick = scan_once(repo, heartbeat_stale_ttl_seconds=stale_ttl)
            tick_count += 1
            _log_supervisor_tick(tick, tick_count)
        except Exception as exc:
            logger.error("supervisor tick failed: %s", exc)

        await asyncio.sleep(interval)


# ── Learning Worker ─────────────────────────────────────────────

async def learning_worker_loop(
    *,
    state_dir: Path,
    is_running: Callable[[], bool],
    idle_seconds: float = 20.0,
) -> None:
    """Async learning worker: same logic as ``run_learning_worker`` but using ``asyncio.sleep``."""
    from apps.cli.runtime import CliRuntime
    from apps.learning_worker_runtime import (
        _write_learning_worker_record,
        run_learning_job,
    )
    from uuid import uuid4
    import os

    runtime = CliRuntime.create(state_dir=state_dir)
    worker_id = f"daemon-learning-worker:{os.getpid()}:{uuid4().hex[:8]}"
    started_at = datetime.now(UTC).isoformat()

    logger.info("learning worker started (idle_seconds=%gs)", idle_seconds)

    _write_learning_worker_record(
        state_dir,
        pid=os.getpid(),
        status="running",
        started_at=started_at,
    )

    last_activity = time.monotonic()
    jobs_completed = 0
    try:
        while is_running():
            job = runtime.repository.claim_learning_job(worker_id=worker_id)
            if job is None:
                if time.monotonic() - last_activity >= max(1.0, idle_seconds):
                    logger.info("learning worker idle timeout (%gs, %d job(s) completed), exiting", idle_seconds, jobs_completed)
                    break
                _write_learning_worker_record(
                    state_dir, pid=os.getpid(), status="idle", started_at=started_at,
                )
                await asyncio.sleep(0.5)
                continue

            last_activity = time.monotonic()
            logger.info("learning job claimed: %s (stage=%s, attempt=%d)", job.job_id, job.progress_stage, job.attempt_count)
            _write_learning_worker_record(
                state_dir,
                pid=os.getpid(),
                status="running",
                active_job_id=job.job_id,
                current_stage=job.progress_stage,
                started_at=started_at,
            )
            try:
                run_learning_job(runtime, job, worker_id=worker_id)
                jobs_completed += 1
                logger.info("learning job completed: %s", job.job_id)
            except Exception as error:
                message = str(error).strip() or error.__class__.__name__
                logger.error("learning job failed: %s - %s", job.job_id, message)
                runtime.repository.fail_learning_job(
                    job.job_id,
                    worker_id=worker_id,
                    error=message,
                    retry_delay_seconds=min(60, max(5, job.attempt_count * 5)),
                )
            finally:
                _write_learning_worker_record(
                    state_dir, pid=os.getpid(), status="running", started_at=started_at,
                )
    finally:
        _write_learning_worker_record(
            state_dir,
            pid=None,
            status="stopped",
            started_at=started_at,
            stopped_at=datetime.now(UTC).isoformat(),
            last_exit_code=0,
        )


# ── Helpers ────────────────────────────────────────────────────


def _log_supervisor_tick(tick: object, tick_count: int) -> None:
    """Log a supervisor tick result via structured logger instead of print().

    When there are decisions, each one is logged at INFO level.
    Every 10th idle tick is logged at DEBUG level as a liveness heartbeat.
    """
    decisions = getattr(tick, "decisions", None) or []
    scanned_count = getattr(tick, "scanned_count", 0)

    if decisions:
        logger.info(
            "supervisor tick #%d: scanned=%d decisions=%d",
            tick_count, scanned_count, len(decisions),
        )
        for decision in decisions:
            action = getattr(decision, "action", "?")
            loop_id = getattr(decision, "loop_id", "?")
            snapshot = getattr(decision, "snapshot", None)
            wait_kind = getattr(snapshot, "wait_condition_kind", None) if snapshot else None
            retry = getattr(snapshot, "retry_attempt", 0) if snapshot else 0
            pending = len(getattr(snapshot, "replay_plans", []) or []) if snapshot else 0
            logger.info(
                "supervisor decision: %s %s wc=%s retry=%d pending=%d",
                action, loop_id, wait_kind or "<none>", retry, pending,
            )
    elif tick_count % 10 == 0:
        logger.debug(
            "supervisor tick #%d: scanned=%d, no decisions",
            tick_count, scanned_count,
        )

