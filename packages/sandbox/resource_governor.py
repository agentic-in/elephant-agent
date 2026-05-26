"""Resource governor for sandboxed process execution."""

from __future__ import annotations

import os
import resource
import signal
import subprocess
import time
from pathlib import Path

from .config import ResourceLimits
from .types import SandboxOutput


class ResourceGovernor:
    """Applies resource limits and governs a running sandboxed process."""

    def __init__(self, limits: ResourceLimits) -> None:
        self._limits = limits

    def apply_preallocation(self) -> dict[str, str]:
        """Return env vars describing the resource limits applied via preexec_fn.

        The actual ``resource.setrlimit`` calls happen inside *preexec_fn*
        (i.e. in the child before exec).  This method returns a diagnostic
        mapping of what was configured so callers can include it in logs.
        """
        applied: dict[str, str] = {}

        try:
            resource.getrlimit(resource.RLIMIT_FSIZE)  # probe availability
            fsize_bytes = self._limits.max_file_size_mb * 1024 * 1024
            applied["RLIMIT_FSIZE"] = str(fsize_bytes)
        except (AttributeError, OSError):
            pass

        import sys as _sys

        # On macOS RLIMIT_NPROC limits the total user process count, not
        # the child subtree — skip the diagnostic to avoid misleading logs.
        if _sys.platform != "darwin":
            try:
                resource.getrlimit(resource.RLIMIT_NPROC)
                applied["RLIMIT_NPROC"] = str(self._limits.max_processes)
            except (AttributeError, OSError):
                pass

        try:
            _soft, hard = resource.getrlimit(resource.RLIMIT_AS)
            as_bytes = self._limits.max_memory_mb * 1024 * 1024
            effective = min(as_bytes, hard)
            applied["RLIMIT_AS"] = str(effective)
        except (AttributeError, OSError):
            pass

        return applied

    def preexec_fn(self) -> None:
        """Function to pass as ``preexec_fn`` to ``subprocess.Popen``.

        Sets ``resource.setrlimit`` constraints in the child process.

        .. note::

           On macOS ``RLIMIT_AS`` often cannot be set because the current
           soft limit already exceeds the hard limit.  We probe
           ``getrlimit`` first and only call ``setrlimit`` when the
           requested value is within the hard limit.
        """
        try:
            fsize_bytes = self._limits.max_file_size_mb * 1024 * 1024
            _safe_setrlimit(resource.RLIMIT_FSIZE, (fsize_bytes, fsize_bytes))
        except (AttributeError, ValueError, OSError):
            pass

        try:
            _safe_setrlimit(resource.RLIMIT_NPROC, (self._limits.max_processes, self._limits.max_processes))
        except (AttributeError, ValueError, OSError):
            pass

        try:
            as_bytes = self._limits.max_memory_mb * 1024 * 1024
            _safe_setrlimit(resource.RLIMIT_AS, (as_bytes, as_bytes))
        except (AttributeError, ValueError, OSError):
            pass

    def govern_command(
        self,
        process: subprocess.Popen,
        *,
        timeout_seconds: int,
        stdout_path: Path,
        stderr_path: Path,
    ) -> SandboxOutput:
        """Govern a running process with wall-clock timeout and output capture.

        Polls the process, enforces a wall-clock deadline, and kills the
        process group on timeout.  After exit, reads stdout/stderr from
        files with truncation limits.
        """
        deadline = time.monotonic() + timeout_seconds
        timed_out = False

        while process.poll() is None:
            if time.monotonic() > deadline:
                timed_out = True
                try:
                    pgid = os.getpgid(process.pid)
                    os.killpg(pgid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    process.kill()
                break
            time.sleep(0.02)

        process.wait()

        stdout_text, stdout_diagnostics = self._read_limited(
            stdout_path, limit=self._limits.max_stdout_bytes, label="stdout",
        )
        stderr_text, stderr_diagnostics = self._read_limited(
            stderr_path, limit=self._limits.max_stderr_bytes, label="stderr",
        )

        diagnostics: list[str] = []
        if stdout_diagnostics:
            diagnostics.append(stdout_diagnostics)
        if stderr_diagnostics:
            diagnostics.append(stderr_diagnostics)
        if timed_out:
            diagnostics.append(f"process killed after {timeout_seconds}s wall-clock timeout")

        return SandboxOutput(
            stdout=stdout_text,
            stderr=stderr_text,
            returncode=process.returncode,
            timed_out=timed_out,
            diagnostics=tuple(diagnostics),
        )

    def _read_limited(
        self, path: Path, *, limit: int, label: str,
    ) -> tuple[str, str | None]:
        """Read a file up to *limit* bytes, returning (text, diagnostic)."""
        try:
            payload = path.read_bytes()
        except OSError:
            return "", None

        if len(payload) <= limit:
            return payload.decode("utf-8", errors="replace").strip(), None

        head_size = max(0, limit // 2)
        tail_size = max(0, limit - head_size)
        head = payload[:head_size].decode("utf-8", errors="replace")
        tail = payload[-tail_size:].decode("utf-8", errors="replace")
        omitted = len(payload) - head_size - tail_size
        text = f"{head.rstrip()}\n... [{label} truncated, {omitted:,} bytes omitted] ...\n{tail.lstrip()}"
        diagnostic = f"{label} truncated: {len(payload):,} bytes exceeded {limit:,} byte limit"
        return text.strip(), diagnostic


def _safe_setrlimit(resource_id: int, limits: tuple[int, int]) -> None:
    """Set a resource limit only if the requested value does not exceed the hard limit.

    On macOS, ``RLIMIT_AS`` often has both soft and hard at ``RLIM_INFINITY``
    and lowering the soft limit is rejected.  ``RLIMIT_NPROC`` on macOS
    limits the total number of processes for the *user*, not the child
    process, so setting it low will cause ``fork`` to fail with
    ``EAGAIN``.  This helper probes ``getrlimit`` first and skips the
    call when it would fail or cause regressions.
    """
    import sys

    try:
        soft, hard = resource.getrlimit(resource_id)
    except (AttributeError, OSError):
        return

    # On macOS, RLIMIT_NPROC is per-user, not per-process.  Setting it
    # below the current user process count causes fork() to fail, so we
    # skip it entirely on macOS.
    if sys.platform == "darwin" and resource_id == resource.RLIMIT_NPROC:
        return

    # If current soft is already at or below the requested value, nothing to do
    if soft <= limits[0]:
        return
    # Clamp both soft and hard to the system hard limit
    clamped = tuple(min(value, hard) for value in limits)
    resource.setrlimit(resource_id, clamped)
