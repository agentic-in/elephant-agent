"""Direct local CLI execution adapters for baby elephants."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
from typing import Mapping

from .local_agents import LocalAgentRuntimeRecord, provider_spec

_OUTPUT_LIMIT = 12000


@dataclass(frozen=True, slots=True)
class LocalAgentExecutionResult:
    status: str
    summary: str
    stdout: str
    stderr: str
    exit_code: int
    provider_id: str
    runtime_id: str

    def as_payload(self) -> dict[str, object]:
        return {
            "status": self.status,
            "summary": self.summary,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "exitCode": self.exit_code,
            "provider_id": self.provider_id,
            "providerId": self.provider_id,
            "runtime_id": self.runtime_id,
            "runtimeId": self.runtime_id,
        }


def run_local_agent_cli(
    runtime: LocalAgentRuntimeRecord,
    *,
    prompt: str,
    cwd: str | Path,
    model: str = "",
    env: Mapping[str, str] | None = None,
    timeout_seconds: int = 1800,
) -> LocalAgentExecutionResult:
    spec = provider_spec(runtime.provider_id)
    if spec is None:
        raise ValueError(f"unknown local agent provider: {runtime.provider_id}")
    if not spec.executable or not spec.run_args:
        raise ValueError(f"local agent provider is not executable yet: {runtime.provider_id}")
    path = Path(runtime.resolved_path)
    if not path.is_file():
        raise ValueError(f"local agent executable is missing: {runtime.resolved_path}")
    argv = [str(path)]
    model_text = (model or runtime.default_model or "").strip()
    if model_text and spec.model_arg:
        argv.extend([spec.model_arg, model_text])
    argv.extend(prompt if part == "{prompt}" else part for part in spec.run_args)
    resolved_env = _execution_env(env)
    try:
        completed = subprocess.run(
            argv,
            check=False,
            cwd=str(Path(cwd).expanduser()),
            env=resolved_env,
            capture_output=True,
            text=True,
            timeout=max(1, int(timeout_seconds or 1)),
        )
    except subprocess.TimeoutExpired as error:
        stdout = _bounded_text(error.stdout or "")
        stderr = _bounded_text(error.stderr or "")
        summary = _summary(stdout, stderr, status="failed") or f"{runtime.display_name} timed out"
        return LocalAgentExecutionResult(
            status="failed",
            summary=summary,
            stdout=stdout,
            stderr=stderr,
            exit_code=124,
            provider_id=runtime.provider_id,
            runtime_id=runtime.runtime_id,
        )
    stdout = _bounded_text(completed.stdout or "")
    stderr = _bounded_text(completed.stderr or "")
    status = "completed" if completed.returncode == 0 else "failed"
    return LocalAgentExecutionResult(
        status=status,
        summary=_summary(stdout, stderr, status=status),
        stdout=stdout,
        stderr=stderr,
        exit_code=int(completed.returncode or 0),
        provider_id=runtime.provider_id,
        runtime_id=runtime.runtime_id,
    )


def _execution_env(extra: Mapping[str, str] | None) -> dict[str, str]:
    allow_prefixes = ("LC_",)
    allow_names = {
        "HOME",
        "PATH",
        "SHELL",
        "USER",
        "LOGNAME",
        "LANG",
        "TMPDIR",
        "OPENAI_API_KEY",
        "CODEX_API_KEY",
        "ANTHROPIC_API_KEY",
        "CLAUDE_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GITHUB_TOKEN",
        "COPILOT_GITHUB_TOKEN",
    }
    resolved = {
        key: value
        for key, value in os.environ.items()
        if key in allow_names or any(key.startswith(prefix) for prefix in allow_prefixes)
    }
    if extra:
        resolved.update({str(key): str(value) for key, value in extra.items() if str(key).strip()})
    return resolved


def _summary(stdout: str, stderr: str, *, status: str) -> str:
    text = stdout.strip() or stderr.strip()
    if not text:
        return f"local agent {status} with no output"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    selected = lines[-10:] if len(lines) > 10 else lines
    summary = _bounded_text("\n".join(selected))
    if status == "failed" and not summary.lower().startswith("local agent failed"):
        return f"local agent failed:\n{summary}"
    return summary


def _bounded_text(value: str, *, limit: int = _OUTPUT_LIMIT) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}\n[truncated]"


__all__ = ["LocalAgentExecutionResult", "run_local_agent_cli"]
