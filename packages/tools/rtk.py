"""RTK command rewriting support for terminal tools."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import os
import re
import shlex
import shutil
import subprocess
from typing import Any


_FULL_OUTPUT_RE = re.compile(r"\[full output:\s*(?P<path>[^\]]+)\]")
_TRUTHY = {"1", "true", "yes", "on"}
_REWRITE_TIMEOUT_DEFAULT = 2
_FILE_READ_MIN_CHARS_DEFAULT = 8_000


@dataclass(frozen=True, slots=True)
class RtkRewriteResult:
    original_command: str
    command: str
    enabled: bool
    rewritten: bool
    binary: str = ""
    exit_code: int | None = None
    skipped_reason: str = ""
    error: str = ""

    def trace_metadata(self) -> dict[str, str]:
        metadata = {
            "rtk_enabled": "true" if self.enabled else "false",
            "rtk_rewritten": "true" if self.rewritten else "false",
        }
        if self.binary:
            metadata["rtk_binary"] = self.binary
        if self.exit_code is not None:
            metadata["rtk_exit_code"] = str(self.exit_code)
        if self.skipped_reason:
            metadata["rtk_skip_reason"] = self.skipped_reason
        if self.error:
            metadata["rtk_error"] = self.error[:240]
        return metadata


@dataclass(frozen=True, slots=True)
class RtkFileReadOptimizationResult:
    summary: str = ""
    enabled: bool = False
    optimized: bool = False
    binary: str = ""
    exit_code: int | None = None
    skipped_reason: str = ""
    error: str = ""
    input_chars: int = 0
    output_chars: int = 0
    total_lines: int = 0

    def trace_metadata(self) -> dict[str, str]:
        metadata = {
            "rtk_enabled": "true" if self.enabled else "false",
            "rtk_file_read_optimized": "true" if self.optimized else "false",
        }
        if self.binary:
            metadata["rtk_binary"] = self.binary
        if self.exit_code is not None:
            metadata["rtk_exit_code"] = str(self.exit_code)
        if self.skipped_reason:
            metadata["rtk_skip_reason"] = self.skipped_reason
        if self.error:
            metadata["rtk_error"] = self.error[:240]
        if self.input_chars:
            metadata["rtk_input_chars"] = str(self.input_chars)
        if self.output_chars:
            metadata["rtk_output_chars"] = str(self.output_chars)
        if self.total_lines:
            metadata["rtk_total_lines"] = str(self.total_lines)
        return metadata


@dataclass(frozen=True, slots=True)
class RtkProbe:
    ok: bool
    binary: str = ""
    version: str = ""
    rewrite_output: str = ""
    rewrite_exit_code: int | None = None
    error: str = ""


class RtkCommandRewriter:
    """Fail-open adapter around `rtk rewrite`."""

    def __init__(
        self,
        *,
        enabled: bool,
        binary: str = "rtk",
        rewrite_timeout_seconds: int = _REWRITE_TIMEOUT_DEFAULT,
        file_read_optimizer_enabled: bool = True,
        file_read_min_chars: int = _FILE_READ_MIN_CHARS_DEFAULT,
    ) -> None:
        self.enabled = bool(enabled)
        self.binary = str(binary or "rtk")
        self.rewrite_timeout_seconds = max(1, min(int(rewrite_timeout_seconds or _REWRITE_TIMEOUT_DEFAULT), 10))
        self.file_read_optimizer_enabled = bool(file_read_optimizer_enabled)
        self.file_read_min_chars = max(1, int(file_read_min_chars or _FILE_READ_MIN_CHARS_DEFAULT))

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> "RtkCommandRewriter":
        file_read_config = config.get("file_read_optimizer")
        if not isinstance(file_read_config, Mapping):
            file_read_config = {}
        return cls(
            enabled=bool(config.get("enabled", False)),
            binary=str(config.get("binary") or "rtk"),
            rewrite_timeout_seconds=int(config.get("rewrite_timeout_seconds") or _REWRITE_TIMEOUT_DEFAULT),
            file_read_optimizer_enabled=bool(file_read_config.get("enabled", True)),
            file_read_min_chars=int(file_read_config.get("min_chars") or _FILE_READ_MIN_CHARS_DEFAULT),
        )

    def rewrite(self, command: str, *, env: Mapping[str, str] | None = None) -> RtkRewriteResult:
        original = str(command or "").strip()
        if not self.enabled:
            return self._passthrough(original, skipped_reason="disabled")
        if not original:
            return self._passthrough(original, skipped_reason="empty")
        if _rtk_disabled(original, env):
            return self._passthrough(original, skipped_reason="rtk_disabled")
        if _already_rtk_command(original):
            return self._passthrough(original, skipped_reason="already_rtk")

        binary = resolve_rtk_binary(self.binary, env=env)
        if not binary:
            return self._passthrough(original, skipped_reason="missing_binary", binary=self.binary)

        try:
            completed = subprocess.run(
                [binary, "rewrite", original],
                capture_output=True,
                text=True,
                timeout=self.rewrite_timeout_seconds,
                env=_merged_env(env),
            )
        except subprocess.TimeoutExpired:
            return self._passthrough(original, skipped_reason="timeout", binary=binary)
        except OSError as exc:
            return self._passthrough(original, skipped_reason="error", binary=binary, error=str(exc))

        rewritten = completed.stdout.strip()
        if completed.returncode in {0, 3} and rewritten:
            return RtkRewriteResult(
                original_command=original,
                command=rewritten,
                enabled=True,
                rewritten=True,
                binary=binary,
                exit_code=completed.returncode,
            )

        reason = "no_rewrite" if completed.returncode == 1 else "denied" if completed.returncode == 2 else "error"
        error = completed.stderr.strip() if completed.returncode not in {1, 2} else ""
        return self._passthrough(
            original,
            skipped_reason=reason,
            binary=binary,
            exit_code=completed.returncode,
            error=error,
        )

    def _passthrough(
        self,
        command: str,
        *,
        skipped_reason: str,
        binary: str = "",
        exit_code: int | None = None,
        error: str = "",
    ) -> RtkRewriteResult:
        return RtkRewriteResult(
            original_command=command,
            command=command,
            enabled=self.enabled,
            rewritten=False,
            binary=binary,
            exit_code=exit_code,
            skipped_reason=skipped_reason,
            error=error,
        )

    def optimize_file_read(
        self,
        *,
        path: Path,
        explicit_offset: bool,
        explicit_limit: bool,
        selected_chars: int,
        total_lines: int,
        env: Mapping[str, str] | None = None,
    ) -> RtkFileReadOptimizationResult:
        if not self.enabled:
            return self._file_read_passthrough(skipped_reason="disabled", total_lines=total_lines)
        if not self.file_read_optimizer_enabled:
            return self._file_read_passthrough(skipped_reason="file_read_optimizer_disabled", total_lines=total_lines)
        if explicit_offset or explicit_limit:
            return self._file_read_passthrough(skipped_reason="exact_read", total_lines=total_lines)
        if selected_chars < self.file_read_min_chars:
            return self._file_read_passthrough(
                skipped_reason="small_read",
                input_chars=selected_chars,
                total_lines=total_lines,
            )
        if _rtk_disabled("", env):
            return self._file_read_passthrough(skipped_reason="rtk_disabled", total_lines=total_lines)

        binary = resolve_rtk_binary(self.binary, env=env)
        if not binary:
            return self._file_read_passthrough(skipped_reason="missing_binary", binary=self.binary, total_lines=total_lines)

        try:
            completed = subprocess.run(
                [binary, "read", str(path)],
                capture_output=True,
                text=True,
                timeout=self.rewrite_timeout_seconds,
                env=_merged_env(env),
            )
        except subprocess.TimeoutExpired:
            return self._file_read_passthrough(skipped_reason="timeout", binary=binary, total_lines=total_lines)
        except OSError as exc:
            return self._file_read_passthrough(
                skipped_reason="error",
                binary=binary,
                error=str(exc),
                total_lines=total_lines,
            )

        output = completed.stdout.strip()
        if completed.returncode == 0 and output:
            summary = "\n".join(
                (
                    f"path: {path}",
                    "optimized_by: rtk read",
                    f"lines: optimized view of {total_lines}",
                    "truncated: true",
                    "hint: pass explicit offset/limit for raw line pagination",
                    output,
                )
            )
            return RtkFileReadOptimizationResult(
                summary=summary,
                enabled=True,
                optimized=True,
                binary=binary,
                exit_code=completed.returncode,
                input_chars=selected_chars,
                output_chars=len(summary),
                total_lines=total_lines,
            )

        error = completed.stderr.strip() if completed.returncode != 0 else ""
        reason = "no_output" if completed.returncode == 0 else "error"
        return self._file_read_passthrough(
            skipped_reason=reason,
            binary=binary,
            exit_code=completed.returncode,
            error=error,
            input_chars=selected_chars,
            total_lines=total_lines,
        )

    def _file_read_passthrough(
        self,
        *,
        skipped_reason: str,
        binary: str = "",
        exit_code: int | None = None,
        error: str = "",
        input_chars: int = 0,
        total_lines: int = 0,
    ) -> RtkFileReadOptimizationResult:
        return RtkFileReadOptimizationResult(
            enabled=self.enabled,
            optimized=False,
            binary=binary,
            exit_code=exit_code,
            skipped_reason=skipped_reason,
            error=error,
            input_chars=input_chars,
            total_lines=total_lines,
        )


def resolve_rtk_binary(binary: str, *, env: Mapping[str, str] | None = None) -> str:
    candidate = str(binary or "rtk").strip() or "rtk"
    if os.sep in candidate or (os.altsep and os.altsep in candidate):
        path = Path(candidate).expanduser()
        return str(path) if path.exists() else ""
    path_env = None
    if env and env.get("PATH"):
        path_env = str(env["PATH"])
    return shutil.which(candidate, path=path_env) or ""


def probe_rtk(binary: str, *, timeout_seconds: int = _REWRITE_TIMEOUT_DEFAULT) -> RtkProbe:
    resolved = resolve_rtk_binary(binary)
    if not resolved:
        return RtkProbe(ok=False, binary=binary or "rtk", error="rtk binary not found")
    timeout = max(1, min(int(timeout_seconds or _REWRITE_TIMEOUT_DEFAULT), 10))
    try:
        version = subprocess.run(
            [resolved, "--version"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        rewrite = subprocess.run(
            [resolved, "rewrite", "git status"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return RtkProbe(ok=False, binary=resolved, error="rtk probe timed out")
    except OSError as exc:
        return RtkProbe(ok=False, binary=resolved, error=str(exc))

    rewrite_output = rewrite.stdout.strip()
    ok = rewrite.returncode in {0, 3} and bool(rewrite_output)
    error = ""
    if not ok:
        error = (rewrite.stderr or version.stderr or f"rewrite exited with status {rewrite.returncode}").strip()
    return RtkProbe(
        ok=ok,
        binary=resolved,
        version=(version.stdout or version.stderr).strip(),
        rewrite_output=rewrite_output,
        rewrite_exit_code=rewrite.returncode,
        error=error,
    )


def append_rtk_full_output_tail(
    summary: str,
    *,
    max_lines: int = 80,
    max_chars: int = 6000,
) -> str:
    match = _FULL_OUTPUT_RE.search(summary)
    if match is None:
        return summary
    raw_path = match.group("path").strip()
    path = Path(os.path.expanduser(raw_path))
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return summary
    lines = content.splitlines()
    tail = "\n".join(lines[-max(1, max_lines):]).strip()
    if len(tail) > max_chars:
        tail = tail[-max_chars:].lstrip()
    if not tail:
        return summary
    return f"{summary}\n\nRTK full output tail ({path}):\n{tail}"


def append_rtk_failure_tail(summary: str, rewrite_result: Any) -> str:
    if rewrite_result is not None and getattr(rewrite_result, "rewritten", False):
        return append_rtk_full_output_tail(summary)
    return summary


def _merged_env(env: Mapping[str, str] | None) -> dict[str, str] | None:
    if not env:
        return None
    return {**os.environ, **{str(key): str(value) for key, value in env.items()}}


def _rtk_disabled(command: str, env: Mapping[str, str] | None) -> bool:
    if env and str(env.get("RTK_DISABLED", "")).strip().lower() in _TRUTHY:
        return True
    text = command.lstrip()
    return text.startswith("RTK_DISABLED=1 ") or text == "RTK_DISABLED=1"


def _already_rtk_command(command: str) -> bool:
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return False
    for token in tokens:
        if "=" in token and not token.startswith("=") and token.split("=", 1)[0].replace("_", "").isalnum():
            continue
        return Path(token).name == "rtk"
    return False
