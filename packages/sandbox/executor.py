"""Delegating tool executor that routes foreground terminal commands and
code execution through the sandbox.

This executor wraps an ``InMemoryToolExecutor`` and intercepts:

Phase 1A:
  - ``tool.terminal.exec`` with ``background=false`` (default)

Phase 1B:
  - ``tool.code.execute`` — the handler runs normally, but receives a
    ``SandboxCodeLauncher`` that ensures the runner subprocess is
    started inside the sandbox with resource limits and env sanitisation.

Phase 1C:
  - ``tool.file.write`` — routes file writes to the cloud sandbox
    filesystem instead of the local filesystem (cloud backend only).
  - ``tool.file.read`` — routes file reads from the cloud sandbox
    filesystem instead of the local filesystem (cloud backend only).

All other tools (including ``tool.terminal.exec background=true``) pass
through to the delegate unchanged.

.. note::

   Imports from ``packages.tools`` are deferred to method bodies to avoid
   circular imports (sandbox -> tools -> sandbox via factory).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

from packages.contracts.runtime import ExecutionResult

_log = logging.getLogger(__name__)

from .code_launcher import SandboxCodeLauncher
from .config import SandboxConfig
from .environment import SandboxEnvironment
from .path_mapper import SandboxPathMapper
from .security_guard import SecurityGuard
from .types import SessionHandle

if TYPE_CHECKING:
    from packages.tools.runtime import InMemoryToolExecutor, ToolDefinition, ToolHandler, ToolInvocation


class SandboxToolExecutor:
    """Delegating executor that routes eligible tool calls through the sandbox.

    Phase 1A eligibility:
      - ``tool.terminal.exec`` with ``background=false`` (default)

    Phase 1B eligibility:
      - ``tool.code.execute`` — injects a ``SandboxCodeLauncher`` into
        the handler invocation context

    All other tools delegate to the inner ``InMemoryToolExecutor`` unchanged.
    """

    def __init__(
        self,
        delegate: InMemoryToolExecutor,
        config: SandboxConfig,
        environment: SandboxEnvironment,
        security_guard: SecurityGuard,
        *,
        path_mapper: SandboxPathMapper | None = None,
        allowed_roots: tuple[Path, ...] = (),
        cwd_resolver: Any | None = None,
        process_manager: Any | None = None,
        event_sink: Any | None = None,
        event_source: str = "tool.runtime.sandbox",
    ) -> None:
        self._delegate = delegate
        self._config = config
        self._environment = environment
        self._security_guard = security_guard
        self._path_mapper = path_mapper or SandboxPathMapper()
        self._allowed_roots = allowed_roots
        self._cwd_resolver = cwd_resolver
        self._sessions: dict[str, SessionHandle] = {}
        self._code_launchers: dict[str, SandboxCodeLauncher] = {}
        self._process_manager: Any | None = process_manager
        self._event_sink = event_sink
        self._event_source = event_source

    def _executor_id(self) -> str:
        return f"0x{id(self):x}"

    def _effective_episode_id(self, invocation: ToolInvocation) -> str:
        return invocation.context.episode_id or invocation.session_id

    def _sandbox_id(self, handle: SessionHandle | None) -> str:
        if handle is None or not handle.attachments:
            return "-"
        return handle.attachments[0]

    def _sandbox_backend_id(self, handle: SessionHandle | None = None) -> str:
        if handle is not None:
            return str(handle.backend_id or "").strip()
        return str(getattr(self._environment._backend, "BACKEND_ID", "") or "").strip()

    def _sandbox_backend_class(self) -> str:
        return type(self._environment._backend).__name__

    def _sandbox_trace_metadata(
        self,
        *,
        handle: SessionHandle | None,
        cwd: Path | None,
        resolution: str | None = None,
        cached_session: bool | None = None,
    ) -> dict[str, str]:
        metadata: dict[str, str] = {}
        backend = self._sandbox_backend_id(handle)
        if backend:
            metadata["sandbox_backend"] = backend
        backend_class = self._sandbox_backend_class()
        if backend_class:
            metadata["sandbox_backend_class"] = backend_class
        sandbox_id = self._sandbox_id(handle)
        if sandbox_id and sandbox_id != "-":
            metadata["sandbox_id"] = sandbox_id
        if cwd is not None:
            metadata["sandbox_cwd"] = str(cwd)
        if resolution:
            metadata["sandbox_resolution"] = resolution
        if cached_session is not None:
            metadata["sandbox_cached_session"] = "true" if cached_session else "false"
        if backend == "cloud":
            profile = self._config.effective_cloud()
            provider = str(profile.provider or "").strip()
            template = str(profile.template or "").strip()
            if provider:
                metadata["sandbox_provider"] = provider
            if template:
                metadata["sandbox_template"] = template
            if profile.timeout:
                metadata["sandbox_timeout_seconds"] = str(profile.timeout)
        return metadata

    def _sandbox_result(
        self,
        *,
        definition: ToolDefinition,
        invocation: ToolInvocation,
        payload: Mapping[str, Any],
        trace_metadata: Mapping[str, str] | None = None,
    ) -> ExecutionResult:
        summary = str(payload["summary"]) if "summary" in payload else ""
        outcome = str(payload.get("outcome", "success"))
        side_effects = tuple(payload.get("side_effects", definition.side_effects.categories))
        payload_trace_metadata = payload.get("trace_metadata", {})
        normalized_trace_metadata: dict[str, str] = {}
        if isinstance(payload_trace_metadata, Mapping):
            normalized_trace_metadata.update(
                {
                    str(key): str(value)
                    for key, value in payload_trace_metadata.items()
                    if value is not None and str(key).strip() and str(value).strip()
                }
            )
        if trace_metadata:
            normalized_trace_metadata.update(
                {
                    str(key): str(value)
                    for key, value in trace_metadata.items()
                    if value is not None and str(key).strip() and str(value).strip()
                }
            )
        return ExecutionResult(
            execution_id=str(payload.get("execution_id", invocation.invocation_id)),
            episode_id=invocation.session_id,
            outcome=outcome,
            summary=summary,
            telemetry_event_ids=tuple(payload.get("telemetry_event_ids", ())),
            trace_metadata=normalized_trace_metadata,
            side_effects=side_effects,
        )

    def _emit_sink_event(self, payload: Mapping[str, Any]) -> None:
        sink = self._event_sink
        emitter = getattr(sink, "emit", None)
        if callable(emitter):
            try:
                emitter(dict(payload))
            except Exception:
                return
            return
        if callable(sink):
            try:
                sink(dict(payload))
            except Exception:
                return

    def _emit_sandbox_event(
        self,
        *,
        name: str,
        invocation: ToolInvocation,
        handle: SessionHandle | None = None,
        cwd: Path | None = None,
        resolution: str | None = None,
        **extra: Any,
    ) -> None:
        occurred_at = datetime.now(timezone.utc).isoformat()
        session_key = invocation.invocation_id or invocation.session_id or name
        sandbox_id = self._sandbox_id(handle) if handle is not None else "-"
        payload: dict[str, Any] = {
            "event_id": f"sandbox:{name}:{session_key}:{occurred_at}",
            "event_type": "sandbox.lifecycle",
            "family": "sandbox",
            "name": name,
            "occurred_at": occurred_at,
            "source": self._event_source,
            "invocation_id": invocation.invocation_id,
            "episode_id": self._effective_episode_id(invocation),
            "session_id": invocation.session_id,
            "tool_id": invocation.tool_id,
            "backend": handle.backend_id if handle is not None else getattr(self._environment._backend, "BACKEND_ID", "?"),
            "sandbox_id": None if sandbox_id == "-" else sandbox_id,
            "cwd": str(cwd) if cwd is not None else None,
            "resolution": resolution,
            "executor_id": self._executor_id(),
            "pid": os.getpid(),
            "active": self._config.is_active,
        }
        for key, value in extra.items():
            payload[key] = value
        self._emit_sink_event(payload)

    def _emit_cloud_created(
        self,
        *,
        invocation: ToolInvocation,
        handle: SessionHandle,
        cwd: Path,
    ) -> None:
        if handle.backend_id != "cloud":
            return
        profile = self._config.effective_cloud()
        self._emit_sandbox_event(
            name="sandbox.cloud_created",
            invocation=invocation,
            handle=handle,
            cwd=cwd,
            template=profile.template or "-",
            timeout_seconds=profile.timeout,
            provider=profile.provider,
        )

    def _log_invocation(self, definition: ToolDefinition, invocation: ToolInvocation) -> None:
        cached_session = self._peek_live_session(invocation.session_id) is not None
        _log.debug(
            "sandbox.invoke pid=%d executor_id=%s backend=%s active=%s tool_id=%s invocation_id=%s episode_id=%s session_id=%s cached_session=%s",
            os.getpid(),
            self._executor_id(),
            getattr(self._environment._backend, "BACKEND_ID", "?"),
            self._config.is_active,
            definition.tool_id,
            invocation.invocation_id,
            self._effective_episode_id(invocation),
            invocation.session_id,
            cached_session,
        )
        self._emit_sandbox_event(
            name="sandbox.invoke",
            invocation=invocation,
            cached_session=cached_session,
            tool_id=definition.tool_id,
        )

    def _log_session_binding(
        self,
        *,
        invocation: ToolInvocation,
        handle: SessionHandle,
        resolution: str,
        cwd: Path,
    ) -> None:
        cache_size = len(self._sessions)
        _log.debug(
            "sandbox.session pid=%d executor_id=%s tool_id=%s invocation_id=%s episode_id=%s session_id=%s resolution=%s backend=%s sandbox_id=%s cwd=%s cache_size=%d",
            os.getpid(),
            self._executor_id(),
            invocation.tool_id,
            invocation.invocation_id,
            self._effective_episode_id(invocation),
            invocation.session_id,
            resolution,
            handle.backend_id,
            self._sandbox_id(handle),
            cwd,
            cache_size,
        )
        self._emit_sandbox_event(
            name="sandbox.session",
            invocation=invocation,
            handle=handle,
            cwd=cwd,
            resolution=resolution,
            cache_size=cache_size,
        )

    # -- Delegating ToolExecutionBackend interface --

    def bind(self, tool_id: str, handler: ToolHandler) -> None:
        self._delegate.bind(tool_id, handler)

    def unbind(self, tool_id: str) -> bool:
        return self._delegate.unbind(tool_id)

    def execute(self, definition: ToolDefinition, invocation: ToolInvocation) -> ExecutionResult:
        self._log_invocation(definition, invocation)
        # Phase 1A: intercept foreground terminal exec
        if self._should_sandbox_terminal_foreground(definition, invocation):
            payload = self._run_sandboxed_terminal_exec(invocation)
            if isinstance(payload, ExecutionResult):
                return payload
            return self._sandbox_result(definition=definition, invocation=invocation, payload=payload)

        # Phase 3: intercept background terminal exec
        if self._should_sandbox_terminal_background(definition, invocation):
            payload = self._run_sandboxed_terminal_background(invocation)
            if isinstance(payload, ExecutionResult):
                return payload
            return self._sandbox_result(definition=definition, invocation=invocation, payload=payload)

        # Phase 1B: inject sandbox code launcher for tool.code.execute
        if self._should_sandbox_code_execute(definition):
            return self._run_sandboxed_code_execute(definition, invocation)

        # Phase 1C: intercept file operations for cloud sandbox
        if self._should_sandbox_file_write(definition):
            payload = self._run_sandboxed_file_write(invocation)
            if isinstance(payload, ExecutionResult):
                return payload
            return self._sandbox_result(definition=definition, invocation=invocation, payload=payload)

        if self._should_sandbox_file_read(definition):
            payload = self._run_sandboxed_file_read(invocation)
            if isinstance(payload, ExecutionResult):
                return payload
            return self._sandbox_result(definition=definition, invocation=invocation, payload=payload)

        # Phase 1C: intercept file search for cloud sandbox
        if self._should_sandbox_file_search(definition):
            payload = self._run_sandboxed_file_search(invocation)
            if isinstance(payload, ExecutionResult):
                return payload
            return self._sandbox_result(definition=definition, invocation=invocation, payload=payload)

        # Phase 1C: intercept file patch for cloud sandbox
        if self._should_sandbox_file_patch(definition):
            payload = self._run_sandboxed_file_patch(invocation)
            if isinstance(payload, ExecutionResult):
                return payload
            return self._sandbox_result(definition=definition, invocation=invocation, payload=payload)

        return self._delegate.execute(definition, invocation)

    # -- Sandbox eligibility --

    def _should_sandbox_terminal_foreground(
        self, definition: ToolDefinition, invocation: ToolInvocation,
    ) -> bool:
        from packages.tools.handler_support import coerce_bool

        if not self._config.is_active:
            return False
        if definition.tool_id != "tool.terminal.exec":
            return False
        background = coerce_bool(invocation.arguments.get("background"), default=False)
        if background:
            return False
        return True

    def _should_sandbox_terminal_background(
        self, definition: ToolDefinition, invocation: ToolInvocation,
    ) -> bool:
        from packages.tools.handler_support import coerce_bool

        if not self._config.is_active:
            return False
        if definition.tool_id != "tool.terminal.exec":
            return False
        background = coerce_bool(invocation.arguments.get("background"), default=False)
        if not background:
            return False
        return True

    def _should_sandbox_code_execute(self, definition: ToolDefinition) -> bool:
        if not self._config.is_active:
            return False
        return definition.tool_id == "tool.code.execute"

    def _should_sandbox_file_write(self, definition: ToolDefinition) -> bool:
        if not self._config.is_active:
            return False
        if not self._is_cloud_backend():
            return False
        return definition.tool_id == "tool.file.write"

    def _should_sandbox_file_read(self, definition: ToolDefinition) -> bool:
        if not self._config.is_active:
            return False
        if not self._is_cloud_backend():
            return False
        return definition.tool_id == "tool.file.read"

    def _should_sandbox_file_search(self, definition: ToolDefinition) -> bool:
        if not self._config.is_active:
            return False
        if not self._is_cloud_backend():
            return False
        return definition.tool_id == "tool.file.search"

    def _should_sandbox_file_patch(self, definition: ToolDefinition) -> bool:
        if not self._config.is_active:
            return False
        if not self._is_cloud_backend():
            return False
        return definition.tool_id == "tool.file.patch"

    def _is_cloud_backend(self) -> bool:
        """Check if the active sandbox backend is cloud-based."""
        return getattr(self._environment._backend, "BACKEND_ID", None) == "cloud"

    # -- Foreground terminal exec through sandbox --

    def _run_sandboxed_terminal_exec(self, invocation: ToolInvocation) -> Mapping[str, Any]:
        from packages.tools.handler_support import (
            coerce_env,
            coerce_int,
            join_parts,
            optional_string,
            resolve_allowed_path,
            tool_summary,
        )

        command = str(invocation.arguments.get("command") or "").strip()
        if not command:
            raise ValueError("tool.terminal.exec requires a 'command' argument")

        # Resolve cwd using the same logic as the original handler
        cwd = self._resolve_cwd(invocation)
        env = self._resolve_env(invocation)
        timeout_seconds = max(
            1, min(coerce_int(invocation.arguments.get("timeout_seconds"), default=20), 120),
        )

        # Get or create sandbox session
        handle, resolution = self._acquire_session(
            invocation.session_id,
            cwd=cwd,
            env=env,
            invocation=invocation,
        )
        cached_session = resolution == "reuse"
        trace_metadata = self._sandbox_trace_metadata(
            handle=handle,
            cwd=cwd,
            resolution=resolution,
            cached_session=cached_session,
        )

        # Execute through sandbox
        output = self._environment.execute(
            handle,
            command,
            cwd=cwd,
            env=env,
            timeout_seconds=timeout_seconds,
        )

        # Build the same result format as the original foreground terminal exec
        body = join_parts(output.stdout, output.stderr)
        if output.timed_out:
            summary = body or f"command timed out after {timeout_seconds} seconds"
            return tool_summary(
                invocation,
                summary,
                side_effects=("terminal", "filesystem"),
                trace_metadata=trace_metadata,
            )

        if output.returncode != 0:
            summary = body or f"command exited with status {output.returncode}"
            return tool_summary(
                invocation,
                summary,
                side_effects=("terminal", "filesystem"),
                trace_metadata=trace_metadata,
            )

        summary = body or f"command exited with status {output.returncode}"
        return tool_summary(
            invocation,
            summary,
            side_effects=("terminal", "filesystem"),
            trace_metadata=trace_metadata,
        )

    # -- File write through cloud sandbox (Phase 1C) --

    def _run_sandboxed_file_write(self, invocation: ToolInvocation) -> Mapping[str, Any]:
        from packages.tools.handler_support import optional_string, tool_summary

        raw_path = optional_string(invocation.arguments.get("path"))
        content = invocation.arguments.get("content")
        if raw_path is None or content is None:
            raise ValueError("tool.file.write requires 'path' and 'content'")

        # Map local path to remote sandbox path
        remote_path = self._path_mapper.to_remote(raw_path)
        env = self._resolve_env(invocation)
        sandbox_cwd = Path(self._path_mapper.remote_cwd(str(self._resolve_base_cwd(invocation))))
        handle, resolution = self._acquire_session(
            invocation.session_id,
            cwd=sandbox_cwd,
            env=env,
            invocation=invocation,
        )
        trace_metadata = self._sandbox_trace_metadata(
            handle=handle,
            cwd=sandbox_cwd,
            resolution=resolution,
            cached_session=resolution == "reuse",
        )

        # Use the cloud backend's write_file method
        backend = self._environment._backend
        success = backend.write_file(handle, remote_path, str(content))

        if not success:
            return tool_summary(
                invocation,
                f"Failed to write file to cloud sandbox: {remote_path}",
                side_effects=("file", "write"),
                trace_metadata=trace_metadata,
            )

        return tool_summary(
            invocation,
            f"path: {remote_path}\nmode: overwrite\nbytes: {len(str(content).encode('utf-8'))}",
            side_effects=("file", "write"),
            trace_metadata=trace_metadata,
        )

    # -- File read through cloud sandbox (Phase 1C) --

    def _run_sandboxed_file_read(self, invocation: ToolInvocation) -> Mapping[str, Any]:
        from packages.tools.handler_support import coerce_int, optional_string, tool_summary

        raw_path = optional_string(invocation.arguments.get("path"))
        if raw_path is None:
            raise ValueError("tool.file.read requires 'path'")

        offset = max(1, coerce_int(invocation.arguments.get("offset"), default=1))
        limit = max(1, min(coerce_int(invocation.arguments.get("limit"), default=2000), 2000))

        # Map local path to remote sandbox path
        remote_path = self._path_mapper.to_remote(raw_path)
        env = self._resolve_env(invocation)
        sandbox_cwd = Path(self._path_mapper.remote_cwd(str(self._resolve_base_cwd(invocation))))
        handle, resolution = self._acquire_session(
            invocation.session_id,
            cwd=sandbox_cwd,
            env=env,
            invocation=invocation,
        )
        trace_metadata = self._sandbox_trace_metadata(
            handle=handle,
            cwd=sandbox_cwd,
            resolution=resolution,
            cached_session=resolution == "reuse",
        )

        # Use the cloud backend's read_file method
        backend = self._environment._backend
        content = backend.read_file(handle, remote_path)

        if content is None:
            return tool_summary(
                invocation,
                f"File not found in cloud sandbox: {remote_path}",
                side_effects=("file", "read"),
                trace_metadata=trace_metadata,
            )

        # Apply offset/limit (1-indexed offset, line-based)
        lines = content.splitlines()
        selected = lines[offset - 1: offset - 1 + limit]
        result_text = "\n".join(selected)
        total_lines = len(lines)
        shown_lines = len(selected)

        header = f"File: {remote_path} ({total_lines} lines total"
        if offset > 1 or shown_lines < total_lines:
            header += f"; showing lines {offset}-{offset + shown_lines - 1}"
        header += ")\n"

        return tool_summary(
            invocation,
            header + result_text,
            side_effects=("file", "read"),
            trace_metadata=trace_metadata,
        )

    # -- File search through cloud sandbox (Phase 1C) --

    def _run_sandboxed_file_search(self, invocation: ToolInvocation) -> Mapping[str, Any]:
        from packages.tools.handler_support import coerce_int, optional_string, tool_summary

        target = str(invocation.arguments.get("target") or "content").strip().lower()
        glob_pattern = optional_string(invocation.arguments.get("glob")) or optional_string(invocation.arguments.get("include"))
        query = str(invocation.arguments.get("query") or invocation.arguments.get("pattern") or "").strip()
        if not query and target != "files":
            raise ValueError("tool.file.search requires a 'query' argument unless target=files")

        raw_path = optional_string(invocation.arguments.get("path"))
        limit = max(1, min(coerce_int(invocation.arguments.get("limit"), default=20), 200))
        offset = max(0, coerce_int(invocation.arguments.get("offset"), default=0))
        context_lines = max(0, min(coerce_int(invocation.arguments.get("context"), default=0), 5))

        # Determine remote search root
        base_cwd = self._resolve_base_cwd(invocation)
        sandbox_cwd = self._path_mapper.remote_cwd(str(base_cwd))
        search_root = self._path_mapper.to_remote(raw_path) if raw_path else sandbox_cwd

        env = self._resolve_env(invocation)
        handle, resolution = self._acquire_session(
            invocation.session_id,
            cwd=Path(sandbox_cwd),
            env=env,
            invocation=invocation,
        )
        trace_metadata = self._sandbox_trace_metadata(
            handle=handle,
            cwd=Path(sandbox_cwd),
            resolution=resolution,
            cached_session=resolution == "reuse",
        )

        # Build rg command for remote execution
        max_lines = offset + limit + 1
        if target == "files":
            rg_cmd = f"rg --files '{search_root}'"
            if glob_pattern or query:
                rg_cmd = f"rg --files -g '{glob_pattern or query}' '{search_root}'"
        elif target == "content":
            rg_parts = ["rg", "-n", "--no-heading", "--with-filename", "--smart-case"]
            if glob_pattern:
                rg_parts.extend(["-g", f"'{glob_pattern}'"])
            if context_lines:
                rg_parts.extend(["-C", str(context_lines)])
            rg_parts.extend(["--", f"'{query}'", f"'{search_root}'"])
            rg_cmd = " ".join(rg_parts)
        else:
            raise ValueError("tool.file.search target must be content or files")

        # Add line limit to avoid massive output
        rg_cmd += f" | head -n {max_lines}"

        output = self._environment.execute(
            handle,
            rg_cmd,
            cwd=Path(sandbox_cwd),
            env=env,
            timeout_seconds=20,
        )

        # Parse output lines
        raw_lines = (output.stdout or "").splitlines()
        visible = raw_lines[offset: offset + limit]
        truncated = len(raw_lines) > offset + limit
        body = "\n".join(visible).strip()

        if body:
            footer = [
                f"shown: {len(visible)}",
                f"offset: {offset}",
                f"truncated: {str(truncated).lower()}",
            ]
            if truncated:
                footer.append(f"hint: use offset={offset + limit} to continue")
            summary = "\n".join((body, *footer))
        else:
            summary = f"no file matches for query: {query or glob_pattern or '*'}"

        return tool_summary(
            invocation,
            summary,
            side_effects=("file", "search"),
            trace_metadata=trace_metadata,
        )

    # -- File patch through cloud sandbox (Phase 1C) --

    def _run_sandboxed_file_patch(self, invocation: ToolInvocation) -> Mapping[str, Any]:
        from packages.tools.handler_support import optional_string, tool_summary

        patch_text = optional_string(invocation.arguments.get("patch"))
        if not patch_text:
            raise ValueError("tool.file.patch requires a 'patch' argument")

        base_cwd = self._resolve_base_cwd(invocation)
        sandbox_cwd = self._path_mapper.remote_cwd(str(base_cwd))
        env = self._resolve_env(invocation)

        handle, resolution = self._acquire_session(
            invocation.session_id,
            cwd=Path(sandbox_cwd),
            env=env,
            invocation=invocation,
        )
        trace_metadata = self._sandbox_trace_metadata(
            handle=handle,
            cwd=Path(sandbox_cwd),
            resolution=resolution,
            cached_session=resolution == "reuse",
        )

        # Apply patch using a Python one-liner inside the sandbox
        # We base64-encode the patch to avoid shell escaping issues
        import base64
        patch_b64 = base64.b64encode(patch_text.encode()).decode()

        apply_cmd = (
            f"python3 -c \""
            f"import base64, sys; "
            f"patch = base64.b64decode('{patch_b64}').decode(); "
            f"exec(open('/tmp/_elephant_patch_apply.py').read())\" "
        )

        # Write a small patch-apply helper, then run it
        helper_script = r'''
import base64, sys, os
patch_b64 = sys.argv[1]
patch_text = base64.b64decode(patch_b64).decode()
files_patched = []
current_file = None
current_lines = None
hunks = []

for line in patch_text.splitlines():
    if line.startswith("--- ") or line.startswith("+++ "):
        if line.startswith("+++ "):
            path = line[4:].strip()
            if path.startswith("b/"):
                path = path[2:]
            current_file = path
    elif line.startswith("@@ "):
        pass
    elif current_file and not os.path.isabs(current_file):
        current_file = os.path.join(os.getcwd(), current_file)

# Simpler: just pipe through patch command
import subprocess
result = subprocess.run(
    ["patch", "-p1", "--no-backup-if-mismatch"],
    input=patch_text, capture_output=True, text=True, cwd=os.getcwd()
)
if result.returncode == 0:
    print(result.stdout or "patch applied successfully")
else:
    print(result.stdout)
    print(result.stderr, file=sys.stderr)
    sys.exit(result.returncode)
'''

        # Use a simpler approach: pipe patch through `patch -p1`
        patch_cmd = (
            f"echo '{patch_b64}' | base64 -d | patch -p1 --no-backup-if-mismatch"
        )

        output = self._environment.execute(
            handle,
            patch_cmd,
            cwd=Path(sandbox_cwd),
            env=env,
            timeout_seconds=30,
        )

        body = (output.stdout or "").strip()
        if output.returncode != 0:
            err = (output.stderr or "").strip()
            summary = f"patch failed (exit {output.returncode}): {err or body or 'unknown error'}"
        else:
            summary = body or "patch applied successfully"

        return tool_summary(
            invocation,
            summary,
            side_effects=("file", "patch"),
            trace_metadata=trace_metadata,
        )

    # -- Background terminal exec through sandbox (Phase 3) --

    def _run_sandboxed_terminal_background(self, invocation: ToolInvocation) -> Mapping[str, Any]:
        """Run background terminal exec through the sandbox process manager.

        This mirrors the original handler's background=true path, but the
        subprocess is started inside a sandbox session with resource limits
        and env sanitisation.
        """
        from packages.tools.handler_support import (
            coerce_env,
            join_parts,
            optional_string,
            resolve_allowed_path,
            tool_summary,
        )
        from .process_manager import SandboxProcessManager

        command = str(invocation.arguments.get("command") or "").strip()
        if not command:
            raise ValueError("tool.terminal.exec requires a 'command' argument")

        cwd = self._resolve_cwd(invocation)
        env = self._resolve_env(invocation)

        # Get or create the sandbox process manager for this executor
        process_manager = self._get_or_create_process_manager()
        managed = process_manager.start(
            command=command,
            cwd=cwd,
            env=env,
            session_id=invocation.session_id,
        )
        trace_metadata = self._sandbox_trace_metadata(
            handle=managed.session_handle,
            cwd=cwd,
            resolution=managed.session_resolution,
            cached_session=managed.session_resolution == "reuse",
        )

        return tool_summary(
            invocation,
            "\n".join(
                [
                    f"process_id: {managed.process_id}",
                    "status: running",
                    f"cwd: {managed.cwd}",
                    f"command: {managed.command}",
                ]
            ),
            side_effects=("terminal", "process"),
            trace_metadata=trace_metadata,
        )

    # -- Code execute with sandbox launcher (Phase 1B) --

    def _run_sandboxed_code_execute(
        self, definition: ToolDefinition, invocation: ToolInvocation,
    ) -> ExecutionResult:
        """Run tool.code.execute with a SandboxCodeLauncher injected.

        The handler's AST validation, project/strict mode, and tool RPC
        are all preserved unchanged.  Only the subprocess launch point
        is replaced by the sandbox launcher.
        """
        from packages.tools.handler_support import (
            coerce_env,
            coerce_int,
            optional_string,
            resolve_allowed_path,
        )

        # Get or create a sandbox code launcher for this session
        launcher = self._get_or_create_code_launcher(invocation.session_id)
        launcher.bind_invocation(
            invocation_id=invocation.invocation_id,
            episode_id=self._effective_episode_id(invocation),
            tool_id=invocation.tool_id,
        )

        # Inject the launcher into the invocation's context so the
        # handler can pick it up.  We store it in the handler kwargs
        # via a well-known key.
        # The code.execute handler is called via delegate.execute(),
        # but we need to pass the launcher through.  The cleanest way
        # is to add it as a kwarg to the handler.  Since the handler
        # is already bound, we use the invocation context's extras dict.
        modified_invocation = self._inject_code_launcher(invocation, launcher)

        result = self._delegate.execute(definition, modified_invocation)
        trace_metadata = launcher.trace_metadata()
        if not trace_metadata:
            return result
        merged_trace_metadata = dict(result.trace_metadata)
        merged_trace_metadata.update(trace_metadata)
        return replace(result, trace_metadata=merged_trace_metadata)

    def _inject_code_launcher(
        self, invocation: ToolInvocation, launcher: SandboxCodeLauncher,
    ) -> ToolInvocation:
        """Add code_launcher to invocation so the handler can access it."""
        import dataclasses

        # We use a special key in arguments to pass the launcher through.
        # The handler checks for this key and uses it if present.
        modified_args = dict(invocation.arguments)
        modified_args["__sandbox_code_launcher__"] = launcher
        return dataclasses.replace(invocation, arguments=modified_args)

    def _get_or_create_code_launcher(self, session_id: str) -> SandboxCodeLauncher:
        if session_id in self._code_launchers:
            return self._code_launchers[session_id]
        launcher = SandboxCodeLauncher(
            config=self._config,
            session_id=session_id,
            backend=self._environment._backend,
            event_sink=self._event_sink,
            event_source=self._event_source,
            session_provider=lambda cwd, env, _session_id=session_id: self._acquire_session(
                _session_id,
                cwd=cwd,
                env=env,
            ),
        )
        self._code_launchers[session_id] = launcher
        return launcher

    # -- Common helpers --

    def _resolve_cwd(self, invocation: ToolInvocation) -> Path:
        from packages.tools.handler_support import optional_string, resolve_allowed_path

        raw_cwd = optional_string(invocation.arguments.get("cwd"))
        base_cwd = self._resolve_base_cwd(invocation)
        all_allowed = (*self._allowed_roots, *invocation.context.allowed_roots)
        return resolve_allowed_path(
            base_cwd,
            raw_cwd,
            must_exist=True,
            allowed_roots=all_allowed,
        )

    def _resolve_base_cwd(self, invocation: ToolInvocation) -> Path:
        if self._cwd_resolver is not None:
            return self._cwd_resolver(invocation.session_id)
        return invocation.context.cwd

    def _resolve_env(self, invocation: ToolInvocation) -> dict[str, str]:
        from packages.tools.handler_support import coerce_env

        env = dict(invocation.context.env)
        env.update(coerce_env(invocation.arguments.get("env")))
        return env

    def _session_is_alive(self, handle: SessionHandle) -> bool:
        reader = getattr(self._environment._backend, "read_cwd", None)
        if not callable(reader):
            return True
        try:
            reader(handle)
        except Exception:
            return False
        return True

    def _drop_session(self, session_id: str, handle: SessionHandle | None = None) -> None:
        cached = self._sessions.pop(session_id, None)
        resolved = cached or handle
        if resolved is None:
            return
        try:
            self._environment.cleanup(resolved)
        except Exception:
            pass
        launcher = self._code_launchers.get(session_id)
        if launcher is not None:
            launcher.release_session()

    def _peek_live_session(self, session_id: str) -> SessionHandle | None:
        handle = self._sessions.get(session_id)
        if handle is None:
            return None
        if self._session_is_alive(handle):
            return handle
        self._drop_session(session_id, handle)
        return None

    def _create_session(self, session_id: str, *, cwd: Path, env: dict[str, str]) -> SessionHandle:
        sanitized_env = self._security_guard.sanitize_env(dict(os.environ), extra_env=env)
        handle = self._environment.create_session(
            session_id=session_id,
            cwd=cwd,
            env=sanitized_env,
        )
        self._sessions[session_id] = handle
        return handle

    def _acquire_session(
        self,
        session_id: str,
        *,
        cwd: Path,
        env: dict[str, str],
        invocation: ToolInvocation | None = None,
    ) -> tuple[SessionHandle, str]:
        handle = self._peek_live_session(session_id)
        if handle is not None:
            if invocation is not None:
                self._log_session_binding(
                    invocation=invocation,
                    handle=handle,
                    resolution="reuse",
                    cwd=cwd,
                )
            return handle, "reuse"

        handle = self._create_session(session_id, cwd=cwd, env=env)
        if invocation is not None:
            self._emit_cloud_created(
                invocation=invocation,
                handle=handle,
                cwd=cwd,
            )
            self._log_session_binding(
                invocation=invocation,
                handle=handle,
                resolution="create",
                cwd=cwd,
            )
        return handle, "create"

    def cleanup_session(self, session_id: str) -> bool:
        cleaned = False
        if self._process_manager is not None:
            cleanup_processes = getattr(self._process_manager, "cleanup_session", None)
            if callable(cleanup_processes):
                try:
                    cleaned = bool(cleanup_processes(session_id)) or cleaned
                except Exception:
                    pass

        launcher = self._code_launchers.pop(session_id, None)
        if launcher is not None:
            try:
                launcher.cleanup()
            except Exception:
                pass
            cleaned = True

        handle = self._sessions.pop(session_id, None)
        if handle is not None:
            try:
                self._environment.cleanup(handle)
            except Exception:
                pass
            cleaned = True
        return cleaned

    def cleanup_all_sessions(self) -> None:
        if self._process_manager is not None:
            try:
                self._process_manager.cleanup_all()
            except Exception:
                pass
        for launcher in self._code_launchers.values():
            try:
                launcher.cleanup()
            except Exception:
                pass
        self._code_launchers.clear()
        for handle in self._sessions.values():
            try:
                self._environment.cleanup(handle)
            except Exception:
                pass
        self._sessions.clear()

    def _get_or_create_process_manager(self) -> Any:
        """Lazy-initialize the sandbox process manager."""
        if self._process_manager is not None:
            return self._process_manager
        from .process_manager import SandboxProcessManager
        self._process_manager = SandboxProcessManager(
            config=self._config,
            environment=self._environment,
            security_guard=self._security_guard,
        )
        configure_session_lifecycle = getattr(self._process_manager, "configure_session_lifecycle", None)
        if callable(configure_session_lifecycle):
            configure_session_lifecycle(
                session_provider=lambda session_id, cwd, env: self._acquire_session(
                    session_id,
                    cwd=cwd,
                    env=env,
                )
            )
        return self._process_manager
