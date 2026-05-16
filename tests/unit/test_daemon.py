"""Unit tests for the unified Elephant daemon public API and task guard."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest


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
        with patch("apps.daemon_command.subprocess.Popen") as mock_popen:
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
        assert statuses["test"].status == "running"  # No change on success

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
