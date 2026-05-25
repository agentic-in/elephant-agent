"""Managed cron scheduler service for gateway-owned background execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
import sys
import time
from typing import Any, Protocol

from apps.runtime_layout import default_cli_state_dir
from packages.cron import CronJob, CronJobExecution
from packages.gateway_core.cron_delivery import cron_execution_should_deliver
from packages.gateway_core.proactive_ask import CONFIGURED_IM_ADAPTERS, run_proactive_ask_tick
from packages.runtime_layout import infer_install_root_from_state_dir

from .plugins import GatewayManagedRuntime, GatewayPluginRegistry, default_gateway_runtime_path


LOGGER = logging.getLogger(__name__)

CRON_SCHEDULER_TARGET = "scheduler"

CronDeliveryCallback = Callable[[CronJob, CronJobExecution], None]


class CronRuntimeLike(Protocol):
    cron_runtime: Any

    def run_due_cron_jobs_for_scheduler(self) -> tuple[CronJobExecution, ...]:
        ...


CronRuntimeFactory = Callable[[Path], CronRuntimeLike]


@dataclass(slots=True)
class CronSchedulerService:
    app: Any
    default_cli_state_dir: str | None = None
    environ: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    runtime_state_dir: Path | None = None
    service_key: str = "cron"
    delivery_callback: CronDeliveryCallback | None = None
    runtime_factory: CronRuntimeFactory | None = None

    def describe(self) -> Mapping[str, object]:
        payload: dict[str, object] = {
            "configured_transport": CRON_SCHEDULER_TARGET,
            "runtime": "managed-service",
        }
        try:
            runtime = self._cli_runtime()
            jobs = runtime.cron_runtime.list_jobs()
            active_jobs = tuple(job for job in jobs if job.status == "scheduled")
            due_jobs = runtime.cron_runtime.due_jobs()
            payload.update(
                {
                    "runtime_status": "ready",
                    "jobs": len(jobs),
                    "active_jobs": len(active_jobs),
                    "due_jobs": len(due_jobs),
                    "next_run_at": min(
                        (job.next_run_at for job in active_jobs if job.next_run_at is not None),
                        default=None,
                    ),
                }
            )
        except Exception as error:
            payload.update({"runtime_status": "unavailable", "runtime_error": str(error)})
        return payload

    def configured_runtime_target(self) -> str:
        return CRON_SCHEDULER_TARGET

    def managed_runtime(self, *, args: Any, target: str) -> GatewayManagedRuntime:
        normalized_target = _normalize_target(target)
        state_dir = Path(args.state_dir)
        return GatewayManagedRuntime(
            service_key=self.service_key,
            runtime_id=f"{self.service_key}:{normalized_target}",
            target=normalized_target,
            label="cron scheduler",
            pid_path=default_gateway_runtime_path(
                state_dir,
                service_key=self.service_key,
                target=normalized_target,
                suffix="pid",
            ),
            log_path=default_gateway_runtime_path(
                state_dir,
                service_key=self.service_key,
                target=normalized_target,
                suffix="log",
            ),
            record_path=default_gateway_runtime_path(
                state_dir,
                service_key=self.service_key,
                target=normalized_target,
                suffix="runtime.json",
            ),
        )

    def build_detached_runtime_command(self, *, args: Any, target: str) -> tuple[str, ...]:
        command = [
            sys.executable,
            "-m",
            "apps.launcher",
            "cron",
            "run",
            "--state-dir",
            str(args.state_dir),
            "--cli-state-dir",
            str(args.cli_state_dir),
            "--interval-seconds",
            str(getattr(args, "interval_seconds", 60.0)),
        ]
        return tuple(command)

    def prepare_managed_runtime(self, *, action: str, target: str) -> None:
        _normalize_target(target)

    def managed_runtime_log_hint(self, *, target: str) -> str:
        return "elephant cron logs --follow"

    def run_scheduler(self, *, interval_seconds: float = 60.0, once: bool = False) -> int:
        return run_cron_scheduler_loop(
            cli_state_dir=self._cli_state_dir(),
            interval_seconds=interval_seconds,
            once=once,
            delivery_callback=self.delivery_callback,
            runtime_factory=self.runtime_factory,
        )

    def _cli_runtime(self) -> CronRuntimeLike:
        if self.runtime_factory is None:
            raise RuntimeError("cron runtime factory is unavailable")
        return self.runtime_factory(self._cli_state_dir())

    def _cli_state_dir(self) -> Path:
        if self.default_cli_state_dir:
            return Path(self.default_cli_state_dir)
        state_dir = getattr(self.app, "state_dir", None)
        if state_dir:
            return Path(str(state_dir))
        return default_cli_state_dir(environ=self.environ)


def run_cron_scheduler_loop(
    *,
    cli_state_dir: Path,
    interval_seconds: float = 60.0,
    once: bool = False,
    delivery_callback: CronDeliveryCallback | None = None,
    runtime_factory: CronRuntimeFactory | None = None,
) -> int:
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be greater than zero")
    if runtime_factory is None:
        raise RuntimeError("cron runtime factory is unavailable")
    runtime = runtime_factory(cli_state_dir)
    print(
        f"Elephant Agent cron scheduler started (interval={interval_seconds:g}s, elephant={cli_state_dir})",
        flush=True,
    )
    last_maintenance_at = 0.0
    last_proactive_ask_at = 0.0
    while True:
        executions = runtime.run_due_cron_jobs_for_scheduler()
        for execution in executions:
            print(
                f"cron {execution.outcome}: {execution.job.job_id} {execution.job.name} - {execution.summary}",
                flush=True,
            )
            if delivery_callback is not None:
                _try_deliver_cron_result(delivery_callback, execution)
        # Run daily maintenance (auto-retire stale facts) once per 24h
        now_ts = time.time()
        if now_ts - last_maintenance_at > 86400:
            try:
                from packages.understanding.auto_retire import retire_stale_facts
                retired = retire_stale_facts(runtime.repository)
                if retired:
                    print(f"auto-retire: {retired} stale fact(s) retired", flush=True)
                last_maintenance_at = now_ts
            except Exception as exc:
                print(f"auto-retire failed: {exc}", flush=True)
                last_maintenance_at = now_ts
        # Proactive ask — check every tick, actual send gated by idle threshold
        if now_ts - last_proactive_ask_at > 60:
            last_proactive_ask_at = now_ts
            try:
                _run_proactive_ask_all_adapters(cli_state_dir, delivery_callback)
            except Exception as exc:
                print(f"proactive-ask failed: {exc}", flush=True)
        if once:
            return 0
        time.sleep(interval_seconds)


def _run_proactive_ask_all_adapters(
    cli_state_dir: Path,
    delivery_callback: CronDeliveryCallback | None,
) -> None:
    """Run proactive ask tick for every configured adapter."""
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
                print(
                    f"proactive-ask {adapter_id}: delivered {result.enqueued} question(s)",
                    flush=True,
                )
        except Exception as exc:
            print(f"proactive-ask {adapter_id} failed: {exc}", flush=True)


def _try_deliver_cron_result(
    callback: CronDeliveryCallback,
    execution: CronJobExecution,
) -> None:
    """Attempt to deliver a cron execution result via the IM adapter."""
    if not cron_execution_should_deliver(execution):
        return
    try:
        callback(execution.job, execution)
    except Exception as error:
        print(
            f"cron delivery failed: {execution.job.job_id} {execution.job.name} - {error}",
            flush=True,
        )


def build_gateway_cron_delivery_callback(
    *,
    state_dir: Path | str,
    cli_state_dir: Path | str,
    environ: Mapping[str, str] | None = None,
) -> CronDeliveryCallback | None:
    """Build a fan-out delivery callback across every configured IM adapter.

    This is the single shared factory used by both the scheduler daemon and the
    manual-trigger ("verify") endpoint. Each adapter's ``deliver_cron_result``
    filters on its own ``adapter_id`` and only the one owning the elephant's identity
    actually delivers — so "fan-out" is safe even when multiple adapters are
    configured at once.

    Returns ``None`` when no adapter is configured (nothing to deliver to).
    """
    env = dict(environ or {})
    callbacks: list[CronDeliveryCallback] = []
    for builder in (
        _try_feishu_cron_callback,
        _try_discord_cron_callback,
        _try_weixin_cron_callback,
    ):
        callback = builder(
            state_dir=str(state_dir),
            cli_state_dir=str(cli_state_dir),
            environ=env,
        )
        if callback is not None:
            callbacks.append(callback)
    if not callbacks:
        return None
    def _fanout(job, execution) -> None:
        for callback in callbacks:
            try:
                callback(job, execution)
            except Exception as error:
                # One misconfigured adapter must not block the others.
                LOGGER.warning(
                    "Cron delivery callback %s failed for job %s: %s",
                    _callback_label(callback),
                    getattr(job, "job_id", "<unknown>"),
                    error,
                    exc_info=True,
                )
                continue

    raw_callback = callbacks[0] if len(callbacks) == 1 else _fanout

    def _filtered(job, execution) -> None:
        if cron_execution_should_deliver(execution):
            raw_callback(job, execution)

    return _filtered


def _try_feishu_cron_callback(
    *,
    state_dir: str,
    cli_state_dir: str,
    environ: Mapping[str, str],
) -> CronDeliveryCallback | None:
    try:
        from apps.gateway.feishu_impl import build_feishu_gateway_service

        feishu_service = build_feishu_gateway_service(
            state_dir=state_dir,
            default_cli_state_dir=cli_state_dir,
            environ=environ,
        )
        if not feishu_service.account_configs:
            return None
        return feishu_service.deliver_cron_result
    except Exception:
        LOGGER.debug("Feishu cron delivery callback is unavailable.", exc_info=True)
        return None


def _try_discord_cron_callback(
    *,
    state_dir: str,
    cli_state_dir: str,
    environ: Mapping[str, str],
) -> CronDeliveryCallback | None:
    try:
        from apps.gateway.discord_service import DiscordGatewayService
        from apps.gateway.runtime import build_gateway_app

        app, _, _ = build_gateway_app(state_dir=state_dir)
        service = DiscordGatewayService(app=app, environ=dict(environ))
        if not service.account_configs:
            return None
        return service.deliver_cron_result
    except Exception:
        LOGGER.debug("Discord cron delivery callback is unavailable.", exc_info=True)
        return None


def _try_weixin_cron_callback(
    *,
    state_dir: str,
    cli_state_dir: str,
    environ: Mapping[str, str],
) -> CronDeliveryCallback | None:
    try:
        from apps.gateway.weixin_service import WeixinGatewayService
        from apps.gateway.runtime import build_gateway_app

        app, _, _ = build_gateway_app(state_dir=state_dir)
        service = WeixinGatewayService(app=app, environ=dict(environ))
        if not service.account_configs:
            return None
        return service.deliver_cron_result
    except Exception:
        LOGGER.debug("Weixin cron delivery callback is unavailable.", exc_info=True)
        return None


def _callback_label(callback: CronDeliveryCallback) -> str:
    return str(
        getattr(callback, "__qualname__", None)
        or getattr(callback, "__name__", None)
        or repr(callback)
    )


def register_cron_scheduler_service(registry: GatewayPluginRegistry) -> GatewayPluginRegistry:
    registry.register_service("cron", factory=build_cron_scheduler_service, enabled_by_default=True)
    return registry


def build_cron_scheduler_service(
    *,
    app: Any,
    default_cli_state_dir: str | None = None,
    environ: Mapping[str, str] | None = None,
    runtime_state_dir: Path | None = None,
    runtime_factory: CronRuntimeFactory | None = None,
    **_: object,
) -> CronSchedulerService:
    return CronSchedulerService(
        app=app,
        default_cli_state_dir=default_cli_state_dir,
        environ=dict(environ or os.environ),
        runtime_state_dir=runtime_state_dir,
        runtime_factory=runtime_factory,
    )


def _normalize_target(value: object) -> str:
    normalized = str(value or CRON_SCHEDULER_TARGET).strip().lower().replace("_", "-")
    if normalized in {"configured", CRON_SCHEDULER_TARGET, "cron"}:
        return CRON_SCHEDULER_TARGET
    raise ValueError(f"unsupported cron scheduler target: {value}")


__all__ = [
    "CONFIGURED_IM_ADAPTERS",
    "CRON_SCHEDULER_TARGET",
    "CronDeliveryCallback",
    "CronSchedulerService",
    "CronRuntimeFactory",
    "CronRuntimeLike",
    "build_cron_scheduler_service",
    "build_gateway_cron_delivery_callback",
    "cron_execution_should_deliver",
    "register_cron_scheduler_service",
    "run_cron_scheduler_loop",
]
