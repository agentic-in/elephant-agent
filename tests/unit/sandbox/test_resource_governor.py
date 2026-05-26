"""Tests for ResourceGovernor — preallocation and governed command execution."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.sandbox import ResourceGovernor
from packages.sandbox.config import ResourceLimits
from packages.sandbox.types import SandboxOutput


class TestApplyPreallocation(unittest.TestCase):
    """ResourceGovernor.apply_preallocation returns applied limits."""

    def test_returns_dict(self) -> None:
        limits = ResourceLimits()
        gov = ResourceGovernor(limits)
        result = gov.apply_preallocation()
        self.assertIsInstance(result, dict)

    def test_includes_rlimit_fsize(self) -> None:
        limits = ResourceLimits(max_file_size_mb=50)
        gov = ResourceGovernor(limits)
        result = gov.apply_preallocation()
        self.assertIn("RLIMIT_FSIZE", result)
        self.assertEqual(result["RLIMIT_FSIZE"], str(50 * 1024 * 1024))

    @unittest.skipIf(sys.platform == "darwin", "RLIMIT_NPROC skipped on macOS in apply_preallocation")
    def test_includes_rlimit_nproc(self) -> None:
        limits = ResourceLimits(max_processes=256)
        gov = ResourceGovernor(limits)
        result = gov.apply_preallocation()
        self.assertIn("RLIMIT_NPROC", result)
        self.assertEqual(result["RLIMIT_NPROC"], "256")

    @unittest.skipUnless(sys.platform == "darwin", "RLIMIT_NPROC diagnostic only skipped on macOS")
    def test_nproc_not_in_diagnostics_on_macos(self) -> None:
        limits = ResourceLimits(max_processes=256)
        gov = ResourceGovernor(limits)
        result = gov.apply_preallocation()
        self.assertNotIn("RLIMIT_NPROC", result)

    def test_includes_rlimit_as(self) -> None:
        limits = ResourceLimits(max_memory_mb=512)
        gov = ResourceGovernor(limits)
        result = gov.apply_preallocation()
        self.assertIn("RLIMIT_AS", result)
        self.assertEqual(result["RLIMIT_AS"], str(512 * 1024 * 1024))


class TestGovernCommand(unittest.TestCase):
    """ResourceGovernor.govern_command integration-style tests with real subprocesses."""

    def _run_governed(
        self,
        command: str,
        *,
        limits: ResourceLimits | None = None,
        timeout_seconds: int = 10,
        cwd: Path | None = None,
    ) -> SandboxOutput:
        """Helper: start a process and govern it."""
        if limits is None:
            limits = ResourceLimits(max_wall_seconds=10)
        gov = ResourceGovernor(limits)

        with tempfile.TemporaryDirectory(prefix="test-govern-") as tmpdir:
            sandbox_root = Path(tmpdir)
            stdout_path = sandbox_root / "stdout.txt"
            stderr_path = sandbox_root / "stderr.txt"

            with stdout_path.open("wb") as out_f, stderr_path.open("wb") as err_f:
                proc = subprocess.Popen(
                    command,
                    shell=True,
                    cwd=cwd,
                    stdin=subprocess.DEVNULL,
                    stdout=out_f,
                    stderr=err_f,
                    preexec_fn=gov.preexec_fn,
                    start_new_session=True,
                )

            return gov.govern_command(
                proc,
                timeout_seconds=timeout_seconds,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )

    def test_quick_command_completes(self) -> None:
        output = self._run_governed("echo hello")
        self.assertEqual(output.returncode, 0)
        self.assertIn("hello", output.stdout)
        self.assertFalse(output.timed_out)

    def test_timeout_kills_process(self) -> None:
        output = self._run_governed("sleep 10", timeout_seconds=1)
        self.assertTrue(output.timed_out)

    def test_stdout_truncation(self) -> None:
        """stdout exceeding max_stdout_bytes is truncated."""
        limits = ResourceLimits(max_wall_seconds=10, max_stdout_bytes=100)
        output = self._run_governed(
            "python3 -c \"print('A'*2000)\"",
            limits=limits,
        )
        # Should be truncated, so much shorter than 2000 chars
        self.assertLessEqual(len(output.stdout.encode()), 300)
        if output.diagnostics:
            self.assertTrue(
                any("stdout" in d.lower() or "truncat" in d.lower() for d in output.diagnostics),
                f"Expected stdout truncation diagnostic, got: {output.diagnostics}",
            )

    def test_stderr_truncation(self) -> None:
        """stderr exceeding max_stderr_bytes is truncated."""
        limits = ResourceLimits(max_wall_seconds=10, max_stderr_bytes=50)
        output = self._run_governed(
            "python3 -c \"import sys; sys.stderr.write('B'*500)\"",
            limits=limits,
        )
        self.assertLessEqual(len(output.stderr.encode()), 300)
        if output.diagnostics:
            self.assertTrue(
                any("stderr" in d.lower() or "truncat" in d.lower() for d in output.diagnostics),
                f"Expected stderr truncation diagnostic, got: {output.diagnostics}",
            )

    def test_command_captures_returncode(self) -> None:
        output = self._run_governed("exit 42")
        self.assertEqual(output.returncode, 42)

    def test_command_captures_stderr(self) -> None:
        output = self._run_governed("python3 -c \"import sys; sys.stderr.write('err-msg\\n')\"")
        self.assertIn("err-msg", output.stderr)

    def test_govern_command_with_cwd(self) -> None:
        """govern_command respects cwd parameter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output = self._run_governed("pwd", cwd=Path(tmpdir))
            self.assertIn(tmpdir, output.stdout)

    def test_timeout_diagnostic_message(self) -> None:
        output = self._run_governed("sleep 10", timeout_seconds=1)
        self.assertTrue(
            any("timeout" in d.lower() for d in output.diagnostics),
            f"Expected timeout diagnostic, got: {output.diagnostics}",
        )


if __name__ == "__main__":
    unittest.main()
