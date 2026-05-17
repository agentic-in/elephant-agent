"""Unified Elephant daemon: all IM adapters, cron, supervisor, and learning worker in one process."""

from __future__ import annotations

import asyncio
import logging
import signal
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apps.logging_setup import setup_logging
from apps.runtime_layout import default_cli_state_dir, default_gateway_state_dir

logger = logging.getLogger("elephant.daemon")

# Maximum time (seconds) to wait for a single service to stop gracefully.
GRACEFUL_STOP_TIMEOUT = 5.0

# Maximum time (seconds) to wait for all tasks to cancel after stop requests.
SHUTDOWN_TIMEOUT = 15.0


@dataclass(slots=True)
class DaemonServiceStatus:
    name: str
    status: str = "idle"  # idle | running | failed | stopped | skipped
    started_at: str | None = None
    last_error: str | None = None


@dataclass(slots=True)
class ServiceDaemon:
    """Unified daemon that runs all Elephant services in a single asyncio event loop."""

    state_dir: Path
    cli_state_dir: Path
    host: str = "0.0.0.0"
    port: int = 8900

    _shutdown: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)
    _tasks: list[asyncio.Task] = field(default_factory=list, init=False, repr=False)
    _task_names: dict[asyncio.Task, str] = field(default_factory=dict, init=False, repr=False)
    _service_statuses: dict[str, DaemonServiceStatus] = field(default_factory=dict, init=False, repr=False)
    _started_at: str | None = field(default=None, init=False, repr=False)
    _gateway_app: Any = field(default=None, init=False, repr=False)
    _daemon_services: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _http_services: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _adapter_locks: dict[str, asyncio.Lock] = field(default_factory=dict, init=False, repr=False)
    _http_app: Any = field(default=None, init=False, repr=False)
    _dashboard_api_app: Any = field(default=None, init=False, repr=False)
    _registered_http_service_keys: list[str] = field(default_factory=list, init=False, repr=False)

    # ── Lifecycle ──────────────────────────────────────────────

    async def start(self) -> None:
        """Start all daemon tasks and block until shutdown."""
        self._started_at = datetime.now(UTC).isoformat()
        loop = asyncio.get_running_loop()

        # Register signal handlers for graceful shutdown
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._request_shutdown, sig)
            except NotImplementedError:
                pass

        logger.info("Elephant daemon starting (pid=%d)", _pid())
        logger.info("state_dir=%s", self.state_dir)
        logger.info("http=%s:%d", self.host, self.port)

        # Start services in order
        await self._start_gateway_app()
        await self._start_dashboard_api()
        await self._start_im_adapters()  # Discover services before HTTP server
        await self._start_http_server()  # HTTP server gets routes from discovered services
        await self._start_cron_scheduler()
        await self._start_supervisor()
        await self._start_learning_worker()

        # Wrap all tasks with DaemonTaskGuard for fault isolation
        guarded_tasks = []
        for task in self._tasks:
            name = self._task_names.get(task, task.get_name())
            guarded = asyncio.create_task(
                _daemon_task_guard(task, name, self._service_statuses),
                name=f"guard:{name}",
            )
            guarded_tasks.append(guarded)
        self._tasks = guarded_tasks

        logger.info("all services started (%d tasks)", len(self._tasks))

        # Start periodic health heartbeat
        heartbeat_task = asyncio.create_task(
            self._health_heartbeat(), name="health-heartbeat"
        )
        self._tasks.append(heartbeat_task)

        # Block until shutdown requested
        await self._shutdown.wait()

        # Graceful shutdown
        await self._stop_all()

    async def _stop_all(self) -> None:
        """Cancel all tasks and wait for them to finish."""
        logger.info("shutting down...")

        # Stop daemon services gracefully first (with timeout)
        logger.info("stopping %d service(s)...", len(self._daemon_services))
        stop_tasks = []
        for key, service in self._daemon_services.items():
            stop_tasks.append(self._stop_service_safe(key, service))
        if stop_tasks:
            await asyncio.gather(*stop_tasks)

        # Cancel all tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()

        # Wait for all tasks with overall shutdown timeout
        if self._tasks:
            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*self._tasks, return_exceptions=True),
                    timeout=SHUTDOWN_TIMEOUT,
                )
                for task, result in zip(self._tasks, results):
                    if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                        task_name = task.get_name()
                        logger.error("task %s failed during shutdown: %s", task_name, result)
            except asyncio.TimeoutError:
                logger.warning("shutdown timed out after %ss, some tasks may not have stopped cleanly", SHUTDOWN_TIMEOUT)

        # Update all statuses
        for name, status in self._service_statuses.items():
            if status.status == "running":
                status.status = "stopped"

        logger.info("shutdown complete")

    async def _stop_service_safe(self, key: str, service: Any) -> None:
        """Stop a single daemon service with timeout protection."""
        try:
            await asyncio.wait_for(service.stop_daemon_task(), timeout=GRACEFUL_STOP_TIMEOUT)
            logger.info("service %s stopped gracefully", key)
        except asyncio.TimeoutError:
            logger.warning("service %s did not stop within %ss, force-cancelling", key, GRACEFUL_STOP_TIMEOUT)
        except Exception as exc:
            logger.error("failed to stop service %s: %s", key, exc)

    def _request_shutdown(self, sig: signal.Signals | int | None = None) -> None:
        sig_name = signal.Signals(sig).name if isinstance(sig, int) else str(sig)
        logger.info("received %s, requesting shutdown...", sig_name)
        self._shutdown.set()

    async def _health_heartbeat(self, interval_seconds: float = 300.0) -> None:
        """Periodic liveness log: emit daemon status every N seconds."""
        while not self._shutdown.is_set():
            await asyncio.sleep(interval_seconds)
            if self._shutdown.is_set():
                break
            uptime = 0.0
            if self._started_at:
                uptime = (datetime.now(UTC) - datetime.fromisoformat(self._started_at)).total_seconds()
            service_summary = ", ".join(
                f"{name}={s.status}" for name, s in self._service_statuses.items()
            ) or "none"
            logger.info(
                "heartbeat: uptime=%.0fs tasks=%d services=[%s]",
                uptime, len(self._tasks), service_summary,
            )

    # ── Gateway App ────────────────────────────────────────────

    async def _start_gateway_app(self) -> None:
        """Build the shared GatewayApp and plugin registry."""
        try:
            from apps.gateway.runtime import build_gateway_app
            app, chat_adapter, webhook_adapter = build_gateway_app(
                state_dir=str(self.state_dir),
            )
            self._gateway_app = app
            logger.info("GatewayApp initialized (profile=%s)", app.profile_id)
        except Exception as exc:
            logger.error("GatewayApp initialization failed: %s", exc)
            self._service_statuses["gateway_app"] = DaemonServiceStatus(
                name="gateway_app", status="failed", last_error=str(exc)
            )

    # ── Dashboard API ───────────────────────────────────────────

    async def _start_dashboard_api(self) -> None:
        """Build the ElephantAPIApp for the dashboard /v1/ API bridge.

        The app's ``dispatch(method, path, body) -> APIResponse`` method
        is called directly by the aiohttp handler — no WSGI involved.
        """
        try:
            from apps.api import create_app

            database_path = self.cli_state_dir / "elephant.sqlite3"
            self._dashboard_api_app = create_app(database_path=database_path)
            self._service_statuses["dashboard_api"] = DaemonServiceStatus(
                name="dashboard_api", status="running", started_at=datetime.now(UTC).isoformat()
            )
            logger.info("Dashboard API initialized (database=%s)", database_path)
        except Exception as exc:
            logger.warning("Dashboard API initialization skipped: %s", exc)
            self._service_statuses["dashboard_api"] = DaemonServiceStatus(
                name="dashboard_api", status="skipped", last_error=str(exc)
            )

    # ── IM Adapters ────────────────────────────────────────────

    async def _start_im_adapters(self) -> None:
        """Discover and start all configured IM adapter services."""
        from apps.gateway.plugins import DaemonService, GatewayHttpService

        app = self._gateway_app
        if app is None or app.plugin_registry is None:
            return

        registry = app.plugin_registry
        manifest = app.loaded_profile.manifest if app.loaded_profile is not None else {}
        configured_keys = registry.configured_service_keys(manifest)

        if not configured_keys:
            logger.info("no IM adapters configured")

        for key in configured_keys:
            try:
                service = registry.create_service(key, app=app, runtime_state_dir=self.state_dir)
            except TypeError:
                # Some services don't accept runtime_state_dir
                try:
                    service = registry.create_service(key, app=app)
                except Exception as exc:
                    logger.error("failed to create service %s: %s", key, exc)
                    self._service_statuses[key] = DaemonServiceStatus(
                        name=key, status="failed", last_error=str(exc)
                    )
                    continue

            # ── Preflight: check credentials ──
            is_daemon_service = isinstance(service, DaemonService)
            is_http_service = isinstance(service, GatewayHttpService)
            has_creds = hasattr(service, "has_credentials") and service.has_credentials()

            if not has_creds:
                logger.info("adapter %s skipped: no credentials configured", key)
                self._service_statuses[key] = DaemonServiceStatus(
                    name=key, status="skipped", last_error="no credentials"
                )
                continue

            # Track HTTP services for route registration
            if is_http_service:
                self._http_services[key] = service
                self._registered_http_service_keys.append(key)

            # Start as daemon task if it implements DaemonService
            if is_daemon_service:
                self._daemon_services[key] = service
                try:
                    task = await service.start_daemon_task(loop=asyncio.get_running_loop())
                    if task is not None:
                        self._tasks.append(task)
                        self._task_names[task] = key
                        logger.info("%s adapter started", key)
                    else:
                        logger.info("%s: webhook-only, no long-running task", key)
                    self._service_statuses[key] = DaemonServiceStatus(
                        name=key, status="running", started_at=datetime.now(UTC).isoformat()
                    )
                except Exception as exc:
                    logger.error("failed to start service %s: %s", key, exc)
                    self._service_statuses[key] = DaemonServiceStatus(
                        name=key, status="failed", last_error=str(exc)
                    )

    # ── Service starters ───────────────────────────────────────

    async def _start_http_server(self) -> None:
        """Start the aiohttp HTTP server for webhooks and health checks."""
        from .daemon_http import create_daemon_aiohttp_app

        app, access_log = create_daemon_aiohttp_app(daemon=self)
        self._http_app = app
        try:
            from aiohttp import web
            runner = web.AppRunner(app, access_log=access_log)
            await runner.setup()
            site = web.TCPSite(runner, self.host, self.port)
            await site.start()
            self._service_statuses["http"] = DaemonServiceStatus(
                name="http", status="running", started_at=datetime.now(UTC).isoformat()
            )
            logger.info("HTTP server listening on %s:%d", self.host, self.port)
        except ImportError:
            logger.warning("aiohttp not available, HTTP server skipped")
            self._service_statuses["http"] = DaemonServiceStatus(name="http", status="failed", last_error="aiohttp not installed")

    async def _start_cron_scheduler(self) -> None:
        """Start the cron scheduler as an async task."""
        from .daemon_tasks import cron_scheduler_loop

        task = asyncio.create_task(
            cron_scheduler_loop(
                cli_state_dir=self.cli_state_dir,
                state_dir=self.state_dir,
                is_running=lambda: not self._shutdown.is_set(),
            ),
            name="cron-scheduler",
        )
        self._tasks.append(task)
        self._task_names[task] = "cron"
        self._service_statuses["cron"] = DaemonServiceStatus(
            name="cron", status="running", started_at=datetime.now(UTC).isoformat()
        )

    async def _start_supervisor(self) -> None:
        """Start the harness supervisor as an async task."""
        from .daemon_tasks import supervisor_loop

        task = asyncio.create_task(
            supervisor_loop(
                state_dir=self.cli_state_dir,
                is_running=lambda: not self._shutdown.is_set(),
            ),
            name="supervisor",
        )
        self._tasks.append(task)
        self._task_names[task] = "supervisor"
        self._service_statuses["supervisor"] = DaemonServiceStatus(
            name="supervisor", status="running", started_at=datetime.now(UTC).isoformat()
        )

    async def _start_learning_worker(self) -> None:
        """Start the learning worker as an async task."""
        from .daemon_tasks import learning_worker_loop

        task = asyncio.create_task(
            learning_worker_loop(
                state_dir=self.cli_state_dir,
                is_running=lambda: not self._shutdown.is_set(),
            ),
            name="learning-worker",
        )
        self._tasks.append(task)
        self._task_names[task] = "learning_worker"
        self._service_statuses["learning_worker"] = DaemonServiceStatus(
            name="learning_worker", status="running", started_at=datetime.now(UTC).isoformat()
        )

    # ── Dynamic adapter lifecycle ─────────────────────────────────

    def _get_adapter_lock(self, key: str) -> asyncio.Lock:
        """Get or create an asyncio.Lock for the given adapter key."""
        if key not in self._adapter_locks:
            self._adapter_locks[key] = asyncio.Lock()
        return self._adapter_locks[key]

    async def start_adapter(self, key: str) -> dict[str, str]:
        """Dynamically start a previously-skipped adapter.

        Returns: {"status": "running"} or {"status": "skipped", "reason": "..."}
        """
        from apps.gateway.plugins import DaemonService, GatewayHttpService

        lock = self._get_adapter_lock(key)
        if lock.locked():
            return {"status": "error", "reason": "operation in progress"}

        async with lock:
            # Check if already running
            current = self._service_statuses.get(key)
            if current and current.status == "running":
                return {"status": "already_running"}

            app = self._gateway_app
            if app is None or app.plugin_registry is None:
                return {"status": "error", "reason": "gateway not initialized"}

            registry = app.plugin_registry

            # Re-create service (fresh environment check)
            try:
                service = registry.create_service(key, app=app, runtime_state_dir=self.state_dir)
            except TypeError:
                try:
                    service = registry.create_service(key, app=app)
                except Exception as exc:
                    return {"status": "error", "reason": str(exc)}

            # Preflight: check credentials
            if hasattr(service, "has_credentials") and not service.has_credentials():
                self._service_statuses[key] = DaemonServiceStatus(
                    name=key, status="skipped", last_error="no credentials"
                )
                return {"status": "skipped", "reason": "no credentials configured"}

            # Register HTTP service if applicable
            is_daemon_service = isinstance(service, DaemonService)
            is_http_service = isinstance(service, GatewayHttpService)

            if is_http_service:
                self._http_services[key] = service
                # Only register routes if not already present (aiohttp forbids duplicates)
                if not any(n == key for n in self._registered_http_service_keys):
                    self._register_http_routes_for_service(service, key)
                    self._registered_http_service_keys.append(key)
                else:
                    logger.info("adapter %s HTTP routes already registered, skipping re-register", key)

            # Start daemon task if applicable
            if is_daemon_service:
                self._daemon_services[key] = service
                try:
                    task = await service.start_daemon_task(loop=asyncio.get_running_loop())
                    if task is not None:
                        guarded = asyncio.create_task(
                            _daemon_task_guard(task, key, self._service_statuses),
                            name=f"guard:{key}",
                        )
                        self._tasks.append(guarded)
                        self._task_names[guarded] = key
                    self._service_statuses[key] = DaemonServiceStatus(
                        name=key, status="running", started_at=datetime.now(UTC).isoformat()
                    )
                    logger.info("adapter %s started dynamically", key)
                    return {"status": "running"}
                except Exception as exc:
                    self._service_statuses[key] = DaemonServiceStatus(
                        name=key, status="failed", last_error=str(exc)
                    )
                    return {"status": "error", "reason": str(exc)}

            # Webhook-only services (e.g. telegram with no daemon task)
            self._service_statuses[key] = DaemonServiceStatus(
                name=key, status="running", started_at=datetime.now(UTC).isoformat()
            )
            logger.info("adapter %s started dynamically (webhook-only)", key)
            return {"status": "running"}

    async def stop_adapter(self, key: str) -> dict[str, str]:
        """Dynamically stop a running adapter.

        Returns: {"status": "stopped"} or {"status": "not_running"}
        """
        lock = self._get_adapter_lock(key)
        if lock.locked():
            return {"status": "error", "reason": "operation in progress"}

        async with lock:
            current = self._service_statuses.get(key)
            if not current or current.status not in ("running", "failed"):
                return {"status": "not_running"}

            # Stop daemon service gracefully
            service = self._daemon_services.get(key)
            if service is not None:
                try:
                    await asyncio.wait_for(service.stop_daemon_task(), timeout=GRACEFUL_STOP_TIMEOUT)
                except asyncio.TimeoutError:
                    logger.warning("adapter %s did not stop within %ss", key, GRACEFUL_STOP_TIMEOUT)
                except Exception as exc:
                    logger.error("failed to stop adapter %s: %s", key, exc)
                finally:
                    del self._daemon_services[key]

            # Cancel the guarded task for this adapter
            tasks_to_remove = [
                t for t, n in self._task_names.items() if n == key
            ]
            for task in tasks_to_remove:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass
                if task in self._tasks:
                    self._tasks.remove(task)
                self._task_names.pop(task, None)

            # Update status
            self._service_statuses[key] = DaemonServiceStatus(
                name=key, status="stopped"
            )

            # Note: HTTP routes remain registered but the handler will return 503
            # for stopped services (checked via service status in the handler)

            logger.info("adapter %s stopped", key)
            return {"status": "stopped"}

    def _register_http_routes_for_service(self, service: Any, key: str) -> None:
        """Register HTTP routes for a dynamically started adapter."""
        from apps.gateway.plugins import GatewayHttpService
        from .daemon_http import register_event_route

        if self._http_app is None:
            return
        if not isinstance(service, GatewayHttpService):
            return
        for path in service.http_paths:
            register_event_route(self._http_app, path, service, key)

    # ── Status ─────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": "running" if not self._shutdown.is_set() else "stopping",
            "pid": _pid(),
            "uptime_seconds": (
                (datetime.now(UTC) - datetime.fromisoformat(self._started_at)).total_seconds()
                if self._started_at
                else 0
            ),
            "started_at": self._started_at,
            "services": {
                name: {"status": s.status, "started_at": s.started_at, "last_error": s.last_error}
                for name, s in self._service_statuses.items()
            },
        }

        # Add adapter-specific describe() info for running services
        for key, service in self._daemon_services.items():
            if hasattr(service, "describe") and callable(service.describe):
                try:
                    desc = service.describe()
                    if isinstance(desc, dict):
                        result["services"].setdefault(key, {}).setdefault("details", desc)
                except Exception:
                    pass

        return result


# ── Daemon Task Guard ──────────────────────────────────────────


async def _daemon_task_guard(
    inner_task: asyncio.Task,
    name: str,
    statuses: dict[str, DaemonServiceStatus],
) -> None:
    """Guard a daemon task: catch exceptions, update status, log errors.

    This wrapper ensures a single adapter failure does not crash the entire
    daemon. When the inner task raises, the guard logs the error and updates
    the service status to "failed".

    ``asyncio.shield`` prevents the implicit cancellation from propagating
    into *inner_task* so we can cancel it explicitly and update its status
    before re-raising.
    """
    try:
        await asyncio.shield(inner_task)
    except asyncio.CancelledError:
        # Guard was cancelled (shutdown) — also cancel the inner task so it
        # doesn't keep running after the guard exits.
        inner_task.cancel()
        # Give the inner task a chance to handle cancellation gracefully.
        try:
            await inner_task
        except (asyncio.CancelledError, Exception):
            pass
        raise
    except Exception as exc:
        logger.error("task %s failed: %s", name, exc, exc_info=True)
        status = statuses.get(name)
        if status is not None:
            status.status = "failed"
            status.last_error = str(exc)


# ── CLI entry point ────────────────────────────────────────────

def _pid() -> int:
    return __import__("os").getpid()


def run_daemon_foreground(
    *,
    state_dir: Path,
    cli_state_dir: Path,
    host: str = "0.0.0.0",
    port: int = 8900,
    log_level: str = "INFO",
) -> int:
    """Run the daemon in the foreground (blocking)."""
    setup_logging(level=log_level)
    daemon = ServiceDaemon(
        state_dir=state_dir,
        cli_state_dir=cli_state_dir,
        host=host,
        port=port,
    )
    try:
        asyncio.run(daemon.start())
    except KeyboardInterrupt:
        pass
    return 0
