"""Local coding-agent discovery and runtime records for Herd."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
from typing import Mapping, Sequence


@dataclass(frozen=True, slots=True)
class LocalAgentProviderSpec:
    provider_id: str
    command: str
    display_name: str
    default_role_title: str
    role_prompt: str
    executable: bool = False
    run_args: tuple[str, ...] = ()
    model_arg: str = ""
    default_model: str = ""

    @property
    def path_env_var(self) -> str:
        token = re.sub(r"[^A-Z0-9]+", "_", self.provider_id.upper()).strip("_")
        return f"ELEPHANT_{token}_PATH"

    @property
    def model_env_var(self) -> str:
        token = re.sub(r"[^A-Z0-9]+", "_", self.provider_id.upper()).strip("_")
        return f"ELEPHANT_{token}_MODEL"


@dataclass(frozen=True, slots=True)
class LocalAgentRuntimeRecord:
    runtime_id: str
    provider_id: str
    command: str
    display_name: str
    resolved_path: str
    version: str = ""
    status: str = "detected"
    auth_status: str = "unknown"
    source: str = "path"
    default_model: str = ""
    can_execute: bool = False
    role_title: str = ""
    role_prompt: str = ""
    detected_at: str = ""
    last_error: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)

    def as_payload(self) -> dict[str, object]:
        return {
            "runtime_id": self.runtime_id,
            "runtimeId": self.runtime_id,
            "provider_id": self.provider_id,
            "providerId": self.provider_id,
            "command": self.command,
            "display_name": self.display_name,
            "displayName": self.display_name,
            "resolved_path": self.resolved_path,
            "resolvedPath": self.resolved_path,
            "version": self.version,
            "status": self.status,
            "auth_status": self.auth_status,
            "authStatus": self.auth_status,
            "source": self.source,
            "default_model": self.default_model,
            "defaultModel": self.default_model,
            "can_execute": self.can_execute,
            "canExecute": self.can_execute,
            "role_title": self.role_title,
            "roleTitle": self.role_title,
            "role_prompt": self.role_prompt,
            "rolePrompt": self.role_prompt,
            "detected_at": self.detected_at,
            "detectedAt": self.detected_at,
            "last_error": self.last_error,
            "lastError": self.last_error,
            "metadata": dict(self.metadata),
        }


def provider_specs() -> tuple[LocalAgentProviderSpec, ...]:
    return (
        LocalAgentProviderSpec(
            provider_id="codex",
            command="codex",
            display_name="Codex",
            default_role_title="coding implementer",
            role_prompt="Use Codex for repository changes, code review, terminal-driven investigation, and validation-heavy engineering work.",
            executable=True,
            run_args=("exec", "{prompt}"),
            model_arg="--model",
        ),
        LocalAgentProviderSpec(
            provider_id="claude",
            command="claude",
            display_name="Claude Code",
            default_role_title="architecture reviewer",
            role_prompt="Use Claude Code for architecture review, refactoring analysis, and broad codebase reasoning.",
            executable=True,
            run_args=("-p", "{prompt}"),
            model_arg="--model",
        ),
        LocalAgentProviderSpec(
            provider_id="gemini",
            command="gemini",
            display_name="Gemini CLI",
            default_role_title="research analyst",
            role_prompt="Use Gemini CLI for broad research, comparison, and alternative implementation analysis.",
            executable=True,
            run_args=("-p", "{prompt}"),
            model_arg="-m",
        ),
        LocalAgentProviderSpec(
            provider_id="copilot",
            command="copilot",
            display_name="GitHub Copilot CLI",
            default_role_title="github assistant",
            role_prompt="Use Copilot for GitHub-centric code questions and repository workflow assistance.",
        ),
        LocalAgentProviderSpec(
            provider_id="cursor-agent",
            command="cursor-agent",
            display_name="Cursor Agent",
            default_role_title="editor agent",
            role_prompt="Use Cursor Agent for editor-oriented implementation and UI inspection tasks.",
        ),
        LocalAgentProviderSpec(
            provider_id="opencode",
            command="opencode",
            display_name="OpenCode",
            default_role_title="open source coder",
            role_prompt="Use OpenCode for open-source coding tasks when its local CLI is configured.",
        ),
        LocalAgentProviderSpec(
            provider_id="openclaw",
            command="openclaw",
            display_name="OpenClaw",
            default_role_title="automation agent",
            role_prompt="Use OpenClaw for automation-oriented local agent tasks when configured.",
        ),
        LocalAgentProviderSpec(
            provider_id="kimi",
            command="kimi",
            display_name="Kimi CLI",
            default_role_title="long-context analyst",
            role_prompt="Use Kimi CLI for long-context reading, synthesis, and Chinese-language analysis.",
        ),
        LocalAgentProviderSpec(
            provider_id="kiro-cli",
            command="kiro-cli",
            display_name="Kiro CLI",
            default_role_title="spec agent",
            role_prompt="Use Kiro CLI for specification and implementation planning tasks when configured.",
        ),
        LocalAgentProviderSpec(
            provider_id="hermes",
            command="hermes",
            display_name="Hermes",
            default_role_title="local assistant",
            role_prompt="Use Hermes for local assistant tasks when its CLI is configured.",
        ),
        LocalAgentProviderSpec(
            provider_id="pi",
            command="pi",
            display_name="Pi CLI",
            default_role_title="conversation aide",
            role_prompt="Use Pi for conversational exploration when its CLI is configured.",
        ),
    )


def provider_spec(provider_id: str) -> LocalAgentProviderSpec | None:
    target = provider_id.strip().lower()
    return next((spec for spec in provider_specs() if spec.provider_id == target), None)


def scan_local_agents(*, env: Mapping[str, str] | None = None) -> tuple[LocalAgentRuntimeRecord, ...]:
    resolved_env = dict(os.environ if env is None else env)
    login_shell_paths = _resolve_login_shell_commands(
        tuple(spec.command for spec in provider_specs()),
        env=resolved_env,
    )
    records: list[LocalAgentRuntimeRecord] = []
    now = datetime.now(timezone.utc).isoformat()
    for spec in provider_specs():
        source = ""
        path = ""
        last_error = ""
        env_path = str(resolved_env.get(spec.path_env_var) or "").strip()
        if env_path:
            path = _valid_executable_path(env_path) or ""
            source = "env"
            if not path:
                last_error = f"{spec.path_env_var} does not point to an executable file"
        if not path:
            path = _valid_executable_path(
                shutil.which(spec.command, path=str(resolved_env.get("PATH") or "")) or ""
            ) or ""
            source = "path" if path else source
        if not path:
            path = _valid_executable_path(login_shell_paths.get(spec.command, "")) or ""
            source = "login_shell" if path else source
        if not path:
            continue
        version, version_error = detect_agent_version(path)
        if version_error and not last_error:
            last_error = version_error
        default_model = str(resolved_env.get(spec.model_env_var) or spec.default_model or "").strip()
        records.append(
            LocalAgentRuntimeRecord(
                runtime_id=runtime_id_for(spec.provider_id, path),
                provider_id=spec.provider_id,
                command=spec.command,
                display_name=spec.display_name,
                resolved_path=path,
                version=version,
                status="detected",
                auth_status=_auth_status_for(spec, resolved_env),
                source=source or "path",
                default_model=default_model,
                can_execute=spec.executable,
                role_title=spec.default_role_title,
                role_prompt=spec.role_prompt,
                detected_at=now,
                last_error=last_error,
                metadata={
                    "path_env_var": spec.path_env_var,
                    "model_env_var": spec.model_env_var,
                    "adapter": "argv_prompt" if spec.executable else "",
                },
            )
        )
    return tuple(records)


def runtime_id_for(provider_id: str, resolved_path: str) -> str:
    fingerprint = hashlib.sha1(f"{provider_id}\0{resolved_path}".encode("utf-8")).hexdigest()[:12]
    return f"local-agent:{provider_id}:{fingerprint}"


def detect_agent_version(path: str, *, timeout_seconds: float = 4.0) -> tuple[str, str]:
    try:
        completed = subprocess.run(
            [path, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except Exception as error:
        return "", f"version probe failed: {type(error).__name__}: {error}"
    output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip()).strip()
    first_line = output.splitlines()[0].strip() if output else ""
    if completed.returncode != 0 and not first_line:
        return "", f"version probe exited {completed.returncode}"
    return first_line[:240], ""


def _auth_status_for(spec: LocalAgentProviderSpec, env: Mapping[str, str]) -> str:
    token_vars = {
        "codex": ("OPENAI_API_KEY", "CODEX_API_KEY"),
        "claude": ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY"),
        "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "copilot": ("GITHUB_TOKEN", "COPILOT_GITHUB_TOKEN"),
    }.get(spec.provider_id, ())
    if any(str(env.get(name) or "").strip() for name in token_vars):
        return "env"
    return "unknown"


def _valid_executable_path(value: str) -> str | None:
    candidate = str(value or "").strip()
    if not candidate:
        return None
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        return None
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return None
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        return None
    return str(resolved)


def _resolve_login_shell_commands(
    commands: Sequence[str],
    *,
    env: Mapping[str, str],
    timeout_seconds: float = 3.0,
) -> dict[str, str]:
    if platform.system().lower() not in {"darwin", "linux"}:
        return {}
    shell = str(env.get("SHELL") or "").strip()
    if not shell:
        return {}
    shell_name = Path(shell).name
    if shell_name not in {"zsh", "bash", "sh", "dash", "ksh"}:
        return {}
    script = r'''
for c in "$@"; do
  p=$(command -v "$c" 2>/dev/null || true)
  case "$p" in
    /*) printf '%s\t%s\n' "$c" "$p" ;;
  esac
done
'''
    try:
        completed = subprocess.run(
            [shell, "-ilc", script, "elephant-local-agent-discovery", *commands],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env={key: str(value) for key, value in env.items()},
        )
    except Exception:
        return {}
    resolved: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        command, separator, path = line.partition("\t")
        if not separator:
            continue
        valid = _valid_executable_path(path)
        if valid:
            resolved[command.strip()] = valid
    return resolved


__all__ = [
    "LocalAgentProviderSpec",
    "LocalAgentRuntimeRecord",
    "detect_agent_version",
    "provider_spec",
    "provider_specs",
    "runtime_id_for",
    "scan_local_agents",
]
