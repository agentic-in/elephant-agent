"""Unit tests for the unified Elephant daemon public API and task guard."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import signal
import sys
import time
import warnings
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_apps_module = sys.modules.get("apps")
if _apps_module is not None:
    _apps_paths = [Path(path).resolve() for path in getattr(_apps_module, "__path__", ())]
    if (ROOT / "apps") not in _apps_paths:
        del sys.modules["apps"]


@pytest.fixture(autouse=True)
def _prefer_repo_apps_package() -> None:
    if str(ROOT) in sys.path:
        sys.path.remove(str(ROOT))
    unit_tests_path = str(Path(__file__).resolve().parent)
    while unit_tests_path in sys.path:
        sys.path.remove(unit_tests_path)
    sys.path.insert(0, str(ROOT))
    for module_name in list(sys.modules):
        if module_name == "apps" or module_name.startswith("apps."):
            del sys.modules[module_name]


# ── daemon_command public API tests ──────────────────────────────


class TestDaemonPidPath:
    """Tests for daemon_pid_path / daemon_record_path."""

    def test_pid_path(self, tmp_path: Path) -> None:
        from apps.daemon_command import daemon_pid_path

        result = daemon_pid_path(tmp_path)
        assert result == tmp_path / "daemon.pid"

    def test_record_path(self, tmp_path: Path) -> None:
        from apps.daemon_command import daemon_record_path

        result = daemon_record_path(tmp_path)
        assert result == tmp_path / "daemon.runtime.json"


class TestDaemonIsRunning:
    """Tests for daemon_is_running."""

    def test_no_pid_file(self, tmp_path: Path) -> None:
        from apps.daemon_command import daemon_is_running

        assert daemon_is_running(tmp_path) is False

    def test_stale_pid_file(self, tmp_path: Path) -> None:
        from apps.daemon_command import daemon_is_running

        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text("99999999\n", encoding="utf-8")
        assert daemon_is_running(tmp_path) is False

    def test_current_pid(self, tmp_path: Path) -> None:
        from apps.daemon_command import daemon_is_running

        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text(f"{os.getpid()}\n", encoding="utf-8")
        assert daemon_is_running(tmp_path) is True

    def test_healthz_state_identity_must_match(self, tmp_path: Path) -> None:
        from apps.daemon_command import _healthz_matches_state

        assert _healthz_matches_state(
            {"status": "running", "state_dir": str(tmp_path)},
            tmp_path,
        ) is True
        assert _healthz_matches_state(
            {"status": "running", "state_dir": str(tmp_path / "other")},
            tmp_path,
        ) is False


class TestStartDaemonDetached:
    """Tests for start_daemon_detached."""

    def test_already_running(self, tmp_path: Path) -> None:
        from apps.daemon_command import start_daemon_detached

        # Write current pid to simulate a running daemon
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text(f"{os.getpid()}\n", encoding="utf-8")

        result = start_daemon_detached(tmp_path, tmp_path)
        assert result == 1  # Should refuse to start

    def test_start_and_cleanup(self, tmp_path: Path) -> None:
        """Verify that start_daemon_detached writes PID and record files."""
        from apps.daemon_command import start_daemon_detached

        # Patch subprocess.Popen to simulate a successful daemon start
        with (
            patch("apps.daemon_command.subprocess.Popen") as mock_popen,
            patch(
                "apps.daemon_command._daemon_healthz_payload",
                return_value={"status": "running", "pid": 12345, "state_dir": str(tmp_path)},
            ),
        ):
            mock_process = mock_popen.return_value
            mock_process.pid = 12345
            mock_process.poll.return_value = None  # Still running

            result = start_daemon_detached(tmp_path, tmp_path)

            assert result == 0
            pid_path = tmp_path / "daemon.pid"
            assert pid_path.exists()
            assert "12345" in pid_path.read_text()

            record_path = tmp_path / "daemon.runtime.json"
            assert record_path.exists()
            record = json.loads(record_path.read_text())
            assert record["status"] == "running"
            assert record["pid"] == 12345

    def test_start_suppresses_expected_detached_process_warning(self, tmp_path: Path) -> None:
        """Detached daemon ownership moves to pidfile state, not the local Popen wrapper."""
        from apps.daemon_command import start_daemon_detached

        class WarningProcess:
            pid = 12346

            def poll(self) -> None:
                return None

            def __del__(self) -> None:
                warnings.warn(
                    "subprocess 12346 is still running",
                    ResourceWarning,
                    stacklevel=2,
                )

        with (
            patch("apps.daemon_command.subprocess.Popen", side_effect=lambda *_args, **_kwargs: WarningProcess()),
            patch(
                "apps.daemon_command._daemon_healthz_payload",
                return_value={"status": "running", "pid": 12346, "state_dir": str(tmp_path)},
            ),
        ):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", ResourceWarning)
                result = start_daemon_detached(tmp_path, tmp_path)

        assert result == 0
        assert not [
            warning
            for warning in caught
            if warning.category is ResourceWarning
            and "subprocess 12346 is still running" in str(warning.message)
        ]

    def test_start_does_not_overwrite_child_ready_record_after_timeout(self, tmp_path: Path) -> None:
        from apps.daemon_command import start_daemon_detached

        class FakeProcess:
            pid = 12347

            def poll(self) -> None:
                return None

        def mark_child_ready(_state_dir: Path) -> None:
            record_path = tmp_path / "daemon.runtime.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["status"] = "running"
            record["healthz_ready_at"] = "2026-05-18T00:00:00+00:00"
            record_path.write_text(json.dumps(record), encoding="utf-8")
            return None

        with (
            patch("apps.daemon_command.subprocess.Popen", return_value=FakeProcess()),
            patch("apps.daemon_command._DAEMON_STARTUP_WAIT_SECONDS", 0.0),
            patch("apps.daemon_command._daemon_healthz_payload", side_effect=mark_child_ready),
        ):
            result = start_daemon_detached(tmp_path, tmp_path)

        assert result == 0
        record = json.loads((tmp_path / "daemon.runtime.json").read_text(encoding="utf-8"))
        assert record["status"] == "running"
        assert "last_error" not in record


class TestStopDaemon:
    """Tests for stop_daemon."""

    def test_not_running(self, tmp_path: Path) -> None:
        from apps.daemon_command import stop_daemon

        result = stop_daemon(tmp_path)
        assert result == 0

    def test_stop_with_current_pid(self, tmp_path: Path) -> None:
        """Stopping the current process should not actually kill it (will fail with PermissionError or succeed)."""
        from apps.daemon_command import stop_daemon

        # Use our own PID — the stop command will try SIGTERM but we handle it
        pid_path = tmp_path / "daemon.pid"
        pid_path.write_text(f"{os.getpid()}\n", encoding="utf-8")
        record_path = tmp_path / "daemon.runtime.json"
        record_path.write_text(json.dumps({"status": "running", "pid": os.getpid()}))

        # This will send SIGTERM to our own process; Python's default handler
        # may or may not raise. We patch os.kill to avoid actually killing ourselves.
        with patch("apps.daemon_command.os.kill") as mock_kill:
            mock_kill.side_effect = ProcessLookupError
            result = stop_daemon(tmp_path)
            assert result == 0

    def test_stop_uses_healthz_pid_when_pid_file_is_missing(self, tmp_path: Path) -> None:
        from apps.daemon_command import stop_daemon

        record_path = tmp_path / "daemon.runtime.json"
        record_path.write_text(json.dumps({"status": "running", "host": "127.0.0.1", "port": 9876}), encoding="utf-8")
        running = {"value": True}

        def fake_is_running(pid: int | None) -> bool:
            return pid == 4321 and running["value"]

        def fake_kill(pid: int, sig: int) -> None:
            assert pid == 4321
            assert sig == signal.SIGTERM
            running["value"] = False

        with (
            patch("apps.daemon_command._pid_from_healthz", return_value=4321),
            patch("apps.daemon_command._pid_is_running", side_effect=fake_is_running),
            patch("apps.daemon_command.os.kill", side_effect=fake_kill) as kill,
        ):
            result = stop_daemon(tmp_path)

        assert result == 0
        kill.assert_called_once()
        record = json.loads(record_path.read_text(encoding="utf-8"))
        assert record["status"] == "stopped"
        assert record["pid"] is None

    def test_restart_does_not_start_when_stop_fails(self, tmp_path: Path) -> None:
        from apps.daemon_command import restart_daemon

        with (
            patch("apps.daemon_command._stop_daemon", return_value=1) as stop,
            patch("apps.daemon_command._start_detached") as start,
        ):
            result = restart_daemon(tmp_path, tmp_path)

        assert result == 1
        stop.assert_called_once()
        start.assert_not_called()


class TestDaemonLogsCommand:
    """Tests for daemon log CLI behavior."""

    def test_logs_help_advertises_follow_short_flag(self, tmp_path: Path) -> None:
        from apps.daemon_command import command_main

        output = io.StringIO()
        with redirect_stdout(output):
            result = command_main(["logs", "--help"], default_state_dir=tmp_path)

        assert result == 0
        rendered = output.getvalue()
        assert "-f" in rendered
        assert "--follow" in rendered

    def test_logs_missing_file_returns_actionable_message(self, tmp_path: Path) -> None:
        from apps.daemon_command import command_main

        output = io.StringIO()
        error = io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            result = command_main(["logs"], default_state_dir=tmp_path)

        assert result == 1
        assert output.getvalue() == ""
        rendered = error.getvalue()
        assert str(tmp_path / "daemon.log") in rendered
        assert "elephant daemon start --detach" in rendered
        assert "elephant daemon logs --path" in rendered

    def test_logs_short_follow_streams_appended_output(self, tmp_path: Path) -> None:
        from apps.daemon_command import command_main

        log_path = tmp_path / "daemon.log"
        log_path.write_text("existing line\n", encoding="utf-8")
        sleeps = 0

        def fake_sleep(_seconds: float) -> None:
            nonlocal sleeps
            sleeps += 1
            if sleeps == 1:
                with log_path.open("a", encoding="utf-8") as log_file:
                    log_file.write("followed line\n")
                return
            raise KeyboardInterrupt

        output = io.StringIO()
        with patch("apps.daemon_command.time.sleep", side_effect=fake_sleep), redirect_stdout(output):
            result = command_main(["logs", "-f"], default_state_dir=tmp_path)

        assert result == 0
        assert output.getvalue().splitlines() == ["existing line", "followed line"]


class TestCronSchedulerCommand:
    """Tests for cron command delegation to the unified daemon."""

    def test_start_routes_to_daemon_even_without_detach(self, tmp_path: Path) -> None:
        from apps import cron_scheduler_command

        with (
            patch.object(cron_scheduler_command, "_cron_start_via_daemon", return_value=0) as start_via_daemon,
            patch.object(cron_scheduler_command, "_build_service") as build_service,
        ):
            result = cron_scheduler_command.command_main(
                ["start"],
                default_state_dir=tmp_path,
                default_control_state_dir=tmp_path,
            )

        assert result == 0
        start_via_daemon.assert_called_once()
        build_service.assert_not_called()

    def test_run_keeps_explicit_foreground_scheduler_loop(self, tmp_path: Path) -> None:
        from apps import cron_scheduler_command

        service = SimpleNamespace(run_scheduler=lambda **_: 0)
        with (
            patch.object(cron_scheduler_command, "_build_service", return_value=service) as build_service,
            patch.object(cron_scheduler_command, "_cron_start_via_daemon") as start_via_daemon,
        ):
            result = cron_scheduler_command.command_main(
                ["run", "--once", "--interval-seconds", "5"],
                default_state_dir=tmp_path,
                default_control_state_dir=tmp_path,
            )

        assert result == 0
        build_service.assert_called_once()
        start_via_daemon.assert_not_called()

    def test_status_routes_to_daemon_when_daemon_running(self, tmp_path: Path) -> None:
        from apps import cron_scheduler_command

        output = io.StringIO()
        with (
            patch.object(cron_scheduler_command, "daemon_is_running", return_value=True),
            patch("apps.daemon_command.command_main", return_value=0) as daemon_command,
            patch.object(cron_scheduler_command, "_build_service") as build_service,
            redirect_stdout(output),
        ):
            result = cron_scheduler_command.command_main(
                ["status"],
                default_state_dir=tmp_path,
                default_control_state_dir=tmp_path,
            )

        assert result == 0
        daemon_command.assert_called_once_with(["status"], default_state_dir=tmp_path)
        build_service.assert_not_called()
        assert "Cron is managed by the unified daemon." in output.getvalue()

    def test_logs_route_to_daemon_when_daemon_running(self, tmp_path: Path) -> None:
        from apps import cron_scheduler_command

        with (
            patch.object(cron_scheduler_command, "daemon_is_running", return_value=True),
            patch("apps.daemon_command.command_main", return_value=0) as daemon_command,
            patch.object(cron_scheduler_command, "_build_service") as build_service,
        ):
            result = cron_scheduler_command.command_main(
                ["logs", "--tail", "5", "--follow"],
                default_state_dir=tmp_path,
                default_control_state_dir=tmp_path,
            )

        assert result == 0
        daemon_command.assert_called_once_with(
            ["logs", "--tail", "5", "--follow"],
            default_state_dir=tmp_path,
        )
        build_service.assert_not_called()


# ── daemon task guard tests ──────────────────────────────────────


class TestDaemonTaskGuard:
    """Tests for _daemon_task_guard."""

    def test_normal_completion(self) -> None:
        from apps.daemon import DaemonServiceStatus, _daemon_task_guard

        statuses: dict[str, DaemonServiceStatus] = {
            "test": DaemonServiceStatus(name="test", status="running")
        }

        async def _inner():
            pass  # Complete normally

        async def _run():
            task = asyncio.create_task(_inner())
            await _daemon_task_guard(task, "test", statuses)

        asyncio.run(_run())
        assert statuses["test"].status == "stopped"
        assert statuses["test"].last_error == "task exited"

    def test_exception_updates_status(self) -> None:
        from apps.daemon import DaemonServiceStatus, _daemon_task_guard

        statuses: dict[str, DaemonServiceStatus] = {
            "test": DaemonServiceStatus(name="test", status="running")
        }

        async def _inner():
            raise RuntimeError("boom")

        async def _run():
            task = asyncio.create_task(_inner())
            await _daemon_task_guard(task, "test", statuses)

        asyncio.run(_run())
        assert statuses["test"].status == "failed"
        assert "boom" in (statuses["test"].last_error or "")

    def test_cancellation_cancels_inner(self) -> None:
        """When the guard is cancelled, the inner task should also be cancelled."""
        from apps.daemon import DaemonServiceStatus, _daemon_task_guard

        statuses: dict[str, DaemonServiceStatus] = {
            "test": DaemonServiceStatus(name="test", status="running")
        }
        inner_cancelled = False

        async def _inner():
            nonlocal inner_cancelled
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                inner_cancelled = True
                raise

        async def _run():
            task = asyncio.create_task(_inner())
            guard = asyncio.create_task(
                _daemon_task_guard(task, "test", statuses),
                name="guard:test",
            )
            # Give the inner task time to start
            await asyncio.sleep(0.05)
            # Cancel the guard (simulating shutdown)
            guard.cancel()
            try:
                await guard
            except asyncio.CancelledError:
                pass

        asyncio.run(_run())
        assert inner_cancelled, "Inner task should have been cancelled when guard was cancelled"


class TestServiceDaemonStartup:
    """Tests for daemon service startup wiring."""

    def test_gateway_service_key_discovery_logs_registry_failures(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from apps.daemon import ServiceDaemon

        class BrokenRegistry:
            def service_keys(self) -> tuple[str, ...]:
                raise RuntimeError("registry unavailable")

        daemon = ServiceDaemon(state_dir=tmp_path, cli_state_dir=tmp_path)
        daemon._gateway_app = SimpleNamespace(plugin_registry=BrokenRegistry())
        daemon._daemon_services["feishu"] = object()

        with caplog.at_level(logging.DEBUG, logger="elephant.daemon"):
            service_keys = daemon._gateway_service_keys()

        assert service_keys == ("feishu",)
        assert "service_keys() failed" in caplog.text
        assert "registry unavailable" in caplog.text

    def test_get_status_logs_service_describe_failures(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from apps.daemon import ServiceDaemon, DaemonServiceStatus

        class BrokenService:
            def describe(self) -> dict[str, object]:
                raise RuntimeError("describe unavailable")

        daemon = ServiceDaemon(state_dir=tmp_path, cli_state_dir=tmp_path)
        daemon._daemon_services["feishu"] = BrokenService()
        daemon._service_statuses["feishu"] = DaemonServiceStatus(name="feishu", status="running")

        with caplog.at_level(logging.DEBUG, logger="elephant.daemon"):
            status = daemon.get_status()

        assert status["services"]["feishu"]["status"] == "running"
        assert "details" not in status["services"]["feishu"]
        assert "feishu describe() failed" in caplog.text
        assert "describe unavailable" in caplog.text

    def test_run_cron_job_now_uses_root_cli_runtime_bridge(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from apps.daemon import ServiceDaemon

        captured: dict[str, object] = {}

        def fake_create_runtime(*, state_dir: Path, warm_embedding: bool = True) -> object:
            captured["state_dir"] = state_dir
            captured["warm_embedding"] = warm_embedding
            return SimpleNamespace(run_cron_job_now=lambda job_id: {"job_id": job_id})

        monkeypatch.setattr(
            "apps.cli_runtime_bridge.create_cli_runtime_for_app_support",
            fake_create_runtime,
        )

        daemon = ServiceDaemon(state_dir=tmp_path, cli_state_dir=tmp_path)
        result = daemon.run_cron_job_now(cli_state_dir=tmp_path / "cli", job_id="job-1")

        assert result == {"job_id": "job-1"}
        assert captured == {
            "state_dir": tmp_path / "cli",
            "warm_embedding": True,
        }

    def test_reflect_context_runtime_uses_root_cli_runtime_bridge(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from apps.daemon import ServiceDaemon

        runtime = object()
        captured: dict[str, object] = {}

        def fake_create_runtime(*, state_dir: Path, warm_embedding: bool = True) -> object:
            captured["state_dir"] = state_dir
            captured["warm_embedding"] = warm_embedding
            return runtime

        monkeypatch.setattr(
            "apps.cli_runtime_bridge.create_cli_runtime_for_app_support",
            fake_create_runtime,
        )

        daemon = ServiceDaemon(state_dir=tmp_path, cli_state_dir=tmp_path)
        result = daemon.reflect_context_runtime(state_dir=tmp_path / "state")

        assert result is runtime
        assert captured == {
            "state_dir": tmp_path / "state",
            "warm_embedding": False,
        }

    def test_gateway_app_start_disables_standalone_learning_worker(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from apps.daemon import ServiceDaemon
        import apps.gateway.runtime_impl as gateway_runtime

        captured: dict[str, object] = {}

        def fake_build_gateway_app(**kwargs: object) -> tuple[object, object, object]:
            captured.update(kwargs)
            return SimpleNamespace(profile_id="you"), object(), object()

        monkeypatch.setattr(gateway_runtime, "build_gateway_app", fake_build_gateway_app)

        daemon = ServiceDaemon(state_dir=tmp_path, cli_state_dir=tmp_path)
        asyncio.run(daemon._start_gateway_app())

        assert captured["state_dir"] == str(tmp_path)
        assert captured["start_learning_worker"] is False

    def test_mark_runtime_ready_updates_record(self, tmp_path: Path) -> None:
        from apps.daemon import ServiceDaemon

        record_path = tmp_path / "daemon.runtime.json"
        record_path.write_text(
            json.dumps({"status": "starting", "pid": 12345, "last_error": "healthz not ready"}),
            encoding="utf-8",
        )
        daemon = ServiceDaemon(state_dir=tmp_path, cli_state_dir=tmp_path, host="127.0.0.1", port=9876)

        daemon._mark_runtime_ready()

        record = json.loads(record_path.read_text(encoding="utf-8"))
        assert record["status"] == "running"
        assert record["pid"] == os.getpid()
        assert record["state_dir"] == str(tmp_path)
        assert record["cli_state_dir"] == str(tmp_path)
        assert record["host"] == "127.0.0.1"
        assert record["port"] == 9876
        assert "healthz_ready_at" in record
        assert "last_error" not in record


# ── daemon_tasks import structure test ───────────────────────────


class TestDaemonTasksImports:
    """Verify daemon_tasks has clean imports at the top."""

    def test_datetime_at_top(self) -> None:
        import ast

        source = Path("apps/daemon_tasks.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        # Find all ImportFrom nodes at module level
        datetime_imports = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module == "datetime"
            and any(alias.name in ("UTC", "datetime") for alias in node.names)
        ]
        assert len(datetime_imports) >= 1, "datetime import should exist at module level"
        # Verify none at the bottom (after function defs)
        last_func_line = max(
            node.lineno for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        )
        for imp in datetime_imports:
            assert imp.lineno < last_func_line, (
                f"datetime import at line {imp.lineno} should be at the top, "
                f"not after function definitions (last func at line {last_func_line})"
            )


class TestLearningWorkerLoop:
    """Tests for daemon learning worker event-loop behavior."""

    def test_format_idle_seconds_handles_none(self) -> None:
        from apps.daemon_tasks import _format_idle_seconds

        assert _format_idle_seconds(None) == "unbounded"
        assert _format_idle_seconds(20.0) == "20s"
        assert _format_idle_seconds(0.5) == "0.5s"

    def test_learning_worker_does_not_idle_exit_by_default(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from apps import daemon_tasks

        class FakeRepository:
            def bootstrap(self) -> None:
                pass

            def claim_learning_job(self, *, worker_id: str) -> object | None:
                return None

        def fake_repository_factory(_database_path: Path) -> FakeRepository:
            return FakeRepository()

        def fake_write_record(*_args: object, **_kwargs: object) -> dict[str, object]:
            return {}

        monkeypatch.setattr(daemon_tasks, "RuntimeStorageRepository", fake_repository_factory)
        monkeypatch.setattr("apps.learning_worker_runtime._write_learning_worker_record", fake_write_record)

        running = True

        async def run_loop() -> None:
            nonlocal running
            worker = asyncio.create_task(
                daemon_tasks.learning_worker_loop(
                    state_dir=tmp_path,
                    is_running=lambda: running,
                )
            )
            await asyncio.sleep(1.2)
            assert not worker.done()
            running = False
            await asyncio.wait_for(worker, timeout=1.0)

        asyncio.run(run_loop())

    def test_claimed_learning_job_runs_off_event_loop(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from apps import daemon_tasks

        class FakeRepository:
            def __init__(self) -> None:
                self.claimed = False

            def bootstrap(self) -> None:
                pass

            def claim_learning_job(self, *, worker_id: str) -> object | None:
                if self.claimed:
                    return None
                self.claimed = True
                return SimpleNamespace(job_id="job-1", progress_stage="queued", attempt_count=1)

            def fail_learning_job(self, *_args: object, **_kwargs: object) -> None:
                pytest.fail("learning job should not fail")

        repository = FakeRepository()
        running = True

        def fake_repository_factory(_database_path: Path) -> FakeRepository:
            return repository

        def fake_write_record(*_args: object, **_kwargs: object) -> dict[str, object]:
            return {}

        def fake_run_claimed_job(_state_dir: Path, _job_id: str, _worker_id: str) -> None:
            nonlocal running
            time.sleep(0.2)
            running = False

        monkeypatch.setattr(daemon_tasks, "RuntimeStorageRepository", fake_repository_factory)
        monkeypatch.setattr("apps.learning_worker_runtime._write_learning_worker_record", fake_write_record)
        monkeypatch.setattr(daemon_tasks, "_run_claimed_learning_job", fake_run_claimed_job)

        tick_at = 0.0

        async def ticker(started_at: float) -> None:
            nonlocal tick_at
            await asyncio.sleep(0.05)
            tick_at = time.perf_counter() - started_at

        async def run_loop() -> None:
            started_at = time.perf_counter()
            await asyncio.gather(
                daemon_tasks.learning_worker_loop(
                    state_dir=tmp_path,
                    is_running=lambda: running,
                    idle_seconds=1.0,
                ),
                ticker(started_at),
            )

        asyncio.run(run_loop())

        assert tick_at < 0.15
